#!/usr/bin/env python3

import sys
import os
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gevent import monkey
monkey.patch_all(thread=True)

from app import app
from classes import activitypub
from classes import RecordedVideo


def print_delete_activity_by_url(video_id):
    with app.app_context():
        # Get the video UUID from the RecordedVideo table
        video = RecordedVideo.RecordedVideo.query.filter_by(id=video_id).first()
        if not video or not hasattr(video, 'uuid') or not video.uuid:
            print(f"[ERROR] Could not find video or UUID for video ID {video_id}")
            return
        uuid = video.uuid
        print(f"[DEBUG] Video {video_id} has UUID: {uuid}")
        # Construct the expected ActivityPub video URL
        from conf import config
        domain = getattr(config, 'siteAddress', None) or getattr(config, 'activitypubDomain', None) or 'live.divby0.net'
        video_url = f"https://{domain}/activitypub/videos/{uuid}"
        print(f"[DEBUG] Looking for delete activity with object: {video_url}")
        # Find the most recent delete activity for this object URL
        delete_activities = activitypub.ActivityPubActivity.query.filter(
            activitypub.ActivityPubActivity.activity_type == 'Delete',
            activitypub.ActivityPubActivity.object_data.contains(video_url)
        ).order_by(activitypub.ActivityPubActivity.created_at.desc()).all()
        if not delete_activities:
            print(f"[ERROR] No delete activity found for video URL {video_url}")
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
        print("Usage: python3 print_delete_activity_by_url.py <video_id>")
        sys.exit(1)
    video_id = int(sys.argv[1])
    print_delete_activity_by_url(video_id) 