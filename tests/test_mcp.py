"""MCP server（PRD R7/R7b、F147）：tools 重用 services；/mcp 掛載與 auth 走 HTTP 驗證。"""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.control_models import McpToken
from app.db import make_engine
from app.main import create_app
from app.mcp import create_mcp
from app.models import BodyMetric, Exercise, Workout, WorkoutSet
from app.schemas import BodyMetricIn, LogSetIn, LogWorkoutIn, TemplateCreate, TemplateExerciseIn
from app.services.body_metrics import upsert_body_metric
from app.services.mcp_tokens import DEFAULT_EXPIRY_DAYS
from app.services.templates import create_template
from app.services.workouts import log_workout

EXPECTED_TOOLS = {
    "query_workouts",
    "get_progress",
    "list_templates",
    "get_body_metrics",
    "log_workout",
    "log_body_metrics",
}


@pytest.fixture()
def mcp_server(session_factory: sessionmaker) -> FastMCP:
    with session_factory() as session:
        session.add(Exercise(name_zh="深蹲", name_en="Squat", muscle_group="腿"))
        session.commit()
    return create_mcp(session_factory, token="test-token")


def _structured(result) -> dict:
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_mcp_lists_expected_tools_and_prompt(mcp_server: FastMCP) -> None:
    async with Client(mcp_server) as client:
        tool_names = {tool.name for tool in await client.list_tools()}
        prompt_names = {prompt.name for prompt in await client.list_prompts()}
    assert EXPECTED_TOOLS <= tool_names
    assert "log-workout-interview" in prompt_names


@pytest.mark.asyncio
async def test_mcp_log_workout_writes_and_returns_summary(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "log_workout",
            {
                "sets": [
                    {"exercise": "深蹲", "weight_kg": 80, "reps": 8},
                    {"exercise": "squat", "weight_kg": 80, "reps": 8},
                ]
            },
        )
    payload = _structured(result)
    assert payload["sets_count"] == 2
    assert payload["tonnage_kg"] == 1280
    with session_factory() as session:
        assert session.query(WorkoutSet).count() == 2


@pytest.mark.asyncio
async def test_mcp_log_workout_unknown_exercise_rejects_with_suggestions(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "log_workout",
            {"sets": [{"exercise": "深躦", "weight_kg": 80, "reps": 8}]},
        )
    payload = _structured(result)
    assert payload["error"] == "unknown exercise"
    assert payload["unknown"] == ["深躦"]
    assert "深蹲 Squat" in payload["suggestions"]
    with session_factory() as session:
        assert session.query(Workout).count() == 0


