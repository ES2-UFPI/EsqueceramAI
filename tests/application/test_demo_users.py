from application.models import db
from application.repositories.users import find_user_by_email


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
