"""Envio do código de confirmação por e-mail.

- SMTP: defina SMTP_HOST (+ SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_STARTTLS, SMTP_SSL).
- Sem SMTP_HOST (ou com EMAIL_BACKEND=console): modo desenvolvimento, a mensagem é impressa no console
  do servidor. Nunca exibimos o código na tela, para não anular a verificação.
"""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("esqueceram.email")


class EmailError(Exception):
    """Falha no envio (SMTP indisponível, credenciais inválidas...)."""


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "sim")


def backend_name() -> str:
    if os.getenv("EMAIL_BACKEND", "").lower() == "console" or not os.getenv("SMTP_HOST"):
        return "console"
    return "smtp"


def mask_email(email: str) -> str:
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"


def send_email(to: str, subject: str, body: str) -> str:
    """Envia a mensagem e devolve o backend usado ("smtp" ou "console")."""
    if backend_name() == "console":
        banner = "=" * 62
        print(f"\n{banner}\n[E-MAIL - modo desenvolvimento, SMTP não configurado]\nPara: {to}\nAssunto: {subject}\n\n{body}\n{banner}\n", flush=True)
        log.warning("E-mail para %s não enviado de verdade (backend console).", mask_email(to))
        return "console"

    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM", "Esqueceram AI <no-reply@esqueceram.local>")
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    host, port = os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))
    try:
        if _flag("SMTP_SSL", False):
            server = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=15)
        with server:
            if not _flag("SMTP_SSL", False) and _flag("SMTP_STARTTLS", True):
                server.starttls(context=ssl.create_default_context())
            if os.getenv("SMTP_USER"):
                server.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        log.error("Falha ao enviar e-mail para %s: %s", mask_email(to), exc)
        raise EmailError(str(exc)) from exc
    return "smtp"


def send_confirmation_code(*, to: str, name: str, code: str, item_title: str, point_name: str | None, ttl_minutes: int) -> str:
    local = f" no ponto de coleta {point_name}" if point_name else ""
    body = (
        f"Olá, {name}.\n\n"
        f"Seu código de confirmação para retirar o item \"{item_title}\"{local} é:\n\n"
        f"    {code}\n\n"
        f"O código vale por {ttl_minutes} minutos. Informe-o ao atendente somente quando estiver com o item em mãos.\n"
        f"Se você não está retirando um objeto agora, ignore esta mensagem e não compartilhe o código.\n\n"
        f"Esqueceram AI · achados e perdidos"
    )
    return send_email(to, "Código de confirmação de retirada - Esqueceram AI", body)