@pytest.mark.asyncio
async def test_mcp_log_body_metrics_and_get_body_metrics(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    async with Client(mcp_server) as client:
        logged = await client.call_tool(
            "log_body_metrics", {"weight_kg": 101.6, "date": "2026-07-10"}
        )
        fetched = await client.call_tool(
            "get_body_metrics", {"start_date": "2026-07-01", "end_date": "2026-07-31"}
        )
    assert _structured(logged)["weight_kg"] == 101.6
    metrics = _structured(fetched)["metrics"]
    assert [(m["date"], m["weight_kg"]) for m in metrics] == [("2026-07-10", 101.6)]
    with session_factory() as session:
        assert session.query(BodyMetric).count() == 1


@pytest.mark.asyncio
async def test_mcp_log_body_metrics_out_of_range_rejected(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    async with Client(mcp_server) as client:
        result = await client.call_tool("log_body_metrics", {"weight_kg": 500})
    assert "error" in _structured(result)
    with session_factory() as session:
        assert session.query(BodyMetric).count() == 0


@pytest.mark.asyncio
async def test_mcp_query_workouts_and_progress(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    with session_factory() as session:
        upsert_body_metric(session, BodyMetricIn(date=date(2026, 7, 9), weight_kg=100))
        log_workout(
            session,
            LogWorkoutIn(
                sets=[
                    LogSetIn(exercise="深蹲", weight_kg=80, reps=8),
                    LogSetIn(exercise="深蹲", weight_kg=85, reps=6),
                ],
                date=date(2026, 7, 10),
            ),
        )

    async with Client(mcp_server) as client:
        workouts = await client.call_tool(
            "query_workouts",
            {"start_date": "2026-07-01", "end_date": "2026-07-31", "exercise": "squat"},
        )
        progress = await client.call_tool("get_progress", {"exercise": "深蹲"})

    listed = _structured(workouts)["workouts"]
    assert len(listed) == 1
    assert listed[0]["date"] == "2026-07-10"
    assert [(s["exercise"], s["weight_kg"], s["reps"]) for s in listed[0]["sets"]] == [
        ("深蹲 Squat", 80.0, 8),
        ("深蹲 Squat", 85.0, 6),
    ]

    points = _structured(progress)["points"]
    assert points == [
        {"date": "2026-07-10", "top_weight_kg": 85.0, "reps": 6, "duration_seconds": None}
    ]


@pytest.mark.asyncio
async def test_mcp_log_workout_empty_sets_returns_error_contract(
    mcp_server: FastMCP,
) -> None:
    """sets=[] 要回 {"error": ...}，不得裸拋 ValidationError 違反工具契約。"""
    async with Client(mcp_server) as client:
        result = await client.call_tool("log_workout", {"sets": []})
    assert "error" in _structured(result)


@pytest.mark.asyncio
async def test_mcp_log_workout_client_uuid_replay_idempotent(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    """LLM timeout 重試帶同 client_uuid：不得重複寫入。"""
    args = {
        "sets": [{"exercise": "深蹲", "weight_kg": 80, "reps": 8}],
        "client_uuid": "llm-retry-01",
    }
    async with Client(mcp_server) as client:
        first = _structured(await client.call_tool("log_workout", args))
        second = _structured(await client.call_tool("log_workout", args))
    assert second["workout_id"] == first["workout_id"]
    with session_factory() as session:
        assert session.query(WorkoutSet).count() == 1


@pytest.mark.asyncio
async def test_mcp_get_progress_unknown_exercise(mcp_server: FastMCP) -> None:
    async with Client(mcp_server) as client:
        result = await client.call_tool("get_progress", {"exercise": "nope"})
    assert _structured(result)["error"] == "exercise not found"


@pytest.mark.asyncio
async def test_mcp_list_templates(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    with session_factory() as session:
        exercise_id = session.query(Exercise).one().id
        items = [TemplateExerciseIn(exercise_id=exercise_id, default_sets=3)]
        create_template(session, TemplateCreate(name="練腿日", exercises=items))
    async with Client(mcp_server) as client:
        result = await client.call_tool("list_templates", {})
    templates = _structured(result)["templates"]
    assert [t["name"] for t in templates] == ["練腿日"]
    assert templates[0]["exercises"][0]["name_zh"] == "深蹲"


@pytest.mark.asyncio
async def test_mcp_list_templates_includes_rest_hint(
    mcp_server: FastMCP, session_factory: sessionmaker
) -> None:
    """F12（PRD R10）：MCP 課表輸出帶 rest_hint_seconds，agent 才能討論休息配置。"""
    with session_factory() as session:
        exercise_id = session.query(Exercise).one().id
        items = [
            TemplateExerciseIn(exercise_id=exercise_id, default_sets=3, rest_hint_seconds=90)
        ]
        create_template(session, TemplateCreate(name="背日", exercises=items))
    async with Client(mcp_server) as client:
        result = await client.call_tool("list_templates", {})
    templates = _structured(result)["templates"]
    assert templates[0]["exercises"][0]["rest_hint_seconds"] == 90


def test_http_mcp_requires_token(anon_client: TestClient) -> None:
    resp = anon_client.post("/mcp/", json={})
    assert resp.status_code == 401
    resp = anon_client.post(
        "/mcp/", json={}, headers={"Authorization": "Bearer wrong-token"}
    )
    assert resp.status_code == 401


def test_http_mcp_non_ascii_token_rejected_as_401(anon_client: TestClient) -> None:
    """非 ASCII token 必須乾淨回 401，不得因 compare_digest TypeError 變 500。"""
    resp = anon_client.post(
        "/mcp/", json={}, headers={b"Authorization": "Bearer 密碼token".encode()}
    )
    assert resp.status_code == 401


def test_http_mcp_correct_token_passes_auth(client: TestClient) -> None:
    # 不驗完整 MCP 握手（in-memory client 已覆蓋工具行為），只驗 token 通過 auth 層
    resp = client.post("/mcp/", json={})
    assert resp.status_code != 401


def test_http_mcp_without_trailing_slash_reaches_mcp(client: TestClient) -> None:
    """connector 給的 URL 是 /mcp（無斜線），不得掉進靜態檔 mount 變 405。"""
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "probe", "version": "1.0"},
        },
    }
    resp = client.post(
        "/mcp", json=init, headers={"Accept": "application/json, text/event-stream"}
    )
    assert resp.status_code == 200

    bad_token = client.post(
        "/mcp",
        json=init,
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer wrong-token",
        },
    )
    assert bad_token.status_code == 401


# ---------- F147: User-scoped MCP token ----------


def _multi_user_settings(tmp_path: Path) -> Settings:
    return Settings(
        token="legacy-token",
        db_path=str(tmp_path / "legacy.db"),
        control_db_path=str(tmp_path / "control.db"),
        user_data_dir=str(tmp_path / "users"),
        google_client_id="test-google-client",
    )


def _google_claims(raw_token: str) -> dict[str, object]:
    return {
        "sub": f"google-{raw_token}",
        "aud": "test-google-client",
        "iss": "https://accounts.google.com",
        "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
        "nonce": f"nonce-{raw_token}-long-enough",
        "email": f"{raw_token}@example.com",
        "email_verified": True,
    }


def _rest_client(app) -> httpx.AsyncClient:
    """走真的 ASGI 呼叫鏈（含 lifespan、middleware），不必開真連線。"""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    )


