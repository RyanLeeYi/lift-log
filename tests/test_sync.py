from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import make_engine
from app.main import create_app
from app.sync_models import SyncEntity


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
def sync_client(tmp_path: Path) -> TestClient:
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


def _login(client: TestClient, name: str) -> tuple[dict[str, str], str]:
    response = client.post(
        "/api/auth/google",
        json={
            "id_token": name,
            "nonce": f"nonce-{name}-long-enough",
            "device_id": str(uuid4()),
            "device_name": name,
            "client": "android",
        },
    )
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["device"]["id"]


def _mutation(
    *,
    mutation_id: str | None = None,
    entity_id: str | None = None,
    entity_type: str = "body_metric",
    operation: str = "upsert",
    base_version: int = 0,
    payload: dict | None = None,
) -> dict:
    entity_id = entity_id or str(uuid4())
    return {
        "mutation_id": mutation_id or str(uuid4()),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "operation": operation,
        "base_version": base_version,
        "lease_generation": None,
        "payload": payload
        or {
            "sync_id": entity_id,
            "date": "2026-08-11",
            "weight_kg": 80,
            "body_fat_pct": 20,
        },
    }


def _baseline(client: TestClient, headers: dict[str, str]) -> int:
    """登入後的基準游標。

    F154 起種子動作庫也會進 change log（不進的話新帳號的手機永遠拿不到預設動作），
    所以 server_seq 不再從 1 起算。測試改成驗「相對於基準的增量」，那才是真正要釘的東西。
    """
    page = client.get("/api/sync/pull?cursor=0&limit=1000", headers=headers)
    assert page.status_code == 200
    return int(page.json()["next_cursor"])


def _body_metric_payload(day: int) -> dict:
    entity_id = str(uuid4())
    return {
        "sync_id": entity_id,
        "date": f"2026-08-{day:02d}",
        "weight_kg": 80,
        "body_fat_pct": 20,
    }


def _push(
    client: TestClient,
    headers: dict[str, str],
    device_id: str,
    mutations: list[dict],
    *,
    schema_version: int = 1,
):
    return client.post(
        "/api/sync/push",
        headers=headers,
        json={
            "schema_version": schema_version,
            "device_id": device_id,
            "mutations": mutations,
        },
    )


def test_push_is_idempotent_and_pull_cursor_is_stable(sync_client: TestClient) -> None:
    with sync_client as client:
        headers, device_id = _login(client, "idempotent")
        base = _baseline(client, headers)
        mutation = _mutation()

        first = _push(client, headers, device_id, [mutation])
        repeated = _push(client, headers, device_id, [mutation])

        assert first.status_code == 200
        assert repeated.json() == first.json()
        accepted = first.json()["accepted"]
        assert accepted[0]["version"] == 1
        assert accepted[0]["server_seq"] == base + 1

        page = client.get(f"/api/sync/pull?cursor={base}&limit=1000", headers=headers)
        repeated_page = client.get(f"/api/sync/pull?cursor={base}&limit=1000", headers=headers)
        assert page.status_code == 200
        assert repeated_page.json() == page.json()
        assert [change["server_seq"] for change in page.json()["changes"]] == [base + 1]
        assert page.json()["next_cursor"] == base + 1
        assert page.json()["has_more"] is False


def test_version_conflict_tombstone_and_delete_idempotency(sync_client: TestClient) -> None:
    with sync_client as client:
        headers, device_id = _login(client, "conflict")
        entity_id = str(uuid4())
        created = _mutation(entity_id=entity_id)
        assert _push(client, headers, device_id, [created]).status_code == 200

        stale = _mutation(entity_id=entity_id, base_version=0)
        conflict = _push(client, headers, device_id, [stale]).json()["conflicts"][0]
        assert conflict["reason"] == "version_mismatch"
        assert conflict["server"]["version"] == 1

        deleted = _mutation(
            entity_id=entity_id,
            operation="delete",
            base_version=1,
            payload={"sync_id": entity_id},
        )
        delete_result = _push(client, headers, device_id, [deleted]).json()["accepted"][0]
        assert delete_result["version"] == 2

        second_delete = _mutation(
            entity_id=entity_id,
            operation="delete",
            base_version=1,
            payload={"sync_id": entity_id},
        )
        idempotent_delete = _push(client, headers, device_id, [second_delete]).json()
        assert idempotent_delete["accepted"][0]["version"] == 2
        assert idempotent_delete["accepted"][0]["server_seq"] == delete_result["server_seq"]

        resurrection = _mutation(entity_id=entity_id, base_version=2)
        rejected = _push(client, headers, device_id, [resurrection]).json()["conflicts"][0]
        assert rejected["reason"] == "tombstoned"


