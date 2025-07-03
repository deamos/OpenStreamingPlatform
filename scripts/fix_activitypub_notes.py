#!/usr/bin/env python3
"""
Fix ActivityPub Note objects to include required fields for Mastodon compatibility.
This script adds missing 'id' and 'attributedTo' fields to Note objects.
"""

import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from classes import activitypub
from conf import config

def fix_note_objects():
    """Fix Note objects to include required fields for Mastodon"""
    with app.app_context():
        domain = getattr(config, 'activitypubDomain', 'localhost')
        fixed_notes = 0
        
        # Find all Create activities with Note objects
        activities = activitypub.ActivityPubActivity.query.filter_by(activity_type='Create').all()
        
        for activity in activities:
            try:
                if not activity.object_data:
                    continue
                    
                # Parse object data
                object_data = json.loads(activity.object_data) if isinstance(activity.object_data, str) else activity.object_data
                
                if object_data.get('type') != 'Note':
                    continue
                
                # Check if Note object is missing required fields
                needs_fix = False
                if 'id' not in object_data:
                    needs_fix = True
                if 'attributedTo' not in object_data:
                    needs_fix = True
                
                if needs_fix:
                    print(f"[INFO] Fixing Note object in activity {activity.uuid}")
                    
                    # Add missing id field
                    if 'id' not in object_data:
                        object_data['id'] = f"https://{domain}/activitypub/notes/{activity.uuid}"
                    
                    # Add missing attributedTo field
                    if 'attributedTo' not in object_data:
                        actor = activity.actor
                        if actor:
                            object_data['attributedTo'] = f"https://{domain}/activitypub/actors/{actor.username}"
                    
                    # Update the activity with fixed object data
                    activity.object_data = json.dumps(object_data)
                    fixed_notes += 1
                    
            except Exception as e:
                print(f"[ERROR] Error fixing activity {activity.uuid}: {e}")
        
        # Commit changes
        db.session.commit()
        print(f"[INFO] Fixed {fixed_notes} Note objects")
        
        # Now re-deliver the fixed activities
        print("[INFO] Re-delivering fixed activities...")
        from scripts.send_unsent_notes import main as redeliver_notes
        redeliver_notes()

if __name__ == "__main__":
    fix_note_objects() 