async def _login_android(hc: httpx.AsyncClient, name: str) -> dict:
    resp = await hc.post(
        "/api/auth/google",
        json={
            "id_token": name,
            "nonce": f"nonce-{name}-long-enough",
            "device_id": str(uuid4()),
            "device_name": name,
            "client": "android",
        },
    )
    assert resp.status_code == 200
    return resp.json()


def _mcp_client(app, plaintext_token: str) -> Client:
    """真正打進 /mcp/ HTTP 層（bearer 驗證、per-user DB routing 都會生效）。"""

    def httpx_factory(*, headers=None, auth=None, follow_redirects=True, timeout=None, **_kw):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://testserver",
            headers=headers,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout or httpx.Timeout(30),
        )

    return Client(
        StreamableHttpTransport(
            url="https://testserver/mcp/",
            auth=plaintext_token,
            httpx_client_factory=httpx_factory,
        )
    )


@pytest.mark.asyncio
async def test_mcp_token_create_list_revoke_and_hash_only_storage(tmp_path: Path) -> None:
    app = create_app(_multi_user_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app):
        async with _rest_client(app) as hc:
            issued = await _login_android(hc, "alice")
            headers = {"Authorization": f"Bearer {issued['access_token']}"}

            created = await hc.post("/api/mcp-tokens/", headers=headers, json={"name": "claude"})
            assert created.status_code == 201
            body = created.json()
            plaintext = body["token"]
            assert plaintext and body["name"] == "claude"

            listed = await hc.get("/api/mcp-tokens/", headers=headers)
            assert listed.status_code == 200
            rows = listed.json()
            assert len(rows) == 1
            assert "token" not in rows[0] and "token_hash" not in rows[0]
            assert rows[0]["revoked_at"] is None

            revoke = await hc.delete(f"/api/mcp-tokens/{body['id']}", headers=headers)
            assert revoke.status_code == 204
            # 已撤銷再撤銷一次仍是 204（冪等），不得變 404
            again = await hc.delete(f"/api/mcp-tokens/{body['id']}", headers=headers)
            assert again.status_code == 204

            after = (await hc.get("/api/mcp-tokens/", headers=headers)).json()
            assert after[0]["revoked_at"] is not None

        with app.state.control_session_factory() as control:
            row = control.scalar(select(McpToken).where(McpToken.id == body["id"]))
            assert row.token_hash != plaintext
            assert plaintext not in row.token_hash
            assert len(row.token_hash) == 64  # sha256 hex digest，看不出明文長度或內容


