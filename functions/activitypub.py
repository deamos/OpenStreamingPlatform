import json
import requests
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from urllib.parse import urlparse
import logging
import uuid
import hashlib
from datetime import datetime

from classes.shared import db
from functions import cachedDbCalls
from classes import activitypub
from conf import config

log = logging.getLogger(__name__)


def get_actor_url(follower):
    """Get the canonical actor URL using WebFinger discovery."""
    try:
        # Try WebFinger first
        webfinger_url = f"https://{follower.domain}/.well-known/webfinger?resource=acct:{follower.username}@{follower.domain}"
        log.debug(f"Trying WebFinger: {webfinger_url}")
        resp = requests.get(webfinger_url, headers={"Accept": "application/jrd+json"}, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            # Look for the ActivityPub actor URL in the links
            for link in data.get('links', []):
                if link.get('type') == 'application/activity+json':
                    actor_url = link.get('href')
                    if actor_url:
                        log.debug(f"Found actor URL via WebFinger: {actor_url}")
                        return actor_url
        
        # Fallback to common patterns
        return try_common_actor_urls(follower)
        
    except Exception as e:
        log.warning(f"WebFinger failed for {follower.username}@{follower.domain}: {e}")
        return try_common_actor_urls(follower)


def try_common_actor_urls(follower):
    """Try common ActivityPub actor URL patterns."""
    patterns = [
        f"https://{follower.domain}/users/{follower.username}",  # Mastodon
        f"https://{follower.domain}/@/{follower.username}",      # Some Mastodon instances
        f"https://{follower.domain}/activitypub/actors/{follower.username}",  # Your format
        f"https://{follower.domain}/actor/{follower.username}",  # Some other platforms
    ]
    
    for url in patterns:
        try:
            log.debug(f"Trying actor URL: {url}")
            resp = requests.get(url, headers={"Accept": "application/activity+json"}, timeout=10)
            if resp.status_code == 200:
                log.debug(f"Found working actor URL: {url}")
                return url
        except Exception as e:
            log.debug(f"Failed to try {url}: {e}")
            continue
    
    return None


class ActivityPubService:
    """Service class for ActivityPub operations"""
    
    def __init__(self, domain):
        self.domain = domain
        # Load configuration
        try:
            from conf import config
            self.config = config
        except ImportError:
            # Fallback to default values if config not available
            self.config = type('Config', (), {
                'activitypubEnabled': True,
                'activitypubMaxRetries': 3,
                'activitypubTimeout': 30,
                'activitypubUserAgent': 'OSP-ActivityPub/1.0',
                'activitypubSignatureAlgorithm': 'rsa-sha256',
                'activitypubDefaultVisibility': 'public'
            })()
    
    def create_user_actor(self, user):
        """Create ActivityPub actor for a user"""
        try:
            # Check if ActivityPub is enabled
            if not getattr(self.config, 'activitypubEnabled', True):
                return None
                
            # Check if actor already exists
            existing_actor = activitypub.ActivityPubActor.query.filter_by(
                user_id=user.id, is_local=True
            ).first()
            
            if existing_actor:
                return existing_actor
            
            # Create new actor
            actor = activitypub.ActivityPubActor(
                actor_type="Person",
                username=user.username,
                domain=self.domain,
                display_name=user.username,
                summary=user.biography or ""
            )
            
            # Generate RSA key pair
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048
            )
            public_key = private_key.public_key()
            
            # Store keys
            actor.private_key_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ).decode('utf-8')
            
            actor.public_key_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode('utf-8')
            
            # Set icon and header URLs
            if user.pictureLocation:
                actor.icon_url = f"https://{self.domain}/images/{user.pictureLocation}"
            if user.bannerLocation:
                actor.header_url = f"https://{self.domain}/images/{user.bannerLocation}"
            
            actor.user_id = user.id
            db.session.add(actor)
            db.session.commit()
            
            return actor
            
        except Exception as e:
            log.error(f"Error creating user actor: {e}")
            db.session.rollback()
            return None
    
    def create_channel_actor(self, channel):
        """Create ActivityPub actor for a channel"""
        try:
            # Check if ActivityPub is enabled
            if not getattr(self.config, 'activitypubEnabled', True):
                return None
                
            # Check if actor already exists
            existing_actor = activitypub.ActivityPubActor.query.filter_by(
                channel_id=channel.id, is_local=True
            ).first()
            
            if existing_actor:
                return existing_actor
            
            # Create new actor
            actor = activitypub.ActivityPubActor(
                actor_type="Group",
                username=channel.channelLoc,
                domain=self.domain,
                display_name=channel.channelName,
                summary=channel.description or ""
            )
            
            # Generate RSA key pair
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048
            )
            public_key = private_key.public_key()
            
            # Store keys
            actor.private_key_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ).decode('utf-8')
            
            actor.public_key_pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode('utf-8')
            
            # Set icon and header URLs
            if channel.imageLocation:
                actor.icon_url = f"https://{self.domain}/images/{channel.imageLocation}"
            if channel.channelBannerLocation:
                actor.header_url = f"https://{self.domain}/images/{channel.channelBannerLocation}"
            
            actor.channel_id = channel.id
            db.session.add(actor)
            db.session.commit()
            
            return actor
            
        except Exception as e:
            log.error(f"Error creating channel actor: {e}")
            db.session.rollback()
            return None
    
    def create_video_object(self, video, actor):
        """Create ActivityPub Video object and a Note for Mastodon"""
        try:
            if not getattr(self.config, 'activitypubEnabled', True):
                return None, None
            existing_object = activitypub.ActivityPubObject.query.filter_by(
                local_object_id=video.id,
                local_object_type='video'
            ).first()
            if existing_object:
                return existing_object, None
            # Create video object data
            video_data = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"https://{self.domain}/activitypub/videos/{video.uuid}",
                "type": "Video",
                "name": video.channelName,
                "summary": video.description or "",
                "content": video.description or "",
                "duration": f"PT{int(video.length)}S" if video.length else None,
                "url": [
                    {"type": "Link", "href": f"https://{self.domain}/play/{video.id}", "mediaType": "text/html"},
                    {"type": "Link", "href": f"https://{self.domain}/videos/{video.videoLocation}", "mediaType": "video/mp4"}
                ],
                "icon": {"type": "Image", "url": f"https://{self.domain}/videos/{video.thumbnailLocation}"} if video.thumbnailLocation else None,
                "attributedTo": f"https://{self.domain}/activitypub/actors/{actor.username}",
                "published": video.videoDate.isoformat(),
                "to": ["https://www.w3.org/ns/activitystreams#Public"],
                "cc": [f"https://{self.domain}/activitypub/actors/{actor.username}/followers"]
            }
            ap_object = activitypub.ActivityPubObject(
                object_type="Video",
                actor_id=actor.id,
                local_object_id=video.id,
                local_object_type='video',
                object_data=video_data
            )
            ap_object.uuid = video.uuid
            db.session.add(ap_object)
            db.session.commit()
            # Create Note object for Mastodon
            note_object = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"https://{self.domain}/activitypub/notes/{video.uuid}",
                "type": "Note",
                "content": f"{video.description or video.channelName} <a href='https://{self.domain}/play/{video.id}'>Watch here</a>",
                "attributedTo": f"https://{self.domain}/activitypub/actors/{actor.username}",
                "attachment": [
                    {
                        "type": "Video",
                        "mediaType": "video/mp4",
                        "url": f"https://{self.domain}/videos/{video.videoLocation}",
                        "icon": {"type": "Image", "url": f"https://{self.domain}/videos/{video.thumbnailLocation}"} if video.thumbnailLocation else None,
                        "name": video.channelName,
                        "summary": video.description or "",
                        "attributedTo": f"https://{self.domain}/activitypub/actors/{actor.username}",
                        "published": video.videoDate.isoformat()
                    }
                ],
                "published": video.videoDate.isoformat(),
                "to": ["https://www.w3.org/ns/activitystreams#Public"],
                "cc": [f"https://{self.domain}/activitypub/actors/{actor.username}/followers"]
            }
            return ap_object, note_object
        except Exception as e:
            log.error(f"Error creating video object: {e}")
            db.session.rollback()
            return None, None
    
    def create_stream_object(self, stream, actor):
        """Create ActivityPub Stream object and a Note for Mastodon"""
        try:
            if not getattr(self.config, 'activitypubEnabled', True):
                return None, None
            existing_object = activitypub.ActivityPubObject.query.filter_by(
                local_object_id=stream.id,
                local_object_type='stream'
            ).first()
            if existing_object:
                return existing_object, None
            channelQuery = cachedDbCalls.getChannel(stream.linkedChannel)
            if channelQuery is None or not hasattr(channelQuery, 'channelLoc'):
                log.error(f"Could not find channel or channelLoc for stream {stream.id}")
                return None, None
            stream_data = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"https://{self.domain}/activitypub/streams/{stream.uuid}",
                "type": "Video",
                "name": stream.streamName,
                "summary": f"Live stream by {actor.display_name}",
                "content": f"Live stream by {actor.display_name}",
                "url": [
                    {"type": "Link", "href": f"https://{self.domain}/view/{channelQuery.channelLoc}", "mediaType": "text/html"},
                    {"type": "Link", "href": f"https://{self.domain}/live/{channelQuery.channelLoc}/index.m3u8", "mediaType": "application/x-mpegURL"}
                ],
                "icon": {"type": "Image", "url": f"https://{self.domain}/stream-thumb/{channelQuery.channelLoc}.png"},
                "attributedTo": f"https://{self.domain}/activitypub/actors/{actor.username}",
                "published": stream.startTimestamp.isoformat(),
                "to": ["https://www.w3.org/ns/activitystreams#Public"],
                "cc": [f"https://{self.domain}/activitypub/actors/{actor.username}/followers"]
            }
            ap_object = activitypub.ActivityPubObject(
                object_type="Video",
                actor_id=actor.id,
                local_object_id=stream.id,
                local_object_type='stream',
                object_data=stream_data
            )
            ap_object.uuid = stream.uuid
            db.session.add(ap_object)
            db.session.commit()
            # Create Note object for Mastodon
            note_object = {
                "@context": "https://www.w3.org/ns/activitystreams",
                "id": f"https://{self.domain}/activitypub/notes/{stream.uuid}",
                "type": "Note",
                "content": f"Live stream by {actor.display_name} <a href='https://{self.domain}/view/{channelQuery.channelLoc}'>Watch here</a>",
                "attributedTo": f"https://{self.domain}/activitypub/actors/{actor.username}",
                "attachment": [
                    {
                        "type": "Video",
                        "mediaType": "application/x-mpegURL",
                        "url": f"https://{self.domain}/live/{channelQuery.channelLoc}/index.m3u8",
                        "icon": {"type": "Image", "url": f"https://{self.domain}/stream-thumb/{channelQuery.channelLoc}.png"},
                        "name": stream.streamName,
                        "summary": f"Live stream by {actor.display_name}",
                        "attributedTo": f"https://{self.domain}/activitypub/actors/{actor.username}",
                        "published": stream.startTimestamp.isoformat()
                    }
                ],
                "published": stream.startTimestamp.isoformat(),
                "to": ["https://www.w3.org/ns/activitystreams#Public"],
                "cc": [f"https://{self.domain}/activitypub/actors/{actor.username}/followers"]
            }
            return ap_object, note_object
        except Exception as e:
            log.error(f"Error creating stream object: {e}")
            db.session.rollback()
            return None, None
    
    def send_activity(self, activity_type, actor, object_data=None, target_id=None, to=None, cc=None):
        """Send ActivityPub activity to remote servers and all followers"""
        try:
            # Check if ActivityPub is enabled
            if not getattr(self.config, 'activitypubEnabled', True):
                return None

            # Ensure object_data is a dict, not a JSON string
            if isinstance(object_data, str):
                try:
                    object_data = json.loads(object_data)
                except Exception:
                    log.error("object_data passed to send_activity is a string but not valid JSON")
                    return None

            # Create activity
            activity = activitypub.ActivityPubActivity(
                activity_type=activity_type,
                actor_id=actor.id,
                object_data=object_data,
                target_id=target_id,
                to=to or ["https://www.w3.org/ns/activitystreams#Public"],
                cc=cc
            )
            db.session.add(activity)
            db.session.commit()

            # Sign the activity
            signed_activity = self._sign_activity(activity)

            # Deliver to all followers' inboxes (in addition to any explicit recipients)
            self._deliver_activity_to_followers_and_recipients(signed_activity, actor)

            return activity

        except Exception as e:
            log.error(f"Error sending activity: {e}")
            db.session.rollback()
            return None
    
    def _sign_activity(self, activity):
        """Sign ActivityPub activity with actor's private key"""
        try:
            # Get actor's private key
            private_key = serialization.load_pem_private_key(
                activity.actor.private_key_pem.encode('utf-8'),
                password=None
            )
            
            # Create signature
            activity_data = json.dumps(activity.to_activitypub(), separators=(',', ':'))
            signature = private_key.sign(
                activity_data.encode('utf-8'),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            
            # Store signature
            activity.signature = base64.b64encode(signature).decode('utf-8')
            db.session.commit()
            
            return activity.to_activitypub()
            
        except Exception as e:
            log.error(f"Error signing activity: {e}")
            return None
    
    def _deliver_activity_to_followers_and_recipients(self, activity_data, actor):
        """Deliver activity to all followers' inboxes and any explicit recipients."""
        # Deliver to explicit recipients (to/cc)
        recipients = []
        if 'to' in activity_data:
            recipients.extend(activity_data['to'])
        if 'cc' in activity_data:
            recipients.extend(activity_data['cc'])
        # Remove duplicates
        recipients = list(set(recipients))
        # Remove #Public and followers collection URLs (we'll handle followers below)
        recipients = [r for r in recipients if not r.endswith('/followers') and r != "https://www.w3.org/ns/activitystreams#Public"]
        self._deliver_activity(activity_data, recipients)
        # Deliver to all followers' inboxes (for local actors only)
        if getattr(actor, 'is_local', True):
            # Find all accepted followers
            follows = activitypub.ActivityPubFollow.query.filter_by(following_id=actor.id, status='accepted').all()
            for follow in follows:
                follower = activitypub.ActivityPubActor.query.filter_by(id=follow.follower_id).first()
                if follower and not follower.is_local:
                    # Get the canonical actor URL using WebFinger discovery
                    actor_url = get_actor_url(follower)
                    if not actor_url:
                        log.warning(f"Could not determine actor URL for {follower.username}@{follower.domain}")
                        continue
                    
                    # Fetch remote actor's inbox URL
                    try:
                        resp = requests.get(actor_url, headers={"Accept": "application/activity+json"}, timeout=10)
                        if resp.status_code == 200:
                            inbox_url = resp.json().get('inbox')
                            if inbox_url:
                                self._send_to_inbox(activity_data, inbox_url, 3, 30, 'OSP-ActivityPub/1.0')
                    except Exception as e:
                        log.warning(f"Failed to deliver to follower {follower.username}@{follower.domain}: {e}")
    
    def _send_to_inbox(self, activity_data, inbox_url, max_retries=3, timeout=30, user_agent='OSP-ActivityPub/1.0'):
        """Send activity to a specific inbox"""
        try:
            # Get actor from activity data
            actor_url = activity_data.get('actor')
            if not actor_url:
                log.error("No actor URL in activity data")
                return
            
            # Extract actor username from URL
            actor_username = actor_url.split('/')[-1]
            actor = activitypub.ActivityPubActor.query.filter_by(
                username=actor_username,
                is_local=True
            ).first()
            
            if not actor:
                log.error(f"Actor not found: {actor_username}")
                return
            
            # Prepare the request body
            body = json.dumps(activity_data, separators=(',', ':')).encode('utf-8')
            digest = base64.b64encode(hashlib.sha256(body).digest()).decode('utf-8')
            digest_header = f"SHA-256={digest}"

            # Generate signature string (now includes digest)
            date = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
            signature_string_parts = [
                f'(request-target): post {urlparse(inbox_url).path}',
                f'host: {urlparse(inbox_url).netloc}',
                f'date: {date}',
                f'digest: {digest_header}',
                'content-type: application/activity+json'
            ]
            signature_string = '\n'.join(signature_string_parts)

            # Add detailed logging for debugging 401 errors
            log.debug("[ActivityPub] Outgoing delivery:")
            log.debug(f"  actor_url: {actor_url}")
            log.debug(f"  inbox_url: {inbox_url}")
            log.debug(f"  signature string: {signature_string}")

            # Sign the string
            private_key = serialization.load_pem_private_key(
                actor.private_key_pem.encode('utf-8'),
                password=None
            )

            signature = private_key.sign(
                signature_string.encode('utf-8'),
                padding.PKCS1v15(),
                hashes.SHA256()
            )

            signature_b64 = base64.b64encode(signature).decode('utf-8')

            # Create signature header (now includes digest)
            signature_header = (
                f'keyId="{actor_url}#main-key",'
                f'algorithm="rsa-sha256",'
                f'headers="(request-target) host date digest content-type",'
                f'signature="{signature_b64}"'
            )

            headers = {
                'Content-Type': 'application/activity+json',
                'User-Agent': user_agent,
                'Date': date,
                'Digest': digest_header,
                'Signature': signature_header
            }

            log.debug(f"  headers: {headers}")
            log.debug(f"  activity_data: {json.dumps(activity_data, indent=2)}")

            response = requests.post(
                inbox_url,
                data=body,
                headers=headers,
                timeout=timeout
            )
            
            if response.status_code in [200, 201, 202]:
                log.info(f"Successfully delivered activity to {inbox_url}")
            else:
                log.warning(f"Failed to deliver activity to {inbox_url}: {response.status_code}")
                
        except Exception as e:
            log.error(f"Error sending to inbox {inbox_url}: {e}")
    
    def handle_incoming_activity(self, activity_data):
        """Handle incoming ActivityPub activity"""
        try:
            # Check if ActivityPub is enabled
            if not getattr(self.config, 'activitypubEnabled', True):
                return

            activity_id = activity_data.get('id')
            if not activity_id:
                log.warning('Incoming activity missing id, ignoring.')
                return
            # Deduplication: check if this activity has already been processed
            existing = activitypub.ActivityPubActivity.query.filter_by(target_id=activity_id).first()
            if existing:
                log.info(f"Duplicate activity {activity_id} ignored.")
                return

            activity_type = activity_data.get('type')
            
            if activity_type == 'Follow':
                self._handle_follow(activity_data)
            elif activity_type == 'Accept':
                self._handle_accept(activity_data)
            elif activity_type == 'Reject':
                self._handle_reject(activity_data)
            elif activity_type == 'Undo':
                self._handle_undo(activity_data)
            elif activity_type == 'Create':
                self._handle_create(activity_data)
            elif activity_type == 'Like':
                self._handle_like(activity_data)
            elif activity_type == 'Announce':
                self._handle_announce(activity_data)
            else:
                log.info(f"Unhandled activity type: {activity_type}")
                
            # Store the incoming activity for deduplication
            actor_url = activity_data.get('actor')
            actor_id = None
            if actor_url:
                username = actor_url.split('/')[-1]
                domain = actor_url.split('/')[2]
                actor = activitypub.ActivityPubActor.query.filter_by(username=username, domain=domain).first()
                if not actor:
                    actor = activitypub.ActivityPubActor(
                        actor_type="Person",
                        username=username,
                        domain=domain
                    )
                    actor.is_local = False
                    db.session.add(actor)
                    db.session.commit()
                actor_id = actor.id

            new_activity = activitypub.ActivityPubActivity(
                activity_type=activity_type,
                actor_id=actor_id,
                object_data=activity_data.get('object'),
                target_id=activity_id
            )
            db.session.add(new_activity)
            db.session.commit()
        except Exception as e:
            log.error(f"Error handling incoming activity: {e}")
    
    def _handle_follow(self, activity_data):
        """Handle Follow activity (auto-accept)"""
        try:
            actor_url = activity_data.get('actor')
            object_url = activity_data.get('object')
            
            # Extract usernames from URLs
            following_username = object_url.split('/')[-1]
            follower_username = actor_url.split('/')[-1]

            # Find local actor being followed
            local_actor = activitypub.ActivityPubActor.query.filter_by(
                username=following_username,
                is_local=True
            ).first()

            # Find or create remote actor (the follower)
            remote_actor = activitypub.ActivityPubActor.query.filter_by(
                username=follower_username,
                is_local=False
            ).first()
            if not remote_actor:
                # Create a minimal remote actor record
                remote_actor = activitypub.ActivityPubActor(
                    actor_type="Person",
                    username=follower_username,
                    domain=actor_url.split('/')[2]  # crude domain extraction
                )
                remote_actor.is_local = False
                db.session.add(remote_actor)
                db.session.commit()

            # Prevent duplicate follows
            existing_follow = activitypub.ActivityPubFollow.query.filter_by(
                follower_id=remote_actor.id,
                following_id=local_actor.id
            ).first()
            if existing_follow and existing_follow.status != 'rejected':
                log.info(f"Duplicate follow from {remote_actor.username} to {local_actor.username} ignored.")
                return

            # Create follow relationship with status 'accepted'
            follow = activitypub.ActivityPubFollow(
                uuid=str(uuid.uuid4()),
                follower_id=remote_actor.id,
                following_id=local_actor.id,
                status='accepted'
            )
            db.session.add(follow)
            db.session.commit()
            
            # Send Accept activity
            self.send_activity(
                activity_type="Accept",
                actor=local_actor,
                object_data=activity_data,
                to=[actor_url]
            )
            
        except Exception as e:
            log.error(f"Error handling follow: {e}")
            db.session.rollback()
    
    def _handle_accept(self, activity_data):
        """Handle Accept activity"""
        try:
            object_data = activity_data.get('object')
            if object_data and object_data.get('type') == 'Follow':
                # Update follow status to accepted
                follow_uuid = object_data.get('id').split('/')[-1]
                follow = activitypub.ActivityPubFollow.query.filter_by(uuid=follow_uuid).first()
                if follow:
                    follow.status = 'accepted'
                    db.session.commit()
                    
        except Exception as e:
            log.error(f"Error handling accept: {e}")
            db.session.rollback()
    
    def _handle_reject(self, activity_data):
        """Handle Reject activity"""
        try:
            object_data = activity_data.get('object')
            if object_data and object_data.get('type') == 'Follow':
                # Update follow status to rejected
                follow_uuid = object_data.get('id').split('/')[-1]
                follow = activitypub.ActivityPubFollow.query.filter_by(uuid=follow_uuid).first()
                if follow:
                    follow.status = 'rejected'
                    db.session.commit()
                    
        except Exception as e:
            log.error(f"Error handling reject: {e}")
            db.session.rollback()
    
    def _handle_undo(self, activity_data):
        """Handle Undo activity (unfollow)"""
        try:
            object_data = activity_data.get('object')
            if object_data and object_data.get('type') == 'Follow':
                # Find the follow relationship and delete it
                actor_url = object_data.get('actor')
                object_url = object_data.get('object')
                # Extract usernames from URLs as in _handle_follow
                following_username = object_url.split('/')[-1]
                follower_username = actor_url.split('/')[-1]
                # Find local actor being followed
                local_actor = activitypub.ActivityPubActor.query.filter_by(
                    username=following_username,
                    is_local=True
                ).first()
                # Find remote actor (follower)
                remote_actor = activitypub.ActivityPubActor.query.filter_by(
                    username=follower_username,
                    is_local=False
                ).first()
                if local_actor and remote_actor:
                    follow = activitypub.ActivityPubFollow.query.filter_by(
                        follower_id=remote_actor.id,
                        following_id=local_actor.id
                    ).first()
                    if follow:
                        db.session.delete(follow)
                        db.session.commit()
        except Exception as e:
            log.error(f"Error handling undo: {e}")
            db.session.rollback()
    
    def _handle_create(self, activity_data):
        """Handle Create activity"""
        try:
            object_data = activity_data.get('object')
            if not object_data:
                return
                
            # Handle Video objects
            if object_data.get('type') == 'Video':
                # Store remote video object
                ap_object = activitypub.ActivityPubObject(
                    object_type="Video",
                    actor_id=None,  # Remote actor
                    local_object_id=None,  # Remote object
                    local_object_type='remote_video',
                    object_data=object_data
                )
                db.session.add(ap_object)
                db.session.commit()
            
            # Handle Note objects (for Mastodon compatibility)
            elif object_data.get('type') == 'Note':
                # Store remote note object
                ap_object = activitypub.ActivityPubObject(
                    object_type="Note",
                    actor_id=None,  # Remote actor
                    local_object_id=None,  # Remote object
                    local_object_type='remote_note',
                    object_data=object_data
                )
                db.session.add(ap_object)
                db.session.commit()
                
        except Exception as e:
            log.error(f"Error handling create: {e}")
            db.session.rollback()
    
    def _handle_like(self, activity_data):
        """Handle Like activity"""
        try:
            # Handle like of local content
            # This would integrate with your existing upvote system
            pass
            
        except Exception as e:
            log.error(f"Error handling like: {e}")
    
    def _handle_announce(self, activity_data):
        """Handle Announce activity (repost/boost)"""
        try:
            # Handle announce of local content
            pass
            
        except Exception as e:
            log.error(f"Error handling announce: {e}")
    
    def get_actor_by_username(self, username):
        """Get ActivityPub actor by username"""
        try:
            # Check if ActivityPub is enabled
            if not getattr(self.config, 'activitypubEnabled', True):
                return None
                
            actor = activitypub.ActivityPubActor.query.filter_by(
                username=username,
                domain=self.domain,
                is_local=True
            ).first()
            
            return actor
            
        except Exception as e:
            log.error(f"Error getting actor by username: {e}")
            return None
    
    def verify_http_signature(self, request, actor_url):
        """Verify HTTP signature for incoming activities"""
        try:
            # Get signature header
            signature_header = request.headers.get('Signature')
            if not signature_header:
                log.warning("No signature header found")
                return False

            # Add detailed logging for debugging signature verification
            log.debug("[ActivityPub] Incoming signature verification:")
            log.debug(f"  actor_url: {actor_url}")
            log.debug(f"  signature header: {signature_header}")
            log.debug(f"  request headers: {dict(request.headers)}")

            # Parse signature header
            signature_parts = {}
            for part in signature_header.split(','):
                if '=' in part:
                    key, value = part.split('=', 1)
                    signature_parts[key.strip()] = value.strip().strip('"')

            # Extract required parts
            key_id = signature_parts.get('keyId')
            algorithm = signature_parts.get('algorithm')
            headers = signature_parts.get('headers', '').split(' ')
            signature = signature_parts.get('signature')

            if not all([key_id, algorithm, signature]):
                log.warning("Missing required signature parts")
                return False

            # Get actor's public key
            # Use Accept: application/activity+json to ensure we get ActivityPub JSON, not HTML
            actor_response = requests.get(actor_url, timeout=10, headers={"Accept": "application/activity+json"})
            log.debug(f"  actor_response.status_code: {actor_response.status_code}")
            log.debug(f"  actor_response.content: {actor_response.text}")
            if actor_response.status_code != 200:
                log.warning(f"Failed to fetch actor: {actor_url} (status {actor_response.status_code}) Content: {actor_response.text}")
                return False
            try:
                actor_data = actor_response.json()
            except Exception as e:
                log.warning(f"Failed to parse actor JSON from {actor_url}: {e} -- Content: {actor_response.text}")
                return False
            public_key_pem = actor_data.get('publicKey', {}).get('publicKeyPem')
            if not public_key_pem:
                log.warning("No public key found in actor data")
                return False

            # Load public key
            public_key = serialization.load_pem_public_key(
                public_key_pem.encode('utf-8')
            )

            # Build signature string
            signature_string_parts = []
            for header_name in headers:
                if header_name == '(request-target)':
                    signature_string_parts.append(f'(request-target): post {request.path}')
                elif header_name == 'host':
                    signature_string_parts.append(f'host: {request.host}')
                elif header_name == 'date':
                    signature_string_parts.append(f'date: {request.headers.get("Date", "")}')
                elif header_name == 'content-type':
                    signature_string_parts.append(f'content-type: {request.headers.get("Content-Type", "")}')
                else:
                    signature_string_parts.append(f'{header_name}: {request.headers.get(header_name, "")}')

            signature_string = '\n'.join(signature_string_parts)
            log.debug(f"  signature string: {signature_string}")

            # Verify signature
            try:
                if signature is None:
                    log.warning("Signature value is None, cannot verify.")
                    return False
                signature_bytes = base64.b64decode(signature)
                public_key.verify(
                    signature_bytes,
                    signature_string.encode('utf-8'),
                    padding.PKCS1v15(),
                    hashes.SHA256()
                )
                log.info(f"Signature verified for {actor_url}")
                return True
            except Exception as e:
                log.warning(f"Signature verification failed: {e}")
                return False
                
        except Exception as e:
            log.error(f"Error verifying signature: {e}")
            return False

    def _deliver_activity(self, activity_data, recipients):
        """Deliver activity to remote servers"""
        max_retries = getattr(self.config, 'activitypubMaxRetries', 3)
        timeout = getattr(self.config, 'activitypubTimeout', 30)
        user_agent = getattr(self.config, 'activitypubUserAgent', 'OSP-ActivityPub/1.0')

        # Ensure recipients is a list, not a string
        if isinstance(recipients, str):
            try:
                recipients = json.loads(recipients)
            except Exception:
                recipients = [recipients]

        for recipient in recipients:
            if recipient == "https://www.w3.org/ns/activitystreams#Public":
                continue  # Skip public recipient
            try:
                parsed_url = urlparse(recipient)
                if parsed_url.path.endswith('/followers'):
                    # Extract actor URL from followers URL
                    actor_url = recipient.replace('/followers', '')
                    # Get actor's inbox
                    response = requests.get(actor_url, timeout=timeout, headers={"Accept": "application/activity+json"})
                    if response.status_code == 200:
                        actor_data = response.json()
                        inbox_url = actor_data.get('inbox')
                        if inbox_url:
                            self._send_to_inbox(activity_data, inbox_url, max_retries, timeout, user_agent)
                elif not parsed_url.path.endswith('/inbox'):
                    # If it's an actor profile, fetch their inbox
                    response = requests.get(recipient, timeout=timeout, headers={"Accept": "application/activity+json"})
                    if response.status_code == 200:
                        actor_data = response.json()
                        inbox_url = actor_data.get('inbox')
                        if inbox_url:
                            self._send_to_inbox(activity_data, inbox_url, max_retries, timeout, user_agent)
                else:
                    # It's already an inbox URL
                    self._send_to_inbox(activity_data, recipient, max_retries, timeout, user_agent)
            except Exception as e:
                log.error(f"Error delivering to {recipient}: {e}")


# Global ActivityPub service instance
activitypub_service = None


def init_activitypub_service(domain):
    """Initialize global ActivityPub service"""
    global activitypub_service
    activitypub_service = ActivityPubService(domain)


def get_activitypub_service():
    """Get global ActivityPub service instance"""
    return activitypub_service


def create_activitypub_actor_for_user(user):
    """Helper function to create ActivityPub actor for a user"""
    try:
        service = get_activitypub_service()
        if service:
            return service.create_user_actor(user)
        return None
    except Exception as e:
        log.error(f"Error creating ActivityPub actor for user {user.username}: {e}")
        return None 