from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.api.auth import AuthRateLimiter
from app.config import Settings
from app.control_models import User
from app.db import make_engine
from app.main import create_app


def _settings(tmp_path: Path, *, max_bytes: int = 100 * 1024 * 1024) -> Settings:
    return Settings(
        token="legacy-token",
        db_path=str(tmp_path / "legacy.db"),
        control_db_path=str(tmp_path / "control.db"),
        user_data_dir=str(tmp_path / "users"),
        data_db_max_bytes=max_bytes,
        google_client_id="test-google-client",
    )


def _claims(raw_token: str) -> dict[str, object]:
    return {
        "sub": f"google-{raw_token}",
        "aud": "test-google-client",
        "iss": "https://accounts.google.com",
        "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
        "nonce": f"nonce-{raw_token}-long-enough",
        "email": f"{raw_token}@example.com",
        "email_verified": True,
    }


def _client(tmp_path: Path, *, max_bytes: int = 100 * 1024 * 1024) -> TestClient:
    return TestClient(
        create_app(_settings(tmp_path, max_bytes=max_bytes), google_token_verifier=_claims),
        base_url="https://testserver",
    )


def _login(client: TestClient, name: str, *, kind: str = "android") -> dict:
    response = client.post(
        "/api/auth/google",
        json={
            "id_token": name,
            "nonce": f"nonce-{name}-long-enough",
            "device_id": str(uuid4()),
            "device_name": name,
            "client": kind,
        },
    )
    assert response.status_code == 200
    return response.json()


