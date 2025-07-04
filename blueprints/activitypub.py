from flask import Blueprint, request, jsonify, current_app, Response
from flask_security import current_user
import logging
import json

from classes import activitypub
from classes import Sec
from functions.activitypub import get_activitypub_service

log = logging.getLogger("app.blueprints.activitypub")

activitypub_bp = Blueprint("activitypub", __name__, url_prefix="/activitypub")

# Create a separate blueprint for discovery endpoints at root level
discovery_bp = Blueprint("discovery", __name__)

default_error_response = {"error": "Internal server error"}


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
        return jsonify(default_error_response), 500


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
        return jsonify(default_error_response), 500


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
        return jsonify(default_error_response), 500


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
        
        return Response(
            json.dumps(actor.to_activitypub()),
            mimetype='application/activity+json'
        )
        
    except Exception as e:
        log.error(f"Actor endpoint error: {e}")
        return jsonify(default_error_response), 500


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
        return jsonify(default_error_response), 500


@activitypub_bp.route("/actors/<username>/outbox")
def outbox(username):
    """Get ActivityPub actor's outbox with proper ActivityPub paging support"""
    try:
        actor = activitypub.ActivityPubActor.query.filter_by(
            username=username,
            is_local=True
        ).first()
        
        if not actor:
            return jsonify({"error": "Actor not found"}), 404
        
        page = request.args.get('page', type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)
        base_url = f"https://{actor.domain}/activitypub/actors/{username}/outbox"
        
        # Include all Delete activities, and Create activities for Note, Video, or Article
        activity_types = ["Create", "Delete"]
        post_types = ["Note", "Video", "Article"]
        post_activities_query = activitypub.ActivityPubActivity.query.filter(
            activitypub.ActivityPubActivity.actor_id == actor.id,
            activitypub.ActivityPubActivity.activity_type.in_(activity_types)
        )
        post_activities = []
        for a in post_activities_query:
            if a.activity_type == "Create":
                data = a.object_data
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except Exception:
                        continue
                if data and data.get("type") in post_types:
                    post_activities.append(a)
            elif a.activity_type == "Delete":
                post_activities.append(a)
        
        if page is None:
            # Return OrderedCollection with 'first' field
            total = len(post_activities)
            response = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": base_url,
                "type": "OrderedCollection",
                "totalItems": total,
                "first": f"{base_url}?page=1"
            }
            return Response(
                json.dumps(response),
                mimetype='application/activity+json'
            )
        else:
            # Return OrderedCollectionPage
            start = (page - 1) * per_page
            end = start + per_page
            items = [activity.to_activitypub() for activity in post_activities[start:end]]
            response = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{base_url}?page={page}",
                "type": "OrderedCollectionPage",
                "partOf": base_url,
                "orderedItems": items
            }
            if end < len(post_activities):
                response["next"] = f"{base_url}?page={page+1}"
            if start > 0:
                response["prev"] = f"{base_url}?page={page-1}"
            return Response(
                json.dumps(response),
                mimetype='application/activity+json'
            )
    except Exception as e:
        log.error(f"Outbox error: {e}")
        return jsonify(default_error_response), 500


@activitypub_bp.route("/actors/<username>/followers")
def followers(username):
    """Get ActivityPub actor's followers with paging support"""
    try:
        actor = activitypub.ActivityPubActor.query.filter_by(
            username=username,
            is_local=True
        ).first()
        
        if not actor:
            return jsonify({"error": "Actor not found"}), 404
        
        page = request.args.get('page', type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)
        base_url = f"https://{actor.domain}/activitypub/actors/{username}/followers"
        
        if page is None:
            total = activitypub.ActivityPubFollow.query.filter_by(
                following_id=actor.id,
                status='accepted'
            ).count()
            response = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": base_url,
                "type": "OrderedCollection",
                "totalItems": total,
                "first": f"{base_url}?page=1"
            }
            return Response(
                json.dumps(response),
                mimetype='application/activity+json'
            )
        else:
            follows = activitypub.ActivityPubFollow.query.filter_by(
                following_id=actor.id,
                status='accepted'
            ).order_by(activitypub.ActivityPubFollow.created_at.desc()).paginate(
                page=page,
                per_page=per_page,
                error_out=False
            )
            items = [
                follower.canonical_url if getattr(follower, 'canonical_url', None)
                else f"https://{follower.domain}/activitypub/actors/{follower.username}"
                for follower in (activitypub.ActivityPubActor.query.filter_by(id=follow.follower_id).first() for follow in follows.items)
                if follower is not None
            ]
            response = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{base_url}?page={page}",
                "type": "OrderedCollectionPage",
                "partOf": base_url,
                "orderedItems": items
            }
            if follows.has_next:
                response["next"] = f"{base_url}?page={follows.next_num}"
            if follows.has_prev:
                response["prev"] = f"{base_url}?page={follows.prev_num}"
            return Response(
                json.dumps(response),
                mimetype='application/activity+json'
            )
    except Exception as e:
        log.error(f"Followers error: {e}")
        return jsonify(default_error_response), 500


