# Codebase Structure

**Analysis Date:** 2026-08-19

## Directory Layout

```
lift-log/
├── app/                          # Python FastAPI backend
│   ├── __init__.py
│   ├── main.py                   # Entry point: app_factory(), app_with_seed()
│   ├── config.py                 # Settings class, env var loading
│   ├── db.py                     # Session factories, DB initialization, path management
│   ├── models.py                 # SQLAlchemy ORM: Workout, WorkoutSet, Exercise, Template, etc.
│   ├── schemas.py                # Pydantic request/response models
│   ├── errors.py                 # Domain error classes (NotFoundError, ConflictError, etc.)
│   ├── migrations.py             # Schema evolution, index backfills
│   ├── mcp.py                    # MCP server setup, Claude-compatible tools
│   ├── control_db.py             # Control DB session factory, secret management
│   ├── control_models.py         # SQLAlchemy ORM: User, Device, AuthSession, McpToken, etc.
│   ├── sync_models.py            # Sync-related Pydantic models
│   ├── seed.py                   # Seed exercises into DB
│   │
│   ├── api/                      # REST endpoint handlers
│   │   ├── __init__.py
│   │   ├── deps.py               # Dependency injection: require_domain_auth, resolve_request_session, DbSession
│   │   ├── auth.py               # POST /api/auth/* (signin, refresh, logout, rate limiting)
│   │   ├── workouts.py           # POST/GET /api/workouts (log, search, batch, sync preview)
│   │   ├── exercises.py          # GET/POST /api/exercises (search, history, last sets)
│   │   ├── stats.py              # GET /api/stats (tonnage, volume, max weight)
│   │   ├── templates.py          # GET/POST /api/templates (CRUD workout programs)
│   │   ├── body_metrics.py       # GET/POST /api/body-metrics (weight, body fat)
│   │   ├── daily_status.py       # GET/POST /api/daily-status (energy, sleep, notes)
│   │   ├── push.py               # POST /api/push/* (subscribe, test notification)
│   │   ├── schedule.py           # GET /api/schedule (today's workout, weekly progress)
│   │   ├── settings.py           # GET/PUT /api/settings (weekly target days, etc.)
│   │   ├── sync.py               # POST /api/sync (batch workout write + conflict detection)
│   │   ├── account.py            # GET/POST /api/account (export, delete, tombstone)
│   │   ├── mcp_tokens.py         # GET/POST /api/mcp-tokens (CRUD Claude integration tokens)
│   │   └── app_release.py        # GET /api/app-release (APK version check, download)
│   │
│   ├── services/                 # Business logic layer (single source of truth)
│   │   ├── __init__.py
│   │   ├── auth.py               # Session resolve, token verify, CSRF, rate limit, Google OAuth
│   │   ├── workouts.py           # Log sets, batch write, dry-run preview, exercise name resolution
│   │   ├── exercises.py          # Create/search exercises, muscle group, name normalization
│   │   ├── stats.py              # Tonnage, max weight, volume, personal records
│   │   ├── templates.py          # CRUD templates, exercise reordering, weekday assignment
│   │   ├── body_metrics.py       # Weight/body fat tracking, latest, time series
│   │   ├── daily_status.py       # Energy, sleep quality, per-day notes
│   │   ├── push.py               # Web Push subscription, send notifications
│   │   ├── schedule.py           # Template→weekday projection, today's schedule
│   │   ├── settings.py           # Key/value app settings (weekly target, units, etc.)
│   │   ├── sync.py               # Batch merge, conflict detection, version tracking, tombstone
│   │   ├── account.py            # Export SQL dump, delete account, tombstone marking
│   │   ├── history.py            # Exercise history aggregation, time-range queries
│   │   ├── projection.py         # Workout set projection (inline totals, exercise history)
│   │   ├── quota.py              # Daily mutation counter, rate limit enforcement
│   │   └── mcp_tokens.py         # MCP token CRUD, hash validation, expiry check
│   │
│   └── static/                   # PWA frontend (served at /)
│       ├── index.html            # HTML shell, meta tags, Bootstrap
│       ├── sw.js                 # Service Worker: offline caching, background sync, install
│       │
│       ├── js/
│       │   ├── state.js          # APP_VERSION constant, active workout state, default settings
│       │   ├── app.js            # Main UI state machine, render() loop, feature routing
│       │   ├── api.js            # Fetch wrapper, token management, error handling
│       │   ├── auth.js           # Google OAuth, native sign-in (Capacitor), session restore
│       │   ├── queue.js          # Offline queue: enqueue set, flush on sync, dedup
│       │   ├── sync.js           # Web PWA sync trigger via navigator.serviceWorker
│       │   ├── native-sync.js    # Android sync: call Capacitor bridge, resolve conflicts
│       │   ├── native-notify.js  # Android native notifications: subscribe, receive
│       │   ├── rest-notify.js    # Rest timer unified interface (Web Push or native)
│       │   ├── push.js           # Web Push subscription, VAPID key handling
│       │   │
│       │   ├── dom.js            # Utility: el(), stepper(), RPE picker, date parsing
│       │   ├── icons.js          # SVG icon registry (not emoji), icon() function
│       │   ├── range.js          # Date range picker UI
│       │   ├── drag-sort.js      # Reorderable list (exercises in template)
│       │   ├── switch-row.js     # Toggle switch UI component
│       │   ├── custom-exercise.js│ # Modal: create new exercise on-the-fly
│       │   │
│       │   ├── workouts.js       # (Legacy? not in scope—workout logging in app.js)
│       │   ├── body.js           # Body weight/fat log screen
│       │   ├── calendar.js       # Heatmap calendar, click→date picker
│       │   ├── exercise-detail.js│ # Exercise history detail view, PR chart
│       │   ├── templates.js      # Template CRUD, exercise order, weekday assignment
│       │   ├── account.js        # Account settings, export, MCP token manage, delete
│       │   ├── app-update.js     # Check for APK updates, prompt user, download/install
│       │   ├── env.js            # API base URL, isNativeApp flag
│       │   └── dev/e2e/          # E2E test helpers (not shipped)
│       │
│       └── css/
│           └── app.css           # All styles (single file, no preprocessor)
│
├── tests/                        # Test suite
│   ├── conftest.py               # Pytest fixtures: test DB, client, auth session
│   ├── test_*.py                 # Unit & integration tests (API, service, model layer)
│   │
│   └── e2e/                      # End-to-end tests (Playwright, entire app flow)
│       ├── verify_f*.py          # Feature verification scripts (one per feature)
│       └── smoke_encoding.py     # Basic UTF-8 tests
│
├── android/                      # Android project (Capacitor wrapper)
│   ├── app/
│   │   ├── build.gradle          # App-level Gradle config, signing, product flavors
│   │   └── src/main/
│   │       ├── AndroidManifest.xml
│   │       ├── java/.../MainActivity.kt
│   │       └── assets/
│   │           └── public/       # Copied from app/static/ by cap sync
│   │
│   ├── capacitor.config.json     # Capacitor bridge config
│   └── gradlew.bat               # Gradle wrapper script
│
├── scripts/                      # Admin & utility scripts
│   ├── backup.py                 # Backup user DBs to tar.gz
│   ├── restore_drill.py          # Test restore procedure
│   ├── backfill_sync.py          # Populate sync_id for existing records (F155)
│   ├── migrate_legacy.py         # Schema migration, index creation for old DBs
│   ├── build_fonts.py            # Subset system fonts for APK size
│   ├── build-apk.ps1             # PowerShell: gradlew assembleRelease, copy APK
│   ├── deploy.ps1                # PowerShell: rsync to production, restart uvicorn
│   └── seed_dev.py               # Populate dev DB with test data
│
├── docs/                         # Documentation
│   ├── archive/                  # Passed acceptance criteria, design history
│   ├── evidence/                 # Feature verification evidence (screenshots, test logs)
│   ├── decisions/                # Technical decision records
│   └── schema-migration.md       # Historical DB schema notes
│
├── deploy/                       # Deployment artifacts
│   ├── current/                  # Latest deployed code
│   └── previous/                 # Rollback version
│
├── release/                      # Built APKs (prod flavor)
└── release-dev/                  # Built APKs (dev flavor)

├── package.json                  # Capacitor/Node dependencies
├── pyproject.toml                # Python project metadata, pytest, ruff config
├── capacitor.config.json         # Capacitor bridge config
├── docker-compose.yml            # Local dev environment (not production)
├── .env                          # (Secrets—never commit; .env.example shows structure)
├── .env.example                  # Template for .env
├── .gitignore                    # Exclude build, venv, DB files, APK
├── CLAUDE.md                     # Project charter, rules for AI agents
│
├── control.db                    # Control plane DB (users, devices, auth sessions)
├── control.db-shm                # SQLite WAL temp files
├── control.db-wal
│
├── .coverage                     # Pytest coverage data
├── .pytest_cache/                # Pytest cache
├── .ruff_cache/                  # Ruff linter cache
└── .venv/                        # Python virtualenv (local dev)
```