def test_pull_paginates_without_gaps_or_duplicates(sync_client: TestClient) -> None:
    with sync_client as client:
        headers, device_id = _login(client, "pagination")
        base = _baseline(client, headers)
        # F154 起 domain 表是事實來源，而體重一天只有一筆——三筆同日的 metric 不再是三個
        # 獨立 entity，而是自然鍵衝突。這裡要驗的是分頁，所以給三個不同日期。
        payloads = [_body_metric_payload(day) for day in (11, 12, 13)]
        mutations = [
            _mutation(entity_id=payload["sync_id"], payload=payload) for payload in payloads
        ]
        assert _push(client, headers, device_id, mutations).status_code == 200

        first = client.get(f"/api/sync/pull?cursor={base}&limit=2", headers=headers).json()
        second = client.get(
            f"/api/sync/pull?cursor={first['next_cursor']}&limit=2", headers=headers
        ).json()

        assert [row["server_seq"] for row in first["changes"]] == [base + 1, base + 2]
        assert first["has_more"] is True
        assert [row["server_seq"] for row in second["changes"]] == [base + 3]
        assert second["has_more"] is False


def test_invalid_mutation_does_not_block_valid_sibling_or_advance_for_it(
    sync_client: TestClient,
) -> None:
    with sync_client as client:
        headers, device_id = _login(client, "partial")
        base = _baseline(client, headers)
        invalid = _mutation(entity_type="unknown")
        valid = _mutation()

        result = _push(client, headers, device_id, [invalid, valid])

        assert result.status_code == 200
        assert result.json()["conflicts"][0]["reason"] == "unsupported_entity"
        assert result.json()["accepted"][0]["server_seq"] == base + 1
        changes = client.get(
            f"/api/sync/pull?cursor={base}", headers=headers
        ).json()["changes"]
        assert len(changes) == 1
        assert changes[0]["entity_id"] == valid["entity_id"]


def test_missing_dependency_can_retry_after_parent_arrives(sync_client: TestClient) -> None:
    with sync_client as client:
        headers, device_id = _login(client, "dependency")
        base = _baseline(client, headers)
        workout_id = str(uuid4())
        exercise_id = str(uuid4())
        set_id = str(uuid4())
        set_mutation = _mutation(
            entity_type="set",
            entity_id=set_id,
            payload={
                "sync_id": set_id,
                "client_uuid": str(uuid4()),
                "workout_sync_id": workout_id,
                "exercise_sync_id": exercise_id,
                "set_number": 1,
                "weight_kg": 80,
                "reps": 8,
                "rpe": 8,
                "rest_seconds": 90,
            },
        )
        blocked = _push(client, headers, device_id, [set_mutation]).json()
        assert blocked["conflicts"][0]["reason"] == "dependency_missing"

        workout = _mutation(
            entity_type="workout",
            entity_id=workout_id,
            payload={
                "sync_id": workout_id,
                "date": "2026-08-11",
                "template_sync_id": None,
                "note": None,
                "ended_at": None,
                "owner_device_id": device_id,
                "lease_generation": 1,
            },
        )
        exercise = _mutation(
            entity_type="exercise",
            entity_id=exercise_id,
            payload={
                "sync_id": exercise_id,
                # 不能用種子動作庫裡有的名字——F154 起會撞自然鍵，變成衝突而不是新增
                "name_zh": "測試專用動作",
                "name_en": "Dependency Test Lift",
                "muscle_group": "腿",
                "is_bodyweight": False,
            },
        )
        assert len(_push(client, headers, device_id, [workout, exercise]).json()["accepted"]) == 2
        retried = _push(client, headers, device_id, [set_mutation]).json()
        assert retried["accepted"][0]["server_seq"] == base + 3


def test_push_enforces_schema_device_count_and_byte_boundaries(sync_client: TestClient) -> None:
    with sync_client as client:
        headers, device_id = _login(client, "boundaries")
        assert _push(client, headers, device_id, [], schema_version=999).status_code == 409
        assert _push(client, headers, str(uuid4()), []).status_code == 403
        too_many = _push(client, headers, device_id, [_mutation() for _ in range(501)])
        assert too_many.status_code == 400

        oversized = _mutation(
            entity_type="daily_status",
            payload={
                "sync_id": str(uuid4()),
                "date": "2026-08-11",
                "energy": 3,
                "sleep_quality": 3,
                "note": "x" * (1024 * 1024),
            },
        )
        oversized["entity_id"] = oversized["payload"]["sync_id"]
        response = _push(client, headers, device_id, [oversized])
        assert response.status_code == 413
        assert response.json() == {"error": "sync_batch_too_large"}

        before_json_parsing = client.post(
            "/api/sync/push",
            headers={**headers, "Content-Length": str(1024 * 1024 + 1)},
            content=b"{",
        )
        assert before_json_parsing.status_code == 413
        assert before_json_parsing.json() == {"error": "sync_batch_too_large"}

        lying_length = client.post(
            "/api/sync/push",
            headers={
                **headers,
                "Content-Length": "1",
                "Origin": "https://localhost",
            },
            content=b"x" * (1024 * 1024 + 1),
        )
        assert lying_length.status_code == 413
        assert lying_length.headers["Access-Control-Allow-Origin"] == "https://localhost"

        def chunks():
            yield b"x" * (512 * 1024)
            yield b"x" * (512 * 1024 + 1)

        without_length = client.post(
            "/api/sync/push",
            headers={**headers, "Transfer-Encoding": "chunked"},
            content=chunks(),
        )
        assert without_length.status_code == 413


