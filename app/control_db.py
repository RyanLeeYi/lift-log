from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.control_models import ControlBase
from app.db import make_engine


def make_control_session_factory(db_path: str) -> sessionmaker[Session]:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine: Engine = make_engine(str(path))
    ControlBase.metadata.create_all(engine)
    with engine.begin() as connection:
        user_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(users)"))
        }
        if user_columns and "sync_server_seq" not in user_columns:
            connection.execute(
                text(
                    "ALTER TABLE users ADD COLUMN sync_server_seq "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            )
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_metadata ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO schema_metadata (key, value) VALUES ('schema_version', '2') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
        )
    return sessionmaker(bind=engine, expire_on_commit=False)
