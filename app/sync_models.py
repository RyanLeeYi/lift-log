from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class SyncEntity(Base):
    __tablename__ = "sync_entities"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class MutationReceipt(Base):
    __tablename__ = "mutation_receipts"

    mutation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class SyncChange(Base):
    __tablename__ = "sync_changes"
    __table_args__ = {"sqlite_autoincrement": True}

    server_seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class SyncState(Base):
    __tablename__ = "sync_state_server"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
