"""User-scoped MCP token 管理（F147／PRD R6）。

明文只在 `create_token` 回傳的當下存在一次；DB 只保存 `token_hash`。
`resolve_token` 是 MCP verifier 的身分來源，只回傳 active user，不洩漏存在與否。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.control_models import McpToken, User
from app.errors import NotFoundError
from app.services.auth import utcnow

TOKEN_BYTES = 32
# F158：90 天。跟 refresh token 的絕對上限同一個數量級——比它短沒有道理
# （MCP token 的暴露面更小，不會隨每次請求上路），比它長則失去自我過期的意義。
DEFAULT_EXPIRY_DAYS = 90


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def create_token(
    control_session: Session,
    user_id: str,
    name: str,
    *,
    expires_in_days: int | None = DEFAULT_EXPIRY_DAYS,
    read_only: bool = False,
) -> tuple[McpToken, str]:
    """建立一顆新 token；回傳 (row, plaintext)——plaintext 只有這裡拿得到。

    `expires_in_days=None` 才是永不過期，而預設**有**期限：明文要貼進第三方設定檔，
    永久有效的預設等於把「永遠不會被撤的鑰匙」設成常態。
    """
    now = utcnow()
    plaintext = secrets.token_urlsafe(TOKEN_BYTES)
    token = McpToken(
        user_id=user_id,
        name=name,
        token_hash=_hash(plaintext),
        created_at=now,
        expires_at=now + timedelta(days=expires_in_days) if expires_in_days else None,
        read_only=read_only,
    )
    control_session.add(token)
    control_session.commit()
    control_session.refresh(token)
    return token, plaintext


def list_tokens(control_session: Session, user_id: str) -> list[McpToken]:
    """該 user 的所有 token（含已撤銷）；呼叫端負責不把 hash 序列化出去。"""
    return list(
        control_session.scalars(
            select(McpToken).where(McpToken.user_id == user_id).order_by(McpToken.created_at)
        )
    )


def revoke_token(control_session: Session, user_id: str, token_id: str) -> None:
    """撤銷一顆 token；別人的 token id 一律當不存在（404，不洩漏是否存在）。已撤銷再撤銷為冪等。"""
    token = control_session.get(McpToken, token_id)
    if token is None or token.user_id != user_id:
        raise NotFoundError()
    if token.revoked_at is None:
        token.revoked_at = utcnow()
        control_session.commit()


def resolve_token(control_session: Session, plaintext: str) -> User | None:
    """MCP verifier 用：明文 → 有效 user，或 None（查無／已撤銷／已到期／user 非 active）。"""
    now = utcnow()
    token = control_session.scalar(
        select(McpToken).where(McpToken.token_hash == _hash(plaintext))
    )
    # 到期與撤銷走同一條 return，呼叫端分不出是哪一種——連「這顆存在過」都不洩漏。
    if token is None or token.revoked_at is not None:
        return None
    if token.expires_at is not None and token.expires_at <= now:
        return None
    user = control_session.get(User, token.user_id)
    if user is None or user.status != "active":
        return None
    token.last_used_at = now
    control_session.commit()
    return user
