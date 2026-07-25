from datetime import date as date_type

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import DbSession, require_token
from app.schemas import BodyMetricBounds, BodyMetricIn, BodyMetricOut
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


# ⚠ 必須宣告在任何 `/body-metrics/{...}` 路由之前——否則 "range" 會被當成 path param 吃掉
# （目前只有 DELETE 用 path param，所以還沒衝突；這行是給日後加 GET /{day} 的人看的）
@router.get("/body-metrics/range")
def body_metric_bounds(session: DbSession) -> BodyMetricBounds:
    """F58：資料起訖（不回資料列）——前端用它判斷哪些區間檔位有意義。"""
    return BodyMetricBounds.model_validate(svc.metric_bounds(session))


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
