from datetime import date as date_type
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, DomainError, NotFoundError
from app.models import Exercise, Workout, WorkoutSet
from app.schemas import SetCreate, WorkoutCreate


def create_workout(session: Session, data: WorkoutCreate) -> Workout:
    workout = Workout(
        date=data.date or date_type.today(),
        template_id=data.template_id,
        note=data.note,
    )
    session.add(workout)
    session.commit()
    session.refresh(workout)
    return workout


def get_workout(session: Session, workout_id: int) -> Workout:
    workout = session.get(Workout, workout_id)
    if workout is None:
        raise NotFoundError()
    return workout


def get_active_sets(session: Session, workout_id: int) -> list[WorkoutSet]:
    """該 workout 未刪除的組，SQL 端過濾與排序（軟刪除不變量的唯一入口）。"""
    return list(
        session.scalars(
            select(WorkoutSet)
            .where(WorkoutSet.workout_id == workout_id, WorkoutSet.deleted_at.is_(None))
            .order_by(WorkoutSet.exercise_id, WorkoutSet.set_number, WorkoutSet.id)
        )
    )


def list_workouts(
    session: Session, start: date_type | None, end: date_type | None
) -> list[Workout]:
    query = select(Workout).order_by(Workout.date, Workout.id)
    if start is not None:
        query = query.where(Workout.date >= start)
    if end is not None:
        query = query.where(Workout.date <= end)
    return list(session.scalars(query))


def _find_by_client_uuid(session: Session, client_uuid: str) -> WorkoutSet | None:
    return session.scalar(select(WorkoutSet).where(WorkoutSet.client_uuid == client_uuid))


def _as_idempotent_hit(existing: WorkoutSet, workout_id: int) -> WorkoutSet:
    """重放必須命中「同一 workout 的未刪除組」，否則是衝突不是冪等。"""
    if existing.workout_id != workout_id or existing.deleted_at is not None:
        raise ConflictError("client_uuid already used")
    return existing


def log_set(session: Session, workout_id: int, data: SetCreate) -> tuple[WorkoutSet, bool]:
    """寫入一組。回傳 (set, created)；同 client_uuid 重放冪等回傳既有那筆。

    順序：先驗證 workout（404）與 exercise（400），再查冪等鍵；
    insert 撞 UNIQUE（TOCTOU 輸掉競賽）時 rollback 重查復原為冪等回應。
    """
    get_workout(session, workout_id)
    if session.get(Exercise, data.exercise_id) is None:
        raise DomainError("exercise not found")

    existing = _find_by_client_uuid(session, data.client_uuid)
    if existing is not None:
        return _as_idempotent_hit(existing, workout_id), False

    workout_set = WorkoutSet(workout_id=workout_id, **data.model_dump())
    session.add(workout_set)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raced = _find_by_client_uuid(session, data.client_uuid)
        if raced is None:
            raise
        return _as_idempotent_hit(raced, workout_id), False
    session.refresh(workout_set)
    return workout_set, True


def soft_delete_set(session: Session, set_id: int) -> None:
    workout_set = session.get(WorkoutSet, set_id)
    if workout_set is None or workout_set.deleted_at is not None:
        raise NotFoundError()
    workout_set.deleted_at = datetime.now()
    session.commit()
