"""E-mail de confirmação enviado ao dono depois que a posse é validada (US04).

Separado de ``email_service`` de propósito: aquele módulo é do fluxo de entrega e cobre
códigos/segurança. Aqui só reutilizamos o transporte (``send_email``) e o mesmo backend
SMTP/console configurado por ``EMAIL_BACKEND``.
"""
from application.delivery import email_service
from application.delivery.email_service import EmailError, mask_email

TEXT = """Olá, {name}!

{claimant} respondeu corretamente à pergunta de segurança do item "{title}" ({code}),
então a posse foi validada.

Próximo passo: combine a retirada no ponto de coleta combinado com a equipe.

Se você não esperava esta confirmação, entre em contato com a administração.
"""

HTML = """<div style="font-family:system-ui,sans-serif;line-height:1.6">
  <p>Olá, <strong>{name}</strong>!</p>
  <p><strong>{claimant}</strong> respondeu corretamente à pergunta de segurança do item
     <strong>{title}</strong> ({code}) e a posse foi validada.</p>
  <p>Próximo passo: combine a retirada no ponto de coleta combinado com a equipe.</p>
  <p style="color:#666;font-size:13px">Se você não esperava esta confirmação, avise a administração.</p>
</div>"""


def send_ownership_confirmed(*, to: str, name: str, claimant: str, title: str, code: str) -> str:
    """Retorna o backend usado ("console"/"smtp"); levanta ``EmailError`` se o envio falhar."""
    fields = {"name": name, "claimant": claimant, "title": title, "code": code}
    return email_service.send_email(to=to, subject=f"Posse validada: {title}",
                                    body=TEXT.format(**fields), html_body=HTML.format(**fields))


__all__ = ["send_ownership_confirmed", "EmailError", "mask_email"]
