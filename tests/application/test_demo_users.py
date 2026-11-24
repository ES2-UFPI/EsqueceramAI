from application.auth import hash_password
from application.models import User, db
from application.repositories.users import create_user, find_user_by_email
from application.services.seed_service import DEMO_PASSWORD, ensure_demo_accounts


def test_demo_flag_controls_quick_login_list(app, client):
    with app.app_context():
        if not find_user_by_email("nao_demo@ufpi.edu.br"):
            create_user(name="Usuária Comum", email="nao_demo@ufpi.edu.br",
                        password_hash=hash_password(DEMO_PASSWORD))

    html = client.get("/entrar").get_data(as_text=True)
    assert "Ana Beatriz Lima" in html
    assert "Usuária Comum" not in html

    with app.app_context():
        u = find_user_by_email("nao_demo@ufpi.edu.br")
        assert u is not None and u.demo is False
        u.demo = True
        db.commit()

    try:
        html = client.get("/entrar").get_data(as_text=True)
        assert "Usuária Comum" in html

        r_ok = client.post("/api/auth/demo", json={"persona": "nao_demo@ufpi.edu.br"})
        assert r_ok.status_code == 200
        assert r_ok.json["user"]["email"] == "nao_demo@ufpi.edu.br"

        with app.app_context():
            u = find_user_by_email("nao_demo@ufpi.edu.br")
            u.demo = False
            db.commit()

        html = client.get("/entrar").get_data(as_text=True)
        assert "Usuária Comum" not in html
        r_denied = client.post("/api/auth/demo", json={"persona": "nao_demo@ufpi.edu.br"})
        assert r_denied.status_code == 404
    finally:
        with app.app_context():
            u = find_user_by_email("nao_demo@ufpi.edu.br")
            if u and u.demo:
                u.demo = False
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
