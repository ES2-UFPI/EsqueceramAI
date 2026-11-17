from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from application import domain
from application.models import CollectionPoint, Item, ItemEvent, User, db
from conftest import persona_client


@pytest.fixture()
def point_item(app):
    owner = db.execute(select(User).where(User.email == "carlos@ufpi.edu.br")).scalar_one()
    point = db.execute(select(CollectionPoint)).scalars().first()
    made = []

    def _make(*, title="Garrafa térmica azul", storage_location=None, inv_status="AWAITING_DROP_OFF", with_point=True):
        now = datetime.now(timezone.utc)
        item = Item(
            user_id=owner.id,
            type="FOUND",
            category="ACCESSORY",
            title=title,
            description="Item de teste para controle de inventário no posto.",
            location="Biblioteca Central",
            occurred_at=now,
            point_id=point.id if with_point else None,
            storage_location=storage_location,
            inventory_status=inv_status if with_point else None,
        )
        db.add(item)
        db.commit()
        made.append(item.id)
        return item.id

    _make.point_id = point.id
    yield _make
    for item_id in made:
        row = db.get(Item, item_id)
        if row:
            db.delete(row)
    db.commit()


def test_storage_location_is_exclusive_to_staff(app, point_item):
    item_id = point_item(storage_location="PRAT-A1")

    regular = persona_client(app, "carlos@ufpi.edu.br")
    # Usuário comum não vê storageLocation na API nem na página
    detail = regular.get(f"/api/items/{item_id}").get_json()
    assert detail["item"]["storageLocation"] is None
    listed = regular.get("/api/items").get_json()["items"]
    mine = next(i for i in listed if i["id"] == item_id)
    assert mine["storageLocation"] is None
    assert "PRAT-A1" not in regular.get(f"/itens/{item_id}").get_data(as_text=True)

    # Usuário comum não pode definir nem alterar localização física
    r_patch = regular.patch(f"/api/items/{item_id}/inventory", json={"storageLocation": "GAV-9"})
    assert r_patch.status_code == 403
    r_post = regular.post(
        "/api/items",
        data={
            "type": "FOUND", "category": "ACCESSORY", "title": "Chaveiro teste",
            "description": "Chaveiro encontrado perto do bloco de computação.",
            "location": "Centro de Tecnologia", "occurredAt": "2026-10-01",
            "pointId": str(point_item.point_id), "storageLocation": "GAV-1",
        },
        content_type="multipart/form-data",
    )
    assert r_post.status_code == 403

    # Atendente vê e edita localização física
    staff = persona_client(app, "operador@ufpi.edu.br")
    staff_detail = staff.get(f"/api/items/{item_id}").get_json()
    assert staff_detail["item"]["storageLocation"] == "PRAT-A1"
    upd = staff.patch(f"/api/items/{item_id}/inventory", json={"storageLocation": "Prateleira B2 · Gaveta 3"})
    assert upd.status_code == 200
    assert upd.get_json()["storageLocation"] == "Prateleira B2 · Gaveta 3"


def test_storage_location_validation_and_point_requirement(app, point_item):
    staff = persona_client(app, "operador@ufpi.edu.br")
    no_point = point_item(with_point=False)
    assert staff.patch(f"/api/items/{no_point}/inventory", json={"storageLocation": "A1"}).status_code == 422

    with_point = point_item()
    too_long = "X" * 81
    assert staff.patch(f"/api/items/{with_point}/inventory", json={"storageLocation": too_long}).status_code == 422


def test_quick_search_by_physical_location_in_operator_panel(app, point_item):
    id_a = point_item(title="Carregador USB-C", storage_location="GAV-B2", inv_status="STORED")
    id_b = point_item(title="Carteira preta", storage_location="PRAT-C9", inv_status="STORED")

    regular = persona_client(app, "carlos@ufpi.edu.br")
    assert regular.get("/api/operador/inventario?q=GAV-B2").status_code == 403

    staff = persona_client(app, "operador@ufpi.edu.br")
    api_res = staff.get("/api/operador/inventario?q=GAV-B2").get_json()["items"]
    assert [i["id"] for i in api_res] == [id_a]

    html = staff.get("/painel/operador?q=GAV-B2").get_data(as_text=True)
    assert "Carregador USB-C" in html and "GAV-B2" in html
    assert "PRAT-C9" not in html

    by_code = staff.get(f"/api/operador/inventario?q={domain.item_code(id_b)}").get_json()["items"]
    assert [i["id"] for i in by_code] == [id_b]


def test_visual_and_printable_package_label(app, point_item):
    item_id = point_item(title="Fone Bluetooth JBL", storage_location="CX-04", inv_status="STORED")
    code = domain.item_code(item_id)

    regular = persona_client(app, "carlos@ufpi.edu.br")
    assert regular.get(f"/painel/itens/{item_id}/etiqueta").status_code in (302, 403)

    staff = persona_client(app, "operador@ufpi.edu.br")
    detail_html = staff.get(f"/itens/{item_id}").get_data(as_text=True)
    assert code in detail_html and "CX-04" in detail_html and "Imprimir etiqueta" in detail_html

    label_html = staff.get(f"/painel/itens/{item_id}/etiqueta").get_data(as_text=True)
    assert code in label_html and "CX-04" in label_html and "Fone Bluetooth JBL" in label_html


def test_inventory_state_machine_transitions(app, point_item):
    item_id = point_item(inv_status="AWAITING_DROP_OFF")
    staff = persona_client(app, "operador@ufpi.edu.br")

    # Transições inválidas a partir de AWAITING_DROP_OFF
    assert staff.patch(f"/api/items/{item_id}/inventory", json={"inventoryStatus": "DELIVERED"}).status_code == 409
    assert staff.patch(f"/api/items/{item_id}/inventory", json={"inventoryStatus": "DISPOSED"}).status_code == 409

    # Aguardando entrega no posto -> Armazenado
    r1 = staff.patch(
        f"/api/items/{item_id}/inventory",
        json={"inventoryStatus": "STORED", "storageLocation": "PRAT-A3"},
    )
    assert r1.status_code == 200
    assert r1.get_json()["inventoryStatus"] == "STORED"
    assert r1.get_json()["storageLocation"] == "PRAT-A3"

    # Não pode voltar para AWAITING_DROP_OFF
    assert staff.patch(f"/api/items/{item_id}/inventory", json={"inventoryStatus": "AWAITING_DROP_OFF"}).status_code == 409

    # Armazenado -> Entregue (estado terminal)
    r2 = staff.patch(f"/api/items/{item_id}/inventory", json={"inventoryStatus": "DELIVERED"})
    assert r2.status_code == 200
    assert r2.get_json()["inventoryStatus"] == "DELIVERED"
    assert r2.get_json()["status"] == "DELIVERED"
    assert staff.patch(f"/api/items/{item_id}/inventory", json={"inventoryStatus": "DISPOSED"}).status_code == 409

    # Fluxo Armazenado -> Descartado/Doado (estado terminal e arquiva o item)
    disposed_id = point_item(inv_status="STORED", storage_location="PRAT-D1")
    r3 = staff.patch(f"/api/items/{disposed_id}/inventory", json={"inventoryStatus": "DISPOSED"})
    assert r3.status_code == 200
    assert r3.get_json()["inventoryStatus"] == "DISPOSED"
    assert r3.get_json()["status"] == "ARCHIVED"
    assert staff.patch(f"/api/items/{disposed_id}/inventory", json={"inventoryStatus": "DELIVERED"}).status_code == 409

    events = db.execute(select(ItemEvent).where(ItemEvent.item_id == item_id)).scalars().all()
    assert len(events) >= 2
