import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_session


def require_token(request: Request) -> None:
    expected = f"Bearer {request.app.state.settings.token}"
    provided = request.headers.get("Authorization") or ""
    if not secrets.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


DbSession = Annotated[Session, Depends(get_session)]
