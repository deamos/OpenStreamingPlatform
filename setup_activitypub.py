#!/usr/bin/env python3
"""
ActivityPub Setup Script for Open Streaming Platform

This script helps you set up and test ActivityPub functionality.
"""

import os
import sys
import requests
import json
from urllib.parse import urlparse

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_config():
    """Check if ActivityPub is properly configured"""
    print("🔍 Checking ActivityPub configuration...")
    
    try:
        from conf import config
        
        # Check required settings
        enabled = getattr(config, 'activitypubEnabled', False)
        domain = getattr(config, 'activitypubDomain', None)
        
        print(f"  ActivityPub enabled: {enabled}")
        print(f"  Domain: {domain}")
        
        if not enabled:
            print("❌ ActivityPub is disabled. Set activitypubEnabled = True in conf/config.py")
            return False
            
        if not domain or domain == 'localhost':
            print("❌ Please set activitypubDomain to your actual domain in conf/config.py")
            return False
            
        print("✅ Configuration looks good!")
        return True
        
    except ImportError:
        print("❌ Could not import config. Make sure you're running this from the OSP root directory.")
        return False

def check_database():
    """Check if ActivityPub database tables exist"""
    print("\n🗄️  Checking database tables...")
    
    try:
        # Import and initialize Flask app
        from app import app
        
        with app.app_context():
            from classes.shared import db
            from classes import activitypub
            
            # Try to query ActivityPub tables
            actor_count = activitypub.ActivityPubActor.query.count()
            activity_count = activitypub.ActivityPubActivity.query.count()
            
            print(f"  ActivityPub actors: {actor_count}")
            print(f"  ActivityPub activities: {activity_count}")
            print("✅ Database tables exist!")
            return True
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        print("   Run 'flask db upgrade' to create ActivityPub tables")
        return False

def test_endpoints(domain):
    """Test ActivityPub endpoints"""
    print(f"\n🌐 Testing ActivityPub endpoints on {domain}...")
    
    base_url = f"https://{domain}"
    
    # Test NodeInfo
    try:
        response = requests.get(f"{base_url}/.well-known/nodeinfo", timeout=10)
        if response.status_code == 200:
            print("✅ NodeInfo discovery endpoint working")
        else:
            print(f"❌ NodeInfo discovery endpoint failed: {response.status_code}")
    except Exception as e:
        print(f"❌ NodeInfo discovery endpoint error: {e}")
    
    # Test NodeInfo 2.0
    try:
        response = requests.get(f"{base_url}/nodeinfo/2.0", timeout=10)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ NodeInfo 2.0 endpoint working (users: {data.get('usage', {}).get('users', {}).get('total', 0)})")
        else:
            print(f"❌ NodeInfo 2.0 endpoint failed: {response.status_code}")
    except Exception as e:
        print(f"❌ NodeInfo 2.0 endpoint error: {e}")

def create_test_actor():
    """Create a test ActivityPub actor"""
    print("\n👤 Creating test ActivityPub actor...")
    
    try:
        from app import app
        
        with app.app_context():
            from functions.activitypub import get_activitypub_service
            from classes import Sec
            
            service = get_activitypub_service()
            if not service:
                print("❌ ActivityPub service not available")
                return False
            
            # Find first user
            user = Sec.User.query.first()
            if not user:
                print("❌ No users found in database")
                return False
            
            # Create actor
            actor = service.create_user_actor(user)
            if actor:
                print(f"✅ Created ActivityPub actor for user: {user.username}")
                print(f"   Actor URL: https://{actor.domain}/activitypub/actors/{actor.username}")
                return True
            else:
                print("❌ Failed to create ActivityPub actor")
                return False
            
    except Exception as e:
        print(f"❌ Error creating test actor: {e}")
        return False

def test_webfinger(domain, username):
    """Test WebFinger discovery"""
    print(f"\n🔍 Testing WebFinger for {username}@{domain}...")
    
    try:
        response = requests.get(
            f"https://{domain}/.well-known/webfinger",
            params={"resource": f"acct:{username}@{domain}"},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            print("✅ WebFinger working")
            print(f"   Subject: {data.get('subject')}")
            return True
        else:
            print(f"❌ WebFinger failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ WebFinger error: {e}")
        return False

def main():
    """Main setup function"""
    print("🚀 ActivityPub Setup for Open Streaming Platform")
    print("=" * 50)
    
    # Check configuration
    if not check_config():
        print("\n📝 To enable ActivityPub:")
        print("1. Set activitypubEnabled = True in conf/config.py")
        print("2. Set activitypubDomain to your actual domain")
        print("3. Run this script again")
        return
    
    # Get domain from config
    from conf import config
    domain = getattr(config, 'activitypubDomain', 'localhost')
    
    # Check database
    if not check_database():
        print("\n📝 To create database tables:")
        print("1. Run: flask db upgrade")
        print("2. Run this script again")
        return
    
    # Test endpoints
    test_endpoints(domain)
    
    # Create test actor
    if create_test_actor():
        # Test WebFinger with the created actor
        from app import app
        with app.app_context():
            from classes import Sec
            user = Sec.User.query.first()
            if user:
                test_webfinger(domain, user.username)
    
    print("\n🎉 ActivityPub setup complete!")
    print("\n📚 Next steps:")
    print("1. Test federation with other ActivityPub instances")
    print("2. Configure your domain's DNS and SSL certificates")
    print("3. Monitor ActivityPub logs for any issues")
    print("4. Check the admin interface at /admin/activitypub")

if __name__ == "__main__":
    main() 