"""F164：內建對話的後端 endpoint。

一句自然語言 → LLM → 經 F163 橋接層呼叫與 `/mcp` 完全相同的那組 tool。
寫入兩段式：第一次只跑 dry-run 並回 `pending_write`，client 帶回同一份才真的寫。

LLM key 兩種來源（F153 決議 (a) server 代打）：server `.env` 的 `LIFTLOG_LLM_API_KEY`，
或使用者自填、由 client 每次請求以 `X-LLM-API-Key` 夾帶。自填 key 只活在這個請求的
生命週期內——不寫 DB、不寫 log、不回傳給任何 client。
"""

import hashlib
import hmac
import json
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastmcp import Client
from pydantic import BaseModel, Field

from app.api.deps import require_domain_auth
from app.mcp import run_tool

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(require_domain_auth)])

USER_KEY_HEADER = "X-LLM-API-Key"

# 這三個 tool 會改資料，一律先 dry-run 等使用者確認；其餘是唯讀查詢，直接跑。
WRITE_TOOLS = {"log_workout", "log_body_metrics", "log_daily_status"}
# 只有它吃得下 F152 的 dry_run；另外兩個是單列 upsert，預覽就是參數本身。
DRY_RUN_TOOLS = {"log_workout"}

# 一次請求最多讓 LLM 連續呼叫幾輪唯讀 tool。上限存在的理由是成本與延遲，
# 不是正確性——正常查詢一到兩輪就收斂。
MAX_TOOL_ROUNDS = 4

SYSTEM_PROMPT = """\
你是健身紀錄助手，用繁體中文回答。使用者的訓練資料只能經 tool 取得，不要自己編。
查詢類問題先呼叫對應 tool 再依結果回答。要記錄訓練或體重時直接呼叫寫入 tool——
系統會先攔下來給使用者確認，你不必自己再問一次確認。
噸位（kg）與總秒數是兩個並列指標，不要相加。
"""


class PendingWrite(BaseModel):
    """待確認的寫入：tool 名、完整參數，以及 server 自己核發的簽章。

    ③ 要求「真正寫入只在 client 帶回**同一份** pending_write 時才發生」——沒有簽章的話
    server 分不出這份是自己核發的還是 client 自己捏的，第一段（LLM ＋ dry-run）就形同
    可跳過：任何人都能直接送一份 pending_write 進來寫。簽章是無狀態的做法，
    不必為一次確認建表或存 session。
    """

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    signature: str = ""


class ChatIn(BaseModel):
    message: str = ""
    pending_write: PendingWrite | None = None


class ChatOut(BaseModel):
    reply: str
    pending_write: PendingWrite | None = None
    # F152 摘要（只有 log_workout 有）；其餘寫入 tool 為 None，預覽看 pending_write.arguments
    dry_run: dict[str, Any] | None = None
    # 確認後的實際寫入結果
    result: dict[str, Any] | None = None


class _UpstreamError(Exception):
    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _sign(request: Request, tool: str, arguments: dict[str, Any]) -> str:
    """對 (tool, arguments) 簽名。金鑰沿用 web session 的 CSRF 金鑰（已持久化在 control DB），
    不另外生一把——多一把金鑰就多一個會漂掉的東西。"""
    payload = json.dumps([tool, arguments], sort_keys=True, ensure_ascii=False, default=str)
    secret = request.app.state.web_csrf_secret
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _user_id(request: Request) -> str:
    """legacy 共用 token 沒有 user 身分，內建對話一律不給（F164①）。"""
    scope = request.state.domain_scope
    if scope == "legacy":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return scope


def _api_key(request: Request) -> str:
    """使用者自填優先；兩者皆無回 `llm_key_missing`，不靜默成功。"""
    user_key = (request.headers.get(USER_KEY_HEADER) or "").strip()
    key = user_key or request.app.state.settings.llm_api_key
    if not key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="llm_key_missing")
    return key


async def _tool_specs(request: Request) -> list[dict[str, Any]]:
    """給 LLM 的 tool 定義＝`/mcp` 對外那份，不另外維護第二張表（快取在 app.state）。"""
    cached = getattr(request.app.state, "chat_tool_specs", None)
    if cached is not None:
        return cached
    async with Client(request.app.state.mcp_server) as client:
        specs = [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            for tool in await client.list_tools()
        ]
    request.app.state.chat_tool_specs = specs
    return specs


