# ActivityPub Integration for Open Streaming Platform

This document describes the ActivityPub integration for the Open Streaming Platform, enabling federation with other ActivityPub-compatible platforms like Mastodon, PeerTube, and more.

## Overview

ActivityPub is a W3C standard for decentralized social networking. This integration allows OSP to:

- Create ActivityPub actors for users and channels
- Publish videos and streams as ActivityPub objects
- Send and receive activities (follows, likes, announces, etc.)
- Federate with other ActivityPub platforms
- Provide WebFinger and NodeInfo discovery endpoints

## Installation

### 1. Dependencies

The ActivityPub dependencies are already included in the main `setup/requirements.txt` file:

- `cryptography>=3.4.8` - For RSA key generation and signing
- `requests>=2.25.1` - For HTTP communication with remote servers

### 2. Configuration

Add the following ActivityPub configuration options to your `conf/config.py`:

```python
# ActivityPub Configuration
# Enable ActivityPub federation
activitypubEnabled = True

# Your domain for ActivityPub URLs (e.g., "yourdomain.com")
activitypubDomain = "yourdomain.com"

# Site information for ActivityPub
activitypubSiteName = "Open Streaming Platform"
activitypubSiteDescription = "Federated Video Streaming Platform"

# ActivityPub service configuration
activitypubMaxRetries = 3
activitypubTimeout = 30
activitypubUserAgent = "OSP-ActivityPub/1.0"
activitypubSignatureAlgorithm = "rsa-sha256"
activitypubDefaultVisibility = "public"
```

### 3. Database Migration

Run the database migration to create the ActivityPub tables:

```bash
flask db upgrade
```

This will create the following tables:
- `activitypub_actors` - Stores ActivityPub actors (users/channels)
- `activitypub_objects` - Stores ActivityPub objects (videos/streams)
- `activitypub_activities` - Stores ActivityPub activities
- `activitypub_follows` - Stores follow relationships

### 4. Setup and Testing

Use the provided setup script to configure and test ActivityPub:

```bash
python setup_activitypub.py
```

This script will:
- Check your configuration
- Verify database tables exist
- Test ActivityPub endpoints
- Create a test actor
- Test WebFinger discovery

### 5. Restart the Application

Restart your OSP application for the changes to take effect:

```bash
# If using systemd
sudo systemctl restart osp

# If running manually
python app.py
```

## What's Needed for ActivityPub to Work

### Cryptographic Keys

**No additional key generation is needed!** The ActivityPub implementation:

- **Generates RSA keys automatically** for each user/channel when they become ActivityPub actors
- **Uses the cryptography library** (already included in requirements)
- **Stores keys securely** in the database
- **Does NOT use nginx keys** - ActivityPub has its own key management

### Required Infrastructure

1. **HTTPS/SSL Certificate**: ActivityPub requires HTTPS for all communications
2. **Public Domain**: Your server must be accessible from the internet
3. **Proper DNS**: Your domain must resolve correctly
4. **Firewall Configuration**: Port 443 (HTTPS) must be open

### Automatic Features

When ActivityPub is enabled:

- **Users and channels** automatically become ActivityPub actors when accessed
- **Videos and streams** are automatically published to ActivityPub
- **Follow relationships** are automatically managed
- **Incoming activities** are automatically processed

### Manual Steps Required

1. **Enable ActivityPub** in configuration
2. **Set your domain** in configuration
3. **Run database migration**
4. **Restart the application**
5. **Test with the setup script**

## API Endpoints

### Discovery Endpoints

#### WebFinger
```
GET /.well-known/webfinger?resource=acct:username@domain
```

Returns WebFinger information for ActivityPub actors.

#### NodeInfo
```
GET /.well-known/nodeinfo
GET /nodeinfo/2.0
```

Returns NodeInfo information about the server.

### Actor Endpoints

#### Actor Profile
```
GET /activitypub/actors/{username}
```

Returns ActivityPub actor information.

#### Actor Inbox
```
POST /activitypub/actors/{username}/inbox
```

Receives incoming ActivityPub activities.

#### Actor Outbox
```
GET /activitypub/actors/{username}/outbox
```

Returns the actor's outbox (published activities).

#### Followers
```
GET /activitypub/actors/{username}/followers
```

Returns the actor's followers list.

#### Following
```
GET /activitypub/actors/{username}/following
```

