from sqlalchemy import func, select

from application.models import CollectionPoint, Item, db

_UNSET = object()

_FIELD_MAP = {
    "name": "name",
    "building": "building",
    "description": "description",
    "openingHours": "opening_hours",
    "contact": "contact",
    "latitude": "latitude",
    "longitude": "longitude",
    "isActive": "is_active",
}

_NON_NULL_FIELDS = {"name", "building", "isActive"}


def _map_point_fields(values: dict, allowed_keys: tuple[str, ...], *, skip_none: bool = False) -> dict:
    mapped = {}
    for key in allowed_keys:
        val = values.get(key, _UNSET)
        if val is _UNSET:
            continue
        if (skip_none or key in _NON_NULL_FIELDS) and val is None:
            continue
        mapped[_FIELD_MAP[key]] = val
    return mapped


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
    fields = _map_point_fields(
        values,
        ("name", "building", "description", "openingHours", "contact", "latitude", "longitude"),
        skip_none=True,
    )
    row = CollectionPoint(**fields)
    db.add(row)
    db.commit()
    return row


def update_point(point_id: int, **values):
    row = db.get(CollectionPoint, point_id)
    if not row:
        return None
    fields = _map_point_fields(
        values,
        ("name", "building", "isActive", "openingHours", "description", "contact", "latitude", "longitude"),
    )
    for attr, val in fields.items():
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
