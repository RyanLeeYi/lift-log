"""services.workouts.log_workout：MCP 代記錄的單一交易入口（PRD R7b）。"""

from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import DomainError, UnknownExerciseError
from app.models import Exercise, Template, TemplateExercise, Workout, WorkoutSet
from app.schemas import LogSetIn, LogWorkoutIn
from app.services.workouts import log_workout


@pytest.fixture()
def squat(db_session: Session) -> Exercise:
    exercise = Exercise(name_zh="深蹲", name_en="Squat", muscle_group="腿")
    db_session.add(exercise)
    db_session.commit()
    return exercise


def _payload(**overrides: object) -> LogWorkoutIn:
    base: dict = {
        "sets": [
            LogSetIn(exercise="深蹲", weight_kg=80, reps=8),
            LogSetIn(exercise="深蹲", weight_kg=80, reps=8),
        ]
    }
    return LogWorkoutIn(**{**base, **overrides})


def test_log_workout_writes_all_sets_and_returns_summary(
    db_session: Session, squat: Exercise
) -> None:
    summary = log_workout(db_session, _payload())

    assert summary.sets_count == 2
    assert summary.tonnage_kg == 1280
    assert summary.date == date.today()

    workout = db_session.get(Workout, summary.workout_id)
    assert workout is not None
    sets = list(db_session.scalars(select(WorkoutSet).order_by(WorkoutSet.set_number)))
    assert [(s.exercise_id, s.set_number) for s in sets] == [(squat.id, 1), (squat.id, 2)]
    assert all(s.client_uuid for s in sets)
    assert len({s.client_uuid for s in sets}) == 2


def test_log_workout_matches_english_name_case_insensitive(
    db_session: Session, squat: Exercise
) -> None:
    payload = _payload(sets=[LogSetIn(exercise="  sQuAt ", weight_kg=100, reps=5)])
    summary = log_workout(db_session, payload)
    assert summary.sets_count == 1
    assert summary.tonnage_kg == 500


def test_log_workout_set_numbers_count_per_exercise(db_session: Session, squat: Exercise) -> None:
    bench = Exercise(name_zh="臥推", name_en="Bench Press", muscle_group="胸")
    db_session.add(bench)
    db_session.commit()
    payload = _payload(
        sets=[
            LogSetIn(exercise="深蹲", weight_kg=80, reps=8),
            LogSetIn(exercise="臥推", weight_kg=60, reps=10),
            LogSetIn(exercise="深蹲", weight_kg=85, reps=6),
        ]
    )
    log_workout(db_session, payload)
    rows = db_session.execute(
        select(WorkoutSet.exercise_id, WorkoutSet.set_number).order_by(WorkoutSet.id)
    ).all()
    assert rows == [(squat.id, 1), (bench.id, 1), (squat.id, 2)]


def test_log_workout_unknown_exercise_rejects_whole_batch(
    db_session: Session, squat: Exercise
) -> None:
    payload = _payload(
        sets=[
            LogSetIn(exercise="深蹲", weight_kg=80, reps=8),
            LogSetIn(exercise="深躦", weight_kg=80, reps=8),
        ]
    )
    with pytest.raises(UnknownExerciseError) as exc_info:
        log_workout(db_session, payload)

    assert exc_info.value.unknown == ["深躦"]
    assert "深蹲 Squat" in exc_info.value.suggestions
    # 整包拒絕：不留半套
    assert db_session.scalars(select(Workout)).first() is None
    assert db_session.scalars(select(WorkoutSet)).first() is None


def test_log_workout_create_missing_creates_exercise(
    db_session: Session, squat: Exercise
) -> None:
    payload = _payload(
        sets=[LogSetIn(exercise="農夫走路", weight_kg=40, reps=20)], create_missing=True
    )
    summary = log_workout(db_session, payload)
    assert summary.sets_count == 1
    created = db_session.scalar(select(Exercise).where(Exercise.name_zh == "農夫走路"))
    assert created is not None


def test_log_workout_explicit_date_and_note(db_session: Session, squat: Exercise) -> None:
    payload = _payload(date=date(2026, 7, 10), note="練腿日")
    summary = log_workout(db_session, payload)
    assert summary.date == date(2026, 7, 10)
    workout = db_session.get(Workout, summary.workout_id)
    assert workout is not None and workout.note == "練腿日"


