"""體重體脂 service：同日覆蓋 upsert、區間查詢、最新體重（噸位計算用）。"""

from datetime import date as date_type

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BodyMetric
from app.schemas import BodyMetricIn


def upsert_body_metric(session: Session, data: BodyMetricIn) -> tuple[BodyMetric, bool]:
    """一天一筆：同日重送為覆蓋更新（PRD R6）。回傳 (row, created)——REST 以此分 201/200。"""
    day = data.date or date_type.today()
    row = session.scalar(select(BodyMetric).where(BodyMetric.date == day))
    created = row is None
    if created:
        row = BodyMetric(date=day, weight_kg=data.weight_kg, body_fat_pct=data.body_fat_pct)
        session.add(row)
    else:
        row.weight_kg = data.weight_kg
        row.body_fat_pct = data.body_fat_pct
    try:
        session.commit()
    except IntegrityError:
        # 併發同日首寫（雙擊等）撞 date UNIQUE：輸掉競賽就復原為「同日覆蓋」，不漏 500
        session.rollback()
        row = session.scalar(select(BodyMetric).where(BodyMetric.date == day))
        if row is None:
            raise
        row.weight_kg = data.weight_kg
        row.body_fat_pct = data.body_fat_pct
        session.commit()
        created = False
    session.refresh(row)
    return row, created


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
