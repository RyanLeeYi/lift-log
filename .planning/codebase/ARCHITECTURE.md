<!-- refreshed: 2026-08-19 -->
# Architecture

**Analysis Date:** 2026-08-19

## System Overview

Lift-log is a multi-platform workout logging system with a shared Python/FastAPI backend, vanilla JavaScript PWA frontend, and Capacitor-wrapped Android app. Architecture centers on a service layer pattern that encapsulates all business logic, with separation between multi-tenant control (user accounts, auth) and single-tenant data (workout records per user).

```text
┌────────────────────────────────────────────────────────────────┐
│                   Presentation Layer                            │
├────────────────────┬──────────────────┬───────────────────────┤
│  PWA (Web)         │  Android App     │  Admin/CLI            │
│  `app/static/js`   │  `android/`      │  `scripts/`           │
│  Vanilla JS        │  Capacitor       │  Python migration     │
│  No framework      │  WebView wrapper │  & backup tools       │
└────────────┬───────┴────────┬─────────┴──────────┬────────────┘
             │                │                    │
             └────────────────┴────────────────────┘
                      HTTP/JSON
              ┌────────────────────────────┐
              │    FastAPI Backend         │
              │    `app/main.py`           │
              ├────────────────────────────┤
              │   Middleware Stack:        │
              │  • CORS (Capacitor)        │
              │  • Request logging         │
              │  • Session/cookie sliding  │
              │  • MCP path normalization  │
              └────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
        ▼             ▼             ▼
┌──────────────┐ ┌──────────────┐ ┌──────────┐
│  API Layer   │ │  MCP Layer   │ │ Static   │
│ `app/api/`   │ │ `app/mcp.py` │ │ Files    │
│ REST routes  │ │ Claude tools │ │ `static/ │
└──────┬───────┘ └──────────────┘ └──────────┘
       │
       ▼
┌────────────────────────────────────────────┐
│       Service Layer (Domain Logic)         │
│       `app/services/`                      │
├────────────────────────────────────────────┤
│ • workouts: logging, batch operations      │
│ • exercises: name resolution, history      │
│ • sync: cross-device conflict resolution   │
│ • body_metrics: weight/body fat tracking   │
│ • schedule: weekly template projection     │
│ • stats: tonnage, volume calculations      │
│ • templates: workout program management    │
│ • auth: session, token, CSRF handling      │
│ • quota: per-user rate limiting            │
│ • account: export, deletion, tombstoning   │
└────────────┬───────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────┐
│      Data Layer                            │
├────────────────────────────────────────────┤
│  Control DB (control.db — SQLite)          │
│  `app/control_models.py`                   │
│  • Users (Google OAuth sub)                │
│  • Devices (cross-device tracking)         │
│  • Auth Sessions (access tokens, CSRF)     │
│  • MCP Tokens (Claude integration)         │
│  • Account Tombstones (deletion tracking)  │
│                                            │
│  Per-User Data DBs (user_*.db — SQLite)    │
│  `app/models.py`                           │
│  • Workouts, WorkoutSets                   │
│  • Exercises, Templates                    │
│  • BodyMetrics, DailyStatus                │
│  • PushSubscriptions                       │
│  • AppSettings, sync metadata              │
└────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| FastAPI app | HTTP server, middleware, router registry, error handling | `app/main.py` |
| API routers | HTTP endpoint handlers, request parsing, response formatting | `app/api/*.py` (auth, workouts, exercises, etc.) |
| Service layer | Business logic isolation, DB queries, constraint enforcement | `app/services/*.py` |
| Models (ORM) | SQLAlchemy domain objects, schema definition, validation | `app/models.py` (data), `app/control_models.py` (control) |
| Auth service | Session resolution, token verification, CSRF protection, rate limiting | `app/services/auth.py` |
| Sync service | Cross-device conflict resolution, version tracking, tombstone handling | `app/services/sync.py` |
| Workouts service | Set logging, batch operations, idempotency, volume calculations | `app/services/workouts.py` |
| MCP integration | Claude-specific tools for workout query, read-only & write modes | `app/mcp.py` |
| Frontend | PWA shell, state management, offline queue, UI rendering | `app/static/js/app.js` (main), various feature modules |
| Android wrapper | Capacitor bridge to native notifications, sync, APK self-update | `android/app/` |
| Migrations | Schema evolution, partial unique index additions, backfills | `app/migrations.py` |
| Config | Environment loading, secrets, path resolution | `app/config.py` |

