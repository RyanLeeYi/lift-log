from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.schemas import (
    SyncBodyMetricPayload,
    SyncDailyStatusPayload,
    SyncDeletePayload,
    SyncExercisePayload,
    SyncMutation,
    SyncSetPayload,
    SyncSettingPayload,
    SyncTemplatePayload,
    SyncWorkoutPayload,
)
from app.services import projection
from app.sync_models import MutationReceipt, SyncChange, SyncEntity, SyncState

SCHEMA_VERSION = 1

_PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "exercise": SyncExercisePayload,
    "template": SyncTemplatePayload,
    "workout": SyncWorkoutPayload,
    "set": SyncSetPayload,
    "body_metric": SyncBodyMetricPayload,
    "daily_status": SyncDailyStatusPayload,
    "setting": SyncSettingPayload,
}


class SequenceRegression(Exception):
    pass


class CursorAhead(Exception):
    pass


class MissingDependency(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _state(session: Session, key: str) -> str | None:
    row = session.get(SyncState, key)
    return row.value if row else None


def _set_state(session: Session, key: str, value: str) -> None:
    row = session.get(SyncState, key)
    if row:
        row.value = value
    else:
        session.add(SyncState(key=key, value=value))


def _high_water(session: Session, sequence_floor: int) -> int:
    actual = session.scalar(select(func.max(SyncChange.server_seq))) or 0
    stored = int(_state(session, "server_seq_high_water") or actual)
    if _state(session, "disabled_reason") or actual < max(stored, sequence_floor):
        _set_state(session, "disabled_reason", "sequence_regression")
        session.commit()
        raise SequenceRegression
    if stored != actual:
        _set_state(session, "server_seq_high_water", str(actual))
    return actual


def _entity_json(entity: SyncEntity | None) -> dict[str, Any] | None:
    if entity is None:
        return None
    return {
        "entity_type": entity.entity_type,
        "entity_id": entity.entity_id,
        "version": entity.version,
        "updated_at": entity.updated_at.isoformat() + "Z",
        "deleted_at": entity.deleted_at.isoformat() + "Z" if entity.deleted_at else None,
        "payload": json.loads(entity.payload_json),
    }


def _conflict(mutation_id: str | None, reason: str, entity: SyncEntity | None = None) -> dict:
    return {
        "mutation_id": mutation_id,
        "reason": reason,
        "server": _entity_json(entity),
    }


def _receipt_hash(mutation: SyncMutation) -> str:
    encoded = _json(mutation.model_dump(mode="json")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _save_receipt(
    session: Session,
    mutation: SyncMutation,
    request_hash: str,
    kind: str,
    result: dict,
) -> None:
    session.add(
        MutationReceipt(
            mutation_id=str(mutation.mutation_id),
            request_hash=request_hash,
            result_kind=kind,
            result_json=_json(result),
            created_at=_now(),
        )
    )


def _record_change(
    session: Session,
    entity: SyncEntity,
    operation: str,
    payload: dict[str, Any],
) -> int:
    change = SyncChange(
        schema_version=SCHEMA_VERSION,
        entity_type=entity.entity_type,
        entity_id=entity.entity_id,
        operation=operation,
        version=entity.version,
        updated_at=entity.updated_at,
        deleted_at=entity.deleted_at,
        payload_json=_json(payload),
    )
    session.add(change)
    session.flush()
    _set_state(session, "server_seq_high_water", str(change.server_seq))
    return change.server_seq


def _require_active(session: Session, entity_type: str, entity_id: str) -> None:
    entity = session.scalar(
        select(SyncEntity).where(
            SyncEntity.entity_type == entity_type,
            SyncEntity.entity_id == entity_id,
            SyncEntity.deleted_at.is_(None),
        )
    )
    if entity is None:
        raise MissingDependency


def _validate_dependencies(
    session: Session, entity_type: str, payload: dict[str, Any]
) -> None:
    if entity_type == "set":
        _require_active(session, "workout", payload["workout_sync_id"])
        _require_active(session, "exercise", payload["exercise_sync_id"])
    elif entity_type == "workout" and payload["template_sync_id"]:
        _require_active(session, "template", payload["template_sync_id"])
    elif entity_type == "template":
        for item in payload["exercises"]:
            _require_active(session, "exercise", item["exercise_sync_id"])


def _apply_upsert(session: Session, mutation: SyncMutation, entity: SyncEntity | None) -> dict:
    payload_model = _PAYLOAD_MODELS[mutation.entity_type]
    payload = payload_model.model_validate(mutation.payload).model_dump(mode="json")
    if payload["sync_id"] != str(mutation.entity_id):
        raise ValueError("sync_id mismatch")
    _validate_dependencies(session, mutation.entity_type, payload)
    if entity and entity.deleted_at:
        return _conflict(str(mutation.mutation_id), "tombstoned", entity)
    if entity is None and mutation.base_version != 0:
        return _conflict(str(mutation.mutation_id), "version_mismatch")
    if entity and entity.version != mutation.base_version:
        return _conflict(str(mutation.mutation_id), "version_mismatch", entity)

    # F154：先投影到 domain 表。它是唯一會因為自然鍵撞號而失敗的一步，
    # 放在 SyncEntity 版本更新之前，失敗時才不會留下「版本加了但資料沒寫」的半套狀態。
    row = projection.apply_payload(session, mutation.entity_type, payload)

    now = _now()
    if entity is None:
        entity = SyncEntity(
            entity_type=mutation.entity_type,
            entity_id=str(mutation.entity_id),
            version=1,
            updated_at=now,
            deleted_at=None,
            payload_json=_json(payload),
        )
        session.add(entity)
    else:
        entity.version += 1
        entity.updated_at = now
        entity.payload_json = _json(payload)
    entity.deleted_at = None
    row.version = entity.version
    server_seq = _record_change(session, entity, "upsert", payload)
    return {
        "mutation_id": str(mutation.mutation_id),
        "version": entity.version,
        "server_seq": server_seq,
    }


def _apply_delete(session: Session, mutation: SyncMutation, entity: SyncEntity | None) -> dict:
    payload = SyncDeletePayload.model_validate(mutation.payload).model_dump(mode="json")
    if payload["sync_id"] != str(mutation.entity_id):
        raise ValueError("sync_id mismatch")
    if entity is None:
        return _conflict(str(mutation.mutation_id), "not_found")
    if entity.deleted_at:
        server_seq = session.scalar(
            select(SyncChange.server_seq)
            .where(
                SyncChange.entity_type == entity.entity_type,
                SyncChange.entity_id == entity.entity_id,
                SyncChange.operation == "delete",
            )
            .order_by(SyncChange.server_seq.desc())
            .limit(1)
        )
        return {
            "mutation_id": str(mutation.mutation_id),
            "version": entity.version,
            "server_seq": server_seq,
        }
    if entity.version != mutation.base_version:
        return _conflict(str(mutation.mutation_id), "version_mismatch", entity)

    entity.version += 1
    entity.updated_at = _now()
    entity.deleted_at = entity.updated_at
    # tombstone 同樣要落到 domain row，否則刪除只在同步層生效、REST 還查得到那筆
    row = projection.row_for(session, entity.entity_type, entity.entity_id)
    if row is not None:
        row.deleted_at = entity.deleted_at
        row.version = entity.version
    server_seq = _record_change(session, entity, "delete", payload)
    return {
        "mutation_id": str(mutation.mutation_id),
        "version": entity.version,
        "server_seq": server_seq,
    }


def _entity_of(session: Session, entity_type: str, sync_id: str | None) -> SyncEntity | None:
    if not sync_id:
        return None
    return session.scalar(
        select(SyncEntity).where(
            SyncEntity.entity_type == entity_type, SyncEntity.entity_id == sync_id
        )
    )


def _process(session: Session, raw: dict[str, Any]) -> tuple[str, dict]:
    try:
        mutation = SyncMutation.model_validate(raw)
    except ValidationError:
        mutation_id = raw.get("mutation_id") if isinstance(raw, dict) else None
        return "conflict", _conflict(str(mutation_id) if mutation_id else None, "validation_failed")

    mutation_id = str(mutation.mutation_id)
    request_hash = _receipt_hash(mutation)
    receipt = session.get(MutationReceipt, mutation_id)
    if receipt:
        if receipt.request_hash != request_hash:
            return "conflict", _conflict(mutation_id, "mutation_id_reused")
        return receipt.result_kind, json.loads(receipt.result_json)

    entity = session.scalar(
        select(SyncEntity).where(
            SyncEntity.entity_type == mutation.entity_type,
            SyncEntity.entity_id == str(mutation.entity_id),
        )
    )
    if mutation.entity_type not in _PAYLOAD_MODELS:
        kind, result = "conflict", _conflict(mutation_id, "unsupported_entity")
    elif mutation.operation == "upsert":
        try:
            result = _apply_upsert(session, mutation, entity)
        except (MissingDependency, projection.MissingReference):
            result = _conflict(mutation_id, "dependency_missing")
        except projection.NaturalKeyConflict as clash:
            # 同一個自然鍵被兩個 sync_id 搶——退成衝突交給收件匣，不自動選邊
            result = _conflict(
                mutation_id,
                "natural_key_conflict",
                _entity_of(session, mutation.entity_type, clash.existing.sync_id),
            )
        except (ValidationError, ValueError):
            result = _conflict(mutation_id, "validation_failed")
        kind = "accepted" if "server_seq" in result else "conflict"
    elif mutation.operation == "delete":
        try:
            result = _apply_delete(session, mutation, entity)
        except (ValidationError, ValueError):
            result = _conflict(mutation_id, "validation_failed")
        kind = "accepted" if "server_seq" in result else "conflict"
    else:
        kind, result = "conflict", _conflict(mutation_id, "unsupported_operation")
    if result.get("reason") != "dependency_missing":
        _save_receipt(session, mutation, request_hash, kind, result)
    return kind, result


def push(
    session: Session,
    mutations: list[dict[str, Any]],
    sequence_floor: int = 0,
) -> dict[str, list[dict]]:
    # ponytail: SQLite 本來就是 single-writer；先取 write lock，避免兩個 request 同讀舊版後
    # 都 accepted。若未來每 user 寫入量高到 5 秒 lock 不夠，再換 managed DB 的 row lock。
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    _high_water(session, sequence_floor)
    response: dict[str, list[dict]] = {"accepted": [], "conflicts": []}
    for raw in mutations:
        kind, result = _process(session, raw)
        response["accepted" if kind == "accepted" else "conflicts"].append(result)
    session.commit()
    return response


def pull(
    session: Session,
    cursor: int,
    limit: int,
    sequence_floor: int = 0,
) -> dict[str, Any]:
    high_water = _high_water(session, sequence_floor)
    if cursor > high_water:
        raise CursorAhead
    rows = list(
        session.scalars(
            select(SyncChange)
            .where(SyncChange.server_seq > cursor)
            .order_by(SyncChange.server_seq)
            .limit(limit + 1)
        )
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    changes = [
        {
            "server_seq": row.server_seq,
            "schema_version": row.schema_version,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "operation": row.operation,
            "version": row.version,
            "updated_at": row.updated_at.replace(tzinfo=UTC),
            "deleted_at": row.deleted_at.replace(tzinfo=UTC) if row.deleted_at else None,
            "payload": json.loads(row.payload_json),
        }
        for row in rows
    ]
    return {
        "changes": changes,
        "next_cursor": rows[-1].server_seq if rows else cursor,
        "has_more": has_more,
    }
