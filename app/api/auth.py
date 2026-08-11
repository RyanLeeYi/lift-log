from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.db import canonical_user_db_path, initialize_data_db
from app.schemas import GoogleLoginIn, RefreshIn
from app.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])
WEB_SESSION_COOKIE = "liftlog_session"


class AuthRateLimiter:
    """單一 uvicorn process 的公開登入閘門。

    # ponytail: 單機單 worker 足夠；開始跑多 worker 時改成 control DB/共享 store。
    """

    def __init__(self, limit: int = 10, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._last_cleanup = time.monotonic()

    def retry_after(self, key: str) -> int | None:
        now = time.monotonic()
        with self._lock:
            if now - self._last_cleanup >= self.window_seconds:
                cutoff = now - self.window_seconds
                for stored_key, stored in list(self._attempts.items()):
                    while stored and stored[0] <= cutoff:
                        stored.popleft()
                    if not stored:
                        del self._attempts[stored_key]
                self._last_cleanup = now
            attempts = self._attempts[key]
            while attempts and attempts[0] <= now - self.window_seconds:
                attempts.popleft()
            if len(attempts) >= self.limit:
                return max(1, math.ceil(self.window_seconds - (now - attempts[0])))
            attempts.append(now)
        return None


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if peer in {"127.0.0.1", "::1"}:
        return request.headers.get("CF-Connecting-IP") or peer
    return peer


def _rate_limit(request: Request) -> None:
    retry_after = request.app.state.auth_rate_limiter.retry_after(_client_ip(request))
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )


def _bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    scheme, separator, token = header.partition(" ")
    return token if separator and scheme.lower() == "bearer" and token else None


def _current(request: Request):  # type: ignore[no-untyped-def]
    try:
        return auth_service.resolve_session(
            request.app.state.control_session_factory,
            access_token=_bearer(request),
            web_cookie=request.cookies.get(WEB_SESSION_COOKIE),
        )
    except auth_service.InvalidSession as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized"
        ) from exc


def _out(issued: auth_service.IssuedAuth) -> dict[str, object]:
    return {
        "user": {"id": issued.user.id},
        "device": {"id": issued.device.client_device_id, "name": issued.device.name},
    }


def _recover_user_data_if_available(
    request: Request, issued: auth_service.IssuedAuth
) -> None:
    unavailable = request.app.state.unavailable_user_ids
    if issued.user.id not in unavailable:
        return
    try:
        path = canonical_user_db_path(
            request.app.state.settings.user_data_dir,
            issued.user.id,
            issued.user.data_db_name,
        )
        if not path.is_file():
            return
        initialize_data_db(path)
    except Exception:
        return
    unavailable.discard(issued.user.id)


@router.get("/config")
def auth_config(request: Request) -> dict[str, str]:
    return {"google_client_id": request.app.state.settings.google_client_id}


@router.post("/google")
def google_login(data: GoogleLoginIn, request: Request, response: Response) -> dict[str, object]:
    _rate_limit(request)
    try:
        issued = auth_service.login_with_google(
            request.app.state.control_session_factory,
            request.app.state.settings,
            request.app.state.google_token_verifier,
            data,
        )
    except auth_service.InvalidGoogleToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized"
        ) from exc
    except (auth_service.GoogleVerifierUnavailable, auth_service.AuthUnavailable) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="authentication unavailable",
        ) from exc

    request.app.state.unavailable_user_ids.discard(issued.user.id)
    body = _out(issued)
    if data.client == "web":
        response.set_cookie(
            WEB_SESSION_COOKIE,
            issued.access_token,
            max_age=int(auth_service.WEB_SESSION_TTL.total_seconds()),
            secure=True,
            httponly=True,
            samesite="lax",
            path="/api",
        )
        body["csrf_token"] = issued.csrf_token
        return body
    body.update(
        access_token=issued.access_token,
        expires_in=int(auth_service.ACCESS_TTL.total_seconds()),
        refresh_token=issued.refresh_token,
    )
    return body


@router.post("/refresh")
def refresh(data: RefreshIn, request: Request) -> dict[str, object]:
    try:
        issued = auth_service.refresh_android_session(
            request.app.state.control_session_factory,
            data.refresh_token,
            str(data.device_id),
        )
    except auth_service.InvalidSession as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized"
        ) from exc
    _recover_user_data_if_available(request, issued)
    body = _out(issued)
    body.update(
        access_token=issued.access_token,
        expires_in=int(auth_service.ACCESS_TTL.total_seconds()),
        refresh_token=issued.refresh_token,
    )
    return body


@router.get("/session")
def current_session(request: Request) -> dict[str, object]:
    _auth_session, user, device = _current(request)
    return {
        "user": {"id": user.id},
        "device": {"id": device.client_device_id, "name": device.name},
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> None:
    auth_session, _user, _device = _current(request)
    if request.cookies.get(WEB_SESSION_COOKIE) and not auth_service.csrf_matches(
        auth_session, request.headers.get("X-CSRF-Token")
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf invalid")
    auth_service.revoke_session(request.app.state.control_session_factory, auth_session.id)
    response.delete_cookie(WEB_SESSION_COOKIE, path="/api", secure=True, httponly=True)
