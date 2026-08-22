"""F164：內建對話 endpoint。上游 LLM 一律以 MockTransport stub 掉，測試不打外網。"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.api import chat
from app.config import Settings
from app.main import create_app

CHAT_URL = "/api/chat/"


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(
        token="legacy-token",
        db_path=str(tmp_path / "legacy.db"),
        control_db_path=str(tmp_path / "control.db"),
        user_data_dir=str(tmp_path / "users"),
        google_client_id="test-google-client",
        **overrides,
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
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver")


async def _login(hc: httpx.AsyncClient, name: str) -> dict:
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


class _Upstream:
    """假的 Anthropic Messages API：記下每次收到的 header 與 body，回預先排好的回應。"""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            import json

            self.calls.append(
                {"headers": dict(request.headers), "body": json.loads(request.content)}
            )
            nxt = self._responses.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt

        transport = httpx.MockTransport(handler)
        real = httpx.AsyncClient

        def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            # 這是全域的 httpx.AsyncClient；只有沒自帶 transport 的呼叫（＝chat 打上游）
            # 才換成 mock，測試自己那顆 ASGITransport client 不受影響。
            kwargs.setdefault("transport", transport)
            return real(*args, **kwargs)

        monkeypatch.setattr(chat.httpx, "AsyncClient", factory)


def _text(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}
    )


def _tool_use(name: str, arguments: dict, text: str = "") -> httpx.Response:
    content: list[dict[str, Any]] = []
    if text:
        content.append({"type": "text", "text": text})
    content.append({"type": "tool_use", "id": "tu_1", "name": name, "input": arguments})
    return httpx.Response(200, json={"content": content, "stop_reason": "tool_use"})


@pytest.mark.asyncio
async def test_chat_rejects_legacy_token(tmp_path: Path) -> None:
    """F164①：legacy 共用 token 沒有 user 身分，一律 403。"""
    app = create_app(_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app), _rest_client(app) as hc:
        resp = await hc.post(
            CHAT_URL,
            headers={"Authorization": "Bearer legacy-token"},
            json={"message": "上週練了什麼"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_chat_without_any_key_returns_llm_key_missing(tmp_path: Path) -> None:
    """F164⑤：server 沒設、使用者也沒填 → 4xx ＋ llm_key_missing，不靜默成功。"""
    app = create_app(_settings(tmp_path), google_token_verifier=_google_claims)
    async with app.router.lifespan_context(app), _rest_client(app) as hc:
        issued = await _login(hc, "alice")
        resp = await hc.post(
            CHAT_URL,
            headers={"Authorization": f"Bearer {issued['access_token']}"},
            json={"message": "上週練了什麼"},
        )
    assert resp.status_code == 400
    assert resp.json() == {"error": "llm_key_missing"}


@pytest.mark.asyncio
async def test_user_supplied_key_wins_and_never_comes_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F164④：自填 key 優先於 server key，只活在請求生命週期內。"""
    upstream = _Upstream([_text("嗨")])
    upstream.install(monkeypatch)
    app = create_app(
        _settings(tmp_path, llm_api_key="server-key"), google_token_verifier=_google_claims
    )
    async with app.router.lifespan_context(app), _rest_client(app) as hc:
        issued = await _login(hc, "alice")
        resp = await hc.post(
            CHAT_URL,
            headers={
                "Authorization": f"Bearer {issued['access_token']}",
                chat.USER_KEY_HEADER: "user-own-key",
            },
            json={"message": "哈囉"},
        )
    assert resp.status_code == 200
    assert upstream.calls[0]["headers"]["x-api-key"] == "user-own-key"
    assert "user-own-key" not in resp.text
    # 不落地：control DB 與 user data DB 的位元組裡都不該出現這把 key
    for db in tmp_path.rglob("*.db"):
        assert b"user-own-key" not in db.read_bytes()


@pytest.mark.asyncio
async def test_server_key_used_when_user_has_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upstream = _Upstream([_text("嗨")])
    upstream.install(monkeypatch)
    app = create_app(
        _settings(tmp_path, llm_api_key="server-key"), google_token_verifier=_google_claims
    )
    async with app.router.lifespan_context(app), _rest_client(app) as hc:
        issued = await _login(hc, "alice")
        resp = await hc.post(
            CHAT_URL,
            headers={"Authorization": f"Bearer {issued['access_token']}"},
            json={"message": "哈囉"},
        )
    assert resp.status_code == 200
    assert upstream.calls[0]["headers"]["x-api-key"] == "server-key"


