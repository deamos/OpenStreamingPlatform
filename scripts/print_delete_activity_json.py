#!/usr/bin/env python3

import sys
import os
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gevent import monkey
monkey.patch_all(thread=True)

from app import app
from classes import activitypub
from functions import cachedDbCalls


def print_delete_activity_json(video_id):
    with app.app_context():
        # Find the ActivityPub object for this video
        ap_object = activitypub.ActivityPubObject.query.filter_by(
            local_object_id=video_id,
            local_object_type='video'
        ).first()
        if not ap_object:
            print(f"[ERROR] No ActivityPub object found for video {video_id}")
            return
        uuid = ap_object.uuid
        print(f"[DEBUG] Video {video_id} has UUID: {uuid}")
        # Find the most recent delete activity for this UUID
        delete_activities = activitypub.ActivityPubActivity.query.filter(
            activitypub.ActivityPubActivity.activity_type == 'Delete',
            activitypub.ActivityPubActivity.object_data.contains(uuid)
        ).order_by(activitypub.ActivityPubActivity.created_at.desc()).all()
        if not delete_activities:
            print(f"[ERROR] No delete activity found for video UUID {uuid}")
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
        print("Usage: python3 print_delete_activity_json.py <video_id>")
        sys.exit(1)
    video_id = int(sys.argv[1])
    print_delete_activity_json(video_id) 