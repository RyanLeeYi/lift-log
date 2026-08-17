from __future__ import annotations

import re
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


def test_refresh_replay_after_grace_period_revokes_only_that_family(tmp_path: Path) -> None:
    """F156驗收2：超過 60 秒寬限期後重播，維持盜用偵測——吊銷整個 family 並回 401。"""
    payload = login_payload()
    with make_client(tmp_path) as client:
        login = client.post("/api/auth/google", json=payload).json()
        rotated = client.post(
            "/api/auth/refresh",
            json={"refresh_token": login["refresh_token"], "device_id": payload["device_id"]},
        )
        assert rotated.status_code == 200
        assert rotated.json()["refresh_token"] != login["refresh_token"]

        from app.control_models import RefreshToken
        from app.services.auth import REFRESH_REPLAY_GRACE, token_hash

        with client.app.state.control_session_factory() as session:
            used = session.scalar(
                select(RefreshToken).where(
                    RefreshToken.token_hash == token_hash(login["refresh_token"])
                )
            )
            used.used_at = datetime.now(UTC).replace(tzinfo=None) - (
                REFRESH_REPLAY_GRACE + timedelta(seconds=1)
            )
            session.commit()

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


def test_refresh_replay_within_grace_period_rotates_without_revoking_family(
    tmp_path: Path,
) -> None:
    """F156驗收1：60 秒寬限內重播照常輪替發新 token，不吊銷 family；

    先前輪替出的新 token 仍可用（Android 背景同步與 webview 併發重送同一顆 token 的情境）。
    """
    payload = login_payload()
    with make_client(tmp_path) as client:
        login = client.post("/api/auth/google", json=payload).json()
        rotated = client.post(
            "/api/auth/refresh",
            json={"refresh_token": login["refresh_token"], "device_id": payload["device_id"]},
        ).json()

        from app.control_models import RefreshToken
        from app.services.auth import REFRESH_REPLAY_GRACE, token_hash

        with client.app.state.control_session_factory() as session:
            used = session.scalar(
                select(RefreshToken).where(
                    RefreshToken.token_hash == token_hash(login["refresh_token"])
                )
            )
            used.used_at = datetime.now(UTC).replace(tzinfo=None) - (
                REFRESH_REPLAY_GRACE - timedelta(seconds=10)
            )
            session.commit()

        replay = client.post(
            "/api/auth/refresh",
            json={"refresh_token": login["refresh_token"], "device_id": payload["device_id"]},
        )
        assert replay.status_code == 200
        assert replay.json()["refresh_token"] != login["refresh_token"]

        still_usable = client.post(
            "/api/auth/refresh",
            json={"refresh_token": rotated["refresh_token"], "device_id": payload["device_id"]},
        )
        assert still_usable.status_code == 200


def test_refresh_replay_grace_window_anchored_to_first_use_not_extended(
    tmp_path: Path,
) -> None:
    """F156驗收3：重播不更新 used_at，連續重播不會把寬限窗口往後展延。"""
    payload = login_payload()
    with make_client(tmp_path) as client:
        login = client.post("/api/auth/google", json=payload).json()
        client.post(
            "/api/auth/refresh",
            json={"refresh_token": login["refresh_token"], "device_id": payload["device_id"]},
        )

        from app.control_models import RefreshToken
        from app.services.auth import REFRESH_REPLAY_GRACE, token_hash

        def load_original(session):
            return session.scalar(
                select(RefreshToken).where(
                    RefreshToken.token_hash == token_hash(login["refresh_token"])
                )
            )

        backdated_used_at = datetime.now(UTC).replace(tzinfo=None) - (
            REFRESH_REPLAY_GRACE - timedelta(seconds=10)
        )
        with client.app.state.control_session_factory() as session:
            load_original(session).used_at = backdated_used_at
            session.commit()

        within_grace_replay = client.post(
            "/api/auth/refresh",
            json={"refresh_token": login["refresh_token"], "device_id": payload["device_id"]},
        )
        assert within_grace_replay.status_code == 200

        with client.app.state.control_session_factory() as session:
            reloaded_used_at = load_original(session).used_at
            # 重播沒有把 used_at 推到「現在」——寬限窗口的錨點沒有被展延
            assert abs((reloaded_used_at - backdated_used_at).total_seconds()) < 1
            load_original(session).used_at = datetime.now(UTC).replace(tzinfo=None) - (
                REFRESH_REPLAY_GRACE + timedelta(seconds=1)
            )
            session.commit()

        past_grace_replay = client.post(
            "/api/auth/refresh",
            json={"refresh_token": login["refresh_token"], "device_id": payload["device_id"]},
        )
        assert past_grace_replay.status_code == 401


