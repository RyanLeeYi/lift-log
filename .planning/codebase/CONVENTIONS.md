# Coding Conventions

**Analysis Date:** 2026-08-19

## Naming Patterns

**Files:**
- Lowercase with underscores: `models.py`, `workouts.py`, `body_metrics.py`
- Prefix test files with `test_`: `test_api_workouts.py`, `test_auth.py`
- E2E verification scripts use `verify_f<ID>.py` (e.g., `verify_f67.py`)

**Functions:**
- snake_case for all functions: `create_workout()`, `upsert_body_metric()`
- Prefix private/internal functions with `_`: `_exercise_index()`, `_suggest()`, `_batch_validation_errors()`
- Async functions use `async def` with snake_case names: `async def rest_timer()`

**Variables:**
- snake_case throughout: `session_factory`, `exercise_id`, `client_uuid`
- Constants in UPPER_SNAKE_CASE: `ACCESS_TTL`, `TEST_TOKEN`, `WEB_SESSION_TTL`, `DEFAULT_MUSCLE_GROUP`
- Type aliases use CamelCase: `GoogleTokenVerifier = Callable[[str], dict[str, Any]]`

**Types:**
- ORM Models: CamelCase (Exercise, Workout, Template, BodyMetric)
- Pydantic Schemas: CamelCase (WorkoutCreate, WorkoutOut, LogWorkoutIn)
- Use `Mapped[type]` for SQLAlchemy type hints in models

## Code Style

**Formatting:**
- Tool: `ruff format`
- Line length: 100 characters (configured in `pyproject.toml` [tool.ruff])
- Enforced by CI/pre-commit

**Linting:**
- Tool: ruff (not pylint or flake8)
- Config in `pyproject.toml` [tool.ruff.lint]
- Selected rules: E (pycodestyle), F (Pyflakes), I (isort), UP (upgrades), B (flake8-bugbear)
- Run: `uv run ruff check . && uv run ruff format .`

**Type Hints:**
- Full type annotations for function signatures (required)
- Include return types: `def create_workout(session: Session, data: WorkoutCreate) -> WorkoutOut:`
- Use `|` for unions (Python 3.10+ syntax): `str | None`, `int | float`
- For untyped middleware/callbacks, use `# type: ignore[no-untyped-def]` comment
- Import `from __future__ import annotations` for forward references

## Import Organization

**Order:**
1. `from __future__ import annotations` (if using forward refs)
2. Standard library: `from datetime import date, datetime`
3. Third-party: `from fastapi import FastAPI`, `from sqlalchemy import ...`
4. Local application: `from app.models import Exercise`, `from app.services import workouts`

**Path Aliases:**
- No path aliases used. All imports use absolute paths from package root: `from app.models import ...`

**Blank lines:**
- Two blank lines between major import groups
- One blank line between local vs third-party groups if on same level

## Error Handling

**Patterns:**
- Custom exceptions defined in `app/errors.py`:
  - `NotFoundError` → 404 response
  - `DomainError(message)` → 400 response with custom message
  - `ConflictError(message)` → 409 response
  - `UnknownExerciseError(unknown_list, suggestions_list)` → 400 with suggestions
- Register handlers with `register_error_handlers(app)` in app startup
- Handlers convert exceptions to JSON responses with `{"error": "message"}` format
- Batch operations return structured error lists: `{"error": "validation failed", "errors": [...]}`

**Validation:**
- Use Pydantic `BaseModel` and `BaseSettings` for schema validation
- Field validators with `@field_validator` for custom rules
- Validation errors caught in routes and transformed to user-friendly messages
- Use `validation_message(exc)` helper to extract first error as single-line message

## Logging

**Framework:** No centralized logging library (stdlib logging not used)

**Patterns:**
- Print debugging via comments referencing feature IDs (F1, F67, etc.)
- Exceptions and error states use custom exception types
- Feature references in comments for debugging: `# F157: [explanation]`
- No structured logging; focus on correct exception types and messages

## Comments

**When to Comment:**
- Explain WHY, not WHAT (code shows what it does)
- Reference feature IDs (F1, F67) for architectural decisions
- Explain non-obvious business logic or constraints
- Warn about gotchas and edge cases

**Format:**
- Use bilingual comments (English + Traditional Chinese) for complex decisions
- Example: `# F157：設定優先；沒設就用 control DB 持久化的那顆`
- Single-line comments with `#` (not inline on code lines when possible)
- Multi-line explanations as block comments above the code

**Docstrings:**
- Module-level docstrings describe overall purpose: `"""體重體脂 service：同日覆蓋 upsert..."""`
- Function docstrings explain parameters, behavior, and return values
- Use triple quotes for all docstrings
- Include PRD (Product Requirements Document) references where applicable
- Example: `"""一天一筆：同日重送為覆蓋更新（PRD R6）。回傳 (row, created)..."""`

## Function Design

**Size:** Prefer functions under 50 lines; complex logic broken into smaller helpers

**Parameters:**
- Type hints required for all parameters
- Default values come after required parameters
- Database sessions always named `session` (from dependency)
- Use positional args for core dependencies (session), keyword args for options

**Return Values:**
- Explicit return type hints required
- Return tuples for multiple values: `tuple[Model, bool]`
- Use dataclasses or NamedTuples for complex returns: `@dataclass(frozen=True) class IssuedAuth:`
- Empty return still needs `-> None` type hint

**Async Functions:**
- Mark with `async def` when used with FastAPI routes or MCP tools
- Handle awaits explicitly with `await` keyword
- Mark tests requiring async with `@pytest.mark.asyncio`

## Module Design

**Exports:**
- No explicit `__all__` definition used
- All public functions and classes are importable
- Private functions prefixed with `_`

**Layer Organization:**
- **Models** (`app/models.py`): SQLAlchemy ORM models with Mapped types
- **Schemas** (`app/schemas.py`): Pydantic models for request/response validation
- **Services** (`app/services/`): Business logic (no SQL, no HTTP concerns)
- **API** (`app/api/`): HTTP routes, validation, dependency injection
- **Errors** (`app/errors.py`): Exception definitions and error handlers
- **Config** (`app/config.py`): Settings via Pydantic BaseSettings
- **MCP** (`app/mcp.py`): Model Context Protocol tool definitions

**Naming Convention by Layer:**
- Models: Singular (Exercise, Workout)
- Services: Module per domain (services/workouts.py contains workout logic)
- API: Router per domain (api/workouts.py contains workout endpoints)
- Functions in services can call other service functions but not API functions

**Separation of Concerns:**
- API routes must not contain SQL or business logic
- Routes delegate to service functions via dependency injection
- Services reused by both REST API and MCP tools
- Database operations isolated to services, never in API handlers
- Configuration read once at app startup, passed through state

---

*Convention analysis: 2026-08-19*
