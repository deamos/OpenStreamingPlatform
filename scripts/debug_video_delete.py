#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gevent import monkey
monkey.patch_all(thread=True)

from app import app
from classes import activitypub
from classes.shared import db
from conf import config
from functions.activitypub import get_activitypub_service
from functions import cachedDbCalls

def debug_video_delete(video_id):
    """Debug why ActivityPub delete isn't working for a video"""
    with app.app_context():
        print(f"[DEBUG] Investigating video delete for video ID: {video_id}")
        
        # Check if ActivityPub is enabled
        activitypub_enabled = getattr(config, 'activitypubEnabled', False)
        print(f"[DEBUG] ActivityPub enabled: {activitypub_enabled}")
        
        if not activitypub_enabled:
            print("[ERROR] ActivityPub is not enabled in config")
            return
        
        # Get the video
        video = cachedDbCalls.getVideo(video_id)
        if not video:
            print(f"[ERROR] Video {video_id} not found")
            return
        
        print(f"[DEBUG] Found video: {video.channelName} (ID: {video.id})")
        
        # Get the user
        user = cachedDbCalls.getUser(video.owningUser)
        if not user:
            print(f"[ERROR] User {video.owningUser} not found")
            return
        
        print(f"[DEBUG] Found user: {user.username} (ID: {user.id})")
        
        # Get ActivityPub service
        service = get_activitypub_service()
        if not service:
            print("[ERROR] Could not get ActivityPub service")
            return
        
        print(f"[DEBUG] ActivityPub service domain: {service.domain}")
        
        # Create/get actor
        actor = service.create_user_actor(user)
        if not actor:
            print("[ERROR] Could not create/get user actor")
            return
        
        print(f"[DEBUG] Found actor: {actor.username}@{actor.domain} (ID: {actor.id})")
        
        # Check for existing ActivityPub object
        ap_object = activitypub.ActivityPubObject.query.filter_by(
            local_object_id=video_id,
            local_object_type='video'
        ).first()
        
        if ap_object:
            print(f"[DEBUG] Found ActivityPub object: {ap_object.uuid} (ID: {ap_object.id})")
            print(f"[DEBUG] Object data: {ap_object.object_data}")
        else:
            print(f"[WARN] No ActivityPub object found for video {video_id}")
        
        # Check for followers
        follows = activitypub.ActivityPubFollow.query.filter_by(
            following_id=actor.id, 
            status='accepted'
        ).all()
        
        print(f"[DEBUG] Found {len(follows)} accepted followers")
        
        for follow in follows:
            follower = activitypub.ActivityPubActor.query.filter_by(id=follow.follower_id).first()
            if follower:
                print(f"[DEBUG] Follower: {follower.username}@{follower.domain} (local: {follower.is_local})")
        
        # Try to send delete activity
        print(f"[DEBUG] Attempting to send delete activity...")
        try:
            result = service.delete_video_object(video_id, actor)
            if result:
                print(f"[SUCCESS] Delete activity sent successfully")
                print(f"[DEBUG] Activity ID: {result.id}")
                print(f"[DEBUG] Activity delivered: {result.delivered}")
            else:
                print(f"[ERROR] Delete activity returned None")
        except Exception as e:
            print(f"[ERROR] Exception sending delete activity: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python debug_video_delete.py <video_id>")
        sys.exit(1)
    
    video_id = int(sys.argv[1])
    debug_video_delete(video_id) 