## Directory Purposes

**`app/`**
- Purpose: Core backend and frontend
- Contains: FastAPI server, ORM models, REST routers, business logic services, PWA shell
- Key files: `main.py` (entry point), `models.py` (data schema), `api/` (endpoints), `services/` (logic), `static/` (frontend)

**`app/api/`**
- Purpose: REST endpoint definitions
- Contains: Route handlers, request/response parsing, dependency injection
- Key files: `deps.py` (auth, DB session), `workouts.py`, `exercises.py`, `sync.py` (core endpoints)
- Pattern: Each file is a FastAPI router with prefix `/api`, imported and registered in `main.py`

**`app/services/`**
- Purpose: Encapsulate all business logic; single source of truth for queries
- Contains: Domain functions, constraint enforcement, cross-domain coordination
- Key files: `auth.py` (session/token), `workouts.py` (set logging), `sync.py` (conflict resolution)
- Pattern: One module per domain; all functions take `session: Session` as first arg

**`app/static/js/`**
- Purpose: Frontend state machine and UI rendering
- Contains: PWA startup, page routing, API calls, offline queue, sync coordination
- Key files: `app.js` (main loop), `state.js` (constants), `api.js` (fetch wrapper), feature modules
- Pattern: No framework, no bundler; module-level state + function exports; IndexedDB for persistence

