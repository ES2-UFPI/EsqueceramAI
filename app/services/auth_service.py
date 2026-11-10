"""Cadastro, login, recuperação de senha e perfil (src/server/services/auth-service.ts)."""
import os
import re

from app.auth import create_session, hash_password, to_session_user, verify_password
from app.errors import ApiError
from app.repositories.engagement import create_notification
from app.repositories.users import (create_user, find_user_by_email, find_user_by_id, update_user_password,
                                    update_user_profile)
from app.services.seed_service import ensure_demo_accounts, ensure_seeded, find_demo_persona
from app.validation import Form


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

    # Contas de demonstração são criadas sob demanda, mantendo as credenciais documentadas válidas.
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


def recover_password(raw: dict) -> dict:
    f = Form(raw)
    f.email("email")
    f.text("phone", min=8, min_msg="Informe o telefone cadastrado na conta.")
    f.raw_text("newPassword", min=8, min_msg="A nova senha deve ter no mínimo 8 caracteres.")
    data = f.finish()
    user = find_user_by_email(data["email"])
    if not user:
        raise ApiError("Não encontramos uma conta com este e-mail. Confira os dados ou crie um novo cadastro.", 404)
    only_digits = lambda s: re.sub(r"\D", "", s or "")  # noqa: E731
    stored, informed = only_digits(user.phone), only_digits(data["phone"])
    if not stored or stored != informed:
        raise ApiError("O telefone informado não corresponde ao cadastro desta conta.", 422,
                       {"phone": ["Telefone diferente do cadastrado."]})
    update_user_password(user.id, hash_password(data["newPassword"]))
    create_notification(userId=user.id, type="SYSTEM", title="Sua senha foi redefinida",
                        body="A senha foi alterada com verificação por telefone. Se não foi você, procure a administração imediatamente.",
                        link="/painel/perfil")
    return {"ok": True}


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
