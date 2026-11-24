from sqlalchemy import select

from application import domain as D
from application.errors import ApiError, forbidden, not_found
from application.models import MatchMessage, User, db
from application.repositories.engagement import create_notifications, find_match_by_id
from application.repositories.items import find_item_by_id
from application.validation import Form


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


def _serialize(msg: MatchMessage, sender_name: str, sender_role: str, viewer_id: int) -> dict:
    return {
        "id": msg.id,
        "matchId": msg.match_id,
        "senderId": msg.sender_id,
        "senderName": sender_name,
        "senderRole": D.ROLE_LABEL.get(sender_role, sender_role),
        "body": msg.body,
        "createdAt": msg.created_at,
        "isMine": msg.sender_id == viewer_id,
    }


def list_match_messages(user: dict, match_id: int) -> dict:
    _, has_point = _load_authorized_match(user, match_id)
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

    row = MatchMessage(match_id=match_id, sender_id=user["id"], body=data["body"])
    db.add(row)
    db.commit()

    recipient_id = None
    if has_point:
        if user["id"] != match["found"]["ownerId"]:
            recipient_id = match["found"]["ownerId"]
    else:
        recipient_id = match["found"]["ownerId"] if user["id"] == match["lost"]["ownerId"] else match["lost"]["ownerId"]
    if recipient_id and recipient_id != user["id"]:
        create_notifications([{
            "userId": recipient_id,
            "type": "UPDATE",
            "title": "Nova mensagem sobre a entrega",
            "body": f"{user['name']}: {data['body'][:120]}",
            "link": f"/correspondencias/{match_id}",
        }])

    return _serialize(row, user["name"], user["role"], user["id"])
