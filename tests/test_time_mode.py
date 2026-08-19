"""F105 時間型動作（棒式這類做幾秒）的回歸檢查。

只放「這條邏輯壞掉時會紅」的檢查：mode 互斥驗證、噸位不吃時間型、
熱力圖改吃組數、PR 兩張卡、MCP 查得到秒數，以及舊 DB 的 reps 去 NOT NULL。
"""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import make_engine
from app.migrations import migrate_schema
from tests.conftest import make_set_payload


def _time_exercise(client: TestClient) -> int:
    resp = client.post(
        "/api/exercises",
        json={
            "name_zh": "棒式",
            "name_en": "Plank",
            "muscle_group": "核心",
            "is_bodyweight": True,
            "mode": "time",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["mode"] == "time"
    return resp.json()["id"]


def _workout(client: TestClient, date: str = "2026-07-16") -> int:
    return client.post("/api/workouts", json={"date": date}).json()["id"]


def _post_set(client: TestClient, workout_id: int, payload: dict):
    return client.post(f"/api/workouts/{workout_id}/sets", json=payload)


def _time_payload(exercise_id: int, **overrides) -> dict:
    payload = make_set_payload(exercise_id, **overrides)
    payload.pop("reps", None)
    payload.setdefault("duration_seconds", 60)
    return payload


class TestModeValidation:
    """acceptance ②：欄位組合與動作 mode 不符一律 422。"""

    def test_time_set_accepts_duration_only(self, client):
        ex = _time_exercise(client)
        resp = _post_set(client, _workout(client), _time_payload(ex, weight_kg=0))
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["duration_seconds"] == 60
        assert body["reps"] is None

    def test_time_set_with_reps_is_422(self, client):
        ex = _time_exercise(client)
        payload = _time_payload(ex)
        payload["reps"] = 10
        assert _post_set(client, _workout(client), payload).status_code == 422

    def test_time_set_without_duration_is_422(self, client):
        ex = _time_exercise(client)
        payload = _time_payload(ex)
        del payload["duration_seconds"]
        assert _post_set(client, _workout(client), payload).status_code == 422

    def test_reps_set_with_duration_is_422(self, client, exercise_id):
        payload = make_set_payload(exercise_id, duration_seconds=30)
        assert _post_set(client, _workout(client), payload).status_code == 422

    def test_update_cannot_switch_mode(self, client, exercise_id):
        """編輯不得把次數型的組改成時間型——動作的 mode 才是權威。"""
        w = _workout(client)
        set_id = _post_set(client, w, make_set_payload(exercise_id)).json()["id"]
        resp = client.patch(f"/api/sets/{set_id}", json={"weight_kg": 60, "duration_seconds": 45})
        assert resp.status_code == 422


class TestTonnageAndCalendar:
    """acceptance ③④：時間型不進噸位，熱力圖改吃組數。"""

    def test_time_sets_contribute_zero_tonnage_but_count_seconds(self, client):
        ex = _time_exercise(client)
        w = _workout(client, "2026-07-16")
        for i, seconds in enumerate((60, 45), start=1):
            payload = _time_payload(
                ex,
                client_uuid=str(i) * 32,
                weight_kg=0,
                set_number=i,
                duration_seconds=seconds,
            )
            assert _post_set(client, w, payload).status_code == 201

        day = client.get("/api/stats/calendar?year=2026&month=7").json()["days"]["2026-07-16"]
        assert day["tonnage_kg"] == 0.0
        assert day["duration_seconds"] == 105
        # ④ 的重點：只做棒式的一天噸位是 0，靠 sets_count 才不會被畫成「沒練」
        assert day["sets_count"] == 2

    def test_reps_and_time_on_same_day_are_not_added_together(self, client, exercise_id):
        ex = _time_exercise(client)
        w = _workout(client, "2026-07-16")
        reps_set = make_set_payload(exercise_id, weight_kg=80, reps=8)
        assert _post_set(client, w, reps_set).status_code == 201
        time_set = _time_payload(ex, client_uuid="9" * 32, weight_kg=0)
        assert _post_set(client, w, time_set).status_code == 201

        day = client.get("/api/stats/calendar?year=2026&month=7").json()["days"]["2026-07-16"]
        assert day["tonnage_kg"] == 640.0  # 只有次數型那組
        assert day["duration_seconds"] == 60  # 只有時間型那組
        assert day["sets_count"] == 2


class TestTimePrs:
    """acceptance ⑤：時間型只有兩張卡，估計 1RM 整格不出現（None）。"""

    def test_prs_use_duration_and_omit_est_1rm(self, client):
        ex = _time_exercise(client)
        w1 = _workout(client, "2026-07-10")
        first = _time_payload(ex, client_uuid="a" * 32, weight_kg=0, duration_seconds=60)
        assert _post_set(client, w1, first).status_code == 201
        second = _time_payload(
            ex, client_uuid="b" * 32, weight_kg=0, set_number=2, duration_seconds=50
        )
        assert _post_set(client, w1, second).status_code == 201
        w2 = _workout(client, "2026-07-12")
        third = _time_payload(ex, client_uuid="c" * 32, weight_kg=0, duration_seconds=90)
        assert _post_set(client, w2, third).status_code == 201

        prs = client.get(
            f"/api/exercises/{ex}/history", params={"from": "2026-07-01", "to": "2026-07-31"}
        ).json()["prs"]
        assert prs["top_set_duration"]["duration_seconds"] == 90  # 最長單組
        assert prs["top_session_duration_seconds"] == 110  # 60+50 那次勝過 90
        assert prs["top_est_1rm"] is None
        assert prs["top_weight"] is None
        assert prs["top_set_volume"] is None


class TestMcpAndProgress:
    """acceptance ⑦：MCP 要答得出「棒式我做過幾秒」。"""

    def test_progress_returns_longest_set_for_time_exercise(self, client):
        ex = _time_exercise(client)
        w = _workout(client, "2026-07-10")
        short = _time_payload(ex, client_uuid="d" * 32, weight_kg=0, duration_seconds=40)
        assert _post_set(client, w, short).status_code == 201
        longest = _time_payload(
            ex, client_uuid="e" * 32, weight_kg=0, set_number=2, duration_seconds=75
        )
        assert _post_set(client, w, longest).status_code == 201

        points = client.get("/api/stats/progress", params={"exercise": "棒式"}).json()["points"]
        assert points == [
            {"date": "2026-07-10", "top_weight_kg": 0.0, "reps": None, "duration_seconds": 75}
        ]


class TestNoRegressionForRepsMode:
    """acceptance ⑨：既有次數型行為不變。"""

    def test_reps_set_still_writes_and_counts_tonnage(self, client, exercise_id):
        w = _workout(client, "2026-07-16")
        resp = _post_set(client, w, make_set_payload(exercise_id, weight_kg=80, reps=8))
        assert resp.status_code == 201
        assert resp.json()["reps"] == 8
        assert resp.json()["duration_seconds"] is None
        day = client.get("/api/stats/calendar?year=2026&month=7").json()["days"]["2026-07-16"]
        assert day["tonnage_kg"] == 640.0
        assert day["duration_seconds"] == 0

    def test_existing_exercises_default_to_reps_mode(self, client, exercise_id):
        listed = client.get("/api/exercises", params={"q": "深蹲"}).json()
        assert listed[0]["mode"] == "reps"


def _legacy_engine(tmp_path: Path):
    """F105 之前的 sets：reps 是 NOT NULL，且沒有 duration_seconds。"""
    engine = make_engine(str(tmp_path / "legacy_f105.db"))
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE sets ("
                "id INTEGER PRIMARY KEY, client_uuid VARCHAR NOT NULL, "
                "workout_id INTEGER NOT NULL, exercise_id INTEGER NOT NULL, "
                "set_number INTEGER NOT NULL, weight_kg FLOAT NOT NULL, "
                "reps INTEGER NOT NULL, rpe INTEGER, rest_seconds INTEGER, "
                "deleted_at DATETIME, created_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE exercises ("
                "id INTEGER PRIMARY KEY, name_zh VARCHAR, name_en VARCHAR, "
                "muscle_group VARCHAR, is_bodyweight BOOLEAN, created_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO sets "
                "(id, client_uuid, workout_id, exercise_id, set_number, weight_kg, reps) "
                "VALUES (1, 'legacy-uuid', 1, 1, 1, 80.0, 8)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO exercises (id, name_zh, name_en, muscle_group, is_bodyweight) "
                "VALUES (1, '深蹲', 'Squat', '腿', 0)"
            )
        )
    return engine


def _reps_notnull(engine) -> int:
    with engine.begin() as conn:
        return next(r[3] for r in conn.execute(text("PRAGMA table_info(sets)")) if r[1] == "reps")


class TestMigration:
    """acceptance ①⑩：既有 DB 升級後 reps 可為 NULL，且既有資料一列不少。"""

    def test_legacy_reps_becomes_nullable_and_rows_survive(self, tmp_path: Path):
        engine = _legacy_engine(tmp_path)
        assert _reps_notnull(engine) == 1

        migrate_schema(engine)

        assert _reps_notnull(engine) == 0
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT id, client_uuid, weight_kg, reps, duration_seconds FROM sets")
            ).one()
            assert tuple(row) == (1, "legacy-uuid", 80.0, 8, None)
            modes = conn.execute(text("SELECT mode FROM exercises")).all()
            assert [r[0] for r in modes] == ["reps"]  # 既有動作全部視為次數型

    def test_migration_is_idempotent(self, tmp_path: Path):
        engine = _legacy_engine(tmp_path)
        migrate_schema(engine)
        migrate_schema(engine)
        with engine.begin() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM sets")).scalar() == 1
            indexes = {r[1] for r in conn.execute(text("PRAGMA index_list(sets)"))}
        assert "ix_sets_client_uuid" in indexes
        assert "ix_sets_workout_exercise_set_number_active" in indexes
