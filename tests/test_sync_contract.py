import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.schemas import (
    SyncBodyMetricPayload,
    SyncDailyStatusPayload,
    SyncExercisePayload,
    SyncMutation,
    SyncPullOut,
    SyncPushIn,
    SyncPushOut,
    SyncSetPayload,
    SyncSettingPayload,
    SyncTemplatePayload,
    SyncWorkoutPayload,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sync"
REQUEST_FIXTURES = (
    ("exercise", "push_exercise.json"),
    ("template", "push_template.json"),
    ("workout", "push_workout.json"),
    ("set", "push_set.json"),
    ("body_metric", "push_body_metric.json"),
    ("daily_status", "push_daily_status.json"),
    ("setting", "push_setting.json"),
)
PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "exercise": SyncExercisePayload,
    "template": SyncTemplatePayload,
    "workout": SyncWorkoutPayload,
    "set": SyncSetPayload,
    "body_metric": SyncBodyMetricPayload,
    "daily_status": SyncDailyStatusPayload,
    "setting": SyncSettingPayload,
}


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _validate_payload(entity_type: str, entity_id: str, payload: dict) -> None:
    model = PAYLOAD_MODELS[entity_type].model_validate(payload)
    assert str(model.sync_id) == entity_id


@pytest.mark.parametrize(("entity_type", "fixture_name"), REQUEST_FIXTURES)
def test_push_request_fixtures_validate_against_entity_schema(
    entity_type: str, fixture_name: str
) -> None:
    request = SyncPushIn.model_validate(_fixture(fixture_name))

    assert request.schema_version == 1
    assert len(request.mutations) == 1
    mutation = SyncMutation.model_validate(request.mutations[0])
    assert mutation.entity_type == entity_type
    assert mutation.operation == "upsert"
    _validate_payload(mutation.entity_type, str(mutation.entity_id), mutation.payload)


def test_response_fixtures_validate_push_and_paginated_pull_contracts() -> None:
    accepted = SyncPushOut.model_validate(_fixture("response_push_accepted.json"))
    assert len(accepted.accepted) == 1
    assert not accepted.conflicts
    assert accepted.accepted[0].version > 0
    assert accepted.accepted[0].server_seq > 0

    conflict_raw = _fixture("response_push_conflict.json")
    conflict = SyncPushOut.model_validate(conflict_raw)
    assert not conflict.accepted
    assert len(conflict.conflicts) == 1
    server = conflict.conflicts[0].server
    assert server is not None
    assert conflict_raw["conflicts"][0]["server"]["updated_at"].endswith("Z")
    _validate_payload(server["entity_type"], server["entity_id"], server["payload"])

    pull_raw = _fixture("response_pull_paginated.json")
    pull = SyncPullOut.model_validate(pull_raw)
    sequences = [change.server_seq for change in pull.changes]
    assert sequences == sorted(sequences)
    assert pull.next_cursor == sequences[-1]
    assert pull.has_more
    for raw_change, change in zip(pull_raw["changes"], pull.changes, strict=True):
        assert raw_change["updated_at"].endswith("Z")
        assert change.schema_version == 1
        _validate_payload(change.entity_type, change.entity_id, change.payload)
