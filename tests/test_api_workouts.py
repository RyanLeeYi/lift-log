"""F1 記錄 API 驗收測試（PRD R1）：CRUD、client_uuid 冪等、401/400/404、數值範圍。"""

import pytest

from app.config import Settings
from app.main import create_app
from tests.conftest import make_set_payload


class TestAuth:
    def test_missing_token_returns_401(self, anon_client):
        resp = anon_client.post("/api/workouts", json={})
        assert resp.status_code == 401
        assert resp.json() == {"error": "unauthorized"}

    def test_wrong_token_returns_401(self, anon_client):
        resp = anon_client.post(
            "/api/workouts", json={}, headers={"Authorization": "Bearer wrong"}
        )
        assert resp.status_code == 401
        assert resp.json() == {"error": "unauthorized"}

    def test_missing_token_setting_refuses_startup(self, tmp_path):
        with pytest.raises(ValueError, match="LIFTLOG_TOKEN"):
            create_app(Settings(token="", db_path=str(tmp_path / "t.db")))

    def test_app_factory_builds_app_from_env(self, tmp_path, monkeypatch):
        """uvicorn 官方入口：app.main:app_factory --factory 必須可用（讀環境變數）。"""
        from app.main import app_factory

        monkeypatch.setenv("LIFTLOG_TOKEN", "env-token")
        monkeypatch.setenv("LIFTLOG_DB", str(tmp_path / "env.db"))
        app = app_factory()
        assert app.state.settings.token == "env-token"


