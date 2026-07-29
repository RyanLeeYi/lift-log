"""啟動時的輕量 schema 遷移。

create_all 只建新表、不動既有表——升級上來的正式 DB 缺新欄位時，
在這裡以冪等的 ALTER TABLE 補上。每次啟動都會執行，必須可重複跑。
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine

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
]


def migrate_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        for table, column, ddl in _COLUMN_MIGRATIONS:
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if existing and column not in existing:
                conn.execute(text(ddl))
