import io
import re

import pytest

from application.delivery import models as m
from application.delivery import repository as repo
from application.delivery.seed import DEMO_REGISTRATION, ensure_demo_attendant
from application.models import db
from conftest import JPEG, VALID_CPF, persona_client


def form(item_id, **over):
    data = {"itemId": str(item_id), "recipientName": "Maria de Sousa Lima", "cpf": VALID_CPF, "email": "maria@exemplo.com",
            "document": (io.BytesIO(JPEG), "rg.jpg", "image/jpeg")}
    data.update(over)
    return data


def post_new(c, item_id, **over):
    return c.post("/painel/entregas/nova", data=form(item_id, **over), content_type="multipart/form-data")


def test_checkout_pages_restricted_to_attendant(app):
    anon = app.test_client()
    for path in ("/painel/entregas/", "/painel/entregas/nova"):
        r = anon.get(path)
        assert r.status_code == 302 and "/entrar" in r.headers["Location"]
    for persona in ("ana@ufpi.edu.br", "carlos@ufpi.edu.br"):                 # comunidade: nada
        c = persona_client(app, persona)
        for path in ("/painel/entregas/", "/painel/entregas/nova", "/painel/entregas/1"):
            r = c.get(path)
            assert r.status_code == 302 and r.headers["Location"].endswith("erro=permissao"), (persona, path)
    admin = persona_client(app, "admin@ufpi.edu.br")                           # admin audita, mas não faz checkout
    assert admin.get("/painel/entregas/").status_code == 200
    assert admin.get("/painel/entregas/nova").headers["Location"].endswith("erro=permissao")
    assert admin.post("/painel/entregas/nova", data={}).headers["Location"].endswith("erro=permissao")


def test_checkout_form_renders_with_all_fields(app, attendant, make_item):
    item = make_item()
    html = attendant.get(f"/painel/entregas/nova?item={item}").get_data(as_text=True)
    for needle in ('name="itemId"', 'name="recipientName"', 'name="cpf"', 'name="email"', 'name="document"',
                   'capture="environment"', "Capturar com a câmera", "ATD-2024-0117", f'value="{item}" selected', "delivery.js"):
        assert needle in html, needle
    assert attendant.get("/painel/entregas/delivery-static/delivery.js").status_code == 200


def test_form_shows_validation_errors(app, attendant, make_item, sent_codes):
    item = make_item()
    r = post_new(attendant, item, cpf="111.111.111-11")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "dígitos verificadores" in html and "Confira os campos" in html
    assert 'value="Maria de Sousa Lima"' in html                               # não perde o que foi digitado
    r = post_new(attendant, item, cpf="", email="x", document=None)
    html = r.get_data(as_text=True)
    assert "Informe o CPF" in html and "e-mail válido" in html and "Anexe ou capture" in html
    assert sent_codes == []


def test_full_checkout_through_pages(app, attendant, make_item, sent_codes):
    item = make_item()
    r = post_new(attendant, item)
    assert r.status_code == 302
    confirm_url = r.headers["Location"]
    assert re.fullmatch(r"/painel/entregas/\d+/confirmar", confirm_url)
    delivery_id = int(confirm_url.split("/")[3])

    page = attendant.get(confirm_url).get_data(as_text=True)
    assert "m***@exemplo.com" in page and "***.982.247-**" in page and 'name="code"' in page and "Tentativas restantes: <b>5</b>" in page
    code = sent_codes[-1]["code"]
    assert code not in page and VALID_CPF not in page                           # código e CPF nunca na tela

    wrong = "000000" if code != "000000" else "111111"
    r = attendant.post(confirm_url, data={"code": wrong})
    assert r.status_code == 200 and "Código incorreto. Restam 4" in r.get_data(as_text=True)
    r = attendant.post(confirm_url, data={"code": "12"})
    assert r.status_code == 200 and "6 dígitos" in r.get_data(as_text=True)

    r = attendant.post(confirm_url, data={"code": code})
    assert r.status_code == 302 and r.headers["Location"] == f"/painel/entregas/{delivery_id}"
    detail = attendant.get(r.headers["Location"]).get_data(as_text=True)
    for needle in ("Concluída", "Baixar termo em PDF", f"/api/deliveries/{delivery_id}/receipt", "ATD-2024-0117",
                   "***.982.247-**", "CONFIRMED", "Código de verificação do termo", "SHA-256"):
        assert needle in detail, needle
    assert VALID_CPF not in detail and "52998224725" not in detail
    assert attendant.get(f"/api/deliveries/{delivery_id}/receipt").mimetype == "application/pdf"
    assert attendant.get(confirm_url).status_code == 302                       # já concluída: volta ao detalhe

    # conferência de CPF na contestação
    ok = attendant.post(f"/painel/entregas/{delivery_id}/verificar", data={"cpf": VALID_CPF}).get_data(as_text=True)
    assert "confere com o retirante" in ok and "Termo íntegro: <b>sim</b>" in ok
    bad = attendant.post(f"/painel/entregas/{delivery_id}/verificar", data={"cpf": "390.533.447-05"}).get_data(as_text=True)
    assert "NÃO confere" in bad
    assert "ESQ-" in attendant.get("/painel/entregas/").get_data(as_text=True)


