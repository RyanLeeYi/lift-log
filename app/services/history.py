"""F35：動作歷來查詢——某動作在 [from, to] 內每次訓練的全部組，加全期 PR。

與 stats.get_progress（只回每次最重組、供 MCP 文字查詢）分開：這裡回完整組資料，
給詳情頁前端算兩個指標（最重重量／最重總訓練量）、畫曲線與歷來清單。
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Exercise, Workout, WorkoutSet
from app.schemas import ExerciseHistoryOut, HistorySession, PrEntry, PrSummary, SetOut


def _all_time_prs(session: Session, exercise_id: int) -> PrSummary:
    """全期（不限日期）單組最大 weight_kg、與單組最大 weight_kg×reps。無資料為 None。"""
    rows = session.execute(
        select(WorkoutSet.weight_kg, WorkoutSet.reps).where(
            WorkoutSet.exercise_id == exercise_id,
            WorkoutSet.deleted_at.is_(None),
        )
    ).all()
    if not rows:
        return PrSummary(top_weight=None, top_set_volume=None)
    top_weight = max(rows, key=lambda r: r.weight_kg)
    top_volume = max(rows, key=lambda r: r.weight_kg * r.reps)
    return PrSummary(
        top_weight=PrEntry(weight_kg=top_weight.weight_kg, reps=top_weight.reps),
        top_set_volume=PrEntry(weight_kg=top_volume.weight_kg, reps=top_volume.reps),
    )


def exercise_history(
    session: Session, exercise_id: int, from_date: date, to_date: date
) -> ExerciseHistoryOut:
    """動作 id 不存在 → 404。sessions 依日期升冪，只含未軟刪、日期落在 [from, to] 的組。"""
    if session.get(Exercise, exercise_id) is None:
        raise NotFoundError()

    rows = session.scalars(
        select(WorkoutSet)
        .join(Workout, Workout.id == WorkoutSet.workout_id)
        .where(
            WorkoutSet.exercise_id == exercise_id,
            WorkoutSet.deleted_at.is_(None),
            Workout.date >= from_date,
            Workout.date <= to_date,
        )
        .order_by(Workout.date, Workout.id, WorkoutSet.set_number)
    ).all()

    sessions: list[HistorySession] = []
    by_workout: dict[int, HistorySession] = {}
    for s in rows:
        entry = by_workout.get(s.workout_id)
        if entry is None:
            entry = HistorySession(workout_id=s.workout_id, date=s.workout.date, sets=[])
            by_workout[s.workout_id] = entry
            sessions.append(entry)
        entry.sets.append(SetOut.model_validate(s))

    return ExerciseHistoryOut(prs=_all_time_prs(session, exercise_id), sessions=sessions)