**`tests/`**
- Purpose: Unit and integration tests
- Contains: Pytest tests, E2E Playwright scripts, fixtures
- Key files: `conftest.py` (fixtures), `test_*.py` (unit), `e2e/verify_*.py` (feature acceptance)
- Pattern: Tests follow feature ID (F48, F101, etc.); E2E scripts are self-contained Playwright + assertions

**`android/`**
- Purpose: Native Android app wrapper
- Contains: Capacitor bridge, Gradle build config, AndroidManifest
- Key files: `build.gradle`, `capacitor.config.json`, `MainActivity.kt`
- Pattern: Capacitor copies `app/static/` to APK assets; WebView loads `index.html` from there

**`scripts/`**
- Purpose: Admin utilities, schema migration, deployment
- Contains: Backup/restore, APK building, production deployment
- Key files: `deploy.ps1` (production release), `build-apk.ps1` (APK assembly)
- Pattern: One-off scripts; not part of core app; idempotent where possible

**`docs/`**
- Purpose: Documentation and evidence
- Contains: Feature acceptance criteria (archived), design decisions, schema notes
- Key files: `archive/` (passed acceptance), `evidence/` (screenshots), `decisions/` (technical choices)
- Pattern: Evidence per feature (e.g., `evidence/F61.md`); design decisions in `decisions/`

**`deploy/`**
- Purpose: Deployment artifact staging
- Contains: Latest deployed code snapshot, previous version for rollback
- Key files: None directly; full `lift-log/` snapshot of deployed commit
- Pattern: Used by `scripts/deploy.ps1` for blue-green deploy

## Key File Locations

**Entry Points:**
- `app/main.py`: Entrypoint for uvicorn (app_factory function)
- `app/static/index.html`: HTML shell for PWA / Android WebView
- `android/app/src/main/java/.../MainActivity.kt`: Android entry point (Capacitor)

**Configuration:**
- `app/config.py`: Environment variable loading, Settings dataclass
- `.env`: Runtime secrets (LIFTLOG_TOKEN, Google OAuth credentials, DB path)
- `capacitor.config.json`: Capacitor bridge settings, app ID
- `pyproject.toml`: Python dependencies, pytest/ruff config

**Core Logic:**
- `app/models.py`: ORM schema for per-user data
- `app/control_models.py`: ORM schema for control plane (users, auth, MCP tokens)
- `app/services/`: All business logic functions
- `app/api/`: All REST route handlers

