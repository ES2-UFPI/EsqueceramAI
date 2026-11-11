"""Modelo relacional (equivalente a src/db/schema.ts / Drizzle)."""
import os
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer,
                        LargeBinary, String, Text, UniqueConstraint, create_engine)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, scoped_session, sessionmaker
from sqlalchemy.types import TypeDecorator

from application import domain


def utcnow():
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """timestamptz no PostgreSQL; no SQLite garante datetimes com fuso (UTC)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


JSONType = JSON().with_variant(JSONB(), "postgresql")


def _enum(values, name):
    return Enum(*values, name=name, native_enum=True, validate_strings=False)


user_role = _enum(domain.ROLES, "user_role")
record_type = _enum(domain.RECORD_TYPES, "record_type")
item_category = _enum(domain.CATEGORIES, "item_category")
item_status = _enum(domain.STATUSES, "item_status")
match_status = _enum(domain.MATCH_STATUSES, "match_status")
notification_type = _enum(domain.NOTIFICATION_TYPES, "notification_type")
storage_provider = _enum(("SUPABASE", "DATABASE"), "storage_provider")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(user_role, default="USER")
    score: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuthSession(Base):
    __tablename__ = "sessions"
    token: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class CollectionPoint(Base):
    __tablename__ = "collection_points"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    building: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    opening_hours: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (Index("items_type_status_idx", "type", "status"),
                      Index("items_user_idx", "user_id"), Index("items_category_idx", "category"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(record_type)
    category: Mapped[str] = mapped_column(item_category)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[dict] = mapped_column(JSONType, default=dict)
    location: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(item_status, default="OPEN")
    point_id: Mapped[int | None] = mapped_column(ForeignKey("collection_points.id", ondelete="SET NULL"), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ItemImage(Base):
    """Bytes privados da imagem (equivale ao bucket privado do Supabase)."""
    __tablename__ = "item_images"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[str] = mapped_column(storage_provider, default="DATABASE")
    storage_key: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("lost_item_id", "found_item_id", name="matches_pair_unique"),
                      Index("matches_status_idx", "status"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lost_item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    found_item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    score: Mapped[int] = mapped_column(Integer)
    reasons: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(match_status, default="PENDING")
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("notifications_user_idx", "user_id", "is_read"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(notification_type, default="SYSTEM")
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class MatchNotification(Base):
    """Livro-razão de avisos externos (US09): a chave única por match/destinatário/canal garante idempotência."""
    __tablename__ = "match_notifications"
    __table_args__ = (UniqueConstraint("match_id", "user_id", "channel", name="match_notifications_unique"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(Text, default="EMAIL")
    status: Mapped[str] = mapped_column(Text, default="PENDING")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ItemSecret(Base):
    """US04 (#27): detalhe confidencial e pergunta-chave usados para validar a posse.

    Tabela separada de propósito: nenhuma listagem ou serialização de item consulta estes
    campos, então o detalhe nunca vaza por descuido. A resposta é guardada apenas como HMAC.
    """
    __tablename__ = "item_secrets"
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    detail: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    answer_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ItemEvent(Base):
    __tablename__ = "item_events"
    __table_args__ = (Index("item_events_item_idx", "item_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(item_status)
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ------------------------------------------------------------------ engine/sessão
def _database_url() -> str:
    url = os.getenv("DATABASE_URL") or "sqlite:///esqueceram.db"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    # Algumas URLs do Supabase vêm explicitamente com o driver psycopg 3;
    # mantemos esse formato e o declaramos nas dependências do backend.
    return url


engine = create_engine(_database_url(), pool_pre_ping=True,
                       connect_args={"check_same_thread": False} if _database_url().startswith("sqlite") else {})
if engine.dialect.name == "sqlite":
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _fk_on(conn, _):  # SQLite precisa habilitar FKs (ON DELETE CASCADE)
        conn.execute("PRAGMA foreign_keys=ON")

db = scoped_session(sessionmaker(bind=engine, expire_on_commit=False))


def init_db():
    """Equivalente a `drizzle-kit push`: cria as tabelas que ainda não existem."""
    Base.metadata.create_all(engine)
