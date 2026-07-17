import uuid
from datetime import date as date_type
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, DomainError, NotFoundError, UnknownExerciseError
from app.models import Exercise, Template, Workout, WorkoutSet
from app.schemas import LogWorkoutIn, LogWorkoutSummary, SetCreate, WorkoutCreate
from app.services.body_metrics import latest_weight
from app.services.stats import set_tonnage

_SUGGEST_CUTOFF = 0.4
_SUGGEST_LIMIT = 3


def _exercise_index(exercises: list[Exercise]) -> dict[str, Exercise]:
    """雙語名稱（去空白、不分大小寫）→ Exercise。"""
    index: dict[str, Exercise] = {}
    for exercise in exercises:
        index[exercise.name_zh.strip().lower()] = exercise
        index[exercise.name_en.strip().lower()] = exercise
    return index


def _suggest(exercises: list[Exercise], unknown: str) -> list[str]:
    """對未命中名稱給相近動作建議，格式「深蹲 Squat」。"""
    target = unknown.strip().lower()
    scored: list[tuple[float, str]] = []
    for exercise in exercises:
        zh = exercise.name_zh.lower()
        en = exercise.name_en.lower()
        score = max(
            SequenceMatcher(None, target, zh).ratio(),
            SequenceMatcher(None, target, en).ratio(),
        )
        if target in zh or target in en or zh in target or en in target:
            score = max(score, 0.9)
        if score >= _SUGGEST_CUTOFF:
            scored.append((score, f"{exercise.name_zh} {exercise.name_en}"))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [label for _, label in scored[:_SUGGEST_LIMIT]]


def _resolve_template_id(session: Session, name: str) -> int:
    template_id = session.scalar(select(Template.id).where(Template.name == name))
    if template_id is None:
        raise DomainError("template not found")
    return template_id


def log_workout(session: Session, data: LogWorkoutIn) -> LogWorkoutSummary:
    """MCP 代記錄的單一交易入口（PRD R7b）。

    整包寫入或整包拒絕（單一 commit，不留半套）；動作名雙語比對，
    未命中且未帶 create_missing 時回未知清單＋相近建議。
    """
    template_id = _resolve_template_id(session, data.template) if data.template else None

    exercises = list(session.scalars(select(Exercise)))
    index = _exercise_index(exercises)
    wanted = list(dict.fromkeys(item.exercise.strip() for item in data.sets))
    unknown = [name for name in wanted if name.lower() not in index]

    if unknown and not data.create_missing:
        suggestions: list[str] = []
        for name in unknown:
            suggestions.extend(_suggest(exercises, name))
        raise UnknownExerciseError(unknown, list(dict.fromkeys(suggestions)))

    for name in unknown:
        created = Exercise(name_zh=name, name_en=name, muscle_group="未分類")
        session.add(created)
        index[name.lower()] = created
    session.flush()

    workout = Workout(
        date=data.date or date_type.today(), template_id=template_id, note=data.note
    )
    session.add(workout)
    session.flush()

    bodyweight_kg = latest_weight(session)
    set_counts: dict[int, int] = {}
    tonnage = 0.0
    for item in data.sets:
        exercise = index[item.exercise.strip().lower()]
        set_counts[exercise.id] = set_counts.get(exercise.id, 0) + 1
        session.add(
            WorkoutSet(
                client_uuid=str(uuid.uuid4()),
                workout_id=workout.id,
                exercise_id=exercise.id,
                set_number=set_counts[exercise.id],
                weight_kg=item.weight_kg,
                reps=item.reps,
                rpe=item.rpe,
            )
        )
        tonnage += set_tonnage(item.weight_kg, item.reps, exercise.is_bodyweight, bodyweight_kg)
    session.commit()
    return LogWorkoutSummary(
        workout_id=workout.id,
        date=workout.date,
        sets_count=len(data.sets),
        tonnage_kg=tonnage,
    )


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
