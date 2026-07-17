"""統計服務：日曆噸位（F3）、進步曲線（F6）。體重整合（F8）之後加在這裡。"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Exercise, Workout, WorkoutSet
from app.schemas import ExerciseName, ProgressOut, ProgressPoint
from app.services.exercises import find_by_name


def get_progress(session: Session, exercise: str) -> ProgressOut:
    """每次訓練（workout）該動作的最大重量與該重量的次數，依日期排序（PRD R7 範例 3）。"""
    found = find_by_name(session, exercise)
    if found is None:
        raise NotFoundError()

    rows = session.execute(
        select(Workout.id, Workout.date, WorkoutSet.weight_kg, WorkoutSet.reps)
        .join(WorkoutSet, WorkoutSet.workout_id == Workout.id)
        .where(WorkoutSet.exercise_id == found.id, WorkoutSet.deleted_at.is_(None))
        .order_by(Workout.date, Workout.id)
    ).all()

    top: dict[int, ProgressPoint] = {}
    for workout_id, workout_date, weight_kg, reps in rows:
        current = top.get(workout_id)
        heavier = current is None or weight_kg > current.top_weight_kg
        same_weight_more_reps = (
            current is not None and weight_kg == current.top_weight_kg and reps > current.reps
        )
        if heavier or same_weight_more_reps:
            top[workout_id] = ProgressPoint(date=workout_date, top_weight_kg=weight_kg, reps=reps)
    return ProgressOut(
        exercise=ExerciseName(name_zh=found.name_zh, name_en=found.name_en),
        points=list(top.values()),
    )


def set_tonnage(
    weight_kg: float, reps: int, is_bodyweight: bool, bodyweight_kg: float | None
) -> float:
    """單組噸位。自體重動作以（最新體重＋額外負重）計；無體重紀錄只計額外負重。"""
    effective = weight_kg
    if is_bodyweight and bodyweight_kg:
        effective += bodyweight_kg
    return effective * reps


def calendar_tonnage(
    session: Session, year: int, month: int, bodyweight_kg: float | None = None
) -> dict[str, float]:
    """回傳該月每個訓練日的總噸位 {"YYYY-MM-DD": tonnage}；沒練的日子不出現。

    bodyweight_kg 由呼叫端提供（F8 起接 body_metrics 最新體重；目前為 None）。
    """
    month_start = date(year, month, 1)
    month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    rows = session.execute(
        select(Workout.date, WorkoutSet.weight_kg, WorkoutSet.reps, Exercise.is_bodyweight)
        .join(WorkoutSet, WorkoutSet.workout_id == Workout.id)
        .join(Exercise, Exercise.id == WorkoutSet.exercise_id)
        .where(
            Workout.date >= month_start,
            Workout.date < month_end,
            WorkoutSet.deleted_at.is_(None),
        )
    ).all()

    days: dict[str, float] = {}
    for workout_date, weight_kg, reps, is_bodyweight in rows:
        key = workout_date.isoformat()
        days[key] = days.get(key, 0.0) + set_tonnage(weight_kg, reps, is_bodyweight, bodyweight_kg)
    return days
