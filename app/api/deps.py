import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session, sessionmaker

from app.db import (
    UserDataUnavailable,
    canonical_user_db_path,
    data_db_size,
    make_engine,
)
from app.services import auth as auth_service
from app.services import quota as quota_service

WEB_SESSION_COOKIE = "liftlog_session"
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


SLIDING_COOKIE_STATE = "web_session_sliding_cookie"


def issue_web_session_cookie(response: Response, token: str, expires_at: datetime) -> None:
    """F157：把 cookie 的 Max-Age 對齊 DB 的 `access_expires_at`。

    cookie 有它**自己**的到期機制，而且是瀏覽器單方面執行的——Max-Age 一到就直接丟掉，
    不會再送出來，伺服器端的 session 還有多久有效它根本不知道。所以光在 DB 裡把到期
    時間往後推是看不見的：使用者仍會在登入後精確 12 小時被登出。滑動到期必須兩邊
    一起推。

    以 `access_expires_at` 反推 Max-Age（而不是直接用 WEB_SESSION_TTL），是為了讓
    絕對上限自動生效——`resolve_session` 已經用 min() 把它夾在 90 天內了。
    """
    max_age = int((expires_at - auth_service.utcnow()).total_seconds())
    response.set_cookie(
        WEB_SESSION_COOKIE,
        token,
        max_age=max(max_age, 0),
        secure=True,
        httponly=True,
        samesite="lax",
        path="/api",
    )


def resolve_request_session(request: Request):  # type: ignore[no-untyped-def]
    """解析這個請求的 session，並登記 web 端該續發的 cookie。

    F157：**所有** `resolve_session` 的呼叫點都要走這裡。第一版把 cookie 重發寫在
    各個呼叫點上，結果第四個呼叫點（`api/account.py`）漏掉了——只要往後再多一條
    直接呼叫 `resolve_session` 的路由，同一個洞就會複製一份。這裡把「延長 DB」與
    「延長瀏覽器」綁成同一個動作，由 middleware 統一寫進回應，漏不掉。
    """
    try:
        auth_session, user, device = auth_service.resolve_session(
            request.app.state.control_session_factory,
            access_token=_bearer(request),
            web_cookie=request.cookies.get(WEB_SESSION_COOKIE),
        )
    except auth_service.InvalidSession as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized"
        ) from exc
    if auth_session.client == "web":
        setattr(
            request.state,
            SLIDING_COOKIE_STATE,
            (request.cookies[WEB_SESSION_COOKIE], auth_session.access_expires_at),
        )
    return auth_session, user, device


def require_app_download_auth(request: Request) -> None:
    """F67 legacy token 或 F141 Android access token 都可下載全域 APK。"""
    provided = request.headers.get("Authorization") or ""
    if _is_legacy_request(request):
        return
    scheme, separator, token = provided.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    try:
        auth_service.resolve_session(
            request.app.state.control_session_factory,
            access_token=token,
            web_cookie=None,
        )
    except auth_service.InvalidSession as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized"
        ) from exc


def _bearer(request: Request) -> str | None:
    scheme, separator, token = (request.headers.get("Authorization") or "").partition(" ")
    return token if separator and scheme.lower() == "bearer" and token else None


def _is_legacy_request(request: Request) -> bool:
    """F149：`LIFTLOG_TOKEN` 未設＝demo 模式關閉，legacy 路徑整條不存在。

    這個提前 return 不是最佳化——沒有它，未設 token 時 expected 會是 `"Bearer "`，
    任何人送一個空 token 就繞過 CSRF、rate limit、每日配額與 user 隔離。
    """
    configured = request.app.state.settings.token
    if not configured:
        return False
    provided = request.headers.get("Authorization") or ""
    expected = f"Bearer {configured}"
    return secrets.compare_digest(provided.encode(), expected.encode())


def require_domain_auth(request: Request) -> Iterator[None]:
    """Resolve one request to either the pre-cutover DB or one verified user's DB."""
    if _is_legacy_request(request):
        request.state.domain_session_factory = request.app.state.session_factory
        request.state.domain_scope = "legacy"
        request.state.domain_client = "legacy"
        request.state.domain_device_id = None
        yield
        return

    auth_session, user, device = resolve_request_session(request)
    if user.id in request.app.state.unavailable_user_ids:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="data unavailable",
        )

    if (
        request.method in MUTATING_METHODS
        and auth_session.client == "web"
        and not auth_service.csrf_matches(
            auth_session, request.headers.get("X-CSRF-Token")
        )
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf invalid")

    retry_after = request.app.state.domain_rate_limiter.retry_after(
        f"{user.id}:{device.id}"
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        path = canonical_user_db_path(
            request.app.state.settings.user_data_dir,
            user.id,
            user.data_db_name,
        )
    except UserDataUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="data unavailable",
        ) from exc
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="data unavailable",
        )
    if (
        request.method in MUTATING_METHODS
        and data_db_size(path) >= request.app.state.settings.data_db_max_bytes
    ):
        if request.url.path.startswith("/api/sync/"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="sync_unavailable",
            )
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail="data_db_quota_exceeded",
        )

    # sync push 自己按批次筆數扣（一次請求可能帶多筆 mutation），這裡只算 domain API。
    if request.method in MUTATING_METHODS and not request.url.path.startswith("/api/sync/"):
        try:
            quota_service.consume_mutations(
                request.app.state.control_session_factory,
                user.id,
                request.app.state.settings.daily_mutation_limit,
            )
        except quota_service.DailyMutationQuotaExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="mutation_quota_exceeded",
                headers={"Retry-After": str(exc.retry_after)},
            ) from exc

    engine = make_engine(str(path))
    request.state.domain_session_factory = sessionmaker(bind=engine)
    request.state.domain_scope = user.id
    request.state.domain_client = auth_session.client
    request.state.domain_device_id = device.client_device_id
    try:
        yield
    finally:
        engine.dispose()


def get_domain_session(
    request: Request,
    _auth: Annotated[None, Depends(require_domain_auth)],
) -> Iterator[Session]:
    factory: sessionmaker[Session] = request.state.domain_session_factory
    with factory() as session:
        yield session


DbSession = Annotated[Session, Depends(get_domain_session)]


@dataclass(frozen=True)
class SyncIdentity:
    user_id: str
    device_id: str


def get_sync_identity(
    request: Request,
    _auth: Annotated[None, Depends(require_domain_auth)],
) -> SyncIdentity:
    if request.state.domain_client != "android":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
    return SyncIdentity(
        user_id=request.state.domain_scope,
        device_id=request.state.domain_device_id,
    )
