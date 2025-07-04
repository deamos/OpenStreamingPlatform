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
import json

def debug_delete_activity(activity_id):
    """Debug a specific delete activity"""
    with app.app_context():
        print(f"[DEBUG] Investigating delete activity ID: {activity_id}")
        
        # Get the activity
        activity = activitypub.ActivityPubActivity.query.filter_by(id=activity_id).first()
        if not activity:
            print(f"[ERROR] Activity {activity_id} not found")
            return
        
        print(f"[DEBUG] Found activity:")
        print(f"  Type: {activity.activity_type}")
        print(f"  Actor ID: {activity.actor_id}")
        print(f"  Delivered: {activity.delivered}")
        print(f"  Created: {activity.created_at}")
        
        # Get the actor
        actor = activitypub.ActivityPubActor.query.filter_by(id=activity.actor_id).first()
        if actor:
            print(f"  Actor: {actor.username}@{actor.domain}")
        
        # Get the object data
        if activity.object_data:
            try:
                object_data = json.loads(activity.object_data) if isinstance(activity.object_data, str) else activity.object_data
                print(f"[DEBUG] Object data:")
                print(json.dumps(object_data, indent=2))
                
                # Check if this is a proper delete activity
                if object_data.get('type') == 'Delete':
                    print(f"[DEBUG] This is a Delete activity")
                    print(f"  Object being deleted: {object_data.get('object')}")
                    print(f"  Actor: {object_data.get('actor')}")
                    print(f"  ID: {object_data.get('id')}")
                    
                    # Check if the object URL matches the expected format
                    object_url = object_data.get('object')
                    if object_url:
                        print(f"[DEBUG] Object URL: {object_url}")
                        # Check if this URL would match what Mastodon expects
                        if '/activitypub/videos/' in object_url:
                            print(f"[DEBUG] Object URL contains /activitypub/videos/ - this should work")
                        else:
                            print(f"[WARN] Object URL doesn't contain /activitypub/videos/ - this might be the issue")
                else:
                    print(f"[WARN] Activity type is not 'Delete': {object_data.get('type')}")
                    
            except Exception as e:
                print(f"[ERROR] Failed to parse object data: {e}")
                print(f"Raw object data: {activity.object_data}")
        else:
            print(f"[WARN] No object data found")
        
        # Check if there are any related objects
        print(f"[DEBUG] Checking for related ActivityPub objects...")
        related_objects = activitypub.ActivityPubObject.query.filter_by(
            actor_id=activity.actor_id
        ).all()
        
        print(f"[DEBUG] Found {len(related_objects)} related objects for this actor")
        for obj in related_objects:
            print(f"  Object ID: {obj.id}, Type: {obj.object_type}, Local ID: {obj.local_object_id}, UUID: {obj.uuid}")


def find_delete_activities():
    """Find all delete activities"""
    with app.app_context():
        print(f"[DEBUG] Searching for delete activities...")
        
        # Find all activities with type 'Delete'
        delete_activities = activitypub.ActivityPubActivity.query.filter_by(
            activity_type='Delete'
        ).order_by(activitypub.ActivityPubActivity.created_at.desc()).all()
        
        print(f"[DEBUG] Found {len(delete_activities)} delete activities:")
        for activity in delete_activities:
            print(f"  ID: {activity.id}, Created: {activity.created_at}, Delivered: {activity.delivered}")
            
            # Get the actor
            actor = activitypub.ActivityPubActor.query.filter_by(id=activity.actor_id).first()
            if actor:
                print(f"    Actor: {actor.username}@{actor.domain}")
            
            # Show object data if available
            if activity.object_data:
                try:
                    object_data = json.loads(activity.object_data) if isinstance(activity.object_data, str) else activity.object_data
                    object_url = object_data.get('object', 'No object URL')
                    print(f"    Object: {object_url}")
                except:
                    print(f"    Object: [Error parsing object data]")
            print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python debug_delete_activity.py <activity_id>")
        print("  python debug_delete_activity.py --find")
        sys.exit(1)
    
    if sys.argv[1] == "--find":
        find_delete_activities()
    else:
        activity_id = int(sys.argv[1])
        debug_delete_activity(activity_id) 