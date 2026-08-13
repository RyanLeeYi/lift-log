"""F152 批次寫入 dry-run：回傳將發生什麼，不寫入任何資料、不產生 change log。

dry-run 重用 F151 的冪等鍵判斷（`_plan_batch`），conflict 情境專測「idem_key 為 NULL 的
舊資料」——那是 F151 之前寫入、真的寫下去會撞 SET_NUMBER_UNIQUE_INDEX 的典型來源。
"""

from sqlalchemy import select

from app.models import Exercise, Workout, WorkoutSet
from app.sync_models import SyncState

BATCH = {
    "date": "2026-08-14",
    "sets": [
        {"exercise": "深蹲", "weight_kg": 80, "reps": 8},
        {"exercise": "深蹲", "weight_kg": 85, "reps": 6},
    ],
}


def _row_counts(client):
    factory = client.app.state.session_factory  # type: ignore[attr-defined]
    with factory() as session:
        return {
            "exercises": session.query(Exercise).count(),
            "workouts": session.query(Workout).count(),
            "sets": session.query(WorkoutSet).count(),
        }


def _high_water_value(client):
    factory = client.app.state.session_factory  # type: ignore[attr-defined]
    with factory() as session:
        row = session.get(SyncState, "server_seq_high_water")
        return row.value if row else None


class TestBatchDryRun:
    def test_fresh_batch_reports_all_create_and_writes_nothing(self, client, exercise_id):
        before = _row_counts(client)

        resp = client.post("/api/workouts/batch", json={**BATCH, "dry_run": True})

        assert resp.status_code == 200
        body = resp.json()
        assert (
            body["will_create_count"],
            body["will_skip_count"],
            body["will_conflict_count"],
        ) == (2, 0, 0)
        assert _row_counts(client) == before

    def test_after_real_write_dry_run_reports_skip(self, client, exercise_id):
        client.post("/api/workouts/batch", json=BATCH)

        body = client.post("/api/workouts/batch", json={**BATCH, "dry_run": True}).json()

        assert (body["will_create_count"], body["will_skip_count"]) == (0, 2)

    def test_dry_run_then_real_write_report_consistent_counts(self, client, exercise_id):
        dry = client.post("/api/workouts/batch", json={**BATCH, "dry_run": True}).json()

        real = client.post("/api/workouts/batch", json=BATCH).json()

        assert real["created_count"] == dry["will_create_count"]
        assert real["skipped_count"] == dry["will_skip_count"]

        again_dry = client.post("/api/workouts/batch", json={**BATCH, "dry_run": True}).json()
        assert again_dry["will_create_count"] == 0
        assert again_dry["will_skip_count"] == real["created_count"]

    def test_create_missing_dry_run_does_not_create_exercise_row(self, client):
        before = _row_counts(client)["exercises"]

        body = client.post(
            "/api/workouts/batch",
            json={
                "date": "2026-08-14",
                "create_missing": True,
                "dry_run": True,
                "sets": [{"exercise": "臥推", "weight_kg": 60, "reps": 8}],
            },
        ).json()

        assert body["will_create_count"] == 1
        assert _row_counts(client)["exercises"] == before

    def test_conflict_from_legacy_null_idem_key_row(self, client, exercise_id):
        """模擬 F151 之前的舊資料（idem_key=NULL）：真的寫下去會撞組號唯一約束。"""
        first = client.post("/api/workouts/batch", json=BATCH).json()

        factory = client.app.state.session_factory  # type: ignore[attr-defined]
        with factory() as session:
            legacy = session.scalar(
                select(WorkoutSet).where(
                    WorkoutSet.workout_id == first["workout_id"],
                    WorkoutSet.exercise_id == exercise_id,
                    WorkoutSet.set_number == 2,
                )
            )
            legacy.idem_key = None
            session.commit()

        resp = client.post(
            "/api/workouts/batch",
            json={
                **BATCH,
                "sets": [*BATCH["sets"], {"exercise": "深蹲", "weight_kg": 95, "reps": 4}],
                "dry_run": True,
            },
        )

        body = resp.json()
        assert (
            body["will_create_count"],
            body["will_skip_count"],
            body["will_conflict_count"],
        ) == (1, 1, 1)
        dispositions = {item["index"]: item["disposition"] for item in body["preview"]}
        assert dispositions == {0: "skip", 1: "conflict", 2: "create"}
        # 零副作用：conflict 判定本身不得留下任何新列
        assert _row_counts(client)["sets"] == 2

    def test_dry_run_does_not_advance_server_seq_high_water(self, client, exercise_id):
        before = _high_water_value(client)

        client.post("/api/workouts/batch", json={**BATCH, "dry_run": True})

        assert _high_water_value(client) == before

    def test_unknown_exercise_dry_run_still_returns_400(self, client):
        resp = client.post(
            "/api/workouts/batch",
            json={
                "date": "2026-08-14",
                "dry_run": True,
                "sets": [{"exercise": "不存在的動作", "weight_kg": 10, "reps": 1}],
            },
        )

        assert resp.status_code == 400
        assert resp.json()["error"] == "validation failed"
