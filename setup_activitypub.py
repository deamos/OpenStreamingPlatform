#!/usr/bin/env python3
"""
ActivityPub Setup Script for Open Streaming Platform

This script helps you set up and test ActivityPub functionality.
"""

import os
import sys

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
                return None
            
            # Find first user
            user = Sec.User.query.first()
            if not user:
                print("❌ No users found in database")
                return None
            
            # Create actor
            actor = service.create_user_actor(user)
            if actor:
                print(f"✅ Created ActivityPub actor for user: {user.username}")
                print(f"   Actor URL: https://{actor.domain}/activitypub/actors/{actor.username}")
                return user.username
            else:
                print("❌ Failed to create ActivityPub actor")
                return None
            
    except Exception as e:
        print(f"❌ Error creating test actor: {e}")
        return None


def create_actors_for_existing_users():
    """Create ActivityPub actors for all existing users"""
    print("\n👥 Creating ActivityPub actors for existing users...")
    
    try:
        from app import app
        
        with app.app_context():
            from functions.activitypub import get_activitypub_service
            from classes import Sec
            
            service = get_activitypub_service()
            if not service:
                print("❌ ActivityPub service not available")
                return False
            
            # Get all users
            users = Sec.User.query.all()
            if not users:
                print("❌ No users found in database")
                return False
            
            created_count = 0
            existing_count = 0
            failed_count = 0
            
            for user in users:
                try:
                    actor = service.create_user_actor(user)
                    if actor:
                        if actor.created_at == actor.updated_at:
                            created_count += 1
                            print(f"  ✅ Created actor for: {user.username}")
                        else:
                            existing_count += 1
                            print(f"  ℹ️  Actor already exists for: {user.username}")
                    else:
                        failed_count += 1
                        print(f"  ❌ Failed to create actor for: {user.username}")
                except Exception as e:
                    failed_count += 1
                    print(f"  ❌ Error creating actor for {user.username}: {e}")
            
            print("\n📊 Summary:")
            print(f"  Created: {created_count}")
            print(f"  Already existed: {existing_count}")
            print(f"  Failed: {failed_count}")
            print(f"  Total users: {len(users)}")
            
            return True
            
    except Exception as e:
        print(f"❌ Error creating actors for existing users: {e}")
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
    
    # Create test actor and get username
    username = create_test_actor()
    
    # Create actors for existing users
    create_actors_for_existing_users()
    
    print("\n🎉 ActivityPub setup complete!")
    print("\n📚 Next steps:")
    print("1. Test federation with other ActivityPub instances")
    print("2. Configure your domain's DNS and SSL certificates")
    print("3. Monitor ActivityPub logs for any issues")
    print("4. Check the admin interface at /admin/activitypub")
    
    if username:
        print(f"\n🔧 Manual testing (replace 'USERNAME' with '{username}'):")
        print(f"  - Visit: https://{domain}/.well-known/nodeinfo")
        print(f"  - Visit: https://{domain}/nodeinfo/2.0")
        print(f"  - Visit: https://{domain}/.well-known/webfinger?resource=acct:{username}@{domain}")
        print(f"  - Visit: https://{domain}/activitypub/actors/{username}")
        print("\n🌐 Federation testing:")
        print(f"  - Try following @{username}@{domain} from Mastodon")
        print("  - Try following a Mastodon user from your OSP instance")
    else:
        print("\n🔧 Manual testing:")
        print(f"  - Visit: https://{domain}/.well-known/nodeinfo")
        print(f"  - Visit: https://{domain}/nodeinfo/2.0")
        print("  - Create a user first, then run this script again")


if __name__ == "__main__":
    main() 