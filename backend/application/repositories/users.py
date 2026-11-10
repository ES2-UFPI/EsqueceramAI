"""Acesso a dados de usuários (src/server/repositories/users.ts)."""
from sqlalchemy import func, or_, select

from application.models import Item, User, db, utcnow


def find_user_by_email(email: str):
    return db.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()


def find_user_by_id(user_id: int):
    return db.get(User, user_id)


def create_user(*, name, email, password_hash, phone=None, role="USER"):
    row = User(name=name.strip(), email=email.strip().lower(), password_hash=password_hash,
               phone=(phone or "").strip() or None, role=role)
    db.add(row)
    db.commit()
    return row


def update_user_profile(user_id: int, *, name, phone, avatar_url):
    row = db.get(User, user_id)
    if not row:
        return None
    row.name, row.phone, row.avatar_url, row.updated_at = name, phone, avatar_url, utcnow()
    db.commit()
    return row


def update_user_password(user_id: int, password_hash: str):
    row = db.get(User, user_id)
    row.password_hash, row.updated_at = password_hash, utcnow()
    db.commit()


def add_user_score(user_id: int, amount: int):
    row = db.get(User, user_id)
    if row:
        row.score = max(row.score + amount, 0)  # greatest(score + n, 0)
        row.updated_at = utcnow()
        db.commit()


def _count_items(*extra):
    return (select(func.count()).select_from(Item).where(Item.user_id == User.id, *extra)
            .correlate(User).scalar_subquery())


def list_users(q: str | None = None, role: str | None = None) -> list[dict]:
    stmt = select(User, _count_items().label("n"),
                  _count_items(Item.status == "RETURNED").label("r")).order_by(User.name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.name.ilike(like), User.email.ilike(like)))
    if role:
        stmt = stmt.where(User.role == role)
    return [{"id": u.id, "name": u.name, "email": u.email, "phone": u.phone, "avatarUrl": u.avatar_url,
             "role": u.role, "score": u.score, "isActive": u.is_active, "createdAt": u.created_at,
             "itemCount": n, "recoveries": r} for u, n, r in db.execute(stmt)]


def set_user_role(user_id: int, role: str):
    row = db.get(User, user_id)
    if row:
        row.role, row.updated_at = role, utcnow()
        db.commit()


def set_user_active(user_id: int, active: bool):
    row = db.get(User, user_id)
    if row:
        row.is_active, row.updated_at = active, utcnow()
        db.commit()


def top_contributors(limit=5) -> list[dict]:
    stmt = (select(User, _count_items(Item.status == "RETURNED").label("r"))
            .where(User.is_active.is_(True)).order_by(User.score.desc()).limit(limit))
    return [{"id": u.id, "name": u.name, "role": u.role, "score": u.score, "returned": r}
            for u, r in db.execute(stmt)]


def count_users() -> int:
    return db.scalar(select(func.count()).select_from(User)) or 0


def count_users_by_role() -> list[dict]:
    rows = db.execute(select(User.role, func.count()).group_by(User.role))
    return [{"role": r, "total": int(t)} for r, t in rows]
