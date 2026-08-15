"""F155：既有資料回填進同步層。

四個情境對應 acceptance ①②④與冪等性：domain 列缺 sync_id、sync_entities 裡的孤兒資料、
兩邊 payload 分歧時 domain 勝出、以及連跑兩次第二次全為 skipped。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import make_engine
from app.migrations import migrate_schema
from app.models import Base, BodyMetric, Exercise, Workout
from app.sync_models import SyncChange, SyncEntity
from scripts import backfill_sync
from scripts.backfill_sync import run_backfill


def _build_db(tmp_path: Path) -> Path:
    """空白 domain schema，不灌種子動作——回填筆數才好精準斷言。"""
    db_path = tmp_path / "user.db"
    engine = make_engine(str(db_path))
    Base.metadata.create_all(engine)
    migrate_schema(engine)
    engine.dispose()
    return db_path


def _session(db_path: Path):
    engine = make_engine(str(db_path))
    return engine, sessionmaker(bind=engine)()


def _orphan_workout_payload(sync_id: str) -> dict:
    return {
        "sync_id": sync_id,
        "date": "2026-01-02",
        "template_sync_id": None,
        "note": "只存在同步層的訓練",
        "ended_at": None,
        "owner_device_id": None,
        "lease_generation": 1,
    }


def test_domain_row_without_sync_id_gets_backfilled(tmp_path: Path) -> None:
    db_path = _build_db(tmp_path)
    engine, session = _session(db_path)
    metric = BodyMetric(date=date(2026, 1, 1), weight_kg=80.0)
    session.add(metric)
    session.commit()
    assert metric.sync_id is None

    summary = run_backfill(session)
    session.commit()

    assert summary.backfilled == 1
    assert summary.skipped == 0
    entity = session.scalar(select(SyncEntity).where(SyncEntity.entity_type == "body_metric"))
    assert entity is not None
    assert entity.entity_id == metric.sync_id
    change = session.scalar(select(SyncChange).where(SyncChange.entity_id == metric.sync_id))
    assert change is not None
    assert change.operation == "upsert"
    session.close()
    engine.dispose()


def test_orphan_entity_projects_into_domain_row(tmp_path: Path) -> None:
    db_path = _build_db(tmp_path)
    engine, session = _session(db_path)
    sync_id = str(uuid4())
    session.add(
        SyncEntity(
            entity_type="workout",
            entity_id=sync_id,
            version=1,
            updated_at=datetime(2026, 1, 1),
            deleted_at=None,
            payload_json=json.dumps(
                _orphan_workout_payload(sync_id), ensure_ascii=False, sort_keys=True
            ),
        )
    )
    session.commit()

    summary = run_backfill(session)
    session.commit()

    assert summary.projected == 1
    row = session.scalar(select(Workout).where(Workout.sync_id == sync_id))
    assert row is not None
    assert row.note == "只存在同步層的訓練"
    assert row.version == 1
    session.close()
    engine.dispose()


def test_domain_wins_when_payload_diverges(tmp_path: Path) -> None:
    db_path = _build_db(tmp_path)
    engine, session = _session(db_path)
    exercise = Exercise(
        name_zh="回填測試動作", name_en="BackfillTestLift", muscle_group="胸", is_bodyweight=False
    )
    session.add(exercise)
    session.flush()
    exercise.sync_id = str(uuid4())
    stale_payload = {
        "sync_id": exercise.sync_id,
        "name_zh": exercise.name_zh,
        "name_en": exercise.name_en,
        "muscle_group": "背",  # 跟 domain 目前的值不同——模擬同步層還停在舊值
        "is_bodyweight": False,
    }
    session.add(
        SyncEntity(
            entity_type="exercise",
            entity_id=exercise.sync_id,
            version=1,
            updated_at=datetime(2026, 1, 1),
            deleted_at=None,
            payload_json=json.dumps(stale_payload, ensure_ascii=False, sort_keys=True),
        )
    )
    session.commit()

    summary = run_backfill(session)
    session.commit()

    assert summary.overridden == [
        {"entity_type": "exercise", "sync_id": exercise.sync_id, "old_payload": stale_payload}
    ]
    refreshed = session.scalar(
        select(SyncEntity).where(SyncEntity.entity_id == exercise.sync_id)
    )
    assert json.loads(refreshed.payload_json)["muscle_group"] == "胸", "domain 版本要勝出"
    session.close()
    engine.dispose()


def test_rerunning_backfill_is_idempotent(tmp_path: Path) -> None:
    db_path = _build_db(tmp_path)
    engine, session = _session(db_path)

    # 湊齊①②④三種待處理狀態
    metric = BodyMetric(date=date(2026, 1, 1), weight_kg=80.0)
    session.add(metric)

    orphan_sync_id = str(uuid4())
    session.add(
        SyncEntity(
            entity_type="workout",
            entity_id=orphan_sync_id,
            version=1,
            updated_at=datetime(2026, 1, 1),
            deleted_at=None,
            payload_json=json.dumps(
                _orphan_workout_payload(orphan_sync_id), ensure_ascii=False, sort_keys=True
            ),
        )
    )

    exercise = Exercise(
        name_zh="冪等測試動作", name_en="IdempotentTestLift", muscle_group="背", is_bodyweight=False
    )
    session.add(exercise)
    session.flush()
    exercise.sync_id = str(uuid4())
    session.add(
        SyncEntity(
            entity_type="exercise",
            entity_id=exercise.sync_id,
            version=1,
            updated_at=datetime(2026, 1, 1),
            deleted_at=None,
            payload_json=json.dumps(
                {
                    "sync_id": exercise.sync_id,
                    "name_zh": exercise.name_zh,
                    "name_en": exercise.name_en,
                    "muscle_group": "胸",  # 舊值，跟 domain 現在的「背」不同
                    "is_bodyweight": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
    )
    session.commit()

    first = run_backfill(session)
    session.commit()
    assert first.backfilled == 1
    assert first.projected == 1
    assert len(first.overridden) == 1

    second = run_backfill(session)
    session.commit()
    assert second.backfilled == 0
    assert second.projected == 0
    assert second.overridden == []
    assert second.skipped == 3, "三筆都該已經一致，重跑只會跳過"

    session.close()
    engine.dispose()


def test_orphan_losing_natural_key_race_is_reported_not_dropped(tmp_path: Path) -> None:
    """②例外：自然鍵被別的 sync_id 佔住的孤兒不投影，但要留下明細——F145 收件匣只看
    push-time conflict，看不到這裡，靜默 skip 等於資料蒸發（2026-08-15 獨立驗收抓到）。"""
    db_path = _build_db(tmp_path)
    engine, session = _session(db_path)

    winner = BodyMetric(date=date(2026, 3, 1), weight_kg=80.0)
    session.add(winner)
    session.flush()
    winner.sync_id = str(uuid4())

    loser_sync_id = str(uuid4())
    loser_payload = {
        "sync_id": loser_sync_id,
        "date": "2026-03-01",  # 同一天——body_metrics.date 是 UNIQUE，兩筆不可能並存
        "weight_kg": 91.5,
        "body_fat_pct": None,
    }
    session.add(
        SyncEntity(
            entity_type="body_metric",
            entity_id=loser_sync_id,
            version=1,
            updated_at=datetime(2026, 3, 1),
            deleted_at=None,
            payload_json=json.dumps(loser_payload, ensure_ascii=False, sort_keys=True),
        )
    )
    session.commit()

    summary = run_backfill(session)
    session.commit()

    assert summary.projected == 0
    assert len(summary.unresolved) == 1
    entry = summary.unresolved[0]
    assert entry["orphan_sync_id"] == loser_sync_id
    assert entry["orphan_payload"]["weight_kg"] == 91.5, "落選那筆的原始值不得丟棄"
    assert entry["occupied_by_sync_id"] == winner.sync_id
    assert entry["occupied_payload"]["weight_kg"] == 80.0
    assert summary.as_dict()["unresolved"] == 1

    # 冪等：重跑仍然只報一次，不會憑空多出 domain 列
    again = run_backfill(session)
    session.commit()
    assert len(again.unresolved) == 1
    assert session.scalars(select(BodyMetric)).all() == [winner]

    session.close()
    engine.dispose()


def test_dry_run_prints_summary_without_writing_or_backing_up(tmp_path: Path, capsys) -> None:
    db_path = _build_db(tmp_path)
    engine, session = _session(db_path)
    session.add(BodyMetric(date=date(2026, 1, 1), weight_kg=80.0))
    session.commit()
    session.close()
    engine.dispose()

    exit_code = backfill_sync.main(["--db", str(db_path), "--dry-run"])
    assert exit_code == 0
    assert not (db_path.parent / "backfill_backups").exists()

    engine, session = _session(db_path)
    metric = session.scalar(select(BodyMetric))
    assert metric.sync_id is None, "--dry-run 不該真的寫入"
    session.close()
    engine.dispose()

    output = capsys.readouterr().out
    summary = json.loads(output[output.index("{") :])
    assert summary["backfilled"] == 1


def test_real_run_backs_up_first_then_persists(tmp_path: Path) -> None:
    db_path = _build_db(tmp_path)
    engine, session = _session(db_path)
    session.add(BodyMetric(date=date(2026, 1, 1), weight_kg=80.0))
    session.commit()
    session.close()
    engine.dispose()

    exit_code = backfill_sync.main(["--db", str(db_path)])
    assert exit_code == 0

    backups = list((db_path.parent / "backfill_backups").rglob("*.db"))
    assert backups, "執行前要先備份"

    engine, session = _session(db_path)
    metric = session.scalar(select(BodyMetric))
    assert metric.sync_id is not None, "非 dry-run 要真的寫入"
    session.close()
    engine.dispose()
