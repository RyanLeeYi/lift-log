"""F12（PRD R10）：舊 DB 的 template_exercises 缺 rest_hint_seconds，啟動時就地補欄位。

create_all 只建新表、不加欄位——正式 DB 是升級上來的，必須有輕量遷移。
"""

from pathlib import Path

from sqlalchemy import text

from app.db import make_engine
from app.migrations import migrate_schema
from app.models import Base


def _legacy_engine(tmp_path: Path):
    """建一顆 F4 時代 schema 的 DB：template_exercises 沒有 rest_hint_seconds。"""
    engine = make_engine(str(tmp_path / "legacy.db"))
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE template_exercises ("
                "template_id INTEGER NOT NULL, position INTEGER NOT NULL, "
                "exercise_id INTEGER NOT NULL, default_sets INTEGER NOT NULL, "
                "PRIMARY KEY (template_id, position))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO template_exercises "
                "(template_id, position, exercise_id, default_sets) VALUES (1, 1, 1, 3)"
            )
        )
    return engine


def _columns(engine, table: str) -> list[str]:
    with engine.begin() as conn:
        return [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))]


def test_adds_rest_hint_column_to_legacy_table(tmp_path: Path) -> None:
    engine = _legacy_engine(tmp_path)
    migrate_schema(engine)
    assert "rest_hint_seconds" in _columns(engine, "template_exercises")


def test_existing_rows_get_null_and_stay_intact(tmp_path: Path) -> None:
    engine = _legacy_engine(tmp_path)
    migrate_schema(engine)
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT template_id, position, exercise_id, default_sets, rest_hint_seconds "
                "FROM template_exercises"
            )
        ).one()
    assert tuple(row) == (1, 1, 1, 3, None)


def test_migrate_is_idempotent_on_current_schema(tmp_path: Path) -> None:
    engine = make_engine(str(tmp_path / "new.db"))
    Base.metadata.create_all(engine)
    migrate_schema(engine)
    migrate_schema(engine)  # 重複跑不得炸（每次啟動都會執行）
    assert "rest_hint_seconds" in _columns(engine, "template_exercises")


def _legacy_workouts_engine(tmp_path: Path):
    """F91 之前的 workouts 表：沒有 ended_at，且已有一筆訓練。"""
    engine = make_engine(str(tmp_path / "legacy_workouts.db"))
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE workouts ("
                "id INTEGER PRIMARY KEY, date DATE NOT NULL, template_id INTEGER, "
                "note VARCHAR, created_at DATETIME)"
            )
        )
        conn.execute(
            text("INSERT INTO workouts (id, date, note) VALUES (1, '2026-07-20', '練腿日')")
        )
    return engine


def test_adds_ended_at_to_legacy_workouts(tmp_path: Path) -> None:
    engine = _legacy_workouts_engine(tmp_path)
    migrate_schema(engine)
    assert "ended_at" in _columns(engine, "workouts")


def test_legacy_workouts_are_not_backfilled_as_ended(tmp_path: Path) -> None:
    """舊訓練一律 NULL＝未結束。回填等於謊稱那些訓練有正常收工。"""
    engine = _legacy_workouts_engine(tmp_path)
    migrate_schema(engine)
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id, note, ended_at FROM workouts")).one()
    assert tuple(row) == (1, "練腿日", None)
