"""F148／PRD R7：匯出、登出後的帳號綁定資料、刪帳。

登出本身沿用既有 `/api/auth/logout`（它已經只憑 Bearer／cookie 解析 session，
不分 android/web），這裡只加「匯出」與「刪帳」兩個新動作。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy.orm import sessionmaker

from app.api.auth import AuthRateLimiter
from app.api.deps import resolve_request_session
from app.db import UserDataUnavailable, canonical_user_db_path, make_engine
from app.schemas import AccountDeleteIn, ReauthIn
from app.services import account as account_service
from app.services import auth as auth_service

router = APIRouter(prefix="/api/account", tags=["account"])
WEB_SESSION_COOKIE = "liftlog_session"


def _current(request: Request):  # type: ignore[no-untyped-def]
    """已登入的 Google user（android／web 皆可）；legacy 單一 token 沒有對應 session，一律 401。"""
    return resolve_request_session(request)


def _check_csrf(request: Request, auth_session) -> None:  # type: ignore[no-untyped-def]
    if request.cookies.get(WEB_SESSION_COOKIE) and not auth_service.csrf_matches(
        auth_session, request.headers.get("X-CSRF-Token")
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf invalid")


def _rate_limit(limiter: AuthRateLimiter, user_id: str) -> None:
    retry_after = limiter.retry_after(user_id)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )


def _reauth(request: Request, user, data: ReauthIn) -> None:  # type: ignore[no-untyped-def]
    try:
        auth_service.verify_recent_google_identity(
            request.app.state.settings,
            request.app.state.google_token_verifier,
            user,
            data.id_token,
            data.nonce,
        )
    except auth_service.InvalidGoogleToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized"
        ) from exc
    except auth_service.GoogleVerifierUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="authentication unavailable",
        ) from exc


@router.post("/export")
def export_account(data: ReauthIn, request: Request) -> dict:
    auth_session, user, _device = _current(request)
    _check_csrf(request, auth_session)
    _rate_limit(request.app.state.export_rate_limiter, user.id)
    _reauth(request, user, data)

    try:
        path = canonical_user_db_path(
            request.app.state.settings.user_data_dir, user.id, user.data_db_name
        )
    except UserDataUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="data unavailable"
        ) from exc
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="data unavailable"
        )

    engine = make_engine(str(path))
    try:
        with sessionmaker(bind=engine)() as session:
            return account_service.export_account_data(session)
    finally:
        engine.dispose()


@router.post("/delete")
def delete_account(data: AccountDeleteIn, request: Request, response: Response) -> dict:
    auth_session, user, _device = _current(request)
    _check_csrf(request, auth_session)
    _rate_limit(request.app.state.account_delete_rate_limiter, user.id)
    _reauth(request, user, data)

    account_service.delete_account(
        request.app.state.control_session_factory, request.app.state.settings, user.id
    )
    response.delete_cookie(WEB_SESSION_COOKIE, path="/api", secure=True, httponly=True)
    return {"status": "deleted"}
