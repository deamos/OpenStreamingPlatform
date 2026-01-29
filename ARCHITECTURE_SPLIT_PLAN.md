# Flask Application Architecture Split Plan
## Separating API and Frontend for Improved Scalability

---

## Executive Summary

This document outlines a comprehensive plan to split the current monolithic Flask application into separate **API Backend** and **Frontend** services. This separation will improve scalability, allow independent deployment, enable better caching strategies, and support multiple frontend clients (web, mobile, etc.).

---

## 1. Current Architecture Analysis

### 1.1 Current Structure

The Flask application (`app.py`) currently serves both:
- **API endpoints** (via Flask-RESTX namespaces under `/apiv1`)
- **Frontend pages** (via Flask blueprints rendering Jinja2 templates)
- **WebSocket connections** (via Flask-SocketIO)
- **Static file serving** (CSS, JS, images)
- **Media streaming** (HLS m3u8 playlists, video files)

### 1.2 Current Blueprints Classification

#### **API-Only Blueprints** (Move to API Service)
- `blueprints/apiv1.py` - Main API blueprint with RESTX namespaces
  - `apis/server_ns.py` - Server information endpoints
  - `apis/channel_ns.py` - Channel management endpoints
  - `apis/stream_ns.py` - Stream management endpoints
  - `apis/video_ns.py` - Video management endpoints
  - `apis/clip_ns.py` - Clip management endpoints
  - `apis/topic_ns.py` - Topic management endpoints
  - `apis/user_ns.py` - User management endpoints
  - `apis/xmpp_ns.py` - XMPP chat endpoints
  - `apis/rtmp_ns.py` - RTMP configuration endpoints
- `blueprints/activitypub.py` - ActivityPub federation endpoints (JSON responses)
- `blueprints/m3u8.py` - HLS playlist generation (could stay in API or move to media service)

#### **Frontend-Only Blueprints** (Move to Frontend Service)
- `blueprints/root.py` - Main page, search, messages, notifications
- `blueprints/channels.py` - Channel listing and viewing pages
- `blueprints/profile.py` - User profile pages
- `blueprints/play.py` - Video playback pages
- `blueprints/liveview.py` - Live stream viewing pages
- `blueprints/clip.py` - Clip viewing pages
- `blueprints/streamers.py` - Streamer listing pages
- `blueprints/topics.py` - Topic listing pages
- `blueprints/upload.py` - Video upload pages
- `blueprints/settings/` - Settings pages (user, admin, channels)
- `blueprints/errorhandler.py` - Error page templates

#### **Hybrid/Shared Blueprints** (Requires Analysis)
- `blueprints/oauth.py` - OAuth authentication (handles both redirects and API)
- `blueprints/m3u8.py` - HLS playlists (served to players, could be API or media service)

#### **Special Endpoints** (Decision Required)
- `/auth` - Channel protection auth check (used by nginx/RTMP)
- `/rtmpCheck` - RTMP server routing (used by RTMP handler)
- `/xmpp` - XMPP BOSH proxy (used by chat system)
- `/proxy/*` - Proxy redirects for edge servers

### 1.3 Current Dependencies

#### **Shared Components** (Both services will need)
- `classes/` - SQLAlchemy models (Channel, User, Video, Stream, etc.)
- `functions/` - Business logic functions
  - `cachedDbCalls.py` - Database query caching
  - `database.py` - Database utilities
  - `securityFunc.py` - Security functions
  - `videoFunc.py` - Video processing
  - `channelFunc.py` - Channel management
  - `rtmpFunc.py` - RTMP management
  - `webhookFunc.py` - Webhook handling
  - `commentsFunc.py` - Comment management
  - `subsFunc.py` - Subscription management
  - `notifications.py` - Notification system
  - `activitypub.py` - ActivityPub federation
- `globals/globalvars.py` - Global variables
- `conf/` - Configuration management
- `migrations/` - Database migrations

#### **API-Specific Components**
- Flask-RESTX for API documentation
- API key authentication
- CORS configuration