## Pattern Overview

**Overall:** Layered architecture with service encapsulation and multi-tenant isolation

**Key Characteristics:**
- **Service-driven queries:** API routers never write SQL; all DB access goes through `app/services/` (single source of truth for each domain)
- **Async-first async handling:** FastAPI endpoints use async; services are sync-on-sync to match SQLAlchemy ORM (v2.0)
- **Multi-tenant control plane:** Shared `control.db` holds users, devices, auth sessions; per-user `user_*.db` files hold isolated workout data (symbiotic: control DB enables multi-device sync, data DBs enable data isolation)
- **Conflict-free sync:** Offline queue + server-side version tracking + tombstone soft-deletes enable merge-free sync (Preston platform semantics)
- **Vanilla frontend:** No framework, no bundler, no npm build step (PWA loaded directly from `app/static/`); state held in module-level variables and IndexedDB
- **Capacitor wrapper:** Android shell loads web assets from APK; bridge enables native notifications, file system access, local notifications polling
- **Cross-platform consistency:** Same API serves web and mobile; client differentiation only for native capabilities (rest notify, sync timing)

## Layers

**HTTP & Middleware:**
- Purpose: Request routing, cross-cutting concerns (CORS, logging, session management)
- Location: `app/main.py`
- Contains: FastAPI app creation, middleware setup, router registration
- Depends on: Settings, Control DB session factory, Google token verifier
- Used by: All clients (web, mobile, MCP)

**API Layer (REST Endpoints):**
- Purpose: Parse HTTP requests, validate input schemas, call services, format responses
- Location: `app/api/` (auth, workouts, exercises, stats, templates, body_metrics, daily_status, push, schedule, sync, account, mcp_tokens, app_release, settings)
- Contains: FastAPI route handlers, dependency injection (session, auth)
- Depends on: Service layer, schema validation (Pydantic), auth dependencies
- Used by: HTTP clients (PWA, Android WebView, external integrations)

**Service Layer (Business Logic):**
- Purpose: Encapsulate domain logic, query composition, constraint enforcement, cross-domain coordination
- Location: `app/services/`
- Contains: One module per domain (workouts, exercises, auth, sync, stats, etc.); domain errors, workflows, calculations
- Depends on: Models (ORM), config, cross-service imports (workouts→exercises, sync→projections)
- Used by: API routers, MCP tools, migration scripts, admin CLI

**Data Layer (Persistence):**
- Purpose: ORM models and database access primitives
- Location: `app/models.py` (per-user data), `app/control_models.py` (control plane), `app/db.py` (session factories, path management)
- Contains: SQLAlchemy declarative models, table definitions, relationships, indexes
- Depends on: SQLAlchemy, config (DB paths)
- Used by: Services (queries), migrations (schema creation)

**Auth & Control Plane:**
- Purpose: Multi-tenant isolation, session management, user quota, MCP token lifecycle
- Location: `app/services/auth.py` (session resolution, CSRF, rate limiting), `app/control_db.py` (control session factory), `app/control_models.py` (control schema)
- Contains: User lookup, device tracking, auth session lifecycle, token hashing, quota enforcement per user per day
- Depends on: Control DB, Google OAuth SDK
- Used by: All endpoints (via `require_domain_auth` or `resolve_request_session` dependency), MCP layer

**Frontend (PWA):**
- Purpose: Single-page workout logging, offline capability, sync management
- Location: `app/static/js/`
- Contains: DOM management, state machine, offline queue, service worker, API client
- Depends on: Vanilla JS APIs, IndexedDB, fetch
- Used by: Browser, Capacitor WebView

**MCP Integration:**
- Purpose: Allow Claude and other AI agents to query workout data via remote procedure calls
- Location: `app/mcp.py`
- Contains: Tool definitions (get_workouts, search_exercises, body_metrics), read-only & write mode token validation
- Depends on: Service layer, control DB (token lookup)
- Used by: Claude via MCP client libraries

## Data Flow

### Primary Request Path (Web/Mobile User)

1. **Client initiates** (`app/static/js/app.js` or Android WebView) → calls `api.js` with fetch
2. **Request enters** (`app/main.py`) → middleware chain (CORS, logging, session sliding)
3. **Route match** (`app/api/<feature>.py`) → resolver extracts auth session via `resolve_request_session` dependency
4. **Authorization check** (`app/api/deps.py::require_domain_auth`) → validates user token or web cookie, loads device context
5. **Service call** (API endpoint) → calls `app/services/<domain>.py` function with validated session/user
6. **DB query** (Service) → SQLAlchemy ORM on per-user `session_factory()`, may also read from control DB
7. **Response format** (API endpoint) → Pydantic model validation, HTTP response
8. **Middleware egress** → session sliding cookie set (via `slide_web_session_cookie` middleware)
9. **Client receives** → JSON payload, updates local state/IndexedDB, re-renders UI