@pytest.mark.asyncio
async def test_read_tool_runs_as_caller_and_cannot_reach_other_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F164②：tool 經橋接層綁呼叫者本人的 DB；LLM 給什麼參數都換不到別人的資料。"""
    upstream = _Upstream(
        [
            _tool_use("get_body_metrics", {}),
            _text("你目前沒有體重紀錄。"),
            _tool_use("get_body_metrics", {}),
            _text("最新體重 70 公斤。"),
        ]
    )
    upstream.install(monkeypatch)
    app = create_app(
        _settings(tmp_path, llm_api_key="server-key"), google_token_verifier=_google_claims
    )
    async with app.router.lifespan_context(app), _rest_client(app) as hc:
        alice = await _login(hc, "alice")
        bob = await _login(hc, "bob")
        created = await hc.post(
            "/api/body-metrics",
            headers={"Authorization": f"Bearer {bob['access_token']}"},
            json={"weight_kg": 70, "date": "2026-08-01"},
        )
        assert created.status_code == 201

        alice_resp = await hc.post(
            CHAT_URL,
            headers={"Authorization": f"Bearer {alice['access_token']}"},
            json={"message": "我的體重紀錄"},
        )
        bob_resp = await hc.post(
            CHAT_URL,
            headers={"Authorization": f"Bearer {bob['access_token']}"},
            json={"message": "我的體重紀錄"},
        )

    assert alice_resp.status_code == 200
    # alice 那輪送回 LLM 的 tool_result 不含 bob 的資料
    alice_tool_result = upstream.calls[1]["body"]["messages"][-1]["content"][0]["content"][0][
        "text"
    ]
    assert "70" not in alice_tool_result
    bob_tool_result = upstream.calls[3]["body"]["messages"][-1]["content"][0]["content"][0]["text"]
    assert "70" in bob_tool_result
    assert bob_resp.json()["reply"] == "最新體重 70 公斤。"


@pytest.mark.asyncio
async def test_write_is_two_phase_dry_run_then_confirm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F164③：第一次只 dry-run 回 pending_write；確認後才寫，且確認不再打 LLM。"""
    upstream = _Upstream(
        [
            _tool_use(
                "log_workout",
                {
                    "sets": [{"exercise": "深蹲", "weight_kg": 60, "reps": 5}],
                    "date": "2026-08-12",
                    "create_missing": True,
                },
                "幫你記這組",
            )
        ]
    )
    upstream.install(monkeypatch)
    app = create_app(
        _settings(tmp_path, llm_api_key="server-key"), google_token_verifier=_google_claims
    )
    async with app.router.lifespan_context(app), _rest_client(app) as hc:
        issued = await _login(hc, "alice")
        headers = {"Authorization": f"Bearer {issued['access_token']}"}
        seed = (await hc.get("/api/sync/pull", headers=headers, params={"cursor": 0})).json()

        first = await hc.post(CHAT_URL, headers=headers, json={"message": "深蹲 60 公斤 5 下"})
        assert first.status_code == 200
        body = first.json()
        assert body["pending_write"]["tool"] == "log_workout"
        assert body["dry_run"]["will_create_count"] == 1

        # 未確認前：零新增列、零 change log
        listed = await hc.get(
            "/api/workouts",
            headers=headers,
            params={"start_date": "2026-08-01", "end_date": "2026-08-31"},
        )
        assert listed.json() == []
        after_dry = (await hc.get("/api/sync/pull", headers=headers, params={"cursor": 0})).json()
        assert after_dry["changes"] == seed["changes"]

        confirmed = await hc.post(
            CHAT_URL, headers=headers, json={"pending_write": body["pending_write"]}
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["result"]["sets_count"] == 1

        pulled = (await hc.get("/api/sync/pull", headers=headers, params={"cursor": 0})).json()
        assert any(c["entity_type"] == "set" for c in pulled["changes"])

    # 確認那一次沒有再打 LLM
    assert len(upstream.calls) == 1


@pytest.mark.asyncio
async def test_single_turn_sends_no_conversation_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F164⑦：單輪查詢，不存對話歷史——第二次請求送出去的仍只有這一句。"""
    upstream = _Upstream([_text("第一句"), _text("第二句")])
    upstream.install(monkeypatch)
    app = create_app(
        _settings(tmp_path, llm_api_key="server-key"), google_token_verifier=_google_claims
    )
    async with app.router.lifespan_context(app), _rest_client(app) as hc:
        issued = await _login(hc, "alice")
        headers = {"Authorization": f"Bearer {issued['access_token']}"}
        await hc.post(CHAT_URL, headers=headers, json={"message": "第一問"})
        await hc.post(CHAT_URL, headers=headers, json={"message": "第二問"})

    assert [m["content"] for m in upstream.calls[1]["body"]["messages"]] == ["第二問"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_response", "expected_status", "expected_code"),
    [
        (
            httpx.Response(401, json={"error": {"message": "invalid x-api-key"}}),
            502,
            "llm_unauthorized",
        ),
        (httpx.Response(429, json={"error": {"message": "rate limit"}}), 429, "llm_rate_limited"),
        (httpx.ReadTimeout("too slow"), 504, "llm_timeout"),
    ],
)
async def test_upstream_errors_become_readable_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    upstream_response: Any,
    expected_status: int,
    expected_code: str,
) -> None:
    """F164⑥：401／429／逾時轉成錯誤碼；回應不帶 key 也不帶上游 body。"""
    upstream = _Upstream([upstream_response])
    upstream.install(monkeypatch)
    app = create_app(
        _settings(tmp_path, llm_api_key="server-key"), google_token_verifier=_google_claims
    )
    async with app.router.lifespan_context(app), _rest_client(app) as hc:
        issued = await _login(hc, "alice")
        resp = await hc.post(
            CHAT_URL,
            headers={
                "Authorization": f"Bearer {issued['access_token']}",
                chat.USER_KEY_HEADER: "user-own-key",
            },
            json={"message": "哈囉"},
        )
    assert resp.status_code == expected_status
    assert resp.json() == {"error": expected_code}
    assert "user-own-key" not in resp.text
    assert "invalid x-api-key" not in resp.text


@pytest.mark.asyncio
async def test_confirm_rejects_non_write_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """確認路徑只接受寫入類 tool——不然它會變成一條繞過 LLM 的任意 tool 呼叫器。"""
    app = create_app(
        _settings(tmp_path, llm_api_key="server-key"), google_token_verifier=_google_claims
    )
    async with app.router.lifespan_context(app), _rest_client(app) as hc:
        issued = await _login(hc, "alice")
        resp = await hc.post(
            CHAT_URL,
            headers={"Authorization": f"Bearer {issued['access_token']}"},
            json={"pending_write": {"tool": "query_workouts", "arguments": {}}},
        )
    assert resp.status_code == 400
    assert resp.json() == {"error": "not_a_write_tool"}


@pytest.mark.asyncio
async def test_chat_tools_are_exactly_the_mcp_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """送給 LLM 的 tool 定義＝/mcp 那份，沒有第二張表。"""
    upstream = _Upstream([_text("嗨")])
    upstream.install(monkeypatch)
    app = create_app(
        _settings(tmp_path, llm_api_key="server-key"), google_token_verifier=_google_claims
    )
    async with app.router.lifespan_context(app), _rest_client(app) as hc:
        issued = await _login(hc, "alice")
        await hc.post(
            CHAT_URL,
            headers={"Authorization": f"Bearer {issued['access_token']}"},
            json={"message": "哈囉"},
        )
        from fastmcp import Client

        async with Client(app.state.mcp_server) as client:
            mcp_names = {tool.name for tool in await client.list_tools()}

    assert {tool["name"] for tool in upstream.calls[0]["body"]["tools"]} == mcp_names


@pytest.mark.asyncio
async def test_confirm_without_prior_dry_run_is_rejected(tmp_path: Path) -> None:
    """F164③ 驗收 P2：沒跑過第一段就直接送 pending_write 不得寫入。

    2026-08-22 獨立驗收重現的洞：確認路徑原本只檢查 tool 名在不在寫入清單裡，
    其餘完全信任 client——等於整個 dry-run 確認流程可以跳過。
    """
    app = create_app(
        _settings(tmp_path, llm_api_key="server-key"), google_token_verifier=_google_claims
    )
    async with app.router.lifespan_context(app), _rest_client(app) as hc:
        issued = await _login(hc, "alice")
        headers = {"Authorization": f"Bearer {issued['access_token']}"}
        resp = await hc.post(
            CHAT_URL,
            headers=headers,
            json={
                "pending_write": {
                    "tool": "log_body_metrics",
                    "arguments": {"weight_kg": 71.5, "date": "2026-01-02"},
                }
            },
        )
        assert resp.status_code == 400
        assert resp.json() == {"error": "pending_write_invalid"}

        # 真的沒寫進去
        metrics = await hc.get("/api/body-metrics", headers=headers)
        assert metrics.json() == []


@pytest.mark.asyncio
async def test_confirm_rejects_tampered_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F164③：拿到合法簽章後偷改參數也不行——簽的是 (tool, arguments) 這一整份。"""
    upstream = _Upstream(
        [_tool_use("log_body_metrics", {"weight_kg": 70, "date": "2026-01-02"}, "幫你記")]
    )
    upstream.install(monkeypatch)
    app = create_app(
        _settings(tmp_path, llm_api_key="server-key"), google_token_verifier=_google_claims
    )
    async with app.router.lifespan_context(app), _rest_client(app) as hc:
        issued = await _login(hc, "alice")
        headers = {"Authorization": f"Bearer {issued['access_token']}"}
        first = await hc.post(CHAT_URL, headers=headers, json={"message": "體重 70"})
        pending = first.json()["pending_write"]
        assert pending["signature"]

        tampered = {**pending, "arguments": {**pending["arguments"], "weight_kg": 999}}
        resp = await hc.post(CHAT_URL, headers=headers, json={"pending_write": tampered})
        assert resp.status_code == 400
        assert resp.json() == {"error": "pending_write_invalid"}

        # 原封不動帶回去才寫得進
        ok = await hc.post(CHAT_URL, headers=headers, json={"pending_write": pending})
        assert ok.status_code == 200
        metrics = (await hc.get("/api/body-metrics", headers=headers)).json()
        assert [row["weight_kg"] for row in metrics] == [70]
