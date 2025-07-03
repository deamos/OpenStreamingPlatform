from app import app
from classes import activitypub
import json
from classes.shared import db
from conf import config


def make_note_for_video(video_obj, actor, domain):
    data = json.loads(video_obj.object_data)
    note = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "type": "Note",
        "content": f"{data.get('description', data.get('name', ''))} <a href='https://{domain}/play/{video_obj.local_object_id}'>Watch here</a>",
        "attachment": [
            {
                "type": "Video",
                "mediaType": "video/mp4",
                "url": f"https://{domain}/videos/{data.get('videoLocation', data.get('videoLocation', ''))}",
                "icon": {"type": "Image", "url": f"https://{domain}/videos/{data.get('thumbnailLocation', '')}"} if data.get('thumbnailLocation') else None,
                "name": data.get('name', ''),
                "summary": data.get('description', ''),
                "attributedTo": data.get('attributedTo'),
                "published": data.get('published')
            }
        ],
        "published": data.get('published'),
        "to": data.get('to', ["https://www.w3.org/ns/activitystreams#Public"]),
        "cc": data.get('cc', [])
    }
    return note

def make_note_for_stream(stream_obj, actor, domain):
    data = json.loads(stream_obj.object_data)
    channelLoc = data['url'][0]['href'].split('/')[-1] if 'url' in data and data['url'] else ''
    note = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "type": "Note",
        "content": f"Live stream: {data.get('name', '')} <a href='https://{domain}/view/{channelLoc}'>Watch here</a>",
        "attachment": [
            {
                "type": "Video",
                "mediaType": "application/x-mpegURL",
                "url": f"https://{domain}/live/{channelLoc}/index.m3u8",
                "icon": {"type": "Image", "url": f"https://{domain}/stream-thumb/{channelLoc}.png"},
                "name": data.get('name', ''),
                "summary": data.get('summary', ''),
                "attributedTo": data.get('attributedTo'),
                "published": data.get('published')
            }
        ],
        "published": data.get('published'),
        "to": data.get('to', ["https://www.w3.org/ns/activitystreams#Public"]),
        "cc": data.get('cc', [])
    }
    return note

def fix_content_fields():
    with app.app_context():
        fixed_activities = 0
        fixed_objects = 0
        added_notes = 0
        domain = getattr(config, 'activitypubDomain', 'localhost')
        # Fix ActivityPubObject (videos and streams)
        objects = activitypub.ActivityPubObject.query.all()
        for obj in objects:
            if obj.object_data:
                try:
                    data = json.loads(obj.object_data)
                    if data.get('type') == 'Video' and 'content' not in data:
                        data['content'] = data.get('summary') or data.get('name') or ''
                        obj.object_data = json.dumps(data)
                        fixed_objects += 1
                    # Add Note object for Video
                    if data.get('type') == 'Video' and obj.local_object_type == 'video':
                        actor = activitypub.ActivityPubActor.query.filter_by(id=obj.actor_id).first()
                        note = make_note_for_video(obj, actor, domain)
                        # Check if Note already exists for this video
                        note_exists = activitypub.ActivityPubObject.query.filter_by(local_object_id=obj.local_object_id, local_object_type='video_note').first()
                        if not note_exists:
                            note_obj = activitypub.ActivityPubObject(
                                object_type="Note",
                                actor_id=obj.actor_id,
                                local_object_id=obj.local_object_id,
                                local_object_type='video_note',
                                object_data=note
                            )
                            db.session.add(note_obj)
                            added_notes += 1
                    # Add Note object for Stream
                    if data.get('type') == 'Video' and obj.local_object_type == 'stream':
                        actor = activitypub.ActivityPubActor.query.filter_by(id=obj.actor_id).first()
                        note = make_note_for_stream(obj, actor, domain)
                        note_exists = activitypub.ActivityPubObject.query.filter_by(local_object_id=obj.local_object_id, local_object_type='stream_note').first()
                        if not note_exists:
                            note_obj = activitypub.ActivityPubObject(
                                object_type="Note",
                                actor_id=obj.actor_id,
                                local_object_id=obj.local_object_id,
                                local_object_type='stream_note',
                                object_data=note
                            )
                            db.session.add(note_obj)
                            added_notes += 1
                except Exception as e:
                    print(f"Error fixing object {obj.uuid}: {e}")
        # Fix ActivityPubActivity (activities with embedded object)
        activities = activitypub.ActivityPubActivity.query.all()
        for act in activities:
            if act.object_data:
                try:
                    data = json.loads(act.object_data)
                    if isinstance(data, dict) and data.get('type') == 'Video' and 'content' not in data:
                        data['content'] = data.get('summary') or data.get('name') or ''
                        act.object_data = json.dumps(data)
                        fixed_activities += 1
                    # Add Create(Note) activity if not present
                    if isinstance(data, dict) and data.get('type') == 'Video':
                        # Find corresponding Note object
                        note_obj = activitypub.ActivityPubObject.query.filter_by(local_object_id=act.target_id, object_type='Note').first()
                        if note_obj:
                            # Check if Create(Note) activity exists
                            note_activity_exists = activitypub.ActivityPubActivity.query.filter_by(activity_type='Create', actor_id=act.actor_id, object_data=json.dumps(note_obj.object_data)).first()
                            if not note_activity_exists:
                                note_activity = activitypub.ActivityPubActivity(
                                    activity_type='Create',
                                    actor_id=act.actor_id,
                                    object_data=note_obj.object_data,
                                    target_id=note_obj.local_object_id,
                                    to=json.loads(act.to) if act.to else None,
                                    cc=json.loads(act.cc) if act.cc else None
                                )
                                db.session.add(note_activity)
                except Exception as e:
                    print(f"Error fixing activity {act.uuid}: {e}")
        # Remove duplicate followers
        follows = activitypub.ActivityPubFollow.query.order_by(activitypub.ActivityPubFollow.created_at.desc()).all()
        seen = set()
        removed = 0
        for follow in follows:
            key = (follow.follower_id, follow.following_id)
            if key in seen:
                db.session.delete(follow)
                removed += 1
            else:
                seen.add(key)
        db.session.commit()
        print(f"Fixed {fixed_objects} ActivityPub objects and {fixed_activities} ActivityPub activities.")
        print(f"Added {added_notes} Note objects for existing content.")
        print(f"Removed {removed} duplicate ActivityPub followers.")


if __name__ == "__main__":
    fix_content_fields() 