**Frontend:**
- `app/static/js/app.js`: Main PWA state machine
- `app/static/js/api.js`: API client wrapper
- `app/static/js/queue.js`: Offline queue management
- `app/static/sw.js`: Service Worker (caching, background sync)

**Testing:**
- `tests/conftest.py`: Pytest fixtures
- `tests/test_*.py`: Unit & integration tests
- `tests/e2e/verify_*.py`: Feature acceptance tests (Playwright)

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` (e.g., `service_auth.py`, `app.py`)
- Frontend JS: `kebab-case.js` or `camelCase.js` depending on function (e.g., `app-update.js`, `api.js`)
- Test files: `test_*.py` (unit), `verify_*.py` (E2E feature acceptance)
- Config: lowercase with underscores (e.g., `.env`, `capacitor.config.json`)

**Directories:**
- Python packages: `lowercase` (e.g., `app`, `tests`, `services`, `api`)
- Frontend modules: `static/js/`, grouped by feature (e.g., `auth.js`, `body.js`)
- Build outputs: lowercase (e.g., `release/`, `android/app/build/`)

**Database:**
- Control DB: `control.db` (SQLite, multi-tenant, holds users/devices/auth)
- Per-user DBs: `user_<USER_ID>.db` (SQLite, isolated per user, holds workout data)
- Locations: Control DB in `.venv/` or config-specified path; per-user DBs in `data/` dir or config-specified path

## Where to Add New Code

**New Feature (e.g., F65):**
1. **Endpoint:** Create or update route in `app/api/<feature>.py` (e.g., `app/api/body_metrics.py`)
   - Define Pydantic schema in `app/schemas.py`
   - Call service function, handle errors
2. **Business Logic:** Add function to `app/services/<feature>.py`
   - Keep queries SQLAlchemy-only; no direct SQL
   - Enforce domain constraints (e.g., "never return deleted_at IS NOT NULL")
3. **Frontend:** Add UI module `app/static/js/<feature>.js`
   - Export functions for rendering, event handlers
   - Call `api.<method>()` for server calls
   - Integrate with main `app.js` state machine
4. **Test:** Write `tests/test_<feature>.py` (unit) and/or `tests/e2e/verify_<feature>.py` (E2E)
   - Unit test focuses on service layer (repos→svc functions)
   - E2E test exercises full flow (API→frontend→sync)
5. **Schema:** If new ORM model needed:
   - Add class to `app/models.py` (per-user) or `app/control_models.py` (multi-tenant)
   - Add migration in `app/migrations.py`

**New Component/Module:**
- Helper functions: Add to `app/services/` (if business logic) or `app/static/js/` (if frontend utility)
- Cross-cutting concern (e.g., logging): Add to `app/` root or frontend `js/` root
- API middleware: Modify `app/main.py::create_app()`

**Utilities:**
- Backend helpers: `app/services/` (if domain-specific) or new module in `app/` (if general)
- Frontend helpers: `app/static/js/dom.js` (DOM), `app/static/js/api.js` (API calls), or new file (if feature-specific)

**Testing:**
- Unit test: `tests/test_<module>.py` (pytest)
- E2E test: `tests/e2e/verify_<feature>.py` (Playwright + Python)
- Fixtures: `tests/conftest.py` (shared setup)

## Special Directories

**`.planning/codebase/`:**
- Purpose: This auto-generated codebase documentation (Architecture, Structure, Conventions, Concerns)
- Generated: By `gsd-map-codebase` agent
- Committed: Yes (tracked in git)

**`.claude/`:**
- Purpose: Claude Code workspace metadata
- Generated: By Claude Code harness
- Committed: Yes (tracked in git)

**`.venv/`:**
- Purpose: Python virtualenv for development
- Generated: By `uv venv` or `python -m venv`
- Committed: No (.gitignore)

**`.pytest_cache/`, `.ruff_cache/`, `__pycache__/`:**
- Purpose: Test and linter cache
- Generated: By pytest, ruff
- Committed: No (.gitignore)

**`prod-data/`, `release/`, `release-dev/`:**
- Purpose: Production data and built APKs
- Generated: By backup script, gradlew, APK build
- Committed: No (.gitignore)

**`node_modules/`:**
- Purpose: Node/Capacitor dependencies
- Generated: By `npm install`
- Committed: No (.gitignore)

---

*Structure analysis: 2026-08-19*
