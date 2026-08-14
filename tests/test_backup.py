"""F149／PRD R9：加密備份保留策略、restore drill 逐表 row count 與 tombstone 拒絕還原。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.control_db import make_control_session_factory
from app.control_models import AccountTombstone, User
from app.db import initialize_data_db
from app.services.auth import utcnow
from scripts.backup import DAILY_KEEP, WEEKLY_KEEP, latest_backup, run_backup
from scripts.restore_drill import (
    TombstonedAccountRestoreError,
    promote_to_active,
    restore_drill,
    row_counts,
)

USER_ID = "11111111-1111-1111-1111-111111111111"
SQLITE_MAGIC = b"SQLite format 3\x00"


def _make_control_db_with_user(path: Path, user_id: str = USER_ID) -> None:
    factory = make_control_session_factory(str(path))
    with factory() as control:
        control.add(
            User(
                id=user_id,
                google_sub=f"sub-{user_id}",
                email="person@example.com",
                data_db_name=f"{user_id}.db",
                created_at=utcnow(),
            )
        )
        control.commit()


def test_backup_file_cannot_be_read_as_plaintext(tmp_path: Path) -> None:
    control_db = tmp_path / "control.db"
    _make_control_db_with_user(control_db)
    key = Fernet.generate_key()

    written = run_backup(
        control_db_path=control_db,
        user_data_dir=tmp_path / "users",
        dest_dir=tmp_path / "backups",
        key=key,
        now=datetime(2026, 1, 5, tzinfo=UTC),
    )

    backup_file = next(p for p in written if p.parent.name == "control")
    raw = backup_file.read_bytes()
    assert not raw.startswith(SQLITE_MAGIC)
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(str(backup_file)).execute("SELECT * FROM users").fetchall()


def test_retention_keeps_seven_daily_and_four_weekly(tmp_path: Path) -> None:
    control_db = tmp_path / "control.db"
    _make_control_db_with_user(control_db)
    dest_dir = tmp_path / "backups"
    key = Fernet.generate_key()

    start = datetime(2026, 1, 5, tzinfo=UTC)  # 週一
    for day_offset in range(40):
        run_backup(
            control_db_path=control_db,
            user_data_dir=tmp_path / "users",
            dest_dir=dest_dir,
            key=key,
            now=start + timedelta(days=day_offset),
        )

    daily_files = sorted((dest_dir / "daily" / "control").glob("*.db.enc"))
    weekly_files = sorted((dest_dir / "weekly" / "control").glob("*.db.enc"))
    assert len(daily_files) == DAILY_KEEP
    assert len(weekly_files) == WEEKLY_KEEP


def test_restore_drill_row_counts_match_source(tmp_path: Path) -> None:
    source_path = tmp_path / "users" / f"{USER_ID}.db"
    initialize_data_db(source_path)  # 灌好 seed exercises，逐表 row count 才有東西可比

    key = Fernet.generate_key()
    dest_dir = tmp_path / "backups"
    run_backup(
        control_db_path=tmp_path / "control.db",  # 尚未存在，backup 只會略過
        user_data_dir=tmp_path / "users",
        dest_dir=dest_dir,
        key=key,
        now=datetime(2026, 1, 5, tzinfo=UTC),
    )

    backup_file = latest_backup(dest_dir, USER_ID, "daily")
    assert backup_file is not None

    restore_dir = tmp_path / "restore_tmp"
    counts = restore_drill(
        encrypted_backup=backup_file,
        key=key,
        restore_dir=restore_dir,
        db_name=USER_ID,
        source_db=source_path,
    )

    assert counts is not None
    assert counts["exercises"] > 0
    assert counts == row_counts(source_path, set(counts))


def test_promote_to_active_writes_file_for_active_user(tmp_path: Path) -> None:
    control_db = tmp_path / "control.db"
    _make_control_db_with_user(control_db)
    restored_db = tmp_path / "restored" / f"{USER_ID}.restored.db"
    restored_db.parent.mkdir(parents=True)
    restored_db.write_bytes(b"restored-db-bytes")
    active_dest = tmp_path / "active_users" / f"{USER_ID}.db"

    promote_to_active(
        restored_db=restored_db,
        active_dest=active_dest,
        control_db_path=control_db,
        user_id=USER_ID,
    )

    assert active_dest.read_bytes() == b"restored-db-bytes"


def test_promote_to_active_rejects_tombstoned_account(tmp_path: Path) -> None:
    control_db = tmp_path / "control.db"
    _make_control_db_with_user(control_db)
    factory = make_control_session_factory(str(control_db))
    with factory() as control:
        control.add(
            AccountTombstone(
                user_id=USER_ID, deleted_at=utcnow(), purge_after=utcnow() + timedelta(days=30)
            )
        )
        control.commit()

    restored_db = tmp_path / "restored" / f"{USER_ID}.restored.db"
    restored_db.parent.mkdir(parents=True)
    restored_db.write_bytes(b"restored-db-bytes")
    active_dest = tmp_path / "active_users" / f"{USER_ID}.db"

    with pytest.raises(TombstonedAccountRestoreError):
        promote_to_active(
            restored_db=restored_db,
            active_dest=active_dest,
            control_db_path=control_db,
            user_id=USER_ID,
        )

    assert not active_dest.exists()
