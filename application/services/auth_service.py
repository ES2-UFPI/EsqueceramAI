import hashlib
import os
import re
import secrets
from datetime import timedelta

from application.auth import create_session, hash_password, to_session_user, verify_password
from application.delivery.email_service import send_password_reset_link
from application.errors import ApiError
from application.models import utcnow
from application.repositories.engagement import create_notification
from application.repositories.users import (create_password_reset_token, create_user,
                                    find_user_by_email, find_user_by_id,
                                    find_valid_password_reset_token,
                                    mark_password_reset_token_used, update_user_password,
                                    update_user_profile)
from application.services.seed_service import ensure_demo_accounts, ensure_seeded, find_demo_persona
from application.validation import Form


def register_user(raw: dict) -> dict:
    f = Form(raw)
    f.text("name", min=3, max=120, min_msg="Informe seu nome completo.", max_msg="Nome muito longo.")
    f.email("email")
    f.text("phone", max=30, max_msg="Telefone muito longo.", optional=True)
    f.raw_text("password", min=8, max=128, min_msg="A senha deve ter no mínimo 8 caracteres.", max_msg="Senha muito longa.")
    data = f.finish()
    if find_user_by_email(data["email"]):
        raise ApiError("Já existe uma conta com este e-mail.", 409, {"email": ["E-mail já cadastrado."]})
    created = create_user(name=data["name"], email=data["email"], phone=data["phone"] or None,
                          password_hash=hash_password(data["password"]))
    create_notification(userId=created.id, type="SYSTEM", title="Bem-vindo(a) ao Esqueceram AI",
                        body="Sua conta está pronta. Registre itens perdidos ou encontrados e receba sugestões automáticas de correspondência.",
                        link="/painel")
    create_session(created.id)
    return to_session_user(created)


def login_user(raw: dict) -> dict:
    f = Form(raw)
    f.email("email")
    f.raw_text("password", min=1, min_msg="Informe sua senha.")
    data = f.finish()

    user = find_user_by_email(data["email"])
    if not user:
        try:
            ensure_demo_accounts()
        except Exception as exc:  # noqa: BLE001
            print("[auth] demo account provisioning failed", exc)
        ensure_seeded()
        user = find_user_by_email(data["email"])

    if not user or not verify_password(data["password"], user.password_hash):
        raise ApiError("E-mail ou senha inválidos. Se estiver testando a demonstração, use um dos acessos rápidos.", 401)
    if not user.is_active:
        raise ApiError("Sua conta está desativada. Procure a administração.", 403)
    create_session(user.id)
    return to_session_user(user)


def login_demo_user(persona: str | None) -> dict:
    """Acesso de 1 clique às contas whitelisted. Desativável com DEMO_LOGIN_DISABLED=true."""
    if os.getenv("DEMO_LOGIN_DISABLED", "").lower() == "true":
        raise ApiError("O acesso de demonstração está desativado neste ambiente.", 403)
    selected = find_demo_persona(persona)
    try:
        ensure_demo_accounts()
        ensure_seeded()
    except Exception as exc:  # noqa: BLE001
        print("[auth] demo seeding failed", exc)
    user = find_user_by_email(selected["email"])
    if not user:
        ids = ensure_demo_accounts()
        uid = ids.get(selected["key"])
        user = find_user_by_id(uid) if uid else None
    if not user:
        raise ApiError("Não foi possível preparar a conta de demonstração.", 503)
    if not user.is_active:
        raise ApiError("A conta de demonstração está desativada.", 403)
    create_session(user.id)
    return to_session_user(user)


RESET_TOKEN_TTL_MINUTES = 30


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def request_password_reset(raw: dict, base_url: str | None = None) -> dict:
    """Gera token temporário de redefinição e envia link por e-mail."""
    f = Form(raw)
    f.email("email")
    data = f.finish()
    user = find_user_by_email(data["email"])
    if user and user.is_active:
        token = secrets.token_urlsafe(32)
        expires_at = utcnow() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
        create_password_reset_token(user_id=user.id, token_hash=_token_hash(token), expires_at=expires_at)
        root = (base_url or os.getenv("APP_BASE_URL") or "http://localhost:5000").rstrip("/")
        reset_url = f"{root}/redefinir-senha?token={token}"
        send_password_reset_link(to=user.email, name=user.name, reset_url=reset_url, ttl_minutes=RESET_TOKEN_TTL_MINUTES)
    return {"ok": True}


def validate_password_reset_token(token: str | None) -> bool:
    clean = (token or "").strip()
    if not clean:
        return False
    return find_valid_password_reset_token(_token_hash(clean)) is not None


def reset_password_with_token(raw: dict) -> dict:
    """Valida o token enviado por e-mail, redefine a senha e invalida o token."""
    f = Form(raw)
    f.raw_text("token", min=10, min_msg="Token de redefinição inválido.")
    f.raw_text("newPassword", min=8, max=128, min_msg="A nova senha deve ter no mínimo 8 caracteres.", max_msg="Senha muito longa.")
    data = f.finish()
    row = find_valid_password_reset_token(_token_hash(data["token"].strip()))
    if not row:
        raise ApiError("Link de redefinição inválido ou expirado. Solicite um novo.", 400)
    update_user_password(row.user_id, hash_password(data["newPassword"]))
    mark_password_reset_token_used(row.id)
    create_notification(userId=row.user_id, type="SYSTEM", title="Sua senha foi redefinida",
                        body="A senha foi alterada usando o link enviado por e-mail. Se não foi você, procure a administração imediatamente.",
                        link="/painel/perfil")
    return {"ok": True}


def recover_password(raw: dict) -> dict:
    if (raw or {}).get("token"):
        return reset_password_with_token(raw)
    return request_password_reset(raw)


def update_profile(user_id: int, raw: dict) -> dict:
    f = Form(raw)
    f.text("name", min=3, max=120, min_msg="Informe seu nome completo.")
    f.text("phone", max=30, optional=True)
    avatar = f.text("avatarUrl", optional=True)
    if avatar and not re.match(r"^https?://[^\s/$.?#].[^\s]*$", avatar, re.I):
        f.errors.setdefault("avatarUrl", []).append("Informe uma URL válida.")
    data = f.finish()
    updated = update_user_profile(user_id, name=data["name"], phone=data["phone"] or None, avatar_url=data["avatarUrl"] or None)
    if not updated:
        raise ApiError("Perfil não encontrado.", 404)
    return to_session_user(updated)


def change_password(user_id: int, raw: dict) -> dict:
    f = Form(raw)
    f.raw_text("currentPassword", min=1, min_msg="Informe a senha atual.")
    f.raw_text("newPassword", min=8, min_msg="A nova senha deve ter no mínimo 8 caracteres.")
    data = f.finish()
    user = find_user_by_id(user_id)
    if not user:
        raise ApiError("Usuário não encontrado.", 404)
    if not verify_password(data["currentPassword"], user.password_hash):
        raise ApiError("Senha atual incorreta.", 422, {"currentPassword": ["Senha atual incorreta."]})
    update_user_password(user_id, hash_password(data["newPassword"]))
    return {"ok": True}


def get_profile(user_id: int):
    user = find_user_by_id(user_id)
    return to_session_user(user) if user else None
