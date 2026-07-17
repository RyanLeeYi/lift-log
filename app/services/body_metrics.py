"""體重體脂 service：同日覆蓋 upsert、區間查詢、最新體重（噸位計算用）。"""

from datetime import date as date_type

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BodyMetric
from app.schemas import BodyMetricIn


def upsert_body_metric(session: Session, data: BodyMetricIn) -> BodyMetric:
    """一天一筆：同日重送為覆蓋更新（PRD R6）。"""
    day = data.date or date_type.today()
    row = session.scalar(select(BodyMetric).where(BodyMetric.date == day))
    if row is None:
        row = BodyMetric(date=day, weight_kg=data.weight_kg, body_fat_pct=data.body_fat_pct)
        session.add(row)
    else:
        row.weight_kg = data.weight_kg
        row.body_fat_pct = data.body_fat_pct
    session.commit()
    session.refresh(row)
    return row


def list_body_metrics(
    session: Session, start: date_type | None = None, end: date_type | None = None
) -> list[BodyMetric]:
    query = select(BodyMetric).order_by(BodyMetric.date)
    if start is not None:
        query = query.where(BodyMetric.date >= start)
    if end is not None:
        query = query.where(BodyMetric.date <= end)
    return list(session.scalars(query))


def latest_weight(session: Session) -> float | None:
    return session.scalar(
        select(BodyMetric.weight_kg).order_by(BodyMetric.date.desc()).limit(1)
    )
