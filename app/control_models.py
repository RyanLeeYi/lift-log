from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_uuid() -> str:
    return str(uuid4())


class ControlBase(DeclarativeBase):
    pass


class User(ControlBase):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    data_db_name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    sync_server_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Device(ControlBase):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("user_id", "client_device_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    client_device_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    user: Mapped[User] = relationship()


class AuthSession(ControlBase):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    client: Mapped[str] = mapped_column(String(10), nullable=False)
    family_id: Mapped[str] = mapped_column(String(36), default=new_uuid, nullable=False, index=True)
    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    web_session_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    csrf_token_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User] = relationship()
    device: Mapped[Device] = relationship()


class RefreshToken(ControlBase):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("auth_sessions.id"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)

    session: Mapped[AuthSession] = relationship()
