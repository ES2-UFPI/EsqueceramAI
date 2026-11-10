import smtplib

import pytest

from app.delivery import email_service as email
from app.delivery import security as sec


def test_code_is_six_digits_and_random():
    codes = {sec.generate_code() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 150


def test_code_hash_is_bound_to_delivery_and_never_plain():
    h = sec.hash_code(7, "123456")
    assert "123456" not in h and len(h) == 64
    assert sec.verify_code(7, "123456", h)
    assert sec.verify_code(7, " 123456 ", h)
    assert not sec.verify_code(8, "123456", h)       # código de outra entrega não vale
    assert not sec.verify_code(7, "654321", h)
    assert not sec.verify_code(7, "123456", None)


def test_cpf_hash_deterministic_without_exposing_cpf():
    h = sec.hash_cpf("52998224725")
    assert h == sec.hash_cpf("52998224725") and h != sec.hash_cpf("39053344705")
    assert "52998224725" not in h


def test_key_change_invalidates(monkeypatch):
    h = sec.hash_code(1, "000001")
    monkeypatch.setenv("DELIVERY_HMAC_KEY", "outra-chave")
    assert not sec.verify_code(1, "000001", h)


def test_mask_email():
    assert email.mask_email("maria.souza@gmail.com") == "m***@gmail.com"
    assert email.mask_email("invalido") == "***"


def test_console_backend_prints_code(capsys):
    assert email.backend_name() == "console"
    used = email.send_confirmation_code(to="a@b.com", name="Ana", code="987654", item_title="Fone JBL",
                                        point_name="Biblioteca Central", ttl_minutes=15)
    out = capsys.readouterr().out
    assert used == "console" and "987654" in out and "a@b.com" in out and "Fone JBL" in out and "15 minutos" in out


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.log, self.sent = host, port, [], None
        FakeSMTP.instances.append(self)

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self, context=None): self.log.append("starttls")
    def login(self, user, pwd): self.log.append(("login", user, pwd))
    def send_message(self, msg): self.sent = msg


def test_smtp_backend(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setenv("SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setenv("SMTP_USER", "u")
    monkeypatch.setenv("SMTP_PASSWORD", "p")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    used = email.send_confirmation_code(to="maria@x.com", name="Maria", code="111222", item_title="Chave",
                                        point_name=None, ttl_minutes=15)
    srv = FakeSMTP.instances[0]
    assert used == "smtp" and (srv.host, srv.port) == ("smtp.exemplo.com", 587)
    assert srv.log == ["starttls", ("login", "u", "p")]
    assert srv.sent["To"] == "maria@x.com" and "111222" in srv.sent.get_content()


def test_smtp_failure_raises_email_error(monkeypatch):
    class Broken(FakeSMTP):
        def send_message(self, msg): raise smtplib.SMTPRecipientsRefused({})
    monkeypatch.setenv("SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setattr(smtplib, "SMTP", Broken)
    with pytest.raises(email.EmailError):
        email.send_email("x@y.com", "a", "b")


def test_console_forced_even_with_smtp_host(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setenv("EMAIL_BACKEND", "console")
    assert email.backend_name() == "console"
