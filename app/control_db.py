from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.control_models import ControlBase
from app.db import make_engine


def make_control_session_factory(db_path: str) -> sessionmaker[Session]:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine: Engine = make_engine(str(path))
    ControlBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