def _bearer(login: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {login['access_token']}"}


def _exercise(client: TestClient, headers: dict[str, str], name: str) -> int:
    response = client.post(
        "/api/exercises",
        headers=headers,
        json={
            "name_zh": name,
            "name_en": name,
            "muscle_group": "其他",
            "is_bodyweight": False,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_two_accounts_cannot_read_write_list_or_idor_each_others_rows(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        alice = _bearer(_login(client, "alice"))
        bob = _bearer(_login(client, "bob"))
        alice_exercise = _exercise(client, alice, "Alice only")
        workout = client.post("/api/workouts", headers=alice, json={"date": "2026-08-10"})
        assert workout.status_code == 201
        workout_id = workout.json()["id"]
        logged = client.post(
            f"/api/workouts/{workout_id}/sets",
            headers=alice,
            json={
                "client_uuid": str(uuid4()),
                "exercise_id": alice_exercise,
                "set_number": 1,
                "weight_kg": 100,
                "reps": 5,
            },
        )
        assert logged.status_code == 201

        assert client.get("/api/workouts", headers=bob).json() == []
        assert client.get(f"/api/workouts/{workout_id}", headers=bob).status_code == 404
        assert client.patch(
            f"/api/sets/{logged.json()['id']}",
            headers=bob,
            json={"weight_kg": 1, "reps": 99},
        ).status_code == 404
        assert client.post(
            f"/api/workouts/{workout_id}/sets",
            headers=bob,
            json={
                "client_uuid": str(uuid4()),
                "exercise_id": alice_exercise,
                "set_number": 2,
                "weight_kg": 1,
                "reps": 1,
            },
        ).status_code == 404

        _exercise(client, bob, "Bob only")
        alice_names = {row["name_en"] for row in client.get("/api/exercises", headers=alice).json()}
        bob_names = {row["name_en"] for row in client.get("/api/exercises", headers=bob).json()}
        assert "Alice only" in alice_names and "Alice only" not in bob_names
        assert "Bob only" in bob_names and "Bob only" not in alice_names

        injected = client.get(
            "/api/workouts",
            headers=bob,
            params={"user_id": alice["Authorization"], "db_path": "../legacy.db"},
        )
        assert injected.status_code == 200
        assert injected.json() == []


def test_web_domain_mutation_requires_matching_csrf(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        web = _login(client, "web-user", kind="web")
        payload = {
            "name_zh": "Web only",
            "name_en": "Web only",
            "muscle_group": "其他",
            "is_bodyweight": False,
        }
        assert client.post("/api/exercises", json=payload).status_code == 403
        assert client.post(
            "/api/exercises",
            json=payload,
            headers={"X-CSRF-Token": web["csrf_token"]},
        ).status_code == 201


def test_suspended_or_closed_user_loses_domain_access(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        issued = _login(client, "blocked")
        headers = _bearer(issued)
        assert client.get("/api/workouts", headers=headers).status_code == 200
        with client.app.state.control_session_factory() as session:
            user = session.scalar(select(User).where(User.id == issued["user"]["id"]))
            user.status = "suspended"
            session.commit()
        assert client.get("/api/workouts", headers=headers).status_code == 401

        with client.app.state.control_session_factory() as session:
            user = session.get(User, issued["user"]["id"])
            user.status = "closed"
            session.commit()
        assert client.get("/api/workouts", headers=headers).status_code == 401


def test_tampered_control_db_path_fails_closed_without_disclosure(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        issued = _login(client, "tampered")
        with client.app.state.control_session_factory() as session:
            user = session.get(User, issued["user"]["id"])
            user.data_db_name = "../legacy.db"
            session.commit()

        response = client.get("/api/workouts", headers=_bearer(issued))
        assert response.status_code == 503
        assert "legacy.db" not in response.text
        assert str(tmp_path) not in response.text


def test_user_db_enables_required_sqlite_pragmas_and_reruns_migration(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        issued = _login(client, "pragma")
        with client.app.state.control_session_factory() as session:
            db_name = session.get(User, issued["user"]["id"]).data_db_name
    with _client(tmp_path) as restarted:
        assert _login(restarted, "pragma")["user"]["id"] == issued["user"]["id"]

    engine = make_engine(str(tmp_path / "users" / db_name))
    try:
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert connection.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
            assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() >= 5000
            assert connection.execute(
                text("SELECT value FROM schema_metadata WHERE key='schema_version'")
            ).scalar_one() == "2"
    finally:
        engine.dispose()

    control = make_engine(str(tmp_path / "control.db"))
    try:
        with control.connect() as connection:
            assert connection.execute(
                text("SELECT value FROM schema_metadata WHERE key='schema_version'")
            ).scalar_one() == "2"
    finally:
        control.dispose()


def test_full_user_db_rejects_mutation_with_stable_error(tmp_path: Path) -> None:
    with _client(tmp_path, max_bytes=1) as client:
        issued = _login(client, "full")
        response = client.post(
            "/api/workouts",
            headers=_bearer(issued),
            json={"date": "2026-08-10"},
        )
        assert response.status_code == 507
        assert response.json() == {"error": "data_db_quota_exceeded"}


def test_missing_user_db_only_blocks_that_account_after_restart(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        missing = _login(client, "missing")
        healthy = _login(client, "healthy")
        with client.app.state.control_session_factory() as session:
            db_name = session.get(User, missing["user"]["id"]).data_db_name
    path = tmp_path / "users" / db_name
    backup = path.read_bytes()
    path.unlink()

    with TestClient(
        create_app(_settings(tmp_path), google_token_verifier=_claims),
        base_url="https://testserver",
    ) as restarted:
        assert restarted.get("/api/workouts", headers=_bearer(missing)).status_code == 503
        assert restarted.get("/api/workouts", headers=_bearer(healthy)).status_code == 200
        assert not path.exists()
        path.write_bytes(backup)
        refreshed = restarted.post(
            "/api/auth/refresh",
            json={
                "refresh_token": missing["refresh_token"],
                "device_id": missing["device"]["id"],
            },
        )
        assert refreshed.status_code == 200
        assert restarted.get(
            "/api/workouts", headers=_bearer(refreshed.json())
        ).status_code == 200


def test_domain_rate_limit_is_per_user_and_device(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        alice = _bearer(_login(client, "rate-alice"))
        bob = _bearer(_login(client, "rate-bob"))
        client.app.state.domain_rate_limiter = AuthRateLimiter(limit=2, window_seconds=60)

        assert client.get("/api/workouts", headers=alice).status_code == 200
        assert client.get("/api/workouts", headers=alice).status_code == 200
        blocked = client.get("/api/workouts", headers=alice)
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0
        assert client.get("/api/workouts", headers=bob).status_code == 200
