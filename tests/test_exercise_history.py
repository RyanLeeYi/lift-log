"""F35：動作歷來查詢端點 GET /api/exercises/{id}/history?from=&to=。
service exercise_history 回 {prs（全期）, sessions（區間內每次訓練的全部組）}。"""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Exercise, Workout, WorkoutSet
from app.services.history import exercise_history
from tests.conftest import make_set_payload


def _seed(db_session: Session) -> Exercise:
    """深蹲三次訓練：4/10（區間外，含全期最重 120×2）、7/10、7/16（含軟刪組）。"""
    squat = Exercise(name_zh="深蹲", name_en="Squat", muscle_group="腿")
    db_session.add(squat)
    db_session.flush()
    w0 = Workout(date=date(2026, 4, 10))
    w1 = Workout(date=date(2026, 7, 10))
    w2 = Workout(date=date(2026, 7, 16))
    db_session.add_all([w0, w1, w2])
    db_session.flush()
    rows = [
        (w0, 1, 120.0, 2, None),   # 全期最重重量 120，也是全期最大單組量 240
        (w1, 1, 80.0, 8, None),    # 單組量 640
        (w1, 2, 75.0, 10, None),
        (w2, 1, 85.0, 6, None),
        (w2, 2, 100.0, 5, None),   # 單組量 500
        (w2, 3, 90.0, 1, datetime(2026, 7, 16, 12, 0)),  # 軟刪，不得計入
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


def test_history_sessions_in_range_all_sets_sorted(db_session: Session) -> None:
    squat = _seed(db_session)
    result = exercise_history(db_session, squat.id, date(2026, 7, 1), date(2026, 7, 31))
    # 只含 7 月兩次訓練，依日期升冪
    assert [s.date for s in result.sessions] == [date(2026, 7, 10), date(2026, 7, 16)]
    # 每次訓練含當次全部（未軟刪）組
    assert [(st.weight_kg, st.reps) for st in result.sessions[0].sets] == [(80.0, 8), (75.0, 10)]
    # 軟刪那組（90×1）不得出現
    assert [(st.weight_kg, st.reps) for st in result.sessions[1].sets] == [(85.0, 6), (100.0, 5)]


def test_history_prs_all_time_regardless_of_range(db_session: Session) -> None:
    squat = _seed(db_session)
    # 查 7 月，但 PR 要反映全期（4/10 的 120×2 在區間外）
    result = exercise_history(db_session, squat.id, date(2026, 7, 1), date(2026, 7, 31))
    assert result.prs.top_weight.weight_kg == 120.0
    assert result.prs.top_weight.reps == 2
    # 全期單組最大 weight×reps：75×10=750 > 80×8=640 > 100×5=500 > 120×2=240
    assert result.prs.top_set_volume.weight_kg == 75.0
    assert result.prs.top_set_volume.reps == 10


def test_history_empty_range_still_has_prs(db_session: Session) -> None:
    squat = _seed(db_session)
    result = exercise_history(db_session, squat.id, date(2026, 1, 1), date(2026, 1, 31))
    assert result.sessions == []
    assert result.prs.top_weight.weight_kg == 120.0  # 區間外仍有 → PR 有值


def test_history_unknown_exercise_not_found(db_session: Session) -> None:
    _seed(db_session)
    with pytest.raises(NotFoundError):
        exercise_history(db_session, 99999, date(2026, 7, 1), date(2026, 7, 31))


def test_history_no_data_at_all_prs_null(db_session: Session) -> None:
    ohp = Exercise(name_zh="肩推", name_en="OHP", muscle_group="肩")
    db_session.add(ohp)
    db_session.commit()
    result = exercise_history(db_session, ohp.id, date(2026, 7, 1), date(2026, 7, 31))
    assert result.sessions == []
    assert result.prs.top_weight is None
    assert result.prs.top_set_volume is None


# ---- API 層 ----

def _post_set(client: TestClient, wid: int, ex: int, uuid: str, **kw: object) -> None:
    resp = client.post(
        f"/api/workouts/{wid}/sets",
        json=make_set_payload(ex, client_uuid=uuid, **kw),
    )
    assert resp.status_code == 201


def test_api_history_returns_prs_and_sessions(client: TestClient, exercise_id: int) -> None:
    w = client.post("/api/workouts", json={"date": "2026-07-10"}).json()
    _post_set(client, w["id"], exercise_id, "api-uuid-1", set_number=1, weight_kg=80.0, reps=8)
    _post_set(client, w["id"], exercise_id, "api-uuid-2", set_number=2, weight_kg=100.0, reps=3)

    resp = client.get(
        f"/api/exercises/{exercise_id}/history",
        params={"from": "2026-07-01", "to": "2026-07-31"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["date"] == "2026-07-10"
    got = {(s["weight_kg"], s["reps"]) for s in body["sessions"][0]["sets"]}
    assert got == {(80.0, 8), (100.0, 3)}
    assert body["prs"]["top_weight"] == {"weight_kg": 100.0, "reps": 3}
    assert body["prs"]["top_set_volume"] == {"weight_kg": 80.0, "reps": 8}


def test_api_history_from_after_to_422(client: TestClient, exercise_id: int) -> None:
    resp = client.get(
        f"/api/exercises/{exercise_id}/history",
        params={"from": "2026-07-31", "to": "2026-07-01"},
    )
    assert resp.status_code == 422


def test_api_history_unknown_exercise_404(client: TestClient) -> None:
    resp = client.get(
        "/api/exercises/99999/history",
        params={"from": "2026-07-01", "to": "2026-07-31"},
    )
    assert resp.status_code == 404


def test_api_history_requires_token(anon_client: TestClient) -> None:
    resp = anon_client.get(
        "/api/exercises/1/history",
        params={"from": "2026-07-01", "to": "2026-07-31"},
    )
    assert resp.status_code == 401


def test_api_history_default_range_last_3_months(client: TestClient, exercise_id: int) -> None:
    # 省略 from/to → 預設近 3 個月；不報錯、回 200 與該區間
    resp = client.get(f"/api/exercises/{exercise_id}/history")
    assert resp.status_code == 200
    assert "prs" in resp.json() and "sessions" in resp.json()
