# External Integrations

**Analysis Date:** 2026-08-19

## APIs & External Services

**Google OAuth 2.0:**
- Service: Google Identity Services for user authentication
- SDK/Client: `google-auth[requests]` 2.55+, `google.oauth2.id_token` module
- Location: `app/services/auth.py::google_verifier()` (lines 76-99)
- Flow: Web/native app submits Google ID token → server calls `verify_oauth2_token()` via `app/services/auth.py`
- Auth: `LIFTLOG_GOOGLE_CLIENT_ID` env var (Google OAuth client ID, required for authentication)
- Rate limiting: In-memory per-IP rate limiter in `app/api/auth.py::AuthRateLimiter` (10 attempts per 60 seconds)
- Fallback: If client ID missing, Google login disabled; only demo token mode available (F149)

**Web Push Protocol (VAPID):**
- Service: Browser push notifications via Web Push API (RFC 8188)
- SDK/Client: `pywebpush` 2.3+ library
- Location: `app/services/push.py::_send_one()` (lines 37-49)
- Implementation: Async notification sending to subscribed devices
- Auth: VAPID keypair (asymmetric cryptography):
  - `LIFTLOG_VAPID_PRIVATE_KEY` - PKCS8 DER base64url (stored in `.env`)
  - `LIFTLOG_VAPID_PUBLIC_KEY` - Base64url compressed public key (sent to frontend for subscription)
  - `LIFTLOG_VAPID_SUBJECT` - VAPID claims subject (default: `mailto:admin@example.com`)
- Feature: Rest timer notifications (`app/api/push.py::rest_timer()`, F31)
- Limitations: Feature disabled if either VAPID key missing; graceful degradation (rest timer still works, just no notification)

**MCP (Model Context Protocol) for AI Agents:**
- Service: Remote tool server for Claude, ChatGPT, Gemini to query training data
- SDK/Client: `fastmcp` 2.0+ (custom MCP server implementation)
- Location: `app/mcp.py` (entire file, 250+ lines)
- Endpoints:
  - Query tools: `query_exercises`, `query_workouts`, `query_body_metrics`, `query_daily_status`, `query_stats`
  - Write tools: `log_workout`, `log_daily_status`, `log_body_metric`
- Mount point: `/mcp` path in FastAPI app (`app/main.py::MCP_MOUNT`)
- Auth mechanisms (two types):
  1. **Legacy token** - Single shared Bearer token (`settings.token`, `LIFTLOG_TOKEN` env var)
  2. **User MCP tokens** (F147) - Per-user API keys with scopes (read/write), verified against `control.db` user registry
- Token verification: `app/services/mcp_tokens.resolve_token()`
- Tools reuse services layer (no duplicate query logic): `app/services/workouts.py`, `app/services/body_metrics.py`, etc.

## Data Storage

**Databases:**

**Primary Data (SQLite):**
- Type: SQLite 3
- Connection: `sqlite:///` URI with WAL mode enabled
- Client: SQLAlchemy 2.0+ ORM
- Path: `LIFTLOG_DB` env var (default: `./liftlog.db`)
- Schema: `app/models.py` (Exercise, Template, Workout, Set, BodyMetric, DailyStatus, PushSubscription)
- Migrations: `app/migrations.py` (schema evolution, F154 sync IDs)
- Config: `app/db.py::make_engine()` enables:
  - Foreign key constraints
  - 5-second busy timeout
  - Write-Ahead Log (WAL) journal mode for concurrent access

**Control Database (SQLite):**
- Type: SQLite 3 (separate from data DB)
- Path: `LIFTLOG_CONTROL_DB_PATH` (default: `./control.db`)
- Purpose: User registry, auth sessions, refresh tokens, account tombstones
- Schema: `app/control_models.py` (User, AuthSession, RefreshToken, Device, AccountTombstone)
- Lifecycle: Created at startup via `app/main.py::initialize_data_db()`

**Per-User Databases:**
- Type: SQLite 3 (isolated per user for multi-user support)
- Path: `{LIFTLOG_USER_DATA_DIR}/{uuid}.db`
- Purpose: Each user's workouts, exercises, metrics isolated from others
- Isolation: Path validation in `app/db.py::canonical_user_db_path()` prevents directory traversal
- Creation: On first user data initialization by `app/services/` functions

**File Storage:**

**Static Assets:**
- Location: `app/static/` directory
- Served by: FastAPI StaticFiles middleware in `app/main.py`
- Content: HTML, CSS, JavaScript for PWA frontend (no external CDN)
- Mount point: `/` root path

**Release APKs:**
- Location: `LIFTLOG_RELEASE_DIR` env var (default: `./release/`)
- Purpose: App self-update mechanism (F67)
- Format: Filename pattern `lift-log-v<N>.apk` served for mobile app download
- Logic: `app/api/app_release.py` scans directory for latest version

**Data Directory (Docker Volume):**
- Path: `/data/` (inside container)
- Mounted from: `lift-log-data` Docker volume (persists across restarts)
- Contains: `liftlog.db`, `control.db`, `users/` directory, `release/` subdirectory

## Authentication & Identity

**Auth Provider:**
- Type: Google OAuth 2.0 + custom session-based auth
- Implementation approach:
  1. **Native/Web Login**: User submits Google ID token to `/api/auth/google-login` (`app/api/auth.py`)
  2. **Token Verification**: Server verifies token signature against Google's public keys via `app/services/auth.py::google_verifier()`
  3. **User Lookup/Creation**: If valid, creates/updates user record in `control.db`
  4. **Session Issuance**: Returns access token + optional refresh token + web session cookie
