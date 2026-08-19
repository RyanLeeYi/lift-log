# Codebase Concerns

**Analysis Date:** 2026-08-19

## Tech Debt

**SQLite Connection Pooling:**
- Issue: Per-request engine instantiation without connection pooling; each request creates a new SQLite engine via `make_engine(str(path))` and disposes it after completion
- Files: `app/api/deps.py` (lines 196-204), `app/db.py` (line 14)
- Impact: Performance degradation under high concurrency; expensive engine creation/disposal cycle; SQLite has limited concurrent write support anyway with `check_same_thread=False`
- Fix approach: Consider implementing connection pooling or caching engines per user database file; evaluate StaticPool for per-user SQLite databases with known file paths

**Broad Exception Handler at Startup:**
- Issue: Generic `except Exception` silently adds users to `unavailable_user_ids` without distinguishing between recoverable and fatal errors
- Files: `app/main.py` (lines 66-78)
- Impact: Real errors (permissions, corrupted data) are masked as "user data unavailable"; makes debugging startup failures harder; users appear offline when only some data is actually unavailable
- Fix approach: Narrow exception catching to specific errors (FileNotFoundError, sqlite3.DatabaseError); log different exception types; distinguish between "DB not initialized" vs "DB corrupted"

**Startup Migration Delays:**
- Issue: All schema migrations run on every startup via `migrate_schema()` called sequentially for each existing user database
- Files: `app/migrations.py`, `app/db.py` (line 49), `app/main.py` (line 59)
- Impact: Startup time scales with number of users and migration complexity; ALTER TABLE operations on large databases can lock tables; any migration failure blocks the entire service
- Fix approach: Add schema version tracking to skip completed migrations; consider background migration tasks instead of blocking startup; implement per-database migration status

**SQLite Thread Safety Override:**
- Issue: `check_same_thread=False` disables SQLite's built-in thread safety checks; relies entirely on application-level synchronization
- Files: `app/db.py` (line 14)
- Impact: Multi-threaded request handling risks silent data corruption if concurrent writes hit the same database; uvicorn with multiple workers will create threads that bypass SQLite's warnings
- Fix approach: Document the single-threaded FastAPI assumption; consider using connection pooling library that enforces thread safety; add runtime assertions for thread model consistency

## Known Bugs

**User Database Initialization Race Condition:**
- Symptoms: During login, if two concurrent requests from the same new Google account try to create the user database simultaneously, one might fail
- Files: `app/services/auth.py` (lines 162-175), `app/db.py` (lines 43-56)
- Trigger: New user login followed immediately by second device login with same Google account before first request completes `initialize_data_db()`
- Workaround: Retry login; subsequent attempt will find existing database

**Missing Sync Recovery for Partial Failures:**
- Symptoms: If sync push succeeds in writing some mutations but fails partway through (e.g., OOM, disk full during response generation), client may retry with different data structure
- Files: `app/api/sync.py`, `app/services/sync.py` (mutation processing logic)
- Trigger: Large sync batches on systems with limited resources
- Workaround: Client-side retry with same data should succeed due to idempotency keys

## Security Considerations

**CSRF Token Derivation Vulnerability:**
- Risk: CSRF token is derived from HMAC(secret_key, session_id); if secret_key is compromised, all active web sessions become vulnerable to CSRF
- Files: `app/services/auth.py`, `app/api/deps.py` (line 135-137)
- Current mitigation: Secret key stored in control DB and persisted; not leaked in logs or error messages
- Recommendations: Add secret key rotation mechanism; consider using cryptographically signed session tokens instead of HMAC; audit all places where secret_key is used

**Legacy Bearer Token Path Security:**
- Risk: When `LIFTLOG_TOKEN` is set for demo mode, the `_is_legacy_request()` function bypasses CSRF, rate limiting, daily mutation quota, and user isolation
- Files: `app/api/deps.py` (lines 101-112), `app/config.py` (line 15)
- Current mitigation: Token only works if explicitly configured; default (empty string) disables entire legacy path
- Recommendations: Document risk of demo mode clearly; consider time-based token expiry for demo/staging; audit all legacy code paths for additional privilege escalation

