from app import app
from classes import activitypub
import json


def fix_activitypub_activities():
    with app.app_context():
        fixed_activities = 0
        fixed_objects = 0
        activities = activitypub.ActivityPubActivity.query.all()
        for act in activities:
            if act.object_data:
                try:
                    data = json.loads(act.object_data)
                    # If data is a string, it's double-encoded
                    if isinstance(data, str):
                        try:
                            data2 = json.loads(data)
                            changed = False
                            # Ensure 'content' is present
                            if data2.get('type') == 'Video' and 'content' not in data2:
                                data2['content'] = data2.get('summary') or data2.get('name') or ''
                                changed = True
                            # If it's a stream, ensure playback link is present
                            if data2.get('type') == 'Video' and 'url' in data2 and isinstance(data2['url'], list):
                                m3u8_link = None
                                playback_link = None
                                for link in data2['url']:
                                    if link.get('mediaType') == 'application/x-mpegURL':
                                        m3u8_link = link
                                    if link.get('mediaType') == 'text/html' and '/view/' in link.get('href', ''):
                                        playback_link = link
                                # If m3u8 exists but playback does not, add playback link
                                if m3u8_link and not playback_link:
                                    # Try to extract channelLoc from m3u8 href
                                    import re
                                    match = re.search(r'/live/([^/]+)/', m3u8_link['href'])
                                    if match:
                                        channelLoc = match.group(1)
                                        playback = {
                                            'type': 'Link',
                                            'href': m3u8_link['href'].split('/live/')[0] + f'/view/{channelLoc}',
                                            'mediaType': 'text/html'
                                        }
                                        data2['url'].insert(0, playback)
                                        changed = True
                            if changed:
                                act.object_data = json.dumps(data2)
                                fixed_activities += 1
                        except Exception as e:
                            print(f"Error decoding double-encoded object for activity {act.uuid}: {e}")
                    elif isinstance(data, dict):
                        changed = False
                        if data.get('type') == 'Video' and 'content' not in data:
                            data['content'] = data.get('summary') or data.get('name') or ''
                            changed = True
                        if data.get('type') == 'Video' and 'url' in data and isinstance(data['url'], list):
                            m3u8_link = None
                            playback_link = None
                            for link in data['url']:
                                if link.get('mediaType') == 'application/x-mpegURL':
                                    m3u8_link = link
                                if link.get('mediaType') == 'text/html' and '/view/' in link.get('href', ''):
                                    playback_link = link
                            if m3u8_link and not playback_link:
                                import re
                                match = re.search(r'/live/([^/]+)/', m3u8_link['href'])
                                if match:
                                    channelLoc = match.group(1)
                                    playback = {
                                        'type': 'Link',
                                        'href': m3u8_link['href'].split('/live/')[0] + f'/view/{channelLoc}',
                                        'mediaType': 'text/html'
                                    }
                                    data['url'].insert(0, playback)
                                    changed = True
                        if changed:
                            act.object_data = json.dumps(data)
                            fixed_activities += 1
                except Exception as e:
                    print(f"Error fixing activity {act.uuid}: {e}")
        # Also fix ActivityPubObject records
        objects = activitypub.ActivityPubObject.query.all()
        for obj in objects:
            if obj.object_data:
                try:
                    data = json.loads(obj.object_data)
                    changed = False
                    if data.get('type') == 'Video' and 'content' not in data:
                        data['content'] = data.get('summary') or data.get('name') or ''
                        changed = True
                    if data.get('type') == 'Video' and 'url' in data and isinstance(data['url'], list):
                        m3u8_link = None
                        playback_link = None
                        for link in data['url']:
                            if link.get('mediaType') == 'application/x-mpegURL':
                                m3u8_link = link
                            if link.get('mediaType') == 'text/html' and '/view/' in link.get('href', ''):
                                playback_link = link
                        if m3u8_link and not playback_link:
                            import re
                            match = re.search(r'/live/([^/]+)/', m3u8_link['href'])
                            if match:
                                channelLoc = match.group(1)
                                playback = {
                                    'type': 'Link',
                                    'href': m3u8_link['href'].split('/live/')[0] + f'/view/{channelLoc}',
                                    'mediaType': 'text/html'
                                }
                                data['url'].insert(0, playback)
                                changed = True
                    if changed:
                        obj.object_data = json.dumps(data)
                        fixed_objects += 1
                except Exception as e:
                    print(f"Error fixing object {obj.uuid}: {e}")
        from classes.shared import db
        db.session.commit()
        print(f"Fixed {fixed_activities} ActivityPub activities and {fixed_objects} ActivityPub objects.")


if __name__ == "__main__":
    fix_activitypub_activities() 