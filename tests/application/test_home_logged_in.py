from conftest import persona_client


def test_home_shows_guest_actions_when_logged_out(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    for needle in ('href="/entrar"', 'href="/cadastrar"', "Testar sem cadastro"):
        assert needle in html, needle

    for absent in ("Achei um item", "Perdi um item", "＋ Novo registro", 'action="/sair"'):
        assert absent not in html, absent


def test_home_shows_logged_in_actions_when_authenticated(app):
    authed = persona_client(app, "ana@ufpi.edu.br")
    resp = authed.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    for needle in (
        'href="/painel/itens/novo?tipo=FOUND"',
        "Achei um item",
        'href="/painel/itens/novo?tipo=LOST"',
        "Perdi um item",
        'href="/painel/itens/novo"',
        "＋ Novo registro",
        'href="/painel"',
        "Ir para o painel →",
        "Painel →",
        'action="/sair"',
    ):
        assert needle in html, needle

    for absent in ('href="/cadastrar"', "Testar sem cadastro"):
        assert absent not in html, absent
