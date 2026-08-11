"""F31 Web Push endpoints：公鑰、訂閱、休息通知排程/取消。"""

import asyncio

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import DbSession, require_domain_auth
from app.schemas import PushSubscriptionIn, RestTimerIn
from app.services import push as svc

router = APIRouter(prefix="/api/push", dependencies=[Depends(require_domain_auth)])


@router.get("/public-key")
def public_key(request: Request) -> dict:
    """前端 subscribe 要的 applicationServerKey；enabled 讓前端知道推播有沒有設定好。"""
    settings = request.app.state.settings
    return {
        "key": settings.vapid_public_key,
        "enabled": bool(settings.vapid_private_key and settings.vapid_public_key),
    }


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
def subscribe(data: PushSubscriptionIn, session: DbSession) -> None:
    svc.upsert_subscription(session, data)


@router.post("/rest-timer", status_code=status.HTTP_202_ACCEPTED)
async def rest_timer(data: RestTimerIn, request: Request) -> dict:
    """休息開始時呼叫：排定 seconds 後推「休息結束」；覆蓋前一個未觸發的排程。"""
    factory = request.state.domain_session_factory
    scope = request.state.domain_scope
    settings = request.app.state.settings

    async def fire() -> None:
        # pywebpush 為阻塞 IO，丟執行緒不擋事件迴圈
        await asyncio.to_thread(
            svc.send_to_all, factory, settings, "休息結束", "時間到，繼續下一組！"
        )

    svc.schedule_rest(data.seconds, fire, key=scope)
    return {"scheduled": data.seconds}


@router.post("/rest-timer/cancel", status_code=status.HTTP_204_NO_CONTENT)
def rest_timer_cancel(request: Request) -> None:
    """提早繼續下一組/換動作/收工：取消未觸發的休息通知。"""
    svc.cancel_rest(key=request.state.domain_scope)
