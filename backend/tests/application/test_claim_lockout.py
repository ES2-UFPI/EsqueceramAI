"""US04 #31 - bloqueio de novas tentativas após três respostas incorretas."""
import io
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from application.models import CLAIM_BLOCKED, ItemClaim, ItemSecret, db
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


def test_each_wrong_answer_reports_remaining_attempts(item_with_secret, claimant):
    for expected_left in (2, 1):
        response = claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": "chute errado"})
        assert response.status_code == 422
        assert f"Restam {expected_left}" in response.json["error"]


def test_third_wrong_answer_blocks_the_user(item_with_secret, claimant):
    claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": "chute 1"})
    claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": "chute 2"})
    blocked = claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": "chute 3"})
    assert blocked.status_code == 429

    claim = db.execute(select(ItemClaim).where(ItemClaim.item_id == item_with_secret)).scalar_one()
    assert claim.status == CLAIM_BLOCKED and claim.attempts == 3


def test_blocked_user_cannot_answer_even_correctly(item_with_secret, claimant):
    for _ in range(3):
        claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": "chute"})
    locked = claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": SECRET["secretAnswer"]})
    assert locked.status_code == 429


def test_page_shows_the_lock_state(item_with_secret, claimant):
    for _ in range(3):
        claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": "chute"})
    page = claimant.get(f"/itens/{item_with_secret}").get_data(as_text=True)
    assert "Limite de tentativas atingido" in page
    assert f"/itens/{item_with_secret}/reivindicar" not in page


def test_a_different_user_is_not_affected_by_someone_elses_block(item_with_secret, claimant, app):
    for _ in range(3):
        claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": "chute"})
    # maria/joao/lucas não são personas de login: cadastra um usuário de verdade
    other = app.test_client()
    assert other.post("/api/auth/register", json={"name": "Maria Teste", "email": "maria.blocked@ufpi.edu.br",
                                                  "password": "senha-segura-123"}).status_code == 201
    assert other.post("/api/auth/login", json={"email": "maria.blocked@ufpi.edu.br",
                                               "password": "senha-segura-123"}).status_code == 200
    ok = other.post(f"/api/items/{item_with_secret}/claim", json={"answer": SECRET["secretAnswer"]})
    assert ok.status_code == 200 and ok.json["verified"] is True


def test_correct_answer_is_not_blocked_by_earlier_mistakes(item_with_secret, claimant):
    claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": "chute 1"})
    claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": "chute 2"})
    ok = claimant.post(f"/api/items/{item_with_secret}/claim", json={"answer": SECRET["secretAnswer"]})
    assert ok.status_code == 200
    assert ok.json["verified"] is True
