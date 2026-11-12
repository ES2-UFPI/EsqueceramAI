import pytest
from sqlalchemy import func, select
from application import domain
from application.delivery import models as m
from application.delivery import repository as repo
from application.delivery import service
from application.models import CollectionPoint, Item, ItemEvent, atomic, db
from application.services import stats_service
from conftest import persona_client, start
from test_delivery_service import code_of, user_score

def _confirm(client, delivery_id, code):
    return client.post(f"/api/deliveries/{delivery_id}/confirm", json={"code": code})

def _item_status(item_id):
    db.expire_all()
    return db.get(Item, item_id).status

def _started(attendant, make_item, sent_codes):
    item = make_item()
    delivery = start(attendant, item).get_json()["delivery"]
    return item, delivery["id"], code_of(sent_codes)

def _delivered(attendant, make_item, sent_codes):
    item, delivery_id, code = _started(attendant, make_item, sent_codes)
    assert _confirm(attendant, delivery_id, code).status_code == 200
    return item, delivery_id

# status "Entregue"
def test_delivered_is_a_labelled_status():
    assert domain.STATUS_LABEL["DELIVERED"] == "Entregue"
    assert set(domain.STATUSES) == set(domain.STATUS_LABEL)          # todo status tem rótulo
    assert set(domain.FINAL_STATUSES) <= set(domain.STATUSES)

def test_item_stays_available_until_delivery_is_confirmed(app, attendant, make_item, sent_codes):
    item, delivery_id, _ = _started(attendant, make_item, sent_codes)
    assert _item_status(item) == "OPEN"
    detail = attendant.get(f"/api/deliveries/{delivery_id}").get_json()["delivery"]
    assert detail["status"] == "PENDING" and detail["itemStatus"] == "OPEN"

def test_confirmation_persists_record_and_final_item_status(app, attendant, make_item, sent_codes):
    item, delivery_id, code = _started(attendant, make_item, sent_codes)
    r = _confirm(attendant, delivery_id, code)
    assert r.status_code == 200
    body = r.get_json()["delivery"]
    assert body["status"] == "COMPLETED" and body["itemStatus"] == "DELIVERED"
    db.expire_all()
    delivery = db.get(m.Delivery, delivery_id)
    assert delivery.status == m.COMPLETED and delivery.item_id == item     # registro ligado ao item
    assert delivery.confirmed_at is not None and delivery.code_hash is None  # código de uso único descartado
    assert db.get(Item, item).status == "DELIVERED"
    assert repo.get_receipt(delivery_id) is not None
    assert "CONFIRMED" in [e.action for e in repo.list_events(delivery_id)]
    last = db.execute(select(ItemEvent).where(ItemEvent.item_id == item)
                      .order_by(ItemEvent.id.desc())).scalars().first()
    assert last.status == "DELIVERED" and body["receiptNumber"] in last.note    # linha do tempo do item

def test_delivered_status_is_searchable_in_both_apis(app, attendant, make_item, sent_codes):
    item, _ = _delivered(attendant, make_item, sent_codes)
    found = attendant.get("/api/items?status=DELIVERED").get_json()
    assert item in [i["id"] for i in found["items"]]
    mvp = attendant.get("/api/itens?status=ENTREGUE")                    # contrato em português do frontend
    assert mvp.status_code == 200
    assert {i["id"]: i["status"] for i in mvp.get_json()}[item] == "ENTREGUE"
    assert item not in [i["id"] for i in attendant.get("/api/itens?status=ABERTO").get_json()]

def test_delivered_item_is_not_deliverable_again(app, attendant, make_item, sent_codes):
    item, _ = _delivered(attendant, make_item, sent_codes)
    assert item not in [i["id"] for i in service.deliverable_items()]
    assert start(attendant, item).status_code == 409

