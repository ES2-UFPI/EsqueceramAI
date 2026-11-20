"""Consulta consolidada de logs de auditoria e eventos do sistema para administradores."""
from sqlalchemy import select

from application import domain as D
from application.delivery.models import Delivery, DeliveryEvent
from application.models import Item, ItemEvent, Match, MatchNotification, User, db

LOG_TYPES = ("ITEM", "DELIVERY", "NOTIFICATION")
LOG_TYPE_LABEL = {
    "ITEM": "Evento de item",
    "DELIVERY": "Auditoria de entrega",
    "NOTIFICATION": "Notificação de match",
}


def _item_logs(limit: int) -> list[dict]:
    stmt = (
        select(ItemEvent, Item.title, User.name)
        .join(Item, Item.id == ItemEvent.item_id)
        .outerjoin(User, User.id == ItemEvent.actor_id)
        .order_by(ItemEvent.created_at.desc(), ItemEvent.id.desc())
        .limit(limit)
    )
    rows = []
    for ev, item_title, actor_name in db.execute(stmt).all():
        rows.append({
            "type": "ITEM",
            "typeLabel": LOG_TYPE_LABEL["ITEM"],
            "title": f"{D.item_code(ev.item_id)} · {item_title}",
            "detail": ev.note or D.STATUS_LABEL.get(ev.status, ev.status),
            "status": D.STATUS_LABEL.get(ev.status, ev.status),
            "actor": actor_name or "Sistema",
            "createdAt": ev.created_at,
            "link": f"/itens/{ev.item_id}",
        })
    return rows


def _delivery_logs(limit: int) -> list[dict]:
    stmt = (
        select(DeliveryEvent, Delivery.item_id, Delivery.item_code, Delivery.item_title, Delivery.attendant_name)
        .join(Delivery, Delivery.id == DeliveryEvent.delivery_id)
        .order_by(DeliveryEvent.created_at.desc(), DeliveryEvent.id.desc())
        .limit(limit)
    )
    rows = []
    for ev, item_id, item_code, item_title, attendant_name in db.execute(stmt).all():
        code = item_code or (D.item_code(item_id) if item_id else "—")
        rows.append({
            "type": "DELIVERY",
            "typeLabel": LOG_TYPE_LABEL["DELIVERY"],
            "title": f"Entrega #{ev.delivery_id} · {code} ({item_title})",
            "detail": ev.detail or ev.action,
            "status": ev.action,
            "actor": attendant_name or "Atendente",
            "createdAt": ev.created_at,
            "link": f"/painel/entregas/{ev.delivery_id}",
        })
    return rows


def _notification_logs(limit: int) -> list[dict]:
    stmt = (
        select(MatchNotification, User.name, User.email, Match.lost_item_id)
        .join(User, User.id == MatchNotification.user_id)
        .join(Match, Match.id == MatchNotification.match_id)
        .order_by(MatchNotification.created_at.desc(), MatchNotification.id.desc())
        .limit(limit)
    )
    rows = []
    for notif, user_name, user_email, lost_item_id in db.execute(stmt).all():
        detail = f"Canal {notif.channel} para {user_email}"
        if notif.error:
            detail += f" · erro: {notif.error}"
        rows.append({
            "type": "NOTIFICATION",
            "typeLabel": LOG_TYPE_LABEL["NOTIFICATION"],
            "title": f"Match #{notif.match_id} · {D.item_code(lost_item_id)}",
            "detail": detail,
            "status": notif.status,
            "actor": user_name,
            "createdAt": notif.created_at,
            "link": f"/itens/{lost_item_id}",
        })
    return rows


def list_system_logs(log_type: str | None = None, q: str | None = None, limit: int = 100) -> list[dict]:
    """Retorna logs consolidados ordenados do mais recente para o mais antigo."""
    selected = log_type if log_type in LOG_TYPES else None
    fetchers = {
        "ITEM": _item_logs,
        "DELIVERY": _delivery_logs,
        "NOTIFICATION": _notification_logs,
    }
    entries: list[dict] = []
    for key, fn in fetchers.items():
        if selected is None or selected == key:
            entries.extend(fn(limit))

    query = (q or "").strip().lower()
    if query:
        entries = [
            e for e in entries
            if query in e["title"].lower()
            or query in e["detail"].lower()
            or query in e["actor"].lower()
            or query in e["status"].lower()
        ]

    entries.sort(key=lambda e: e["createdAt"], reverse=True)
    return entries[:limit]
