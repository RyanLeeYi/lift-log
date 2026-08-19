"""F158（第三段）：MCP token API 層——建立時帶到期／唯讀、列表含新欄位、legacy token 401。

服務層的到期／唯讀語意（DB 欄位、`resolve_token` 到期判定、舊庫 ALTER）已由第一段的
`tests/test_mcp.py` 與 service 測試釘住；這支只驗 **API 這一層的契約**——
`McpTokenCreateIn`/`McpTokenOut`/`McpTokenCreateOut` 有沒有把 `expires_in_days`／
`read_only` 正確傳進 service、正確吐回回應（F158 acceptance 4），以及 legacy 單一 token
仍然不能碰這組端點（acceptance 7）。UI 這一側由 `tests/e2e/verify_f158.py` 覆蓋。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

NONCE = "nonce-f158-long-enough"


def _claims(**overrides: object) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "sub": "google-sub-f158",
        "aud": "test-google-client",
        "iss": "https://accounts.google.com",
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": NONCE,
        "email": "f158@example.com",
        "email_verified": True,
        **overrides,
    }


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        token="legacy-token",
        db_path=str(tmp_path / "legacy.db"),
        control_db_path=str(tmp_path / "control.db"),
        user_data_dir=str(tmp_path / "users"),
        google_client_id="test-google-client",
    )


def _make_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(_settings(tmp_path), google_token_verifier=lambda _t: _claims()),
        base_url="https://testserver",
    )


def _login(client: TestClient) -> str:
    resp = client.post(
        "/api/auth/google",
        json={
            "id_token": "raw-google-id-token",
            "nonce": NONCE,
            "device_id": str(uuid4()),
            "device_name": "Pixel",
            "client": "android",
        },
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_create_default_is_90_days_and_writable(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        headers = {"Authorization": f"Bearer {_login(client)}"}
        resp = client.post("/api/mcp-tokens/", headers=headers, json={"name": "claude"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["read_only"] is False
        created_at = datetime.fromisoformat(body["created_at"])
        expires_at = datetime.fromisoformat(body["expires_at"])
        assert timedelta(days=89) < (expires_at - created_at) < timedelta(days=91)


def test_create_with_custom_expiry_and_read_only(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        headers = {"Authorization": f"Bearer {_login(client)}"}
        resp = client.post(
            "/api/mcp-tokens/",
            headers=headers,
            json={"name": "chatgpt", "expires_in_days": 30, "read_only": True},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["read_only"] is True
        created_at = datetime.fromisoformat(body["created_at"])
        expires_at = datetime.fromisoformat(body["expires_at"])
        assert timedelta(days=29) < (expires_at - created_at) < timedelta(days=31)


def test_create_permanent_requires_explicit_none(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        headers = {"Authorization": f"Bearer {_login(client)}"}
        resp = client.post(
            "/api/mcp-tokens/",
            headers=headers,
            json={"name": "gemini", "expires_in_days": None},
        )
        assert resp.status_code == 201
        assert resp.json()["expires_at"] is None


def test_create_rejects_non_positive_expiry(tmp_path: Path) -> None:
    """`app.errors` 把 pydantic validation error 統一轉成 400（見 app/errors.py），不是 422。"""
    with _make_client(tmp_path) as client:
        headers = {"Authorization": f"Bearer {_login(client)}"}
        resp = client.post(
            "/api/mcp-tokens/",
            headers=headers,
            json={"name": "bad", "expires_in_days": 0},
        )
        assert resp.status_code == 400
        assert "expires_in_days" in resp.json()["error"]


def test_list_includes_expiry_and_read_only_but_not_secret(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        headers = {"Authorization": f"Bearer {_login(client)}"}
        client.post(
            "/api/mcp-tokens/",
            headers=headers,
            json={"name": "claude", "expires_in_days": 180, "read_only": True},
        )
        rows = client.get("/api/mcp-tokens/", headers=headers).json()
        assert len(rows) == 1
        row = rows[0]
        assert row["read_only"] is True
        assert row["expires_at"] is not None
        assert "token" not in row and "token_hash" not in row


def test_legacy_token_rejected_on_all_mcp_token_endpoints(tmp_path: Path) -> None:
    """acceptance 7：legacy `LIFTLOG_TOKEN` 仍然管不了 MCP token（_user_id 的既有拒絕）。"""
    with _make_client(tmp_path) as client:
        legacy_headers = {"Authorization": "Bearer legacy-token"}

        create = client.post("/api/mcp-tokens/", headers=legacy_headers, json={"name": "x"})
        assert create.status_code == 401

        listed = client.get("/api/mcp-tokens/", headers=legacy_headers)
        assert listed.status_code == 401

        # 用一顆真使用者建立的 token 當目標 id，證明擋在 legacy 身分本身，不是「id 不存在」
        real_headers = {"Authorization": f"Bearer {_login(client)}"}
        created = client.post(
            "/api/mcp-tokens/", headers=real_headers, json={"name": "claude"}
        ).json()
        revoke = client.delete(f"/api/mcp-tokens/{created['id']}", headers=legacy_headers)
        assert revoke.status_code == 401
