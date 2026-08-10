import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.services import auth as auth_service


def require_token(request: Request) -> None:
    expected = f"Bearer {request.app.state.settings.token}"
    provided = request.headers.get("Authorization") or ""
    if not secrets.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


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


DbSession = Annotated[Session, Depends(get_session)]
