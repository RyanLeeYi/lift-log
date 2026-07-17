from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import sessionmaker

from app.api import exercises, stats, workouts
from app.config import Settings
from app.db import make_engine
from app.errors import register_error_handlers
from app.models import Base
from app.seed import seed_exercises

STATIC_DIR = Path(__file__).parent / "static"


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
    app.include_router(stats.router)
    # 靜態 PWA 不擋 token（資料靠 API token 保護）；最後掛載避免吃掉 /api/*
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def app_with_seed(settings: Settings) -> FastAPI:
    """正式啟動用：建 app 並補種動作庫（冪等）。"""
    app = create_app(settings)
    with app.state.session_factory() as session:
        seed_exercises(session)
    return app


def app_factory() -> FastAPI:
    """uvicorn 入口：`uv run uvicorn app.main:app_factory --factory`（設定讀 .env／環境變數）。"""
    return app_with_seed(Settings())
