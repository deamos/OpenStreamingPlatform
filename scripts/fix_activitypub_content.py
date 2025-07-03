from app import app
from classes import activitypub
import json


def fix_content_fields():
    with app.app_context():
        fixed_activities = 0
        fixed_objects = 0
        # Fix ActivityPubObject (videos and streams)
        objects = activitypub.ActivityPubObject.query.all()
        for obj in objects:
            if obj.object_data:
                try:
                    data = json.loads(obj.object_data)
                    if data.get('type') == 'Video' and 'content' not in data:
                        # Use summary or name as fallback
                        data['content'] = data.get('summary') or data.get('name') or ''
                        obj.object_data = json.dumps(data)
                        fixed_objects += 1
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
                except Exception as e:
                    print(f"Error fixing activity {act.uuid}: {e}")
        from classes.shared import db
        db.session.commit()
        print(f"Fixed {fixed_objects} ActivityPub objects and {fixed_activities} ActivityPub activities.")


if __name__ == "__main__":
    fix_content_fields() 