### Offline Queue + Sync

1. **Offline set logged** → `queue.js` enqueues set (client_uuid, workout date, exercise, reps, weight, RPE)
2. **Connectivity restored** → `native-sync.js` (Android) or `sync.js` (Web PWA) triggers `/api/sync` endpoint
3. **Sync endpoint** (`app/api/sync.py`) → calls `services/sync.py` batch processor
4. **Conflict detection** → Sync service compares `version`, `deleted_at`, `owner_device_id`, `lease_generation`
5. **Merge or reject** → If no conflict, set inserted/updated; if conflict, returned in conflict list for user resolution
6. **Queue flush** → Successful sets removed; conflicts kept for manual resolution UI
7. **Projection updated** → Schedule, stats refresh on next request

### MCP Query (Claude Integration)

1. **Claude calls MCP tool** (e.g., `get_workouts`) via HTTP POST to `/mcp/`
2. **MCP router** (`app/mcp.py`) → validates token hash from control DB
3. **Tool execution** → calls service (e.g., `services/workouts.py::list_workouts`)
4. **Response** → JSON with workout summaries, sets filtered by read-only flag if applicable

**State Management:**
- **Control DB:** Persistent across restarts; holds user identities, session tokens, quotas, MCP token hashes (never plaintext)
- **Per-user DBs:** Each user has isolated SQLite file; contains all workout data, templates, settings
- **Frontend state:** Module-level variables (current workout, template cache, offline queue); also IndexedDB for persistence
- **Session state:** Transient; held in control DB (AuthSession table) with TTL; extends via sliding cookie on each request

## Key Abstractions

**Sync Entity:**
- Purpose: Represent versioned, deletable records that sync across devices
- Examples: `Workout`, `WorkoutSet`, `BodyMetric`, `DailyStatus`, `Exercise`, `Template`, `AppSetting`
- Pattern: Mixin class `SyncColumns` with `sync_id`, `version`, `deleted_at`; queries always filter `deleted_at IS NULL`

**Domain Error Hierarchy:**
- Purpose: Communicate constraint violations to clients without leaking implementation details
- Examples: `NotFoundError`, `ConflictError`, `UnknownExerciseError`, `DomainError`, `RateLimitError`
- Pattern: Subclass `DomainError`; API error handler converts to HTTP 4xx/5xx with safe detail message

**AuthSession & Device:**
- Purpose: Enable multi-device login without server-side session store (stateless except control DB)
- Examples: Same user logged into web browser + Android app; both have access tokens, can sync in parallel
- Pattern: Token-based auth; each device registers itself; session tied to user+device pair for rate limit isolation

**Schedule Projection:**
- Purpose: Calculate "which template fires today?" based on template weekday assignments
- Examples: Monday → Template A, Wednesday → Template B
- Pattern: Pure function in `services/schedule.py`; idempotent, no side effects

**WorkoutSet Idempotency:**
- Purpose: Batch set writes (offline queue flush) don't duplicate if retried
- Examples: `idem_key` = sha256(workout_date | exercise_id | set_number)
- Pattern: Unique index on `idem_key` (partial, where `deleted_at IS NULL`) prevents duplicate inserts

**Rate Limiting:**
- Purpose: Protect API from abuse; per-user quota + global domain quota
- Examples: Auth endpoint has burst limit (60 req/min per IP), daily mutation quota (configurable per user/day)
- Pattern: `AuthRateLimiter` class with time-window bucketing; key is IP for auth, user_id for mutations

## Entry Points

**HTTP Server:**
- Location: `app/main.py::app_factory()`
- Triggers: `uvicorn app.main:app_factory --factory --reload`
- Responsibilities: Load config, initialize DBs, create FastAPI app, register middlewares, mount routers, start lifespan

**Static Files (PWA):**
- Location: `app/static/index.html` (mounted at `/`)
- Triggers: Browser navigation to `https://liftlog.example.com/`
- Responsibilities: Serve HTML shell, trigger service worker registration, boot frontend state machine

