"""F155：把 F154 合一之前就存在的資料補進同步層。

domain 表是唯一事實來源（D17），所以回填方向分兩種，且都要走
`app/services/projection.py` 唯一的橋樑，不自己組 payload：

- domain 列缺 `sync_id`／對應 entity → `record_write()` 補 sync_id、SyncEntity、SyncChange（①）
- `sync_entities` 裡沒有對應 domain 列的資料 → `apply_payload()` 投影成 domain row（②）
- 兩邊自然鍵撞在一起但 payload 不同 → domain 版本勝出，重寫 entity 並記進 overridden（④）

用法（repo 根目錄）：
    uv run python scripts/backfill_sync.py --db <user-uuid>.db [--dry-run]

非 dry-run 會先用 `scripts/backup.py` 的 VACUUM INTO 快照備份該 DB，再開始寫入。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.db import make_engine  # noqa: E402
from app.migrations import migrate_schema  # noqa: E402
from app.services import projection  # noqa: E402
from app.sync_models import SyncEntity  # noqa: E402
from scripts.backup import snapshot_to_temp  # noqa: E402


@dataclass
class BackfillSummary:
    backfilled: int = 0
    skipped: int = 0
    projected: int = 0
    overridden: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "backfilled": self.backfilled,
            "skipped": self.skipped,
            "overridden": len(self.overridden),
            "projected": self.projected,
            "unresolved": len(self.unresolved),
            "overridden_detail": self.overridden,
            "unresolved_detail": self.unresolved,
        }


def _reconcile(
    session: Session,
    entity_type: str,
    row: Any,
    entity: SyncEntity,
    summary: BackfillSummary,
) -> None:
    """domain 列與既有 entity 已配對——payload 一致就跳過，不同則 domain 勝出（④）。"""
    domain_payload = projection.payload_for(session, entity_type, row)
    entity_payload = json.loads(entity.payload_json)
    if domain_payload == entity_payload:
        summary.skipped += 1
        return
    summary.overridden.append(
        {"entity_type": entity_type, "sync_id": row.sync_id, "old_payload": entity_payload}
    )
    projection.record_write(session, entity_type, row)


def _process_entity_type(session: Session, entity_type: str, summary: BackfillSummary) -> None:
    model = projection.ENTITY_MODELS[entity_type]
    entities_by_id = {
        entity.entity_id: entity
        for entity in session.scalars(
            select(SyncEntity).where(SyncEntity.entity_type == entity_type)
        )
    }
    linked_ids: set[str] = set()

    # ①＋④：domain 列已有 sync_id → 找對應 entity，缺就補、有就比對決定覆蓋或跳過
    for row in session.scalars(select(model).where(model.sync_id.is_not(None))):
        entity = entities_by_id.get(row.sync_id)
        if entity is None:
            projection.record_write(session, entity_type, row)
            summary.backfilled += 1
            continue
        linked_ids.add(row.sync_id)
        _reconcile(session, entity_type, row, entity, summary)

    # ②＋④：只存在於 sync_entities 的資料 → 依自然鍵找回對應 domain 列，否則投影新列
    for entity_id, entity in entities_by_id.items():
        if entity_id in linked_ids:
            continue
        payload = json.loads(entity.payload_json)
        # 直接沿用 projection.py 既有的自然鍵比對，避免另外拼一份會漂移的規則
        candidate = projection._natural_key_match(session, entity_type, payload)  # noqa: SLF001
        if candidate is not None and candidate.sync_id and candidate.sync_id != entity_id:
            # 自然鍵被另一個 sync_id 佔用：domain 表的 UNIQUE 約束讓兩筆並存在結構上不可能，
            # 所以不投影。但也不能只計進 skipped——那等於靜默丟棄（F145 收件匣只服務
            # push-time conflict，看不到這裡的 skip）。兩邊 payload 都列進明細供人工處理。
            summary.unresolved.append(
                {
                    "entity_type": entity_type,
                    "orphan_sync_id": entity_id,
                    "orphan_payload": payload,
                    "occupied_by_sync_id": candidate.sync_id,
                    "occupied_payload": projection.payload_for(session, entity_type, candidate),
                }
            )
            continue
        if candidate is not None:
            candidate.sync_id = entity_id
            _reconcile(session, entity_type, candidate, entity, summary)
            continue
        try:
            row = projection.apply_payload(session, entity_type, payload)
        except projection.MissingReference:
            summary.skipped += 1  # 依賴的 entity 也不存在，這筆資料本身已經斷鏈
            continue
        row.version = entity.version
        row.deleted_at = entity.deleted_at
        summary.projected += 1

    # ①：從沒被同步層碰過的 domain 列 → 全新回填 sync_id／entity／change
    for row in session.scalars(select(model).where(model.sync_id.is_(None))):
        projection.record_write(session, entity_type, row)
        summary.backfilled += 1


def run_backfill(session: Session) -> BackfillSummary:
    """對一顆已開好的 user data DB session 執行回填。

    呼叫端決定 commit 或 rollback（dry-run 用）。
    """
    summary = BackfillSummary()
    for entity_type in projection.ENTITY_MODELS:
        _process_entity_type(session, entity_type, summary)
    session.flush()
    return summary


def backup_before_run(db_path: Path, now: datetime) -> Path:
    """③ 執行前備份——重用 backup.py 的 VACUUM INTO 一致快照，不重寫備份邏輯。"""
    backup_dir = db_path.parent / "backfill_backups" / now.strftime("%Y%m%dT%H%M%SZ")
    backup_dir.mkdir(parents=True, exist_ok=True)
    return snapshot_to_temp(db_path, backup_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="F155：既有資料回填進同步層")
    parser.add_argument("--db", required=True, type=Path, help="目標 user data DB 路徑")
    parser.add_argument("--dry-run", action="store_true", help="只印摘要，不寫入、不備份")
    args = parser.parse_args(argv)

    if not args.db.is_file():
        print(f"[ERROR] 找不到 {args.db}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("[INFO] --dry-run：略過備份，僅試算摘要")
    else:
        backup_path = backup_before_run(args.db, datetime.now(UTC))
        print(f"[OK] 已備份：{backup_path}")

    engine = make_engine(str(args.db))
    migrate_schema(engine)  # 保險：確保 F154 的 sync_id/version 欄位已存在
    session = sessionmaker(bind=engine)()
    try:
        summary = run_backfill(session)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    finally:
        session.close()
        engine.dispose()

    print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