def test_revoked_refresh_token_rejected_even_within_replay_grace(tmp_path: Path) -> None:
    """F156驗收4：family 已吊銷的 revoked token，即使時間上落在寬限期內也不放行。"""
    payload = login_payload()
    with make_client(tmp_path) as client:
        login = client.post("/api/auth/google", json=payload).json()

        from app.control_models import RefreshToken

        with client.app.state.control_session_factory() as session:
            token = session.scalar(select(RefreshToken))
            token.status = "revoked"
            token.used_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()

        response = client.post(
            "/api/auth/refresh",
            json={"refresh_token": login["refresh_token"], "device_id": payload["device_id"]},
        )
        assert response.status_code == 401


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


def test_web_session_slides_forward_on_each_authenticated_request(tmp_path: Path) -> None:
    """F157驗收1：帶有效 cookie 的請求會把 access_expires_at 往後推，不是固定 12 小時到期。"""
    with make_client(tmp_path) as client:
        client.post("/api/auth/google", json=login_payload(client="web"))

        from app.control_models import AuthSession

        soon = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)
        with client.app.state.control_session_factory() as session:
            auth_session = session.scalar(select(AuthSession))
            auth_session.access_expires_at = soon
            session.commit()

        response = client.get("/api/auth/session")
        assert response.status_code == 200

        with client.app.state.control_session_factory() as session:
            reloaded = session.scalar(select(AuthSession))
            # 滑動視窗把到期往後推回一整個 WEB_SESSION_TTL，遠超過原本快到期的 5 分鐘
            assert reloaded.access_expires_at > soon + timedelta(hours=1)


def test_web_session_absolute_cap_rejects_after_ninety_days_even_if_active(
    tmp_path: Path,
) -> None:
    """F157驗收2：從登入起算超過絕對上限（90 天）就必須重新登入，滑動不能無限展延。"""
    with make_client(tmp_path) as client:
        client.post("/api/auth/google", json=login_payload(client="web"))

        from app.control_models import AuthSession
        from app.services.auth import REFRESH_ABSOLUTE_TTL

        with client.app.state.control_session_factory() as session:
            auth_session = session.scalar(select(AuthSession))
            auth_session.created_at = datetime.now(UTC).replace(tzinfo=None) - (
                REFRESH_ABSOLUTE_TTL + timedelta(seconds=1)
            )
            auth_session.access_expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(
                hours=1
            )
            session.commit()

        response = client.get("/api/auth/session")
        assert response.status_code == 401


def test_web_session_expires_after_idle_beyond_sliding_window(tmp_path: Path) -> None:
    """F157驗收3：閒置超過滑動窗口後 session 失效並回 401。"""
    with make_client(tmp_path) as client:
        client.post("/api/auth/google", json=login_payload(client="web"))

        from app.control_models import AuthSession

        with client.app.state.control_session_factory() as session:
            auth_session = session.scalar(select(AuthSession))
            auth_session.access_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(
                seconds=1
            )
            session.commit()

        response = client.get("/api/auth/session")
        assert response.status_code == 401


def test_auth_logs_never_include_google_token_or_email(tmp_path: Path, caplog) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/auth/google", json=login_payload())
        assert response.status_code == 200
    assert "raw-google-id-token" not in caplog.text
    assert "person@example.com" not in caplog.text


def test_web_session_cookie_max_age_slides_with_the_session(tmp_path: Path) -> None:
    """F157驗收1：cookie 的 Max-Age 也要跟著推，不只 DB 欄位。

    cookie 的到期是瀏覽器單方面執行的——Max-Age 一到就丟掉、之後不再送出，
    伺服器端的 session 還有多久有效它不知道。只推 DB 的話，使用者仍會在登入後
    精確 12 小時被登出，也就是這條 feature 要修的原始症狀。
    """
    from app.control_models import AuthSession
    from app.services.auth import WEB_SESSION_TTL

    with make_client(tmp_path) as client:
        login = client.post("/api/auth/google", json=login_payload(client="web"))
        assert "max-age" in login.headers["set-cookie"].lower()

        # 讓 session 逼近到期：剩 5 分鐘
        soon = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5)
        with client.app.state.control_session_factory() as session:
            session.scalar(select(AuthSession)).access_expires_at = soon
            session.commit()

        response = client.get("/api/auth/session")
        assert response.status_code == 200

        cookie = response.headers.get("set-cookie")
        assert cookie is not None, "後續請求沒有重發 cookie，瀏覽器端仍是登入當下的 Max-Age"
        max_age = int(re.search(r"[Mm]ax-[Aa]ge=(\d+)", cookie).group(1))
        # 推回接近一整個 WEB_SESSION_TTL，而不是原本只剩的 5 分鐘
        assert max_age > WEB_SESSION_TTL.total_seconds() - 60


