"""User-scoped MCP token 管理（F147／PRD R6）。

明文只在 `create_token` 回傳的當下存在一次；DB 只保存 `token_hash`。
`resolve_token` 是 MCP verifier 的身分來源，只回傳 active user，不洩漏存在與否。
"""

from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.control_models import McpToken, User
from app.errors import NotFoundError
from app.services.auth import utcnow

TOKEN_BYTES = 32


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def create_token(control_session: Session, user_id: str, name: str) -> tuple[McpToken, str]:
    """建立一顆新 token；回傳 (row, plaintext)——plaintext 只有這裡拿得到。"""
    plaintext = secrets.token_urlsafe(TOKEN_BYTES)
    token = McpToken(
        user_id=user_id,
        name=name,
        token_hash=_hash(plaintext),
        created_at=utcnow(),
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
    """MCP verifier 用：明文 → 有效 user，或 None（查無／已撤銷／user 非 active）。"""
    token = control_session.scalar(
        select(McpToken).where(McpToken.token_hash == _hash(plaintext))
    )
    if token is None or token.revoked_at is not None:
        return None
    user = control_session.get(User, token.user_id)
    if user is None or user.status != "active":
        return None
    token.last_used_at = utcnow()
    control_session.commit()
    return user
