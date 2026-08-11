from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_domain_auth
from app.schemas import ProgressOut
from app.services import stats as svc
from app.services.body_metrics import latest_weight

router = APIRouter(prefix="/api", dependencies=[Depends(require_domain_auth)])


@router.get("/stats/progress")
def progress(session: DbSession, exercise: str = Query(min_length=1)) -> ProgressOut:
    return svc.get_progress(session, exercise)


@router.get("/stats/calendar")
def calendar(
    session: DbSession,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
) -> dict:
    # F8：自體重噸位以最新體重計（與 MCP log_workout 同一規則，PRD R6）
    return {
        "year": year,
        "month": month,
        "days": svc.calendar_tonnage(session, year, month, latest_weight(session)),
    }
