from conftest import persona_client, start


def patch_status(c, item, status="RETURNED"):
    return c.patch(f"/api/items/{item}", json={"status": status})


def test_policy_off_by_default_keeps_quick_return(app, attendant, make_item):
    assert patch_status(attendant, make_item()).status_code == 200


def test_policy_blocks_quick_return_for_items_at_points(app, attendant, make_item, monkeypatch):
    monkeypatch.setenv("DELIVERY_REQUIRE_CHECKOUT", "true")
    item = make_item()
    r = patch_status(attendant, item)
    assert r.status_code == 409 and "formulário de entrega" in r.get_json()["error"]
    assert attendant.get(f"/api/items/{item}").get_json()["item"]["status"] == "OPEN"
    owner = persona_client(app, "carlos@ufpi.edu.br")                     # nem o dono do registro contorna
    assert patch_status(owner, item).status_code == 409
    admin = persona_client(app, "admin@ufpi.edu.br")
    assert patch_status(admin, item).status_code == 409


def test_policy_does_not_touch_other_transitions_or_items(app, attendant, make_item, monkeypatch):
    monkeypatch.setenv("DELIVERY_REQUIRE_CHECKOUT", "true")
    item = make_item()
    assert patch_status(attendant, item, "ARCHIVED").status_code == 200           # outras mudanças de status seguem livres
    assert patch_status(attendant, item, "OPEN").status_code == 200
    assert patch_status(attendant, make_item(kind="LOST")).status_code == 200      # item perdido não tem custódia no posto
    owner = persona_client(app, "carlos@ufpi.edu.br")
    assert patch_status(owner, make_item(with_point=False)).status_code == 200      # nem item fora de ponto (dono devolve)
    assert patch_status(attendant, make_item(with_point=False)).status_code == 403  # regra antiga: operador só gerencia itens de ponto


def test_checkout_still_returns_item_when_policy_on(app, attendant, make_item, sent_codes, monkeypatch):
    monkeypatch.setenv("DELIVERY_REQUIRE_CHECKOUT", "true")
    item = make_item()
    d = start(attendant, item).get_json()["delivery"]
    r = attendant.post(f"/api/deliveries/{d['id']}/confirm", json={"code": sent_codes[-1]["code"]})
    assert r.status_code == 200
    assert attendant.get(f"/api/items/{item}").get_json()["item"]["status"] == "RETURNED"
