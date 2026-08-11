from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker


class UserDataUnavailable(Exception):
    pass


def make_engine(db_path: str) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record) -> None:  # type: ignore[no-untyped-def]
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

    return engine


def canonical_user_db_path(user_data_dir: str, user_id: str, db_name: str) -> Path:
    try:
        normalized_id = str(UUID(user_id))
    except ValueError as exc:
        raise UserDataUnavailable from exc
    if db_name != f"{normalized_id}.db":
        raise UserDataUnavailable
    root = Path(user_data_dir).resolve()
    path = (root / db_name).resolve()
    if path.parent != root:
        raise UserDataUnavailable
    return path


def initialize_data_db(path: Path) -> None:
    from app.migrations import migrate_schema
    from app.seed import seed_exercises
    from app.sync_models import SyncEntity

    path.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(str(path))
    try:
        SyncEntity.metadata.create_all(engine)
        migrate_schema(engine)
        with sessionmaker(bind=engine)() as session:
            seed_exercises(session)
    finally:
        engine.dispose()


def data_db_size(path: Path) -> int:
    return sum(
        candidate.stat().st_size
        for candidate in (path, Path(f"{path}-wal"))
        if candidate.is_file()
    )
