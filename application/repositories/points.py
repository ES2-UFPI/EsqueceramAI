from sqlalchemy import func, select

from application.models import CollectionPoint, Item, db


def point_json(point: CollectionPoint) -> dict:
    return {
        "id": point.id,
        "name": point.name,
        "building": point.building,
        "description": point.description,
        "openingHours": point.opening_hours,
        "contact": point.contact,
        "latitude": point.latitude,
        "longitude": point.longitude,
        "isActive": point.is_active,
        "createdAt": point.created_at,
    }


def _serialize_point_with_counts(point: CollectionPoint, item_count: int, awaiting_count: int) -> dict:
    data = point_json(point)
    data.pop("createdAt", None)
    data["itemCount"] = item_count
    data["awaitingCount"] = awaiting_count
    return data


def list_points(only_active: bool = False) -> list[dict]:
    total_subquery = (
        select(func.count())
        .select_from(Item)
        .where(Item.point_id == CollectionPoint.id)
        .correlate(CollectionPoint)
        .scalar_subquery()
    )
    waiting_subquery = (
        select(func.count())
        .select_from(Item)
        .where(Item.point_id == CollectionPoint.id, Item.status.in_(["OPEN", "RESERVED"]))
        .correlate(CollectionPoint)
        .scalar_subquery()
    )
    stmt = select(CollectionPoint, total_subquery, waiting_subquery).order_by(CollectionPoint.name)
    if only_active:
        stmt = stmt.where(CollectionPoint.is_active.is_(True))
    return [_serialize_point_with_counts(*row) for row in db.execute(stmt)]


def find_point_by_id(point_id: int):
    return db.get(CollectionPoint, point_id)


def create_point(**values):
    row = CollectionPoint(
        name=values["name"],
        building=values["building"],
        description=values.get("description"),
        opening_hours=values.get("openingHours"),
        contact=values.get("contact"),
        latitude=values.get("latitude"),
        longitude=values.get("longitude"),
    )
    db.add(row)
    db.commit()
    return row


_UNSET = object()


def update_point(point_id: int, **values):
    row = db.get(CollectionPoint, point_id)
    if not row:
        return None
    for key, attr in (
        ("name", "name"),
        ("building", "building"),
        ("isActive", "is_active"),
        ("openingHours", "opening_hours"),
        ("description", "description"),
        ("contact", "contact"),
        ("latitude", "latitude"),
        ("longitude", "longitude"),
    ):
        val = values.get(key, _UNSET)
        if val is not _UNSET and (key not in ("name", "building", "isActive") or val is not None):
            setattr(row, attr, val)
    db.commit()
    return row


def count_points() -> int:
    return db.scalar(select(func.count()).select_from(CollectionPoint)) or 0


def list_recent_point_activity(limit: int = 6) -> list[dict]:
    stmt = (
        select(Item.id, Item.title, Item.status, Item.updated_at, CollectionPoint.name, CollectionPoint.id)
        .join(CollectionPoint, CollectionPoint.id == Item.point_id)
        .where(Item.type == "FOUND", Item.status != "ARCHIVED")
        .order_by(Item.updated_at.desc())
        .limit(limit)
    )
    return [
        {
            "itemId": item_id,
            "title": title,
            "status": status,
            "updatedAt": updated_at,
            "pointName": point_name,
            "pointId": point_id,
        }
        for item_id, title, status, updated_at, point_name, point_id in db.execute(stmt)
    ]
