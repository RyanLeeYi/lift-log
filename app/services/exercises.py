from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DomainError, NotFoundError
from app.models import Exercise, Workout, WorkoutSet
from app.schemas import ExerciseCreate


def create_exercise(session: Session, data: ExerciseCreate) -> Exercise:
    exercise = Exercise(**data.model_dump())
    session.add(exercise)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DomainError("exercise name already exists") from exc
    session.refresh(exercise)
    return exercise


def _escape_like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_exercises(session: Session, q: str | None) -> list[Exercise]:
    query = select(Exercise).order_by(Exercise.id)
    if q:
        pattern = f"%{_escape_like(q)}%"
        query = query.where(
            or_(
                Exercise.name_zh.ilike(pattern, escape="\\"),
                Exercise.name_en.ilike(pattern, escape="\\"),
            )
        )
    return list(session.scalars(query))


def last_sets(session: Session, exercise_id: int) -> list[WorkoutSet]:
    """該動作最近一次 workout 的各組（帶入預設值用）；exercise 不存在 → 404。"""
    if session.get(Exercise, exercise_id) is None:
        raise NotFoundError()
    latest_workout_id = (
        select(WorkoutSet.workout_id)
        .join(Workout, Workout.id == WorkoutSet.workout_id)
        .where(WorkoutSet.exercise_id == exercise_id, WorkoutSet.deleted_at.is_(None))
        .order_by(Workout.date.desc(), Workout.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    return list(
        session.scalars(
            select(WorkoutSet)
            .where(
                WorkoutSet.workout_id == latest_workout_id,
                WorkoutSet.exercise_id == exercise_id,
                WorkoutSet.deleted_at.is_(None),
            )
            .order_by(WorkoutSet.set_number)
        )
    )
