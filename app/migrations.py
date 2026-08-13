"""啟動時的輕量 schema 遷移。

create_all 只建新表、不動既有表——升級上來的正式 DB 缺新欄位時，
在這裡以冪等的 ALTER TABLE 補上。每次啟動都會執行，必須可重複跑。
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.models import IDEM_KEY_UNIQUE_INDEX, SET_NUMBER_UNIQUE_INDEX

DOMAIN_SCHEMA_VERSION = 4

# F154：參與同步的 domain 表。順序無關，但 sets 依賴 workouts/exercises 先存在。
SYNC_TABLES = (
    "exercises", "templates", "workouts", "sets",
    "body_metrics", "daily_status", "app_settings",
)

# (table, column, DDL)——新增欄位一律 nullable，舊資料自然為 NULL
_COLUMN_MIGRATIONS = [
    (
        "template_exercises",
        "rest_hint_seconds",
        "ALTER TABLE template_exercises ADD COLUMN rest_hint_seconds INTEGER",
    ),
    # F80 排程：ISO 星期的逗號字串（"1,3,5"）。舊課表為 NULL＝沒排程
    (
        "templates",
        "weekdays",
        "ALTER TABLE templates ADD COLUMN weekdays TEXT",
    ),
    # F91 結束狀態：舊 workout 一律 NULL＝未結束，不回填（回填等於謊稱那些訓練有正常收工）
    (
        "workouts",
        "ended_at",
        "ALTER TABLE workouts ADD COLUMN ended_at DATETIME",
    ),
    # F151：批次寫入冪等鍵。舊列一律 NULL 且不回填——回填前要先確認舊資料沒有同日同動作
    # 同組號跨 workout 的重複，超出這次範圍（見 app/models.py 的 idem_key 欄位註解）。
    (
        "sets",
        "idem_key",
        "ALTER TABLE sets ADD COLUMN idem_key TEXT",
    ),

# F154：可同步 domain 表的共用欄位。既有列的 sync_id 一律 NULL（回填是 F155），
# version 從 1 起算——舊資料等同「第一版」，不是 0。
    ("exercises", "sync_id", "ALTER TABLE exercises ADD COLUMN sync_id TEXT"),
    (
        "exercises",
        "version",
        "ALTER TABLE exercises ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
    ),
    ("templates", "sync_id", "ALTER TABLE templates ADD COLUMN sync_id TEXT"),
    (
        "templates",
        "version",
        "ALTER TABLE templates ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
    ),
    ("workouts", "sync_id", "ALTER TABLE workouts ADD COLUMN sync_id TEXT"),
    (
        "workouts",
        "version",
        "ALTER TABLE workouts ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
    ),
    ("body_metrics", "sync_id", "ALTER TABLE body_metrics ADD COLUMN sync_id TEXT"),
    (
        "body_metrics",
        "version",
        "ALTER TABLE body_metrics ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
    ),
    ("daily_status", "sync_id", "ALTER TABLE daily_status ADD COLUMN sync_id TEXT"),
    (
        "daily_status",
        "version",
        "ALTER TABLE daily_status ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
    ),
    ("app_settings", "sync_id", "ALTER TABLE app_settings ADD COLUMN sync_id TEXT"),
    (
        "app_settings",
        "version",
        "ALTER TABLE app_settings ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
    ),
    ("workouts", "owner_device_id", "ALTER TABLE workouts ADD COLUMN owner_device_id TEXT"),
    (
        "workouts",
        "lease_generation",
        "ALTER TABLE workouts ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 1",
    ),
    ("sets", "sync_id", "ALTER TABLE sets ADD COLUMN sync_id TEXT"),
    (
        "sets",
        "version",
        "ALTER TABLE sets ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
    ),
    ("exercises", "deleted_at", "ALTER TABLE exercises ADD COLUMN deleted_at TIMESTAMP"),
    ("templates", "deleted_at", "ALTER TABLE templates ADD COLUMN deleted_at TIMESTAMP"),
    ("workouts", "deleted_at", "ALTER TABLE workouts ADD COLUMN deleted_at TIMESTAMP"),
    ("body_metrics", "deleted_at", "ALTER TABLE body_metrics ADD COLUMN deleted_at TIMESTAMP"),
    ("daily_status", "deleted_at", "ALTER TABLE daily_status ADD COLUMN deleted_at TIMESTAMP"),
    ("app_settings", "deleted_at", "ALTER TABLE app_settings ADD COLUMN deleted_at TIMESTAMP"),

]


def _assert_no_duplicate_active_set_numbers(conn) -> None:  # noqa: ANN001 - Connection 型別冗長
    """F133 前置：加唯一約束前，未軟刪列裡不得已存在重複組號，撞到就中止而非靜默略過。"""
    dupes = conn.execute(
        text(
            "SELECT workout_id, exercise_id, set_number, COUNT(*) AS n FROM sets "
            "WHERE deleted_at IS NULL "
            "GROUP BY workout_id, exercise_id, set_number HAVING COUNT(*) > 1"
        )
    ).all()
    if dupes:
        detail = ", ".join(
            f"(workout_id={w}, exercise_id={e}, set_number={n}) x{c}" for w, e, n, c in dupes
        )
        raise RuntimeError(
            f"F133 migration 中止：sets 有重複組號未清理，無法建立唯一約束：{detail}"
        )


def migrate_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_metadata ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
        )
        for table, column, ddl in _COLUMN_MIGRATIONS:
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if existing and column not in existing:
                conn.execute(text(ddl))

        # F133 ①：sets 組號唯一約束（只擋未軟刪列）。create_all 只幫新 DB 建，既有 DB 補在這裡。
        sets_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(sets)"))}
        existing_indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(sets)"))}
        if sets_columns and SET_NUMBER_UNIQUE_INDEX not in existing_indexes:
            _assert_no_duplicate_active_set_numbers(conn)
            conn.execute(
                text(
                    f"CREATE UNIQUE INDEX {SET_NUMBER_UNIQUE_INDEX} "
                    "ON sets (workout_id, exercise_id, set_number) "
                    "WHERE deleted_at IS NULL"
                )
            )

        # F151：idem_key 唯一約束。舊列全為 NULL，partial index 天然滿足唯一性，不必先查重複。
        if sets_columns and IDEM_KEY_UNIQUE_INDEX not in existing_indexes:
            conn.execute(
                text(
                    f"CREATE UNIQUE INDEX {IDEM_KEY_UNIQUE_INDEX} "
                    "ON sets (idem_key) "
                    "WHERE idem_key IS NOT NULL AND deleted_at IS NULL"
                )
            )
        # F154：sync_id 唯一索引。SQLite 的 UNIQUE 容許多個 NULL，所以既有未回填的列不受影響。
        for table in SYNC_TABLES:
            columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if "sync_id" not in columns:
                continue
            conn.execute(
                text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table}_sync_id "
                    f"ON {table} (sync_id)"
                )
            )
        conn.execute(
            text(
                "INSERT INTO schema_metadata (key, value) VALUES ('schema_version', :version) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            ),
            {"version": str(DOMAIN_SCHEMA_VERSION)},
        )