@pytest.mark.asyncio
async def test_mcp_token_endpoints_reject_legacy_scope(tmp_path: Path) -> None:
    """legacy 單一 token 沒有 user 身分，不能管理 MCP token（F147）。"""
    app = create_app(_multi_user_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app):
        async with _rest_client(app) as hc:
            resp = await hc.post(
                "/api/mcp-tokens/",
                headers={"Authorization": "Bearer legacy-token"},
                json={"name": "x"},
            )
            assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mcp_wrong_token_over_http_401(tmp_path: Path) -> None:
    app = create_app(_multi_user_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app):
        async with _rest_client(app) as hc:
            resp = await hc.post(
                "/mcp/", json={}, headers={"Authorization": "Bearer not-a-real-token"}
            )
            assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mcp_revoked_user_token_rejected_immediately(tmp_path: Path) -> None:
    app = create_app(_multi_user_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app):
        async with _rest_client(app) as hc:
            issued = await _login_android(hc, "alice")
            headers = {"Authorization": f"Bearer {issued['access_token']}"}
            created = (
                await hc.post("/api/mcp-tokens/", headers=headers, json={"name": "claude"})
            ).json()
            plaintext = created["token"]

            async with _mcp_client(app, plaintext) as mcp_client:
                tools = await mcp_client.list_tools()
                assert {t.name for t in tools}  # 撤銷前握手正常

            await hc.delete(f"/api/mcp-tokens/{created['id']}", headers=headers)

            resp = await hc.post(
                "/mcp/", json={}, headers={"Authorization": f"Bearer {plaintext}"}
            )
            assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mcp_user_token_only_reads_and_writes_own_data(tmp_path: Path) -> None:
    """F147／PRD R6：user A 的 MCP token 讀不到也寫不到 user B 的資料（跨 user IDOR）。"""
    app = create_app(_multi_user_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app):
        async with _rest_client(app) as hc:
            alice = await _login_android(hc, "alice")
            bob = await _login_android(hc, "bob")
            bob_headers = {"Authorization": f"Bearer {bob['access_token']}"}

            # bob 先在自己的資料庫留一筆，之後確認 alice 的 token 看不到
            bob_metric = await hc.post(
                "/api/body-metrics",
                headers=bob_headers,
                json={"weight_kg": 70, "date": "2026-08-01"},
            )
            assert bob_metric.status_code == 201

            alice_token = (
                await hc.post(
                    "/api/mcp-tokens/",
                    headers={"Authorization": f"Bearer {alice['access_token']}"},
                    json={"name": "claude"},
                )
            ).json()["token"]

        async with _mcp_client(app, alice_token) as mcp_client:
            metrics_before = _structured(await mcp_client.call_tool("get_body_metrics", {}))
            assert metrics_before["metrics"] == []  # 讀不到 bob 的資料

            written = _structured(
                await mcp_client.call_tool(
                    "log_body_metrics", {"weight_kg": 88.8, "date": "2026-08-10"}
                )
            )
            assert written["weight_kg"] == 88.8

        async with _rest_client(app) as hc:
            bob_metrics = await hc.get("/api/body-metrics", headers=bob_headers)
            bob_dates = {row["date"] for row in bob_metrics.json()}
            assert bob_dates == {"2026-08-01"}  # 寫不進 bob 的資料庫，仍只有自己那筆


@pytest.mark.asyncio
async def test_mcp_revoke_other_users_token_returns_404(tmp_path: Path) -> None:
    app = create_app(_multi_user_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app):
        async with _rest_client(app) as hc:
            alice = await _login_android(hc, "alice")
            bob = await _login_android(hc, "bob")
            alice_headers = {"Authorization": f"Bearer {alice['access_token']}"}
            bob_headers = {"Authorization": f"Bearer {bob['access_token']}"}

            alice_token = (
                await hc.post("/api/mcp-tokens/", headers=alice_headers, json={"name": "claude"})
            ).json()

            resp = await hc.delete(f"/api/mcp-tokens/{alice_token['id']}", headers=bob_headers)
            assert resp.status_code == 404

            still_active = (await hc.get("/api/mcp-tokens/", headers=alice_headers)).json()
            assert still_active[0]["revoked_at"] is None

            missing = await hc.delete("/api/mcp-tokens/does-not-exist", headers=alice_headers)
            assert missing.status_code == 404


