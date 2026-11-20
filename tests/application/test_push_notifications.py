from conftest import persona_client


def test_service_worker_and_manifest_served(client):
    sw = client.get("/sw.js")
    assert sw.status_code == 200
    assert "javascript" in sw.content_type
    assert sw.headers.get("Service-Worker-Allowed") == "/"
    assert "notificationclick" in sw.get_data(as_text=True)

    manifest = client.get("/static/manifest.webmanifest")
    assert manifest.status_code == 200
    assert "Esqueceram AI" in manifest.get_data(as_text=True)


def test_notifications_page_and_body_flag_for_push(app, client):
    anon_html = client.get("/").get_data(as_text=True)
    assert 'data-user-authed="0"' in anon_html

    authed = persona_client(app, "ana@ufpi.edu.br")
    page = authed.get("/painel/notificacoes")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'data-user-authed="1"' in html
    assert "data-push-enable" in html
    assert "data-push-status" in html
