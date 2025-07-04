#!/usr/bin/env python3

import sys
import os
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gevent import monkey
monkey.patch_all(thread=True)

from app import app
from classes import activitypub


def print_delete_activity_by_object_url(object_url):
    with app.app_context():
        print(f"[DEBUG] Looking for delete activity with object: {object_url}")
        # Find the most recent delete activity for this object URL
        delete_activities = activitypub.ActivityPubActivity.query.filter(
            activitypub.ActivityPubActivity.activity_type == 'Delete',
            activitypub.ActivityPubActivity.object_data.contains(object_url)
        ).order_by(activitypub.ActivityPubActivity.created_at.desc()).all()
        if not delete_activities:
            print(f"[ERROR] No delete activity found for object URL {object_url}")
            return
        # Print the most recent one
        delete_activity = delete_activities[0]
        print(f"[DEBUG] Found delete activity ID: {delete_activity.id}, Created: {delete_activity.created_at}")
        try:
            data = json.loads(delete_activity.object_data) if isinstance(delete_activity.object_data, str) else delete_activity.object_data
            print(json.dumps(data, indent=2))
        except Exception as e:
            print(f"[ERROR] Could not parse delete activity object_data: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 print_delete_activity_by_object_url.py <object_url>")
        sys.exit(1)
    object_url = sys.argv[1]
    print_delete_activity_by_object_url(object_url) 