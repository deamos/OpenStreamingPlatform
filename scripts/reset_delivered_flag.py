#!/usr/bin/env python3
"""
Reset the delivered flag on ActivityPub activities so they can be re-sent.
This is needed after fixing Note objects to ensure the corrected content reaches followers.
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from classes import activitypub


def reset_delivered_flag():
    """Reset delivered flag on all Create activities with Note objects"""
    with app.app_context():
        # Find all Create activities with Note objects
        activities = activitypub.ActivityPubActivity.query.filter_by(activity_type='Create').all()
        print(f"[INFO] Found {len(activities)} Create activities total.")
        
        reset_count = 0
        for act in activities:
            try:
                import json
                obj = json.loads(act.object_data) if act.object_data else {}
                if obj.get('type') == 'Note':
                    act.delivered = False
                    reset_count += 1
                    print(f"[INFO] Reset delivered flag for activity {act.uuid}")
            except Exception as e:
                print(f"[ERROR] Error processing activity {act.uuid}: {e}")
        
        db.session.commit()
        print(f"[INFO] Reset delivered flag for {reset_count} activities")


if __name__ == "__main__":
    reset_delivered_flag() 