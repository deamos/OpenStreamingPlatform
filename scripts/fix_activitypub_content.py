from app import app
from classes import activitypub
import json
from classes.shared import db
from conf import config


def decode_object_data(raw):
    """Recursively decode JSON strings until a dict is reached, or return None if not possible."""
    try:
        data = raw
        for _ in range(3):  # Try up to 3 levels
            if isinstance(data, str):
                data = json.loads(data)
            if isinstance(data, dict):
                return data
        return None
    except Exception:
        return None


def make_note_for_video(video_obj, actor, domain):
    data = decode_object_data(video_obj.object_data)
    if not data:
        print(f"[WARN] Skipping video_obj {video_obj.uuid}: object_data is not valid JSON")
        return None
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
    data = decode_object_data(stream_obj.object_data)
    if not data:
        print(f"[WARN] Skipping stream_obj {stream_obj.uuid}: object_data is not valid JSON")
        return None
    channelLoc = ''
    if 'url' in data and data['url']:
        # Try to extract channelLoc from the text/html or m3u8 link
        for link in data['url']:
            if link.get('mediaType') == 'text/html' and '/view/' in link.get('href', ''):
                channelLoc = link['href'].split('/view/')[-1]
                break
            if link.get('mediaType') == 'application/x-mpegURL' and '/live/' in link.get('href', ''):
                channelLoc = link['href'].split('/live/')[-1].split('/')[0]
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
                    # Recursively decode to dict
                    data = decode_object_data(obj.object_data)
                    if not data:
                        print(f"[WARN] Skipping object {obj.uuid}: object_data is not valid JSON")
                        continue
                    # If object_data is not a dict, skip
                    if not isinstance(data, dict):
                        print(f"[WARN] Skipping object {obj.uuid}: object_data is not a dict after decode")
                        continue
                    # Re-encode as canonical JSON
                    obj.object_data = json.dumps(data)
                    if data.get('type') == 'Video' and 'content' not in data:
                        data['content'] = data.get('summary') or data.get('name') or ''
                        obj.object_data = json.dumps(data)
                        fixed_objects += 1
                    # Add Note object for Video
                    if data.get('type') == 'Video' and obj.local_object_type == 'video':
                        actor = activitypub.ActivityPubActor.query.filter_by(id=obj.actor_id).first()
                        note = make_note_for_video(obj, actor, domain)
                        if note:
                            note_obj = activitypub.ActivityPubObject.query.filter_by(local_object_id=obj.local_object_id, local_object_type='video_note').first()
                            if not note_obj:
                                note_obj = activitypub.ActivityPubObject(
                                    object_type="Note",
                                    actor_id=obj.actor_id,
                                    local_object_id=obj.local_object_id,
                                    local_object_type='video_note',
                                    object_data=note
                                )
                                db.session.add(note_obj)
                                db.session.flush()  # get note_obj.id
                                added_notes += 1
                            # Ensure Create(Note) activity exists
                            note_activity_exists = activitypub.ActivityPubActivity.query.filter_by(
                                activity_type='Create',
                                actor_id=obj.actor_id,
                                target_id=note_obj.local_object_id
                            ).first()
                            if not note_activity_exists:
                                note_activity = activitypub.ActivityPubActivity(
                                    activity_type='Create',
                                    actor_id=obj.actor_id,
                                    object_data=json.dumps(note_obj.object_data),
                                    target_id=note_obj.local_object_id,
                                    to=data.get('to', ["https://www.w3.org/ns/activitystreams#Public"]),
                                    cc=data.get('cc', [])
                                )
                                db.session.add(note_activity)
                    # Add Note object for Stream
                    if data.get('type') == 'Video' and obj.local_object_type == 'stream':
                        actor = activitypub.ActivityPubActor.query.filter_by(id=obj.actor_id).first()
                        note = make_note_for_stream(obj, actor, domain)
                        if note:
                            note_obj = activitypub.ActivityPubObject.query.filter_by(local_object_id=obj.local_object_id, local_object_type='stream_note').first()
                            if not note_obj:
                                note_obj = activitypub.ActivityPubObject(
                                    object_type="Note",
                                    actor_id=obj.actor_id,
                                    local_object_id=obj.local_object_id,
                                    local_object_type='stream_note',
                                    object_data=note
                                )
                                db.session.add(note_obj)
                                db.session.flush()
                                added_notes += 1
                            # Ensure Create(Note) activity exists
                            note_activity_exists = activitypub.ActivityPubActivity.query.filter_by(
                                activity_type='Create',
                                actor_id=obj.actor_id,
                                target_id=note_obj.local_object_id
                            ).first()
                            if not note_activity_exists:
                                note_activity = activitypub.ActivityPubActivity(
                                    activity_type='Create',
                                    actor_id=obj.actor_id,
                                    object_data=json.dumps(note_obj.object_data),
                                    target_id=note_obj.local_object_id,
                                    to=data.get('to', ["https://www.w3.org/ns/activitystreams#Public"]),
                                    cc=data.get('cc', [])
                                )
                                db.session.add(note_activity)
                except Exception as e:
                    print(f"Error fixing object {obj.uuid}: {e}")
        # Fix ActivityPubActivity (activities with embedded object)
        activities = activitypub.ActivityPubActivity.query.all()
        for act in activities:
            if act.object_data:
                try:
                    data = decode_object_data(act.object_data)
                    if not data:
                        print(f"[WARN] Skipping activity {act.uuid}: object_data is not valid JSON")
                        continue
                    if not isinstance(data, dict):
                        print(f"[WARN] Skipping activity {act.uuid}: object_data is not a dict after decode")
                        continue
                    act.object_data = json.dumps(data)
                    if data.get('type') == 'Video' and 'content' not in data:
                        data['content'] = data.get('summary') or data.get('name') or ''
                        act.object_data = json.dumps(data)
                        fixed_activities += 1
                    # Add Create(Note) activity if not present
                    if data.get('type') == 'Video':
                        note_obj = activitypub.ActivityPubObject.query.filter_by(local_object_id=act.target_id, object_type='Note').first()
                        if note_obj:
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