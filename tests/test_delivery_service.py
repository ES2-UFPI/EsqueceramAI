import io
from datetime import timedelta

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.delivery import models as m
from app.delivery import repository as repo
from app.delivery import security as sec
from app.models import Item, User, db, utcnow
from conftest import JPEG, VALID_CPF, persona_client, start


def code_of(sent):  # último código "enviado"
    return sent[-1]["code"]


def user_score(email):
    db.expire_all()
    return db.execute(select(User).where(User.email == email)).scalar_one().score


# --------------------------------------------------------------- permissões
def test_only_attendant_can_checkout(app, make_item, sent_codes, attendant):
    item = make_item()
    for persona in ("ana@ufpi.edu.br", "admin@ufpi.edu.br"):       # comunidade e admin NÃO registram entregas
        r = start(persona_client(app, persona), item)
        assert r.status_code == 403, persona
    assert app.test_client().post("/api/deliveries").status_code == 401
    assert sent_codes == []


def test_registration_required_and_validated(app, make_item, sent_codes):
    c = persona_client(app, "operador@ufpi.edu.br")
    db.query(m.AttendantProfile).delete(); db.commit()
    r = start(c, make_item())
    assert r.status_code == 409 and "matrícula" in r.get_json()["error"].lower()
    assert c.put("/api/attendant/registration", json={"registrationNumber": "ab"}).status_code == 422
    assert c.put("/api/attendant/registration", json={"registrationNumber": "atd 01!"}).status_code == 422
    r = c.put("/api/attendant/registration", json={"registrationNumber": "atd-2024-0117"})
    assert r.get_json()["registrationNumber"] == "ATD-2024-0117"      # normaliza para maiúsculas
    assert c.get("/api/attendant/registration").get_json()["registrationNumber"] == "ATD-2024-0117"
    assert persona_client(app, "ana@ufpi.edu.br").get("/api/attendant/registration").status_code == 403


# --------------------------------------------------------------- validações
def test_cpf_and_form_validation(app, make_item, sent_codes, attendant):
    item = make_item()
    r = start(attendant, item, cpf="111.111.111-11")
    assert r.status_code == 422 and "cpf" in r.get_json()["details"]
    assert "dígitos verificadores" in r.get_json()["details"]["cpf"][0] or "inválido" in r.get_json()["details"]["cpf"][0]
    assert "formato" in start(attendant, item, cpf="123").get_json()["details"]["cpf"][0]
    assert start(attendant, item, cpf="529.982.247-24").status_code == 422
    r = start(attendant, item, cpf="", recipientName="Maria", email="x", document=None)   # todos os erros de uma vez
    assert set(r.get_json()["details"]) == {"cpf", "recipientName", "email", "document"}
    assert start(attendant, item, document=(io.BytesIO(b"<html>"), "a.jpg", "image/jpeg")).status_code == 422
    assert start(attendant, "", ).status_code == 422
    assert sent_codes == []                                           # nada foi enviado nem criado
    assert db.query(m.Delivery).filter(m.Delivery.item_id == item).count() == 0


def test_item_rules(app, make_item, sent_codes, attendant):
    assert start(attendant, make_item(kind="LOST")).status_code == 422          # só itens encontrados
    assert start(attendant, make_item(with_point=False)).status_code == 422     # precisa estar num ponto
    assert start(attendant, make_item(status="RETURNED")).status_code == 409
    assert start(attendant, make_item(status="ARCHIVED")).status_code == 409
    assert start(attendant, 999999).status_code == 404


# ---------------------------------------------------------- fluxo completo
def test_full_flow_receipt_and_item_returned(app, make_item, sent_codes, attendant):
    item = make_item()
    before = user_score("carlos@ufpi.edu.br")
    r = start(attendant, item)
    assert r.status_code == 201
    body = r.get_json()
    d = body["delivery"]
    assert d["status"] == "PENDING" and d["cpfMasked"] == "***.982.247-**" and d["emailMasked"] == "m***@exemplo.com"
    assert body["email"] == {"sent": True, "backend": "console", "error": None}
    assert len(sent_codes) == 1 and sent_codes[0]["to"] == "maria@exemplo.com"
    code = code_of(sent_codes)
    assert code not in r.get_data(as_text=True)                        # o código NUNCA vai na resposta da API
    assert "529" not in r.get_data(as_text=True).replace("***.982.247", "")   # nem o CPF completo
    assert attendant.get(f"/api/deliveries/{d['id']}/receipt").status_code == 404      # sem termo antes de confirmar

    wrong = "000000" if code != "000000" else "111111"
    r = attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": wrong})
    assert r.status_code == 422 and "Restam 4" in r.get_json()["error"]
    assert attendant.get(f"/api/items/{item}").get_json()["item"]["status"] != "RETURNED"

    r = attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": code})
    assert r.status_code == 200
    done = r.get_json()["delivery"]
    assert done["status"] == "COMPLETED" and done["confirmedAt"] and done["verificationCode"]
    assert [e["action"] for e in done["events"]] == ["CREATED", "CODE_SENT", "CODE_WRONG", "CONFIRMED"]

    # item devolvido pelo fluxo EXISTENTE (pontuação do achador + linha do tempo sem dados pessoais)
    detail = attendant.get(f"/api/items/{item}").get_json()
    assert detail["item"]["status"] == "RETURNED"
    assert user_score("carlos@ufpi.edu.br") == before + 40
    notes = " ".join(e["note"] for e in detail["timeline"])
    assert done["receiptNumber"] in notes and "982" not in notes and "Maria" not in notes

    # termo em PDF com os campos exigidos
    pdf = attendant.get(f"/api/deliveries/{d['id']}/receipt")
    assert pdf.status_code == 200 and pdf.mimetype == "application/pdf"
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.data)).pages)
    assert f"ESQ-{item:05d}" in text and "***.982.247-**" in text and "ATD-2024-0117" in text and "Renata Nunes" in text
    assert VALID_CPF not in text and "52998224725" not in text.replace(" ", "")

    # código é de uso único; entrega concluída não aceita novas ações
    assert attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": code}).status_code == 409
    assert attendant.post(f"/api/deliveries/{d['id']}/cancel").status_code == 409
    assert start(attendant, item).status_code == 409                  # item já devolvido


