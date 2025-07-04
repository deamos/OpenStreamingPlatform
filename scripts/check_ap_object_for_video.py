#!/usr/bin/env python3

import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gevent import monkey
monkey.patch_all(thread=True)

from app import app
from classes import activitypub


def check_ap_object_for_video(video_id):
    with app.app_context():
        print(f"[DEBUG] Checking for ActivityPub object for video ID: {video_id}")
        ap_object = activitypub.ActivityPubObject.query.filter_by(
            local_object_id=video_id,
            local_object_type='video'
        ).first()
        if ap_object:
            print(f"[FOUND] ActivityPub object for video {video_id}:")
            print(f"  UUID: {ap_object.uuid}")
            print(f"  DB ID: {ap_object.id}")
            print(f"  Actor ID: {ap_object.actor_id}")
            print(f"  Published: {ap_object.published}")
            print(f"  Updated: {ap_object.updated}")
            try:
                data = json.loads(ap_object.object_data) if isinstance(ap_object.object_data, str) else ap_object.object_data
                print(f"  Object data: {json.dumps(data, indent=2)}")
            except Exception as e:
                print(f"  [ERROR] Could not parse object_data: {e}")
        else:
            print(f"[NOT FOUND] No ActivityPub object found for video {video_id}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 check_ap_object_for_video.py <video_id>")
        sys.exit(1)
    video_id = int(sys.argv[1])
    check_ap_object_for_video(video_id) 