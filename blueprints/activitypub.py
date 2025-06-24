from flask import Blueprint, request, jsonify, current_app
from flask_security import current_user
import logging

from classes import activitypub
from classes import Sec
from functions.activitypub import get_activitypub_service

log = logging.getLogger("app.blueprints.activitypub")

activitypub_bp = Blueprint("activitypub", __name__, url_prefix="/activitypub")

# Create a separate blueprint for discovery endpoints at root level
discovery_bp = Blueprint("discovery", __name__)


@discovery_bp.route("/.well-known/webfinger")
def webfinger():
    """WebFinger endpoint for ActivityPub discovery"""
    try:
        resource = request.args.get('resource')
        if not resource:
            return jsonify({"error": "Missing resource parameter"}), 400
        
        # Parse resource (e.g., "acct:user@domain.com")
        if resource.startswith('acct:'):
            username = resource[5:].split('@')[0]
            domain = resource[5:].split('@')[1]
        else:
            return jsonify({"error": "Invalid resource format"}), 400
        
        # Find actor
        actor = activitypub.ActivityPubActor.query.filter_by(
            username=username,
            domain=domain
        ).first()
        
        if not actor:
            return jsonify({"error": "Actor not found"}), 404
        
        # Return WebFinger response
        response = {
            "subject": resource,
            "links": [
                {
                    "rel": "self",
                    "type": "application/activity+json",
                    "href": f"https://{domain}/activitypub/actors/{username}"
                },
                {
                    "rel": "http://webfinger.net/rel/profile-page",
                    "type": "text/html",
                    "href": f"https://{domain}/profile/{username}"
                }
            ]
        }
        
        return jsonify(response)
        
    except Exception as e:
        log.error(f"WebFinger error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@discovery_bp.route("/.well-known/nodeinfo")
def nodeinfo_discovery():
    """NodeInfo discovery endpoint"""
    try:
        response = {
            "links": [
                {
                    "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                    "href": f"https://{request.host}/nodeinfo/2.0"
                }
            ]
        }
        return jsonify(response)
        
    except Exception as e:
        log.error(f"NodeInfo discovery error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@discovery_bp.route("/nodeinfo/2.0")
def nodeinfo():
    """NodeInfo 2.0 endpoint"""
    try:
        response = {
            "version": "2.0",
            "software": {
                "name": "Open Streaming Platform",
                "version": "1.0.0"
            },
            "protocols": ["activitypub"],
            "services": {
                "inbound": [],
                "outbound": ["activitypub"]
            },
            "openRegistrations": True,
            "usage": {
                "users": {
                    "total": Sec.User.query.count()
                },
                "localPosts": activitypub.ActivityPubActivity.query.count()
            },
            "metadata": {
                "nodeName": getattr(current_app.config, 'activitypubSiteName', 'Open Streaming Platform'),
                "nodeDescription": getattr(current_app.config, 'activitypubSiteDescription', 'Federated Video Streaming Platform')
            }
        }
        return jsonify(response)
        
    except Exception as e:
        log.error(f"NodeInfo error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@activitypub_bp.route("/actors/<username>")
def actor(username):
    """Get ActivityPub actor information"""
    try:
        actor = activitypub.ActivityPubActor.query.filter_by(
            username=username,
            is_local=True
        ).first()
        
        if not actor:
            return jsonify({"error": "Actor not found"}), 404
        
        return jsonify(actor.to_activitypub())
        
    except Exception as e:
        log.error(f"Actor endpoint error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@activitypub_bp.route("/actors/<username>/inbox", methods=['POST'])
def inbox(username):
    """Handle incoming ActivityPub activities"""
    try:
        # Verify actor exists
        actor = activitypub.ActivityPubActor.query.filter_by(
            username=username,
            is_local=True
        ).first()
        
        if not actor:
            return jsonify({"error": "Actor not found"}), 404
        
        # Get activity data
        activity_data = request.get_json()
        if not activity_data:
            return jsonify({"error": "No activity data"}), 400
        
        # Verify HTTP signature
        service = get_activitypub_service()
        if service:
            # Extract actor URL from activity
            actor_url = activity_data.get('actor')
            if not actor_url:
                return jsonify({"error": "No actor URL in activity"}), 400
            
            # Verify signature
            if not service.verify_http_signature(request, actor_url):
                log.warning(f"Signature verification failed for {actor_url}")
                return jsonify({"error": "Invalid signature"}), 401
            
            # Handle the activity
            service.handle_incoming_activity(activity_data)
        
        return jsonify({"status": "ok"}), 202
        
    except Exception as e:
        log.error(f"Inbox error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@activitypub_bp.route("/actors/<username>/outbox")
def outbox(username):
    """Get ActivityPub actor's outbox"""
    try:
        actor = activitypub.ActivityPubActor.query.filter_by(
            username=username,
            is_local=True
        ).first()
        
        if not actor:
            return jsonify({"error": "Actor not found"}), 404
        
        # Get activities
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)
        
        activities = activitypub.ActivityPubActivity.query.filter_by(
            actor_id=actor.id
        ).order_by(
            activitypub.ActivityPubActivity.created_at.desc()
        ).paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
        
        # Build response
        response = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"https://{actor.domain}/activitypub/actors/{username}/outbox",
            "type": "OrderedCollection",
            "totalItems": activities.total,
            "orderedItems": [activity.to_activitypub() for activity in activities.items]
        }
        
        return jsonify(response)
        
    except Exception as e:
        log.error(f"Outbox error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@activitypub_bp.route("/actors/<username>/followers")
def followers(username):
    """Get ActivityPub actor's followers"""
    try:
        actor = activitypub.ActivityPubActor.query.filter_by(
            username=username,
            is_local=True
        ).first()
        
        if not actor:
            return jsonify({"error": "Actor not found"}), 404
        
        # Get followers
        follows = activitypub.ActivityPubFollow.query.filter_by(
            following_id=actor.id,
            status='accepted'
        ).all()
        
        # Build response
        response = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"https://{actor.domain}/activitypub/actors/{username}/followers",
            "type": "OrderedCollection",
            "totalItems": len(follows),
            "orderedItems": [
                f"https://{follow.follower.domain}/activitypub/actors/{follow.follower.username}"
                for follow in follows
            ]
        }
        
        return jsonify(response)
        
    except Exception as e:
        log.error(f"Followers error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@activitypub_bp.route("/actors/<username>/following")
def following(username):
    """Get ActivityPub actor's following"""
    try:
        actor = activitypub.ActivityPubActor.query.filter_by(
            username=username,
            is_local=True
        ).first()
        
        if not actor:
            return jsonify({"error": "Actor not found"}), 404
        
        # Get following
        follows = activitypub.ActivityPubFollow.query.filter_by(
            follower_id=actor.id,
            status='accepted'
        ).all()
        
        # Build response
        response = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"https://{actor.domain}/activitypub/actors/{username}/following",
            "type": "OrderedCollection",
            "totalItems": len(follows),
            "orderedItems": [
                f"https://{follow.following.domain}/activitypub/actors/{follow.following.username}"
                for follow in follows
            ]
        }
        
        return jsonify(response)
        
    except Exception as e:
        log.error(f"Following error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@activitypub_bp.route("/videos/<video_uuid>")
def video(video_uuid):
    """Get ActivityPub video object"""
    try:
        ap_object = activitypub.ActivityPubObject.query.filter_by(
            uuid=video_uuid,
            local_object_type='video'
        ).first()
        
        if not ap_object:
            return jsonify({"error": "Video not found"}), 404
        
        return jsonify(ap_object.to_activitypub())
        
    except Exception as e:
        log.error(f"Video endpoint error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@activitypub_bp.route("/streams/<stream_uuid>")
def stream(stream_uuid):
    """Get ActivityPub stream object"""
    try:
        ap_object = activitypub.ActivityPubObject.query.filter_by(
            uuid=stream_uuid,
            local_object_type='stream'
        ).first()
        
        if not ap_object:
            return jsonify({"error": "Stream not found"}), 404
        
        return jsonify(ap_object.to_activitypub())
        
    except Exception as e:
        log.error(f"Stream endpoint error: {e}")
        return jsonify({"error": "Internal server error"}), 500


# Admin endpoints for managing ActivityPub
@activitypub_bp.route("/admin/actors")
def admin_actors():
    """Admin endpoint to list all actors"""
    try:
        if not current_user.is_authenticated or not current_user.has_role('Admin'):
            return jsonify({"error": "Unauthorized"}), 401
        
        actors = activitypub.ActivityPubActor.query.all()
        
        return jsonify({
            "actors": [
                {
                    "id": actor.id,
                    "username": actor.username,
                    "actor_type": actor.actor_type,
                    "is_local": actor.is_local,
                    "created_at": actor.created_at.isoformat()
                }
                for actor in actors
            ]
        })
        
    except Exception as e:
        log.error(f"Admin actors error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@activitypub_bp.route("/admin/activities")
def admin_activities():
    """Admin endpoint to list recent activities"""
    try:
        if not current_user.is_authenticated or not current_user.has_role('Admin'):
            return jsonify({"error": "Unauthorized"}), 401
        
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)
        
        activities = activitypub.ActivityPubActivity.query.order_by(
            activitypub.ActivityPubActivity.created_at.desc()
        ).paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
        
        return jsonify({
            "activities": [
                {
                    "id": activity.id,
                    "type": activity.activity_type,
                    "actor": activity.actor.username if activity.actor else None,
                    "created_at": activity.created_at.isoformat(),
                    "delivered": activity.delivered
                }
                for activity in activities.items
            ],
            "pagination": {
                "page": activities.page,
                "pages": activities.pages,
                "per_page": activities.per_page,
                "total": activities.total
            }
        })
        
    except Exception as e:
        log.error(f"Admin activities error: {e}")
        return jsonify({"error": "Internal server error"}), 500 