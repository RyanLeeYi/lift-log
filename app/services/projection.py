"""domain 表 ⇄ 同步層的唯一橋樑（F154）。

**domain 表是事實來源**，`sync_entities` 只是版本簿、`sync_changes` 只是變更流水。
所以這裡只有兩個方向：

- `apply_payload()`：sync push 收到的 mutation → 寫進 domain 表
- `record_write()`：REST／Web 改完 domain row → 補版本與 change log

任何 domain 寫入繞過 `record_write()`，就是 PRD R6 明文禁止的「繞過同步版本的第二條寫入路徑」
——它不會當場壞，只會讓那筆資料在另一台裝置上永遠不出現。
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from datetime import date as date_type
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AppSetting,
    BodyMetric,
    DailyStatus,
    Exercise,
    Template,
    TemplateExercise,
    Workout,
    WorkoutSet,
)
from app.sync_models import SyncChange, SyncEntity, SyncState

SCHEMA_VERSION = 1

ENTITY_MODELS: dict[str, type] = {
    "exercise": Exercise,
    "template": Template,
    "workout": Workout,
    "set": WorkoutSet,
    "body_metric": BodyMetric,
    "daily_status": DailyStatus,
    "setting": AppSetting,
}


class MissingReference(Exception):
    """payload 指到一筆本機還沒有的 entity（依賴還沒送到）。"""


class NaturalKeyConflict(Exception):
    """兩個不同 sync_id 搶同一個自然鍵（同一天兩筆體重、同名動作兩份）。

    不自動合併也不覆蓋——PRD R4 說得很清楚，同筆資料的並行修改要讓使用者決定。
    這裡把它退成 conflict，由 F145 的收件匣處理。
    """

    def __init__(self, entity_type: str, existing: Any) -> None:
        super().__init__(f"{entity_type}:{existing.sync_id}")
        self.entity_type = entity_type
        self.existing = existing


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_sync_id() -> str:
    return str(uuid.uuid4())


def ensure_sync_id(row: Any) -> str:
    """新列補一顆 sync_id；既有列（回填前為 NULL）在這裡就地補上，不必等 F155。"""
    if not row.sync_id:
        row.sync_id = new_sync_id()
    return row.sync_id


def _row_by_sync_id(session: Session, entity_type: str, sync_id: str) -> Any | None:
    model = ENTITY_MODELS[entity_type]
    return session.scalar(select(model).where(model.sync_id == sync_id))


def row_for(session: Session, entity_type: str, sync_id: str) -> Any | None:
    """依 sync_id 找 domain row（含已軟刪的）。"""
    return _row_by_sync_id(session, entity_type, sync_id)


def _require_row(session: Session, entity_type: str, sync_id: str) -> Any:
    row = _row_by_sync_id(session, entity_type, sync_id)
    if row is None or row.deleted_at is not None:
        raise MissingReference(f"{entity_type}:{sync_id}")
    return row


def _iso(value: datetime | date_type | None) -> str | None:
    return None if value is None else value.isoformat()


def _weekday_list(value: str | None) -> list[int] | None:
    if not value:
        return None
    return [int(part) for part in value.split(",") if part]


def payload_for(session: Session, entity_type: str, row: Any) -> dict[str, Any]:
    """domain row → sync payload。欄位形狀以 `app/schemas.py` 的 Sync*Payload 為準。"""
    sync_id = ensure_sync_id(row)
    if entity_type == "exercise":
        return {
            "sync_id": sync_id,
            "name_zh": row.name_zh,
            "name_en": row.name_en,
            "muscle_group": row.muscle_group,
            "is_bodyweight": bool(row.is_bodyweight),
        }
    if entity_type == "template":
        items = session.scalars(
            select(TemplateExercise)
            .where(TemplateExercise.template_id == row.id)
            .order_by(TemplateExercise.position)
        ).all()
        exercises = []
        for item in items:
            exercise = session.get(Exercise, item.exercise_id)
            if exercise is None:
                continue
            exercises.append(
                {
                    "exercise_sync_id": ensure_sync_id(exercise),
                    "position": item.position,
                    "default_sets": item.default_sets,
                    "rest_hint_seconds": item.rest_hint_seconds,
                }
            )
        return {
            "sync_id": sync_id,
            "name": row.name,
            "weekdays": _weekday_list(row.weekdays),
            "exercises": exercises,
        }
    if entity_type == "workout":
        template = session.get(Template, row.template_id) if row.template_id else None
        return {
            "sync_id": sync_id,
            "date": _iso(row.date),
            "template_sync_id": ensure_sync_id(template) if template else None,
            "note": row.note,
            "ended_at": _iso(row.ended_at),
            "owner_device_id": row.owner_device_id,
            "lease_generation": row.lease_generation,
        }
    if entity_type == "set":
        workout = session.get(Workout, row.workout_id)
        exercise = session.get(Exercise, row.exercise_id)
        if workout is None or exercise is None:
            raise MissingReference(f"set:{sync_id}")
        return {
            "sync_id": sync_id,
            "client_uuid": row.client_uuid,
            "workout_sync_id": ensure_sync_id(workout),
            "exercise_sync_id": ensure_sync_id(exercise),
            "set_number": row.set_number,
            "weight_kg": row.weight_kg,
            "reps": row.reps,
            "rpe": row.rpe,
            "rest_seconds": row.rest_seconds,
        }
    if entity_type == "body_metric":
        return {
            "sync_id": sync_id,
            "date": _iso(row.date),
            "weight_kg": row.weight_kg,
            "body_fat_pct": row.body_fat_pct,
        }
    if entity_type == "daily_status":
        return {
            "sync_id": sync_id,
            "date": _iso(row.date),
            "energy": row.energy,
            "sleep_quality": row.sleep_quality,
            "note": row.note,
        }
    if entity_type == "setting":
        return {"sync_id": sync_id, "key": row.key, "value": row.value}
    raise ValueError(f"不支援的 sync entity: {entity_type}")


def _parse_date(value: Any) -> date_type:
    return value if isinstance(value, date_type) else date_type.fromisoformat(str(value))


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", ""))


def _natural_key_match(session: Session, entity_type: str, payload: dict[str, Any]) -> Any | None:
    """domain 表的自然鍵（同一天只有一筆體重、動作名唯一…）。含已軟刪的列——
    那些 UNIQUE 約束不是 partial index，軟刪過的列照樣占著位子。"""
    if entity_type == "exercise":
        return session.scalar(
            select(Exercise).where(
                (Exercise.name_zh == payload["name_zh"])
                | (Exercise.name_en == payload["name_en"])
            )
        )
    if entity_type == "body_metric":
        return session.scalar(
            select(BodyMetric).where(BodyMetric.date == _parse_date(payload["date"]))
        )
    if entity_type == "daily_status":
        return session.scalar(
            select(DailyStatus).where(DailyStatus.date == _parse_date(payload["date"]))
        )
    if entity_type == "setting":
        return session.get(AppSetting, payload["key"])
    if entity_type == "set":
        return session.scalar(
            select(WorkoutSet).where(WorkoutSet.client_uuid == payload["client_uuid"])
        )
    return None  # templates／workouts 沒有自然鍵，同名課表本來就可以有兩份


def apply_payload(session: Session, entity_type: str, payload: dict[str, Any]) -> Any:
    """sync payload → domain row（upsert）。回傳寫好的 row，版本由呼叫端設定。"""
    sync_id = str(payload["sync_id"])
    row = _row_by_sync_id(session, entity_type, sync_id)
    model = ENTITY_MODELS[entity_type]
    if row is None:
        # 自然鍵撞到既有列：那多半就是「同一筆資料，兩邊各自建過」——
        # 伺服器先前用 REST 建的種子動作沒有 sync_id，手機推上來的同名動作要認領它，
        # 不能硬插第二列（UNIQUE 會炸），也不能默默覆蓋別人的 sync_id。
        existing = _natural_key_match(session, entity_type, payload)
        if existing is not None:
            if existing.sync_id and existing.sync_id != sync_id:
                raise NaturalKeyConflict(entity_type, existing)
            existing.sync_id = sync_id
            row = existing
    created = row is None
    if created:
        row = model()
        row.sync_id = sync_id
        # 先不 session.add()：欄位還沒填完，任何查詢觸發 autoflush 就會把半空的列送進 DB
        # （NOT NULL 當場炸）。填完再掛進 session。

    if entity_type == "exercise":
        row.name_zh = payload["name_zh"]
        row.name_en = payload["name_en"]
        row.muscle_group = payload["muscle_group"]
        row.is_bodyweight = bool(payload["is_bodyweight"])
    elif entity_type == "template":
        row.name = payload["name"]
        weekdays = payload.get("weekdays")
        row.weekdays = ",".join(str(day) for day in weekdays) if weekdays else None
        # 子項先全部解析完再落地：其中一個動作還沒同步到的話要整筆退成 dependency_missing，
        # 不能先刪掉舊清單才發現寫不完（那會把原本好好的課表清空）
        items = [
            (_require_row(session, "exercise", str(item["exercise_sync_id"])).id, item)
            for item in payload.get("exercises", [])
        ]
        session.add(row)
        session.flush()
        session.query(TemplateExercise).filter(
            TemplateExercise.template_id == row.id
        ).delete()
        for exercise_id, item in items:
            session.add(
                TemplateExercise(
                    template_id=row.id,
                    position=item["position"],
                    exercise_id=exercise_id,
                    default_sets=item["default_sets"],
                    rest_hint_seconds=item.get("rest_hint_seconds"),
                )
            )
    elif entity_type == "workout":
        row.date = _parse_date(payload["date"])
        template_sync_id = payload.get("template_sync_id")
        row.template_id = (
            _require_row(session, "template", str(template_sync_id)).id
            if template_sync_id
            else None
        )
        row.note = payload.get("note")
        row.ended_at = _parse_datetime(payload.get("ended_at"))
        row.owner_device_id = (
            str(payload["owner_device_id"]) if payload.get("owner_device_id") else None
        )
        row.lease_generation = payload.get("lease_generation", 1)
    elif entity_type == "set":
        row.client_uuid = payload["client_uuid"]
        row.workout_id = _require_row(session, "workout", str(payload["workout_sync_id"])).id
        row.exercise_id = _require_row(session, "exercise", str(payload["exercise_sync_id"])).id
        row.set_number = payload["set_number"]
        row.weight_kg = payload["weight_kg"]
        row.reps = payload["reps"]
        row.rpe = payload.get("rpe")
        row.rest_seconds = payload.get("rest_seconds")
    elif entity_type == "body_metric":
        row.date = _parse_date(payload["date"])
        row.weight_kg = payload["weight_kg"]
        row.body_fat_pct = payload.get("body_fat_pct")
    elif entity_type == "daily_status":
        row.date = _parse_date(payload["date"])
        row.energy = payload["energy"]
        row.sleep_quality = payload.get("sleep_quality")
        row.note = payload.get("note")
    elif entity_type == "setting":
        row.key = payload["key"]
        row.value = payload["value"]
    else:
        raise ValueError(f"不支援的 sync entity: {entity_type}")

    row.deleted_at = None
    if created and row not in session:
        session.add(row)
    session.flush()
    return row


def record_write(
    session: Session, entity_type: str, row: Any, *, deleted: bool = False
) -> int:
    """REST／Web 改完 domain row 之後補版本與 change log，回傳新的 server_seq。

    版本掛在 domain row 上（它才是事實來源），`sync_entities` 只是拿來給衝突比對用的鏡射。
    """
    sync_id = ensure_sync_id(row)
    session.flush()
    payload = payload_for(session, entity_type, row)
    now = _now()
    if deleted and row.deleted_at is None:
        row.deleted_at = now
    row.version = (row.version or 0) + 1

    entity = session.scalar(
        select(SyncEntity).where(
            SyncEntity.entity_type == entity_type, SyncEntity.entity_id == sync_id
        )
    )
    if entity is None:
        entity = SyncEntity(
            entity_type=entity_type,
            entity_id=sync_id,
            version=row.version,
            updated_at=now,
            deleted_at=row.deleted_at,
            payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )
        session.add(entity)
    else:
        entity.version = row.version
        entity.updated_at = now
        entity.deleted_at = row.deleted_at
        entity.payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    change = SyncChange(
        schema_version=SCHEMA_VERSION,
        entity_type=entity_type,
        entity_id=sync_id,
        operation="delete" if row.deleted_at else "upsert",
        version=row.version,
        updated_at=now,
        deleted_at=row.deleted_at,
        payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )
    session.add(change)
    session.flush()
    # 高水位要跟著走。漏了的話，下一次 pull 的回滾偵測會把這幾筆 REST 寫入
    # 當成「server sequence 倒退」而停用同步（sync.py::_high_water）。
    state = session.get(SyncState, "server_seq_high_water")
    if state is None:
        session.add(SyncState(key="server_seq_high_water", value=str(change.server_seq)))
    else:
        state.value = str(change.server_seq)
    return change.server_seq
