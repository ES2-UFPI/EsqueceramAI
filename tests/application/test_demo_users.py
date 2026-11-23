from application.models import User, db
from application.repositories.users import find_user_by_email
from application.services.seed_service import ensure_demo_accounts


def test_demo_flag_controls_quick_login_list(app, client):
    html = client.get("/entrar").get_data(as_text=True)
    assert "Ana Beatriz Lima" in html
    assert "Maria de Sousa" not in html

    with app.app_context():
        maria = find_user_by_email("maria@ufpi.edu.br")
        assert maria is not None and maria.demo is False
        maria.demo = True
        db.commit()

    try:
        html = client.get("/entrar").get_data(as_text=True)
        assert "Maria de Sousa" in html

        r_ok = client.post("/api/auth/demo", json={"persona": "maria@ufpi.edu.br"})
        assert r_ok.status_code == 200
        assert r_ok.json["user"]["email"] == "maria@ufpi.edu.br"

        with app.app_context():
            maria = find_user_by_email("maria@ufpi.edu.br")
            maria.demo = False
            db.commit()

        html = client.get("/entrar").get_data(as_text=True)
        assert "Maria de Sousa" not in html
        r_denied = client.post("/api/auth/demo", json={"persona": "maria@ufpi.edu.br"})
        assert r_denied.status_code == 404
    finally:
        with app.app_context():
            maria = find_user_by_email("maria@ufpi.edu.br")
            if maria and maria.demo:
                maria.demo = False
                db.commit()


def test_demo_mode_can_be_disabled_via_db_or_env(app, client, monkeypatch):
    with app.app_context():
        original_demos = [u.id for u in db.query(User).filter(User.demo.is_(True)).all()]
        db.query(User).update({User.demo: False})
        db.commit()

    try:
        with app.app_context():
            ensure_demo_accounts()
            assert db.query(User).filter(User.demo.is_(True)).count() == 0

        html = client.get("/entrar").get_data(as_text=True)
        assert "Acesso rápido de demonstração" not in html

        monkeypatch.setenv("DEMO_LOGIN_DISABLED", "true")
        assert "Acesso rápido de demonstração" not in client.get("/entrar").get_data(as_text=True)
    finally:
        with app.app_context():
            db.query(User).filter(User.id.in_(original_demos)).update({User.demo: True}, synchronize_session=False)
            db.commit()
