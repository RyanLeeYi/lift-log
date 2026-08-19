"""啟動時的輕量 schema 遷移。

create_all 只建新表、不動既有表——升級上來的正式 DB 缺新欄位時，
在這裡以冪等的 ALTER TABLE 補上。每次啟動都會執行，必須可重複跑。
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.models import IDEM_KEY_UNIQUE_INDEX, SET_NUMBER_UNIQUE_INDEX

DOMAIN_SCHEMA_VERSION = 5

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

# F154：可同步 domain 表的共用欄位。ALTER TABLE 當下既有列的 sync_id 一律 NULL，
# 由 `scripts/backfill_sync.py`（F155）事後補上；version 從 1 起算——舊資料等同「第一版」，不是 0。
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

    # F105 時間型動作。既有動作全部是次數型，所以 mode 給 NOT NULL DEFAULT 'reps'
    # ——不留 NULL，避免每個讀取點都要寫 `mode or 'reps'`。
    ("exercises", "mode", "ALTER TABLE exercises ADD COLUMN mode TEXT NOT NULL DEFAULT 'reps'"),
    # 既有組全部是次數型，duration_seconds 一律 NULL，不回填。
    ("sets", "duration_seconds", "ALTER TABLE sets ADD COLUMN duration_seconds INTEGER"),

]


# F105：時間型的組 reps 必須是 NULL，但既有 DB 的 `sets.reps` 是 INTEGER NOT NULL。
# SQLite 沒有 ALTER COLUMN，唯一的辦法是整表重建（官方 12-step 的簡化版：
# 本 DB 沒有任何表以 sets 為父表，所以不必處理反向 FK 改寫）。
#
# ⚠ created_at 刻意**不**加 NOT NULL，雖然 create_all 對新 DB 會加。理由：F151 之前的
# 舊表允許 created_at 為 NULL，而真的有這種列（tests/test_migration.py 的 legacy fixture
# 就是照實際舊 schema 建的）。重建不該比它取代的那張表更嚴格——那會讓升級直接炸在
# INSERT ... SELECT，而且唯一的「修法」是替使用者捏一個假的建立時間。
#
# 這段只會在「舊 DB 第一次升到 F105」時跑一次；判斷依據是 PRAGMA table_info 的 notnull 旗標，
# 重建完就永遠不會再進來。新建的 DB 由 create_all 直接產出正確 schema，不經過這裡。
_SETS_REBUILD_TABLE = """
CREATE TABLE sets_f105_new (
	id INTEGER NOT NULL,
	client_uuid VARCHAR NOT NULL,
	workout_id INTEGER NOT NULL,
	exercise_id INTEGER NOT NULL,
	set_number INTEGER NOT NULL,
	weight_kg FLOAT NOT NULL,
	reps INTEGER,
	duration_seconds INTEGER,
	rpe INTEGER,
	rest_seconds INTEGER,
	idem_key VARCHAR,
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
	sync_id VARCHAR,
	version INTEGER NOT NULL,
	deleted_at DATETIME,
	PRIMARY KEY (id),
	FOREIGN KEY(workout_id) REFERENCES workouts (id),
	FOREIGN KEY(exercise_id) REFERENCES exercises (id)
)
"""

_SETS_REBUILD_COLUMNS = (
    "id, client_uuid, workout_id, exercise_id, set_number, weight_kg, reps, "
    "duration_seconds, rpe, rest_seconds, idem_key, created_at, sync_id, version, deleted_at"
)

# 重建會 DROP TABLE，所有索引跟著消失，必須原樣補回。
# ⚠ 這份清單要與 app/models.py 的 __table_args__ 和 mapped_column(index=/unique=) 保持一致；
# 少補一條不會報錯，只會安靜失去唯一性保護。
_SETS_REBUILD_INDEXES = (
    "CREATE UNIQUE INDEX ix_sets_client_uuid ON sets (client_uuid)",
    "CREATE INDEX ix_sets_workout_id ON sets (workout_id)",
    "CREATE INDEX ix_sets_exercise_id ON sets (exercise_id)",
    "CREATE UNIQUE INDEX ix_sets_sync_id ON sets (sync_id)",
    f"CREATE UNIQUE INDEX {SET_NUMBER_UNIQUE_INDEX} "
    "ON sets (workout_id, exercise_id, set_number) WHERE deleted_at IS NULL",
    f"CREATE UNIQUE INDEX {IDEM_KEY_UNIQUE_INDEX} "
    "ON sets (idem_key) WHERE idem_key IS NOT NULL AND deleted_at IS NULL",
)


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


def _sets_reps_is_not_null(cursor) -> bool:  # noqa: ANN001 - sqlite3.Cursor
    for row in cursor.execute("PRAGMA table_info(sets)").fetchall():
        if row[1] == "reps":
            return bool(row[3])  # notnull 旗標
    return False


def _sets_fingerprint(cursor) -> tuple:  # noqa: ANN001 - sqlite3.Cursor
    """重建前後的複製保真度指紋：筆數對得上，且欄位沒有被搬錯位置。

    只比筆數不夠——`INSERT ... SELECT` 的欄位順序寫錯時筆數一樣正確，值卻整欄錯位。
    加總與相異鍵數量能抓到那種錯。

    刻意**不**用 `PRAGMA foreign_key_check`：F151 之前的舊表沒有 FK 子句，重建後才有，
    於是既有的孤兒列會在重建後「首次」被報出來，看起來像是這次弄壞的。孤兒資料是另一個
    問題，不該讓一個其實成功的升級 rollback。
    """
    return cursor.execute(
        "SELECT COUNT(*), COUNT(DISTINCT client_uuid), "
        "COALESCE(SUM(reps), -1), COALESCE(SUM(weight_kg), -1), "
        "COALESCE(SUM(set_number), -1), COALESCE(SUM(workout_id), -1) FROM sets"
    ).fetchone()


def _rebuild_sets_for_nullable_reps(engine: Engine) -> None:
    """把既有 DB 的 sets.reps 從 NOT NULL 改成 nullable。已經是 nullable 就整段跳過。

    走 DBAPI 原生連線而不是 SQLAlchemy Connection：`PRAGMA foreign_keys` 在交易內是**無效指令**
    （不報錯、也不生效），而 SQLAlchemy 2.0 一 execute 就 autobegin，沒有「交易外」可用。
    所以這裡改成 autocommit（isolation_level=None）並自己下 BEGIN/COMMIT。
    """
    raw = engine.raw_connection()
    try:
        dbapi = raw.driver_connection
        previous_isolation = dbapi.isolation_level
        dbapi.isolation_level = None  # 自己管交易；否則 DDL 不會被包進去
        cursor = dbapi.cursor()
        try:
            if not _sets_reps_is_not_null(cursor):
                return
            cursor.execute("PRAGMA foreign_keys=OFF")
            fingerprint_before = _sets_fingerprint(cursor)
            try:
                cursor.execute("BEGIN")
                cursor.execute(_SETS_REBUILD_TABLE)
                cursor.execute(
                    f"INSERT INTO sets_f105_new ({_SETS_REBUILD_COLUMNS}) "
                    f"SELECT {_SETS_REBUILD_COLUMNS} FROM sets"
                )
                cursor.execute("DROP TABLE sets")
                cursor.execute("ALTER TABLE sets_f105_new RENAME TO sets")
                for ddl in _SETS_REBUILD_INDEXES:
                    cursor.execute(ddl)
                # 提交前自我檢查：外鍵沒斷、reps 真的可為 NULL。這是不可逆操作，
                # 出事要當場回滾，不要留到使用者記第一組時才發現。
                fingerprint_after = _sets_fingerprint(cursor)
                if fingerprint_after != fingerprint_before:
                    raise RuntimeError(
                        f"F105 sets 重建前後資料不一致：{fingerprint_before} -> {fingerprint_after}"
                    )
                if _sets_reps_is_not_null(cursor):
                    raise RuntimeError("F105 sets 重建後 reps 仍是 NOT NULL")
            except Exception:
                cursor.execute("ROLLBACK")
                raise
            else:
                cursor.execute("COMMIT")
            finally:
                cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
            dbapi.isolation_level = previous_isolation
    finally:
        raw.close()


def migrate_schema(engine: Engine) -> None:
    _add_columns_and_indexes(engine)
    # 欄位補完才重建——新表要把 duration_seconds 一起搬過去。
    _rebuild_sets_for_nullable_reps(engine)
    _stamp_schema_version(engine)


def _add_columns_and_indexes(engine: Engine) -> None:
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


def _stamp_schema_version(engine: Engine) -> None:
    """版本戳最後才寫——中途失敗時 schema_version 要停在舊值，否則下次啟動會以為升級完成了。"""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO schema_metadata (key, value) VALUES ('schema_version', :version) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            ),
            {"version": str(DOMAIN_SCHEMA_VERSION)},
        )