# tudo ou nada
def test_failure_midway_rolls_back_everything_and_can_be_retried(app, attendant, make_item, sent_codes, monkeypatch):
    item, delivery_id, code = _started(attendant, make_item, sent_codes)
    score_before = user_score("carlos@ufpi.edu.br")

    with monkeypatch.context() as mp:
        def boom(*a, **kw):
            raise RuntimeError("falha simulada ao gravar o termo")
        mp.setattr(repo, "save_receipt", boom)                           # último passo, depois do status do item
        assert _confirm(attendant, delivery_id, code).status_code >= 500

    db.expire_all()
    delivery = db.get(m.Delivery, delivery_id)
    assert db.get(Item, item).status == "OPEN"                           # item NÃO ficou "Entregue" sem registro
    assert delivery.status == m.PENDING and delivery.confirmed_at is None and delivery.code_hash is not None
    assert repo.get_receipt(delivery_id) is None
    assert "CONFIRMED" not in [e.action for e in repo.list_events(delivery_id)]
    assert "DELIVERED" not in [e.status for e in db.execute(select(ItemEvent).where(ItemEvent.item_id == item)).scalars()]
    assert user_score("carlos@ufpi.edu.br") == score_before              # pontuação também não foi creditada

    # o mesmo código continua válido: o atendente apenas repete a confirmação
    assert _confirm(attendant, delivery_id, code).status_code == 200
    assert _item_status(item) == "DELIVERED"
    assert user_score("carlos@ufpi.edu.br") == score_before + 40

# "Entregue" só pelo fluxo da entrega
def test_manual_patch_cannot_set_delivered(app, attendant, make_item):
    item = make_item()
    owner = persona_client(app, "carlos@ufpi.edu.br")
    for client in (attendant, owner):
        r = client.patch(f"/api/items/{item}", json={"status": "DELIVERED"})
        assert r.status_code == 409 and "termo de retirada" in r.get_json()["error"]
    assert _item_status(item) == "OPEN"

def test_delivered_item_is_frozen(app, attendant, make_item, sent_codes):
    item, _ = _delivered(attendant, make_item, sent_codes)
    owner = persona_client(app, "carlos@ufpi.edu.br")
    for client in (attendant, owner):
        for status in ("OPEN", "RESERVED", "RETURNED", "ARCHIVED"):
            assert client.patch(f"/api/items/{item}", json={"status": status}).status_code == 409, status
    edit = owner.patch(f"/api/items/{item}", data={"title": "Outro título"}, content_type="multipart/form-data")
    assert edit.status_code == 409
    assert _item_status(item) == "DELIVERED"

def test_delivered_counts_as_recovered(app, attendant, make_item, sent_codes):
    before = stats_service.get_public_home()["returned"]
    _delivered(attendant, make_item, sent_codes)
    assert stats_service.get_public_home()["returned"] == before + 1

#atomic()
@pytest.fixture()
def marker_points(app):
    marker = "ZZ-atomic-test"

    def count():
        db.expire_all()
        return db.scalar(select(func.count()).select_from(CollectionPoint).where(CollectionPoint.name.like(f"{marker}%")))

    def add(n):
        db.add(CollectionPoint(name=f"{marker}-{n}", building="Bloco Z"))
        db.commit()                                                      # commit "de repositório"

    yield count, add
    db.rollback()
    db.execute(CollectionPoint.__table__.delete().where(CollectionPoint.name.like(f"{marker}%")))
    db.commit()

def test_atomic_commits_all_or_nothing(marker_points):
    count, add = marker_points
    with pytest.raises(RuntimeError):
        with atomic():
            add(1)
            add(2)
            raise RuntimeError("falha")
    assert count() == 0

    with atomic():
        add(3)
        add(4)
    assert count() == 2

def test_nested_atomic_rolls_back_with_the_outermost(marker_points):
    count, add = marker_points
    with pytest.raises(RuntimeError):
        with atomic():
            add(1)
            with atomic():
                add(2)
            raise RuntimeError("falha depois do bloco interno")
    assert count() == 0

def test_commit_outside_atomic_is_immediate(marker_points):
    count, add = marker_points
    add(1)
    db.rollback()                                                     
