"""F80：今天排到什麼、本週練了幾天（首頁用）。"""

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_token
from app.schemas import ScheduleTodayOut
from app.services import schedule as svc

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@router.get("/schedule/today", response_model=ScheduleTodayOut)
def schedule_today(session: DbSession) -> ScheduleTodayOut:
    return svc.today(session)
