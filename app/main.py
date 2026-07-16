from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app.api import exercises, workouts
from app.config import Settings
from app.db import make_engine
from app.errors import register_error_handlers
from app.models import Base


def create_app(settings: Settings) -> FastAPI:
    if not settings.token:
        raise ValueError("LIFTLOG_TOKEN is required")

    engine = make_engine(settings.db_path)
    Base.metadata.create_all(engine)

    app = FastAPI(title="lift-log")
    app.state.settings = settings
    app.state.session_factory = sessionmaker(bind=engine)

    register_error_handlers(app)
    app.include_router(workouts.router)
    app.include_router(exercises.router)
    return app


def app_factory() -> FastAPI:
    """uvicorn 入口：`uv run uvicorn app.main:app_factory --factory`（設定讀 .env／環境變數）。"""
    return create_app(Settings())