def test_web_session_cookie_max_age_never_outlives_the_absolute_cap(tmp_path: Path) -> None:
    """F157驗收2：cookie 也不能活過絕對上限——否則瀏覽器會一直送一顆早已失效的 cookie。"""
    from app.control_models import AuthSession
    from app.services.auth import REFRESH_ABSOLUTE_TTL

    with make_client(tmp_path) as client:
        client.post("/api/auth/google", json=login_payload(client="web"))

        # 登入日回撥到接近絕對上限：只剩 10 分鐘
        with client.app.state.control_session_factory() as session:
            auth_session = session.scalar(select(AuthSession))
            auth_session.created_at = (
                datetime.now(UTC).replace(tzinfo=None)
                - REFRESH_ABSOLUTE_TTL
                + timedelta(minutes=10)
            )
            session.commit()

        response = client.get("/api/auth/session")
        assert response.status_code == 200

        cookie = response.headers["set-cookie"]
        max_age = int(re.search(r"[Mm]ax-[Aa]ge=(\d+)", cookie).group(1))
        assert max_age <= timedelta(minutes=10).total_seconds()


def test_web_session_cookie_also_slides_on_ordinary_domain_routes(tmp_path: Path) -> None:
    """F157驗收1：一般 API 路由（走 require_domain_auth）也要重發 cookie。

    只補 /api/auth/session 不夠——那條只有重整頁面才會打。持續操作卻沒重整的人
    同樣要拿到延長。
    """
    from app.services.auth import WEB_SESSION_TTL

    with make_client(tmp_path) as client:
        client.post("/api/auth/google", json=login_payload(client="web"))

        response = client.get("/api/exercises")
        assert response.status_code == 200

        cookie = response.headers.get("set-cookie")
        assert cookie is not None, "一般路由沒有重發 cookie，瀏覽器端的 Max-Age 不會延長"
        max_age = int(re.search(r"[Mm]ax-[Aa]ge=(\d+)", cookie).group(1))
        assert max_age > WEB_SESSION_TTL.total_seconds() - 60


def test_web_session_cookie_slides_on_account_routes_too(tmp_path: Path) -> None:
    """F157驗收1：帳號路由（/api/account/*）不走 require_domain_auth，也必須續發 cookie。

    第一版把重發寫在各個呼叫點上，這條路徑就漏了。現在改成 middleware 統一寫入，
    這個測試守的是「不會再有第 N 個呼叫點漏掉」。
    """
    from app.services.auth import WEB_SESSION_TTL

    with make_client(tmp_path) as client:
        login = client.post("/api/auth/google", json=login_payload(client="web")).json()

        response = client.post(
            "/api/account/export",
            json={"id_token": "raw-google-id-token", "nonce": NONCE},
            headers={"X-CSRF-Token": login["csrf_token"]},
        )
        assert response.status_code == 200

        cookie = response.headers.get("set-cookie")
        assert cookie is not None, "帳號路由沒有續發 cookie——瀏覽器端的 Max-Age 不會延長"
        max_age = int(re.search(r"[Mm]ax-[Aa]ge=(\d+)", cookie).group(1))
        assert max_age > WEB_SESSION_TTL.total_seconds() - 60


def test_csrf_rejection_does_not_shorten_the_web_session(tmp_path: Path) -> None:
    """F157：403 拒絕的是「這一次請求」，不是「這個 session」——打錯一次不該提早登出。"""
    from app.services.auth import WEB_SESSION_TTL

    with make_client(tmp_path) as client:
        client.post("/api/auth/google", json=login_payload(client="web"))

        response = client.post("/api/body-metrics", json={"weight_kg": 70, "date": "2026-08-01"})
        assert response.status_code == 403  # 沒帶 CSRF token

        cookie = response.headers.get("set-cookie")
        assert cookie is not None, "CSRF 失敗的回應也該續發 cookie，否則打錯一次就開始倒數"
        max_age = int(re.search(r"[Mm]ax-[Aa]ge=(\d+)", cookie).group(1))
        assert max_age > WEB_SESSION_TTL.total_seconds() - 60
