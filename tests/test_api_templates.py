"""F4 課表 API 驗收測試（PRD R4）：CRUD、動作順序與預設組數、刪課表不影響歷史 workout。"""

from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def exercise_ids(client: TestClient) -> list[int]:
    """三個動作，供順序與更新測試用。"""
    ids = []
    for zh, en, group in [
        ("深蹲", "Squat", "腿"),
        ("硬舉", "Deadlift", "背"),
        ("臥推", "Bench Press", "胸"),
    ]:
        resp = client.post(
            "/api/exercises",
            json={"name_zh": zh, "name_en": en, "muscle_group": group},
        )
        assert resp.status_code == 201
        ids.append(resp.json()["id"])
    return ids


def make_template_payload(exercise_ids: list[int], **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "練腿日",
        "exercises": [
            {"exercise_id": exercise_ids[0], "default_sets": 5},
            {"exercise_id": exercise_ids[1], "default_sets": 3},
        ],
    }
    return {**payload, **overrides}


class TestAuth:
    def test_templates_require_token(self, anon_client):
        assert anon_client.get("/api/templates").status_code == 401
        assert anon_client.post("/api/templates", json={}).status_code == 401


class TestCreateTemplate:
    def test_create_returns_201_with_exercises_in_order(self, client, exercise_ids):
        resp = client.post("/api/templates", json=make_template_payload(exercise_ids))
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] > 0
        assert body["name"] == "練腿日"
        assert [e["exercise_id"] for e in body["exercises"]] == exercise_ids[:2]
        assert [e["position"] for e in body["exercises"]] == [1, 2]
        assert [e["default_sets"] for e in body["exercises"]] == [5, 3]

    def test_create_includes_bilingual_names_for_display(self, client, exercise_ids):
        resp = client.post("/api/templates", json=make_template_payload(exercise_ids))
        first = resp.json()["exercises"][0]
        assert first["name_zh"] == "深蹲"
        assert first["name_en"] == "Squat"
        assert first["muscle_group"] == "腿"  # 前端 state.exercise 契約：與動作庫 shape 一致

    def test_exercises_include_is_bodyweight_for_logger_defaults(self, client):
        """前端 logger 靠 is_bodyweight 決定預設重量（自體重動作負重 0）。"""
        pullup = client.post(
            "/api/exercises",
            json={
                "name_zh": "引體向上",
                "name_en": "Pull-up",
                "muscle_group": "背",
                "is_bodyweight": True,
            },
        ).json()
        resp = client.post(
            "/api/templates",
            json={
                "name": "背日",
                "exercises": [{"exercise_id": pullup["id"], "default_sets": 3}],
            },
        )
        assert resp.json()["exercises"][0]["is_bodyweight"] is True

    def test_unknown_exercise_id_returns_400_and_writes_nothing(self, client, exercise_ids):
        payload = make_template_payload(exercise_ids)
        payload["exercises"].append({"exercise_id": 9999, "default_sets": 3})
        resp = client.post("/api/templates", json=payload)
        assert resp.status_code == 400
        assert resp.json() == {"error": "exercise not found"}
        assert client.get("/api/templates").json() == []

    def test_empty_name_returns_400(self, client, exercise_ids):
        resp = client.post("/api/templates", json=make_template_payload(exercise_ids, name=""))
        assert resp.status_code == 400

    def test_empty_exercises_returns_400(self, client, exercise_ids):
        resp = client.post(
            "/api/templates", json=make_template_payload(exercise_ids, exercises=[])
        )
        assert resp.status_code == 400

    def test_nonpositive_default_sets_returns_400(self, client, exercise_ids):
        payload = make_template_payload(exercise_ids)
        payload["exercises"][0]["default_sets"] = 0
        resp = client.post("/api/templates", json=payload)
        assert resp.status_code == 400

    def test_duplicate_name_returns_400(self, client, exercise_ids):
        """MCP log_workout 以名稱解析課表——同名課表會讓解析歧義，建立時就擋。"""
        payload = make_template_payload(exercise_ids, name="練腿日")
        assert client.post("/api/templates", json=payload).status_code == 201
        resp = client.post("/api/templates", json=payload)
        assert resp.status_code == 400
        assert client.get("/api/templates").json()[0]["name"] == "練腿日"
        assert len(client.get("/api/templates").json()) == 1

    def test_put_rename_onto_existing_name_returns_400(self, client, exercise_ids):
        first = client.post(
            "/api/templates", json=make_template_payload(exercise_ids, name="練腿日")
        ).json()
        client.post("/api/templates", json=make_template_payload(exercise_ids, name="上半身日"))
        resp = client.put(
            f"/api/templates/{first['id']}",
            json=make_template_payload(exercise_ids, name="上半身日"),
        )
        assert resp.status_code == 400

    def test_put_keeping_own_name_is_allowed(self, client, exercise_ids):
        created = client.post(
            "/api/templates", json=make_template_payload(exercise_ids, name="練腿日")
        ).json()
        resp = client.put(
            f"/api/templates/{created['id']}",
            json=make_template_payload(exercise_ids, name="練腿日"),
        )
        assert resp.status_code == 200