**Android App:**
- Location: `android/app/src/main/java/.../MainActivity.kt` (Capacitor entry)
- Triggers: User launches app from home screen
- Responsibilities: Initialize WebView, load `index.html` from APK assets, bridge native capabilities (notifications, sync timing)

**MCP Server:**
- Location: `app/mcp.py::create_mcp()`
- Triggers: Instantiated during app startup; exposed at `/mcp` mount
- Responsibilities: Register Claude-compatible tools, validate tokens, dispatch to services

## Architectural Constraints

- **Threading:** Python async/await at HTTP layer (FastAPI), but services are synchronous (SQLAlchemy v2.0 ORM is sync-on-sync). No worker threads; SQLite is single-writer, locks serialize concurrent schema changes.
- **Global state:** `app.state` holds session factories, settings, rate limiters, verifiers (configured once at startup). No module-level singletons except lazy-initialized Google token verifier cache (thread-safe).
- **Circular imports:** Avoided via careful layering (services don't import API routers; API doesn't import other API modules). Cross-service calls (workouts→exercises) are intra-layer.
- **Single writer:** SQLite enforces one writer at a time; multi-device sync is coordinated via `version` + `deleted_at` + server-side conflict detection, not optimistic locking.
- **Offline-first queue:** Frontend enqueues mutations locally; server accepts them in any order during sync (idempotency key prevents duplication).
- **No ORM N+1:** Services explicitly manage relationships (query templates with exercises in one statement via eager load or separate bulk query).

## Anti-Patterns

### Writing SQL in API Routers

**What happens:** Some legacy code directly calls SQLAlchemy `.select()` in API endpoint functions instead of routing through service layer.

**Why it's wrong:** 
- Query logic duplicates across endpoints (set search in workouts + exercise detail + sync all query the same way)
- Constraint changes force updates in multiple places
- Business logic (e.g., "never show soft-deleted sets") gets forgotten in one endpoint

**Do this instead:** All queries live in `app/services/`. API routers call service functions. Example:
```python
# ✗ Don't: app/api/workouts.py
def get_workout(workout_id: int, session: DbSession):
    return session.execute(select(Workout).where(Workout.id == workout_id)).scalar_one()

# ✓ Do: app/api/workouts.py
def get_workout(workout_id: int, session: DbSession):
    return svc.get_workout(session, workout_id)

# In app/services/workouts.py:
def get_workout(session: Session, workout_id: int) -> Workout:
    w = session.execute(select(Workout).where(Workout.id == workout_id)).scalar_one()
    if w.deleted_at is not None:
        raise NotFoundError("workout not found")
    return w
```

### Skipping CSRF on Web Routes

**What happens:** A route that mutates (POST/PUT/PATCH) accepts requests without validating the CSRF token from the web session.

**Why it's wrong:**
- Cross-site request forgery: malicious site can trick browser into modifying the user's data
- Legacy single-user mode had a blanket exemption; multi-user mode (F149) requires it everywhere

**Do this instead:** Use `require_domain_auth` dependency which validates CSRF for web sessions:
```python
# ✓ Do: app/api/workouts.py
@router.post("/workouts", dependencies=[Depends(require_domain_auth)])
def log_workout(data: LogWorkoutIn, session: DbSession):
    ...
```

### Unbounded Query Results

**What happens:** Service queries all matching sets/workouts without limit, then paginates in Python instead of SQL.

**Why it's wrong:**
- OOM on large datasets (e.g., user with 50k sets)
- Network lag if materializing all rows to client
- Cache inefficiency

**Do this instead:** Use LIMIT/OFFSET or cursor pagination in SQLAlchemy:
```python
# ✓ Do: app/services/workouts.py
def workouts_for_range(session: Session, user_date_from: date, user_date_to: date, limit: int = 1000):
    stmt = (
        select(Workout)
        .where((Workout.date >= user_date_from) & (Workout.date <= user_date_to))
        .order_by(Workout.date.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))
```

### Hardcoding Numbers in Frontend

**What happens:** Retry count, timeouts, debounce intervals are magic numbers scattered in JS files.

**Why it's wrong:**
- No single place to tune behavior
- Easy to accidentally change in one place and forget others
- Complicates testing

**Do this instead:** Constants at top of module:
```javascript
// ✓ Do: app/static/js/api.js
const MAX_RETRIES = 3;
const TIMEOUT_MS = 10000;
const DEBOUNCE_MS = 500;

async function fetchWithRetry(...) {
    // use MAX_RETRIES
}
```

---

*Architecture analysis: 2026-08-19*
