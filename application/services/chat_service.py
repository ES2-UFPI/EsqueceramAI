import html
from datetime import timedelta
from sqlalchemy import select, update

from application import domain as D
from application.delivery import email_service
from application.delivery.email_service import EmailError, public_url
from application.errors import ApiError, forbidden, not_found
from application.models import MatchChatPresence, MatchMessage, User, db, utcnow
from application.repositories.engagement import create_notifications, find_match_by_id
from application.repositories.items import find_item_by_id
from application.validation import Form

ACTIVE_CHAT_WINDOW = timedelta(seconds=15)


def _found_has_point(match: dict) -> bool:
    found = find_item_by_id(match["found"]["id"])
    return bool(found and found.get("pointId") is not None)


def can_access_match_chat(user: dict | None, match: dict) -> bool:
    if not user or match["status"] != "CONFIRMED":
        return False
    if _found_has_point(match):
        return user["id"] == match["found"]["ownerId"] or user["role"] == "OPERATOR_POST"
    return user["id"] in (match["lost"]["ownerId"], match["found"]["ownerId"])


def _load_authorized_match(user: dict, match_id: int) -> tuple[dict, bool]:
    match = find_match_by_id(match_id)
    if not match:
        raise not_found("Correspondência")
    if match["status"] != "CONFIRMED":
        raise ApiError("O chat só é liberado após confirmar a correspondência.", 409)
    has_point = _found_has_point(match)
    if has_point:
        allowed = user["id"] == match["found"]["ownerId"] or user["role"] == "OPERATOR_POST"
    else:
        allowed = user["id"] in (match["lost"]["ownerId"], match["found"]["ownerId"])
    if not allowed:
        raise forbidden("Apenas os envolvidos na entrega têm acesso a este chat.")
    return match, has_point


def _touch_presence(match_id: int, user_id: int) -> None:
    now = utcnow()
    row = db.execute(
        select(MatchChatPresence).where(
            MatchChatPresence.match_id == match_id,
            MatchChatPresence.user_id == user_id,
        )
    ).scalar_one_or_none()
    if row:
        row.last_seen_at = now
    else:
        db.add(MatchChatPresence(match_id=match_id, user_id=user_id, last_seen_at=now))
    db.execute(
        update(MatchMessage)
        .where(
            MatchMessage.match_id == match_id,
            MatchMessage.sender_id != user_id,
            MatchMessage.read_at.is_(None),
        )
        .values(read_at=now)
    )
    db.commit()


def _is_reading_now(match_id: int, user_id: int, now) -> bool:
    seen = db.scalar(
        select(MatchChatPresence.last_seen_at).where(
            MatchChatPresence.match_id == match_id,
            MatchChatPresence.user_id == user_id,
        )
    )
    if not seen:
        return False
    return (now - D._aware(seen)) <= ACTIVE_CHAT_WINDOW


def _recipients_for_message(match: dict, has_point: bool, sender_id: int) -> list[User]:
    if has_point:
        if sender_id == match["found"]["ownerId"]:
            return list(db.scalars(select(User).where(User.role == "OPERATOR_POST", User.is_active.is_(True))))
        target = db.get(User, match["found"]["ownerId"])
        return [target] if target and target.is_active else []
    other_id = match["found"]["ownerId"] if sender_id == match["lost"]["ownerId"] else match["lost"]["ownerId"]
    target = db.get(User, other_id)
    return [target] if target and target.is_active else []


def _serialize(msg: MatchMessage, sender_name: str, sender_role: str, viewer_id: int) -> dict:
    return {
        "id": msg.id,
        "matchId": msg.match_id,
        "senderId": msg.sender_id,
        "senderName": sender_name,
        "senderRole": D.ROLE_LABEL.get(sender_role, sender_role),
        "body": msg.body,
        "readAt": msg.read_at,
        "createdAt": msg.created_at,
        "isMine": msg.sender_id == viewer_id,
    }


def list_match_messages(user: dict, match_id: int) -> dict:
    _, has_point = _load_authorized_match(user, match_id)
    _touch_presence(match_id, user["id"])
    stmt = (
        select(MatchMessage, User.name, User.role)
        .join(User, User.id == MatchMessage.sender_id)
        .where(MatchMessage.match_id == match_id)
        .order_by(MatchMessage.created_at.asc(), MatchMessage.id.asc())
    )
    messages = [_serialize(msg, name, role, user["id"]) for msg, name, role in db.execute(stmt).all()]
    return {"matchId": match_id, "hasPoint": has_point, "messages": messages}


def send_match_message(user: dict, match_id: int, raw: dict) -> dict:
    match, has_point = _load_authorized_match(user, match_id)
    f = Form(raw)
    f.text("body", min=1, max=500, min_msg="Escreva uma mensagem antes de enviar.", max_msg="Mensagem muito longa (máx. 500 caracteres).")
    data = f.finish()

    now = utcnow()
    recipients = [r for r in _recipients_for_message(match, has_point, user["id"]) if r.id != user["id"]]
    unread_recipients = [r for r in recipients if not _is_reading_now(match_id, r.id, now)]

    row = MatchMessage(
        match_id=match_id,
        sender_id=user["id"],
        body=data["body"],
        read_at=now if recipients and not unread_recipients else None,
        created_at=now,
    )
    db.add(row)
    db.commit()

    if unread_recipients:
        link = f"/correspondencias/{match_id}"
        chat_url = public_url(link)
        item_title = match["found"]["title"]
        create_notifications([{
            "userId": r.id,
            "type": "UPDATE",
            "title": "Nova mensagem no chat da entrega",
            "body": f"{user['name']}: {data['body'][:120]}",
            "link": link,
        } for r in unread_recipients])
        for r in unread_recipients:
            if not r.email:
                continue
            body_txt = (
                f"Olá, {r.name}.\n\n"
                f"{user['name']} enviou uma mensagem sobre a entrega de \"{item_title}\":\n\n"
                f"\"{data['body']}\"\n\n"
                f"Responder no chat: {chat_url}\n"
            )
            body_html = (
                f"<div style=\"font-family:Arial,Helvetica,sans-serif;color:#1f2933;max-width:560px\">"
                f"<h2 style=\"margin:0 0 8px\">Nova mensagem sobre a entrega</h2>"
                f"<p>Olá, {html.escape(r.name)}. <strong>{html.escape(user['name'])}</strong> enviou uma mensagem "
                f"sobre <em>\"{html.escape(item_title)}\"</em>:</p>"
                f"<blockquote style=\"border-left:3px solid #0d5c53;margin:12px 0;padding:8px 12px;background:#f7f7f5\">"
                f"{html.escape(data['body'])}</blockquote>"
                f"<p><a href=\"{html.escape(chat_url)}\" style=\"display:inline-block;background:#0d5c53;color:#fff;"
                f"padding:10px 18px;border-radius:8px;text-decoration:none\">Responder no chat</a></p></div>"
            )
            try:
                email_service.send_email(r.email, f"Nova mensagem sobre a entrega: {item_title} - Esqueceram AI", body_txt, body_html)
            except EmailError:
                pass

    return _serialize(row, user["name"], user["role"], user["id"])
