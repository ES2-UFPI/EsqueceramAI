"""Sessões, scrypt e permissões (src/server/auth.ts).

O hash segue o mesmo formato do original (`scrypt:<salt>:<hex>`, N=16384, r=8, p=1,
64 bytes; o salt hexadecimal entra como string), portanto contas criadas pela versão
TypeScript continuam válidas.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from flask import g, redirect, request, url_for
from sqlalchemy import select

from application.models import AuthSession, User, db

SESSION_COOKIE = "esqueceram_session"
SESSION_TTL_DAYS = 14


def _derive(password: str, salt: str) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    return f"scrypt:{salt}:{_derive(password, salt).hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split(":")
    except ValueError:
        return False
    if scheme != "scrypt" or not salt or not digest:
        return False
    return hmac.compare_digest(_derive(password, salt), bytes.fromhex(digest))


def to_session_user(row: User) -> dict:
    return {"id": row.id, "name": row.name, "email": row.email, "phone": row.phone,
            "avatarUrl": row.avatar_url, "role": row.role, "score": row.score}


def create_session(user_id: int) -> tuple[str, datetime]:
    token = secrets.token_hex(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
    db.add(AuthSession(token=token, user_id=user_id, expires_at=expires))
    db.commit()
    g.new_session = (token, expires)  # o controller grava o cookie na resposta
    return token, expires


def destroy_session(token: str | None):
    if token:
        db.query(AuthSession).filter(AuthSession.token == token).delete()
        db.commit()


def get_user_by_token(token: str | None):
    if not token:
        return None
    row = db.execute(
        select(User).join(AuthSession, AuthSession.user_id == User.id)
        .where(AuthSession.token == token, AuthSession.expires_at > datetime.now(timezone.utc))
    ).scalar_one_or_none()
    if not row or not row.is_active:
        return None
    return to_session_user(row)


def cookie_token():
    return request.cookies.get(SESSION_COOKIE)


def bearer_token():
    header = request.headers.get("Authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else None


def authenticate():
    """Bearer ou cookie (API)."""
    if (t := bearer_token()) and (u := get_user_by_token(t)):
        return u
    return get_user_by_token(cookie_token())


def get_current_user():
    """Cookie de sessão (páginas)."""
    if "current_user" not in g:
        g.current_user = get_user_by_token(cookie_token())
    return g.current_user


def can_manage_item(user: dict, item: dict) -> bool:
    return user["role"] == "ADMIN" or user["id"] == item["userId"]


def is_staff(user: dict) -> bool:
    return user["role"] in ("ADMIN", "OPERATOR_POST")
