from conftest import persona_client


def test_collection_point_form_uses_shared_geo_picker_and_persists_coords(app):
    admin = persona_client(app, "admin@ufpi.edu.br")
    form_html = admin.get("/painel/pontos").get_data(as_text=True)
    assert "data-geo-locate" in form_html
    assert "data-geo-map-toggle" in form_html
    assert 'id="item-geo-map-box" hidden' in form_html

    res = admin.post(
        "/painel/pontos",
        data={
            "name": "Guarita Leste Geo",
            "building": "Portaria Leste",
            "description": "Entrada principal",
            "openingHours": "07h às 19h",
            "latitude": "-5.056123",
            "longitude": "-42.789456",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Guarita Leste Geo" in html
    assert "mlat=-5.056123" in html
    assert "mlon=-42.789456" in html

    points = admin.get("/api/points").json["points"]
    created = next(p for p in points if p["name"] == "Guarita Leste Geo")
    assert created["latitude"] == -5.056123
    assert created["longitude"] == -42.789456

    # Item linked to that collection point exposes point map link on /itens/<id>
    item_resp = admin.post(
        "/api/items",
        data={
            "type": "FOUND",
            "category": "ACCESSORY",
            "title": "Chaveiro com tag",
            "description": "Encontrado na entrada leste",
            "location": "Portaria Leste",
            "occurredAt": "2026-11-20",
            "pointId": str(created["id"]),
        },
        content_type="multipart/form-data",
    )
    assert item_resp.status_code == 201
    item_id = item_resp.json["item"]["id"]

    ana = persona_client(app, "ana@ufpi.edu.br")
    detail_html = ana.get(f"/itens/{item_id}").get_data(as_text=True)
    assert "Ver localização do posto no mapa" in detail_html
    assert "mlat=-5.056123" in detail_html
    assert "mlon=-42.789456" in detail_html

    home_html = ana.get("/").get_data(as_text=True)
    assert "Guarita Leste Geo" in home_html
    assert "Ver localização no mapa" in home_html
