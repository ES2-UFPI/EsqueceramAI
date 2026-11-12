"""O Render bloqueia 25/465/587 nas instâncias gratuitas; o log precisa dizer isso.

Sem a dica, "Network is unreachable" parece falha de credencial ou host errado, e
o tempo se perde no lugar errado — foi o que aconteceu no aviso de correspondência.
"""
import logging

import pytest

from application.delivery import email_service

# A captura global (_capture_emails) troca `email_service.send_email`; aqui o alvo é o
# transporte de verdade, então guardamos a referência original na importação.
_send_email_real = email_service.send_email


@pytest.fixture()
def smtp_no_ar(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setenv("SMTP_FROM", "no-reply@esqueceram.local")
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("EMAIL_BACKEND", raising=False)


@pytest.mark.parametrize("porta", ["25", "465", "587"])
def test_blocked_port_logs_the_2525_hint(smtp_no_ar, monkeypatch, caplog, porta):
    monkeypatch.setenv("SMTP_PORT", porta)

    def sem_rota(*_a, **_k):
        raise OSError(101, "Network is unreachable")

    monkeypatch.setattr(email_service.smtplib, "SMTP", sem_rota)
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", sem_rota)
    monkeypatch.setenv("SMTP_SSL", "1" if porta == "465" else "0")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(email_service.EmailError):
            _send_email_real("dest@ufpi.edu.br", "assunto", "corpo")

    texto = caplog.text
    assert "bloqueada para saída" in texto
    assert "SMTP_PORT=2525" in texto


def test_port_2525_does_not_trigger_the_hint(smtp_no_ar, monkeypatch, caplog):
    monkeypatch.setenv("SMTP_PORT", "2525")

    def sem_rota(*_a, **_k):
        raise OSError(101, "Network is unreachable")

    monkeypatch.setattr(email_service.smtplib, "SMTP", sem_rota)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(email_service.EmailError):
            _send_email_real("dest@ufpi.edu.br", "assunto", "corpo")

    assert "SMTP_PORT=2525" not in caplog.text