Returns the actor's following list.

### Object Endpoints

#### Video Object
```
GET /activitypub/videos/{uuid}
```

Returns ActivityPub video object information.

#### Stream Object
```
GET /activitypub/streams/{uuid}
```

Returns ActivityPub stream object information.

### Admin Endpoints

#### ActivityPub Dashboard
```
GET /admin/activitypub
```

Admin dashboard for monitoring ActivityPub activity.

#### ActivityPub Settings
```
GET /admin/activitypub/settings
POST /admin/activitypub/settings
```

Configure ActivityPub settings.

## Usage Examples

### Following a Remote User

```python
from functions.activitypub import get_activitypub_service

service = get_activitypub_service()
actor = service.get_actor_by_username('localuser')

# Send follow activity
service.send_activity(
    activity_type='Follow',
    actor=actor,
    target_id='https://mastodon.social/users/remoteuser',
    to=['https://mastodon.social/users/remoteuser']
)
```

### Publishing a Video

```python
from functions.activitypub import get_activitypub_service

service = get_activitypub_service()
actor = service.get_actor_by_username('channelname')

# Create video object
video_object = service.create_video_object(video, actor)

# Send create activity
service.send_activity(
    activity_type='Create',
    actor=actor,
    object_data=video_object.object_data
)
```

### Handling Incoming Activities

```python
from functions.activitypub import get_activitypub_service

service = get_activitypub_service()

# Handle incoming activity
service.handle_incoming_activity(activity_data)
```

## Federation Examples

### Mastodon Integration

1. **Follow a Mastodon user:**
   ```
   POST /activitypub/actors/localuser/inbox
   {
     "type": "Follow",
     "actor": "https://yourdomain.com/activitypub/actors/localuser",
     "object": "https://mastodon.social/users/remoteuser"
   }
   ```

2. **Receive a follow from Mastodon:**
   ```
   POST https://yourdomain.com/activitypub/actors/localuser/inbox
   {
     "type": "Follow",
     "actor": "https://mastodon.social/users/remoteuser",
     "object": "https://yourdomain.com/activitypub/actors/localuser"
   }
   ```

### PeerTube Integration

1. **Publish a video to PeerTube:**
   ```python
   service.send_activity(
       activity_type='Create',
       actor=actor,
       object_data=video_object.object_data,
       to=['https://peertube.social/inboxes']
   )
   ```

2. **Receive a video from PeerTube:**
   The system automatically handles incoming Create activities for videos.

## Security Considerations

### HTTPS Required
ActivityPub requires HTTPS for all communications. Ensure your server has a valid SSL certificate.

### Signature Verification
All outgoing activities are signed with RSA-SHA256 using the actor's private key. Incoming activities should be verified using the sender's public key.

### Rate Limiting
Consider implementing rate limiting on ActivityPub endpoints to prevent abuse.

### Content Filtering
Implement content filtering for incoming activities to prevent spam and inappropriate content.

## Troubleshooting

### Common Issues

1. **ActivityPub not working:**
   - Check that `activitypubEnabled = True` in config
   - Verify domain configuration is correct
   - Check logs for initialization errors

2. **Federation not working:**
   - Ensure HTTPS is properly configured
   - Check that your domain is accessible from the internet
   - Verify ActivityPub endpoints are responding correctly

3. **Database errors:**
   - Run `flask db upgrade` to ensure all tables exist
   - Check database connection and permissions

### Debug Mode

Enable debug logging by setting `log_level = 'debug'` in your config:

```python
log_level = 'debug'
```

### Log Files

ActivityPub logs are written to the main application log. Look for messages with the prefix `app.functions.activitypub`.

## Contributing

When contributing to the ActivityPub integration:

1. Follow the existing code style
2. Add appropriate error handling
3. Include tests for new functionality
4. Update this documentation for any new features
5. Ensure all ActivityPub activities follow the W3C specification

## References

- [ActivityPub W3C Specification](https://www.w3.org/TR/activitypub/)
- [WebFinger RFC 7033](https://tools.ietf.org/html/rfc7033)
- [NodeInfo Specification](https://nodeinfo.diaspora.software/)
- [Mastodon ActivityPub Documentation](https://docs.joinmastodon.org/spec/activitypub/)
- [PeerTube ActivityPub Implementation](https://docs.joinpeertube.org/developers/activitypub) 