def test_cannot_start_second_delivery_while_pending(app, make_item, sent_codes, attendant):
    item = make_item()
    first = start(attendant, item).get_json()["delivery"]
    r = start(attendant, item)
    assert r.status_code == 409 and f"#{first['id']}" in r.get_json()["error"]
    assert attendant.post(f"/api/deliveries/{first['id']}/cancel").status_code == 200
    assert start(attendant, item).status_code == 201                  # depois de cancelar, pode iniciar outra


# ---------------------------------------------------- segurança do código
def test_lockout_after_five_wrong_codes(app, make_item, sent_codes, attendant):
    d = start(attendant, make_item()).get_json()["delivery"]
    real = code_of(sent_codes)
    wrong = "123456" if real != "123456" else "654321"
    for i in range(4):
        assert attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": wrong}).status_code == 422
    r = attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": wrong})
    assert r.status_code == 429
    assert attendant.get(f"/api/deliveries/{d['id']}").get_json()["delivery"]["status"] == "CANCELLED"
    assert attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": real}).status_code == 409   # nem o código certo vale


def test_expired_code_then_resend(app, make_item, sent_codes, attendant):
    d = start(attendant, make_item()).get_json()["delivery"]
    old = code_of(sent_codes)
    row = repo.get_delivery(d["id"])
    row.code_expires_at = utcnow() - timedelta(minutes=1)
    row.code_sent_at = utcnow() - timedelta(minutes=5)
    repo.save(row)
    r = attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": old})
    assert r.status_code == 410
    assert attendant.get(f"/api/deliveries/{d['id']}").get_json()["delivery"]["codeExpired"] is True
    assert attendant.post(f"/api/deliveries/{d['id']}/resend").status_code == 200
    new = code_of(sent_codes)
    assert len(sent_codes) == 2
    if new != old:
        assert attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": old}).status_code == 422   # código antigo invalidado
    assert attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": new}).status_code == 200


def test_resend_cooldown_and_limit(app, make_item, sent_codes, attendant):
    d = start(attendant, make_item()).get_json()["delivery"]
    r = attendant.post(f"/api/deliveries/{d['id']}/resend")
    assert r.status_code == 429 and "Aguarde" in r.get_json()["error"]
    for _ in range(sec.MAX_RESENDS):
        row = repo.get_delivery(d["id"]); row.code_sent_at = utcnow() - timedelta(minutes=5); repo.save(row)
        assert attendant.post(f"/api/deliveries/{d['id']}/resend").status_code == 200
    row = repo.get_delivery(d["id"]); row.code_sent_at = utcnow() - timedelta(minutes=5); repo.save(row)
    r = attendant.post(f"/api/deliveries/{d['id']}/resend")
    assert r.status_code == 429 and "Limite" in r.get_json()["error"]


def test_email_failure_keeps_delivery_and_allows_resend(app, make_item, attendant, monkeypatch):
    from app.delivery import service
    from app.delivery.email_service import EmailError
    calls = []

    def flaky(**kw):
        calls.append(kw)
        if len(calls) == 1:
            raise EmailError("smtp down")
        return "smtp"
    monkeypatch.setattr(service, "send_confirmation_code", flaky)
    r = start(attendant, make_item())
    assert r.status_code == 201 and r.get_json()["email"]["sent"] is False and "Reenviar" in r.get_json()["email"]["error"]
    d = r.get_json()["delivery"]
    row = repo.get_delivery(d["id"]); row.code_sent_at = utcnow() - timedelta(minutes=5); repo.save(row)
    r = attendant.post(f"/api/deliveries/{d['id']}/resend")
    assert r.get_json()["email"]["sent"] is True
    assert attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": calls[-1]["code"]}).status_code == 200


