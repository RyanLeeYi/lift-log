"""services.workouts.log_workout：MCP 代記錄的單一交易入口（PRD R7b）。"""

from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import select
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
