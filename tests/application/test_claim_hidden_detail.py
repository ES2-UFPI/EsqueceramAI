"""US04 #28 - o detalhe confidencial nunca aparece na listagem nem no detalhe do item."""
import io
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from application.models import ItemSecret, db
from conftest import persona_client

SECRET = {
    "secretDetail": "Arranhão em forma de 'X' na tampa traseira, perto da câmera.",
    "secretQuestion": "Qual é a cor do adesivo dentro da capa?",
    "secretAnswer": "Adesivo do Sport Club do Recife",
}


def _multipart(data):
    payload = {k: str(v) for k, v in data.items() if v is not None}
    payload.setdefault("image", (io.BytesIO(b""), ""))
    return payload


def item_form(**over):
    data = {"type": "FOUND", "category": "ELECTRONIC", "title": "Mochila preta encontrada na biblioteca",
            "description": "Mochila preta com caderno e chaves dentro, achada na Biblioteca Central.",
            "location": "Biblioteca Central", "occurredAt": datetime.now(timezone.utc).date().isoformat()}
    data.update(over)
    return data


@pytest.fixture()
def item_with_secret(app):
    creator = persona_client(app, "carlos@ufpi.edu.br")
    created = creator.post("/api/items", data=_multipart(item_form(**SECRET)), content_type="multipart/form-data")
    assert created.status_code == 201, created.json
    item_id = created.json["item"]["id"]
    yield item_id
    db.query(ItemSecret).filter(ItemSecret.item_id == item_id).delete(synchronize_session=False)
    db.commit()


@pytest.mark.parametrize("path", ["/api/items", "/api/items?tipo=ENCONTRADO", "/api/items/{id}"])
def test_api_never_returns_the_secret(item_with_secret, app, path):
    body = app.test_client().get(path.format(id=item_with_secret)).get_data(as_text=True)
    assert SECRET["secretDetail"] not in body
    assert SECRET["secretQuestion"] not in body
    assert SECRET["secretAnswer"] not in body


def test_public_pages_never_render_the_secret(item_with_secret, app):
    for path in ("/", "/itens", f"/itens/{item_with_secret}"):
        body = app.test_client().get(path).get_data(as_text=True)
        assert SECRET["secretDetail"] not in body, path
        assert SECRET["secretAnswer"] not in body, path


def test_owner_detail_page_shows_a_hint_but_not_the_detail(item_with_secret, app):
    owner = persona_client(app, "carlos@ufpi.edu.br")
    body = owner.get(f"/itens/{item_with_secret}").get_data(as_text=True)
    assert "nunca aparecem nesta página" in body
    assert SECRET["secretDetail"] not in body
    assert SECRET["secretAnswer"] not in body


def test_other_user_sees_the_item_without_the_detail(item_with_secret, app):
    other = persona_client(app, "ana@ufpi.edu.br")
    body = other.get(f"/itens/{item_with_secret}").get_data(as_text=True)
    assert SECRET["secretDetail"] not in body
    assert SECRET["secretAnswer"] not in body