def test_log_workout_template_by_name(db_session: Session, squat: Exercise) -> None:
    template = Template(
        name="練腿日",
        exercises=[TemplateExercise(position=1, exercise_id=squat.id, default_sets=3)],
    )
    db_session.add(template)
    db_session.commit()

    summary = log_workout(db_session, _payload(template="練腿日"))
    workout = db_session.get(Workout, summary.workout_id)
    assert workout is not None and workout.template_id == template.id


def test_log_workout_unknown_template_rejected(db_session: Session, squat: Exercise) -> None:
    with pytest.raises(DomainError):
        log_workout(db_session, _payload(template="不存在的課表"))
    assert db_session.scalars(select(Workout)).first() is None


def test_log_workout_schema_rejects_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        LogSetIn(exercise="深蹲", weight_kg=80, reps=0)
    with pytest.raises(ValidationError):
        LogSetIn(exercise="深蹲", weight_kg=-1, reps=8)
    with pytest.raises(ValidationError):
        LogSetIn(exercise="深蹲", weight_kg=80, reps=8, rpe=11)
    with pytest.raises(ValidationError):
        LogWorkoutIn(sets=[])


def test_log_workout_schema_rejects_blank_exercise_name() -> None:
    """空白動作名不得過驗——否則 create_missing 會建出空名動作。"""
    with pytest.raises(ValidationError):
        LogSetIn(exercise="   ", weight_kg=80, reps=8)


def test_log_workout_same_client_uuid_replays_idempotently(
    db_session: Session, squat: Exercise
) -> None:
    """MCP 呼叫 timeout 後 LLM 重試：同 client_uuid 不得重複寫入。"""
    payload = _payload(client_uuid="retry-4f9a1c22")
    first = log_workout(db_session, payload)
    second = log_workout(db_session, payload)

    assert second.workout_id == first.workout_id
    assert second.sets_count == first.sets_count == 2
    assert db_session.scalar(select(func.count()).select_from(WorkoutSet)) == 2
    assert db_session.scalar(select(func.count()).select_from(Workout)) == 1


def test_log_workout_create_missing_dedupes_case_variants(
    db_session: Session, squat: Exercise
) -> None:
    """同名不同大小寫只建一筆 Exercise，不留孤兒。"""
    payload = _payload(
        sets=[
            LogSetIn(exercise="Face Pull", weight_kg=20, reps=15),
            LogSetIn(exercise="face pull", weight_kg=20, reps=15),
        ],
        create_missing=True,
    )
    summary = log_workout(db_session, payload)
    assert summary.sets_count == 2

    created = list(
        db_session.scalars(select(Exercise).where(func.lower(Exercise.name_en) == "face pull"))
    )
    assert len(created) == 1
    sets = list(db_session.scalars(select(WorkoutSet)))
    assert {s.exercise_id for s in sets} == {created[0].id}


def test_log_workout_commit_conflict_maps_to_domain_error(
    db_session: Session, squat: Exercise, monkeypatch: pytest.MonkeyPatch
) -> None:
    """併發 create_missing 撞 UNIQUE：commit 的 IntegrityError 不得裸拋。"""

    def boom() -> None:
        raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))

    monkeypatch.setattr(db_session, "commit", boom)
    with pytest.raises(DomainError):
        log_workout(db_session, _payload())
    monkeypatch.undo()
    db_session.rollback()
    assert db_session.scalars(select(Workout)).first() is None


def test_log_workout_duplicate_template_name_is_ambiguous(
    db_session: Session, squat: Exercise
) -> None:
    """同名課表不得隨機掛一個——回明確錯誤。"""
    for _ in range(2):
        db_session.add(
            Template(
                name="撞名日",
                exercises=[TemplateExercise(position=1, exercise_id=squat.id, default_sets=3)],
            )
        )
    db_session.commit()

    with pytest.raises(DomainError):
        log_workout(db_session, _payload(template="撞名日"))
    assert db_session.scalars(select(Workout)).first() is None
