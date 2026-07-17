"""F3 驗收：GET /api/stats/calendar 每日噸位（PRD R3）。

噸位 = Σ(重量×次數)；自體重動作以（最新體重＋額外負重）計，
F8 之前沒有 body_metrics，規則落在「無體重紀錄時只計額外負重」。
"""

from fastapi.testclient import TestClient

from tests.conftest import make_set_payload


def _workout_on(client: TestClient, date: str) -> int:
    return client.post("/api/workouts", json={"date": date}).json()["id"]


def _log(client: TestClient, workout_id: int, exercise_id: int, uuid: str, **kw) -> dict:
    resp = client.post(
        f"/api/workouts/{workout_id}/sets",
        json=make_set_payload(exercise_id, client_uuid=uuid, **kw),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestCalendarTonnage:
    def test_daily_tonnage_sums_weight_times_reps(self, client, exercise_id):
        w = _workout_on(client, "2026-07-16")
        _log(client, w, exercise_id, "u1" * 16, weight_kg=80, reps=8, set_number=1)
        _log(client, w, exercise_id, "u2" * 16, weight_kg=85, reps=6, set_number=2)

        resp = client.get("/api/stats/calendar?year=2026&month=7")
        assert resp.status_code == 200
        body = resp.json()
        assert body["year"] == 2026
        assert body["month"] == 7
        assert body["days"]["2026-07-16"] == 80 * 8 + 85 * 6  # 1150

    def test_bodyweight_without_body_metrics_counts_extra_load_only(self, client):
        pullup = client.post(
            "/api/exercises",
            json={
                "name_zh": "引體向上",
                "name_en": "Pull-up",
                "muscle_group": "背",
                "is_bodyweight": True,
            },
        ).json()["id"]
        w = _workout_on(client, "2026-07-10")
        _log(client, w, pullup, "a1" * 16, weight_kg=0, reps=6, set_number=1)  # 純自體重 → 0
        _log(client, w, pullup, "a2" * 16, weight_kg=10, reps=6, set_number=2)  # 額外負重 10

        days = client.get("/api/stats/calendar?year=2026&month=7").json()["days"]
        assert days["2026-07-10"] == 0 * 6 + 10 * 6  # 60

    def test_soft_deleted_sets_excluded(self, client, exercise_id):
        w = _workout_on(client, "2026-07-05")
        kept = _log(client, w, exercise_id, "b1" * 16, weight_kg=50, reps=10, set_number=1)
        removed = _log(client, w, exercise_id, "b2" * 16, weight_kg=100, reps=10, set_number=2)
        assert kept
        assert client.delete(f"/api/sets/{removed['id']}").status_code == 204

        days = client.get("/api/stats/calendar?year=2026&month=7").json()["days"]
        assert days["2026-07-05"] == 500

    def test_only_requested_month_included(self, client, exercise_id):
        w_in = _workout_on(client, "2026-07-31")
        w_out = _workout_on(client, "2026-08-01")
        _log(client, w_in, exercise_id, "c1" * 16, weight_kg=60, reps=5, set_number=1)
        _log(client, w_out, exercise_id, "c2" * 16, weight_kg=60, reps=5, set_number=1)

        days = client.get("/api/stats/calendar?year=2026&month=7").json()["days"]
        assert "2026-07-31" in days
        assert "2026-08-01" not in days

    def test_empty_month_returns_empty_days(self, client):
        resp = client.get("/api/stats/calendar?year=2026&month=1")
        assert resp.status_code == 200
        assert resp.json()["days"] == {}

    def test_invalid_month_returns_400(self, client):
        assert client.get("/api/stats/calendar?year=2026&month=13").status_code == 400
        assert client.get("/api/stats/calendar?year=2026&month=0").status_code == 400

    def test_requires_token(self, anon_client):
        resp = anon_client.get("/api/stats/calendar?year=2026&month=7")
        assert resp.status_code == 401
        assert resp.json() == {"error": "unauthorized"}
