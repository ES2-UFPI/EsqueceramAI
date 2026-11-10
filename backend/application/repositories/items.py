"""Acesso a dados de itens, imagens e estatísticas (src/server/repositories/items.ts)."""
import math
import re
from datetime import datetime, timezone

from sqlalchemy import case, exists, func, or_, select

from application.domain import CAMPUS_CENTER
from application.models import CollectionPoint, Item, ItemImage, User, db, utcnow
from application.validation import parse_iso

_has_image = exists().where(ItemImage.item_id == Item.id).correlate(Item).label("has_image")


def _base():
    return (select(Item, User, CollectionPoint, _has_image)
            .join(User, User.id == Item.user_id)
            .outerjoin(CollectionPoint, CollectionPoint.id == Item.point_id))


def map_item(row) -> dict:
    i, u, p, has_image = row
    return {
        "id": i.id, "userId": i.user_id, "type": i.type, "category": i.category, "title": i.title,
        "description": i.description, "color": i.color, "brand": i.brand, "model": i.model,
        "attributes": i.attributes or {}, "location": i.location, "occurredAt": i.occurred_at,
        "status": i.status, "pointId": i.point_id, "latitude": i.latitude, "longitude": i.longitude,
        "imageSrc": i.image_url or (f"/api/images/{i.id}" if has_image else None),
        "createdAt": i.created_at, "updatedAt": i.updated_at,
        "ownerName": u.name, "ownerEmail": u.email, "ownerPhone": u.phone, "ownerRole": u.role,
        "ownerAvatar": u.avatar_url,
        "pointName": p.name if p else None, "pointBuilding": p.building if p else None,
        "pointHours": p.opening_hours if p else None,
    }


def item_row_json(i: Item) -> dict:
    """Linha crua do banco (como o `returning()` do Drizzle), em camelCase."""
    return {"id": i.id, "userId": i.user_id, "type": i.type, "category": i.category, "title": i.title,
            "description": i.description, "color": i.color, "brand": i.brand, "model": i.model,
            "attributes": i.attributes or {}, "location": i.location, "occurredAt": i.occurred_at,
            "status": i.status, "pointId": i.point_id, "latitude": i.latitude, "longitude": i.longitude,
            "imageUrl": i.image_url, "storageKey": i.storage_key, "createdAt": i.created_at,
            "updatedAt": i.updated_at}


def _aware(d):
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _conditions(f: dict) -> list:
    c = []
    if f.get("type"): c.append(Item.type == f["type"])
    if f.get("category"): c.append(Item.category == f["category"])
    if f.get("status"): c.append(Item.status == f["status"])
    elif not f.get("includeArchived"): c.append(Item.status != "ARCHIVED")
    for key, col in (("location", Item.location), ("color", Item.color), ("brand", Item.brand), ("model", Item.model)):
        if f.get(key): c.append(col.ilike(f"%{f[key]}%"))
    if f.get("ownerId"): c.append(Item.user_id == f["ownerId"])
    if f.get("pointId"): c.append(Item.point_id == f["pointId"])
    if f.get("from") and (d := parse_iso(f["from"])):
        c.append(Item.occurred_at >= _aware(d))
    if f.get("to") and (d := parse_iso(f["to"])):
        c.append(Item.occurred_at <= _aware(d).replace(hour=23, minute=59, second=59, microsecond=999000))
    q = (f.get("q") or "").strip()
    if q:
        term = f"%{q}%"
        parts = [col.ilike(term) for col in (Item.title, Item.description, Item.location, Item.color, Item.brand, Item.model)]
        if m := re.match(r"^esq-?0*(\d+)$", q, re.I):
            parts.append(Item.id == int(m.group(1)))
        c.append(or_(*parts))
    return c


def list_items(f: dict) -> dict:
    page_size = min(f.get("pageSize") or 9, 50)
    page = max(f.get("page") or 1, 1)
    where = _conditions(f)
    order = []
    q = (f.get("q") or "").strip()
    if f.get("sort") == "proximity":
        dlat, dlng = Item.latitude - CAMPUS_CENTER["lat"], Item.longitude - CAMPUS_CENTER["lng"]
        order.append(func.coalesce(dlat * dlat + dlng * dlng, 99999).asc())
    elif f.get("sort") != "recent" and q:
        term = f"%{q}%"
        order.append(case((Item.title.ilike(term), 0), (Item.description.ilike(term), 1), else_=2).asc())
    order += [Item.occurred_at.desc(), Item.id.desc()]
    rows = db.execute(_base().where(*where).order_by(*order).limit(page_size).offset((page - 1) * page_size))
    total = db.scalar(select(func.count()).select_from(Item).where(*where)) or 0
    return {"items": [map_item(r) for r in rows], "total": total, "page": page, "pageSize": page_size,
            "totalPages": max(math.ceil(total / page_size), 1)}