@pytest.mark.asyncio
async def test_mcp_write_reaches_android_sync_pull(tmp_path: Path) -> None:
    """F147／PRD R9：MCP mutation 經 services 寫 change log，Android pull 拿得到。"""
    app = create_app(_multi_user_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app):
        async with _rest_client(app) as hc:
            issued = await _login_android(hc, "alice")
            headers = {"Authorization": f"Bearer {issued['access_token']}"}
            plaintext = (
                await hc.post("/api/mcp-tokens/", headers=headers, json={"name": "claude"})
            ).json()["token"]

        async with _mcp_client(app, plaintext) as mcp_client:
            await mcp_client.call_tool(
                "log_body_metrics", {"weight_kg": 91.2, "date": "2026-08-11"}
            )

        async with _rest_client(app) as hc:
            pulled = await hc.get("/api/sync/pull", headers=headers, params={"cursor": 0})
            assert pulled.status_code == 200
            changes = pulled.json()["changes"]
            body_metric_changes = [c for c in changes if c["entity_type"] == "body_metric"]
            assert any(c["payload"]["weight_kg"] == 91.2 for c in body_metric_changes)


@pytest.mark.asyncio
async def test_mcp_token_defaults_to_expiring_and_writable(tmp_path: Path) -> None:
    """F158①：預設**有**期限。明文要貼進第三方設定檔，永久有效不該是預設值。"""
    app = create_app(_multi_user_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app):
        async with _rest_client(app) as hc:
            issued = await _login_android(hc, "alice")
            headers = {"Authorization": f"Bearer {issued['access_token']}"}
            created = (
                await hc.post("/api/mcp-tokens/", headers=headers, json={"name": "claude"})
            ).json()

        with app.state.control_session_factory() as control:
            row = control.scalar(select(McpToken).where(McpToken.id == created["id"]))
            assert row.expires_at is not None
            assert row.read_only is False  # 預設可寫，維持 F147 既有行為
            lifetime = row.expires_at - row.created_at
            assert lifetime == timedelta(days=DEFAULT_EXPIRY_DAYS)


@pytest.mark.asyncio
async def test_expired_mcp_token_rejected_like_a_revoked_one(tmp_path: Path) -> None:
    """F158②：到期即失效，且與已撤銷走同一條 401——分不出是哪一種。"""
    app = create_app(_multi_user_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app):
        async with _rest_client(app) as hc:
            issued = await _login_android(hc, "alice")
            headers = {"Authorization": f"Bearer {issued['access_token']}"}
            created = (
                await hc.post("/api/mcp-tokens/", headers=headers, json={"name": "claude"})
            ).json()
            plaintext = created["token"]

            async with _mcp_client(app, plaintext) as mcp_client:
                assert {t.name for t in await mcp_client.list_tools()}  # 到期前握手正常

            with app.state.control_session_factory() as control:
                row = control.scalar(select(McpToken).where(McpToken.id == created["id"]))
                row.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
                control.commit()

            resp = await hc.post(
                "/mcp/", json={}, headers={"Authorization": f"Bearer {plaintext}"}
            )
            assert resp.status_code == 401


