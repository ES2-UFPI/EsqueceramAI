"""Pontos de coleta (src/server/repositories/points.ts)."""
from sqlalchemy import func, select

from app.models import CollectionPoint as P, Item, db


def _map(p, n, aw):
    return {"id": p.id, "name": p.name, "building": p.building, "description": p.description,
            "openingHours": p.opening_hours, "contact": p.contact, "latitude": p.latitude,
            "longitude": p.longitude, "isActive": p.is_active, "itemCount": n, "awaitingCount": aw}


def list_points(only_active=False) -> list[dict]:
    total = select(func.count()).select_from(Item).where(Item.point_id == P.id).correlate(P).scalar_subquery()
    waiting = (select(func.count()).select_from(Item)
               .where(Item.point_id == P.id, Item.status.in_(["OPEN", "RESERVED"])).correlate(P).scalar_subquery())
    stmt = select(P, total, waiting).order_by(P.name)
    if only_active:
        stmt = stmt.where(P.is_active.is_(True))
    return [_map(*row) for row in db.execute(stmt)]


def find_point_by_id(point_id: int):
    return db.get(P, point_id)


def create_point(**v):
    row = P(name=v["name"], building=v["building"], description=v.get("description"),
            opening_hours=v.get("openingHours"), contact=v.get("contact"),
            latitude=v.get("latitude"), longitude=v.get("longitude"))
    db.add(row)
    db.commit()
    return row


def update_point(point_id: int, **v):
    row = db.get(P, point_id)
    if not row:
        return None
    for key, attr in (("isActive", "is_active"), ("openingHours", "opening_hours"), ("description", "description")):
        if v.get(key) is not None:
            setattr(row, attr, v[key])
    db.commit()
    return row


def point_json(p) -> dict:
    return {"id": p.id, "name": p.name, "building": p.building, "description": p.description,
            "openingHours": p.opening_hours, "contact": p.contact, "latitude": p.latitude,
            "longitude": p.longitude, "isActive": p.is_active, "createdAt": p.created_at}


def count_points() -> int:
    return db.scalar(select(func.count()).select_from(P)) or 0


def list_recent_point_activity(limit=6) -> list[dict]:
    stmt = (select(Item.id, Item.title, Item.status, Item.updated_at, P.name, P.id)
            .join(P, P.id == Item.point_id).where(Item.type == "FOUND", Item.status != "ARCHIVED")
            .order_by(Item.updated_at.desc()).limit(limit))
    return [{"itemId": i, "title": t, "status": s, "updatedAt": u, "pointName": pn, "pointId": pi}
            for i, t, s, u, pn, pi in db.execute(stmt)]
