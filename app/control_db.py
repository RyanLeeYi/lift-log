import secrets
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.control_models import ControlBase
from app.db import make_engine

WEB_CSRF_SECRET_KEY = "web_csrf_secret"


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


def ensure_web_csrf_secret(factory: sessionmaker[Session]) -> str:
    """取出（必要時產生）CSRF HMAC 金鑰，重用既有的 `schema_metadata` key-value 表。

    持久化是重點：每次啟動重新亂數等於重啟就把所有 web 使用者踢出去，
    而 CSRF token 是由這把金鑰推導的（`services/auth.csrf_for_session`）。
    金鑰跟 control DB 同生命週期——DB 本來就存 session 與 token hash，
    把金鑰放在別處不會讓那些資料更安全。
    """
    with factory() as control:
        row = control.execute(
            text("SELECT value FROM schema_metadata WHERE key = :key"),
            {"key": WEB_CSRF_SECRET_KEY},
        ).first()
        if row is not None and row[0]:
            return str(row[0])
        generated = secrets.token_urlsafe(32)
        control.execute(
            text(
                "INSERT INTO schema_metadata (key, value) VALUES (:key, :value) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            ),
            {"key": WEB_CSRF_SECRET_KEY, "value": generated},
        )
        control.commit()
        return generated
