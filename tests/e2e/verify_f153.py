"""F153 整體驗收：同一句自然語言指令，外部 agent 與內建對話產生相同資料列。

frozen acceptance 的驗證方式是「同一句自然語言指令分別經外部 Claude 與內建對話執行，
產生的資料列相同」。這支腳本把那句話做成可重跑的對照：

  外部路徑：本腳本自己驅動 Anthropic Messages API，拿到的 tool_use 一律經
            **`/mcp` HTTP 端點**執行（真 bearer 驗證、真 per-user DB routing）。
            這就是外部 Claude／ChatGPT 走的那條路——證明 MCP tools 是一等公民介面。
  內建路徑：POST `/api/chat/`，拿到 pending_write 後把同一份帶回去確認才寫入
            （F164 的兩段式寫入；確認的是使用者，不是模型）。

兩條路徑各自綁一個乾淨的 user 與各自的 DB，因此比對的是「同一句話造成的資料列」，
不是「同一列被寫兩次」。比對時忽略 id／時間戳／client_uuid 這類與指令無關的欄位。

需要真的 LLM key（`LIFTLOG_LLM_API_KEY` 或 `--key`）——這支不 mock 上游，
mock 掉就證明不了兩條路徑的模型行為一致。沒有 key 時明確回報 blocked 而非假 PASS。

用法：uv run python tests/e2e/verify_f153.py [--key sk-...] [--message "..."]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import Settings  # noqa: E402
from app.db import canonical_user_db_path, make_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Exercise, WorkoutSet  # noqa: E402

DEFAULT_MESSAGE = "幫我記錄今天的臥推，60 公斤 8 下，做了 3 組"
MAX_ROUNDS = 4
GOOGLE_CLIENT_ID = "test-google-client"

# 兩條路徑都要能比對到同一個動作。新帳號的 DB 本來就帶預設動作表，所以這裡只補不足的
# ——撞名回 400 是預期的，不是失敗。
SEED_EXERCISES = [
    {"name_zh": "臥推", "name_en": "Bench Press", "muscle_group": "胸", "is_bodyweight": False},
    {"name_zh": "深蹲", "name_en": "Squat", "muscle_group": "腿", "is_bodyweight": False},
]

_results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    _results.append((ok, label))
    print(f"{'PASS' if ok else 'FAIL'}  {label}")


def _google_claims(raw_token: str) -> dict[str, object]:
    return {
        "sub": f"google-{raw_token}",
        "aud": GOOGLE_CLIENT_ID,
        "iss": "https://accounts.google.com",
        "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
        "nonce": f"nonce-{raw_token}-long-enough",
        "email": f"{raw_token}@example.com",
        "email_verified": True,
    }


def _settings(tmp: Path, key: str) -> Settings:
    return Settings(
        token="legacy-token",
        db_path=str(tmp / "legacy.db"),
        control_db_path=str(tmp / "control.db"),
        user_data_dir=str(tmp / "users"),
        google_client_id=GOOGLE_CLIENT_ID,
        llm_api_key=key,
    )


def _rest(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
        timeout=httpx.Timeout(120),
    )


def _mcp_client(app: Any, plaintext_token: str) -> Client:
    """真正打進 `/mcp/` HTTP 層——外部 agent 看到的就是這個介面。"""

    def factory(*, headers=None, auth=None, follow_redirects=True, timeout=None, **_kw):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://testserver",
            headers=headers,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout or httpx.Timeout(120),
        )

    return Client(
        StreamableHttpTransport(
            url="https://testserver/mcp/", auth=plaintext_token, httpx_client_factory=factory
        )
    )


async def _login(hc: httpx.AsyncClient, name: str) -> dict[str, Any]:
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
    resp.raise_for_status()
    return resp.json()


async def _seed(hc: httpx.AsyncClient, access_token: str) -> None:
    headers = {"Authorization": f"Bearer {access_token}"}
    for payload in SEED_EXERCISES:
        resp = await hc.post("/api/exercises", headers=headers, json=payload)
        if resp.status_code in (200, 201):
            continue
        if resp.status_code == 400 and "already exists" in resp.text:
            continue  # 預設動作表已經有這一條
        raise RuntimeError(f"seed exercise failed: {resp.status_code} {resp.text}")


async def _ask_anthropic(
    key: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], system: str
) -> dict[str, Any]:
    base = os.environ.get("LIFTLOG_LLM_BASE_URL", "https://api.anthropic.com").rstrip("/")
    model = os.environ.get("LIFTLOG_LLM_MODEL", "claude-sonnet-4-5")
    async with httpx.AsyncClient(timeout=httpx.Timeout(120)) as hc:
        resp = await hc.post(
            f"{base}/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 2048,
                "system": system,
                "messages": messages,
                "tools": tools,
            },
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"upstream {resp.status_code}: {resp.text[:400]}")
    return resp.json()


async def run_external(app: Any, hc: httpx.AsyncClient, key: str, message: str) -> str:
    """外部 agent：模型自己決定參數，tool 一律經 `/mcp` HTTP 執行。"""
    session = await _login(hc, "external")
    access = session["access_token"]
    await _seed(hc, access)
    created = await hc.post(
        "/api/mcp-tokens/", headers={"Authorization": f"Bearer {access}"}, json={"name": "claude"}
    )
    created.raise_for_status()
    mcp_token = created.json()["token"]

    async with _mcp_client(app, mcp_token) as client:
        tools = [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema,
            }
            for t in await client.list_tools()
        ]
        messages: list[dict[str, Any]] = [{"role": "user", "content": message}]
        for _ in range(MAX_ROUNDS):
            payload = await _ask_anthropic(key, messages, tools, _system_prompt())
            content = payload.get("content", [])
            uses = [b for b in content if b.get("type") == "tool_use"]
            if not uses:
                break
            results = []
            for use in uses:
                out = await client.call_tool(use["name"], use.get("input") or {})
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use["id"],
                        "content": [{"type": "text", "text": str(out.structured_content)}],
                    }
                )
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": results})
    return session["user"]["id"]


def _system_prompt() -> str:
    from app.api.chat import SYSTEM_PROMPT

    return SYSTEM_PROMPT


async def run_internal(hc: httpx.AsyncClient, message: str) -> tuple[str, bool, bool]:
    """內建對話：先拿 pending_write（零寫入），帶回同一份才真的寫。"""
    session = await _login(hc, "internal")
    access = session["access_token"]
    await _seed(hc, access)
    headers = {"Authorization": f"Bearer {access}"}

    first = await hc.post("/api/chat/", headers=headers, json={"message": message})
    first.raise_for_status()
    body = first.json()
    pending = body.get("pending_write")
    had_dry_run = body.get("dry_run") is not None

    wrote = False
    if pending is not None:
        second = await hc.post("/api/chat/", headers=headers, json={"pending_write": pending})
        second.raise_for_status()
        wrote = second.json().get("result") is not None

    return session["user"]["id"], pending is not None, (had_dry_run and wrote)


def read_rows(settings: Settings, user_id: str) -> list[tuple[str, float, int | None, int | None]]:
    """把該 user DB 的訓練組正規化成可比對的形狀。

    刻意丟掉 id／client_uuid／建立時間——那些每次都不同且與「指令造成什麼」無關。
    留下的是動作、重量、次數、秒數，以及排序後的組序。
    """
    engine = make_engine(_user_db_path(settings, user_id))
    try:
        with sessionmaker(bind=engine)() as s:
            names = {e.id: e.name_zh for e in s.query(Exercise).all()}
            rows = [
                (
                    names.get(w.exercise_id, f"#{w.exercise_id}"),
                    float(w.weight_kg),
                    w.reps,
                    w.duration_seconds,
                )
                for w in s.query(WorkoutSet).filter(WorkoutSet.deleted_at.is_(None)).all()
            ]
    finally:
        engine.dispose()
    return sorted(rows, key=lambda r: (r[0], r[1], r[2] or 0, r[3] or 0))


def _user_db_path(settings: Settings, user_id: str) -> str:
    from app.control_models import User

    engine = make_engine(settings.control_db_path)
    try:
        with sessionmaker(bind=engine)() as control:
            user = control.get(User, user_id)
            if user is None:
                raise RuntimeError(f"user {user_id} not found in control DB")
            return str(canonical_user_db_path(settings.user_data_dir, user.id, user.data_db_name))
    finally:
        engine.dispose()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", default=os.environ.get("LIFTLOG_LLM_API_KEY", "").strip())
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    args = parser.parse_args()

    if not args.key:
        print(
            "BLOCKED  沒有 LLM key：設 LIFTLOG_LLM_API_KEY 或用 --key 傳入。\n"
            "         這支不 mock 上游——mock 掉就證明不了兩條路徑的模型行為一致。"
        )
        return 2

    print(f"指令：{args.message}\n")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = _settings(Path(tmp), args.key)
        app = create_app(settings, google_token_verifier=_google_claims)
        # /mcp 的 StreamableHTTP session manager 活在 lifespan 裡，ASGITransport 不會自己跑
        blocked = ""
        try:
            async with app.router.lifespan_context(app), _rest(app) as hc:
                ext_user = await run_external(app, hc, args.key, args.message)
                int_user, had_pending, confirmed_write = await run_internal(hc, args.message)
        except* RuntimeError as group:
            # 上游拒絕 key 這類環境問題要講清楚，不要丟一坨 traceback 讓人以為是驗收失敗
            blocked = str(group.exceptions[0])
        if blocked:
            print(f"BLOCKED  上游呼叫失敗，無法完成對照：{blocked}")
            return 2

        ext_rows = read_rows(settings, ext_user)
        int_rows = read_rows(settings, int_user)

    print(f"\n外部（/mcp）    ：{ext_rows}")
    print(f"內建（/api/chat）：{int_rows}\n")

    check(bool(ext_rows), "外部 agent 經 /mcp 確實寫入了資料列")
    check(had_pending, "內建對話寫入前先回 pending_write（第一段零寫入）")
    check(confirmed_write, "帶回同一份 pending_write 才真的寫入，且附 dry-run 摘要")
    check(ext_rows == int_rows, "同一句指令：兩條路徑產生的資料列相同")

    failed = [label for ok, label in _results if not ok]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
