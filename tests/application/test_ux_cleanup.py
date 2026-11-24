from datetime import datetime, timezone

from application import domain as D
from conftest import persona_client


def test_item_form_prefills_date_and_removes_unnecessary_secret_detail(app):
    authed = persona_client(app, "ana@ufpi.edu.br")
    html = authed.get("/painel/itens/novo?tipo=FOUND").get_data(as_text=True)
    today = D.to_input_date(datetime.now(timezone.utc))

    assert f'value="{today}"' in html
    assert 'name="title" required' in html
    assert 'name="description" required' in html
    assert 'name="location" required' in html
    assert 'name="occurredAt" required' in html
    assert "secretDetail" not in html
    assert "Detalhe confidencial" not in html
    assert "data-geo-map-toggle" in html
    assert 'id="item-geo-map-box" hidden' in html
    assert 'data-has-error="0"' in html

    err_html = authed.post(
        "/painel/itens/novo",
        data={"type": "FOUND", "category": "ACCESSORY", "title": "ab", "description": "curta", "location": "CT", "occurredAt": today},
    ).get_data(as_text=True)
    assert 'data-has-error="1"' in err_html


def test_found_item_can_set_question_without_secret_detail(app):
    authed = persona_client(app, "ana@ufpi.edu.br")
    resp = authed.post(
        "/api/items",
        data={
            "type": "FOUND",
            "category": "ACCESSORY",
            "title": "Garrafa azul encontrada",
            "description": "Garrafa térmica azul deixada na sala",
            "location": "Centro de Tecnologia (CT)",
            "occurredAt": "2026-11-20",
            "secretQuestion": "Qual adesivo tem na garrafa?",
            "secretAnswer": "Gato preto",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201


def test_cadastrar_and_perfil_cleaned_up(app, client):
    cad_html = client.get("/cadastrar").get_data(as_text=True)
    assert "usado na recuperação de senha" not in cad_html
    assert "Telefone (opcional)" in cad_html

    authed = persona_client(app, "ana@ufpi.edu.br")
    perfil_html = authed.get("/painel/perfil").get_data(as_text=True)
    assert "avatarUrl" not in perfil_html
    assert "URL da foto" not in perfil_html


def test_item_hero_image_uses_object_fit_contain_to_avoid_cropping(client):
    css = client.get("/static/style.css").get_data(as_text=True)
    assert ".item-hero-thumb{height:auto!important" in css
    assert "object-fit:contain" in css