#### **Frontend-Specific Components**
- Jinja2 templates (`templates/`)
- Static assets (`static/`)
- Flask-Security templates and forms
- Template filters (`functions/templateFilters.py`)
- Theme system (`functions/themes.py`)

#### **SocketIO Components** (Decision Required)
- `functions/socketio/` - Real-time event handlers
- Flask-SocketIO initialization
- Redis message queue for SocketIO

### 1.4 Current Authentication & Session Management

- **Flask-Security** for user authentication
- **Redis sessions** (`SESSION_TYPE = "redis"`)
- **Session cookies** (`ospSession`)
- **OAuth integration** (AuthLib)
- **Two-factor authentication** support
- **API key authentication** for API endpoints

---

## 2. Proposed Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Load Balancer / Nginx                     │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Frontend   │    │  API Service │    │ Media/Proxy  │
│   Service    │    │   (Flask)    │    │   Service    │
│  (Flask/     │    │              │    │  (Optional)  │
│   React/     │    │  - REST API  │    │              │
│   Vue/etc)   │    │  - SocketIO  │    │  - HLS       │
│              │    │  - Auth      │    │  - Video     │
│  - Templates │    │  - Webhooks  │    │  - Static    │
│  - Static    │    │              │    │              │
└──────────────┘    └──────────────┘    └──────────────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Database   │    │    Redis     │    │    Celery    │
│  (MySQL/     │    │              │    │              │
│  PostgreSQL) │    │  - Sessions  │    │  - Tasks     │
│              │    │  - Cache     │    │  - Beat      │
│              │    │  - SocketIO  │    │              │
└──────────────┘    └──────────────┘    └──────────────┘
```

### 2.2 Service Responsibilities

#### **API Service** (`api/`)
- **Purpose**: Backend API for all data operations
- **Technology**: Flask with Flask-RESTX
- **Responsibilities**:
  - RESTful API endpoints (`/apiv1/*`)
  - Authentication & authorization (JWT or session-based)
  - WebSocket/SocketIO connections
  - Webhook processing
  - ActivityPub federation endpoints
  - Business logic execution
  - Database operations
  - Celery task triggering
  - API documentation (Swagger)

#### **Frontend Service** (`frontend/`)
- **Purpose**: User-facing web interface
- **Technology Options**:
  - **Option A**: Flask (minimal) serving static files + templates (easiest migration)
  - **Option B**: React/Vue/Angular SPA (modern, better UX)
  - **Option C**: Next.js/Nuxt.js SSR (best SEO, modern)
- **Responsibilities**:
  - HTML page rendering (if SSR) or SPA hosting
  - Static asset serving (CSS, JS, images)
  - Client-side routing
  - API client integration
  - SocketIO client connections
  - Theme system
  - Form rendering (if using Flask templates)

### 2.3 Communication Between Services

#### **Frontend → API**
- **HTTP/REST**: All data operations via `/apiv1/*` endpoints
- **WebSocket**: Real-time updates via SocketIO (connect to API service)
- **Authentication**: 
  - **Option 1**: JWT tokens (stateless, better for microservices)
  - **Option 2**: Shared session store in Redis (simpler migration)

#### **API → Frontend**
- **API responses**: JSON data
- **WebSocket events**: Real-time notifications, chat, viewer counts, etc.

---

## 3. Detailed Migration Plan

### 3.1 Phase 1: Preparation & Setup

#### Step 1.1: Create Project Structure
```
flask-nginx-rtmp-manager/
├── api/                          # New API service
│   ├── app.py                    # API Flask app
│   ├── blueprints/
│   │   ├── apiv1.py              # Main API blueprint
│   │   └── apis/                 # API namespaces
│   ├── functions/                # Symlink or copy shared functions
│   ├── classes/                  # Symlink or copy shared classes
│   └── requirements.txt
├── frontend/                     # New frontend service
│   ├── app.py                    # Minimal Flask app (if Option A)
│   ├── templates/                # Jinja2 templates
│   ├── static/                   # Static assets
│   ├── src/                      # If using React/Vue (Option B/C)
│   └── requirements.txt
├── shared/                       # Shared code (or use symlinks)
│   ├── classes/                  # SQLAlchemy models
│   ├── functions/                # Business logic
│   └── globals/                  # Global variables
├── app.py                        # Original (keep for reference)
└── ... (existing structure)
```

#### Step 1.2: Extract Shared Code
- Create `shared/` directory or use symlinks
- Move shared components:
  - `classes/` → `shared/classes/`
  - `functions/` → `shared/functions/` (except template-specific)
  - `globals/` → `shared/globals/`
  - `conf/` → `shared/conf/`

#### Step 1.3: Set Up Configuration Management
- Create separate config files:
  - `api/config.py` - API-specific config
  - `frontend/config.py` - Frontend-specific config
  - `shared/config.py` - Shared config (database, Redis, etc.)

### 3.2 Phase 2: API Service Implementation

#### Step 2.1: Create API Flask App
- Create `api/app.py` based on current `app.py`
- **Keep**:
  - Database initialization
  - Redis configuration
  - Celery initialization
  - Flask-Security setup
  - SocketIO initialization
  - CORS configuration
  - API blueprints
- **Remove**:
  - Template rendering
  - Static file serving (except for API docs)
  - Frontend blueprints
  - Template filters (unless needed for API responses)

#### Step 2.2: Migrate API Blueprints
- Move `blueprints/apiv1.py` → `api/blueprints/apiv1.py`
- Move all `blueprints/apis/*` → `api/blueprints/apis/`
- Move `blueprints/activitypub.py` → `api/blueprints/activitypub.py`
- Update imports to use shared code

#### Step 2.3: Implement Authentication Strategy

**Recommended: JWT-based Authentication**

1. **Install JWT library**: `pyjwt` or `flask-jwt-extended`
2. **Create auth endpoints**:
   - `POST /apiv1/auth/login` - Login, returns JWT
   - `POST /apiv1/auth/logout` - Logout (if using refresh tokens)
   - `POST /apiv1/auth/refresh` - Refresh JWT token
   - `GET /apiv1/auth/me` - Get current user info
3. **Update API decorators**:
   - Create `@jwt_required` decorator
   - Replace `@login_required` with JWT validation
   - Maintain role-based access control

**Alternative: Shared Session Store**
- Keep Redis sessions
- Frontend and API share same Redis instance
- Frontend sets session cookie, API validates it
- Simpler but less scalable

#### Step 2.4: Handle SocketIO in API
- Keep SocketIO in API service (real-time is backend concern)
- Frontend connects to API SocketIO endpoint
- Update CORS to allow frontend origin
- SocketIO authentication via JWT or session

#### Step 2.5: Special Endpoints Decision

**Option A: Keep in API**
- `/auth` - Channel protection (used by nginx)
- `/rtmpCheck` - RTMP routing (used by RTMP handler)
- `/xmpp` - XMPP proxy (used by chat)

**Option B: Separate Service**
- Create `gateway/` service for these endpoints
- Or keep in API but document as internal endpoints

**Recommendation**: Keep in API initially, can extract later if needed.

### 3.3 Phase 3: Frontend Service Implementation

#### Step 3.1: Choose Frontend Technology

**Option A: Flask with Templates (Easiest Migration)**
- **Pros**: Minimal changes, templates work as-is, easy migration
- **Cons**: Still coupled to Flask, less modern
- **Best for**: Quick migration, maintaining current UX

**Option B: React/Vue/Angular SPA (Modern)**
- **Pros**: Modern, better UX, can use existing API
- **Cons**: Requires rewrite of templates, SEO challenges
- **Best for**: Long-term, modern stack

**Option C: Next.js/Nuxt.js SSR (Best of Both)**
- **Pros**: Modern, good SEO, server-side rendering
- **Cons**: Requires rewrite, new technology stack
- **Best for**: Production-ready, SEO-important sites

**Recommendation**: Start with **Option A** for easier migration, plan for **Option B/C** later.

#### Step 3.2: Create Frontend Flask App (Option A)
- Create `frontend/app.py` - minimal Flask app
- **Keep**:
  - Template rendering
  - Static file serving
  - Frontend blueprints
  - Template filters
  - Theme system
- **Remove**:
  - Database models (use API calls instead)
  - Business logic (call API)
  - SocketIO server (connect as client)
- **Add**:
  - API client helper functions
  - Session management (if using shared sessions)
  - Error handling for API failures

#### Step 3.3: Migrate Frontend Blueprints
- Move frontend blueprints to `frontend/blueprints/`
- **Update blueprints to use API**:
  - Replace database queries with API calls
  - Replace `render_template()` data fetching with API requests
  - Keep template rendering but fetch data from API

**Example Migration Pattern**:
```python
# OLD (root.py)
@root_bp.route("/")
def main_page():
    activeStreams = Stream.Stream.query.filter_by(active=True).all()
    recordedQuery = RecordedVideo.RecordedVideo.query.filter_by(...).all()
    return render_template("index.html", streamList=activeStreams, ...)

# NEW (frontend/blueprints/root.py)
@root_bp.route("/")
def main_page():
    # Fetch from API
    streams_response = requests.get(f"{API_URL}/apiv1/streams?active=true")
    videos_response = requests.get(f"{API_URL}/apiv1/videos?published=true&limit=16")
    
    activeStreams = streams_response.json()["results"]
    recordedVids = videos_response.json()["results"]
    
    return render_template("index.html", streamList=activeStreams, ...)
```

#### Step 3.4: Update Templates
- Templates remain mostly the same
- Update JavaScript to use API endpoints instead of direct database access
- Update SocketIO client to connect to API service
- Update form submissions to POST to API

#### Step 3.5: Handle Authentication in Frontend
- **If using JWT**:
  - Store JWT in localStorage or httpOnly cookie
  - Include in API requests: `Authorization: Bearer <token>`
  - Handle token refresh
- **If using shared sessions**:
  - Set session cookie on login
  - API validates session from cookie
  - Frontend includes session cookie in API requests

#### Step 3.6: Update Static Assets
- Move `static/` → `frontend/static/`
- Update JavaScript files to use API endpoints
- Update SocketIO client configuration
- Update API base URL configuration

### 3.4 Phase 4: SocketIO Migration

#### Step 4.1: SocketIO Architecture Decision

**Option A: SocketIO in API Only**
- API service runs SocketIO server
- Frontend connects to API SocketIO endpoint
- All real-time events handled by API
- **Recommended**: Simpler, centralized

**Option B: Separate SocketIO Service**
- Dedicated service for SocketIO
- Both API and Frontend connect to it
- **Not Recommended**: Adds complexity

#### Step 4.2: Update SocketIO Client
- Frontend JavaScript connects to API SocketIO URL
- Update connection URL in `static/js/*.js`
- Update authentication (JWT or session-based)

### 3.5 Phase 5: Testing & Validation

#### Step 5.1: Unit Testing
- Test API endpoints independently
- Test frontend templates with mock API responses
- Test authentication flows

#### Step 5.2: Integration Testing
- Test API + Frontend together
- Test SocketIO connections
- Test authentication end-to-end
- Test file uploads (if handled by API)

#### Step 5.3: Load Testing
- Test API scalability
- Test frontend scalability
- Test SocketIO under load

### 3.6 Phase 6: Deployment

#### Step 6.1: Docker Configuration
- Create `api/Dockerfile`
- Create `frontend/Dockerfile`
- Update `docker-compose.yml` to run both services
- Configure networking between services

#### Step 6.2: Nginx Configuration
- Update nginx config to route:
  - `/apiv1/*` → API service
  - `/socket.io/*` → API service (SocketIO)
  - `/static/*` → Frontend service
  - `/*` → Frontend service (pages)
- Configure CORS if needed
- Configure session cookie domain

#### Step 6.3: Environment Variables
- API service: Database, Redis, JWT secret, etc.
- Frontend service: API URL, SocketIO URL, etc.
- Shared: Database connection, Redis connection

---

## 4. Technical Considerations

### 4.1 Authentication Strategy Comparison

| Aspect | JWT Tokens | Shared Sessions |
|--------|-----------|----------------|
| **Scalability** | Excellent (stateless) | Good (requires Redis) |
| **Complexity** | Medium | Low |
| **Security** | Good (if implemented correctly) | Good |
| **Migration Effort** | Medium | Low |
| **Frontend Flexibility** | High (works with any client) | Medium (cookie-based) |
| **Recommendation** | ✅ **Best for long-term** | ✅ **Easier migration** |

**Recommendation**: Start with **shared sessions** for easier migration, migrate to **JWT** later for better scalability.

### 4.2 API Response Format

Standardize API responses:
```json
{
  "success": true,
  "results": { ... },
  "message": "Optional message",
  "errors": []
}
```

Error responses:
```json
{
  "success": false,
  "results": null,
  "message": "Error message",
  "errors": ["Detailed error 1", "Detailed error 2"]
}
```

### 4.3 CORS Configuration

API service must allow frontend origin:
```python
cors = CORS(app, resources={
    r"/apiv1/*": {
        "origins": [FRONTEND_URL],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-API-KEY"]
    },
    r"/socket.io/*": {
        "origins": [FRONTEND_URL],
        "supports_credentials": True
    }
})
```

### 4.4 File Upload Handling

**Option A: API Handles Uploads**
- Frontend uploads to API endpoint
- API processes and stores files
- **Recommended**: Centralized, secure

**Option B: Direct Upload**
- Frontend uploads directly to storage (S3, etc.)
- API receives metadata
- **Alternative**: For large files

### 4.5 Database Connection Pooling

- Both services need database access
- Configure connection pools appropriately
- Consider read replicas for frontend (if it needs DB access)

### 4.6 Caching Strategy

- **API Service**: Cache API responses (Redis)
- **Frontend Service**: Cache rendered templates (if SSR)
- **Shared Cache**: Use Redis for both services

### 4.7 Error Handling

- **API**: Return proper HTTP status codes and JSON error responses
- **Frontend**: Handle API errors gracefully, show user-friendly messages
- **Logging**: Centralized logging (consider ELK stack or similar)

---

## 5. Step-by-Step Implementation Guide

### Phase 1: Preparation (Week 1)

1. **Create directory structure**
   ```bash
   mkdir -p api/blueprints/apis frontend/blueprints shared
   ```

2. **Extract shared code**
   - Move `classes/` → `shared/classes/`
   - Move `functions/` → `shared/functions/`
   - Update imports in existing code

3. **Create configuration files**
   - `api/config.py`
   - `frontend/config.py`
   - `shared/config.py`

4. **Set up version control**
   - Create feature branch: `git checkout -b feature/api-frontend-split`

### Phase 2: API Service (Week 2-3)

1. **Create `api/app.py`**
   - Copy from `app.py`
   - Remove frontend-specific code
   - Keep API, database, SocketIO, Celery

2. **Migrate API blueprints**
   - Move `blueprints/apiv1.py` → `api/blueprints/`
   - Move `blueprints/apis/*` → `api/blueprints/apis/`
   - Move `blueprints/activitypub.py` → `api/blueprints/`

3. **Implement authentication**
   - Choose JWT or shared sessions
   - Create auth endpoints
   - Update API decorators

4. **Test API independently**
   - Use Postman/curl to test endpoints
   - Verify authentication works
   - Test SocketIO connections

### Phase 3: Frontend Service (Week 4-5)

1. **Create `frontend/app.py`**
   - Minimal Flask app
   - Template rendering only
   - Static file serving

2. **Migrate frontend blueprints**
   - Move frontend blueprints
   - Update to use API calls
   - Keep template rendering

3. **Update templates**
   - Update JavaScript for API calls
   - Update SocketIO client URL
   - Update form submissions

4. **Test frontend**
   - Verify pages load
   - Verify API integration works
   - Test authentication flow

### Phase 4: Integration (Week 6)

1. **Update SocketIO**
   - Verify frontend connects to API SocketIO
   - Test real-time features

2. **Update configuration**
   - Environment variables
   - Nginx configuration
   - Docker configuration

3. **End-to-end testing**
   - Test all user flows
   - Test authentication
   - Test real-time features
   - Test file uploads

### Phase 5: Deployment (Week 7)

1. **Docker setup**
   - Create Dockerfiles
   - Update docker-compose.yml

2. **Deploy to staging**
   - Test in staging environment
   - Monitor logs
   - Performance testing

3. **Deploy to production**
   - Gradual rollout
   - Monitor closely
   - Rollback plan ready

---

## 6. Migration Checklist

### Pre-Migration
- [ ] Backup database
- [ ] Document current API endpoints
- [ ] Document current frontend routes
- [ ] Create feature branch
- [ ] Set up development environment

### API Service
- [ ] Create `api/app.py`
- [ ] Migrate API blueprints
- [ ] Implement authentication
- [ ] Test API endpoints
- [ ] Test SocketIO
- [ ] Update API documentation

### Frontend Service
- [ ] Create `frontend/app.py`
- [ ] Migrate frontend blueprints
- [ ] Update templates for API calls
- [ ] Update JavaScript for API
- [ ] Update SocketIO client
- [ ] Test all pages

### Integration
- [ ] Test authentication flow
- [ ] Test SocketIO connections
- [ ] Test file uploads
- [ ] Test all user flows
- [ ] Performance testing

### Deployment
- [ ] Update Docker configuration
- [ ] Update Nginx configuration
- [ ] Update environment variables
- [ ] Deploy to staging
- [ ] Deploy to production
- [ ] Monitor and verify

---

## 7. Risk Mitigation

### Risk 1: Breaking Changes
- **Mitigation**: Keep original `app.py` as reference, gradual migration
- **Rollback**: Can revert to monolithic app if needed

### Risk 2: Authentication Issues
- **Mitigation**: Thoroughly test authentication, use shared sessions initially
- **Rollback**: Can fall back to session-based auth

### Risk 3: SocketIO Connection Issues
- **Mitigation**: Test SocketIO extensively, monitor connections
- **Rollback**: Can keep SocketIO in original app temporarily

### Risk 4: Performance Degradation
- **Mitigation**: Load testing, caching, connection pooling
- **Rollback**: Optimize or revert if needed

### Risk 5: Deployment Complexity
- **Mitigation**: Use Docker, comprehensive documentation
- **Rollback**: Keep deployment scripts for monolithic app

---

## 8. Future Enhancements

After successful split:

1. **Frontend Modernization**
   - Migrate to React/Vue/Angular SPA
   - Implement client-side routing
   - Better UX with modern frameworks

2. **API Improvements**
   - GraphQL endpoint (optional)
   - API versioning (`/apiv2/`)
   - Rate limiting per endpoint
   - API analytics

3. **Additional Services**
   - Media service for video streaming
   - Notification service
   - Search service (Elasticsearch)

4. **Microservices Evolution**
   - Further split API into domain services
   - Service mesh (Istio, Linkerd)
   - API gateway (Kong, Ambassador)

---

## 9. Estimated Timeline

- **Phase 1 (Preparation)**: 1 week
- **Phase 2 (API Service)**: 2-3 weeks
- **Phase 3 (Frontend Service)**: 2-3 weeks
- **Phase 4 (Integration)**: 1 week
- **Phase 5 (Deployment)**: 1 week

**Total**: 7-9 weeks for complete migration

---

## 10. Resources & References

### Documentation to Review
- Flask-RESTX documentation
- Flask-SocketIO documentation
- JWT authentication best practices
- CORS configuration
- Docker multi-service setup

### Tools
- Postman/Insomnia for API testing
- Docker Compose for local development
- Nginx for reverse proxy
- Redis for sessions/cache

---

## Conclusion

This plan provides a comprehensive roadmap for splitting the Flask application into separate API and frontend services. The phased approach allows for gradual migration with minimal risk, while maintaining the ability to roll back if needed.

**Key Recommendations**:
1. Start with shared sessions for easier migration
2. Keep SocketIO in API service
3. Use Flask templates initially (Option A), plan for SPA later
4. Thoroughly test each phase before proceeding
5. Maintain original app as reference during migration

**Next Steps**:
1. Review and approve this plan
2. Set up development environment
3. Begin Phase 1 (Preparation)
4. Regular checkpoints to review progress


