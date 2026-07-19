"""當日狀態 service：同日覆蓋 upsert、區間查詢（PRD R9）。結構鏡射 body_metrics。"""

from datetime import date as date_type

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import DailyStatus
from app.schemas import DailyStatusIn


def upsert_daily_status(session: Session, data: DailyStatusIn) -> tuple[DailyStatus, bool]:
    """一天一筆：同日重送為覆蓋更新。回傳 (row, created)——REST 以此分 201/200。"""
    day = data.date or date_type.today()
    row = session.scalar(select(DailyStatus).where(DailyStatus.date == day))
    created = row is None
    if created:
        row = DailyStatus(
            date=day, energy=data.energy, sleep_quality=data.sleep_quality, note=data.note
        )
        session.add(row)
    else:
        row.energy = data.energy
        row.sleep_quality = data.sleep_quality
        row.note = data.note
    try:
        session.commit()
    except IntegrityError:
        # 併發同日首寫撞 date UNIQUE：輸掉競賽就復原為「同日覆蓋」，不漏 500
        session.rollback()
        row = session.scalar(select(DailyStatus).where(DailyStatus.date == day))
        if row is None:
            raise
        row.energy = data.energy
        row.sleep_quality = data.sleep_quality
        row.note = data.note
        session.commit()
        created = False
    session.refresh(row)
    return row, created


def list_daily_status(
    session: Session, start: date_type | None = None, end: date_type | None = None
) -> list[DailyStatus]:
    query = select(DailyStatus).order_by(DailyStatus.date)
    if start is not None:
        query = query.where(DailyStatus.date >= start)
    if end is not None:
        query = query.where(DailyStatus.date <= end)
    return list(session.scalars(query))


def delete_daily_status(session: Session, day: date_type) -> None:
    """F18：硬刪某日狀態（一天一筆、date UNIQUE、POST 本就覆蓋，硬刪最乾淨；不存在回 404）。"""
    row = session.scalar(select(DailyStatus).where(DailyStatus.date == day))
    if row is None:
        raise NotFoundError()
    session.delete(row)
    session.commit()