class TestListAndGetTemplate:
    def test_list_returns_all_templates_with_exercises(self, client, exercise_ids):
        client.post("/api/templates", json=make_template_payload(exercise_ids))
        client.post("/api/templates", json=make_template_payload(exercise_ids, name="上半身日"))
        body = client.get("/api/templates").json()
        assert [t["name"] for t in body] == ["練腿日", "上半身日"]
        assert all(len(t["exercises"]) == 2 for t in body)

    def test_get_detail_orders_by_position(self, client, exercise_ids):
        # 逆序建立，回傳仍須照 position 排序
        payload = make_template_payload(
            exercise_ids,
            exercises=[
                {"exercise_id": exercise_ids[2], "default_sets": 4},
                {"exercise_id": exercise_ids[0], "default_sets": 5},
            ],
        )
        template_id = client.post("/api/templates", json=payload).json()["id"]
        body = client.get(f"/api/templates/{template_id}").json()
        assert [e["exercise_id"] for e in body["exercises"]] == [
            exercise_ids[2],
            exercise_ids[0],
        ]

    def test_get_unknown_id_returns_404(self, client):
        resp = client.get("/api/templates/9999")
        assert resp.status_code == 404
        assert resp.json() == {"error": "not found"}


class TestUpdateTemplate:
    def test_put_replaces_name_and_exercises(self, client, exercise_ids):
        template_id = client.post(
            "/api/templates", json=make_template_payload(exercise_ids)
        ).json()["id"]
        resp = client.put(
            f"/api/templates/{template_id}",
            json={
                "name": "混合日",
                "exercises": [{"exercise_id": exercise_ids[2], "default_sets": 4}],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "混合日"
        assert [e["exercise_id"] for e in body["exercises"]] == [exercise_ids[2]]

        fetched = client.get(f"/api/templates/{template_id}").json()
        assert fetched["name"] == "混合日"
        assert len(fetched["exercises"]) == 1

    def test_put_unknown_id_returns_404(self, client, exercise_ids):
        resp = client.put(
            "/api/templates/9999", json=make_template_payload(exercise_ids)
        )
        assert resp.status_code == 404

    def test_put_unknown_exercise_keeps_original(self, client, exercise_ids):
        """更新失敗不得留半套：原課表內容必須原封不動。"""
        template_id = client.post(
            "/api/templates", json=make_template_payload(exercise_ids)
        ).json()["id"]
        resp = client.put(
            f"/api/templates/{template_id}",
            json={"name": "壞課表", "exercises": [{"exercise_id": 9999, "default_sets": 1}]},
        )
        assert resp.status_code == 400
        body = client.get(f"/api/templates/{template_id}").json()
        assert body["name"] == "練腿日"
        assert len(body["exercises"]) == 2


class TestDeleteTemplate:
    def test_delete_returns_204_then_404(self, client, exercise_ids):
        template_id = client.post(
            "/api/templates", json=make_template_payload(exercise_ids)
        ).json()["id"]
        assert client.delete(f"/api/templates/{template_id}").status_code == 204
        assert client.get(f"/api/templates/{template_id}").status_code == 404

    def test_delete_unknown_id_returns_404(self, client):
        assert client.delete("/api/templates/9999").status_code == 404

    def test_delete_does_not_affect_historical_workouts(self, client, exercise_ids):
        """PRD R4：刪除課表不影響歷史 workout 紀錄。

        ⚠ F82（Ryan 2026-07-29 裁決）調整了「不影響」的界線：訓練紀錄本身完全保留
        （日期、組數、備註、sets），但**與課表的關聯會被解除**（template_id → NULL）。
        原因是 SQLite 的 INTEGER PRIMARY KEY 會重用被刪掉的最大 id——留著那個數字，
        下一份新建的課表就會繼承這場訓練的歷史（顯示成它的「上次訓練」並冠上新名字）。
        課表都不在了，那個數字本來就解讀不出任何東西。
        """
        template_id = client.post(
            "/api/templates", json=make_template_payload(exercise_ids)
        ).json()["id"]
        workout = client.post(
            "/api/workouts", json={"template_id": template_id, "note": "練腿日"}
        ).json()

        assert client.delete(f"/api/templates/{template_id}").status_code == 204

        detail = client.get(f"/api/workouts/{workout['id']}")
        assert detail.status_code == 200
        assert detail.json()["note"] == "練腿日"  # 紀錄本身完好
        assert detail.json()["template_id"] is None  # 但不再指向一個已不存在的課表


class TestRestHint:
    """F12（PRD R10）：參考休息秒數存於課表動作——選填、範圍 15–600、未設回 null。"""

    def test_create_persists_rest_hint_and_null_when_omitted(self, client, exercise_ids):
        payload = make_template_payload(exercise_ids)
        payload["exercises"][0]["rest_hint_seconds"] = 90
        resp = client.post("/api/templates", json=payload)
        assert resp.status_code == 201
        got = resp.json()["exercises"]
        assert got[0]["rest_hint_seconds"] == 90
        assert got[1]["rest_hint_seconds"] is None  # 未設定→null，前端才知道要用預設 60

    def test_rest_hint_survives_get_roundtrip(self, client, exercise_ids):
        payload = make_template_payload(exercise_ids)
        payload["exercises"][0]["rest_hint_seconds"] = 180
        template_id = client.post("/api/templates", json=payload).json()["id"]
        got = client.get(f"/api/templates/{template_id}").json()
        assert got["exercises"][0]["rest_hint_seconds"] == 180

    def test_update_can_set_and_clear_rest_hint(self, client, exercise_ids):
        template_id = client.post(
            "/api/templates", json=make_template_payload(exercise_ids)
        ).json()["id"]
        payload = make_template_payload(exercise_ids)
        payload["exercises"][0]["rest_hint_seconds"] = 120
        updated = client.put(f"/api/templates/{template_id}", json=payload)
        assert updated.status_code == 200
        assert updated.json()["exercises"][0]["rest_hint_seconds"] == 120

        cleared = client.put(
            f"/api/templates/{template_id}", json=make_template_payload(exercise_ids)
        )
        assert cleared.json()["exercises"][0]["rest_hint_seconds"] is None

    @pytest.mark.parametrize("bad", [14, 601, 0, -30])
    def test_rest_hint_out_of_range_rejected(self, client, exercise_ids, bad):
        payload = make_template_payload(exercise_ids)
        payload["exercises"][0]["rest_hint_seconds"] = bad
        resp = client.post("/api/templates", json=payload)
        assert resp.status_code == 400
        assert "error" in resp.json()

    @pytest.mark.parametrize("ok", [15, 600])
    def test_rest_hint_boundaries_accepted(self, client, exercise_ids, ok):
        payload = make_template_payload(exercise_ids)
        payload["exercises"][0]["rest_hint_seconds"] = ok
        assert client.post("/api/templates", json=payload).status_code == 201
