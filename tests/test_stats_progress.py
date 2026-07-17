"""get_progress：每次訓練該動作最大重量×次數的進步曲線（PRD R7 範例 3）。"""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Exercise, Workout, WorkoutSet
from app.services.stats import get_progress
from tests.conftest import make_set_payload


def _seed_progress_data(db_session: Session) -> Exercise:
    squat = Exercise(name_zh="深蹲", name_en="Squat", muscle_group="腿")
    db_session.add(squat)
    db_session.flush()
    w1 = Workout(date=date(2026, 7, 10))
    w2 = Workout(date=date(2026, 7, 16))
    db_session.add_all([w1, w2])
    db_session.flush()
    rows = [
        (w1, 1, 80.0, 8, None),
        (w1, 2, 80.0, 8, None),
        (w1, 3, 75.0, 10, None),
        (w2, 1, 85.0, 6, None),
        (w2, 2, 80.0, 8, None),
        (w2, 3, 90.0, 1, datetime(2026, 7, 16, 12, 0)),  # 已軟刪除，不得計入
    ]
    for workout, number, weight, reps, deleted_at in rows:
        db_session.add(
            WorkoutSet(
                client_uuid=f"uuid-{workout.date}-{number}",
                workout_id=workout.id,
                exercise_id=squat.id,
                set_number=number,
                weight_kg=weight,
                reps=reps,
                deleted_at=deleted_at,
            )
        )
    db_session.commit()
    return squat


def test_get_progress_top_weight_per_workout_sorted_by_date(db_session: Session) -> None:
    _seed_progress_data(db_session)
    result = get_progress(db_session, "深蹲")

    assert result.exercise.name_zh == "深蹲"
    assert result.exercise.name_en == "Squat"
    assert [(p.date, p.top_weight_kg, p.reps) for p in result.points] == [
        (date(2026, 7, 10), 80.0, 8),
        (date(2026, 7, 16), 85.0, 6),
    ]


def test_get_progress_matches_english_name_case_insensitive(db_session: Session) -> None:
    _seed_progress_data(db_session)
    result = get_progress(db_session, " sQuAt ")
    assert result.exercise.name_zh == "深蹲"


def test_get_progress_unknown_exercise_not_found(db_session: Session) -> None:
    _seed_progress_data(db_session)
    with pytest.raises(NotFoundError):
        get_progress(db_session, "不存在的動作")


def test_api_progress_endpoint(client: TestClient, exercise_id: int) -> None:
    workout = client.post("/api/workouts", json={"date": "2026-07-10"}).json()
    resp = client.post(
        f"/api/workouts/{workout['id']}/sets",
        json=make_set_payload(exercise_id, weight_kg=80.0, reps=8),
    )
    assert resp.status_code == 201

    resp = client.get("/api/stats/progress", params={"exercise": "squat"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["exercise"]["name_zh"] == "深蹲"
    assert body["points"] == [{"date": "2026-07-10", "top_weight_kg": 80.0, "reps": 8}]


def test_api_progress_unknown_exercise_404(client: TestClient) -> None:
    resp = client.get("/api/stats/progress", params={"exercise": "nope"})
    assert resp.status_code == 404


def test_api_progress_requires_token(anon_client: TestClient) -> None:
    resp = anon_client.get("/api/stats/progress", params={"exercise": "squat"})
    assert resp.status_code == 401
