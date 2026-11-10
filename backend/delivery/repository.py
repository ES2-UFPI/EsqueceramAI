"""Acesso a dados da entrega (mesmo padrão dos repositórios existentes)."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.delivery import models as m
from app.models import db, utcnow


class RegistrationTaken(Exception):
    """Matrícula já usada por outro atendente."""


# ------------------------------------------------------------------ matrícula
def get_registration(user_id: int) -> str | None:
    row = db.get(m.AttendantProfile, user_id)
    return row.registration_number if row else None


def set_registration(user_id: int, number: str) -> None:
    row = db.get(m.AttendantProfile, user_id)
    if row:
        row.registration_number, row.updated_at = number, utcnow()
    else:
        db.add(m.AttendantProfile(user_id=user_id, registration_number=number))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise RegistrationTaken(number)


# --------------------------------------------------------------------- entrega
def create_delivery(**fields) -> m.Delivery:
    row = m.Delivery(**fields)
    db.add(row)
    db.commit()
    return row


def get_delivery(delivery_id: int) -> m.Delivery | None:
    return db.get(m.Delivery, delivery_id)


def save(row) -> None:
    row.updated_at = utcnow() if hasattr(row, "updated_at") else None
    db.commit()


def list_deliveries(attendant_id: int | None = None, limit: int = 50) -> list[m.Delivery]:
    stmt = select(m.Delivery).order_by(m.Delivery.created_at.desc(), m.Delivery.id.desc()).limit(limit)
    if attendant_id:
        stmt = stmt.where(m.Delivery.attendant_id == attendant_id)
    return list(db.scalars(stmt))


def deliveries_for_item(item_id: int, statuses=(m.PENDING, m.COMPLETED)) -> list[m.Delivery]:
    return list(db.scalars(select(m.Delivery).where(m.Delivery.item_id == item_id, m.Delivery.status.in_(statuses))))


# ------------------------------------------------------------------- auditoria
def add_event(delivery_id: int, action: str, detail: str = "") -> None:
    db.add(m.DeliveryEvent(delivery_id=delivery_id, action=action, detail=detail))
    db.commit()


def list_events(delivery_id: int) -> list[m.DeliveryEvent]:
    return list(db.scalars(select(m.DeliveryEvent).where(m.DeliveryEvent.delivery_id == delivery_id)
                           .order_by(m.DeliveryEvent.created_at, m.DeliveryEvent.id)))


# ------------------------------------------------------- documento e recibo
def save_document(delivery_id: int, *, mime_type: str, size_bytes: int, sha256: str, data: bytes) -> None:
    db.add(m.DeliveryDocument(delivery_id=delivery_id, mime_type=mime_type, size_bytes=size_bytes, sha256=sha256, data=data))
    db.commit()


def get_document(delivery_id: int) -> m.DeliveryDocument | None:
    return db.execute(select(m.DeliveryDocument).where(m.DeliveryDocument.delivery_id == delivery_id)).scalar_one_or_none()


def save_receipt(delivery_id: int, *, verification_code: str, sha256: str, pdf: bytes) -> None:
    db.add(m.DeliveryReceipt(delivery_id=delivery_id, verification_code=verification_code, sha256=sha256, pdf=pdf))
    db.commit()


def get_receipt(delivery_id: int) -> m.DeliveryReceipt | None:
    return db.execute(select(m.DeliveryReceipt).where(m.DeliveryReceipt.delivery_id == delivery_id)).scalar_one_or_none()
