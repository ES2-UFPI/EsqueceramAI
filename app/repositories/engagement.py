"""Matches, notificações e histórico de eventos (src/server/repositories/engagement.ts)."""
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import aliased

from app.models import Item, ItemEvent, ItemImage, Match, Notification, User, db, utcnow

LI, FI = aliased(Item, name="lost_item"), aliased(Item, name="found_item")
LO, FO = aliased(User, name="lost_owner"), aliased(User, name="found_owner")


def _side(item, owner, has_image):
    return {"id": item.id, "title": item.title, "category": item.category, "status": item.status,
            "location": item.location, "occurredAt": item.occurred_at, "ownerId": item.user_id,
            "ownerName": owner.name,
            "imageSrc": item.image_url or (f"/api/images/{item.id}" if has_image else None)}


def _matches_stmt():
    lost_img = exists().where(ItemImage.item_id == LI.id).correlate(LI).label("lh")
    found_img = exists().where(ItemImage.item_id == FI.id).correlate(FI).label("fh")
    return (select(Match, LI, LO, lost_img, FI, FO, found_img)
            .join(LI, LI.id == Match.lost_item_id).join(FI, FI.id == Match.found_item_id)
            .join(LO, LO.id == LI.user_id).join(FO, FO.id == FI.user_id))


def _map_match(r) -> dict:
    m, li, lo, lh, fi, fo, fh = r
    return {"id": m.id, "score": m.score, "reasons": m.reasons or [], "status": m.status,
            "createdAt": m.created_at, "resolvedAt": m.resolved_at,
            "lost": _side(li, lo, lh), "found": _side(fi, fo, fh)}


def list_matches(user_id=None, status=None, match_id=None, limit=50) -> list[dict]:
    cond = []
    if user_id: cond.append(or_(LI.user_id == user_id, FI.user_id == user_id))
    if match_id: cond.append(Match.id == match_id)
    if status: cond.append(Match.status == status)
    stmt = _matches_stmt().where(*cond).order_by(Match.score.desc(), Match.created_at.desc()).limit(limit)
    return [_map_match(r) for r in db.execute(stmt)]


def list_matches_for_item(item_id: int) -> list[dict]:
    stmt = (_matches_stmt().where(or_(Match.lost_item_id == item_id, Match.found_item_id == item_id))
            .order_by(Match.score.desc()))
    return [_map_match(r) for r in db.execute(stmt)]


def count_pending_matches(user_id=None) -> int:
    stmt = (select(func.count()).select_from(Match).join(LI, LI.id == Match.lost_item_id)
            .join(FI, FI.id == Match.found_item_id).where(Match.status == "PENDING"))
    if user_id:
        stmt = stmt.where(or_(LI.user_id == user_id, FI.user_id == user_id))
    return db.scalar(stmt) or 0


def count_matches(status=None) -> int:
    stmt = select(func.count()).select_from(Match)
    if status:
        stmt = stmt.where(Match.status == status)
    return db.scalar(stmt) or 0


def upsert_match(*, lost_item_id, found_item_id, score, reasons):
    row = db.execute(select(Match).where(Match.lost_item_id == lost_item_id,
                                         Match.found_item_id == found_item_id)).scalar_one_or_none()
    if row:
        row.score, row.reasons = score, reasons
    else:
        row = Match(lost_item_id=lost_item_id, found_item_id=found_item_id, score=score, reasons=reasons)
        db.add(row)
    db.commit()
    return row


def update_match_status(match_id: int, status: str, resolved_by_id: int):
    row = db.get(Match, match_id)
    if row:
        row.status, row.resolved_by_id, row.resolved_at = status, resolved_by_id, utcnow()
        db.commit()
    return row


def find_match_by_id(match_id: int):
    rows = list_matches(match_id=match_id, limit=1)
    return rows[0] if rows else None


def find_match_pairs_for_item(item_id: int) -> list[Match]:
    return list(db.scalars(select(Match).where(or_(Match.lost_item_id == item_id, Match.found_item_id == item_id))))


# ------------------------------------------------------------- notificações
def create_notifications(values: list[dict]):
    if not values:
        return
    for v in values:
        db.add(Notification(user_id=v["userId"], type=v["type"], title=v["title"], body=v["body"], link=v.get("link")))
    db.commit()


def create_notification(**v):
    create_notifications([v])


def notification_json(n: Notification) -> dict:
    return {"id": n.id, "userId": n.user_id, "type": n.type, "title": n.title, "body": n.body,
            "link": n.link, "isRead": n.is_read, "createdAt": n.created_at}


def list_notifications(user_id: int, limit=30) -> list[dict]:
    rows = db.scalars(select(Notification).where(Notification.user_id == user_id)
                      .order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit))
    return [notification_json(n) for n in rows]


def count_unread_notifications(user_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Notification)
                     .where(Notification.user_id == user_id, Notification.is_read.is_(False))) or 0


def mark_notification_read(notification_id: int, user_id: int):
    db.query(Notification).filter(Notification.id == notification_id, Notification.user_id == user_id).update({"is_read": True})
    db.commit()


def mark_all_notifications_read(user_id: int):
    db.query(Notification).filter(Notification.user_id == user_id, Notification.is_read.is_(False)).update({"is_read": True})
    db.commit()


# ------------------------------------------------------------ eventos do item
def add_item_event(*, item_id, actor_id, status, note):
    db.add(ItemEvent(item_id=item_id, actor_id=actor_id, status=status, note=note))
    db.commit()


def list_item_events(item_id: int) -> list[dict]:
    stmt = (select(ItemEvent.id, ItemEvent.status, ItemEvent.note, ItemEvent.created_at, User.name)
            .outerjoin(User, User.id == ItemEvent.actor_id).where(ItemEvent.item_id == item_id)
            .order_by(ItemEvent.created_at.desc(), ItemEvent.id.desc()))
    return [{"id": i, "status": s, "note": n, "createdAt": c, "actorName": a} for i, s, n, c, a in db.execute(stmt)]


def list_recent_events(limit=8, user_id=None) -> list[dict]:
    stmt = (select(ItemEvent.id, ItemEvent.note, ItemEvent.status, ItemEvent.created_at, Item.id, Item.title, Item.type)
            .join(Item, Item.id == ItemEvent.item_id).order_by(ItemEvent.created_at.desc()).limit(limit))
    if user_id:
        stmt = stmt.where(Item.user_id == user_id)
    return [{"id": i, "note": n, "status": s, "createdAt": c, "itemId": ii, "itemTitle": t, "itemType": ty}
            for i, n, s, c, ii, t, ty in db.execute(stmt)]
