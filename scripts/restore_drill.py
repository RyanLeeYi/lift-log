"""F149／PRD R9：隔離環境 restore drill——解密備份、驗 schema／逐表 row count，且拒絕把
已刪帳號（control DB 的 `account_tombstones`）還原為 active。

用法（repo 根目錄）：
    # 隔離驗證（永遠只還原到 --restore-dir，不動任何 active 檔案）
    LIFTLOG_BACKUP_KEY=<key> uv run python scripts/restore_drill.py \\
        --db control --backup-dir <備份目的地> --restore-dir <暫用資料夾>

    # 有來源 DB 可比對時，一併驗逐表 row count
    LIFTLOG_BACKUP_KEY=<key> uv run python scripts/restore_drill.py \\
        --db <user-uuid> --backup-dir <備份目的地> --restore-dir <暫用資料夾> \\
        --source-db ./users/<user-uuid>.db

    # 只有明確要求才會寫回 active；tombstone 帳號一律拒絕（PRD R7/R9）
    LIFTLOG_BACKUP_KEY=<key> uv run python scripts/restore_drill.py \\
        --db <user-uuid> --backup-dir <備份目的地> --restore-dir <暫用資料夾> \\
        --promote-to-active --active-dir ./users --control-db ./control.db

細節見 docs/operations.md。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from cryptography.fernet import Fernet

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# import 只為觸發 sync_models 掛表到 app.models.Base——data DB 的 schema 才完整
import app.sync_models  # noqa: E402,F401
from app.control_db import make_control_session_factory  # noqa: E402
from app.control_models import ControlBase  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import account as account_service  # noqa: E402
from scripts.backup import KEY_ENV_VAR, latest_backup, load_key  # noqa: E402


class SchemaMismatchError(RuntimeError):
    pass


class RowCountMismatchError(RuntimeError):
    pass


class TombstonedAccountRestoreError(RuntimeError):
    pass


def resolve_expected_tables(db_name: str) -> set[str]:
    metadata = ControlBase.metadata if db_name == "control" else Base.metadata
    return {table.name for table in metadata.sorted_tables}


def decrypt_backup(encrypted_path: Path, key: bytes, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = Fernet(key).decrypt(encrypted_path.read_bytes())
    destination.write_bytes(payload)
    return destination


def table_names(db_path: Path) -> set[str]:
    connection = sqlite3.connect(str(db_path))
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    finally:
        connection.close()
    return {row[0] for row in rows}


def row_counts(db_path: Path, tables: set[str]) -> dict[str, int]:
    connection = sqlite3.connect(str(db_path))
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }
    finally:
        connection.close()


def verify_schema(restored_db: Path, expected_tables: set[str]) -> None:
    missing = expected_tables - table_names(restored_db)
    if missing:
        raise SchemaMismatchError(f"restore 缺少資料表: {sorted(missing)}")


def verify_row_counts(source_db: Path, restored_db: Path, tables: set[str]) -> dict[str, int]:
    source_counts = row_counts(source_db, tables)
    restored_counts = row_counts(restored_db, tables)
    mismatched = {
        table: (source_counts[table], restored_counts[table])
        for table in tables
        if source_counts[table] != restored_counts[table]
    }
    if mismatched:
        raise RowCountMismatchError(f"row count 不一致: {mismatched}")
    return restored_counts


def restore_drill(
    *,
    encrypted_backup: Path,
    key: bytes,
    restore_dir: Path,
    db_name: str,
    source_db: Path | None = None,
) -> dict[str, int] | None:
    """永遠只還原到 `restore_dir`（隔離目錄），驗 schema，有來源時再驗逐表 row count。"""
    expected_tables = resolve_expected_tables(db_name)
    restored_db = decrypt_backup(encrypted_backup, key, restore_dir / f"{db_name}.restored.db")
    verify_schema(restored_db, expected_tables)
    if source_db is not None and source_db.is_file():
        return verify_row_counts(source_db, restored_db, expected_tables)
    return None


def promote_to_active(
    *, restored_db: Path, active_dest: Path, control_db_path: Path, user_id: str
) -> None:
    """把隔離目錄的還原結果寫回 active 位置——tombstone 帳號一律拒絕（PRD R7/R9）。"""
    control_factory = make_control_session_factory(str(control_db_path))
    with control_factory() as control:
        if account_service.is_tombstoned(control, user_id):
            raise TombstonedAccountRestoreError(
                "帳號已刪除（control DB account_tombstones），拒絕還原為 active"
            )
    active_dest.parent.mkdir(parents=True, exist_ok=True)
    active_dest.write_bytes(restored_db.read_bytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="F149 隔離環境 restore drill")
    parser.add_argument("--db", required=True, help='備份名稱："control" 或 user uuid')
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("--restore-dir", required=True, type=Path, help="隔離還原目的地")
    parser.add_argument("--pool", default="daily", choices=["daily", "weekly"])
    parser.add_argument("--backup-file", type=Path, help="指定備份檔而非用最新一份")
    parser.add_argument("--source-db", type=Path, help="有來源時同時比對逐表 row count")
    parser.add_argument(
        "--promote-to-active", action="store_true", help="通過隔離驗證後寫回 active"
    )
    parser.add_argument(
        "--active-dir", type=Path, help="promote 用：active control/user_data 目錄"
    )
    parser.add_argument(
        "--control-db", type=Path, help="promote 用：查 tombstone 的 control DB 路徑"
    )
    args = parser.parse_args(argv)

    try:
        key = load_key()
    except Exception as exc:  # noqa: BLE001 - 對操作者印出缺金鑰原因即可
        print(f"[ERROR] {KEY_ENV_VAR}: {exc}", file=sys.stderr)
        return 1

    backup_file = args.backup_file or latest_backup(args.backup_dir, args.db, args.pool)
    if backup_file is None:
        print(f"[ERROR] 找不到 {args.db} 的備份", file=sys.stderr)
        return 1

    try:
        counts = restore_drill(
            encrypted_backup=backup_file,
            key=key,
            restore_dir=args.restore_dir,
            db_name=args.db,
            source_db=args.source_db,
        )
    except (SchemaMismatchError, RowCountMismatchError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(f"[OK] {args.db} 隔離還原驗證通過" + (f"：{counts}" if counts is not None else ""))

    if args.promote_to_active:
        if not args.active_dir or not args.control_db:
            print("[ERROR] --promote-to-active 需要 --active-dir 與 --control-db", file=sys.stderr)
            return 1
        restored_db = args.restore_dir / f"{args.db}.restored.db"
        active_name = "control.db" if args.db == "control" else f"{args.db}.db"
        try:
            promote_to_active(
                restored_db=restored_db,
                active_dest=args.active_dir / active_name,
                control_db_path=args.control_db,
                user_id=args.db,
            )
        except TombstonedAccountRestoreError as exc:
            print(f"[REFUSED] {exc}", file=sys.stderr)
            return 2
        print(f"[OK] {args.db} 已還原為 active")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