def find_item_by_id(item_id: int):
    row = db.execute(_base().where(Item.id == item_id).limit(1)).first()
    return map_item(row) if row else None


def create_item(values: dict) -> Item:
    row = Item(**values)
    db.add(row)
    db.commit()
    return row


def update_item(item_id: int, values: dict):
    row = db.get(Item, item_id)
    if not row:
        return None
    for k, v in values.items():
        setattr(row, k, v)
    row.updated_at = utcnow()
    db.commit()
    return row


def set_item_status(item_id: int, status: str):
    row = db.get(Item, item_id)
    if row:
        row.status, row.updated_at = status, utcnow()
        db.commit()
    return row


def delete_item(item_id: int):
    row = db.get(Item, item_id)
    if row:
        db.delete(row)
        db.commit()


def save_item_image(*, item_id, provider, storage_key, mime_type, size_bytes, data):
    row = db.execute(select(ItemImage).where(ItemImage.item_id == item_id)).scalar_one_or_none()
    if row:
        row.provider, row.storage_key, row.mime_type, row.size_bytes, row.data = provider, storage_key, mime_type, size_bytes, data
    else:
        db.add(ItemImage(item_id=item_id, provider=provider, storage_key=storage_key,
                         mime_type=mime_type, size_bytes=size_bytes, data=data))
    db.commit()


def find_item_image(item_id: int):
    return db.execute(select(ItemImage).where(ItemImage.item_id == item_id).limit(1)).scalar_one_or_none()


def list_open_by_type(record_type: str) -> list[dict]:
    rows = db.scalars(select(Item).where(Item.type == record_type, Item.status.in_(["OPEN", "RESERVED"])))
    return [{"id": i.id, "userId": i.user_id, "type": i.type, "category": i.category, "title": i.title,
             "description": i.description, "color": i.color, "brand": i.brand, "model": i.model,
             "location": i.location, "occurredAt": i.occurred_at, "attributes": i.attributes or {}}
            for i in rows]


def recent_items(limit=6, owner_id=None) -> list[dict]:
    cond = Item.user_id == owner_id if owner_id else Item.status != "ARCHIVED"
    return [map_item(r) for r in db.execute(_base().where(cond).order_by(Item.created_at.desc()).limit(limit))]


def count_items(*where) -> int:
    return db.scalar(select(func.count()).select_from(Item).where(*where)) or 0


def _group_count(col, owner_id):
    stmt = select(col, func.count()).group_by(col)
    if owner_id:
        stmt = stmt.where(Item.user_id == owner_id)
    return [{"key": k, "total": int(t)} for k, t in db.execute(stmt)]


def count_by_status(owner_id=None): return _group_count(Item.status, owner_id)
def count_by_category(owner_id=None): return _group_count(Item.category, owner_id)


def monthly_series(months=6) -> list[dict]:
    """Novos itens por mês e tipo (agregação em Python: portável entre PostgreSQL e SQLite)."""
    now = utcnow()
    y, m = now.year, now.month - (months - 1)
    while m < 1:
        m += 12
        y -= 1
    since = datetime(y, m, 1, tzinfo=timezone.utc)
    counts: dict[tuple[str, str], int] = {}
    for created, typ in db.execute(select(Item.created_at, Item.type).where(Item.created_at >= since)):
        key = (created.strftime("%Y-%m"), typ)
        counts[key] = counts.get(key, 0) + 1
    return [{"month": mo, "type": t, "total": n} for (mo, t), n in sorted(counts.items())]


def items_at_points(point_id=None) -> list[dict]:
    stmt = (select(Item, User, CollectionPoint, _has_image).join(User, User.id == Item.user_id)
            .join(CollectionPoint, CollectionPoint.id == Item.point_id).order_by(Item.updated_at.desc()).limit(40))
    if point_id:
        stmt = stmt.where(Item.point_id == point_id)
    return [map_item(r) for r in db.execute(stmt)]
