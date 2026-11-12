"""US04 - Validação de propriedade por pergunta-chave / detalhe oculto (#26, #27, #28, #29, #30, #31)."""
import io
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from application.models import CLAIM_BLOCKED, CLAIM_VERIFIED, ItemClaim, ItemSecret, User, db
from application.services import claim_service
from conftest import persona_client

SECRET = {
    "secretDetail": "Arranhão em forma de 'X' na tampa traseira, perto da câmera.",
    "secretQuestion": "Qual é a cor do adesivo dentro da capa?",
    "secretAnswer": "Adesivo do Sport Club do Recife",
}


def item_form(**over):
    """Multipart mínimo aceito por `parse_item_form` (mesmos campos da tela de cadastro)."""
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
def creator(app):
    """Usuário comum que registra o item encontrado com detalhe oculto."""
    return persona_client(app, "carlos@ufpi.edu.br")


@pytest.fixture()
def claimant(app):
    return persona_client(app, "ana@ufpi.edu.br")


@pytest.fixture()
def created_item(creator):
    response = creator.post("/api/items", data=_multipart(item_form(**SECRET)), content_type="multipart/form-data")
    assert response.status_code == 201, response.json
    item_id = response.json["item"]["id"]
    yield item_id
    db.query(ItemClaim).filter(ItemClaim.item_id == item_id).delete(synchronize_session=False)
    db.query(ItemSecret).filter(ItemSecret.item_id == item_id).delete(synchronize_session=False)
    db.commit()


# ------------------------------------------------------- #27 cadastro do detalhe
def test_owner_can_register_confidential_detail_and_question(created_item):
    secret = claim_service.get_secret(created_item)
    assert secret is not None
    assert secret.question == SECRET["secretQuestion"]
    assert secret.detail == SECRET["secretDetail"]
    assert secret.answer_hash != SECRET["secretAnswer"]  # resposta nunca em claro


def test_incomplete_secret_block_is_rejected(creator):
    response = creator.post("/api/items", data=_multipart(item_form(secretDetail="Marca de caneta")),
                            content_type="multipart/form-data")
    assert response.status_code == 422
    assert "secretQuestion" in response.json["details"]


def test_lost_item_cannot_have_hidden_detail(creator):
    response = creator.post("/api/items", data=_multipart(item_form(type="LOST", **SECRET)),
                            content_type="multipart/form-data")
    assert response.status_code == 422
    assert "encontrados" in response.json["error"]


# ------------------------------------------------- #28 nada vaza nas visualizações
def test_secret_never_appears_in_listing_or_detail(created_item, app):
    anonymous = app.test_client()
    listing = anonymous.get("/api/items?tipo=ENCONTRADO").get_json()
    detail = anonymous.get(f"/api/items/{created_item}").get_json()
    page = anonymous.get(f"/itens/{created_item}")

    for blob in (listing, detail, page.get_data(as_text=True)):
        text = blob if isinstance(blob, str) else str(blob)
        assert SECRET["secretDetail"] not in text
        assert SECRET["secretAnswer"] not in text
        assert SECRET["secretQuestion"] not in text


# ------------------------------------------------------ #29 pergunta para o reclamante
def test_challenge_returns_question_but_not_detail(created_item, claimant):
    response = claimant.get(f"/api/items/{created_item}/challenge")
    assert response.status_code == 200
    body = response.json["challenge"]
    assert body["question"] == SECRET["secretQuestion"]
    assert body["attemptsLeft"] == claim_service.MAX_FAILED_ATTEMPTS
    assert "detail" not in body and SECRET["secretDetail"] not in str(body)


def test_owner_cannot_claim_own_item(created_item, creator):
    response = creator.get(f"/api/items/{created_item}/challenge")
    assert response.status_code == 409


# ------------------------------------------------------ #30 valida a resposta
def test_correct_answer_validates_ownership(created_item, claimant):
    response = claimant.post(f"/api/items/{created_item}/claim", json={"answer": "adesivo do sport club do recife!"})
    assert response.status_code == 200
    assert response.json["verified"] is True
    claim = db.execute(select(ItemClaim).where(ItemClaim.item_id == created_item)).scalar_one()
    assert claim.status == CLAIM_VERIFIED and claim.verified_at is not None


def test_wrong_answer_is_rejected_with_remaining_attempts(created_item, claimant):
    response = claimant.post(f"/api/items/{created_item}/claim", json={"answer": "adesivo do Náutico"})
    assert response.status_code == 422
    assert response.json["details"]["answer"] == ["Resposta incorreta. Restam 2 tentativa(s)."]


# --------------------------------- #30 só valida a posse depois da resposta certa
def test_confirmation_email_only_after_correct_answer(created_item, claimant, _capture_emails):
    claimant.post(f"/api/items/{created_item}/claim", json={"answer": "chute"})
    assert not [m for m in _capture_emails if "Posse validada" in m["subject"]]

    claimant.post(f"/api/items/{created_item}/claim", json={"answer": SECRET["secretAnswer"]})
    sent = [m for m in _capture_emails if "Posse validada" in m["subject"]]
    assert len(sent) == 1
    assert sent[0]["to"] == "carlos@ufpi.edu.br"
    assert "Ana Beatriz Lima" in sent[0]["body"]


