from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.deps import DbSession, SyncIdentity, get_sync_identity
from app.control_models import User
from app.schemas import SyncPullOut, SyncPushIn, SyncPushOut
from app.services import quota as quota_service
from app.services import sync as sync_service

router = APIRouter(prefix="/api/sync", tags=["sync"])
Identity = Annotated[SyncIdentity, Depends(get_sync_identity)]
MAX_PUSH_BYTES = 1024 * 1024


class SyncBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not (
            scope["method"] == "POST" and scope["path"] == "/api/sync/push"
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        try:
            content_length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            content_length = 0
        if content_length > MAX_PUSH_BYTES:
            await self._reject(scope, receive, send)
            return

        received = 0
        messages = []
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_PUSH_BYTES:
                    await self._reject(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                break

        async def replay_receive():  # type: ignore[no-untyped-def]
            if messages:
                return messages.pop(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={"error": "sync_batch_too_large"},
        )
        await response(scope, receive, send)


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="sync_unavailable",
    )


def _sequence_floor(request: Request, user_id: str) -> int:
    with request.app.state.control_session_factory() as control:
        user = control.get(User, user_id)
        if user is None:
            raise _unavailable()
        return user.sync_server_seq


def _advance_sequence_floor(request: Request, user_id: str, server_seq: int) -> None:
    with request.app.state.control_session_factory() as control:
        control.execute(
            update(User)
            .where(User.id == user_id, User.sync_server_seq < server_seq)
            .values(sync_server_seq=server_seq)
        )
        control.commit()


@router.post("/push", response_model=SyncPushOut)
def push(
    request: Request,
    data: SyncPushIn,
    session: DbSession,
    identity: Identity,
) -> SyncPushOut:
    if data.schema_version != sync_service.SCHEMA_VERSION:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="unsupported_schema")
    if str(data.device_id) != identity.device_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="device_mismatch")
    # 先扣再寫：批次太大時寧可整批擋下，也不要先落地才發現超額。
    try:
        quota_service.consume_mutations(
            request.app.state.control_session_factory,
            identity.user_id,
            request.app.state.settings.daily_mutation_limit,
            len(data.mutations),
        )
    except quota_service.DailyMutationQuotaExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="mutation_quota_exceeded",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    try:
        sequence_floor = _sequence_floor(request, identity.user_id)
        try:
            result = SyncPushOut.model_validate(
                sync_service.push(
                    session,
                    data.mutations,
                    sequence_floor=sequence_floor,
                )
            )
        except IntegrityError:
            session.rollback()
            result = SyncPushOut.model_validate(
                sync_service.push(
                    session,
                    data.mutations,
                    sequence_floor=sequence_floor,
                )
            )
        if result.accepted:
            _advance_sequence_floor(
                request,
                identity.user_id,
                max(item.server_seq for item in result.accepted),
            )
        return result
    except sync_service.SequenceRegression as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="sync_sequence_regression",
        ) from exc
    except (OperationalError, OSError) as exc:
        session.rollback()
        raise _unavailable() from exc


@router.get("/pull", response_model=SyncPullOut)
def pull(
    request: Request,
    session: DbSession,
    identity: Identity,
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=1000, ge=1, le=1000),
) -> SyncPullOut:
    try:
        return SyncPullOut.model_validate(
            sync_service.pull(
                session,
                cursor,
                limit,
                sequence_floor=_sequence_floor(request, identity.user_id),
            )
        )
    except sync_service.CursorAhead as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="sync_cursor_ahead",
        ) from exc
    except sync_service.SequenceRegression as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="sync_sequence_regression",
        ) from exc
    except (OperationalError, OSError) as exc:
        session.rollback()
        raise _unavailable() from exc
