import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, sessionmaker

from app.db import (
    UserDataUnavailable,
    canonical_user_db_path,
    data_db_size,
    make_engine,
)
from app.services import auth as auth_service

WEB_SESSION_COOKIE = "liftlog_session"
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def require_app_download_auth(request: Request) -> None:
    """F67 legacy token 或 F141 Android access token 都可下載全域 APK。"""
    provided = request.headers.get("Authorization") or ""
    expected = f"Bearer {request.app.state.settings.token}"
    if secrets.compare_digest(provided.encode(), expected.encode()):
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
    provided = request.headers.get("Authorization") or ""
    expected = f"Bearer {request.app.state.settings.token}"
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
