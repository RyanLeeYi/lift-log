"""統計服務：日曆噸位（F3）、進步曲線（F6）。體重整合（F8）之後加在這裡。"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import EXERCISE_MODE_TIME, Exercise, Workout, WorkoutSet
from app.schemas import CalendarDay, ExerciseName, ProgressOut, ProgressPoint
from app.services.exercises import find_by_name


def get_progress(session: Session, exercise: str) -> ProgressOut:
    """每次訓練（workout）該動作的代表組，依日期排序（PRD R7 範例 3）。

    次數型＝最重那組（同重量取次數多者）。
    F105 ⑦ 時間型＝**最長那組**（秒數），這樣 MCP 才答得出「棒式我做過幾秒」；
    拿時間型去比 weight_kg 只會得到一條全 0 的線。
    """
    found = find_by_name(session, exercise)
    if found is None:
        raise NotFoundError()

    rows = session.execute(
        select(
            Workout.id,
            Workout.date,
            WorkoutSet.weight_kg,
            WorkoutSet.reps,
            WorkoutSet.duration_seconds,
        )
        .join(WorkoutSet, WorkoutSet.workout_id == Workout.id)
        .where(WorkoutSet.exercise_id == found.id, WorkoutSet.deleted_at.is_(None))
        .order_by(Workout.date, Workout.id)
    ).all()

    is_time = found.mode == EXERCISE_MODE_TIME
    top: dict[int, ProgressPoint] = {}
    for workout_id, workout_date, weight_kg, reps, duration_seconds in rows:
        current = top.get(workout_id)
        if is_time:
            if duration_seconds is None:
                continue
            if current is not None and duration_seconds <= (current.duration_seconds or 0):
                continue
            top[workout_id] = ProgressPoint(
                date=workout_date,
                top_weight_kg=weight_kg,
                duration_seconds=duration_seconds,
            )
            continue
        if reps is None:
            continue
        heavier = current is None or weight_kg > current.top_weight_kg
        same_weight_more_reps = (
            current is not None
            and weight_kg == current.top_weight_kg
            and reps > (current.reps or 0)
        )
        if heavier or same_weight_more_reps:
            top[workout_id] = ProgressPoint(date=workout_date, top_weight_kg=weight_kg, reps=reps)
    return ProgressOut(
        exercise=ExerciseName(name_zh=found.name_zh, name_en=found.name_en),
        points=list(top.values()),
    )


def set_tonnage(
    weight_kg: float, reps: int | None, is_bodyweight: bool, bodyweight_kg: float | None
) -> float:
    """單組噸位。自體重動作以（最新體重＋額外負重）計；無體重紀錄只計額外負重。

    F105 ③：時間型的組（reps 為 None）一律回 0——噸位的意義是「舉起了多少重量」，
    把秒數折算進去會讓**未來每一個**噸位數字都不可信。份量改由總秒數並列表達。
    """
    if reps is None:
        return 0.0
    effective = weight_kg
    if is_bodyweight and bodyweight_kg:
        effective += bodyweight_kg
    return effective * reps


def calendar_days(
    session: Session, year: int, month: int, bodyweight_kg: float | None = None
) -> dict[str, CalendarDay]:
    """回傳該月每個訓練日的三個數字；沒練的日子不出現。

    F105 ④：熱力圖分級改吃 **sets_count**。原本吃噸位，而時間型不進噸位——
    一場只做棒式的訓練噸位是 0，那天會被畫成「沒練」。組數是兩種模式共同都有的量。
    tonnage_kg 與 duration_seconds 仍然各自回傳（③ 並列不相加），給明細與摘要用。

    bodyweight_kg 由呼叫端提供（F8 起接 body_metrics 最新體重）。
    """
    month_start = date(year, month, 1)
    month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    rows = session.execute(
        select(
            Workout.date,
            WorkoutSet.weight_kg,
            WorkoutSet.reps,
            WorkoutSet.duration_seconds,
            Exercise.is_bodyweight,
        )
        .join(WorkoutSet, WorkoutSet.workout_id == Workout.id)
        .join(Exercise, Exercise.id == WorkoutSet.exercise_id)
        .where(
            Workout.date >= month_start,
            Workout.date < month_end,
            WorkoutSet.deleted_at.is_(None),
        )
    ).all()

    days: dict[str, CalendarDay] = {}
    for workout_date, weight_kg, reps, duration_seconds, is_bodyweight in rows:
        key = workout_date.isoformat()
        day = days.get(key)
        if day is None:
            day = CalendarDay(tonnage_kg=0.0, duration_seconds=0, sets_count=0)
            days[key] = day
        day.tonnage_kg += set_tonnage(weight_kg, reps, is_bodyweight, bodyweight_kg)
        day.duration_seconds += duration_seconds or 0
        day.sets_count += 1
    return days
