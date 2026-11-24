from application.services import matching_service
from conftest import persona_client


def test_chat_requires_confirmed_match_and_direct_participants(app, make_item):
    lost_id = make_item(kind="LOST", with_point=False, owner="ana@ufpi.edu.br")
    found_id = make_item(kind="FOUND", with_point=False, owner="carlos@ufpi.edu.br")
    match = matching_service.upsert_match(lost_item_id=lost_id, found_item_id=found_id, score=90, reasons=["Mesma cor"])

    ana = persona_client(app, "ana@ufpi.edu.br")
    carlos = persona_client(app, "carlos@ufpi.edu.br")
    operador = persona_client(app, "operador@ufpi.edu.br")
    admin = persona_client(app, "admin@ufpi.edu.br")

    assert app.test_client().get(f"/api/matches/{match.id}/messages").status_code == 401
    assert ana.get(f"/api/matches/{match.id}/messages").status_code == 409

    assert ana.patch(f"/api/matches/{match.id}", json={"action": "confirm"}).status_code == 200

    assert operador.get(f"/api/matches/{match.id}/messages").status_code == 403
    assert admin.get(f"/api/matches/{match.id}/messages").status_code == 403

    assert ana.post(f"/api/matches/{match.id}/messages", json={"body": ""}).status_code == 422
    r1 = ana.post(f"/api/matches/{match.id}/messages", json={"body": "Podemos combinar na biblioteca?"})
    assert r1.status_code == 201
    r2 = carlos.post(f"/api/matches/{match.id}/messages", json={"body": "Sim, hoje as 14h!"})
    assert r2.status_code == 201

    msgs = carlos.get(f"/api/matches/{match.id}/messages").get_json()["messages"]
    assert [m["body"] for m in msgs] == ["Podemos combinar na biblioteca?", "Sim, hoje as 14h!"]
    assert 'data-match-chat="' in ana.get(f"/correspondencias/{match.id}").get_data(as_text=True)
    assert 'data-match-chat="' not in operador.get(f"/correspondencias/{match.id}").get_data(as_text=True)


def test_chat_with_collection_point_restricts_to_finder_and_operators(app, make_item, _capture_emails):
    lost_id = make_item(kind="LOST", with_point=False, owner="ana@ufpi.edu.br")
    found_id = make_item(kind="FOUND", with_point=True, owner="carlos@ufpi.edu.br")
    match = matching_service.upsert_match(lost_item_id=lost_id, found_item_id=found_id, score=92, reasons=["Mesma marca"])

    ana = persona_client(app, "ana@ufpi.edu.br")
    carlos = persona_client(app, "carlos@ufpi.edu.br")
    operador = persona_client(app, "operador@ufpi.edu.br")
    admin = persona_client(app, "admin@ufpi.edu.br")

    assert ana.patch(f"/api/matches/{match.id}", json={"action": "confirm"}).status_code == 200

    assert ana.get(f"/api/matches/{match.id}/messages").status_code == 403
    assert admin.get(f"/api/matches/{match.id}/messages").status_code == 403
    assert 'data-match-chat="' not in ana.get(f"/itens/{lost_id}").get_data(as_text=True)

    before_emails = len(_capture_emails)
    r1 = carlos.post(f"/api/matches/{match.id}/messages", json={"body": "Levo ao posto hoje a tarde."})
    assert r1.status_code == 201
    assert len(_capture_emails) > before_emails

    # Operador abre o chat (fica ativo/lendo na hora): resposta do Carlos não precisa reenviar e-mail
    assert operador.get(f"/api/matches/{match.id}/messages").status_code == 200
    r2 = operador.post(f"/api/matches/{match.id}/messages", json={"body": "Recebido, estaremos ate 18h."})
    assert r2.status_code == 201

    assert carlos.get(f"/api/matches/{match.id}/messages").status_code == 200
    before_live = len(_capture_emails)
    assert operador.post(f"/api/matches/{match.id}/messages", json={"body": "Pode vir agora."}).status_code == 201
    assert len(_capture_emails) == before_live

    msgs = carlos.get(f"/api/matches/{match.id}/messages").get_json()["messages"]
    assert len(msgs) == 3
    assert 'data-match-chat="' in operador.get(f"/correspondencias/{match.id}").get_data(as_text=True)
