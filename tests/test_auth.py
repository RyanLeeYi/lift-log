from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app

NONCE = "nonce-1-long-enough"


def claims(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "sub": "google-sub-1",
        "aud": "test-google-client",
        "iss": "https://accounts.google.com",
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": NONCE,
        "email": "person@example.com",
        "email_verified": True,
        **overrides,
    }


def auth_settings(tmp_path: Path) -> Settings:
    return Settings(
        token="legacy-token",
        db_path=str(tmp_path / "domain.db"),
        control_db_path=str(tmp_path / "control.db"),
        user_data_dir=str(tmp_path / "users"),
        google_client_id="test-google-client",
    )


def make_client(tmp_path: Path, token_claims: dict[str, object] | None = None) -> TestClient:
    def verifier(_token: str) -> dict[str, object]:
        return token_claims or claims()

    return TestClient(
        create_app(auth_settings(tmp_path), google_token_verifier=verifier),
        base_url="https://testserver",
    )


def login_payload(*, client: str = "android", nonce: str = NONCE) -> dict[str, str]:
    return {
        "id_token": "raw-google-id-token",
        "nonce": nonce,
        "device_id": str(uuid4()),
        "device_name": "Pixel",
        "client": client,
    }


def test_android_login_creates_isolated_control_rows_and_hashed_tokens(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/auth/google", json=login_payload())

        assert response.status_code == 200
        body = response.json()
        assert body["expires_in"] == 900
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["user"]["id"]
        assert body["device"]["id"]

        from app.control_models import AuthSession, Device, RefreshToken, User

        with client.app.state.control_session_factory() as session:
            user = session.scalar(select(User))
            auth_session = session.scalar(select(AuthSession))
            refresh = session.scalar(select(RefreshToken))
            assert session.scalar(select(func.count()).select_from(Device)) == 1
            assert user.google_sub == "google-sub-1"
            assert user.data_db_name == f"{user.id}.db"
            assert auth_session.access_token_hash != body["access_token"]
            assert refresh.token_hash != body["refresh_token"]
            assert auth_session.access_expires_at - auth_session.created_at == timedelta(
                minutes=15
            )
            assert refresh.idle_expires_at - refresh.created_at == timedelta(days=30)
            assert refresh.absolute_expires_at - refresh.created_at == timedelta(days=90)
        assert (tmp_path / "users" / user.data_db_name).is_file()


def test_same_google_sub_reuses_user_and_data_db(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        first = client.post("/api/auth/google", json=login_payload()).json()
        second = client.post("/api/auth/google", json=login_payload()).json()

        assert second["user"]["id"] == first["user"]["id"]
        from app.control_models import User

        with client.app.state.control_session_factory() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 1
        assert len(list((tmp_path / "users").glob("*.db"))) == 1


@pytest.mark.parametrize(
    "bad_claims",
    [
        claims(aud="other-client"),
        claims(iss="https://attacker.example"),
        claims(exp=1),
        claims(nonce="other-nonce-long"),
        claims(email_verified=False),
        claims(sub=""),
    ],
)
def test_invalid_google_claims_leave_no_half_created_account(
    tmp_path: Path, bad_claims: dict[str, object]
) -> None:
    with make_client(tmp_path, bad_claims) as client:
        response = client.post("/api/auth/google", json=login_payload())
        assert response.status_code == 401

        from app.control_models import AuthSession, Device, User

        with client.app.state.control_session_factory() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 0
            assert session.scalar(select(func.count()).select_from(Device)) == 0
            assert session.scalar(select(func.count()).select_from(AuthSession)) == 0
        assert not list((tmp_path / "users").glob("*.db"))


def test_signature_failure_returns_401_without_account(tmp_path: Path) -> None:
    from app.services.auth import InvalidGoogleToken

    def reject(_token: str) -> dict[str, object]:
        raise InvalidGoogleToken

    app = create_app(auth_settings(tmp_path), google_token_verifier=reject)
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/api/auth/google", json=login_payload())
        assert response.status_code == 401


def test_google_verifier_outage_returns_503_without_account(tmp_path: Path) -> None:
    from app.services.auth import GoogleVerifierUnavailable

    def unavailable(_token: str) -> dict[str, object]:
        raise GoogleVerifierUnavailable

    app = create_app(auth_settings(tmp_path), google_token_verifier=unavailable)
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/api/auth/google", json=login_payload())
        assert response.status_code == 503
        assert not list((tmp_path / "users").glob("*.db"))


def test_data_db_failure_rolls_back_user_device_and_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import auth

    def fail(_path: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(auth, "create_user_data_db", fail)
    with make_client(tmp_path) as client:
        response = client.post("/api/auth/google", json=login_payload())
        assert response.status_code == 503

        from app.control_models import AuthSession, Device, User

        with client.app.state.control_session_factory() as session:
            assert session.scalar(select(func.count()).select_from(User)) == 0
            assert session.scalar(select(func.count()).select_from(Device)) == 0
            assert session.scalar(select(func.count()).select_from(AuthSession)) == 0


def test_refresh_rotates_and_replay_revokes_only_that_family(tmp_path: Path) -> None:
    payload = login_payload()
    with make_client(tmp_path) as client:
        login = client.post("/api/auth/google", json=payload).json()
        rotated = client.post(
            "/api/auth/refresh",
            json={"refresh_token": login["refresh_token"], "device_id": payload["device_id"]},
        )
        assert rotated.status_code == 200
        assert rotated.json()["refresh_token"] != login["refresh_token"]

        replay = client.post(
            "/api/auth/refresh",
            json={"refresh_token": login["refresh_token"], "device_id": payload["device_id"]},
        )
        assert replay.status_code == 401

        revoked_new_token = client.post(
            "/api/auth/refresh",
            json={
                "refresh_token": rotated.json()["refresh_token"],
                "device_id": payload["device_id"],
            },
        )
        assert revoked_new_token.status_code == 401


def test_expired_refresh_token_is_rejected(tmp_path: Path) -> None:
    payload = login_payload()
    with make_client(tmp_path) as client:
        login = client.post("/api/auth/google", json=payload).json()
        from app.control_models import RefreshToken

        with client.app.state.control_session_factory() as session:
            token = session.scalar(select(RefreshToken))
            token.idle_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
            session.commit()
        response = client.post(
            "/api/auth/refresh",
            json={"refresh_token": login["refresh_token"], "device_id": payload["device_id"]},
        )
        assert response.status_code == 401


def test_suspended_user_cannot_login_or_refresh(tmp_path: Path) -> None:
    payload = login_payload()
    with make_client(tmp_path) as client:
        issued = client.post("/api/auth/google", json=payload).json()
        from app.control_models import User

        with client.app.state.control_session_factory() as session:
            user = session.scalar(select(User))
            user.status = "suspended"
            session.commit()

        assert client.post("/api/auth/google", json=payload).status_code == 401
        assert client.post(
            "/api/auth/refresh",
            json={
                "refresh_token": issued["refresh_token"],
                "device_id": payload["device_id"],
            },
        ).status_code == 401


def test_web_login_sets_secure_cookie_and_requires_csrf_for_logout(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/auth/google", json=login_payload(client="web"))
        assert response.status_code == 200
        assert "access_token" not in response.json()
        assert "refresh_token" not in response.json()
        assert response.json()["csrf_token"]
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "secure" in cookie
        assert "samesite=lax" in cookie

        current = client.get("/api/auth/session")
        assert current.status_code == 200
        assert current.json()["user"]["id"] == response.json()["user"]["id"]

        assert client.post("/api/auth/logout").status_code == 403
        logout = client.post(
            "/api/auth/logout", headers={"X-CSRF-Token": response.json()["csrf_token"]}
        )
        assert logout.status_code == 204
        assert client.get("/api/auth/session").status_code == 401


def test_web_session_returns_the_same_csrf_so_a_reload_can_still_write(tmp_path: Path) -> None:
    """重整頁面後 cookie 還在、CSRF token 卻沒了——沒有這條，網頁按 F5 之後就不能寫入。"""
    with make_client(tmp_path) as client:
        login = client.post("/api/auth/google", json=login_payload(client="web")).json()
        reloaded = client.get("/api/auth/session")
        assert reloaded.status_code == 200
        # 推導而非重新亂數：重整與新分頁拿到的是同一顆，彼此不會互相失效
        assert reloaded.json()["csrf_token"] == login["csrf_token"]

        assert client.post(
            "/api/auth/logout", headers={"X-CSRF-Token": reloaded.json()["csrf_token"]}
        ).status_code == 204


def test_android_session_never_gets_a_csrf_token(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        login = client.post("/api/auth/google", json=login_payload()).json()
        session = client.get(
            "/api/auth/session", headers={"Authorization": f"Bearer {login['access_token']}"}
        )
        assert session.status_code == 200
        assert "csrf_token" not in session.json()


def test_web_cookie_cannot_be_replayed_as_bearer_to_bypass_csrf(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.post(
            "/api/auth/google", json=login_payload(client="web")
        ).status_code == 200
        cookie = client.cookies.get("liftlog_session")
        assert cookie
        client.cookies.clear()

        headers = {"Authorization": f"Bearer {cookie}"}
        assert client.get("/api/auth/session", headers=headers).status_code == 401
        assert client.post("/api/auth/logout", headers=headers).status_code == 401


def test_android_access_token_authenticates_without_csrf(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        login = client.post("/api/auth/google", json=login_payload()).json()
        response = client.get(
            "/api/auth/session", headers={"Authorization": f"Bearer {login['access_token']}"}
        )
        assert response.status_code == 200


def test_auth_rate_limit_is_ten_per_minute_per_ip(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        for _ in range(10):
            assert client.post("/api/auth/google", json=login_payload()).status_code == 200
        blocked = client.post("/api/auth/google", json=login_payload())
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0


def test_auth_rate_limit_isolated_by_ip() -> None:
    from app.api.auth import AuthRateLimiter

    limiter = AuthRateLimiter()
    for _ in range(10):
        assert limiter.retry_after("192.0.2.1") is None
    assert limiter.retry_after("192.0.2.1") is not None
    assert limiter.retry_after("192.0.2.2") is None


def test_auth_rate_limiter_releases_stale_ip_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import auth

    now = [0.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: now[0])
    limiter = auth.AuthRateLimiter(window_seconds=60)
    assert limiter.retry_after("192.0.2.1") is None
    now[0] = 61.0
    assert limiter.retry_after("192.0.2.2") is None
    assert "192.0.2.1" not in limiter._attempts


def test_google_access_token_can_download_global_app_release(tmp_path: Path) -> None:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "lift-log-v150.apk").write_bytes(b"apk")
    with make_client(tmp_path) as client:
        client.app.state.settings.release_dir = str(release_dir)
        issued = client.post("/api/auth/google", json=login_payload()).json()
        response = client.get(
            "/api/app/latest",
            headers={"Authorization": f"Bearer {issued['access_token']}"},
        )
        assert response.status_code == 200
        assert response.json()["version_code"] == 150


def test_auth_logs_never_include_google_token_or_email(tmp_path: Path, caplog) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/auth/google", json=login_payload())
        assert response.status_code == 200
    assert "raw-google-id-token" not in caplog.text
    assert "person@example.com" not in caplog.text
