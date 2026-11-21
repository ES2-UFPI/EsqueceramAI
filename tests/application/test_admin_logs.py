from conftest import persona_client

from application.delivery.models import Delivery, DeliveryEvent
from application.models import Item, ItemEvent, Match, MatchNotification, User, db


def test_admin_logs_restricted_to_admin(app):
    anon = app.test_client()
    r = anon.get("/painel/admin/logs")
    assert r.status_code == 302 and "/entrar" in r.headers["Location"]

    for persona in ("ana@ufpi.edu.br", "operador@ufpi.edu.br"):
        c = persona_client(app, persona)
        res = c.get("/painel/admin/logs")
        assert res.status_code == 302 and res.headers["Location"].endswith("erro=permissao")


def test_admin_logs_lists_and_filters_events(app):
    with app.app_context():
        user = db.query(User).filter_by(email="ana@ufpi.edu.br").first()
        other = db.query(User).filter_by(email="carlos@ufpi.edu.br").first()
        lost = Item(
            user_id=user.id,
            type="LOST",
            category="ACCESSORY",
            title="Garrafa térmica azul log",
            description="Garrafa perdida perto da biblioteca",
            location="Biblioteca",
            occurred_at=user.created_at,
        )
        found = Item(
            user_id=other.id,
            type="FOUND",
            category="ACCESSORY",
            title="Garrafa térmica encontrada log",
            description="Encontrada na biblioteca",
            location="Biblioteca",
            occurred_at=user.created_at,
        )
        db.add_all([lost, found])
        db.flush()

        db.add(ItemEvent(item_id=lost.id, actor_id=user.id, status="OPEN", note="Registro criado para auditoria"))
        delivery = Delivery(
            item_id=found.id,
            item_code=f"ESQ-{found.id:05d}",
            item_title=found.title,
            attendant_id=user.id,
            attendant_name=user.name,
            attendant_registration="ATD-001",
            recipient_name="Ana",
            recipient_cpf_hash="a" * 64,
            recipient_cpf_masked="***.111.222-**",
            recipient_email="ana@ufpi.edu.br",
        )
        db.add(delivery)
        db.flush()
        db.add(DeliveryEvent(delivery_id=delivery.id, action="CONFIRMED", detail="Entrega confirmada no posto"))

        match = Match(lost_item_id=lost.id, found_item_id=found.id, score=90, reasons=["Mesmo local"])
        db.add(match)
        db.flush()
        db.add(MatchNotification(match_id=match.id, user_id=user.id, channel="EMAIL", status="SENT"))
        db.commit()

    admin = persona_client(app, "admin@ufpi.edu.br")
    resp = admin.get("/painel/admin/logs")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Registro criado para auditoria" in html
    assert "Entrega confirmada no posto" in html
    assert "Canal EMAIL para ana@ufpi.edu.br" in html

    only_delivery = admin.get("/painel/admin/logs?tipo=DELIVERY&q=confirmada")
    assert only_delivery.status_code == 200
    filtered = only_delivery.get_data(as_text=True)
    assert "Entrega confirmada no posto" in filtered
    assert "Registro criado para auditoria" not in filtered


def test_admin_logs_records_auth_admin_and_point_actions_with_filters(app):
    admin = persona_client(app, "admin@ufpi.edu.br")
    # Create a collection point (POINT log)
    pt = admin.post("/api/points", json={
        "name": "Portaria Sul Audit",
        "building": "Portaria",
        "description": "Guarita principal",
    })
    assert pt.status_code == 201

    # Admin updates user status (ADMIN log)
    with app.app_context():
        ana = db.query(User).filter_by(email="ana@ufpi.edu.br").first()
        admin_user = db.query(User).filter_by(email="admin@ufpi.edu.br").first()
        ana_id = ana.id
        admin_name = admin_user.name
    upd = admin.patch("/api/admin/users", json={"userId": ana_id, "isActive": True})
    assert upd.status_code == 200

    # Filter by AUTH
    auth_logs = admin.get("/painel/admin/logs?tipo=AUTH").get_data(as_text=True)
    assert "Login realizado" in auth_logs
    assert "Portaria Sul Audit" not in auth_logs

    # Filter by POINT + actor
    point_logs = admin.get(f"/painel/admin/logs?tipo=POINT&ator={admin_name}").get_data(as_text=True)
    assert "Ponto de coleta criado" in point_logs
    assert "Portaria Sul Audit" in point_logs

    # Filter by ADMIN
    admin_logs = admin.get("/painel/admin/logs?tipo=ADMIN").get_data(as_text=True)
    assert "Usuário atualizado pela administração" in admin_logs

    # Filter by future date range returns empty
    empty_logs = admin.get("/painel/admin/logs?de=2099-01-01&ate=2099-12-31").get_data(as_text=True)
    assert "Nenhum log encontrado" in empty_logs
