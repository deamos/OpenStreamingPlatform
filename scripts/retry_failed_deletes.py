#!/usr/bin/env python3

import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gevent import monkey
monkey.patch_all(thread=True)

from app import app
from classes import activitypub
from classes.shared import db
from functions.activitypub import get_activitypub_service


def retry_failed_deletes():
    """Retry delivery of failed delete activities"""
    with app.app_context():
        print("[DEBUG] Searching for failed delete activities...")
        
        # Find all delete activities that failed to deliver
        failed_deletes = activitypub.ActivityPubActivity.query.filter_by(
            activity_type='Delete',
            delivered=False
        ).order_by(activitypub.ActivityPubActivity.created_at.desc()).all()
        
        print(f"[DEBUG] Found {len(failed_deletes)} failed delete activities:")
        
        if not failed_deletes:
            print("No failed delete activities found.")
            return
        
        service = get_activitypub_service()
        if not service:
            print("[ERROR] Could not get ActivityPub service")
            return
        
        for activity in failed_deletes:
            print(f"\n[DEBUG] Retrying delete activity ID: {activity.id}")
            
            # Get the actor
            actor = activitypub.ActivityPubActor.query.filter_by(id=activity.actor_id).first()
            if not actor:
                print(f"  [ERROR] Actor not found for activity {activity.id}")
                continue
            
            print(f"  Actor: {actor.username}@{actor.domain}")
            
            # Get the object data
            if not activity.object_data:
                print(f"  [ERROR] No object data for activity {activity.id}")
                continue
            
            try:
                object_data = json.loads(activity.object_data) if isinstance(activity.object_data, str) else activity.object_data
                object_url = object_data.get('object', 'No object URL')
                print(f"  Object: {object_url}")
                
                # Retry delivery
                print("  [INFO] Retrying delivery...")
                delivery_success = service._deliver_activity_to_followers_and_recipients(object_data, actor)
                
                if delivery_success:
                    # Mark as delivered
                    activity.delivered = True
                    db.session.commit()
                    print(f"  [SUCCESS] Activity {activity.id} marked as delivered")
                else:
                    print(f"  [FAILED] Activity {activity.id} delivery failed")
                    
            except Exception as e:
                print(f"  [ERROR] Exception retrying activity {activity.id}: {e}")
                import traceback
                print(f"  [ERROR] Traceback: {traceback.format_exc()}")


def show_delivery_status():
    """Show delivery status of all delete activities"""
    with app.app_context():
        print("[DEBUG] Delete activities delivery status:")
        
        # Find all delete activities
        delete_activities = activitypub.ActivityPubActivity.query.filter_by(
            activity_type='Delete'
        ).order_by(activitypub.ActivityPubActivity.created_at.desc()).all()
        
        for activity in delete_activities:
            actor = activitypub.ActivityPubActor.query.filter_by(id=activity.actor_id).first()
            actor_name = f"{actor.username}@{actor.domain}" if actor else "Unknown"
            
            print(f"  ID: {activity.id}, Created: {activity.created_at}, Delivered: {activity.delivered}, Actor: {actor_name}")
            
            if activity.object_data:
                try:
                    object_data = json.loads(activity.object_data) if isinstance(activity.object_data, str) else activity.object_data
                    object_url = object_data.get('object', 'No object URL')
                    print(f"    Object: {object_url}")
                except Exception:
                    print("    Object: [Error parsing object data]")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python retry_failed_deletes.py --retry")
        print("  python retry_failed_deletes.py --status")
        sys.exit(1)
    
    if sys.argv[1] == "--retry":
        retry_failed_deletes()
    elif sys.argv[1] == "--status":
        show_delivery_status()
    else:
        print("Invalid option. Use --retry or --status")
        sys.exit(1) 