#!/usr/bin/env python3
"""
Force re-delivery of ActivityPub activities that were already marked as delivered.
This is needed after fixing Note objects to ensure the corrected content reaches followers.
"""

import sys
import os
import json
import requests
import hashlib
import base64
from email.utils import formatdate
from urllib.parse import urlparse

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from classes import activitypub
from conf import config


def get_actor_url(follower):
    """Get the canonical actor URL using WebFinger discovery"""
    try:
        # Try WebFinger first
        webfinger_url = f"https://{follower.domain}/.well-known/webfinger?resource=acct:{follower.username}@{follower.domain}"
        print(f"[DEBUG] Trying WebFinger: {webfinger_url}")
        
        response = requests.get(webfinger_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            links = data.get('links', [])
            for link in links:
                if link.get('rel') == 'self' and link.get('type') == 'application/activity+json':
                    actor_url = link.get('href')
                    print(f"[DEBUG] Found actor URL via WebFinger: {actor_url}")
                    return actor_url
        
        # Fallback to common URL patterns
        return try_common_actor_urls(follower)
        
    except Exception as e:
        print(f"[DEBUG] WebFinger failed for {follower.username}@{follower.domain}: {e}")
        return try_common_actor_urls(follower)


def try_common_actor_urls(follower):
    """Try common ActivityPub actor URL patterns"""
    common_patterns = [
        f"https://{follower.domain}/users/{follower.username}",
        f"https://{follower.domain}/activitypub/actors/{follower.username}",
        f"https://{follower.domain}/@/{follower.username}"
    ]
    
    for url in common_patterns:
        try:
            print(f"[DEBUG] Trying URL: {url}")
            response = requests.get(url, headers={"Accept": "application/activity+json"}, timeout=10)
            if response.status_code == 200:
                print(f"[DEBUG] Found actor URL: {url}")
                return url
        except Exception as e:
            print(f"[DEBUG] Failed to fetch {url}: {e}")
    
    return None


def get_follower_inboxes(actor):
    """Get inbox URLs for all remote followers of an actor"""
    inboxes = []
    
    # Find all accepted follows
    follows = activitypub.ActivityPubFollow.query.filter_by(following_id=actor.id, status='accepted').all()
    
    for follow in follows:
        follower = activitypub.ActivityPubActor.query.filter_by(id=follow.follower_id).first()
        if follower and not follower.is_local:
            # Get the canonical actor URL using WebFinger discovery
            actor_url = get_actor_url(follower)
            if not actor_url:
                print(f"[WARN] Could not determine actor URL for {follower.username}@{follower.domain}")
                continue
            
            # Fetch remote actor's inbox URL
            try:
                resp = requests.get(actor_url, headers={"Accept": "application/activity+json"}, timeout=10)
                if resp.status_code == 200:
                    inbox_url = resp.json().get('inbox')
                    if inbox_url:
                        inboxes.append((follower.username, follower.domain, inbox_url))
            except Exception as e:
                print(f"[WARN] Failed to fetch inbox for {follower.username}@{follower.domain}: {e}")
    
    return inboxes


def send_activity_to_inbox(activity_data, inbox_url, actor):
    """Send the activity to the given inbox URL, log response."""
    try:
        # Prepare headers and body
        body = json.dumps(activity_data, separators=(',', ':')).encode('utf-8')
        digest = base64.b64encode(hashlib.sha256(body).digest()).decode('utf-8')
        digest_header = f"SHA-256={digest}"
        date = formatdate(timeval=None, localtime=False, usegmt=True)
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
    """Force re-delivery of all Create activities with Note objects"""
    with app.app_context():
        # Find all Create activities with Note objects (including already delivered ones)
        activities = activitypub.ActivityPubActivity.query.filter_by(activity_type='Create').all()
        print(f"[INFO] Found {len(activities)} Create activities total.")
        
        note_activities = []
        for act in activities:
            try:
                obj = json.loads(act.object_data) if act.object_data else {}
                if obj.get('type') == 'Note':
                    note_activities.append(act)
            except Exception as e:
                print(f"[ERROR] Error parsing activity {act.uuid}: {e}")
        
        print(f"[INFO] Found {len(note_activities)} Create(Note) activities.")
        
        for act in note_activities:
            try:
                actor = act.actor
                if not actor:
                    print(f"[WARN] Activity {act.uuid} has no actor.")
                    continue
                
                activity_data = act.to_activitypub()
                inboxes = get_follower_inboxes(actor)
                
                if not inboxes:
                    print(f"[WARN] No remote followers for actor {actor.username}@{actor.domain}")
                    continue
                
                print(f"[INFO] Re-delivering activity {act.uuid} to {len(inboxes)} followers")
                
                all_success = True
                for follower_username, follower_domain, inbox_url in inboxes:
                    print(f"[INFO] Delivering activity {act.uuid} to {follower_username}@{follower_domain}")
                    success = send_activity_to_inbox(activity_data, inbox_url, actor)
                    if not success:
                        all_success = False
                
                if all_success:
                    print(f"[INFO] Successfully re-delivered activity {act.uuid}")
                else:
                    print(f"[WARN] Some deliveries failed for activity {act.uuid}")
                    
            except Exception as e:
                print(f"[ERROR] Exception processing activity {act.uuid}: {e}")


if __name__ == "__main__":
    main() 