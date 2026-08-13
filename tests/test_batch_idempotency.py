"""F151 寫入冪等鍵：agent 重送同一批不會製造重複紀錄。

冪等鍵＝`date + exercise + set_index` 的 server 端 hash，不依賴 client 狀態，
因此跨 session、跨裝置重送同樣成立。與 F143 的 client_uuid mutation 冪等各自作用於
不同層（一個是「這批內容已經在庫裡」，一個是「這個請求已經處理過」），需同時涵蓋。
"""

BATCH = {
    "date": "2026-08-14",
    "sets": [
        {"exercise": "深蹲", "weight_kg": 80, "reps": 8},
        {"exercise": "深蹲", "weight_kg": 85, "reps": 6},
    ],
}


def _sets_of(client, workout_id):
    return client.get(f"/api/workouts/{workout_id}").json()["sets"]


def _all_sets(client):
    return [
        item
        for workout in client.get("/api/workouts").json()
        for item in _sets_of(client, workout["id"])
    ]


class TestBatchIdempotencyKey:
    def test_first_write_reports_all_created(self, client, exercise_id):
        body = client.post("/api/workouts/batch", json=BATCH).json()
        assert body["created_count"] == 2
        assert body["skipped_count"] == 0

    def test_resend_creates_no_row_and_reports_skipped(self, client, exercise_id):
        first = client.post("/api/workouts/batch", json=BATCH).json()

        resp = client.post("/api/workouts/batch", json=BATCH)

        assert resp.status_code == 201
        body = resp.json()
        assert (body["created_count"], body["skipped_count"]) == (0, 2)
        assert body["workout_id"] == first["workout_id"]
        assert len(_all_sets(client)) == 2
        assert len(client.get("/api/workouts").json()) == 1

    def test_resend_without_client_uuid_still_idempotent(self, client, exercise_id):
        """跨 session／跨裝置：呼叫端沒有保留任何 client 狀態也不得重複寫入。"""
        client.post("/api/workouts/batch", json=BATCH)

        client.post("/api/workouts/batch", json={**BATCH, "client_uuid": "device-b-uuid"})

        assert len(_all_sets(client)) == 2

    def test_partial_resend_only_writes_the_new_sets(self, client, exercise_id):
        client.post("/api/workouts/batch", json=BATCH)

        longer = {
            **BATCH,
            "sets": [*BATCH["sets"], {"exercise": "深蹲", "weight_kg": 90, "reps": 4}],
        }
        body = client.post("/api/workouts/batch", json=longer).json()

        assert (body["created_count"], body["skipped_count"]) == (1, 2)
        assert sorted(item["weight_kg"] for item in _all_sets(client)) == [80, 85, 90]

    def test_partial_resend_does_not_create_a_second_workout(self, client, exercise_id):
        first = client.post("/api/workouts/batch", json=BATCH).json()

        longer = {
            **BATCH,
            "sets": [*BATCH["sets"], {"exercise": "深蹲", "weight_kg": 90, "reps": 4}],
        }
        body = client.post("/api/workouts/batch", json=longer).json()

        assert body["workout_id"] == first["workout_id"]
        assert len(client.get("/api/workouts").json()) == 1
        assert len(_sets_of(client, first["workout_id"])) == 3

    def test_different_date_is_not_a_duplicate(self, client, exercise_id):
        client.post("/api/workouts/batch", json=BATCH)

        client.post("/api/workouts/batch", json={**BATCH, "date": "2026-08-15"})

        assert len(_all_sets(client)) == 4

    def test_different_exercise_is_not_a_duplicate(self, client, exercise_id):
        client.post("/api/workouts/batch", json=BATCH)

        client.post(
            "/api/workouts/batch",
            json={
                "date": BATCH["date"],
                "create_missing": True,
                "sets": [{"exercise": "臥推", "weight_kg": 60, "reps": 8}],
            },
        )

        assert len(_all_sets(client)) == 3

    def test_client_uuid_replay_still_idempotent(self, client, exercise_id):
        """F143 層（同 client_uuid 重送）不因新的鍵而失效。"""
        keyed = {**BATCH, "client_uuid": "batch-uuid-1"}
        first = client.post("/api/workouts/batch", json=keyed).json()

        again = client.post("/api/workouts/batch", json=keyed).json()

        assert again["workout_id"] == first["workout_id"]
        assert len(_all_sets(client)) == 2
