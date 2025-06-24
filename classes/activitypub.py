from .shared import db
from datetime import datetime
import json
import uuid


class ActivityPubActor(db.Model):
    """ActivityPub Actor representation for Users and Channels"""
    __tablename__ = "activitypub_actors"
    
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(255), unique=True, nullable=False)
    actor_type = db.Column(db.String(50), nullable=False)  # 'Person' or 'Group'
    username = db.Column(db.String(255), unique=True, nullable=False)
    domain = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(255))
    summary = db.Column(db.Text)
    icon_url = db.Column(db.String(1024))
    header_url = db.Column(db.String(1024))
    inbox_url = db.Column(db.String(1024))
    outbox_url = db.Column(db.String(1024))
    followers_url = db.Column(db.String(1024))
    following_url = db.Column(db.String(1024))
    public_key_pem = db.Column(db.Text)
    private_key_pem = db.Column(db.Text)
    is_local = db.Column(db.Boolean, default=True)
    is_public = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Foreign key relationships
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('Channel.id'), nullable=True)
    
    def __init__(self, actor_type, username, domain, display_name=None, summary=None):
        self.uuid = str(uuid.uuid4())
        self.actor_type = actor_type
        self.username = username
        self.domain = domain
        self.display_name = display_name
        self.summary = summary
        self.inbox_url = f"https://{domain}/activitypub/actors/{username}/inbox"
        self.outbox_url = f"https://{domain}/activitypub/actors/{username}/outbox"
        self.followers_url = f"https://{domain}/activitypub/actors/{username}/followers"
        self.following_url = f"https://{domain}/activitypub/actors/{username}/following"
    
    def to_activitypub(self):
        """Convert to ActivityPub Actor object"""
        return {
            "@context": [
                "https://www.w3.org/ns/activitystreams",
                "https://w3id.org/security/v1"
            ],
            "id": f"https://{self.domain}/activitypub/actors/{self.username}",
            "type": self.actor_type,
            "preferredUsername": self.username,
            "name": self.display_name or self.username,
            "summary": self.summary or "",
            "icon": {
                "type": "Image",
                "url": self.icon_url
            } if self.icon_url else None,
            "image": {
                "type": "Image", 
                "url": self.header_url
            } if self.header_url else None,
            "inbox": self.inbox_url,
            "outbox": self.outbox_url,
            "followers": self.followers_url,
            "following": self.following_url,
            "publicKey": {
                "id": f"https://{self.domain}/activitypub/actors/{self.username}#main-key",
                "owner": f"https://{self.domain}/activitypub/actors/{self.username}",
                "publicKeyPem": self.public_key_pem
            } if self.public_key_pem else None,
            "published": self.created_at.isoformat(),
            "updated": self.updated_at.isoformat()
        }


class ActivityPubActivity(db.Model):
    """ActivityPub Activity objects"""
    __tablename__ = "activitypub_activities"
    
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(255), unique=True, nullable=False)
    activity_type = db.Column(db.String(50), nullable=False)  # Create, Follow, Like, etc.
    actor_id = db.Column(db.Integer, db.ForeignKey('activitypub_actors.id'), nullable=False)
    object_data = db.Column(db.Text)  # JSON serialized object
    target_id = db.Column(db.String(1024))  # Target actor or object URL
    to = db.Column(db.Text)  # JSON array of recipients
    cc = db.Column(db.Text)  # JSON array of CC recipients
    signature = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    delivered = db.Column(db.Boolean, default=False)
    
    # Relationships
    actor = db.relationship('ActivityPubActor', backref='activities')
    
    def __init__(self, activity_type, actor_id, object_data=None, target_id=None, to=None, cc=None):
        self.uuid = str(uuid.uuid4())
        self.activity_type = activity_type
        self.actor_id = actor_id
        self.object_data = json.dumps(object_data) if object_data else None
        self.target_id = target_id
        self.to = json.dumps(to) if to else None
        self.cc = json.dumps(cc) if cc else None
    
    def to_activitypub(self):
        """Convert to ActivityPub Activity object"""
        activity = {
            "@context": "https://www.w3.org/ns/activitystreams",
            "id": f"https://{self.actor.domain}/activitypub/activities/{self.uuid}",
            "type": self.activity_type,
            "actor": f"https://{self.actor.domain}/activitypub/actors/{self.actor.username}",
            "published": self.created_at.isoformat()
        }
        
        if self.object_data:
            activity["object"] = json.loads(self.object_data)
        
        if self.target_id:
            activity["target"] = self.target_id
            
        if self.to:
            activity["to"] = json.loads(self.to)
            
        if self.cc:
            activity["cc"] = json.loads(self.cc)
            
        return activity


class ActivityPubFollow(db.Model):
    """Follow relationships between actors"""
    __tablename__ = "activitypub_follows"
    
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(255), unique=True, nullable=False)
    follower_id = db.Column(db.Integer, db.ForeignKey('activitypub_actors.id'), nullable=False)
    following_id = db.Column(db.Integer, db.ForeignKey('activitypub_actors.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    follower = db.relationship('ActivityPubActor', foreign_keys=[follower_id], backref='following')
    following = db.relationship('ActivityPubActor', foreign_keys=[following_id], backref='followers')


class ActivityPubObject(db.Model):
    """ActivityPub Object representations (Videos, Streams, etc.)"""
    __tablename__ = "activitypub_objects"
    
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(255), unique=True, nullable=False)
    object_type = db.Column(db.String(50), nullable=False)  # Video, Stream, etc.
    actor_id = db.Column(db.Integer, db.ForeignKey('activitypub_actors.id'), nullable=False)
    local_object_id = db.Column(db.Integer)  # ID of local object (video_id, stream_id, etc.)
    local_object_type = db.Column(db.String(50))  # 'video', 'stream', etc.
    object_data = db.Column(db.Text)  # JSON serialized object
    published = db.Column(db.DateTime, default=datetime.utcnow)
    updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    actor = db.relationship('ActivityPubActor', backref='objects')
    
    def __init__(self, object_type, actor_id, local_object_id, local_object_type, object_data):
        self.uuid = str(uuid.uuid4())
        self.object_type = object_type
        self.actor_id = actor_id
        self.local_object_id = local_object_id
        self.local_object_type = local_object_type
        self.object_data = json.dumps(object_data) if object_data else None
    
    def to_activitypub(self):
        """Convert to ActivityPub Object"""
        return json.loads(self.object_data) if self.object_data else {} 