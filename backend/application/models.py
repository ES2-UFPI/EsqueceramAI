"""Modelo relacional (equivalente a src/db/schema.ts / Drizzle)."""
import os
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer,
                        LargeBinary, String, Text, UniqueConstraint, create_engine, inspect, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, scoped_session, sessionmaker
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
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
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

CLAIM_PENDING, CLAIM_VERIFIED, CLAIM_BLOCKED = "PENDING", "VERIFIED", "BLOCKED"
CLAIM_STATUSES = (CLAIM_PENDING, CLAIM_VERIFIED, CLAIM_BLOCKED)

class ItemClaim(Base):
    """US04: tentativa de um usuário provar que é o dono de um item encontrado."""
    __tablename__ = "item_claims"
    __table_args__ = (UniqueConstraint("item_id", "claimant_id", name="item_claims_unique"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    claimant_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(12), default=CLAIM_PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
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

_URL = _database_url()
_PSYCOPG3 = make_url(_URL).get_backend_name() == "postgresql" and make_url(_URL).drivername in (
    "postgresql", "postgresql+psycopg")

# O psycopg 3 prepara um statement após ser executado 5 vezes na mesma conexão e o
# pooler do Supabase (PgBouncer) reaproveita a sessão entre conexões lógicas. Assim o
# nome "_pg3_0" já existe quando outro worker prepara o mesmo statement, e o worker
# morre no boot com DuplicatePreparedStatement. Desligar o preparo resolve na origem.
if _PSYCOPG3:
    _CONNECT_ARGS = {"prepare_threshold": None}
elif _URL.startswith("sqlite"):
    _CONNECT_ARGS = {"check_same_thread": False}
else:
    _CONNECT_ARGS = {}

engine = create_engine(_URL, pool_pre_ping=True, connect_args=_CONNECT_ARGS)
if engine.dialect.name == "sqlite":
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _fk_on(conn, _):  # SQLite precisa habilitar FKs (ON DELETE CASCADE)
        conn.execute("PRAGMA foreign_keys=ON")

class _AtomicSession(Session):
    def commit(self):
        if self.info.get("atomic_depth", 0) > 0:
            self.flush()
            return
        super().commit()

db = scoped_session(sessionmaker(bind=engine, class_=_AtomicSession, expire_on_commit=False))

@contextmanager
def atomic():
    session = db()
    depth = session.info.get("atomic_depth", 0)
    session.info["atomic_depth"] = depth + 1
    try:
        yield
    except BaseException:
        session.info["atomic_depth"] = depth
        if depth == 0:
            session.rollback()
        raise
    session.info["atomic_depth"] = depth
    if depth == 0:
        session.commit()

def _sync_item_status_enum():
    if engine.dialect.name != "postgresql":
        return
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        existing = {row[0] for row in conn.execute(text("SELECT unnest(enum_range(NULL::item_status))::text"))}
        previous = None
        for value in domain.STATUSES:
            if value not in existing:
                position = f" AFTER '{previous}'" if previous else ""  # mesma ordem de um banco novo
                conn.execute(text(f"ALTER TYPE item_status ADD VALUE IF NOT EXISTS '{value}'{position}"))
            previous = value

def _sync_missing_columns():
    """Adiciona colunas que o modelo já declara mas a tabela existente ainda não tem.

    `create_all` só cria tabelas ausentes: um banco em uso (o do Render/Supabase) nunca
    ganha colunas novas. Sem isso, `Item.is_demo` derruba toda leitura de `items` com
    UndefinedColumn. As colunas adicionadas têm default, então as linhas já existentes
    continuam válidas.
    """
    inspector = inspect(engine)
    existentes = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existentes:
                continue
            colunas = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in colunas:
                    continue
                ddl = (f"ALTER TABLE {table.name} ADD COLUMN {column.name} "
                       f"{column.type.compile(dialect=engine.dialect)}")
                if column.server_default is not None:
                    # str vira literal entre aspas: "0" serve para BOOLEAN no PostgreSQL.
                    default = column.server_default.arg
                    ddl += f" DEFAULT {default!r}" if isinstance(default, str) else f" DEFAULT {default}"
                    if not column.nullable:
                        ddl += " NOT NULL"
                conn.execute(text(ddl))


def init_db():
    """Equivalente a `drizzle-kit push`: cria o que falta em banco novo ou já em uso."""
    Base.metadata.create_all(engine)
    _sync_missing_columns()
    _sync_item_status_enum()
