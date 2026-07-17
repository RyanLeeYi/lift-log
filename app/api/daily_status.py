from datetime import date as date_type

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import DbSession, require_token
from app.schemas import DailyStatusIn, DailyStatusOut
from app.services import daily_status as svc

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@router.get("/daily-status")
def list_daily_status(
    session: DbSession,
    start: date_type | None = None,
    end: date_type | None = None,
) -> list[DailyStatusOut]:
    rows = svc.list_daily_status(session, start, end)
    return [DailyStatusOut.model_validate(row) for row in rows]


@router.post("/daily-status")
def upsert_daily_status(
    session: DbSession, data: DailyStatusIn, response: Response
) -> DailyStatusOut:
    """同日覆蓋（PRD R9）：新建 201、覆蓋更新 200；休息日可記，不依附 workout。"""
    row, created = svc.upsert_daily_status(session, data)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return DailyStatusOut.model_validate(row)
