"""F149／PRD R9：control DB 與每個 active user DB 的每日加密備份。

用法（repo 根目錄）：
    LIFTLOG_BACKUP_KEY=<Fernet key> uv run python scripts/backup.py --dest-dir <備份目的地>

金鑰只吃環境變數 `LIFTLOG_BACKUP_KEY`（Fernet 32-byte urlsafe base64 key），不寫死在程式、
log 或檔名。產生一把新金鑰：
    uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

保留策略：daily 池留最新 7 份、weekly 池留最新 4 份（每週一額外寫入 weekly 池）；
超出份數的舊檔在同一次執行內清除。快照一律用 SQLite `VACUUM INTO`，不直接複製 .db 檔——
這個專案的 DB 開 WAL，直接複製會拿到不一致的資料。

細節與排程建議見 docs/operations.md。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.fernet import Fernet

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.config import Settings  # noqa: E402

KEY_ENV_VAR = "LIFTLOG_BACKUP_KEY"
DAILY_KEEP = 7
WEEKLY_KEEP = 4
WEEKLY_ISOWEEKDAY = 1  # 週一額外進 weekly 池
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


class BackupKeyMissing(RuntimeError):
    pass


def load_key(env: dict[str, str] | None = None) -> bytes:
    source = env if env is not None else os.environ
    raw = source.get(KEY_ENV_VAR)
    if not raw:
        raise BackupKeyMissing(f"{KEY_ENV_VAR} 未設定")
    return raw.encode("ascii")


def discover_sources(control_db_path: Path, user_data_dir: Path) -> dict[str, Path]:
    """回傳 {備份名稱: db 檔路徑}。備份名稱只用檔名（uuid 或 "control"），不含路徑。"""
    sources = {"control": control_db_path}
    if user_data_dir.is_dir():
        for candidate in sorted(user_data_dir.glob("*.db")):
            sources[candidate.stem] = candidate
    return sources


def snapshot_to_temp(db_path: Path, tmp_dir: Path) -> Path:
    """`VACUUM INTO` 產生一致快照，避開 WAL 模式下直接複製檔案拿到半套資料的風險。"""
    snapshot_path = tmp_dir / f"{db_path.stem}.snapshot.db"
    connection = sqlite3.connect(str(db_path), timeout=30)
    try:
        connection.execute("VACUUM INTO ?", (str(snapshot_path),))
    finally:
        connection.close()
    return snapshot_path


def encrypt_file(path: Path, key: bytes) -> bytes:
    return Fernet(key).encrypt(path.read_bytes())


def is_same_disk(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def prune_old_backups(pool_dir: Path, keep: int) -> list[Path]:
    if not pool_dir.is_dir():
        return []
    backups = sorted(pool_dir.glob("*.db.enc"))
    stale = backups[:-keep] if keep > 0 else backups
    for path in stale:
        path.unlink()
    return stale


def write_backup(
    dest_root: Path, name: str, pool: str, timestamp: datetime, payload: bytes
) -> Path:
    pool_dir = dest_root / pool / name
    pool_dir.mkdir(parents=True, exist_ok=True)
    out_path = pool_dir / f"{name}_{timestamp.strftime(TIMESTAMP_FORMAT)}.db.enc"
    out_path.write_bytes(payload)
    return out_path


def run_backup(
    *,
    control_db_path: Path,
    user_data_dir: Path,
    dest_dir: Path,
    key: bytes,
    now: datetime,
) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    weekly = now.isoweekday() == WEEKLY_ISOWEEKDAY

    for source in (control_db_path, user_data_dir):
        if is_same_disk(dest_dir, source):
            print(
                f"[WARN] 備份目的地與來源在同一顆磁碟（{source.name}），"
                "不符合 PRD R9 的磁碟分離要求，仍繼續備份。",
                file=sys.stderr,
            )

    written: list[Path] = []
    with TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for name, db_path in discover_sources(control_db_path, user_data_dir).items():
            if not db_path.is_file():
                continue
            snapshot = snapshot_to_temp(db_path, tmp_dir)
            payload = encrypt_file(snapshot, key)
            snapshot.unlink()

            written.append(write_backup(dest_dir, name, "daily", now, payload))
            if weekly:
                written.append(write_backup(dest_dir, name, "weekly", now, payload))
            prune_old_backups(dest_dir / "daily" / name, DAILY_KEEP)
            prune_old_backups(dest_dir / "weekly" / name, WEEKLY_KEEP)
    return written


def latest_backup(dest_dir: Path, name: str, pool: str = "daily") -> Path | None:
    pool_dir = dest_dir / pool / name
    if not pool_dir.is_dir():
        return None
    backups = sorted(pool_dir.glob("*.db.enc"))
    return backups[-1] if backups else None


def unresolved_source(args: argparse.Namespace) -> str | None:
    """沒有 `.env` 也沒有明講來源時，回一段拒絕理由；其餘情況回 None。

    F161 把正式站搬出 git 工作樹之後，`.env` 也跟著搬走了。`Settings` 讀的是「當下
    工作目錄的 .env」，讀不到就靜靜套用預設的相對路徑（`./control.db`、`./users`）
    ——在 repo 目錄下那兩個路徑剛好是**測試站**的檔案，於是備份 exit 0、印出 [OK]，
    看起來完全成功，備到的卻是開發資料。真正需要備份的那天才會發現。

    所以這裡拒絕執行而不是印警告：這支腳本的正常歸宿是排程工作，警告沒有人會看到。
    要嘛從有 .env 的目錄跑（正式站那一側），要嘛把來源明講出來。
    """
    if args.control_db is not None and args.user_data_dir is not None:
        return None
    if Path(".env").is_file():
        return None
    return (
        "當下目錄沒有 .env，備份來源會落回預設的 ./control.db 與 ./users——"
        "那通常是開發用的檔案，不是正式站。請改從正式站目錄執行"
        "（見 docs/operations.md 第 1b 節），或用 --control-db 與 --user-data-dir 明講來源。"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="F149 每日加密備份：control DB + 每個 active user DB"
    )
    parser.add_argument(
        "--control-db", type=Path, default=None, help="預設讀 Settings.control_db_path"
    )
    parser.add_argument(
        "--user-data-dir", type=Path, default=None, help="預設讀 Settings.user_data_dir"
    )
    parser.add_argument(
        "--dest-dir", type=Path, required=True, help="備份目的地（應與來源不同實體磁碟）"
    )
    parser.add_argument(
        "--now", type=str, default=None, help="ISO8601，補跑/測試用；預設現在 UTC"
    )
    args = parser.parse_args(argv)

    if (missing := unresolved_source(args)) is not None:
        print(f"[ERROR] {missing}", file=sys.stderr)
        return 2

    settings = Settings()
    control_db_path = args.control_db or Path(settings.control_db_path)
    user_data_dir = args.user_data_dir or Path(settings.user_data_dir)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)

    try:
        key = load_key()
    except BackupKeyMissing as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    written = run_backup(
        control_db_path=control_db_path,
        user_data_dir=user_data_dir,
        dest_dir=args.dest_dir,
        key=key,
        now=now,
    )
    for path in written:
        print(f"[OK] {path.relative_to(args.dest_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