**Google OAuth Token Verification Network Dependency:**
- Risk: Authentication depends on reaching Google's servers; no local fallback; `GoogleVerifierUnavailable` exception blocks login during network outages
- Files: `app/services/auth.py` (lines 76-99)
- Current mitigation: CacheControl caches verification results per default
- Recommendations: Increase cache TTL for token verification; implement local token structure validation as fallback; document expected behavior during Google service unavailability

**Path Traversal Prevention in User DB Access:**
- Risk: `canonical_user_db_path()` must correctly validate UUID and path to prevent directory traversal
- Files: `app/db.py` (lines 29-40)
- Current mitigation: UUID validation, database name format check, parent directory check with `.resolve()`
- Recommendations: Audit this function before adding any path construction logic; add unit tests for malformed inputs; consider using pathlib.Path exclusively

## Performance Bottlenecks

**Per-User Database File Overhead:**
- Problem: Each user gets a separate SQLite database file; at scale with hundreds of users, this means hundreds of file handles open
- Files: `app/api/deps.py` (lines 151-204), `app/services/auth.py` (lines 162-175)
- Cause: Architecture decision for isolation; acceptable for single-user/small deployment but hits OS file descriptor limits at scale
- Improvement path: Monitor `data_db_size()` calls per request; consider caching open engines per user; evaluate connection pooling solutions for SQLite; profile file descriptor usage under load

**Batch Sync Push Validation:**
- Problem: Sync push validates all mutations and their dependencies sequentially; large batches (near MAX_PUSH_BYTES limit) may take seconds to validate
- Files: `app/services/sync.py` (mutation processing), `app/api/sync.py` (line 17: MAX_PUSH_BYTES = 1MB)
- Cause: No parallel validation; each mutation checks dependencies one at a time
- Improvement path: Batch dependency validation; implement conflict detection upfront before writing; consider indexing SyncEntity by (entity_type, entity_id) for faster lookups

**Schema Metadata Lookups:**
- Problem: Every startup queries `schema_metadata` table for each sync table to check schema version; repeated lookups without caching
- Files: `app/control_db.py` (lines 43-54)
- Cause: No in-memory cache of schema state between requests
- Improvement path: Cache schema state in app startup; store as app state; invalidate only on explicit migration events

## Fragile Areas

**Sync Idempotency Key Semantics:**
- Files: `app/models.py` (lines 151-154), `app/services/workouts.py` (lines 78-80)
- Why fragile: `idem_key` is populated only for new batches (F151); old data remains NULL and is never backfilled. Changing the idem_key algorithm would invalidate historical records without migration path
- Safe modification: Never change idem_key generation logic without backfill script; add schema migration that marks rows as "pre-F151" if idem_key is NULL
- Test coverage: `test_batch_idempotency.py` covers new batches; missing coverage for mixed old+new data scenarios

**Multi-Device Workout Ownership:**
- Files: `app/models.py` (lines 88-89), `app/services/projection.py`, `app/services/workouts.py`
- Why fragile: `owner_device_id` and `lease_generation` track which device "owns" a workout for concurrent editing. Logic is complex and distributed across services; incomplete lease generation bumps could lose edits
- Safe modification: Add comprehensive logging for lease transitions; test all permutations of device disconnect/reconnect while workout is in-flight
- Test coverage: Basic multi-device sync tested but missing scenarios for rapid device switching or network interruptions

**Custom Exercise Creation:**
- Files: `app/services/workouts.py` (line 32: DEFAULT_MUSCLE_GROUP), `app/services/exercises.py`
- Why fragile: When exercises are unknown, `create_missing=True` auto-creates them with "未分類" muscle group. If that string is changed, old created exercises remain but new auto-creates use new string, fragmenting the category
- Safe modification: Add migration to merge "未分類" variants into single canonical category; never change DEFAULT_MUSCLE_GROUP constant without migration
- Test coverage: `test_api_workouts.py` covers unknown exercise rejection; missing test for auto-create muscle group consistency

## Scaling Limits

**SQLite Concurrent Write Limitation:**
- Current capacity: WAL mode allows multiple readers + 1 writer; per-user DBs each have same limit
- Limit: With 100 concurrent users, if 2+ users try to mutate their own database simultaneously, they don't block each other (separate processes). But per single user, only 1 mutation at a time
- Scaling path: Switch to PostgreSQL or other multi-user RDBMS; migrate per-user DB file structure to shared database with user_id column; evaluate split between read-heavy (calendar queries) and write-heavy (sync) workloads

