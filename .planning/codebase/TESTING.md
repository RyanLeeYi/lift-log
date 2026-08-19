# Testing Patterns

**Analysis Date:** 2026-08-19

## Test Framework

**Runner:**
- pytest >= 8.0
- Config: `pyproject.toml` [tool.pytest.ini_options]
- Test paths: `tests/`
- Python path: root (`.`)

**Assertion Library:**
- pytest's built-in `assert` statements

**Additional Frameworks:**
- pytest-asyncio: for async test execution
- pytest-cov: for coverage reporting
- httpx: HTTP client (via TestClient from fastapi)
- Playwright: browser automation for E2E tests

**Run Commands:**
```bash
uv run pytest                              # Run all tests
uv run pytest tests/                       # Run unit/integration tests only
uv run pytest tests/test_auth.py           # Run single test file
uv run pytest -k test_name                 # Run by name pattern
uv run pytest --cov                        # Coverage report
uv run pytest --cov --cov-report=html      # HTML coverage report
PYTHONUTF8=1 uv run python tests/e2e/verify_f67.py  # Run E2E verification
```

## Test File Organization

**Location:**
- Unit/integration tests: co-located in `tests/` directory
- E2E tests: `tests/e2e/verify_f<ID>.py` (feature-based organization)
- Test fixtures: `tests/conftest.py`

**Naming:**
- Test files: `test_<domain>.py` (e.g., `test_workouts.py`, `test_auth.py`)
- Test functions: `test_<scenario>()` or `TestClass.test_<scenario>()`
- E2E scripts: `verify_f<ID>.py` where ID matches feature_list.json feature ID

**Structure:**
```
tests/
├── conftest.py              # Shared fixtures
├── test_auth.py             # Auth service/API tests
├── test_api_workouts.py     # Workout REST API tests
├── test_log_workout.py      # Service layer tests
├── test_sync.py             # Sync functionality tests
└── e2e/
    ├── verify_f67.py        # Feature F67 E2E (server + Playwright)
    ├── verify_f101.py       # Feature F101 E2E
    └── ...
```

## Test Structure

**Suite Organization:**
```python
class TestAuth:
    def test_missing_token_returns_401(self, anon_client):
        resp = anon_client.post("/api/workouts", json={})
        assert resp.status_code == 401
        assert resp.json() == {"error": "unauthorized"}

    def test_wrong_token_returns_401(self, anon_client):
        # ...
```

**Patterns:**
- Class-based grouping by domain/feature (TestAuth, TestWorkouts)
- Each test function is independent (no shared state across tests in class)
- Setup/teardown via pytest fixtures, not class methods
- Assertions use plain `assert` statements

**Setup:**
- Database fixtures create temporary SQLite databases (`tmp_path`)
- Client fixtures initialize TestClient with settings
- Authentication added via headers: `headers={"Authorization": f"Bearer {TEST_TOKEN}"}`
- No teardown needed (tmp_path cleanup automatic)

**Assertions:**
```python
assert response.status_code == 201
assert response.json()["id"]
assert len(results) == 3
assert workout.date == date(2026, 8, 19)
```

## Mocking

**Framework:** pytest's monkeypatch + manual mock functions

**Patterns:**
```python
# Mock Google token verifier
def make_client(tmp_path: Path, token_claims: dict[str, object] | None = None) -> TestClient:
    def verifier(_token: str) -> dict[str, object]:
        return token_claims or claims()
    
    return TestClient(
        create_app(auth_settings(tmp_path), google_token_verifier=verifier),
        base_url="https://testserver",
    )

# Mock environment variables
def test_example(monkeypatch):
    monkeypatch.setenv("LIFTLOG_TOKEN", "test-token")
    monkeypatch.setenv("LIFTLOG_DB", str(tmp_path / "custom.db"))
```

**What to Mock:**
- External APIs (Google OAuth)
- Environment variables
- Time (datetime.utcnow for auth expiry testing)

**What NOT to Mock:**
- Database access (use temporary SQLite)
- HTTP request/response (use TestClient)
- Service layer logic (test actual implementation)

## Fixtures and Factories

**Test Data:**
```python
@pytest.fixture()
def db_session(tmp_path: Path) -> Iterator[Session]:
    """Service layer testing: independent SQLite."""
    engine = make_engine(str(tmp_path / "svc.db"))
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session

@pytest.fixture()
def exercise_id(client: TestClient) -> int:
    resp = client.post(
        "/api/exercises",
        json={"name_zh": "深蹲", "name_en": "Squat", "muscle_group": "腿", "is_bodyweight": False},
    )
    assert resp.status_code == 201
    return resp.json()["id"]

def make_set_payload(exercise_id: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "client_uuid": "11111111-1111-1111-1111-111111111111",
        "exercise_id": exercise_id,
        "set_number": 1,
        "weight_kg": 80.0,
        "reps": 8,
    }
    return {**payload, **overrides}
```

