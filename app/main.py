from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api import exercises, stats, templates, workouts
from app.config import Settings
from app.db import make_engine
from app.errors import register_error_handlers
from app.mcp import create_mcp
from app.models import Base
from app.seed import seed_exercises

STATIC_DIR = Path(__file__).parent / "static"
MCP_MOUNT = "/mcp"  # middleware 的路徑改寫與 mount 共用，兩處不得漂移


def create_app(settings: Settings) -> FastAPI:
    if not settings.token:
        raise ValueError("LIFTLOG_TOKEN is required")

    engine = make_engine(settings.db_path)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    # MCP 先建：FastAPI 必須接 mcp_app.lifespan，session manager 才會初始化
    mcp_app = create_mcp(session_factory, settings.token).http_app(path="/")

    app = FastAPI(title="lift-log", lifespan=mcp_app.lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory

    @app.middleware("http")
    async def normalize_mcp_path(request, call_next):  # type: ignore[no-untyped-def]
        # connector 常用無尾斜線的 /mcp；不改寫會掉進靜態檔 mount 變 405
        if request.scope["path"] == MCP_MOUNT:
            request.scope["path"] = f"{MCP_MOUNT}/"
        return await call_next(request)

    @app.get("/health")
    def health() -> dict:
        # mission-control 健康檢查：無 auth（不吐資料）、實際探 DB——靜態 / 反映不了 DB 壞掉
        with session_factory() as session:
            session.execute(select(1))
        return {"status": "ok"}

    register_error_handlers(app)
    app.include_router(workouts.router)
    app.include_router(exercises.router)
    app.include_router(stats.router)
    app.include_router(templates.router)
    app.mount(MCP_MOUNT, mcp_app)
    # 靜態 PWA 不擋 token（資料靠 API token 保護）；最後掛載避免吃掉 /api/* 與 /mcp
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
