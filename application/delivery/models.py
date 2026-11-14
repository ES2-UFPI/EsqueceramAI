"""Tabelas novas da entrega com respaldo legal.

Só cria tabelas (nenhuma coluna é adicionada às existentes), então `create_all` basta —
bancos já em uso não precisam de migração. Os dados do item, do ponto e do atendente são
copiados (snapshot) para a entrega: o termo continua íntegro mesmo se o item for excluído
ou o atendente trocar de matrícula.
"""
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from application.models import Base, UTCDateTime, utcnow

PENDING, COMPLETED, CANCELLED, EXPIRED = "PENDING", "COMPLETED", "CANCELLED", "EXPIRED"
STATUSES = (PENDING, COMPLETED, CANCELLED, EXPIRED)


class AttendantProfile(Base):
    """Matrícula do atendente do posto (impressa no termo de entrega)."""
    __tablename__ = "attendant_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    registration_number: Mapped[str] = mapped_column(String(20), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (Index("deliveries_item_idx", "item_id"), Index("deliveries_attendant_idx", "attendant_id"),
                      Index("deliveries_cpf_idx", "recipient_cpf_hash"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # item (snapshot)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    item_code: Mapped[str] = mapped_column(String(20))
    item_title: Mapped[str] = mapped_column(Text)
    point_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    # atendente (snapshot)
    attendant_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    attendant_name: Mapped[str] = mapped_column(Text)
    attendant_registration: Mapped[str] = mapped_column(String(20))
    # retirante: o CPF completo NÃO é guardado, só o HMAC (para conferir em contestações) e a máscara
    recipient_name: Mapped[str] = mapped_column(Text)
    recipient_cpf_hash: Mapped[str] = mapped_column(String(64))
    recipient_cpf_masked: Mapped[str] = mapped_column(String(20))
    recipient_email: Mapped[str] = mapped_column(Text)
    # confirmação por código enviado ao e-mail (só o HMAC do código é guardado)
    status: Mapped[str] = mapped_column(String(12), default=PENDING)
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    code_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    code_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    code_attempts: Mapped[int] = mapped_column(Integer, default=0)
    resend_count: Mapped[int] = mapped_column(Integer, default=0)
    email_delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DeliveryDocument(Base):
    """Imagem do documento com foto do retirante (acesso restrito à equipe)."""
    __tablename__ = "delivery_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"), unique=True)
    mime_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DeliveryReceipt(Base):
    """PDF do termo, gravado uma única vez na conclusão (imutável)."""
    __tablename__ = "delivery_receipts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"), unique=True)
    verification_code: Mapped[str] = mapped_column(String(32))
    sha256: Mapped[str] = mapped_column(String(64))
    pdf: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DeliveryEvent(Base):
    """Trilha de auditoria da entrega."""
    __tablename__ = "delivery_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
