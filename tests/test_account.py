"""F148：資料匯出、登出後清憑證、刪帳（近期 Google reauth＋二次確認＋backup tombstone）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import Base

NONCE ="nonce-1-long-enough"


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


def account_settings(tmp_path: Path) -> Settings:
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
        create_app(account_settings(tmp_path), google_token_verifier=verifier),
        base_url="https://testserver",
    )


def login_payload(*, client: str = "android", nonce: str = NONCE) -> dict[str, object]:
    return {
        "id_token": "raw-google-id-token",
        "nonce": nonce,
        "device_id": str(uuid4()),
        "device_name": "Pixel",
        "client": client,
    }


def reauth_payload(**overrides: object) -> dict[str, object]:
    return {"id_token": "raw-google-id-token", "nonce": NONCE, **overrides}


def _log_domain_data(client: TestClient, access_token: str) -> None:
    headers = {"Authorization": f"Bearer {access_token}"}
    exercise = client.post(
        "/api/exercises",
        json={
            "name_zh": "F148測試動作",
            "name_en": "F148TestLift",
            "muscle_group": "腿",
            "is_bodyweight": False,
        },
        headers=headers,
    ).json()
    workout = client.post("/api/workouts", json={}, headers=headers).json()
    client.post(
        f"/api/workouts/{workout['id']}/sets",
        json={
            "client_uuid": "11111111-1111-1111-1111-111111111111",
            "exercise_id": exercise["id"],
            "weight_kg": 80.0,
            "reps": 8,
        },
        headers=headers,
    )
    client.post(
        "/api/body-metrics", json={"weight_kg": 70.0, "body_fat_pct": 18.0}, headers=headers
    )


def test_export_returns_versioned_json_with_domain_data(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        issued = client.post("/api/auth/google", json=login_payload()).json()
        access_token = issued["access_token"]
        _log_domain_data(client, access_token)

        response = client.post(
            "/api/account/export",
            json=reauth_payload(),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["schema_version"] == 1
        assert body["exported_at"]
        # exercises 含種子動作庫＋這次新建的一個——只斷言新建的那個在裡面，不鎖死種子數量
        assert any(row["name_zh"] == "F148測試動作" for row in body["exercises"])
        assert len(body["workouts"]) == 1
        assert len(body["workouts"][0]["sets"]) == 1
        assert len(body["body_metrics"]) == 1


def test_export_covers_every_domain_table(tmp_path: Path) -> None:
    """守門：新增 domain 表卻忘了放進匯出，這條要紅。

    F148 首次驗收就是漏了 push_subscriptions（它沒有對外 GET 端點，
    而匯出當時是照既有 REST 形狀拼的）。這裡直接對 models.Base 的表清單覆核。
    """
    # 匯出鍵名 → 對應的 models 表名；一對多的（sets 嵌在 workouts 裡）也要列出來
    covered = {
        "exercises",
        "templates",
        "template_exercises",
        "workouts",
        "sets",
        "body_metrics",
        "daily_status",
        "push_subscriptions",
        "app_settings",
    }
    # 同步簿記表（D17：domain 表才是事實來源，同步層只是版本簿）不屬於匯出內容
    bookkeeping = {"sync_changes", "sync_entities", "sync_state_server", "mutation_receipts"}
    assert covered == set(Base.metadata.tables) - bookkeeping, (
        "domain 表清單變了，匯出與這條測試都要跟著更新"
    )

    with make_client(tmp_path) as client:
        issued = client.post("/api/auth/google", json=login_payload()).json()
        headers = {"Authorization": f"Bearer {issued['access_token']}"}

        body = client.post("/api/account/export", json=reauth_payload(), headers=headers).json()
        assert "push_subscriptions" in body


def test_export_never_contains_tokens_or_secrets(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        issued = client.post("/api/auth/google", json=login_payload()).json()
        access_token = issued["access_token"]
        refresh_token = issued["refresh_token"]
        mcp = client.post(
            "/api/mcp-tokens/", json={"name": "claude"},
            headers={"Authorization": f"Bearer {access_token}"},
        ).json()
        _log_domain_data(client, access_token)

        response = client.post(
            "/api/account/export",
            json=reauth_payload(),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200
        raw = response.text
        assert access_token not in raw
        assert refresh_token not in raw
        assert mcp["token"] not in raw
        assert "raw-google-id-token" not in raw
        assert str(tmp_path) not in raw  # server 絕對路徑不得洩漏
        forbidden_keys = ("access_token", "refresh_token", "token_hash", "google_sub", "id_token")
        for forbidden_key in forbidden_keys:
            assert forbidden_key not in raw


def test_export_rejects_stale_or_mismatched_reauth(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        issued = client.post("/api/auth/google", json=login_payload()).json()
        access_token = issued["access_token"]

        wrong_nonce = client.post(
            "/api/account/export",
            json=reauth_payload(nonce="a-completely-different-nonce"),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert wrong_nonce.status_code == 401


def test_export_rejects_reauth_for_a_different_google_account(tmp_path: Path) -> None:
    """reauth 的 id_token 驗出另一個 sub——不得讓別人的有效身分幫你重驗過關。"""

    # 用兩個不同 verifier 才能模擬「login 時是自己，reauth 時卻驗出別人」
    calls = {"n": 0}

    def two_stage_verifier(_token: str) -> dict[str, object]:
        calls["n"] += 1
        if calls["n"] == 1:
            return claims()  # 登入：合法本人
        return claims(sub="google-sub-attacker")  # reauth：驗出別人

    with TestClient(
        create_app(account_settings(tmp_path), google_token_verifier=two_stage_verifier),
        base_url="https://testserver",
    ) as client:
        issued = client.post("/api/auth/google", json=login_payload()).json()
        access_token = issued["access_token"]
        response = client.post(
            "/api/account/export",
            json=reauth_payload(),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 401


def test_export_rate_limited_at_three_per_hour(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        issued = client.post("/api/auth/google", json=login_payload()).json()
        access_token = issued["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        for _ in range(3):
            assert client.post(
                "/api/account/export", json=reauth_payload(), headers=headers
            ).status_code == 200
        blocked = client.post("/api/account/export", json=reauth_payload(), headers=headers)
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0


def test_export_rejects_legacy_scope(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/account/export",
            json=reauth_payload(),
            headers={"Authorization": "Bearer legacy-token"},
        )
        assert response.status_code == 401


def test_delete_account_requires_confirm_literal(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        issued = client.post("/api/auth/google", json=login_payload()).json()
        access_token = issued["access_token"]
        response = client.post(
            "/api/account/delete",
            json=reauth_payload(confirm="delete"),  # 大小寫不符也不算確認
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 400  # app 的 validation handler 統一回 400，見 app/errors.py


def test_delete_account_revokes_everything_and_deletes_data_db(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        issued = client.post("/api/auth/google", json=login_payload()).json()
        access_token = issued["access_token"]
        refresh_token = issued["refresh_token"]
        mcp = client.post(
            "/api/mcp-tokens/", json={"name": "claude"},
            headers={"Authorization": f"Bearer {access_token}"},
        ).json()
        _log_domain_data(client, access_token)

        from app.control_models import McpToken, RefreshToken, User

        with client.app.state.control_session_factory() as control:
            user = control.scalar(select(User))
            user_id, data_db_name = user.id, user.data_db_name
        data_db_path = tmp_path / "users" / data_db_name
        assert data_db_path.is_file()

        response = client.post(
            "/api/account/delete",
            json=reauth_payload(confirm="DELETE"),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 200

        # 憑證立即失效
        assert client.get(
            "/api/auth/session", headers={"Authorization": f"Bearer {access_token}"}
        ).status_code == 401
        assert client.post(
            "/api/auth/refresh",
            json={"refresh_token": refresh_token, "device_id": login_payload()["device_id"]},
        ).status_code == 401
        assert client.get(
            "/api/mcp-tokens/", headers={"Authorization": f"Bearer {mcp['token']}"}
        ).status_code == 401

        with client.app.state.control_session_factory() as control:
            reloaded = control.get(User, user_id)
            assert reloaded.status == "closed"
            assert all(
                token.revoked_at is not None
                for token in control.scalars(select(McpToken).where(McpToken.user_id == user_id))
            )
            assert all(
                token.status == "revoked"
                for token in control.scalars(select(RefreshToken))
            )

        assert not data_db_path.is_file()


def test_delete_account_writes_tombstone_with_thirty_day_retention(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        issued = client.post("/api/auth/google", json=login_payload()).json()
        access_token = issued["access_token"]
        before = datetime.now(UTC).replace(tzinfo=None)
        client.post(
            "/api/account/delete",
            json=reauth_payload(confirm="DELETE"),
            headers={"Authorization": f"Bearer {access_token}"},
        )

        from app.control_models import AccountTombstone, User

        with client.app.state.control_session_factory() as control:
            user = control.scalar(select(User))
            tombstone = control.get(AccountTombstone, user.id)
            assert tombstone is not None
            assert tombstone.purge_after - tombstone.deleted_at == timedelta(days=30)
            assert tombstone.deleted_at >= before


def test_delete_account_rate_limited_at_three_per_hour(tmp_path: Path) -> None:
    """帳號刪一次後憑證就失效，所以逼近限流上限得用未刪除的帳號連續打錯的 reauth 才能不真的刪掉。"""
    with make_client(tmp_path) as client:
        issued = client.post("/api/auth/google", json=login_payload()).json()
        access_token = issued["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        # 前三次都用會被 reauth 擋下來的請求（401），但一樣算進限流計數
        for _ in range(3):
            response = client.post(
                "/api/account/delete",
                json=reauth_payload(confirm="DELETE", nonce="wrong-nonce-value-long"),
                headers=headers,
            )
            assert response.status_code == 401
        blocked = client.post(
            "/api/account/delete", json=reauth_payload(confirm="DELETE"), headers=headers
        )
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0


def test_delete_account_failure_does_not_report_fake_success(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        issued = client.post("/api/auth/google", json=login_payload()).json()
        access_token = issued["access_token"]
        response = client.post(
            "/api/account/delete",
            json=reauth_payload(confirm="DELETE", nonce="wrong-nonce-value-long"),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 401

        from app.control_models import User

        with client.app.state.control_session_factory() as control:
            user = control.scalar(select(User))
            assert user.status == "active"  # 失敗不得偷偷關閉帳號


def test_deleted_account_login_is_rejected(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        issued = client.post("/api/auth/google", json=login_payload()).json()
        access_token = issued["access_token"]
        client.post(
            "/api/account/delete",
            json=reauth_payload(confirm="DELETE"),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        # 同一個 Google 帳號想重新登入——closed 狀態擋下，不會復活舊帳號
        relogin = client.post("/api/auth/google", json=login_payload())
        assert relogin.status_code == 401


def test_tombstone_blocks_recovery_even_if_control_row_looks_active_again(
    tmp_path: Path,
) -> None:
    """模擬局部還原：control DB 的 user 列被恢復成 active，但 tombstone 仍在——啟動流程仍要拒絕。"""
    settings = account_settings(tmp_path)
    with make_client(tmp_path) as client:
        issued = client.post("/api/auth/google", json=login_payload()).json()
        access_token = issued["access_token"]
        client.post(
            "/api/account/delete",
            json=reauth_payload(confirm="DELETE"),
            headers={"Authorization": f"Bearer {access_token}"},
        )

        from app.control_models import User
        from app.db import initialize_data_db

        with client.app.state.control_session_factory() as control:
            user = control.scalar(select(User))
            user_id, data_db_name = user.id, user.data_db_name
            user.status = "active"  # 模擬 control.db 被還原成刪除前的舊快照
            control.commit()

        # 模擬資料庫檔案也被還原回磁碟（backup 裡拿出來的 blob）
        restored_path = tmp_path / "users" / data_db_name
        initialize_data_db(restored_path)
        assert restored_path.is_file()

    # 重新啟動 server（新的 create_app 呼叫，模擬程序重啟時的啟動流程）
    from app.main import create_app as create_app_again

    def verifier(_token: str) -> dict[str, object]:
        return claims()

    app2 = create_app_again(settings, google_token_verifier=verifier)
    assert user_id in app2.state.unavailable_user_ids


def test_is_tombstoned_service_function(tmp_path: Path) -> None:
    from app.control_db import make_control_session_factory
    from app.control_models import AccountTombstone, User
    from app.services import account as account_service
    from app.services.auth import utcnow

    factory = make_control_session_factory(str(tmp_path / "control.db"))
    with factory() as control:
        user = User(
            id="11111111-1111-1111-1111-111111111111",
            google_sub="sub-1",
            email="a@example.com",
            data_db_name="11111111-1111-1111-1111-111111111111.db",
            created_at=utcnow(),
        )
        control.add(user)
        control.commit()
        assert account_service.is_tombstoned(control, user.id) is False

        control.add(
            AccountTombstone(
                user_id=user.id, deleted_at=utcnow(), purge_after=utcnow() + timedelta(days=30)
            )
        )
        control.commit()
        assert account_service.is_tombstoned(control, user.id) is True


def test_delete_account_is_idempotent_at_service_layer(tmp_path: Path) -> None:
    """雙重刪除不得因為 tombstone primary key 撞號而 500（正常流程走不到，這裡直接測 service）。"""
    from app.control_db import make_control_session_factory
    from app.services import account as account_service

    settings = account_settings(tmp_path)
    factory = make_control_session_factory(settings.control_db_path)
    with make_client(tmp_path) as client:
        client.post("/api/auth/google", json=login_payload())
        from app.control_models import User

        with client.app.state.control_session_factory() as control:
            user_id = control.scalar(select(User)).id

    account_service.delete_account(factory, settings, user_id)
    account_service.delete_account(factory, settings, user_id)  # 不得拋例外