# ------------------------------------------------- #31 bloqueio após três erros
def test_three_wrong_answers_block_further_attempts(created_item, claimant):
    for expected_left in (2, 1):
        response = claimant.post(f"/api/items/{created_item}/claim", json={"answer": "chute errado"})
        assert response.status_code == 422
        assert f"Restam {expected_left}" in response.json["error"]

    blocked = claimant.post(f"/api/items/{created_item}/claim", json={"answer": "chute errado"})
    assert blocked.status_code == 429

    # nem a resposta certa destrava depois do bloqueio
    locked = claimant.post(f"/api/items/{created_item}/claim", json={"answer": SECRET["secretAnswer"]})
    assert locked.status_code == 429
    assert claimant.get(f"/api/items/{created_item}/challenge").json["challenge"]["blocked"] is True


def test_opposite_matches_are_compact_and_do_not_leak_secret(created_item, app):
    """Ciclo de correspondência: o `found` casado não pode expor o detalhe oculto."""
    owner = db.execute(select(User).where(User.email == "carlos@ufpi.edu.br")).scalar_one()
    bystander = db.execute(select(User).where(User.email == "ana@ufpi.edu.br")).scalar_one()
    from application.services import matching_service
    from conftest import persona_client as login

    client = login(app, bystander.email)
    lost = client.post("/api/items", data=_multipart(item_form(
        type="LOST", title="Mochila preta perdida na biblioteca",
        description="Mochila preta com caderno e chaves, perdi na Biblioteca Central.")),
        content_type="multipart/form-data")
    assert lost.status_code == 201, lost.json
    matches = matching_service.suggestions_for_user(bystander.id, limit=10)
    assert SECRET["secretDetail"] not in str(matches)
    assert owner.id != bystander.id


def test_edit_can_add_secret_later_and_remove_it(creator):
    created = creator.post("/api/items", data=_multipart(item_form()), content_type="multipart/form-data")
    item_id = created.json["item"]["id"]
    try:
        assert claim_service.get_secret(item_id) is None
        edited = creator.patch(f"/api/items/{item_id}", data=_multipart(item_form(**SECRET)),
                               content_type="multipart/form-data")
        assert edited.status_code == 200
        assert claim_service.get_secret(item_id) is not None

        # atualizar o item sem os campos da pergunta não pode apagar o detalhe oculto
        kept = creator.patch(f"/api/items/{item_id}", data=_multipart(item_form(title="Mochila preta com adesivo")),
                             content_type="multipart/form-data")
        assert kept.status_code == 200
        assert claim_service.get_secret(item_id) is not None

        cleaned = creator.patch(f"/api/items/{item_id}", data=_multipart({**item_form(), "secretClear": "1"}),
                                content_type="multipart/form-data")
        assert cleaned.status_code == 200
        assert claim_service.get_secret(item_id) is None
    finally:
        db.query(ItemClaim).filter(ItemClaim.item_id == item_id).delete(synchronize_session=False)
        db.query(ItemSecret).filter(ItemSecret.item_id == item_id).delete(synchronize_session=False)
        db.commit()


def test_detail_page_shows_question_to_claimant_and_never_the_detail(created_item, claimant):
    page = claimant.get(f"/itens/{created_item}").get_data(as_text=True)
    assert SECRET["secretQuestion"] in page
    assert SECRET["secretDetail"] not in page
    assert SECRET["secretAnswer"] not in page

    # quem não está logado não vê nem a pergunta
    anonymous = claimant.application.test_client().get(f"/itens/{created_item}").get_data(as_text=True)
    assert SECRET["secretQuestion"] not in anonymous


def test_form_post_flow_validates_and_flashes_result(created_item, claimant):
    response = claimant.post(f"/itens/{created_item}/reivindicar", data={"answer": SECRET["secretAnswer"]},
                             follow_redirects=True)
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Posse validada" in page
    assert SECRET["secretDetail"] not in page


def test_form_post_shows_remaining_attempts(created_item, claimant):
    response = claimant.post(f"/itens/{created_item}/reivindicar", data={"answer": "errado"},
                             follow_redirects=True)
    page = response.get_data(as_text=True)
    assert "Restam 2 tentativa" in page


def test_edit_form_prefills_question_but_never_the_answer(created_item, creator):
    page = creator.get(f"/painel/itens/{created_item}/editar")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Arranhão em forma de" in html  # Jinja escapa as aspas simples do texto
    assert SECRET["secretQuestion"] in html
    assert SECRET["secretAnswer"] not in html
    assert "preencha para manter a atual" in html


def test_form_only_offers_secret_box_for_found_items(creator):
    form = creator.get("/painel/itens/novo").get_data(as_text=True)
    assert "secretQuestion" in form
    assert "data-secret-box" in form


def test_normalize_answer_ignores_case_accents_and_punctuation():
    assert claim_service.normalize_answer("  Árvore-D'Água! ") == "arvore d agua"
    assert claim_service.normalize_answer("SPORT club") == claim_service.normalize_answer("sport  CLUB")