def test_resend_and_cancel_through_pages(app, attendant, make_item, sent_codes):
    item = make_item()
    url = post_new(attendant, item).headers["Location"]
    r = attendant.post(url.replace("confirmar", "reenviar"), follow_redirects=True)      # cooldown de 60 s
    assert "Aguarde" in r.get_data(as_text=True)
    r = attendant.post(url.replace("confirmar", "cancelar"), follow_redirects=True)
    assert "Entrega cancelada" in r.get_data(as_text=True) and r.request.path == "/painel/entregas/"
    r = attendant.post(url, data={"code": sent_codes[-1]["code"]}, follow_redirects=True)  # cancelada: não confirma
    assert "cancelada ou expirou" in r.get_data(as_text=True)


def test_registration_gate_in_form(app, make_item):
    c = persona_client(app, "operador@ufpi.edu.br")
    db.query(m.AttendantProfile).delete(); db.commit()
    html = c.get("/painel/entregas/nova").get_data(as_text=True)
    assert "Cadastre sua matrícula" in html and 'name="itemId"' not in html          # formulário bloqueado
    r = c.post("/painel/entregas/matricula", data={"registrationNumber": "x", "next": "/painel/entregas/nova"}, follow_redirects=True)
    assert "Use de 4 a 20 caracteres" in r.get_data(as_text=True)
    r = c.post("/painel/entregas/matricula", data={"registrationNumber": "mat-77", "next": "//evil.com"})
    assert r.headers["Location"].endswith("/painel/entregas/nova")                   # next externo é ignorado
    assert 'name="itemId"' in c.get("/painel/entregas/nova").get_data(as_text=True)
    c.put("/api/attendant/registration", json={"registrationNumber": DEMO_REGISTRATION})


def test_demo_attendant_seed_is_idempotent_and_never_overwrites(app):
    from sqlalchemy import select
    from application.models import User
    op = db.execute(select(User).where(User.email == "operador@ufpi.edu.br")).scalar_one()
    db.query(m.AttendantProfile).delete(); db.commit()
    ensure_demo_attendant(); ensure_demo_attendant()
    assert repo.get_registration(op.id) == DEMO_REGISTRATION
    repo.set_registration(op.id, "CUSTOM-123")
    ensure_demo_attendant()
    assert repo.get_registration(op.id) == "CUSTOM-123"
    repo.set_registration(op.id, DEMO_REGISTRATION)


def test_entry_points_in_existing_pages(app, attendant, make_item):
    item = make_item()
    assert "/painel/entregas" in attendant.get("/painel").get_data(as_text=True)                       # menu lateral
    assert f"/painel/entregas/nova?item={item}" in attendant.get(f"/itens/{item}").get_data(as_text=True)
    assert "Registrar entrega" in attendant.get("/painel/operador").get_data(as_text=True)
    community = persona_client(app, "ana@ufpi.edu.br")
    assert "/painel/entregas" not in community.get("/painel").get_data(as_text=True)
    assert "Registrar entrega (CPF" not in community.get(f"/itens/{item}").get_data(as_text=True)


@pytest.mark.parametrize("persona", ["ana@ufpi.edu.br", "carlos@ufpi.edu.br", "operador@ufpi.edu.br", "admin@ufpi.edu.br"])
def test_existing_pages_still_work(app, persona):
    """Regressão: nenhuma página/API anterior foi afetada pelo módulo novo."""
    c = persona_client(app, persona)
    for path in ("/", "/itens", "/itens/1", "/painel", "/painel/itens", "/painel/itens/novo", "/painel/matches",
                 "/painel/notificacoes", "/painel/perfil", "/painel/pontos", "/api/items", "/api/matches",
                 "/api/notifications", "/api/points", "/api/health", "/api/auth/me"):
        assert c.get(path).status_code == 200, (persona, path)
    staff = persona in ("operador@ufpi.edu.br", "admin@ufpi.edu.br")
    assert c.get("/painel/operador").status_code == (200 if staff else 302)
    assert c.get("/painel/admin").status_code == (200 if persona == "admin@ufpi.edu.br" else 302)
