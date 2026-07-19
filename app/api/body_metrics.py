from datetime import date as date_type

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import DbSession, require_token
from app.schemas import BodyMetricIn, BodyMetricOut
from app.services import body_metrics as svc

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@router.get("/body-metrics")
def list_body_metrics(
    session: DbSession,
    start: date_type | None = None,
    end: date_type | None = None,
) -> list[BodyMetricOut]:
    rows = svc.list_body_metrics(session, start, end)
    return [BodyMetricOut.model_validate(row) for row in rows]


@router.post("/body-metrics")
def upsert_body_metric(
    session: DbSession, data: BodyMetricIn, response: Response
) -> BodyMetricOut:
    """同日覆蓋（PRD R6）：新建 201、覆蓋更新 200。"""
    row, created = svc.upsert_body_metric(session, data)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return BodyMetricOut.model_validate(row)


@router.delete("/body-metrics/{day}", status_code=status.HTTP_204_NO_CONTENT)
def delete_body_metric(day: date_type, session: DbSession) -> None:
    """F17：硬刪某日體重（不存在回 404）。"""
    svc.delete_body_metric(session, day)
