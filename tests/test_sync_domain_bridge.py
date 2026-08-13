"""F154：domain 表與同步層是同一份資料。

這支測的是 acceptance ④——**來源不影響結論**。手機推上來的，REST 要查得到；
網頁／REST 寫的，手機 pull 要拿得到。F154 之前這兩邊是兩個互不相干的世界，
所有單元測試各自都會過，合起來卻是壞的，所以這條檢查必須跨路徑寫。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _claims(raw_token: str) -> dict[str, object]:
    return {
        "sub": f"google-{raw_token}",
        "aud": "test-google-client",
        "iss": "https://accounts.google.com",
        "exp": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp()),
        "nonce": f"nonce-{raw_token}-long-enough",
        "email": f"{raw_token}@example.com",
        "email_verified": True,
    }


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        token="legacy-token",
        db_path=str(tmp_path / "legacy.db"),
        control_db_path=str(tmp_path / "control.db"),
        user_data_dir=str(tmp_path / "users"),
        google_client_id="test-google-client",
    )
    return TestClient(
        create_app(settings, google_token_verifier=_claims),
        base_url="https://testserver",
    )


def _login(client: TestClient) -> tuple[dict[str, str], str]:
    """同一顆 access token 同時用在 REST 與 sync——兩邊必須落在同一個 user data DB。"""
    response = client.post(
        "/api/auth/google",
        json={
            "id_token": "bridge",
            "nonce": "nonce-bridge-long-enough",
            "device_id": str(uuid4()),
            "device_name": "bridge",
            "client": "android",
        },
    )
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["device"]["id"]


def _pull(client: TestClient, headers: dict[str, str], cursor: int = 0) -> list[dict]:
    response = client.get(f"/api/sync/pull?cursor={cursor}&limit=1000", headers=headers)
    assert response.status_code == 200
    return response.json()["changes"]


def _changes_of(changes: list[dict], entity_type: str) -> list[dict]:
    return [change for change in changes if change["entity_type"] == entity_type]


def test_rest_writes_show_up_in_the_sync_change_log(client: TestClient) -> None:
    with client as api:
        headers, _device = _login(api)

        exercise = api.post(
            "/api/exercises",
            headers=headers,
            # 用種子動作庫裡沒有的名字——不然撞的是「動作已存在」，測不到 change log
            json={"name_zh": "橋接測試臥推", "name_en": "BridgeBench", "muscle_group": "胸"},
        )
        assert exercise.status_code == 201
        workout = api.post(
            "/api/workouts", headers=headers, json={"date": "2026-08-14"}
        ).json()
        added = api.post(
            f"/api/workouts/{workout['id']}/sets",
            headers=headers,
            json={
                "client_uuid": str(uuid4()),
                "exercise_id": exercise.json()["id"],
                "set_number": 1,
                "weight_kg": 100,
                "reps": 5,
            },
        )
        assert added.status_code == 201

        changes = _pull(api, headers)
        assert _changes_of(changes, "exercise"), "REST 建的動作沒有進 change log"
        assert _changes_of(changes, "workout"), "REST 建的訓練沒有進 change log"
        set_changes = _changes_of(changes, "set")
        assert set_changes, "REST 記的組沒有進 change log"

        # payload 要是同步層看得懂的形狀，不是 domain row 直接倒出來
        payload = set_changes[-1]["payload"]
        assert payload["weight_kg"] == 100
        assert payload["reps"] == 5
        assert payload["workout_sync_id"] and payload["exercise_sync_id"]
        # server_seq 單調遞增，pull 的 cursor 才推得動
        assert [change["server_seq"] for change in changes] == sorted(
            change["server_seq"] for change in changes
        )


def test_sync_push_is_visible_to_rest_queries(client: TestClient) -> None:
    with client as api:
        headers, device_id = _login(api)
        metric_id = str(uuid4())
        push = api.post(
            "/api/sync/push",
            headers=headers,
            json={
                "schema_version": 1,
                "device_id": device_id,
                "mutations": [
                    {
                        "mutation_id": str(uuid4()),
                        "entity_type": "body_metric",
                        "entity_id": metric_id,
                        "operation": "upsert",
                        "base_version": 0,
                        "lease_generation": None,
                        "payload": {
                            "sync_id": metric_id,
                            "date": "2026-08-14",
                            "weight_kg": 81.5,
                            "body_fat_pct": 18,
                        },
                    }
                ],
            },
        )
        assert push.status_code == 200
        assert push.json()["accepted"], push.json()

        listed = api.get("/api/body-metrics", headers=headers)
        assert listed.status_code == 200
        rows = listed.json()
        assert [row["weight_kg"] for row in rows] == [81.5], "手機推上來的體重 REST 查不到"


def test_rest_delete_reaches_the_other_device_as_a_tombstone(client: TestClient) -> None:
    with client as api:
        headers, _device = _login(api)
        api.post(
            "/api/body-metrics",
            headers=headers,
            json={"date": "2026-08-14", "weight_kg": 80},
        )
        api.delete("/api/body-metrics/2026-08-14", headers=headers)

        metric_changes = _changes_of(_pull(api, headers), "body_metric")
        assert metric_changes[-1]["operation"] == "delete", "硬刪的話另一台裝置永遠不知道"
        assert metric_changes[-1]["deleted_at"] is not None
        # 使用者這一側看到的仍然是「刪掉了」
        assert api.get("/api/body-metrics", headers=headers).json() == []


def test_same_row_written_from_both_paths_keeps_versions_monotonic(client: TestClient) -> None:
    with client as api:
        headers, device_id = _login(api)
        api.post(
            "/api/body-metrics",
            headers=headers,
            json={"date": "2026-08-14", "weight_kg": 80},
        )
        first = _changes_of(_pull(api, headers), "body_metric")[-1]
        sync_id = first["entity_id"]

        # 同一筆改由 sync 這條路再寫一次：版本要往上，不是各自從 1 起算
        push = api.post(
            "/api/sync/push",
            headers=headers,
            json={
                "schema_version": 1,
                "device_id": device_id,
                "mutations": [
                    {
                        "mutation_id": str(uuid4()),
                        "entity_type": "body_metric",
                        "entity_id": sync_id,
                        "operation": "upsert",
                        "base_version": first["version"],
                        "lease_generation": None,
                        "payload": {
                            "sync_id": sync_id,
                            "date": "2026-08-14",
                            "weight_kg": 79,
                            "body_fat_pct": None,
                        },
                    }
                ],
            },
        )
        assert push.status_code == 200
        accepted = push.json()["accepted"]
        assert accepted, push.json()
        assert accepted[0]["version"] == first["version"] + 1

        # REST 這側看到的是同一筆被改掉，不是多出第二筆
        rows = api.get("/api/body-metrics", headers=headers).json()
        assert [row["weight_kg"] for row in rows] == [79]


def test_stale_base_version_from_sync_does_not_silently_overwrite_rest_write(
    client: TestClient,
) -> None:
    with client as api:
        headers, device_id = _login(api)
        api.post(
            "/api/body-metrics",
            headers=headers,
            json={"date": "2026-08-14", "weight_kg": 80},
        )
        sync_id = _changes_of(_pull(api, headers), "body_metric")[-1]["entity_id"]

        push = api.post(
            "/api/sync/push",
            headers=headers,
            json={
                "schema_version": 1,
                "device_id": device_id,
                "mutations": [
                    {
                        "mutation_id": str(uuid4()),
                        "entity_type": "body_metric",
                        "entity_id": sync_id,
                        "operation": "upsert",
                        "base_version": 0,  # 過期的版本
                        "lease_generation": None,
                        "payload": {
                            "sync_id": sync_id,
                            "date": "2026-08-14",
                            "weight_kg": 60,
                            "body_fat_pct": None,
                        },
                    }
                ],
            },
        )
        assert push.json()["conflicts"], "過期版本必須退成衝突，不能默默覆蓋"
        assert api.get("/api/body-metrics", headers=headers).json()[0]["weight_kg"] == 80
