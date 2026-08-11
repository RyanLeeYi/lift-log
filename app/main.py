from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api import (
    app_release,
    auth,
    body_metrics,
    daily_status,
    exercises,
    push,
    schedule,
    stats,
    sync,
    templates,
    workouts,
)
from app.api import (
    settings as settings_api,
)
from app.config import Settings
from app.control_db import make_control_session_factory
from app.control_models import User
from app.db import canonical_user_db_path, initialize_data_db, make_engine
from app.errors import register_error_handlers
from app.mcp import create_mcp
from app.migrations import migrate_schema
from app.models import Base
from app.seed import seed_exercises
from app.services.auth import GoogleTokenVerifier, google_verifier

STATIC_DIR = Path(__file__).parent / "static"
MCP_MOUNT = "/mcp"  # middleware 的路徑改寫與 mount 共用，兩處不得漂移

# F61 ⑧：Capacitor 原生殼的 WebView origin。打包版資產由 APK 內載入，
# 與公開站不同源，故需 CORS；web 版仍是同源請求，不受影響。
# 白名單寫死兩個值即可——**不得改成萬用字元**，那等於任何網頁都能帶著使用者的
# 瀏覽器打這個 API（單人系統只靠 Bearer token 擋，沒有第二道防線）。
CAPACITOR_ORIGINS = [
    "https://localhost",  # Capacitor 8 Android 預設 scheme
    "capacitor://localhost",  # 舊版／iOS 沿用
]


def create_app(
    settings: Settings,
    google_token_verifier: GoogleTokenVerifier | None = None,
) -> FastAPI:
    if not settings.token:
        raise ValueError("LIFTLOG_TOKEN is required")

    engine = make_engine(settings.db_path)
    Base.metadata.create_all(engine)
    migrate_schema(engine)
    session_factory = sessionmaker(bind=engine)
    control_session_factory = make_control_session_factory(settings.control_db_path)
    with control_session_factory() as control:
        users = list(control.scalars(select(User).where(User.status != "closed")))
    unavailable_user_ids: set[str] = set()
    for user in users:
        try:
            path = canonical_user_db_path(
                settings.user_data_dir, user.id, user.data_db_name
            )
            if not path.is_file():
                raise RuntimeError
            initialize_data_db(path)
        except Exception:
            unavailable_user_ids.add(user.id)

    # MCP 先建：FastAPI 必須接 mcp_app.lifespan，session manager 才會初始化
    mcp_app = create_mcp(session_factory, settings.token).http_app(path="/")

    app = FastAPI(title="lift-log", lifespan=mcp_app.lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.control_session_factory = control_session_factory
    app.state.unavailable_user_ids = unavailable_user_ids
    app.state.google_token_verifier = google_token_verifier or google_verifier(
        settings.google_client_id
    )
    app.state.auth_rate_limiter = auth.AuthRateLimiter()
    app.state.domain_rate_limiter = auth.AuthRateLimiter(limit=120)

    app.add_middleware(sync.SyncBodyLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CAPACITOR_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    )

    @app.middleware("http")
    async def normalize_mcp_path(request, call_next):  # type: ignore[no-untyped-def]
        # connector 常用無尾斜線的 /mcp；不改寫會掉進靜態檔 mount 變 405
        if request.scope["path"] == MCP_MOUNT:
            request.scope["path"] = f"{MCP_MOUNT}/"
        return await call_next(request)

    @app.middleware("http")
    async def sw_no_edge_cache(request, call_next):  # type: ignore[no-untyped-def]
        # PWA 更新靠 sw.js 換版觸發；被 CDN 邊緣快取（Cloudflare 預設 4h）會讓部署
        # 延遲整個 TTL 才到手機。只針對 sw.js——其餘殼資產由 SW 的 CACHE_NAME 版本管理
        response = await call_next(request)
        if request.scope["path"] == "/sw.js":
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/health")
    def health() -> dict:
        # mission-control 健康檢查：無 auth（不吐資料）、實際探 DB——靜態 / 反映不了 DB 壞掉
        with session_factory() as session:
            session.execute(select(1))
        # F93：env 也從這裡出——前端在還沒有 token 時就要能顯示「測試環境」，
        # 而 /health 是唯一免 auth 的端點。只吐一個 prod/dev 字串，不涉及資料。
        return {"status": "ok", "env": settings.env_label}

    register_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(workouts.router)
    app.include_router(exercises.router)
    app.include_router(stats.router)
    app.include_router(templates.router)
    app.include_router(body_metrics.router)
    app.include_router(daily_status.router)
    app.include_router(push.router)
    app.include_router(schedule.router)  # F80：今天排到什麼＋本週進度
    app.include_router(settings_api.router)  # F80：每週目標天數等設定
    app.include_router(sync.router)
    app.include_router(app_release.router)  # F67：app 版自我更新的版本查詢與 APK 供檔
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
