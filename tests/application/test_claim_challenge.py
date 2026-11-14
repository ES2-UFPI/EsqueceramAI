"""US04 #29 - a pergunta-chave é exibida a quem vai reivindicar o item."""
import io
from datetime import datetime, timezone

import pytest

from application.models import ItemSecret, db
from conftest import persona_client

SECRET = {
    "secretDetail": "Arranhão em forma de 'X' na tampa traseira, perto da câmera.",
    "secretQuestion": "Qual é a cor do adesivo dentro da capa?",
    "secretAnswer": "Adesivo do Sport Club do Recife",
}


def item_form(**over):
    data = {"type": "FOUND", "category": "ELECTRONIC", "title": "Mochila preta encontrada na biblioteca",
            "description": "Mochila preta com caderno e chaves dentro, achada na Biblioteca Central.",
            "location": "Biblioteca Central", "occurredAt": datetime.now(timezone.utc).date().isoformat()}
    data.update(over)
    return data


def _multipart(data):
    payload = {k: str(v) for k, v in data.items() if v is not None}
    payload.setdefault("image", (io.BytesIO(b""), ""))
    return payload


@pytest.fixture()
def item_with_secret(app):
    creator = persona_client(app, "carlos@ufpi.edu.br")
    created = creator.post("/api/items", data=_multipart(item_form(**SECRET)), content_type="multipart/form-data")
    assert created.status_code == 201, created.json
    item_id = created.json["item"]["id"]
    yield item_id
    db.query(ItemSecret).filter(ItemSecret.item_id == item_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture()
def item_without_secret(app):
    creator = persona_client(app, "carlos@ufpi.edu.br")
    created = creator.post("/api/items", data=_multipart(item_form()), content_type="multipart/form-data")
    item_id = created.json["item"]["id"]
    yield item_id
    db.query(ItemSecret).filter(ItemSecret.item_id == item_id).delete(synchronize_session=False)
    db.commit()


def test_challenge_returns_question_but_never_the_detail(item_with_secret, app):
    claimant = persona_client(app, "ana@ufpi.edu.br")
    response = claimant.get(f"/api/items/{item_with_secret}/challenge")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert SECRET["secretQuestion"] in body
    assert SECRET["secretDetail"] not in body
    assert SECRET["secretAnswer"] not in body


def test_detail_page_shows_the_question_to_the_claimant(item_with_secret, app):
    claimant = persona_client(app, "ana@ufpi.edu.br")
    page = claimant.get(f"/itens/{item_with_secret}").get_data(as_text=True)
    assert SECRET["secretQuestion"] in page
    assert f"/itens/{item_with_secret}/reivindicar" in page
    assert SECRET["secretDetail"] not in page
    assert SECRET["secretAnswer"] not in page


def test_anonymous_visitor_does_not_see_the_question(item_with_secret, app):
    page = app.test_client().get(f"/itens/{item_with_secret}").get_data(as_text=True)
    assert SECRET["secretQuestion"] not in page


def test_owner_is_not_invited_to_claim_own_item(item_with_secret, app):
    owner = persona_client(app, "carlos@ufpi.edu.br")
    assert owner.get(f"/api/items/{item_with_secret}/challenge").status_code == 409
    page = owner.get(f"/itens/{item_with_secret}").get_data(as_text=True)
    assert f"/itens/{item_with_secret}/reivindicar" not in page


def test_item_without_question_has_no_challenge(item_without_secret, app):
    claimant = persona_client(app, "ana@ufpi.edu.br")
    assert claimant.get(f"/api/items/{item_without_secret}/challenge").status_code == 404
    page = claimant.get(f"/itens/{item_without_secret}").get_data(as_text=True)
    assert "/reivindicar" not in page