# ------------------------------------------------ acesso a documento / termo
def test_access_control_for_document_and_receipt(app, make_item, sent_codes, attendant):
    item = make_item()
    d = start(attendant, item).get_json()["delivery"]
    attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": code_of(sent_codes)})

    doc = attendant.get(f"/api/deliveries/{d['id']}/document")
    assert doc.status_code == 200 and doc.mimetype == "image/jpeg" and doc.data == JPEG
    assert "no-store" in doc.headers["Cache-Control"]

    admin = persona_client(app, "admin@ufpi.edu.br")                              # admin audita
    assert admin.get(f"/api/deliveries/{d['id']}/document").status_code == 200
    assert admin.get(f"/api/deliveries/{d['id']}/receipt").status_code == 200
    assert len(admin.get("/api/deliveries").get_json()["deliveries"]) >= 1
    assert admin.post(f"/api/deliveries/{d['id']}/cancel").status_code == 403       # mas não altera

    for other in ("ana@ufpi.edu.br", "carlos@ufpi.edu.br"):                         # comunidade: nada
        c = persona_client(app, other)
        for path in ("", "/document", "/receipt"):
            assert c.get(f"/api/deliveries/{d['id']}{path}").status_code == 403
        assert c.get("/api/deliveries").status_code == 403
    for path in ("", "/document", "/receipt"):
        assert app.test_client().get(f"/api/deliveries/{d['id']}{path}").status_code == 401


def test_other_attendant_cannot_touch_delivery(app, make_item, sent_codes, attendant):
    from app.auth import hash_password
    from app.repositories.users import create_user, find_user_by_email
    if not find_user_by_email("atendente2@ufpi.edu.br"):
        create_user(name="Segundo Atendente", email="atendente2@ufpi.edu.br", password_hash=hash_password("senha-12345"), role="OPERATOR_POST")
    other = app.test_client()
    assert other.post("/api/auth/login", json={"email": "atendente2@ufpi.edu.br", "password": "senha-12345"}).status_code == 200
    other.put("/api/attendant/registration", json={"registrationNumber": "ATD-OUTRO-02"})
    d = start(attendant, make_item()).get_json()["delivery"]
    assert other.get(f"/api/deliveries/{d['id']}").status_code == 403
    for action in ("confirm", "resend", "cancel"):
        assert other.post(f"/api/deliveries/{d['id']}/{action}", json={"code": code_of(sent_codes)}).status_code == 403
    assert all(x["attendantRegistration"] == "ATD-OUTRO-02" for x in other.get("/api/deliveries").get_json()["deliveries"])   # só vê as próprias
    r = other.put("/api/attendant/registration", json={"registrationNumber": "ATD-2024-0117"})
    assert r.status_code == 409                                                       # matrícula única


# -------------------------------------------------------- contestação / auditoria
def test_verify_for_contested_delivery(app, make_item, sent_codes, attendant):
    d = start(attendant, make_item()).get_json()["delivery"]
    attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": code_of(sent_codes)})
    ok = attendant.post(f"/api/deliveries/{d['id']}/verify", json={"cpf": VALID_CPF}).get_json()
    assert ok["cpfMatches"] is True and ok["receiptIntact"] is True and ok["documentIntact"] is True
    assert attendant.post(f"/api/deliveries/{d['id']}/verify", json={"cpf": "390.533.447-05"}).get_json()["cpfMatches"] is False
    assert attendant.post(f"/api/deliveries/{d['id']}/verify", json={"cpf": "000"}).get_json()["cpfMatches"] is False
    # adulteração do PDF ou do documento é detectada
    receipt = repo.get_receipt(d["id"]); receipt.pdf = receipt.pdf + b"x"; db.commit()
    assert attendant.post(f"/api/deliveries/{d['id']}/verify", json={}).get_json()["receiptIntact"] is False
    document = repo.get_document(d["id"]); document.data = b"adulterado"; db.commit()
    assert attendant.post(f"/api/deliveries/{d['id']}/verify", json={}).get_json()["documentIntact"] is False


def test_database_never_stores_plain_cpf_or_code(app, make_item, sent_codes, attendant):
    d = start(attendant, make_item()).get_json()["delivery"]
    row = repo.get_delivery(d["id"])
    values = " ".join(str(getattr(row, c.name)) for c in m.Delivery.__table__.columns)
    assert "52998224725" not in values and VALID_CPF not in values and code_of(sent_codes) not in values.split()
    assert row.recipient_cpf_masked == "***.982.247-**" and len(row.code_hash) == 64


def test_receipt_survives_item_deletion(app, make_item, sent_codes, attendant):
    item = make_item()
    d = start(attendant, item).get_json()["delivery"]
    attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": code_of(sent_codes)})
    db.delete(db.get(Item, item)); db.commit(); db.expire_all()
    got = attendant.get(f"/api/deliveries/{d['id']}").get_json()["delivery"]
    assert got["itemId"] is None and got["itemCode"] == f"ESQ-{item:05d}" and got["status"] == "COMPLETED"
    assert attendant.get(f"/api/deliveries/{d['id']}/receipt").status_code == 200


def test_existing_quick_return_flow_untouched(app, make_item, attendant):
    """O botão antigo 'Devolvido' continua funcionando (política opcional vem em outro commit)."""
    item = make_item()
    assert attendant.patch(f"/api/items/{item}", json={"status": "RETURNED"}).status_code == 200