@activitypub_bp.route("/actors/<username>/following")
def following(username):
    """Get ActivityPub actor's following with paging support"""
    try:
        actor = activitypub.ActivityPubActor.query.filter_by(
            username=username,
            is_local=True
        ).first()
        
        if not actor:
            return jsonify({"error": "Actor not found"}), 404
        
        page = request.args.get('page', type=int)
        per_page = min(request.args.get('per_page', 20, type=int), 100)
        base_url = f"https://{actor.domain}/activitypub/actors/{username}/following"
        
        if page is None:
            total = activitypub.ActivityPubFollow.query.filter_by(
                follower_id=actor.id,
                status='accepted'
            ).count()
            response = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": base_url,
                "type": "OrderedCollection",
                "totalItems": total,
                "first": f"{base_url}?page=1"
            }
            return Response(
                json.dumps(response),
                mimetype='application/activity+json'
            )
        else:
            follows = activitypub.ActivityPubFollow.query.filter_by(
                follower_id=actor.id,
                status='accepted'
            ).order_by(activitypub.ActivityPubFollow.created_at.desc()).paginate(
                page=page,
                per_page=per_page,
                error_out=False
            )
            items = [
                f"https://{follow.following.domain}/activitypub/actors/{follow.following.username}"
                for follow in follows.items
            ]
            response = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"{base_url}?page={page}",
                "type": "OrderedCollectionPage",
                "partOf": base_url,
                "orderedItems": items
            }
            if follows.has_next:
                response["next"] = f"{base_url}?page={follows.next_num}"
            if follows.has_prev:
                response["prev"] = f"{base_url}?page={follows.prev_num}"
            return Response(
                json.dumps(response),
                mimetype='application/activity+json'
            )
    except Exception as e:
        log.error(f"Following error: {e}")
        return jsonify(default_error_response), 500


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
        
        return Response(
            json.dumps(ap_object.to_activitypub()),
            mimetype='application/activity+json'
        )
        
    except Exception as e:
        log.error(f"Video endpoint error: {e}")
        return jsonify(default_error_response), 500


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
        
        return Response(
            json.dumps(ap_object.to_activitypub()),
            mimetype='application/activity+json'
        )
        
    except Exception as e:
        log.error(f"Stream endpoint error: {e}")
        return jsonify(default_error_response), 500


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
        return jsonify(default_error_response), 500


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
        return jsonify(default_error_response), 500


@activitypub_bp.route("/activities/<activity_uuid>")
def activity(activity_uuid):
    """Get ActivityPub activity object"""
    try:
        ap_activity = activitypub.ActivityPubActivity.query.filter_by(uuid=activity_uuid).first()
        if not ap_activity:
            return jsonify({"error": "Activity not found"}), 404
        # Ensure full ActivityPub context is present
        activity_obj = ap_activity.to_activitypub()
        if "@context" not in activity_obj:
            activity_obj["@context"] = "https://www.w3.org/ns/activitystreams"
        return Response(
            json.dumps(activity_obj),
            mimetype='application/activity+json'
        )
    except Exception as e:
        log.error(f"Activity endpoint error: {e}")
        return jsonify(default_error_response), 500 