"""當日狀態 service：同日覆蓋 upsert、區間查詢（PRD R9）。結構鏡射 body_metrics。"""

from datetime import date as date_type

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import DailyStatus
from app.schemas import DailyStatusIn
from app.services import projection


def upsert_daily_status(session: Session, data: DailyStatusIn) -> tuple[DailyStatus, bool]:
    """一天一筆：同日重送為覆蓋更新。回傳 (row, created)——REST 以此分 201/200。"""
    day = data.date or date_type.today()
    # 軟刪的列照樣占著 date UNIQUE——刪掉再記同一天是復活那一列（理由同 body_metrics）
    row = _row(session, day)
    created = row is None or row.deleted_at is not None
    if row is None:
        row = DailyStatus(
            date=day, energy=data.energy, sleep_quality=data.sleep_quality, note=data.note
        )
        session.add(row)
    else:
        row.deleted_at = None
        row.energy = data.energy
        row.sleep_quality = data.sleep_quality
        row.note = data.note
    try:
        # record_write 內含 flush：輸掉競賽時 IntegrityError 會在這裡就拋，不是等到 commit
        projection.record_write(session, "daily_status", row)
        session.commit()
    except IntegrityError:
        # 併發同日首寫撞 date UNIQUE：輸掉競賽就復原為「同日覆蓋」，不漏 500
        session.rollback()
        row = _row(session, day)
        if row is None:
            raise
        row.deleted_at = None
        row.energy = data.energy
        row.sleep_quality = data.sleep_quality
        row.note = data.note
        projection.record_write(session, "daily_status", row)
        session.commit()
        created = False
    session.refresh(row)
    return row, created


def _row(session: Session, day: date_type) -> DailyStatus | None:
    """含已軟刪的列——UNIQUE(date) 不是 partial index，tombstone 仍占著那個日期。"""
    return session.scalar(select(DailyStatus).where(DailyStatus.date == day))


def list_daily_status(
    session: Session, start: date_type | None = None, end: date_type | None = None
) -> list[DailyStatus]:
    query = select(DailyStatus).where(DailyStatus.deleted_at.is_(None)).order_by(DailyStatus.date)
    if start is not None:
        query = query.where(DailyStatus.date >= start)
    if end is not None:
        query = query.where(DailyStatus.date <= end)
    return list(session.scalars(query))


def delete_daily_status(session: Session, day: date_type) -> None:
    """F18：刪除某日狀態（不存在回 404）。F154 起改軟刪，理由同 body_metrics 的 tombstone。"""
    row = session.scalar(
        select(DailyStatus).where(DailyStatus.date == day, DailyStatus.deleted_at.is_(None))
    )
    if row is None:
        raise NotFoundError()
    projection.record_write(session, "daily_status", row, deleted=True)
    session.commit()