class TestCreateWorkout:
    def test_create_workout_returns_201_with_id_and_date(self, client):
        resp = client.post("/api/workouts", json={"date": "2026-07-17", "note": "練腿日"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] > 0
        assert body["date"] == "2026-07-17"
        assert body["note"] == "練腿日"

    def test_create_workout_defaults_to_today(self, client):
        resp = client.post("/api/workouts", json={})
        assert resp.status_code == 201
        assert resp.json()["date"]  # 有日期即可，具體值依 server 當天


class TestLogSet:
    def test_log_set_returns_201_and_is_queryable(self, client, exercise_id):
        workout_id = client.post("/api/workouts", json={}).json()["id"]
        resp = client.post(
            f"/api/workouts/{workout_id}/sets",
            json=make_set_payload(exercise_id, rpe=8, rest_seconds=90),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["weight_kg"] == 80.0
        assert body["reps"] == 8
        assert body["rpe"] == 8
        assert body["rest_seconds"] == 90

        detail = client.get(f"/api/workouts/{workout_id}").json()
        assert len(detail["sets"]) == 1
        assert detail["sets"][0]["id"] == body["id"]

    def test_same_client_uuid_is_idempotent(self, client, exercise_id):
        workout_id = client.post("/api/workouts", json={}).json()["id"]
        payload = make_set_payload(exercise_id)
        first = client.post(f"/api/workouts/{workout_id}/sets", json=payload)
        second = client.post(f"/api/workouts/{workout_id}/sets", json=payload)
        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"]
        detail = client.get(f"/api/workouts/{workout_id}").json()
        assert len(detail["sets"]) == 1

    def test_missing_reps_returns_400(self, client, exercise_id):
        workout_id = client.post("/api/workouts", json={}).json()["id"]
        payload = make_set_payload(exercise_id)
        del payload["reps"]
        resp = client.post(f"/api/workouts/{workout_id}/sets", json=payload)
        assert resp.status_code == 400
        assert "reps" in resp.json()["error"]

    @pytest.mark.parametrize(
        "field,value",
        [("weight_kg", -1), ("reps", 0), ("rpe", 0), ("rpe", 11)],
    )
    def test_out_of_range_values_return_400(self, client, exercise_id, field, value):
        workout_id = client.post("/api/workouts", json={}).json()["id"]
        resp = client.post(
            f"/api/workouts/{workout_id}/sets",
            json=make_set_payload(exercise_id, **{field: value}),
        )
        assert resp.status_code == 400
        assert field in resp.json()["error"]

    def test_unknown_workout_returns_404(self, client, exercise_id):
        resp = client.post("/api/workouts/9999/sets", json=make_set_payload(exercise_id))
        assert resp.status_code == 404

    def test_unknown_exercise_returns_400(self, client):
        workout_id = client.post("/api/workouts", json={}).json()["id"]
        resp = client.post(f"/api/workouts/{workout_id}/sets", json=make_set_payload(9999))
        assert resp.status_code == 400
        assert "exercise" in resp.json()["error"]


class TestIdempotencyEdges:
    """code review C1/C2/C3：冪等重放的邊界（詳見 PRD 邊界情況）。"""

    def test_replay_against_nonexistent_workout_returns_404(self, client, exercise_id):
        workout_id = client.post("/api/workouts", json={}).json()["id"]
        payload = make_set_payload(exercise_id)
        assert client.post(f"/api/workouts/{workout_id}/sets", json=payload).status_code == 201
        resp = client.post("/api/workouts/9999/sets", json=payload)
        assert resp.status_code == 404
        assert resp.json() == {"error": "not found"}

    def test_replay_against_different_workout_returns_409(self, client, exercise_id):
        w1 = client.post("/api/workouts", json={}).json()["id"]
        w2 = client.post("/api/workouts", json={}).json()["id"]
        payload = make_set_payload(exercise_id)
        assert client.post(f"/api/workouts/{w1}/sets", json=payload).status_code == 201
        resp = client.post(f"/api/workouts/{w2}/sets", json=payload)
        assert resp.status_code == 409
        assert "client_uuid" in resp.json()["error"]

    def test_replay_of_soft_deleted_set_returns_409(self, client, exercise_id):
        workout_id = client.post("/api/workouts", json={}).json()["id"]
        payload = make_set_payload(exercise_id)
        set_id = client.post(f"/api/workouts/{workout_id}/sets", json=payload).json()["id"]
        assert client.delete(f"/api/sets/{set_id}").status_code == 204
        resp = client.post(f"/api/workouts/{workout_id}/sets", json=payload)
        assert resp.status_code == 409
        assert "client_uuid" in resp.json()["error"]

    def test_concurrent_duplicate_insert_recovers_idempotently(
        self, client, exercise_id, monkeypatch
    ):
        """模擬 TOCTOU：冪等檢查時看不到（對手尚未 commit），insert 才撞 UNIQUE。
        服務層應 rollback 後重查，復原為冪等 200 回既有那筆，不得漏出 500。"""
        from app.services import workouts as svc

        workout_id = client.post("/api/workouts", json={}).json()["id"]
        payload = make_set_payload(exercise_id)
        first = client.post(f"/api/workouts/{workout_id}/sets", json=payload)
        assert first.status_code == 201

        real_find = svc._find_by_client_uuid
        calls = {"n": 0}

        def blind_then_real(session, client_uuid):  # noqa: ANN001 - 測試替身
            calls["n"] += 1
            if calls["n"] == 1:
                return None  # 第一次（冪等檢查）看不到對手的 row
            return real_find(session, client_uuid)  # 復原重查看得到

        monkeypatch.setattr(svc, "_find_by_client_uuid", blind_then_real)
        resp = client.post(f"/api/workouts/{workout_id}/sets", json=payload)
        assert resp.status_code == 200
        assert resp.json()["id"] == first.json()["id"]


class TestDeleteSet:
    def test_soft_delete_removes_from_detail(self, client, exercise_id):
        workout_id = client.post("/api/workouts", json={}).json()["id"]
        set_id = client.post(
            f"/api/workouts/{workout_id}/sets", json=make_set_payload(exercise_id)
        ).json()["id"]
        resp = client.delete(f"/api/sets/{set_id}")
        assert resp.status_code == 204
        detail = client.get(f"/api/workouts/{workout_id}").json()
        assert detail["sets"] == []

    def test_delete_unknown_set_returns_404(self, client):
        resp = client.delete("/api/sets/9999")
        assert resp.status_code == 404
        assert resp.json() == {"error": "not found"}


class TestQueryWorkouts:
    def test_list_workouts_filters_by_date_range(self, client):
        client.post("/api/workouts", json={"date": "2026-07-01"})
        client.post("/api/workouts", json={"date": "2026-07-10"})
        client.post("/api/workouts", json={"date": "2026-07-31"})  # end 邊界日，必須含入
        client.post("/api/workouts", json={"date": "2026-08-01"})
        resp = client.get("/api/workouts?start=2026-07-01&end=2026-07-31")
        assert resp.status_code == 200
        dates = [w["date"] for w in resp.json()]
        assert dates == ["2026-07-01", "2026-07-10", "2026-07-31"]

    def test_get_unknown_workout_returns_404(self, client):
        resp = client.get("/api/workouts/9999")
        assert resp.status_code == 404
        assert resp.json() == {"error": "not found"}


class TestExercises:
    def test_duplicate_exercise_name_returns_400(self, client, exercise_id):
        resp = client.post(
            "/api/exercises",
            json={"name_zh": "深蹲", "name_en": "Squat", "muscle_group": "腿"},
        )
        assert resp.status_code == 400
        assert "exists" in resp.json()["error"]

    def test_search_with_sql_wildcard_is_literal(self, client, exercise_id):
        resp = client.get("/api/exercises?q=%25")  # q=% 應當字面比對，不得全匹配
        assert resp.status_code == 200
        assert resp.json() == []

    def test_last_sets_unknown_exercise_returns_404(self, client):
        resp = client.get("/api/exercises/9999/last-sets")
        assert resp.status_code == 404
        assert resp.json() == {"error": "not found"}

    def test_search_matches_both_languages(self, client, exercise_id):
        for q in ("深蹲", "squat", "Squ"):
            resp = client.get(f"/api/exercises?q={q}")
            assert resp.status_code == 200
            assert any(e["id"] == exercise_id for e in resp.json()), q

    def test_last_sets_returns_most_recent_workout_sets(self, client, exercise_id):
        w1 = client.post("/api/workouts", json={"date": "2026-07-01"}).json()["id"]
        w2 = client.post("/api/workouts", json={"date": "2026-07-10"}).json()["id"]
        client.post(
            f"/api/workouts/{w1}/sets",
            json=make_set_payload(exercise_id, client_uuid="a" * 32, weight_kg=75),
        )
        client.post(
            f"/api/workouts/{w2}/sets",
            json=make_set_payload(exercise_id, client_uuid="b" * 32, weight_kg=80),
        )
        resp = client.get(f"/api/exercises/{exercise_id}/last-sets")
        assert resp.status_code == 200
        sets = resp.json()
        assert len(sets) == 1
        assert sets[0]["weight_kg"] == 80  # 只回最近一次 workout 的組

    def test_last_sets_returns_empty_for_new_exercise(self, client, exercise_id):
        resp = client.get(f"/api/exercises/{exercise_id}/last-sets")
        assert resp.status_code == 200
        assert resp.json() == []
