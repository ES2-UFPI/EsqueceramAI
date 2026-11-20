"""Registro e consulta consolidada de logs de auditoria e eventos do sistema."""
from datetime import datetime, time, timezone
from sqlalchemy import select

from application import domain as D
from application.delivery.models import Delivery, DeliveryEvent
from application.models import Item, ItemEvent, Match, MatchNotification, Notification, User, db

LOG_TYPES = ("ITEM", "DELIVERY", "NOTIFICATION", "AUTH", "ADMIN", "POINT", "SYSTEM")
LOG_TYPE_LABEL = {
    "ITEM": "Evento de item",
    "DELIVERY": "Auditoria de entrega",
    "NOTIFICATION": "Notificação de match",
    "AUTH": "Autenticação e conta",
    "ADMIN": "Administração",
    "POINT": "Pontos de coleta",
    "SYSTEM": "Sistema",
}
_PREFIX_TO_TYPE = {
    "[AUTH]": "AUTH",
    "[ADMIN]": "ADMIN",
    "[POINT]": "POINT",
}


def record_audit_log(*, user_id: int, category: str, title: str, body: str, link: str | None = None) -> None:
    """Registra uma ação do sistema na tabela notifications (is_read=True para não gerar alerta)."""
    prefix = f"[{category}] " if category in ("AUTH", "ADMIN", "POINT") else ""
    db.add(Notification(user_id=user_id, type="SYSTEM", title=f"{prefix}{title}", body=body, link=link, is_read=True))
    db.commit()


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


def _classify_system_notification(title: str) -> tuple[str, str]:
    for prefix, log_type in _PREFIX_TO_TYPE.items():
        if title.startswith(prefix):
            return log_type, title[len(prefix):].strip()
    return "SYSTEM", title


def _system_logs(limit: int) -> list[dict]:
    stmt = (
        select(Notification, User.name, User.email)
        .join(User, User.id == Notification.user_id)
        .where(Notification.type == "SYSTEM")
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    )
    rows = []
    for notif, user_name, user_email in db.execute(stmt).all():
        log_type, clean_title = _classify_system_notification(notif.title)
        rows.append({
            "type": log_type,
            "typeLabel": LOG_TYPE_LABEL[log_type],
            "title": clean_title,
            "detail": f"{notif.body} ({user_email})",
            "status": log_type,
            "actor": user_name,
            "createdAt": notif.created_at,
            "link": notif.link or "/painel/admin",
        })
    return rows


def _parse_date_bound(raw: str | None, end_of_day: bool = False) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
    return datetime.combine(parsed, time.max if end_of_day else time.min, tzinfo=timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def list_system_logs(
    log_type: str | None = None,
    q: str | None = None,
    actor: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Retorna logs consolidados com filtros por tipo, responsável, período e busca textual."""
    selected = log_type if log_type in LOG_TYPES else None
    entries: list[dict] = []

    if selected in (None, "ITEM"):
        entries.extend(_item_logs(limit))
    if selected in (None, "DELIVERY"):
        entries.extend(_delivery_logs(limit))
    if selected in (None, "NOTIFICATION"):
        entries.extend(_notification_logs(limit))
    if selected in (None, "AUTH", "ADMIN", "POINT", "SYSTEM"):
        sys_entries = _system_logs(limit)
        if selected in ("AUTH", "ADMIN", "POINT", "SYSTEM"):
            sys_entries = [e for e in sys_entries if e["type"] == selected]
        entries.extend(sys_entries)

    actor_q = (actor or "").strip().lower()
    if actor_q:
        entries = [e for e in entries if actor_q in e["actor"].lower()]

    start_dt = _parse_date_bound(date_from, end_of_day=False)
    end_dt = _parse_date_bound(date_to, end_of_day=True)
    if start_dt:
        entries = [e for e in entries if _ensure_utc(e["createdAt"]) >= start_dt]
    if end_dt:
        entries = [e for e in entries if _ensure_utc(e["createdAt"]) <= end_dt]

    query = (q or "").strip().lower()
    if query:
        entries = [
            e for e in entries
            if query in e["title"].lower()
            or query in e["detail"].lower()
            or query in e["actor"].lower()
            or query in e["status"].lower()
        ]

    entries.sort(key=lambda e: _ensure_utc(e["createdAt"]), reverse=True)
    return entries[:limit]
