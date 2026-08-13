"""體重體脂 service：同日覆蓋 upsert、區間查詢、最新體重（噸位計算用）、資料起訖（F58）。"""

from datetime import date as date_type

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import BodyMetric
from app.services import projection
from app.schemas import BodyMetricIn


def upsert_body_metric(session: Session, data: BodyMetricIn) -> tuple[BodyMetric, bool]:
    """一天一筆：同日重送為覆蓋更新（PRD R6）。回傳 (row, created)——REST 以此分 201/200。"""
    day = data.date or date_type.today()
    # 一天一筆是 date UNIQUE 撐著的，軟刪的列照樣占位子——刪掉再記同一天要復活那一列，
    # 不能硬插第二列（會撞 UNIQUE），對使用者而言那就是「重新記了一筆」。
    row = _row(session, day)
    created = row is None or row.deleted_at is not None
    if row is None:
        row = BodyMetric(date=day, weight_kg=data.weight_kg, body_fat_pct=data.body_fat_pct)
        session.add(row)
    else:
        row.deleted_at = None
        row.weight_kg = data.weight_kg
        row.body_fat_pct = data.body_fat_pct
    try:
        # record_write 內含 flush：輸掉併發競賽時 IntegrityError 會在這裡就拋，不是等到 commit
        projection.record_write(session, "body_metric", row)
        session.commit()
    except IntegrityError:
        # 併發同日首寫（雙擊等）撞 date UNIQUE：輸掉競賽就復原為「同日覆蓋」，不漏 500
        session.rollback()
        row = _row(session, day)
        if row is None:
            raise
        row.deleted_at = None
        row.weight_kg = data.weight_kg
        row.body_fat_pct = data.body_fat_pct
        projection.record_write(session, "body_metric", row)
        session.commit()
        created = False
    session.refresh(row)
    return row, created


def _row(session: Session, day: date_type) -> BodyMetric | None:
    """含已軟刪的列——UNIQUE(date) 不是 partial index，tombstone 仍占著那個日期。"""
    return session.scalar(select(BodyMetric).where(BodyMetric.date == day))


def _active(session: Session, day: date_type) -> BodyMetric | None:
    return session.scalar(
        select(BodyMetric).where(BodyMetric.date == day, BodyMetric.deleted_at.is_(None))
    )


def list_body_metrics(
    session: Session, start: date_type | None = None, end: date_type | None = None
) -> list[BodyMetric]:
    query = select(BodyMetric).where(BodyMetric.deleted_at.is_(None)).order_by(BodyMetric.date)
    if start is not None:
        query = query.where(BodyMetric.date >= start)
    if end is not None:
        query = query.where(BodyMetric.date <= end)
    return list(session.scalars(query))


def delete_body_metric(session: Session, day: date_type) -> None:
    """F17：刪除某日體重（不存在回 404）。

    F154 起改軟刪：硬刪的話另一台裝置永遠不知道這筆消失過，下次同步又會把它推回來
    （PRD R4 的 tombstone）。查詢一律濾掉 `deleted_at`，對使用者行為不變。
    """
    row = _active(session, day)
    if row is None:
        raise NotFoundError()
    projection.record_write(session, "body_metric", row, deleted=True)
    session.commit()


def latest_weight(session: Session) -> float | None:
    return session.scalar(
        select(BodyMetric.weight_kg).order_by(BodyMetric.date.desc()).limit(1)
    )


def metric_bounds(session: Session) -> dict[str, date_type | None]:
    """F58：資料起訖——只回 min/max 日期，不回資料列（給前端判斷哪些區間檔位有意義）。

    體脂與體重分開算：體脂通常比體重稀疏，兩者的最早紀錄日不同。
    """
    weight_first, last = session.execute(
        select(func.min(BodyMetric.date), func.max(BodyMetric.date))
    ).one()
    fat_first = session.scalar(
        select(func.min(BodyMetric.date)).where(BodyMetric.body_fat_pct.is_not(None))
    )
    return {"weight_first": weight_first, "fat_first": fat_first, "last": last}
