import re


def test_recuperar_page_asks_only_email(client):
    html = client.get("/recuperar-senha").get_data(as_text=True)
    assert 'name="email"' in html
    assert 'name="phone"' not in html
    assert 'name="newPassword"' not in html


def test_password_reset_flow_sends_token_and_resets_once(client, _capture_emails):
    _capture_emails.clear()
    # Unknown email must not fail or send email (prevents user enumeration)
    unknown = client.post("/recuperar-senha", data={"email": "naoexiste@ufpi.edu.br"}, follow_redirects=False)
    assert unknown.status_code == 302
    assert len(_capture_emails) == 0

    # Valid user email sends reset link with token
    resp = client.post("/recuperar-senha", data={"email": "ana@ufpi.edu.br"}, follow_redirects=False)
    assert resp.status_code == 302
    assert len(_capture_emails) == 1
    mail = _capture_emails[0]
    assert mail["to"] == "ana@ufpi.edu.br"

    match = re.search(r"/redefinir-senha\?token=([A-Za-z0-9_-]+)", mail["body"])
    assert match, mail["body"]
    token = match.group(1)

    # Invalid token shows error page
    bad_page = client.get("/redefinir-senha?token=token-invalido-123")
    assert bad_page.status_code == 200
    assert "Link de redefinição inválido ou expirado" in bad_page.get_data(as_text=True)

    # Valid token renders new password form
    good_page = client.get(f"/redefinir-senha?token={token}")
    assert good_page.status_code == 200
    assert 'name="newPassword"' in good_page.get_data(as_text=True)

    # Submitting new password resets it and invalidates the token
    reset = client.post(
        "/redefinir-senha",
        data={"token": token, "newPassword": "NovaSenhaSegura123"},
        follow_redirects=False,
    )
    assert reset.status_code == 302 and "/entrar" in reset.headers["Location"]

    # Token cannot be reused
    reuse = client.post("/api/auth/recover", json={"token": token, "newPassword": "OutraSenha123"})
    assert reuse.status_code == 400

    # User can log in with the new password
    login = client.post("/api/auth/login", json={"email": "ana@ufpi.edu.br", "password": "NovaSenhaSegura123"})
    assert login.status_code == 200