@pytest.mark.asyncio
async def test_read_only_mcp_token_can_query_but_not_write(tmp_path: Path) -> None:
    """F158⑤：唯讀 token 只能跑查詢類 tool；三個寫入類 tool 一律拒絕並回可讀錯誤，
    而且拒絕發生在寫入之前（拒絕後 body metrics 仍為空）。"""
    app = create_app(_multi_user_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app):
        async with _rest_client(app) as hc:
            issued = await _login_android(hc, "alice")
            headers = {"Authorization": f"Bearer {issued['access_token']}"}
            created = (
                await hc.post("/api/mcp-tokens/", headers=headers, json={"name": "claude"})
            ).json()
            plaintext = created["token"]

        with app.state.control_session_factory() as control:
            row = control.scalar(select(McpToken).where(McpToken.id == created["id"]))
            row.read_only = True
            control.commit()

        async with _mcp_client(app, plaintext) as mcp_client:
            listed = await mcp_client.call_tool("get_body_metrics", {})
            assert "error" not in _structured(listed)

            for tool, args in (
                ("log_body_metrics", {"weight_kg": 91.2, "date": "2026-08-11"}),
                ("log_daily_status", {"energy": 3, "date": "2026-08-11"}),
                (
                    "log_workout",
                    {"sets": [{"exercise": "深蹲", "weight_kg": 60, "reps": 5}]},
                ),
            ):
                denied = _structured(await mcp_client.call_tool(tool, args))
                assert denied.get("error"), (tool, denied)
                assert "read-only" in denied["error"], (tool, denied)

            after = _structured(await mcp_client.call_tool("get_body_metrics", {}))
            assert not after.get("metrics"), after  # 拒絕發生在寫入之前


@pytest.mark.asyncio
async def test_writable_mcp_token_still_writes_after_f158_scopes(tmp_path: Path) -> None:
    """F158⑤ 對照組：預設可寫的 token 不受 scopes 引入影響。"""
    app = create_app(_multi_user_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app):
        async with _rest_client(app) as hc:
            issued = await _login_android(hc, "alice")
            headers = {"Authorization": f"Bearer {issued['access_token']}"}
            plaintext = (
                await hc.post("/api/mcp-tokens/", headers=headers, json={"name": "claude"})
            ).json()["token"]
        async with _mcp_client(app, plaintext) as mcp_client:
            out = _structured(
                await mcp_client.call_tool("log_body_metrics", {"weight_kg": 91.2})
            )
            assert "error" not in out, out


@pytest.mark.asyncio
async def test_mcp_token_issued_before_f158_keeps_working(tmp_path: Path) -> None:
    """F158⑥：升級不得讓既有 token 失效。expires_at NULL＝不過期、read_only 0＝可寫。"""
    app = create_app(_multi_user_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app):
        async with _rest_client(app) as hc:
            issued = await _login_android(hc, "alice")
            headers = {"Authorization": f"Bearer {issued['access_token']}"}
            created = (
                await hc.post("/api/mcp-tokens/", headers=headers, json={"name": "claude"})
            ).json()
            plaintext = created["token"]

            # 把它改回 F158 之前的樣子：沒有到期時間
            with app.state.control_session_factory() as control:
                row = control.scalar(select(McpToken).where(McpToken.id == created["id"]))
                row.expires_at = None
                control.commit()

            async with _mcp_client(app, plaintext) as mcp_client:
                assert {t.name for t in await mcp_client.list_tools()}


def test_control_db_adds_f158_columns_to_existing_mcp_tokens_table(tmp_path: Path) -> None:
    """F158⑥：`create_all` 只建缺席的表，既有 mcp_tokens 得靠 ALTER 補欄位。

    少了那段，升級後的舊庫第一次查 mcp_tokens 就是 OperationalError。
    """
    from sqlalchemy import text

    from app.control_db import make_control_session_factory

    db_path = tmp_path / "control.db"
    # 先造一顆 F158 之前的表：只有舊欄位
    pre_f158 = make_engine(str(db_path))
    with pre_f158.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS mcp_tokens"))
        connection.execute(
            text(
                "CREATE TABLE mcp_tokens ("
                "id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL, "
                "token_hash TEXT NOT NULL UNIQUE, created_at DATETIME NOT NULL, "
                "last_used_at DATETIME, revoked_at DATETIME)"
            )
        )
    pre_f158.dispose()

    factory = make_control_session_factory(str(db_path))
    with factory() as control:
        columns = {
            row[1] for row in control.execute(text("PRAGMA table_info(mcp_tokens)"))
        }
    assert "expires_at" in columns
    assert "read_only" in columns
