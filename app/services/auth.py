from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.control_models import AccountTombstone, AuthSession, Device, RefreshToken, User, new_uuid
from app.db import canonical_user_db_path, initialize_data_db
from app.schemas import GoogleLoginIn

ACCESS_TTL = timedelta(minutes=15)
WEB_SESSION_TTL = timedelta(hours=12)
REFRESH_IDLE_TTL = timedelta(days=30)
REFRESH_ABSOLUTE_TTL = timedelta(days=90)

GoogleTokenVerifier = Callable[[str], dict[str, Any]]


class InvalidGoogleToken(Exception):
    pass


class GoogleVerifierUnavailable(Exception):
    pass


class AuthUnavailable(Exception):
    pass


class InvalidSession(Exception):
    pass


@dataclass(frozen=True)
class IssuedAuth:
    user: User
    device: Device
    session: AuthSession
    access_token: str
    refresh_token: str | None
    csrf_token: str | None


def utcnow() -> datetime:
    # SQLite stores naive datetimes; every value in control.db is UTC by convention.
    return datetime.now(UTC).replace(tzinfo=None)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(48)


def create_user_data_db(path: Path) -> None:
    initialize_data_db(path)


def google_verifier(audience: str) -> GoogleTokenVerifier:
    if not audience:
        def missing_config(_raw_token: str) -> dict[str, Any]:
            raise GoogleVerifierUnavailable

        return missing_config

    import requests
    from cachecontrol import CacheControl
    from google.auth import exceptions as google_exceptions
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token as google_id_token

    request = google_requests.Request(session=CacheControl(requests.Session()))

    def verify(raw_token: str) -> dict[str, Any]:
        try:
            return dict(google_id_token.verify_oauth2_token(raw_token, request, audience))
        except google_exceptions.TransportError as exc:
            raise GoogleVerifierUnavailable from exc
        except (google_exceptions.GoogleAuthError, ValueError) as exc:
            raise InvalidGoogleToken from exc

    return verify


def validate_claims(claims: dict[str, Any], settings: Settings, nonce: str) -> tuple[str, str]:
    now = int(datetime.now(UTC).timestamp())
    issuer = claims.get("iss")
    valid = (
        claims.get("aud") == settings.google_client_id
        and issuer in {"accounts.google.com", "https://accounts.google.com"}
        and isinstance(claims.get("exp"), (int, float))
        and claims["exp"] > now
        and isinstance(claims.get("nonce"), str)
        and secrets.compare_digest(claims["nonce"], nonce)
        and claims.get("email_verified") is True
        and isinstance(claims.get("sub"), str)
        and bool(claims["sub"])
        and isinstance(claims.get("email"), str)
        and bool(claims["email"])
    )
    if not valid:
        raise InvalidGoogleToken
    return claims["sub"], claims["email"]


def verify_recent_google_identity(
    settings: Settings,
    verifier: GoogleTokenVerifier,
    user: User,
    id_token: str,
    nonce: str,
) -> None:
    """F148／PRD R7：匯出／刪帳前的近期身分重驗。

    重用登入的 claims 驗證（exp／nonce／email_verified 全套照舊），多一條：
    驗出來的 sub 必須對得上「目前這個已登入的 user」，不能拿別人的有效 id_token 幫你重驗。
    """
    claims = verifier(id_token)
    sub, _email = validate_claims(claims, settings, nonce)
    if sub != user.google_sub:
        raise InvalidGoogleToken


def _user_is_active(db: Session, user: User) -> bool:
    return user.status == "active" and db.get(AccountTombstone, user.id) is None


def login_with_google(
    factory: sessionmaker[Session],
    settings: Settings,
    verifier: GoogleTokenVerifier,
    data: GoogleLoginIn,
) -> IssuedAuth:
    claims = verifier(data.id_token)
    google_sub, email = validate_claims(claims, settings, data.nonce)
    now = utcnow()
    client_device_id = str(data.device_id)
    created_db: Path | None = None

    with factory() as db:
        try:
            user = db.scalar(select(User).where(User.google_sub == google_sub))
            if user is None:
                user_id = new_uuid()
                data_db_name = f"{user_id}.db"
                created_db = Path(settings.user_data_dir).resolve() / data_db_name
                create_user_data_db(created_db)
                user = User(
                    id=user_id,
                    google_sub=google_sub,
                    email=email,
                    data_db_name=data_db_name,
                    created_at=now,
                )
                db.add(user)
                db.flush()
            else:
                if not _user_is_active(db, user):
                    raise InvalidGoogleToken
                expected_path = canonical_user_db_path(
                    settings.user_data_dir, user.id, user.data_db_name
                )
                if not expected_path.is_file():
                    raise AuthUnavailable
                initialize_data_db(expected_path)
                user.email = email

            device = db.scalar(
                select(Device).where(
                    Device.user_id == user.id,
                    Device.client_device_id == client_device_id,
                )
            )
            if device is None:
                device = Device(
                    user_id=user.id,
                    client_device_id=client_device_id,
                    name=data.device_name,
                    created_at=now,
                    last_seen_at=now,
                )
                db.add(device)
                db.flush()
            else:
                device.name = data.device_name
                device.last_seen_at = now

            access_token = new_token()
            refresh_token = new_token() if data.client == "android" else None
            expires_at = now + (ACCESS_TTL if data.client == "android" else WEB_SESSION_TTL)
            auth_session = AuthSession(
                user_id=user.id,
                device_id=device.id,
                client=data.client,
                access_token_hash=token_hash(access_token),
                access_expires_at=expires_at,
                web_session_hash=token_hash(access_token) if data.client == "web" else None,
                created_at=now,
                last_seen_at=now,
            )
            db.add(auth_session)
            db.flush()
            csrf_token = (
                csrf_for_session(settings.token, auth_session.id)
                if data.client == "web"
                else None
            )
            if csrf_token:
                auth_session.csrf_token_hash = token_hash(csrf_token)
            if refresh_token:
                db.add(
                    RefreshToken(
                        session_id=auth_session.id,
                        token_hash=token_hash(refresh_token),
                        created_at=now,
                        idle_expires_at=now + REFRESH_IDLE_TTL,
                        absolute_expires_at=now + REFRESH_ABSOLUTE_TTL,
                    )
                )
            db.commit()
            return IssuedAuth(
                user=user,
                device=device,
                session=auth_session,
                access_token=access_token,
                refresh_token=refresh_token,
                csrf_token=csrf_token,
            )
        except (InvalidGoogleToken, GoogleVerifierUnavailable, AuthUnavailable):
            db.rollback()
            if created_db:
                created_db.unlink(missing_ok=True)
            raise
        except Exception as exc:
            db.rollback()
            if created_db:
                created_db.unlink(missing_ok=True)
            raise AuthUnavailable from exc


