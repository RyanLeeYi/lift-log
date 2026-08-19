"""F35：動作歷來查詢端點 GET /api/exercises/{id}/history?from=&to=。
service exercise_history 回 {prs（全期）, sessions（區間內每次訓練的全部組）}。"""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models import Exercise, Workout, WorkoutSet
from app.services.history import exercise_history, months_ago
from tests.conftest import make_set_payload


def test_months_ago_calendar_month_subtraction() -> None:
    # 3 個日曆月：07-31 → 04-30（4 月無 31 日，clamp）
    assert months_ago(date(2026, 7, 31), 3) == date(2026, 4, 30)
    # 跨年
    assert months_ago(date(2026, 2, 15), 3) == date(2025, 11, 15)
    # 2 月底 clamp
    assert months_ago(date(2026, 5, 31), 3) == date(2026, 2, 28)


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
    # F105：PrEntry 多了 duration_seconds，次數型一律 null
    assert body["prs"]["top_weight"] == {"weight_kg": 100.0, "reps": 3, "duration_seconds": None}
    assert body["prs"]["top_set_volume"] == {
        "weight_kg": 80.0,
        "reps": 8,
        "duration_seconds": None,
    }


def test_api_history_invalid_date_format_422(client: TestClient, exercise_id: int) -> None:
    resp = client.get(
        f"/api/exercises/{exercise_id}/history",
        params={"from": "not-a-date", "to": "2026-07-31"},
    )
    assert resp.status_code == 422


def test_api_history_set_schema_only_contract_fields(client: TestClient, exercise_id: int) -> None:
    w = client.post("/api/workouts", json={"date": "2026-07-10"}).json()
    _post_set(client, w["id"], exercise_id, "schema-uuid-1", weight_kg=80.0, reps=8, rpe=8)
    resp = client.get(
        f"/api/exercises/{exercise_id}/history",
        params={"from": "2026-07-01", "to": "2026-07-31"},
    )
    assert resp.status_code == 200
    s = resp.json()["sessions"][0]["sets"][0]
    # R1 契約：只回 id/set_number/weight_kg/reps/rpe，不外洩 workout_id/exercise_id/rest_seconds
    # F105：契約多一個 duration_seconds（時間型才有值），仍不外洩 workout_id/exercise_id
    assert set(s.keys()) == {"id", "set_number", "weight_kg", "reps", "duration_seconds", "rpe"}


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


class TestFirstSessionDate:
    """F59：全期最早訓練日——前端據此停用超出資料範圍的區間檔位。"""

    def test_none_when_no_sets(self, db_session: Session) -> None:
        ex = Exercise(name_zh="臥推", name_en="Bench Press", muscle_group="胸")
        db_session.add(ex)
        db_session.commit()

        out = exercise_history(db_session, ex.id, date(2026, 1, 1), date(2026, 12, 31))
        assert out.first_session_date is None

    def test_earliest_session_regardless_of_range(self, db_session: Session) -> None:
        squat = _seed(db_session)  # 4/10、7/10、7/16 三次訓練

        # 查詢區間只框 7 月，first_session_date 仍要回 4/10（全期）
        out = exercise_history(db_session, squat.id, date(2026, 7, 1), date(2026, 7, 31))
        assert out.first_session_date == date(2026, 4, 10)

    def test_ignores_soft_deleted_sets(self, db_session: Session) -> None:
        ex = Exercise(name_zh="划船", name_en="Row", muscle_group="背")
        db_session.add(ex)
        db_session.flush()
        w_old = Workout(date=date(2026, 3, 1))
        w_new = Workout(date=date(2026, 7, 1))
        db_session.add_all([w_old, w_new])
        db_session.flush()
        # 舊那次的組全部軟刪 → 最早訓練日應該是 7/1，不是 3/1
        db_session.add_all([
            WorkoutSet(
                workout_id=w_old.id, exercise_id=ex.id, set_number=1, weight_kg=50.0, reps=8,
                client_uuid="f59-old-1", deleted_at=datetime(2026, 7, 20, 12, 0, 0),
            ),
            WorkoutSet(
                workout_id=w_new.id, exercise_id=ex.id, set_number=1, weight_kg=55.0, reps=8,
                client_uuid="f59-new-1",
            ),
        ])
        db_session.commit()

        out = exercise_history(db_session, ex.id, date(2026, 1, 1), date(2026, 12, 31))
        assert out.first_session_date == date(2026, 7, 1)


# ---------- F86 ②：PR 卡改成「推估 1RM／最重／單次量」三張 ----------
#
# 前兩張現有欄位就有；「推估 1RM」與「單次量」得補。都要是**全期**值——
# 從畫面當下的區間去算，等於把「這三個月最好的一次」當成個人紀錄顯示，是靜默的謊。


def test_history_prs_include_all_time_estimated_1rm(db_session: Session) -> None:
    """推估 1RM 用 Epley（w × (1 + reps/30)），取全期所有組的最大值。

    ⚠ 勝出的那一組**不一定**是最重的那組——這正是這個欄位存在的理由。
    """
    squat = _seed(db_session)
    # 60×20 → 100.0；不是最重（120）也不是最大單組量（750），但 1RM 推估最高的是 120×2＝128
    result = exercise_history(db_session, squat.id, date(2026, 7, 1), date(2026, 7, 31))
    assert result.prs.top_est_1rm == pytest.approx(128.0)  # 120 × (1 + 2/30)

    # 換一組讓「最重」與「推估 1RM」分家：100×12 → 140，勝過 120×2 的 128
    w3 = Workout(date=date(2026, 7, 20))
    db_session.add(w3)
    db_session.flush()
    db_session.add(
        WorkoutSet(
            client_uuid="uuid-1rm", workout_id=w3.id, exercise_id=squat.id,
            set_number=1, weight_kg=100.0, reps=12,
        )
    )
    db_session.commit()
    result = exercise_history(db_session, squat.id, date(2026, 7, 1), date(2026, 7, 31))
    assert result.prs.top_est_1rm == pytest.approx(140.0)  # 100 × (1 + 12/30)
    assert result.prs.top_weight.weight_kg == 120.0  # 最重那張卡不受影響


def test_history_prs_include_all_time_best_session_volume(db_session: Session) -> None:
    """單次量＝一次訓練的總量（Σ weight×reps）中的全期最大值，不是單組量。"""
    squat = _seed(db_session)
    result = exercise_history(db_session, squat.id, date(2026, 7, 1), date(2026, 7, 31))
    # 4/10：240；7/10：640＋750＝1390；7/16：510＋500＝1010（軟刪那組不計）
    assert result.prs.top_session_volume == pytest.approx(1390.0)


def test_history_new_prs_are_all_time_not_range_limited(db_session: Session) -> None:
    """區間內完全沒有資料時，兩個新欄位仍要有值（與既有 PR 欄位同語意）。"""
    squat = _seed(db_session)
    result = exercise_history(db_session, squat.id, date(2026, 1, 1), date(2026, 1, 31))
    assert result.sessions == []
    assert result.prs.top_est_1rm == pytest.approx(128.0)
    assert result.prs.top_session_volume == pytest.approx(1390.0)


def test_history_no_data_new_prs_are_null(db_session: Session) -> None:
    empty = Exercise(name_zh="臥推", name_en="Bench Press", muscle_group="胸")
    db_session.add(empty)
    db_session.commit()
    result = exercise_history(db_session, empty.id, date(2026, 7, 1), date(2026, 7, 31))
    assert result.prs.top_est_1rm is None
    assert result.prs.top_session_volume is None