def test_sync_requires_google_android_session(sync_client: TestClient) -> None:
    with sync_client as client:
        mutation = _mutation()
        legacy = _push(
            client,
            {"Authorization": "Bearer legacy-token"},
            str(uuid4()),
            [mutation],
        )
        assert legacy.status_code == 401


def test_sync_is_user_scoped(sync_client: TestClient) -> None:
    with sync_client as client:
        alice_headers, alice_device = _login(client, "sync-alice")
        bob_headers, _bob_device = _login(client, "sync-bob")
        assert _push(client, alice_headers, alice_device, [_mutation()]).status_code == 200

        # F154 起兩人各自都有種子動作的 change，所以比的是「基準之後有沒有對方的東西」
        bob_base = _baseline(client, bob_headers)
        assert client.get(
            f"/api/sync/pull?cursor={bob_base}", headers=bob_headers
        ).json()["changes"] == []
        alice_changes = client.get(
            "/api/sync/pull?cursor=0", headers=alice_headers
        ).json()["changes"]
        assert len([c for c in alice_changes if c["entity_type"] == "body_metric"]) == 1


def test_locked_database_returns_stable_503(
    sync_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import sync

    def locked(*_args, **_kwargs):
        raise OperationalError("statement", {}, Exception("database is locked"))

    monkeypatch.setattr(sync, "push", locked)
    with sync_client as client:
        headers, device_id = _login(client, "locked")
        response = _push(client, headers, device_id, [_mutation()])
        assert response.status_code == 503
        assert response.json() == {"error": "sync_unavailable"}


def test_quota_full_database_returns_sync_503(sync_client: TestClient) -> None:
    with sync_client as client:
        headers, device_id = _login(client, "full-sync")
        client.app.state.settings.data_db_max_bytes = 1
        response = _push(client, headers, device_id, [_mutation()])
        assert response.status_code == 503
        assert response.json() == {"error": "sync_unavailable"}


def test_client_cursor_ahead_is_rejected_without_disabling_sync(sync_client: TestClient) -> None:
    with sync_client as client:
        headers, device_id = _login(client, "cursor-ahead")
        assert _push(client, headers, device_id, [_mutation()]).status_code == 200

        ahead = client.get("/api/sync/pull?cursor=99", headers=headers)
        assert ahead.status_code == 409
        assert ahead.json() == {"error": "sync_cursor_ahead"}
        assert _push(client, headers, device_id, [_mutation()]).status_code == 200


def test_server_sequence_regression_disables_sync(sync_client: TestClient) -> None:
    with sync_client as client:
        headers, device_id = _login(client, "regression")
        assert _push(client, headers, device_id, [_mutation()]).status_code == 200
        with client.app.state.control_session_factory() as control:
            control.execute(text("UPDATE users SET sync_server_seq=99"))
            control.commit()

        regression = client.get("/api/sync/pull?cursor=0", headers=headers)
        assert regression.status_code == 503
        assert regression.json() == {"error": "sync_sequence_regression"}
        assert _push(client, headers, device_id, [_mutation()]).status_code == 503


def test_concurrent_same_base_version_accepts_only_one_update(tmp_path: Path) -> None:
    from app.services import sync

    engine = make_engine(str(tmp_path / "concurrent.db"))
    SyncEntity.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    entity_id = str(uuid4())
    with factory() as session:
        created = sync.push(session, [_mutation(entity_id=entity_id)])
        assert created["accepted"][0]["server_seq"] == 1  # 這支不經 HTTP，沒有種子動作

    start = Barrier(2)

    def update(weight_kg: float) -> dict:
        mutation = _mutation(
            entity_id=entity_id,
            base_version=1,
            payload={
                "sync_id": entity_id,
                "date": "2026-08-11",
                "weight_kg": weight_kg,
                "body_fat_pct": 20,
            },
        )
        start.wait()
        with factory() as session:
            return sync.push(session, [mutation], sequence_floor=1)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(update, (79.8, 80.2)))

    assert sum(bool(result["accepted"]) for result in results) == 1
    assert sum(
        result["conflicts"][0]["reason"] == "version_mismatch"
        for result in results
        if result["conflicts"]
    ) == 1
