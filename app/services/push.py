"""F31 Web Push：訂閱管理、送通知（pywebpush）、休息結束的 in-process 排程器。

排程器是模組級單一 task（單人 app）：新排程覆蓋舊的；伺服器重啟會漏掉當下未觸發的通知
（休息窗僅 60~180 秒，風險低）。送出走執行緒（pywebpush 為阻塞 IO）。
"""

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable

from cryptography.hazmat.primitives import serialization
from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.models import PushSubscription
from app.schemas import PushSubscriptionIn


def upsert_subscription(session: Session, data: PushSubscriptionIn) -> None:
    """一台裝置一筆（endpoint 唯一）；重新訂閱就更新金鑰。"""
    existing = session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == data.endpoint)
    )
    if existing is not None:
        existing.p256dh = data.keys.p256dh
        existing.auth = data.keys.auth
    else:
        session.add(
            PushSubscription(
                endpoint=data.endpoint, p256dh=data.keys.p256dh, auth=data.keys.auth
            )
        )
    session.commit()


def _private_key_pem(settings: Settings) -> str:
    """.env 存的是 PKCS8 DER 的 base64url；pywebpush 收 PEM 字串。"""
    raw = settings.vapid_private_key
    der = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    key = serialization.load_der_private_key(der, password=None)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _send_one(settings: Settings, sub: PushSubscription, payload: str) -> None:
    webpush(
        subscription_info={
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
        },
        data=payload,
        vapid_private_key=_private_key_pem(settings),
        vapid_claims={"sub": settings.vapid_subject},
        ttl=60,  # 休息通知過時無意義：60 秒送不到就丟
    )


def send_to_all(session_factory: sessionmaker, settings: Settings, title: str, body: str) -> int:
    """送給所有訂閱裝置；回傳成功筆數。失效訂閱（404/410）就地刪除。"""
    if not settings.vapid_private_key:
        return 0  # 未設金鑰＝推播停用，靜默略過
    payload = json.dumps({"title": title, "body": body})
    sent = 0
    with session_factory() as session:
        for sub in list(session.scalars(select(PushSubscription))):
            try:
                _send_one(settings, sub, payload)
                sent += 1
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                if status in (404, 410):
                    session.delete(sub)  # 訂閱已失效（換裝置/清資料）→ 清掉
        session.commit()
    return sent


# ---------- 休息結束排程器（in-process、單一 task） ----------

_rest_task: asyncio.Task | None = None


async def _run_after(seconds: float, callback: Callable[[], Awaitable[None]]) -> None:
    try:
        await asyncio.sleep(seconds)
        await callback()
    except asyncio.CancelledError:
        pass  # 被新排程或取消覆蓋：不觸發


def schedule_rest(seconds: float, callback: Callable[[], Awaitable[None]]) -> None:
    """排定 seconds 後執行 callback；覆蓋前一個尚未觸發的排程。"""
    cancel_rest()
    global _rest_task
    _rest_task = asyncio.create_task(_run_after(seconds, callback))


def cancel_rest() -> None:
    global _rest_task
    if _rest_task is not None and not _rest_task.done():
        _rest_task.cancel()
    _rest_task = None
