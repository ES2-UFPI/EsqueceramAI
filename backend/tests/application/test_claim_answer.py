"""US04 #30 - a resposta é validada antes de avisar o dono e liberar a retirada."""
import io
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from application.models import CLAIM_VERIFIED, ItemClaim, ItemSecret, db
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
    db.query(ItemClaim).filter(ItemClaim.item_id == item_id).delete(synchronize_session=False)
    db.query(ItemSecret).filter(ItemSecret.item_id == item_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture()
def claimant(app):
    return persona_client(app, "ana@ufpi.edu.br")


def test_correct_answer_validates_ownership(item_with_secret, claimant):
    response = claimant.post(f"/api/items/{item_with_secret}/claim",
                             json={"answer": "adesivo do sport club do recife!"})
    assert response.status_code == 200
    assert response.json["verified"] is True
    claim = db.execute(select(ItemClaim).where(ItemClaim.item_id == item_with_secret)).scalar_one()
    assert claim.status == CLAIM_VERIFIED and claim.verified_at is not None


def test_wrong_answer_is_rejected(item_with_secret, claimant):
    response = claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": "adesivo do Náutico"})
    assert response.status_code == 422
    # A resposta é genérica, sem revelar o valor esperado; o contador restante vem do #31.
    assert response.json["details"]["answer"] == ["Resposta incorreta. Restam 2 tentativa(s)."]


def test_notification_and_email_only_after_the_right_answer(item_with_secret, claimant, _capture_emails):
    claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": "chute"})
    assert not [m for m in _capture_emails if "Posse validada" in m["subject"]]

    claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": SECRET["secretAnswer"]})
    sent = [m for m in _capture_emails if "Posse validada" in m["subject"]]
    assert len(sent) == 1
    assert sent[0]["to"] == "carlos@ufpi.edu.br"
    assert "Ana Beatriz Lima" in sent[0]["body"], "o aviso de confirmação só sai depois de validar"


def test_owner_is_notified_inside_the_platform(item_with_secret, claimant, app):
    claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": SECRET["secretAnswer"]})
    owner = persona_client(app, "carlos@ufpi.edu.br")
    notices = owner.get("/api/notifications").json["notifications"]
    assert any("validou a posse" in n["title"] for n in notices)


def test_page_shows_validation_state(item_with_secret, claimant):
    claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": SECRET["secretAnswer"]})
    page = claimant.get(f"/itens/{item_with_secret}").get_data(as_text=True)
    assert "Você validou a posse deste item" in page
    assert SECRET["secretDetail"] not in page


def test_form_post_validates_and_flashes_result(item_with_secret, claimant):
    response = claimant.post(f"/itens/{item_with_secret}/reivindicar", data={"answer": SECRET["secretAnswer"]},
                             follow_redirects=True)
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Posse validada" in page
    assert SECRET["secretDetail"] not in page


def test_form_post_shows_error_on_wrong_answer(item_with_secret, claimant):
    response = claimant.post(f"/itens/{item_with_secret}/reivindicar", data={"answer": "errado"},
                             follow_redirects=True)
    assert "Resposta incorreta" in response.get_data(as_text=True)


def test_answer_requires_login_and_question(item_with_secret, app):
    anonymous = app.test_client().post(f"/api/items/{item_with_secret}/claim", json={"answer": "x"})
    assert anonymous.status_code == 401