async def _ask_llm(
    request: Request, key: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
) -> dict[str, Any]:
    """呼叫上游 Messages API。錯誤一律轉成錯誤碼——不回傳上游 body，也不記 key。"""
    settings = request.app.state.settings
    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            resp = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.llm_model,
                    "max_tokens": settings.llm_max_tokens,
                    "system": SYSTEM_PROMPT,
                    "messages": messages,
                    "tools": tools,
                },
            )
    except httpx.TimeoutException as exc:
        raise _UpstreamError("llm_timeout", status.HTTP_504_GATEWAY_TIMEOUT) from exc
    except httpx.HTTPError as exc:
        raise _UpstreamError("llm_unreachable", status.HTTP_502_BAD_GATEWAY) from exc

    if resp.status_code == 401 or resp.status_code == 403:
        raise _UpstreamError("llm_unauthorized", status.HTTP_502_BAD_GATEWAY)
    if resp.status_code == 429:
        raise _UpstreamError("llm_rate_limited", status.HTTP_429_TOO_MANY_REQUESTS)
    if resp.status_code >= 400:
        raise _UpstreamError("llm_upstream_error", status.HTTP_502_BAD_GATEWAY)
    return resp.json()


def _reply_text(content: list[dict[str, Any]]) -> str:
    return "\n".join(
        block.get("text", "") for block in content if block.get("type") == "text"
    ).strip()


async def _call_tool(request: Request, user_id: str, name: str, arguments: dict) -> Any:
    return await run_tool(request.app.state.mcp_server, user_id, name, arguments)


@router.post("/")
async def chat(data: ChatIn, request: Request) -> ChatOut:
    user_id = _user_id(request)

    # 第二段：client 帶回同一份 pending_write＝使用者按了確認，這時才真的寫。
    # 這條路徑不呼叫 LLM——確認的是使用者，不是模型。
    if data.pending_write is not None:
        pending = data.pending_write
        if pending.tool not in WRITE_TOOLS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="not_a_write_tool")
        arguments = {k: v for k, v in pending.arguments.items() if k != "dry_run"}
        # 沒跑過第一段、或參數被改過，簽章就對不起來——這時不是「換個寫法再試」，是拒絕。
        if not hmac.compare_digest(pending.signature, _sign(request, pending.tool, arguments)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="pending_write_invalid"
            )
        result = await _call_tool(request, user_id, pending.tool, arguments)
        return ChatOut(reply="已寫入。", result=result)

    if not data.message.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty_message")

    key = _api_key(request)
    tools = await _tool_specs(request)
    messages: list[dict[str, Any]] = [{"role": "user", "content": data.message}]

    try:
        for _round in range(MAX_TOOL_ROUNDS):
            payload = await _ask_llm(request, key, messages, tools)
            content = payload.get("content", [])
            uses = [block for block in content if block.get("type") == "tool_use"]
            if not uses:
                return ChatOut(reply=_reply_text(content))

            write = next((u for u in uses if u["name"] in WRITE_TOOLS), None)
            if write is not None:
                # 第一段：只算會發生什麼，零寫入。回 pending_write 等使用者確認。
                arguments = {k: v for k, v in (write.get("input") or {}).items() if k != "dry_run"}
                summary = None
                if write["name"] in DRY_RUN_TOOLS:
                    summary = await _call_tool(
                        request, user_id, write["name"], {**arguments, "dry_run": True}
                    )
                return ChatOut(
                    reply=_reply_text(content),
                    pending_write=PendingWrite(
                        tool=write["name"],
                        arguments=arguments,
                        signature=_sign(request, write["name"], arguments),
                    ),
                    dry_run=summary,
                )

            results = []
            for use in uses:
                output = await _call_tool(request, user_id, use["name"], use.get("input") or {})
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use["id"],
                        "content": [{"type": "text", "text": str(output)}],
                    }
                )
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": results})

        # 連續 MAX_TOOL_ROUNDS 輪還沒收斂：如實說，不假裝有答案
        raise _UpstreamError("llm_tool_loop_exhausted", status.HTTP_502_BAD_GATEWAY)
    except _UpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