def _revoke_family(db: Session, family_id: str, now: datetime) -> None:
    session_ids = list(
        db.scalars(select(AuthSession.id).where(AuthSession.family_id == family_id))
    )
    db.execute(
        update(AuthSession)
        .where(AuthSession.family_id == family_id)
        .values(revoked_at=now)
    )
    if session_ids:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.session_id.in_(session_ids))
            .values(status="revoked")
        )


def refresh_android_session(
    factory: sessionmaker[Session], raw_refresh_token: str, client_device_id: str
) -> IssuedAuth:
    now = utcnow()
    with factory() as db:
        refresh = db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash(raw_refresh_token))
        )
        if refresh is None:
            raise InvalidSession
        auth_session = db.get(AuthSession, refresh.session_id)
        if auth_session is None:
            raise InvalidSession
        device = db.get(Device, auth_session.device_id)
        user = db.get(User, auth_session.user_id)
        if device is None or user is None or device.client_device_id != client_device_id:
            raise InvalidSession
        if not _user_is_active(db, user):
            _revoke_family(db, auth_session.family_id, now)
            db.commit()
            raise InvalidSession
        if refresh.status != "active":
            _revoke_family(db, auth_session.family_id, now)
            db.commit()
            raise InvalidSession
        if (
            auth_session.revoked_at is not None
            or refresh.idle_expires_at <= now
            or refresh.absolute_expires_at <= now
        ):
            _revoke_family(db, auth_session.family_id, now)
            db.commit()
            raise InvalidSession

        refresh.status = "used"
        refresh.used_at = now
        access_token = new_token()
        next_refresh_token = new_token()
        auth_session.access_token_hash = token_hash(access_token)
        auth_session.access_expires_at = now + ACCESS_TTL
        auth_session.last_seen_at = now
        device.last_seen_at = now
        db.add(
            RefreshToken(
                session_id=auth_session.id,
                token_hash=token_hash(next_refresh_token),
                created_at=now,
                idle_expires_at=min(now + REFRESH_IDLE_TTL, refresh.absolute_expires_at),
                absolute_expires_at=refresh.absolute_expires_at,
            )
        )
        db.commit()
        return IssuedAuth(
            user=user,
            device=device,
            session=auth_session,
            access_token=access_token,
            refresh_token=next_refresh_token,
            csrf_token=None,
        )


def resolve_session(
    factory: sessionmaker[Session], *, access_token: str | None, web_cookie: str | None
) -> tuple[AuthSession, User, Device]:
    raw_token = access_token or web_cookie
    if not raw_token:
        raise InvalidSession
    digest = token_hash(raw_token)
    where = (
        AuthSession.access_token_hash == digest
        if access_token
        else AuthSession.web_session_hash == digest
    )
    now = utcnow()
    with factory() as db:
        auth_session = db.scalar(select(AuthSession).where(where))
        if (
            auth_session is None
            or (access_token is not None and auth_session.client != "android")
            or auth_session.revoked_at is not None
            or auth_session.access_expires_at <= now
        ):
            raise InvalidSession
        user = db.get(User, auth_session.user_id)
        device = db.get(Device, auth_session.device_id)
        if user is None or device is None or not _user_is_active(db, user):
            raise InvalidSession
        auth_session.last_seen_at = now
        device.last_seen_at = now
        db.commit()
        return auth_session, user, device


def csrf_matches(auth_session: AuthSession, raw_csrf: str | None) -> bool:
    return bool(
        raw_csrf
        and auth_session.csrf_token_hash
        and secrets.compare_digest(auth_session.csrf_token_hash, token_hash(raw_csrf))
    )


def csrf_for_session(secret: str, session_id: str) -> str:
    """CSRF token 由 session id 推導，不另外亂數產生。

    server 只存 hash，隨機值一旦回應送出去就再也拿不回來——網頁重整後 cookie 還在、
    token 卻沒了，所有寫入都會 403。推導值可以重算，重整與新分頁都拿得到同一顆，
    也不必為此改 schema 或改成「每次讀就換一顆」（換一顆會讓其他分頁立刻失效）。
    """
    return hmac.new(secret.encode(), session_id.encode(), hashlib.sha256).hexdigest()


def revoke_session(factory: sessionmaker[Session], session_id: str) -> None:
    now = utcnow()
    with factory() as db:
        auth_session = db.get(AuthSession, session_id)
        if auth_session is None:
            return
        _revoke_family(db, auth_session.family_id, now)
        db.commit()
