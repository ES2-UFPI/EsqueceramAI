"""Envio de e-mails do Esqueceram AI (código de confirmação e avisos de correspondência).

- SMTP: defina SMTP_HOST (+ SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_STARTTLS, SMTP_SSL).
- Sem SMTP_HOST (ou com EMAIL_BACKEND=console): modo desenvolvimento, a mensagem é impressa no console
  do servidor. Nunca exibimos o código na tela, para não anular a verificação.
- APP_BASE_URL é a raiz dos links enviados (o backend também serve as páginas web).
"""
import html
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


def app_base_url() -> str:
    return (os.getenv("APP_BASE_URL") or "").rstrip("/")


def public_url(path: str) -> str:
    """Link absoluto para as páginas web servidas pelo próprio backend."""
    return f"{app_base_url()}{path}"


def send_email(to: str, subject: str, body: str, html_body: str | None = None) -> str:
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
    if html_body:
        msg.add_alternative(html_body, subtype="html")
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


def _match_card(item: dict, label: str) -> str:
    lines = [f"<p><strong>{label}:</strong> {html.escape(item['title'])}</p>",
             f"<p>Local: {html.escape(item['location'])}</p>"]
    details = [item.get("color"), item.get("brand"), item.get("model")]
    details = [html.escape(str(d)) for d in details if d]
    if details:
        lines.append(f"<p>Detalhes: {' · '.join(details)}</p>")
    if item.get("description"):
        lines.append(f"<p style=\"color:#555\">{html.escape(item['description'][:280])}</p>")
    return "".join(lines)


def send_match_notification(*, to: str, name: str, lost: dict, found: dict, score: int, reasons: list[str],
                            match_id: int) -> str:
    """Avisa quem perdeu o item que uma correspondência forte foi publicada (US09)."""
    card = public_url(f"/correspondencias/{match_id}")
    painel = public_url("/painel/matches")
    reasons_text = "".join(f"  - {r}\n" for r in reasons) or "  - Características compatíveis\n"
    body = (
        f"Olá, {name}.\n\n"
        f"Boa notícia: encontramos um item com {score}% de similaridade com o seu relato \"{lost['title']}\".\n\n"
        f"Item encontrado: {found['title']}\n"
        f"Local: {found['location']}\n\n"
        f"Por que sugerimos esta correspondência:\n{reasons_text}\n"
        f"Veja os detalhes e confirme se o item é seu:\n{card}\n\n"
        f"Se não for o seu item, você também pode descartar a sugestão nesse mesmo link "
        f"para melhorar as próximas recomendações.\n\n"
        f"Esqueceram AI · achados e perdidos"
    )
    reason_items = "".join(f"<li>{html.escape(r)}</li>" for r in reasons) or "<li>Características compatíveis</li>"
    html_body = (
        "<div style=\"font-family:Arial,Helvetica,sans-serif;color:#1f2933;max-width:560px\">"
        "<h2 style=\"margin:0 0 8px\">Encontramos uma possível correspondência</h2>"
        f"<p>Olá, {html.escape(name)}. Um item recém-publicado tem <strong>{score}% de similaridade</strong> "
        f"com o seu relato <em>\"{html.escape(lost['title'])}\"</em>.</p>"
        f"<div style=\"border:1px solid #e3e8ee;border-radius:10px;padding:16px;margin:16px 0\">"
        f"{_match_card(found, 'Item encontrado')}</div>"
        f"<p><strong>Por que sugerimos:</strong></p><ul>{reason_items}</ul>"
        f"<p><a href=\"{html.escape(card)}\" style=\"display:inline-block;background:#1d4ed8;color:#fff;"
        f"padding:10px 18px;border-radius:8px;text-decoration:none\">Ver item e confirmar</a></p>"
        f"<p style=\"color:#555;font-size:13px\">Se não for o seu item, descarte em "
        f"<a href=\"{html.escape(card)}\">Ver item e confirmar</a>; isso melhora as próximas sugestões.</p>"
        f"<p style=\"color:#777;font-size:12px\">Painel de correspondências: "
        f"<a href=\"{html.escape(painel)}\">{html.escape(painel)}</a></p>"
        "</div>"
    )
    return send_email(to, f"Encontramos um item parecido com o seu relato ({score}%) - Esqueceram AI",
                      body, html_body)
