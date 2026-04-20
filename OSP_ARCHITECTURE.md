# Open Streaming Platform (OSP) — Architecture Reference

> **Purpose of this document**: Provide an AI assistant (or new developer) with a complete mental model of how OSP works — its components, how they communicate, where files live, how they are installed, and how data flows from a streamer's OBS through to a viewer's browser.

---

## Table of Contents

1. [What is OSP?](#1-what-is-osp)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Component Overview](#3-component-overview)
4. [OSP-Core (Flask Application)](#4-osp-core-flask-application)
5. [Nginx — Web Proxy + RTMP Ingest](#5-nginx--web-proxy--rtmp-ingest)
6. [OSP-RTMP — Stream Lifecycle Manager](#6-osp-rtmp--stream-lifecycle-manager)
7. [ejabberd — Real-Time Chat](#7-ejabberd--real-time-chat)
8. [OSP-Edge — CDN Offload (Optional)](#8-osp-edge--cdn-offload-optional)
9. [OSP-Proxy — Multi-Server Load Balancer (Optional)](#9-osp-proxy--multi-server-load-balancer-optional)
10. [Redis — Shared State and Message Bus](#10-redis--shared-state-and-message-bus)
11. [MariaDB — Persistent Data Store](#11-mariadb--persistent-data-store)
12. [Celery — Background Task Queue](#12-celery--background-task-queue)
13. [Full Stream Lifecycle Walkthrough](#13-full-stream-lifecycle-walkthrough)
14. [HTTP Request Flow and Authentication](#14-http-request-flow-and-authentication)
15. [File System Layout](#15-file-system-layout)
16. [Installation and Deployment](#16-installation-and-deployment)
17. [Configuration Files](#17-configuration-files)
18. [Key Python Modules and Blueprints](#18-key-python-modules-and-blueprints)
19. [ActivityPub / Federation](#19-activitypub--federation)
20. [Known Architecture Gotchas](#20-known-architecture-gotchas)

---

## 1. What is OSP?

Open Streaming Platform is a self-hosted, open-source video streaming server — a self-hosted alternative to Twitch, YouTube Live, or Ustream. It accepts RTMP streams from broadcasting software (OBS, Streamlabs, ffmpeg) and serves them to viewers as HLS (HTTP Live Streaming) over a standard web browser.

**Core capabilities:**
- RTMP ingest from OBS or any RTMP-compatible broadcaster
- HLS delivery to browsers (no plugin required)
- Live chat powered by XMPP (ejabberd)
- VOD (Video on Demand) — recordings auto-saved from live streams
- Manual MP4 uploads
- Video clipping from live recordings
- Protected / invite-only channels
- Adaptive bitrate streaming (admin-controlled via ffmpeg)
- Webhooks for external integrations
- ActivityPub federation (Fediverse-compatible)
- Restreaming to external RTMP endpoints (YouTube, Twitch, etc.)
- Multi-server scaling via OSP-Edge and OSP-Proxy components

**Version at time of writing:** `0.9.13` (see `globals/globalvars.py`)

---

## 2. High-Level Architecture

```
                      ┌──────────────────────────────────┐
  OBS/Broadcaster ───▶│  Nginx (port 1935 RTMP)          │
                      │  nginx-rtmp / nginx-http-flv      │
                      └──────────────┬───────────────────┘
                                     │ RTMP auth callbacks
                                     ▼
                      ┌──────────────────────────────────┐
                      │  OSP-RTMP (Flask, Gunicorn)       │
                      │  /opt/osp-rtmp  port: 5010+       │
                      └──────────────┬───────────────────┘
                                     │ REST API calls to OSP-Core
                                     ▼
 Browser Viewer ─────▶ Nginx (80/443) ──▶ OSP-Core (Flask, Gunicorn)
                      │  Reverse proxy    │  /opt/osp  ports 5000–5009 │
                      │  Static files     │  SQLAlchemy + MariaDB       │
                      │  HLS files        │  Flask-SocketIO + Redis     │
                      │  Auth subrequest  │  Celery + Celery Beat       │
                      └───────────────────┴─────────────────────────────┘
                                     │
                      ┌──────────────┴────────────────────────────────┐
                      │  Supporting Services                           │
                      │  • Redis (sessions, cache, SocketIO bus)       │
                      │  • MariaDB (all persistent data)              │
                      │  • ejabberd XMPP (live chat)                  │
                      └────────────────────────────────────────────────┘

  (Optional scale-out)
  OSP-Proxy ──▶ routes HLS requests to whichever RTMP node holds the stream
  OSP-Edge  ──▶ receives ffmpeg restream, serves HLS to distributed viewers
```

---

## 3. Component Overview

| Component | Required | Language | Runs As | Default Port(s) |
|---|---|---|---|---|
| **OSP-Core** | ✅ Yes | Python / Flask | Gunicorn workers | 5000–5009 |
| **Nginx (nginx-osp)** | ✅ Yes | C (custom build) | systemd service | 80/443 (HTTP), 1935 (RTMP) |
| **OSP-RTMP** | ✅ Yes | Python / Flask | Gunicorn | 5010 |
| **Redis** | ✅ Yes | C | systemd service | 6379 |
| **MariaDB** | ✅ Yes | C | systemd service | 3306 |
| **ejabberd** | ✅ Yes (for chat) | Erlang | systemd service | 5222, 5280, 5443 |
| **Celery Worker** | ✅ Yes | Python | systemd (osp-celery) | — |
| **Celery Beat** | ✅ Yes | Python | systemd (osp-celery-beat) | — |
| **OSP-Edge** | ❌ Optional | Bash/Nginx | systemd | 1935, 80 |
| **OSP-Proxy** | ❌ Optional | Python / Flask | Gunicorn | 6999 |

---

## 4. OSP-Core (Flask Application)

### Location
- **Source repo:** `/home/<user>/repos/flask-nginx-rtmp-manager/` (dev)
- **Deployed:** `/opt/osp/`
- **Entry point:** `/opt/osp/app.py`

### What it does
OSP-Core is the primary application. It handles:
- All web UI routes (channels, videos, live views, admin settings)
- User registration, login, authentication (Flask-Security-Too)
- REST API (`/apiv1/`) consumed by OSP-RTMP and external clients
- Real-time websocket events via Flask-SocketIO
- Database models and migrations (Flask-Migrate / Alembic)
- Auth subrequest endpoint (`/auth`) consulted by nginx before serving protected content
- Background task scheduling (via Celery)
- ejabberd XMPP integration for chat room management
- ActivityPub federation endpoints
- OAuth provider support (external SSO login)

### Process Model
OSP-Core runs as **11 independent Gunicorn workers** (ports 5000–5010), each a single `GeventWebSocketWorker` process. They are managed by a systemd `osp.target` that depends on 11 individual `osp-worker@<port>.service` units.

```
osp.target
  └── osp-worker@5000.service  → gunicorn app:app --bind 0.0.0.0:5000
  └── osp-worker@5001.service  → gunicorn app:app --bind 0.0.0.0:5001
  ...
  └── osp-worker@5009.service  → gunicorn app:app --bind 0.0.0.0:5009
```

Nginx load-balances across all workers using the **nginx-sticky** module (`sticky expires=8h`), which pins a client to the same worker for the session lifetime. This is important because some in-memory state (`inviteCache`, topic cache) is per-process.

### Shared State Between Workers
Since each worker is a separate process, shared state goes through:
- **Redis** — sessions (`SESSION_TYPE = "redis"`), Flask-Caching (`RedisCache`), Flask-Limiter, Celery broker, SocketIO message bus
- **MariaDB** — all persistent data
- **In-process global dict (`globals/globalvars.py`)** — used for `inviteCache`, `topicCache`, restream subprocesses. These are **NOT shared across workers**; sticky sessions mitigate this but you can get cache misses on failover.

### Key Flask Extensions Used

| Extension | Purpose |
|---|---|
| `Flask-Security-Too` | User auth, roles, 2FA (TOTP), password reset |
| `Flask-SQLAlchemy` | ORM with MariaDB |
| `Flask-Migrate` | Database schema migrations (Alembic) |
| `Flask-SocketIO` | WebSocket events (gevent backend) |
| `Flask-Session` | Server-side sessions stored in Redis |
| `Flask-Caching` | Redis-backed function-level caching |
| `Flask-Limiter` | Rate limiting (backed by Redis) |
| `Flask-Mail` | Email delivery |
| `Flask-Babel` | Internationalization |
| `Flask-CORS` | Cross-origin headers on `/apiv1/*` |
| `Flask-Reuploaded` | Image/file upload handling |
| `Authlib` | OAuth 2.0 client |
| `Celery` | Async task queue |
| `gevent` | Async I/O (monkey-patches stdlib) |

### Blueprint Structure
All routes are organized as Flask blueprints in `blueprints/`:

| Blueprint | Route Prefix | Purpose |
|---|---|---|
| `root_bp` | `/` | Home page, `/auth`, `/rtmpCheck`, search, proxy redirects |
| `channels_bp` | `/channel/` | Channel management pages |
| `liveview_bp` | `/view/` | Live stream viewer page |
| `play_bp` | `/play/` | VOD playback page |
| `clip_bp` | `/clip/` | Clip playback and management |
| `upload_bp` | `/upload/` | Manual video upload |
| `settings_bp` | `/settings/` | User and admin settings |
| `api_v1` | `/apiv1/` | REST API (consumed by OSP-RTMP, clients) |
| `activitypub_bp` | `/activitypub/` | ActivityPub actor/object endpoints |
| `discovery_bp` | `/.well-known/` | WebFinger, NodeInfo |
| `oauth_bp` | `/oauth/` | OAuth login flows |
| `m3u8_bp` | `/m3u8/` | M3U8 playlist generation for embedded players |
| `streamers_bp` | `/streamers/` | Streamer directory |
| `profile_bp` | `/u/` | User profiles |
| `topics_bp` | `/topic/` | Topic/category browsing |

---

## 5. Nginx — Web Proxy + RTMP Ingest

### Build
OSP uses a **custom-compiled nginx** from source at `/usr/local/nginx/`, NOT the distro package. The build includes:
- `nginx-http-flv-module` — replaces the older `nginx-rtmp-module`; handles RTMP ingest and HLS output
- `nginx-sticky-module-ng` — sticky session load balancing for the OSP-Core upstream
- `http_auth_request_module` — enables sub-request authentication (used by `/ospAuth`)
- `http_ssl_module`, `http_v2_module`, `http_stub_status_module`

### Config Structure
```
/usr/local/nginx/conf/
  nginx.conf               ← Main config (http block, proxy_cache_path)
  upstream/
    osp.conf               ← upstream socket_nodes { ... } (ports 5000–5009, sticky)
    osp-edge.conf          ← upstream ospedge_node (edge server address)
    osp-maps.conf          ← map directives for $ospChannelID, $bypass_auth_cache
  locations/
    osp-redirects.conf     ← /ospAuth, /videos, /keys, /images, /live, etc.
    osp-socketio.conf      ← Socket.IO WebSocket proxy
    osp.conf               ← catch-all proxy_pass to socket_nodes
    ejabberd.conf          ← XMPP HTTP bind proxy (if ejabberd installed)
  services/
    *.conf                 ← RTMP server block (port 1935)
  servers/
    *.conf                 ← Additional HTTP server blocks (e.g., osp-rtmp)
  custom/
    osp-custom-servers.conf        ← listen directive (80 or 443 TLS)
    osp-custom-serversredirect.conf ← HTTP→HTTPS redirect (if TLS enabled)
```

### The nginx RTMP / HLS Pipeline
The RTMP server block (in `services/`) defines multiple RTMP applications:
- **`/stream`** — ingest endpoint. OBS publishes here using the stream key. On `on_publish`, nginx calls OSP-RTMP's `/auth-key` endpoint for authentication.
- **`/stream-data`** — internal application that nginx redirects to after auth. Handles HLS output to `/var/www/live/`.
- **`/stream-data-adapt`** — same, but ffmpeg post-processing produces adaptive (multi-bitrate) HLS to `/var/www/live-adapt/`.
- **`/edge-data`** / **`/edge-data-adapt`** — receive ffmpeg restreams from the core and produce HLS for edge delivery.

### Auth Subrequest (`/ospAuth`)
Every request for protected resources (`/videos`, `/keys`, `/stream-thumb`) triggers an nginx `auth_request` to the internal `/ospAuth` location. This location:
1. Extracts `$ospChannelID` from the URI via `map` directives (in `osp-maps.conf`)
2. Proxies to `/auth` on OSP-Core (via `socket_nodes` upstream)
3. Caches the result in `proxy_cache auth_cache` for 10 minutes, keyed by `session cookie + auth token + channelID`
4. Returns 200 (allow) or 401 (deny) to the parent request

---

## 6. OSP-RTMP — Stream Lifecycle Manager

### Location
- **Source:** `installs/osp-rtmp/`
- **Deployed:** `/opt/osp-rtmp/`
- **Entry point:** `/opt/osp-rtmp/app.py`

### What it does
OSP-RTMP is a small, standalone Flask app that acts as the **callback handler for nginx's RTMP module**. Nginx cannot authenticate streams itself — it calls this app at key lifecycle events.

It has no database and no user sessions. It only communicates with OSP-Core via the REST API (`/apiv1/`).

### RTMP Lifecycle Callbacks

| nginx Event | OSP-RTMP Endpoint | OSP-Core API Called | What Happens |
|---|---|---|---|
| Stream publishes (OBS connects) | `POST /auth-key` | `POST /apiv1/rtmp/stage1` | Validates stream key, returns channel location, redirects to `/stream-data` or `/stream-data-adapt` |
| Stream enters `/stream-data` | `POST /auth-user` | `POST /apiv1/rtmp/stage2` | Marks stream active in DB, starts ffmpeg restream subprocesses to edge nodes and external RTMP destinations |
| Recording starts | `POST /auth-record` | `POST /apiv1/rtmp/reccheck` | Verifies channel allows recording |
| Stream ends / OBS disconnects | `POST /deauth-user` | `POST /apiv1/rtmp/streamclose` | Marks stream inactive, kills all ffmpeg restream subprocesses |
| Recording finishes | `POST /deauth-record` | `POST /apiv1/rtmp/recclose` | Triggers video processing (thumbnail, metadata, DB entry) |
| Admin force-closes a stream | `POST /closeStream` | nginx control API at `:9000` | Forcibly drops the RTMP client |

### Restreaming
When a stream starts (`/auth-user`), OSP-RTMP:
1. Fetches restream destinations from OSP-Core API
2. Spawns one `ffmpeg` subprocess per destination (transcodes to configured max bitrate)
3. Fetches active edge nodes from OSP-Core API
4. Spawns one `ffmpeg` subprocess per edge node (copy codec, no transcode)

All subprocess handles are stored in `globalvars.restreamSubprocesses` and `globalvars.edgeRestreamSubprocesses` — keyed by `channelLocation`. These are killed on `deauth-user`.

### Process Model
Runs as a single Gunicorn worker on a fixed port (varies by install, see `osp-rtmp.service`). No load balancing needed since nginx only calls it for RTMP events.

---

## 7. ejabberd — Real-Time Chat

### Role
Each OSP channel has a **persistent XMPP multi-user chat (MUC) room** hosted by ejabberd. Viewers join the chat through OSP's web UI which communicates with ejabberd via BOSH (XMPP over HTTP).

### How the Connection Works
```
Browser ──▶ Nginx /xmpp proxy ──▶ ejabberd port 5280 (BOSH endpoint)
                                        │
Browser connects directly via           │ ejabberd authenticates users via
WebSocket/BOSH to XMPP room            │ external auth script: auth_osp.py
                                        │    ↓ calls OSP-Core API to validate
                                        │    ↓ user credentials
```

The `/xmpp` route in OSP-Core (`blueprints/root.py`) proxies BOSH POST requests to ejabberd at port 5280. This allows the browser to reach ejabberd through the same nginx server without exposing ejabberd's port directly.

### Authentication
ejabberd is configured with an **external authentication script** (`/opt/ejabberd/conf/auth_osp.py`) that calls the OSP-Core API to verify username/password. This keeps user accounts in OSP's database — ejabberd has no separate user store.

### Chat Rooms
Each channel gets an XMPP room created/verified at startup via `ejabberdctl` (XML-RPC). The room configuration is defined in `globals/globalvars.py`:
- Persistent, moderated, members-by-default
- Max 2500 users
- Anonymous visitor nickchanges allowed per-channel setting

### Chat Domain
Default XMPP domain: `osp.internal` (configurable via `config.ospXMPPDomain`). Channels use `xmppToken` (a random hex string per channel) as the XMPP room identity.

---

## 8. OSP-Edge — CDN Offload (Optional)

### Purpose
When a single OSP server can't handle all viewer connections (HLS is bandwidth-intensive and CPU-light), additional **edge nodes** distribute the HLS delivery load. Viewers near an edge node receive HLS from that node rather than the core server.

### How it Works
1. An edge server is provisioned (separate machine or VM)
2. The setup script (`setup-ospEdge.sh`) is run, installing a custom nginx with RTMP
3. The admin adds the edge node's FQDN in OSP Admin → Edge Streamers
4. When a stream starts on the core, OSP-RTMP spawns an `ffmpeg` process that restreams RTMP to each active edge node at `rtmp://<edge>/edge-data/<channelLoc>` or `rtmp://<edge>/edge-data-adapt/<channelLoc>`
5. The edge nginx produces HLS from the received RTMP stream to its local `/var/www/live/` or `/var/www/live-adapt/`
6. Viewers are served HLS from the edge via nginx on port 80

### Edge Config File
OSP-Core maintains `/opt/osp/conf/osp-edge.conf` dynamically — it regenerates that file to list the current active edge nodes, then reloads nginx with the new upstream config. This is the `system.checkOSPEdgeConf()` call in `app.py`.

---

## 9. OSP-Proxy — Multi-Server Load Balancer (Optional)

### Purpose
When multiple **OSP-Core + OSP-RTMP pairs** exist (horizontally scaled), OSP-Proxy routes HLS playback requests to the correct RTMP node holding a given stream.

### Location
- **Source:** `installs/osp-proxy/`
- **Deployed:** `/opt/osp-proxy/`

### How it Works
```
Browser requests /live/<chanLoc>/index.m3u8
    ↓
OSP-Proxy (port 6999)
    ↓  Call /rtmpCheck on OSP-Core with X-Channel-ID header
OSP-Core returns X_UpstreamHost: <rtmp-node-address>
    ↓
OSP-Proxy redirects browser to http://<rtmp-node>/live/<chanLoc>/index.m3u8
```

OSP-Proxy caches the upstream lookup in local Redis for 30 seconds, avoiding a round-trip to OSP-Core on every HLS segment request.

It also handles HLS encryption key delivery, verifying the viewer's token by calling OSP-Core's `/apiv1/rtmp/playbackauth` before serving the `.key` file.

### Upstream Config
OSP-Proxy generates `osp-custom-servers.conf` dynamically via `generate_upstream.py`, which is called by `updateUpstream.sh` on a cron job every 5 minutes.

---

## 10. Redis — Shared State and Message Bus

Redis is a central dependency — multiple subsystems use it simultaneously:

| Use | Key Prefix / Config | Details |
|---|---|---|
| Flask-Session | `ospSession` cookie → Redis | Server-side session storage for all 11 workers |
| Flask-Caching | `OSP_FC:*` keys | Caches DB query results (`cachedDbCalls.*`), cleared on data changes |
| Flask-Limiter | — | Rate limit counters |
| Flask-SocketIO | — | Message bus between workers; events emitted on one worker are broadcast to all via Redis pub/sub |
| Celery broker | `CACHE_REDIS_*` | Task queue for background jobs |
| OSP-Proxy cache | `channelLoc` → upstream | 30-second lookup cache |
| Startup guards | `OSP_DB_INIT_HANDLER`, `OSP_XMPP_INIT_HANDLER`, `OSP_SYSTEM_FIXES_HANDLER` | Prevents multiple workers from running initialization simultaneously on startup |

**Configuration:** `config.redisHost`, `config.redisPort`, `config.redisPassword` in `conf/config.py`.

**Important:** `app.py` calls `r.flushdb()` on every Gunicorn worker startup, which clears all Redis data for that DB. This means sessions are lost when OSP restarts.

---

## 11. MariaDB — Persistent Data Store

All durable application data lives in MariaDB. The schema is managed by **Flask-Migrate** (Alembic).

### Key Tables / Models (in `classes/`)

| Model | Table | Description |
|---|---|---|
| `settings.settings` | `settings` | Global system configuration (one row) |
| `Sec.User` | `user` | User accounts (Flask-Security-Too) |
| `Sec.Role` | `role` | User roles (Admin, Streamer) |
| `Channel.Channel` | `Channel` | Per-user stream channels |
| `Stream.Stream` | `Stream` | Active / recently active streams |
| `RecordedVideo.RecordedVideo` | `RecordedVideo` | VOD entries post-recording |
| `RecordedVideo.Clips` | `Clips` | Short clips cut from recordings |
| `settings.edgeStreamer` | `edgeStreamer` | Registered edge node addresses |
| `settings.rtmpServer` | `rtmpServer` | Registered RTMP servers (for proxy setup) |
| `invites.invitedViewer` | `invitedViewer` | Per-user channel access grants |
| `invites.inviteCode` | `inviteCode` | Shareable invite codes for protected channels |
| `webhook.webhook` | `webhook` | Per-channel outgoing webhook definitions |
| `subscriptions.channelSubs` | `channelSubs` | User subscriptions to channels |
| `notifications.userNotification` | `userNotification` | In-app notification entries |
| `settings.oAuthProvider` | `oAuthProvider` | External SSO provider configurations |
| `activitypub.*` | various | ActivityPub actors, objects, followers |

### Connection Pool
```python
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_use_lifo": True,
    "pool_size": 20,
    "pool_pre_ping": True,
    "max_overflow": 30,
}
app.config["SQLALCHEMY_POOL_RECYCLE"] = 300   # recycle connections every 5 min
app.config["SQLALCHEMY_POOL_TIMEOUT"] = 600
```
Each of the 11 workers can hold up to 50 connections (20 pool + 30 overflow). With 11 workers, maximum theoretical connections = 550. Ensure MariaDB `max_connections` is set accordingly.

---

## 12. Celery — Background Task Queue

### Services
- **`osp-celery`** — worker process that executes tasks
- **`osp-celery-beat`** — scheduler that enqueues periodic tasks
- **`osp-celery-flower`** (optional) — web monitoring dashboard (port 5572)

### What Celery Does
- Sends notification emails (subscriptions, stream start alerts)
- Processes webhook delivery
- Handles video thumbnail generation (post-recording)
- Scheduled cleanup tasks (video/clip retention enforcement, etc.)
- Any long-running operations that shouldn't block an HTTP request

### Task Definitions
Located in `functions/scheduled_tasks/`:
- `scheduler.py` — Celery Beat periodic task schedule
- `message_tasks.py` — email and notification tasks
- Additional task modules imported via `celeryFunc.py`

---

## 13. Full Stream Lifecycle Walkthrough

### Going Live

```
1. Streamer opens OBS, configures RTMP URL:  rtmp://live.example.com/stream
   Stream key = the channel's streamKey (UUID stored in Channel.streamKey)

2. OBS connects → nginx RTMP on port 1935, application /stream

3. nginx RTMP fires on_publish callback:
   POST http://127.0.0.1:5010/auth-key  (OSP-RTMP)
   form data: name=<stream_key>, addr=<streamer_ip>

4. OSP-RTMP calls OSP-Core REST API:
   POST /apiv1/rtmp/stage1  { name: <stream_key>, addr: <ip> }

5. OSP-Core validates stream key → looks up Channel → returns:
   { success: true, channelLoc: "<uuid>", type: "normal"|"adaptive" }

6. OSP-RTMP responds to nginx with redirect:
   302 → rtmp://127.0.0.1/stream-data/<channelLoc>     (normal)
   302 → rtmp://127.0.0.1/stream-data-adapt/<channelLoc> (adaptive)

7. nginx RTMP routes stream into stream-data application,
   fires on_publish again → POST /auth-user (OSP-RTMP stage 2):

8. OSP-RTMP calls POST /apiv1/rtmp/stage2 on OSP-Core:
   - OSP-Core creates Stream DB entry, marks channel live
   - OSP-Core fires stream-start webhooks (via Celery)
   - OSP-Core sends SocketIO event → all browsers on channel page update

9. OSP-RTMP spawns ffmpeg subprocesses:
   - One per active edge node (RTMP restream, codec copy)
   - One per configured restream destination (e.g., YouTube)

10. nginx RTMP writes HLS segments to /var/www/live/<channelLoc>/
    (or /var/www/live-adapt/<channelLoc>/ if adaptive)
```

### Viewer Watching

```
1. Browser navigates to https://live.example.com/view/<channelLoc>

2. nginx receives the request, proxy_passes to OSP-Core (socket_nodes upstream)

3. OSP-Core renders liveview.html with the channel's HLS URL embedded

4. Browser's HLS.js player requests:
   GET /live/<channelLoc>/index.m3u8

5. nginx serves the .m3u8 directly from /var/www/live/ (no auth — live streams
   currently have auth commented out; protect if needed)

6. .m3u8 points to .ts segment files → browser downloads, plays video

7. Browser simultaneously opens a Socket.IO WebSocket connection for real-time
   viewer count, chat notifications, and stream events

8. Browser opens BOSH connection to /xmpp → nginx → ejabberd:
   User joins XMPP MUC room for the channel, chat messages flow via XMPP
```

### Stream Ends

```
1. OBS disconnects / streamer stops stream

2. nginx RTMP fires on_done → POST /deauth-user (OSP-RTMP)

3. OSP-RTMP calls POST /apiv1/rtmp/streamclose on OSP-Core:
   - Stream DB entry deleted/marked inactive
   - Channel marked offline
   - SocketIO event broadcast to viewers
   - Webhooks fired (stream end event)

4. OSP-RTMP kills all ffmpeg restream subprocesses for the channel

5. If recording was enabled, nginx RTMP fires on_record_done:
   POST /deauth-record (OSP-RTMP)

6. OSP-RTMP calls POST /apiv1/rtmp/recclose on OSP-Core:
   - RecordedVideo DB entry created
   - ffmpeg thumbnail extraction queued via Celery
   - Video becomes available in VOD library
```

---

## 14. HTTP Request Flow and Authentication

### Nginx → Flask Request Path

```
Client HTTP request
  ↓
nginx (port 80/443)
  ↓
Match location block in /usr/local/nginx/conf/locations/
  ├── /socket.io  → WebSocket upgrade → socket_nodes upstream  (osp-socketio.conf)
  ├── /videos     → auth_request /ospAuth → serve from /var/www/videos/
  ├── /keys       → auth_request /ospAuth → serve from /var/www/keys/
  ├── /stream-thumb → auth_request /ospAuth → serve from /var/www/stream-thumb/
  ├── /live       → serve from /var/www/live/  (no auth currently)
  ├── /live-adapt → serve from /var/www/live-adapt/  (no auth currently)
  ├── /static     → serve from /opt/osp/static/
  ├── /images     → serve from /var/www/images/
  └── /           → proxy_pass to socket_nodes upstream  (osp.conf)
```

### The `/ospAuth` Subrequest Detail

```nginx
# Defined in upstream/osp-maps.conf
map $request_uri $ospChannelID {
    ~^/videos/([^/]+)/   $1;   # extract channel UUID from URI
    ~^/keys/([^/]+)/     $1;
    ...
}

# Defined in locations/osp-redirects.conf
location /ospAuth {
    internal;
    proxy_pass http://socket_nodes/auth;
    proxy_set_header X-Channel-ID $ospChannelID;
    proxy_set_header X-Original-URI $request_uri;
    proxy_cache auth_cache;
    proxy_cache_key "$cookie_ospSession$http_x_auth_token$ospChannelID";
    proxy_cache_valid 200 10m;   # cache successful auth for 10 minutes
    proxy_cache_bypass $bypass_auth_cache;
    proxy_no_cache $bypass_auth_cache;
}
```

### Flask `/auth` Endpoint Logic (`blueprints/root.py`)

```python
@root_bp.route("/auth")
def auth_check():
    # 1. If global protection is disabled → always allow
    sysSettings = cachedDbCalls.getSystemSettings()
    if not sysSettings.protectionEnabled:
        return "OK"

    # 2. Get channel ID from nginx header
    channelID = request.headers.get("X-Channel-ID", "")

    # 3. Look up channel in DB
    channelQuery = Channel.query.filter_by(channelLoc=channelID).first()

    # 4. If channel is not protected → allow
    if not channelQuery.protected:
        return "OK"

    # 5. Check if current user (session) is a valid viewer
    if securityFunc.check_isValidChannelViewer(channelQuery.id):
        return "OK"
    abort(401)
```

`check_isValidChannelViewer` checks (in order):
1. Is the user an Admin? → allow
2. Is there a cached invite in `globalvars.inviteCache`? → allow
3. Does the user own the channel? → allow + cache
4. Does the user have a valid `invitedViewer` DB entry? → allow + cache
5. For anonymous users: check `session["inviteCodes"]` for valid invite codes
6. Otherwise → deny

---

## 15. File System Layout

```
/opt/osp/                    ← OSP-Core application
  app.py                     ← Flask application factory
  conf/config.py             ← Local configuration (DB, Redis, SMTP, etc.)
  blueprints/                ← Flask route blueprints
  classes/                   ← SQLAlchemy ORM models
  functions/                 ← Business logic, helpers, SocketIO handlers
  globals/globalvars.py      ← Runtime global state
  setup/                     ← Deployment assets (nginx, gunicorn, celery)
  installs/                  ← Other component source (osp-rtmp, osp-proxy, etc.)
  static/                    ← CSS, JS, images served at /static
  templates/                 ← Jinja2 HTML templates
  migrations/                ← Alembic migration scripts
  logs/                      ← Gunicorn access and error logs
  venv/                      ← Python virtual environment

/opt/osp-rtmp/               ← OSP-RTMP application
  app.py
  conf/config.py             ← ospCoreAPI endpoint URL, secret key
  blueprints/rtmp.py         ← RTMP lifecycle callback routes

/opt/osp-proxy/              ← OSP-Proxy application (optional)
  app.py
  conf/config.py             ← ospCoreAPI endpoint, forceDestination settings
  updateUpstream.sh          ← Cron script to refresh upstream config

/usr/local/nginx/            ← Custom-compiled nginx
  conf/                      ← All nginx configuration
  sbin/nginx                 ← nginx binary

/var/www/                    ← Web-served media files
  videos/                    ← Recorded VOD files (.mp4)
  videos/temp/               ← Temporary upload staging
  live/                      ← Live HLS segments (.m3u8, .ts)
  live-adapt/                ← Adaptive HLS segments
  keys/                      ← HLS AES-128 encryption keys
  keys-adapt/                ← Adaptive HLS encryption keys
  stream-thumb/              ← Live stream thumbnail images
  images/                    ← User-uploaded images (avatars, banners, thumbnails)
  pending/                   ← Videos pending processing
  ingest/                    ← Upload ingest staging

/opt/ejabberd/               ← ejabberd XMPP server
  conf/ejabberd.yml          ← ejabberd configuration
  conf/auth_osp.py           ← External auth script (calls OSP-Core API)
```

---

## 16. Installation and Deployment

### Install Script
All installation and upgrades are handled by the interactive bash script:
```
/opt/osp/osp-config.sh    (deployed)
[repo]/osp-config.sh      (development)
```

### Install Functions

| Menu Option | Shell Function | What It Does |
|---|---|---|
| Install OSP - Single Server | Multiple | Full stack: Nginx, Redis, ejabberd, OSP-RTMP, OSP-Core, Celery |
| Install OSP-Core | `install_osp` | Flask app + Gunicorn services + nginx locations |
| Install OSP-RTMP | `install_osp_rtmp` | OSP-RTMP Flask app + nginx RTMP server block |
| Install OSP-Edge | `install_osp_edge` | nginx RTMP on remote machine |
| Install OSP-Proxy | `install_osp_proxy` | OSP-Proxy Flask app + nginx config + cron |
| Install eJabberd | `install_ejabberd` | ejabberd + auth script + nginx BOSH location |

### Upgrade Functions

| Menu Option | Shell Function | Files Updated |
|---|---|---|
| Upgrade OSP - Single Server | `upgrade_osp` + `upgrade_nginxcore` | Locations, upstream configs, `/opt/osp`, DB migration |
| Upgrade OSP-Core | `upgrade_osp` + `upgrade_nginxcore` | Same as above |
| Upgrade Nginx Core | `upgrade_nginxcore` | Copies `installs/nginx-core/nginx.conf` → live |

### File Copy Paths During Upgrade

```bash
# upgrade_osp copies FROM /opt/osp (the deployed app, not the dev repo):
sudo cp -rf /opt/osp/setup/nginx/locations/*        /usr/local/nginx/conf/locations/
sudo cp -rf /opt/osp/setup/nginx/upstream/osp.conf  /usr/local/nginx/conf/upstream/
sudo cp -rf /opt/osp/setup/nginx/upstream/osp-edge.conf /usr/local/nginx/conf/upstream/
sudo cp -rf /opt/osp/setup/nginx/upstream/osp-maps.conf /usr/local/nginx/conf/upstream/

# upgrade_nginxcore copies FROM $DIR (wherever osp-config.sh is run from):
sudo cp -rf "$DIR/installs/nginx-core/nginx.conf" /usr/local/nginx/conf/
```

**Critical implication:** `upgrade_osp` reads from `/opt/osp`, so `/opt/osp` must be updated (e.g., via `git pull` in `/opt/osp`) before running the upgrade. `upgrade_nginxcore` reads from `$DIR` (the script's directory).

### systemd Services

| Service | Type | Controls |
|---|---|---|
| `nginx-osp.service` | Simple | Custom nginx process |
| `osp.target` | Target | All OSP-Core workers (5000–5009) |
| `osp-worker@<port>.service` | Templated | Individual Gunicorn worker |
| `osp-rtmp.service` | Simple | OSP-RTMP Gunicorn |
| `osp-celery.service` | Simple | Celery worker |
| `osp-celery-beat.service` | Simple | Celery scheduler |
| `osp-celery-flower.service` | Simple | Celery dashboard (optional) |
| `ejabberd.service` | Simple | ejabberd XMPP |
| `osp-proxy.service` | Simple | OSP-Proxy Gunicorn (optional) |

---

## 17. Configuration Files

### OSP-Core: `conf/config.py`
(Copied from `conf/config.py.dist` at install time — never committed to git)

```python
dbLocation = "mysql+pymysql://osp:password@localhost/osp"
redisHost = "127.0.0.1"
redisPort = 6379
redisPassword = ""
secretKey = "<random>"
passwordSalt = "<random>"
allowRegistration = True
requireEmailRegistration = False
debugMode = False
ejabberdAdmin = "admin"
ejabberdPass = "<password>"
ejabberdHost = "localhost"
smtpSendAs = "osp@example.com"
smtpServerAddress = "localhost"
smtpServerPort = 25
smtpEncryption = ""
smtpUsername = ""
smtpPassword = ""
```

### Docker / Environment Variable Equivalents
When `conf/config.py` is missing, OSP-Core falls back to environment variables:

| Env Var | Config Equivalent |
|---|---|
| `OSP_CORE_DB` | `dbLocation` |
| `OSP_REDIS_HOST` | `redisHost` |
| `OSP_REDIS_PORT` | `redisPort` |
| `OSP_REDIS_PASSWORD` | `redisPassword` |
| `OSP_CORE_SECRETKEY` | `secretKey` |
| `OSP_EJABBERD_ADMIN` | `ejabberdAdmin` |
| `OSP_EJABBERD_PASSWORD` | `ejabberdPass` |
| `OSP_EJABBERD_ADMINDOMAIN` | `ejabberdHost` |

---

## 18. Key Python Modules and Blueprints

### `functions/cachedDbCalls.py`
Wraps common DB queries in `@cache.memoize()` decorators (Flask-Caching / Redis). Used throughout to avoid redundant SELECT statements for frequently read data like system settings, channel info, and user data. Cache is invalidated explicitly when data changes.

### `functions/securityFunc.py`
- `check_isValidChannelViewer(channelID)` — core authorization check used by `/auth` endpoint and Jinja2 templates
- `check_isUserValidRTMPViewer(userID, channelID)` — RTMP viewer authorization
- `delete_user(userID)` — cascading user deletion (channels, videos, clips, invites, etc.)
- Uses per-process `globalvars.inviteCache` dict for hot-path invite caching

### `functions/socketio/`
All SocketIO event handlers, organized by domain:
- `connections.py` — connect/disconnect lifecycle
- `stream.py` — stream status events
- `video.py` — VOD events
- `xmpp.py` — XMPP/chat bridge events
- `edge.py` — edge node events
- `restream.py` — restream management events
- `rtmp.py` — RTMP control events

### `functions/ejabberdctl.py`
Python wrapper around ejabberd's XML-RPC API. Used to create/destroy XMPP rooms, register users, manage room membership.

### `classes/shared.py`
Creates the shared singleton objects that are initialized in `app.py` and reused everywhere:
```python
db = SQLAlchemy()
socketio = SocketIO()
limiter = Limiter(key_func=get_remote_address)
cache = Cache()
celery = Celery()
oauth = OAuth()
email = Mail()
```

---

## 19. ActivityPub / Federation

OSP implements ActivityPub to allow federation with Mastodon, Pleroma, and other Fediverse platforms. See `ACTIVITYPUB_README.md` for details.

- Channels are represented as `Group` actors
- Videos and streams are published as `Video` objects
- Federation endpoints: `/activitypub/actors/<username>`, `/activitypub/actors/<username>/inbox`, etc.
- WebFinger discovery: `/.well-known/webfinger`, `/.well-known/nodeinfo`
- Implemented in `blueprints/activitypub.py` and `functions/activitypub.py`
- ActivityPub data stored in `classes/activitypub.py` ORM models

---

## 20. Known Architecture Gotchas

### In-Memory State is Per-Worker
`globalvars.inviteCache`, `topicCache`, `restreamSubprocesses`, and `edgeRestreamSubprocesses` live only in one worker's memory. Sticky sessions (`nginx-sticky`) reduce the impact, but:
- A worker restart invalidates its cache entries
- Edge restream subprocesses must be on the worker that handled `/auth-user`; if that worker is killed, ffmpeg processes become orphaned

### Redis `flushdb()` on Startup
`app.py` calls `r.flushdb()` during initialization. With 11 workers starting simultaneously, each will call this — the guards `OSP_DB_INIT_HANDLER`, `OSP_XMPP_INIT_HANDLER`, `OSP_SYSTEM_FIXES_HANDLER` are set with 60-second TTLs to prevent duplicate initialization, but sessions are always lost on restart.

### nginx Auth Cache (10 Minutes)
If a channel's protection status changes (from public to protected, or an invite is revoked), the nginx auth cache will still return the old `200 OK` for up to 10 minutes. There is no cache invalidation mechanism from Flask to nginx.

### `/videos/temp` Was Publicly Accessible
Prior to a recent fix, the `/videos/temp` location had no `auth_request`, making partially-uploaded files accessible without authentication.

### `if` Blocks Replaced by `map` (Recent Change)
The `/ospAuth` location previously used chained `if` blocks to extract `$channelID`. These were replaced with `map` directives in `setup/nginx/upstream/osp-maps.conf` (runs at `http {}` level) to avoid nginx's fragile `if` evaluation rules. This file must be deployed alongside `osp-redirects.conf`.

### nginx.conf vs. Locations Deployment Gap
`installs/nginx-core/nginx.conf` is only deployed by `upgrade_nginxcore`. The locations files (`setup/nginx/locations/`) are deployed by `upgrade_osp`. These are separate upgrade steps — deploying one without the other can result in configuration that references undefined variables (as happened with `$ospChannelID` when `osp-maps.conf` was missing).

### ejabberd Domain Must Match OSP Config
The XMPP domain (`osp.internal` by default) must match across `ejabberd.yml`, `conf/config.py` (`ejabberdHost`), and the OSP admin settings. Mismatches prevent chat rooms from being created correctly.
