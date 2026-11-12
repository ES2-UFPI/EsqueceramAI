"""US04 #27 - cadastro do detalhe confidencial e da pergunta-chave."""
import io
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from application.models import Item, ItemSecret, User, db
from application.repositories.items import find_item_by_id, is_seeded_item
from application.services import claim_service
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

def _cleanup_item(item_id: int):
    db.query(ItemSecret).filter(ItemSecret.item_id == item_id).delete(synchronize_session=False)
    db.query(Item).filter(Item.id == item_id).delete(synchronize_session=False)
    db.commit()


@pytest.fixture()
def creator(app):
    return persona_client(app, "carlos@ufpi.edu.br")

@pytest.fixture()
def created_item(creator):
    response = creator.post("/api/items", data=_multipart(item_form(**SECRET)), content_type="multipart/form-data")
    item_id = response.json["item"]["id"]
    yield item_id
    db.query(ItemSecret).filter(ItemSecret.item_id == item_id).delete(synchronize_session=False)
    db.query(Item).filter(Item.id == item_id).delete(synchronize_session=False)
    db.commit()

@pytest.fixture()
def created_demo_item(creator):
    """Cria um item isolado para o teste e o marca como demonstrativo no banco."""
    response = creator.post("/api/items", data=_multipart(item_form()), content_type="multipart/form-data")
    assert response.status_code == 201, response.json
    item_id = response.json["item"]["id"]
    row = db.get(Item, item_id)
    row.is_demo = True
    db.commit()
    yield item_id
    _cleanup_item(item_id)

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


def test_lost_item_without_secret_is_still_accepted(creator):
    """A checagem do bloco não pode barrar itens perdidos comuns."""
    response = creator.post("/api/items", data=_multipart(item_form(type="LOST")),
                            content_type="multipart/form-data")
    assert response.status_code == 201


def test_seeded_items_cannot_receive_a_secret(creator, created_demo_item):
    """Impede o cadastro em itens demonstrativos."""
    response = creator.patch(f"/api/items/{created_demo_item}", data=_multipart(item_form(**SECRET)),
                             content_type="multipart/form-data")
    assert response.status_code == 422
    assert "demonstrativos" in response.json["error"]

def test_seeded_items_prevent_bypass(creator, created_demo_item):
    """Valida que a tentativa rejeitada de bypass não removeu a trava is_demo."""
    # PATCH quebrando a regra
    r1 = creator.patch(f"/api/items/{created_demo_item}", data=_multipart(item_form(**SECRET, title="Trocou titulo")),
                       content_type="multipart/form-data")
    assert r1.status_code == 422
    
    # Se houvesse TOCTOU/partial write, o item teria atualizado o titulo antes de estourar.
    # Como validate roda ANTES da escrita, o item continua igual.
    item = find_item_by_id(created_demo_item)
    assert item["title"] == "Mochila preta encontrada na biblioteca"
    assert is_seeded_item(item) is True
    
    # Segunda tentativa também deve falhar
    r2 = creator.patch(f"/api/items/{created_demo_item}", data=_multipart(item_form(**SECRET)),
                       content_type="multipart/form-data")
    assert r2.status_code == 422

def test_edit_can_add_secret_later_keep_it_and_remove_explicitly(creator):
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
        db.query(ItemSecret).filter(ItemSecret.item_id == item_id).delete(synchronize_session=False)
        db.commit()


def test_only_the_owner_can_set_the_question(created_item, app):
    other = persona_client(app, "ana@ufpi.edu.br")
    response = other.patch(f"/api/items/{created_item}", data=_multipart(item_form(**SECRET)),
                           content_type="multipart/form-data")
    assert response.status_code == 403

def test_new_item_form_renders_secret_box(creator):
    form = creator.get("/painel/itens/novo").get_data(as_text=True)
    assert "secretQuestion" in form
    assert "data-secret-box" in form

def test_edit_form_prefills_question_but_never_the_answer(created_item, creator):
    page = creator.get(f"/painel/itens/{created_item}/editar")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Arranhão em forma de" in html  # Jinja escapa as aspas simples do texto
    assert SECRET["secretQuestion"] in html
    assert SECRET["secretAnswer"] not in html
    assert "preencha para manter a atual" in html


def test_normalize_answer_ignores_case_accents_and_punctuation():
    assert claim_service.normalize_answer("  Árvore-D'Água! ") == "arvore d agua"
    assert claim_service.normalize_answer("SPORT club") == claim_service.normalize_answer("sport  CLUB")
