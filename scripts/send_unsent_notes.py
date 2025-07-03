import json
import requests
from app import app
from classes import activitypub
from classes.shared import db
from conf import config
from urllib.parse import urlparse

def get_follower_inboxes(actor):
    """Return a list of inbox URLs for all accepted followers of the given actor."""
    from classes.activitypub import ActivityPubFollow, ActivityPubActor
    inboxes = []
    follows = ActivityPubFollow.query.filter_by(following_id=actor.id, status='accepted').all()
    for follow in follows:
        follower = ActivityPubActor.query.filter_by(id=follow.follower_id).first()
        if follower and not follower.is_local:
            try:
                resp = requests.get(f"https://{follower.domain}/activitypub/actors/{follower.username}", headers={"Accept": "application/activity+json"}, timeout=10)
                if resp.status_code == 200:
                    inbox_url = resp.json().get('inbox')
                    if inbox_url:
                        inboxes.append((follower.username, follower.domain, inbox_url))
            except Exception as e:
                print(f"[ERROR] Could not fetch inbox for follower {follower.username}@{follower.domain}: {e}")
    return inboxes

def send_activity_to_inbox(activity_data, inbox_url, actor):
    """Send the activity to the given inbox URL, log response."""
    try:
        # Prepare headers and body
        body = json.dumps(activity_data, separators=(',', ':')).encode('utf-8')
        digest = requests.utils.to_native_string(requests.utils.base64.b64encode(requests.utils.hashlib.sha256(body).digest()))
        digest_header = f"SHA-256={digest}"
        date = requests.utils.formatdate(usegmt=True)
        signature_string_parts = [
            f'(request-target): post {urlparse(inbox_url).path}',
            f'host: {urlparse(inbox_url).netloc}',
            f'date: {date}',
            f'digest: {digest_header}',
            'content-type: application/activity+json'
        ]
        signature_string = '\n'.join(signature_string_parts)
        # Load private key
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        private_key = serialization.load_pem_private_key(
            actor.private_key_pem.encode('utf-8'), password=None
        )
        signature = private_key.sign(
            signature_string.encode('utf-8'),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        import base64
        signature_b64 = base64.b64encode(signature).decode('utf-8')
        signature_header = (
            f'keyId="{activity_data["actor"]}#main-key",'
            f'algorithm="rsa-sha256",'
            f'headers="(request-target) host date digest content-type",'
            f'signature="{signature_b64}"'
        )
        headers = {
            'Content-Type': 'application/activity+json',
            'User-Agent': getattr(config, 'activitypubUserAgent', 'OSP-ActivityPub/1.0'),
            'Date': date,
            'Digest': digest_header,
            'Signature': signature_header
        }
        print(f"[INFO] Sending to inbox: {inbox_url}")
        print(f"[DEBUG] Headers: {headers}")
        print(f"[DEBUG] Activity: {json.dumps(activity_data, indent=2)}")
        resp = requests.post(inbox_url, data=body, headers=headers, timeout=30)
        print(f"[INFO] Response: {resp.status_code} {resp.reason}")
        if resp.status_code not in [200, 201, 202]:
            print(f"[ERROR] Body: {resp.text}")
        return resp.status_code in [200, 201, 202]
    except Exception as e:
        print(f"[ERROR] Exception sending to inbox {inbox_url}: {e}")
        return False

def main():
    with app.app_context():
        # Find all Create(Note) activities not marked as delivered
        activities = activitypub.ActivityPubActivity.query.filter(
            activitypub.ActivityPubActivity.activity_type == 'Create',
            activitypub.ActivityPubActivity.delivered.is_(False)
        ).all()
        print(f"[INFO] Found {len(activities)} undelivered Create activities.")
        for act in activities:
            try:
                obj = json.loads(act.object_data) if act.object_data else {}
                if obj.get('type') != 'Note':
                    continue
                actor = act.actor
                if not actor:
                    print(f"[WARN] Activity {act.uuid} has no actor.")
                    continue
                activity_data = act.to_activitypub()
                inboxes = get_follower_inboxes(actor)
                if not inboxes:
                    print(f"[WARN] No remote followers for actor {actor.username}@{actor.domain}")
                    continue
                all_success = True
                for follower_username, follower_domain, inbox_url in inboxes:
                    print(f"[INFO] Delivering activity {act.uuid} to {follower_username}@{follower_domain}")
                    success = send_activity_to_inbox(activity_data, inbox_url, actor)
                    if not success:
                        all_success = False
                if all_success:
                    act.delivered = True
                    db.session.commit()
                    print(f"[INFO] Marked activity {act.uuid} as delivered.")
            except Exception as e:
                print(f"[ERROR] Exception processing activity {act.uuid}: {e}")

if __name__ == "__main__":
    main() 