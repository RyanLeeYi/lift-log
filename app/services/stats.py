"""統計服務：日曆噸位（F3）。進步曲線（F6）、體重整合（F8）之後加在這裡。"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Exercise, Workout, WorkoutSet


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