**Location:**
- Fixtures: `tests/conftest.py` (shared across all tests)
- Factory functions: `conftest.py` (e.g., `make_set_payload`, `make_client`)
- Test claims/data: defined in test files using fixtures

**Fixture Scope:**
- `@pytest.fixture()` (function scope, default) - recreated for each test
- No session/module scope used (avoid state sharing)

## Coverage

**Requirements:** No explicit minimum enforced, but coverage tracked

**Configuration:**
```toml
[tool.coverage.run]
source = ["app"]
```

**View Coverage:**
```bash
uv run pytest --cov --cov-report=term-missing
uv run pytest --cov --cov-report=html      # Opens htmlcov/index.html
```

**Exclusions:**
- `.ruff_cache`, `__pycache__`, `.venv` automatically excluded
- Per-file exclusions in pyproject.toml for legacy E2E scripts (F4x/F5x)

## Test Types

**Unit Tests:**
- **Scope:** Individual service functions
- **Files:** `tests/test_*.py`
- **Approach:** Call service functions directly with db_session fixture
- **Example:** `tests/test_body_metrics.py` tests `app.services.body_metrics.upsert_body_metric()`
- **Isolation:** Each test uses temporary SQLite database

**Integration Tests:**
- **Scope:** API endpoints + service + database
- **Files:** `tests/test_api_*.py` and `tests/test_*.py`
- **Approach:** Use TestClient to call HTTP endpoints, verify database state
- **Example:** `tests/test_api_workouts.py` tests POST /api/workouts flow
- **Setup:** TestClient with test token, temporary database

**E2E Tests:**
- **Scope:** Full application (server + frontend UI)
- **Files:** `tests/e2e/verify_f<ID>.py`
- **Approach:** Start server, use Playwright to automate browser
- **Example:** `tests/e2e/verify_f67.py` tests complete workout logging flow
- **Run:** `PYTHONUTF8=1 uv run python tests/e2e/verify_f67.py`
- **Browser:** Chromium (installed by init.sh)
- **Assertions:** Check UI state, element visibility, navigation

**Contract Tests:**
- **Files:** `tests/test_sync_contract.py`
- **Scope:** Verify API request/response shapes match expectations
- **Approach:** Validate JSON structure against spec

## Common Patterns

**Async Testing:**
```python
@pytest.mark.asyncio
async def test_mcp_token_verification(session_factory):
    client = ClientPool(
        session_factory=session_factory,
        token="test-token",
    )
    token = await client.verify_token("valid-token")
    assert token is not None
```

**Error Testing:**
```python
def test_unknown_exercise_rejected(client: TestClient, exercise_id: int):
    resp = client.post(
        "/api/workouts/batch",
        json={
            "date": "2026-08-19",
            "sets": [{"exercise": "未知動作", "weight_kg": 50, "reps": 10}],
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "validation failed"
    assert "unknown exercise" in body["errors"][0]["message"]
```

**Database State Verification:**
```python
def test_set_created_in_db(client: TestClient, exercise_id: int):
    resp = client.post(
        "/api/workouts",
        json={"date": "2026-08-19", "sets": [make_set_payload(exercise_id)]},
    )
    assert resp.status_code == 201
    
    # Verify in database
    with client.app.state.session_factory() as session:
        set_count = session.query(WorkoutSet).count()
        assert set_count == 1
```

**Concurrency Testing:**
```python
def test_concurrent_writes_handled(client: TestClient):
    """Verify that race conditions don't cause data corruption."""
    from concurrent.futures import ThreadPoolExecutor
    
    def write_metric():
        return client.post(
            "/api/body_metrics",
            json={"date": "2026-08-19", "weight_kg": 75.5}
        )
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda _: write_metric(), range(5)))
    
    # First wins, rest handled gracefully (200 or 409)
    status_codes = {r.status_code for r in results}
    assert 201 in status_codes or 200 in status_codes
```

**Environment-Dependent Tests:**
```python
def test_missing_token_disables_legacy_path(tmp_path):
    """Verify LIFTLOG_TOKEN="" closes demo mode entirely."""
    app = create_app(
        Settings(
            token="",  # Explicitly empty
            db_path=str(tmp_path / "t.db"),
            control_db_path=str(tmp_path / "control.db"),
            user_data_dir=str(tmp_path / "users"),
        )
    )
    with TestClient(app) as client:
        resp = client.post("/api/workouts", json={}, headers={})
        assert resp.status_code == 401  # Not 200 with demo access
```

---

*Testing analysis: 2026-08-19*