- Session Types:
  - **Access tokens** (15-minute TTL): JWT-like tokens for API authentication
  - **Refresh tokens** (90-day absolute TTL, 30-day idle TTL): Persisted in `control.db` for long-lived sessions (F156)
  - **Web session cookies** (12-hour TTL): Secure, HttpOnly cookies for web frontend
- CSRF Protection:
  - Token derived from: `HMAC(secret_key, session_id)`
  - Secret key source: `LIFTLOG_SECRET_KEY` env var OR generated and persisted in `control.db`
  - Validated by: `app/services/auth.py::csrf_for_session()` and `app/api/deps.py`

**Legacy Demo Mode:**
- Token: Single shared Bearer token stored in `LIFTLOG_TOKEN` env var
- Scope: Entire system operates as single-user if legacy token provided
- Disabling: If `LIFTLOG_TOKEN` left empty (F149), legacy routes disabled and Google login required
- Verification: Simple `secrets.compare_digest()` in `app/mcp.py`

**MCP Token Auth (F147):**
- Type: Per-user API keys with scopes (read or write)
- Storage: `control.db` (MCP tokens table)
- Verification: `app/services/mcp_tokens.resolve_token()` → returns user ID and scope
- Scope enforcement: MCP tools check token scope before allowing mutations

## Monitoring & Observability

**Error Tracking:**
- Type: None integrated (logging only)
- Approach: Application-level exception handlers in `app/errors.py`
- Error responses: Structured JSON with error type and message

**Logs:**
- Approach: Python `logging` module + uvicorn access logs
- Output: Console (stdout for Docker)
- Coverage: API request/response, auth events, MCP operations, push notifications
- No external log aggregation service

## CI/CD & Deployment

**Hosting:**
- Primary: Self-hosted via Docker (no cloud provider hardcoded)
- Production deployment: `docker-compose.yml` or manual Docker container
- Port: 8000 (HTTP on host 0.0.0.0)
- APK distribution: Manual upload to Google Drive for mobile app versions

**CI Pipeline:**
- Type: None automated (local development only)
- Testing: Manual via `uv run pytest` for unit/integration tests, Playwright E2E scripts
- Linting: Manual via `uv run ruff check .` and `uv run ruff format`
- Build: Local development + Capacitor CLI for Android APK

**Docker Build:**
- Base image: `python:3.12-slim` (small footprint)
- Builder: Copies `uv` binary from official `ghcr.io/astral-sh/uv:latest` image
- Layers:
  1. Install uv package manager
  2. Copy `pyproject.toml` + `uv.lock` (cacheable)
  3. Run `uv sync --frozen --no-dev` (production deps only)
  4. Copy app source (`app/` directory)
  5. Expose port 8000
  6. Run: `uvicorn app.main:app_factory --factory --host 0.0.0.0 --port 8000`

**Mobile APK Build:**
- Tool: Capacitor CLI 8.4.2 + Android Gradle
- Steps:
  1. Web assets copied from `app/static/` to Capacitor project
  2. `npx cap sync android` updates Android project
  3. `./android/gradlew.bat -p android assembleRelease` builds APK
  4. Output: `android/app/build/outputs/apk/prod/release/app-prod-release.apk`
  5. Manual upload to Google Drive (release management)

## Environment Configuration

**Required env vars:**
- `LIFTLOG_GOOGLE_CLIENT_ID` - Google OAuth audience (public, not secret)
- `LIFTLOG_VAPID_PRIVATE_KEY` - Web Push signing key (sensitive)
- `LIFTLOG_VAPID_PUBLIC_KEY` - Web Push public key (shared with frontend)

**Optional env vars:**
- `LIFTLOG_TOKEN` - Demo mode shared token (if set, enables legacy Bearer auth; if empty, Google login only)
- `LIFTLOG_SECRET_KEY` - CSRF/session secret (auto-generated if missing, persisted in control.db)
- `LIFTLOG_DB` - Data DB path (default: `./liftlog.db`)
- `LIFTLOG_CONTROL_DB_PATH` - Control DB path (default: `./control.db`)
- `LIFTLOG_USER_DATA_DIR` - User DB directory (default: `./users/`)
- `LIFTLOG_RELEASE_DIR` - APK release directory (default: `./release/`)
- `LIFTLOG_ENV_LABEL` - Display label: `prod` or `dev` (default: `prod`)

**Secrets location:**
- Development: `.env` file (gitignored, template: `.env.example`)
- Production (Docker): Environment variables passed via `.env` file or compose `environment:` section
- Never stored: In source code, version control, or container image

**Docker-specific overrides:**
- `LIFTLOG_DB=/data/liftlog.db` (volume mount)
- `LIFTLOG_CONTROL_DB_PATH=/data/control.db`
- `LIFTLOG_USER_DATA_DIR=/data/users`
- `LIFTLOG_RELEASE_DIR=/data/release`

## Webhooks & Callbacks

**Incoming Webhooks:**
- Google OAuth callback: Not explicitly handled (token verification is one-way)
- Web Push: No incoming webhooks (subscription management via `/api/push/subscribe`)

**Outgoing Webhooks:**
- Web Push notifications: Sent to subscribed endpoints via Push Service API (browser control, not our server)
- MCP tools: No outgoing webhooks; AI agents query via HTTP POST to `/mcp` endpoint

---

*Integration audit: 2026-08-19*