**File Descriptor Resource Usage:**
- Current capacity: Each request opens 2-3 file descriptors per user database (main .db file + WAL files)
- Limit: Ubuntu default is typically 1024 per process; with 100 concurrent requests, could approach limits
- Scaling path: Implement connection pooling to reuse file descriptors; monitor ulimit; consider NFS/cloud storage if hitting local filesystem limits

**Daily Mutation Quota:**
- Current capacity: 20,000 mutations per user per day (configured in `app/config.py` line 28)
- Limit: Power users doing large batch imports could hit limit; quota is per-day, not per-hour
- Scaling path: Implement quota tiering by subscription level; add burst allowance for imports; audit typical mutation counts from real users

## Fragile Dependencies

**google-auth + Requests Session Caching:**
- Risk: Token verification uses CacheControl with Requests session; cache is in-memory per process. With multiple worker processes (gunicorn -w 4), cache hits vary unpredictably
- Impact: Some requests verify token with Google, others hit cache; under high load, network could saturate
- Migration plan: Use shared cache (Redis) for token verification results; or accept higher Google API usage and adjust quota accordingly

**fastmcp Version Constraints:**
- Risk: `fastmcp>=2.0` is broad version range; MCP tools defined in `app/mcp.py` tightly coupled to fastmcp API
- Impact: Major version bump (fastmcp 3.0) could break tool definitions without warning
- Migration plan: Pin to specific minor version (e.g., fastmcp>=2.0,<3.0); set up automated tests for fastmcp upgrade candidates; monitor fastmcp changelog

## Missing Critical Features

**Schema Migration Status Tracking:**
- Problem: No persistent record of which migrations have run; all migrations re-execute every startup
- Blocks: Upgrading migration system to run offline; parallelizing migrations; detecting failed migrations
- Solution needed: Add `completed_migrations` table to control DB; record migration ID + timestamp on completion; skip already-completed migrations

**Concurrent Edit Conflict UI:**
- Problem: Sync service detects conflicts (tombstoned, version mismatch, natural key conflict) but returns generic JSON error
- Blocks: Frontend can't display user-friendly error explaining what conflicted and how to resolve
- Solution needed: Structured error response with conflict metadata (which field, server value, client value); implement conflict resolution UI on frontend

**User Account Soft Delete State Machine:**
- Problem: Account deletion is modeled as status change + tombstone, but state transitions aren't enforced (e.g., can't transition from "closed" back to "active")
- Blocks: Recovery from accidental deletion; audit trail of state changes
- Solution needed: Add state_changed_at timestamp; implement transition validation; document allowed state paths

## Test Coverage Gaps

**Database Connection Cleanup:**
- What's not tested: Engine disposal and connection pool draining under failures (network errors, SIGTERM during request)
- Files: `app/api/deps.py` (lines 196-204)
- Risk: Connection leaks if exception occurs between engine creation and disposal
- Priority: High - could cause file descriptor leaks in production

**Sync Conflict Resolution Edge Cases:**
- What's not tested: Tombstone conflicts with version mismatches; concurrent edits to same field from multiple devices
- Files: `app/services/sync.py` (conflict detection logic)
- Risk: Silent data loss if conflict handling has ordering bugs
- Priority: High - data loss risk

**Migration Failures on Large Datasets:**
- What's not tested: ALTER TABLE performance with millions of rows; disk space exhaustion during WAL growth
- Files: `app/migrations.py`, `app/control_db.py`
- Risk: Startup fails silently, users can't access service
- Priority: Medium - scales with user base size

**Legacy Token CSRF Bypass Scenarios:**
- What's not tested: Edge cases where legacy token path and web session path interact (e.g., same browser with both auth methods)
- Files: `app/api/deps.py` (lines 101-112)
- Risk: Unintended CSRF bypass if logic errors exist
- Priority: High - security risk

**Multi-Worker Concurrency:**
- What's not tested: Race conditions when running under gunicorn/uvicorn with multiple workers (not just single process)
- Files: Entire service, especially auth session creation and quota tracking
- Risk: Data corruption or duplicate writes under production load
- Priority: High - only appears in prod

---

*Concerns audit: 2026-08-19*
