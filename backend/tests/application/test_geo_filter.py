import math
from datetime import datetime, timedelta, timezone
import pytest
from application import domain as D
from conftest import persona_client

# Ponto de referência longe do seed (UFPI, ~88 km): os testes não dependem dos dados demonstrativos.
REF = (-5.0, -42.0)

def _offset(lat_km=0.0, lng_km=0.0):
    return (REF[0] + lat_km / 111.195, REF[1] + lng_km / (111.195 * math.cos(math.radians(REF[0]))))

@pytest.fixture(scope="module")
def geo_items(app):
    from sqlalchemy import select
    from application.models import Item, User, db
    owner = db.execute(select(User).where(User.email == "carlos@ufpi.edu.br")).scalar_one()
    spec = {"A": ("LOST", _offset()), "B": ("FOUND", _offset(lat_km=0.3)),
            "C": ("FOUND", _offset(lng_km=3.0)), "D": ("FOUND", (None, None))}
    ids = {}
    for key, (kind, (lat, lng)) in spec.items():
        item = Item(user_id=owner.id, type=kind, category="ELECTRONIC", title=f"GEOTESTE {key}",
                    description="Descrição longa o suficiente para o teste.", location=f"Local geo {key}",
                    occurred_at=datetime.now(timezone.utc) - timedelta(days=1), latitude=lat, longitude=lng)
        db.add(item)
        db.commit()
        ids[key] = item.id
    yield ids
    for item_id in ids.values():
        db.delete(db.get(Item, item_id))
    db.commit()

def _search(client, **params):
    params = {"q": "GEOTESTE", **params}
    resp = client.get("/api/items", query_string=params)
    return resp, [i["title"].split()[-1] for i in resp.json["items"]] if resp.status_code == 200 else None

GEO = {"lat": REF[0], "lng": REF[1]}

# ------------------------------------------------------------------ domínio
def test_haversine_um_grau_de_longitude_no_equador():
    assert D.haversine_km(0, 0, 0, 1) == pytest.approx(111.195, abs=0.01)

def test_bounding_box_contem_o_circulo():
    lat_min, lat_max, lng_min, lng_max = D.bounding_box(*REF, 1)
    for k in range(0, 360, 15):
        lat = REF[0] + 0.9 / 111.195 * math.sin(math.radians(k))
        lng = REF[1] + 0.9 / (111.195 * math.cos(math.radians(REF[0]))) * math.cos(math.radians(k))
        assert lat_min <= lat <= lat_max and lng_min <= lng <= lng_max

def test_bounding_box_sem_limite_de_longitude_no_antimeridiano():
    assert D.bounding_box(0, 179.9, 50)[2:] == (None, None)

@pytest.mark.parametrize("args", [("1", "", ""), ("", "1", ""), ("", "", "2"), ("x", "1", ""), ("91", "1", ""),
                                  ("1", "181", ""), ("nan", "1", ""), ("1", "1", "0"), ("1", "1", "-1"),
                                  ("1", "1", "51"), ("1", "1", "abc")])
def test_parametros_geograficos_invalidos(args):
    geo, error = D.parse_geo_params(*args)
    assert geo is None and error

def test_parametros_geograficos_validos():
    assert D.parse_geo_params("", None, " ") == (None, None)
    assert D.parse_geo_params("-5,05", "-42.78", "0,5") == ({"lat": -5.05, "lng": -42.78, "radiusKm": 0.5}, None)
    assert D.parse_geo_params("-5", "-42", "")[0]["radiusKm"] is None

@pytest.mark.parametrize("km,texto", [(None, ""), (0.004, "menos de 10 m"), (0.2, "200 m"), (0.123, "120 m"),
                                      (0.996, "1,0 km"), (1.26, "1,3 km")])
def test_formatar_distancia(km, texto):
    assert D.format_distance(km) == texto

# ------------------------------------------------------------------ API principal
def test_raio_filtra_pelo_ponto_de_referencia(client, geo_items):
    assert _search(client, **GEO, raio=1, ordem="proximity")[1] == ["A", "B"]
    assert _search(client, **GEO, raio=5, ordem="proximity")[1] == ["A", "B", "C"]
    assert _search(client, **GEO, raio=0.2)[1] == ["A"]

def test_item_sem_coordenadas_fica_fora_da_busca_por_raio(client, geo_items):
    assert "D" not in _search(client, **GEO, raio=50)[1]

def test_sem_raio_so_ordena_e_mede_distancia(client, geo_items):
    resp, titles = _search(client, **GEO, ordem="proximity")
    assert titles == ["A", "B", "C", "D"]  # sem coordenadas por último
    dist = {i["title"].split()[-1]: i["distanceKm"] for i in resp.json["items"]}
    assert dist["A"] == pytest.approx(0, abs=0.01)
    assert dist["B"] == pytest.approx(0.3, abs=0.01)
    assert dist["C"] == pytest.approx(3.0, abs=0.05)
    assert dist["D"] is None

def test_so_referencia_informa_distancia_sem_reordenar(client, geo_items):
    resp, titles = _search(client, **GEO, ordem="recent")
    base_titles = _search(client, ordem="recent")[1]
    assert titles == base_titles and resp.json["total"] == 4
    dist = {i["title"].split()[-1]: i["distanceKm"] for i in resp.json["items"]}
    assert dist["B"] == pytest.approx(0.3, abs=0.01) and dist["D"] is None

def test_distancia_nula_sem_filtro_geografico(client, geo_items):
    resp, _ = _search(client)
    assert all(i["distanceKm"] is None for i in resp.json["items"])

def test_raio_combina_com_outros_filtros(client, geo_items):
    assert _search(client, **GEO, raio=5, tipo="FOUND", ordem="proximity")[1] == ["B", "C"]
    assert _search(client, **GEO, raio=5, tipo="LOST")[1] == ["A"]
    assert _search(client, **GEO, raio=5, local="geo C")[1] == ["C"]

def test_total_e_paginas_refletem_o_raio(client, geo_items):
    resp, _ = _search(client, **GEO, raio=5, pagina=1)
    assert resp.json["total"] == 3 and resp.json["totalPages"] == 1
    assert _search(client, **GEO, raio=5, pagina=2)[1] == []

@pytest.mark.parametrize("params", [{"lat": -5}, {"lng": -42}, {"raio": 2}, {"lat": "abc", "lng": -42},
                                    {"lat": 95, "lng": -42}, {"lat": -5, "lng": -200},
                                    {"lat": -5, "lng": -42, "raio": 0}, {"lat": -5, "lng": -42, "raio": 999}])
def test_parametros_invalidos_retornam_422(client, params):
    resp = client.get("/api/items", query_string=params)
    assert resp.status_code == 422 and resp.json["error"]

# ------------------------------------------------------------------ API em português (frontend estático)
def _mvp(client, **params):
    resp = client.get("/api/itens", query_string={"q": "GEOTESTE", **params})
    return resp, [i["descricao"] for i in resp.json] if resp.status_code == 200 else None

def test_mvp_filtra_por_raio_e_ordena_por_proximidade(client, geo_items):
    resp, _ = _mvp(client, lat=REF[0], lng=REF[1], raio_km=5)
    assert [i["localizacao"][-1] for i in resp.json] == ["A", "B", "C"]
    assert resp.json[1]["distancia_km"] == pytest.approx(0.3, abs=0.01)
    assert [i["localizacao"][-1] for i in _mvp(client, lat=REF[0], lng=REF[1], raio_km=0.5)[0].json] == ["A", "B"]

def test_mvp_filtra_por_localizacao_textual(client, geo_items):
    resp, _ = _mvp(client, localizacao="geo c")
    assert [i["localizacao"] for i in resp.json] == ["Local geo C"]

def test_mvp_sem_filtro_geografico_nao_traz_distancia(client, geo_items):
    assert all(i["distancia_km"] is None for i in _mvp(client)[0].json)

@pytest.mark.parametrize("params", [{"lat": 1}, {"lat": "x", "lng": 1}, {"lat": 100, "lng": 1},
                                    {"lat": 1, "lng": 1, "raio_km": "abc"}, {"lat": 1, "lng": 1, "raio_km": 0}])
def test_mvp_parametros_invalidos_retornam_400(client, params):
    resp = client.get("/api/itens", query_string=params)
    assert resp.status_code == 400 and resp.json["erro"]

BASE = {"tipo_registro": "ENCONTRADO", "categoria": "ACESSORIO", "descricao": "Garrafa GEOTESTE criada pelo teste"}

@pytest.mark.parametrize("extra", [{"latitude": 999, "longitude": 1}, {"latitude": 1, "longitude": 181},
                                   {"latitude": 10}, {"longitude": 10}, {"latitude": "x", "longitude": 1}])
def test_mvp_cadastro_rejeita_coordenadas_invalidas(client, extra):
    resp = client.post("/api/itens", json={**BASE, **extra})
    assert resp.status_code == 400 and resp.json["erro"]

def test_mvp_cadastro_aceita_coordenada_zero(client):
    from application.models import Item, db
    resp = client.post("/api/itens", json={**BASE, "latitude": 0, "longitude": 0, "localizacao": "Marco zero"})
    assert resp.status_code == 201
    assert resp.json["latitude"] == 0 and resp.json["longitude"] == 0  # 0 não pode virar "sem valor"
    db.delete(db.get(Item, resp.json["id"]))
    db.commit()

# ------------------------------------------------------------------ páginas web
def test_pagina_de_busca_filtra_e_mostra_distancia(client, geo_items):
    html = client.get("/itens", query_string={"q": "GEOTESTE", **GEO, "raio": 1, "ordem": "proximity"}).get_data(as_text=True)
    assert "GEOTESTE A" in html and "GEOTESTE B" in html
    assert "GEOTESTE C" not in html and "GEOTESTE D" not in html
    assert "(a 300 m)" in html and "(a menos de 10 m)" in html
    assert "2 registro(s) encontrado(s) em até 1,0 km" in html
    assert 'name="lat" value="-5.0"' in html  # a referência sobrevive à paginação/refinamento

def test_pagina_de_busca_com_parametros_invalidos_avisa_e_lista_sem_filtro(client, geo_items):
    resp = client.get("/itens", query_string={"q": "GEOTESTE", "lat": "999", "lng": "1", "raio": "1"})
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Latitude deve estar entre -90 e 90." in html and "sem o filtro de localização" in html
    assert "GEOTESTE C" in html

def test_pagina_de_busca_sem_parametros_geograficos_continua_igual(client):
    html = client.get("/itens").get_data(as_text=True)
    assert "Raio de busca" in html and "data-geo-locate" in html and "Referência:" not in html

def test_detalhe_mostra_link_do_mapa_so_quando_ha_coordenadas(client, geo_items):
    com = client.get(f"/itens/{geo_items['A']}").get_data(as_text=True)
    sem = client.get(f"/itens/{geo_items['D']}").get_data(as_text=True)
    assert "openstreetmap.org/?mlat=-5.0" in com and "ver no mapa" in com
    assert "ver no mapa" not in sem

def test_formulario_de_registro_oferece_captura_da_localizacao(app):
    html = persona_client(app, "carlos@ufpi.edu.br").get("/painel/itens/novo").get_data(as_text=True)
    assert 'name="latitude"' in html and 'data-geo-lat-name="latitude"' in html

def test_registro_com_coordenadas_pelo_formulario_entra_na_busca_por_raio(app):
    from application.models import Item, db
    c = persona_client(app, "carlos@ufpi.edu.br")
    lat, lng = _offset(lat_km=0.1)
    resp = c.post("/api/items", data={
        "type": "FOUND", "category": "ACCESSORY", "title": "GEOTESTE formulario", "location": "Perto da referência",
        "description": "Registro criado pelo teste com coordenadas.", "occurredAt": datetime.now(timezone.utc).date().isoformat(),
        "latitude": str(lat), "longitude": str(lng)}, content_type="multipart/form-data")
    assert resp.status_code == 201, resp.json
    try:
        found = c.get("/api/items", query_string={"q": "GEOTESTE formulario", **GEO, "raio": 0.5}).json
        assert [i["id"] for i in found["items"]] == [resp.json["item"]["id"]]
        assert found["items"][0]["distanceKm"] == pytest.approx(0.1, abs=0.01)
    finally:
        db.delete(db.get(Item, resp.json["item"]["id"]))
        db.commit()

def test_registro_rejeita_coordenadas_fora_da_faixa(app):
    c = persona_client(app, "carlos@ufpi.edu.br")
    resp = c.post("/api/items", data={
        "type": "FOUND", "category": "ACCESSORY", "title": "GEOTESTE invalido", "location": "Qualquer lugar",
        "description": "Registro com coordenada inválida.", "occurredAt": datetime.now(timezone.utc).date().isoformat(),
        "latitude": "123", "longitude": "10"}, content_type="multipart/form-data")
    assert resp.status_code == 422 and "latitude" in resp.json["details"]

@pytest.mark.parametrize("extra", [{"latitude": "nan", "longitude": "10"},
                                   {"latitude": "-5.05"}, {"longitude": "-42"}])
def test_registro_rejeita_nan_e_coordenada_incompleta(app, extra):
    c = persona_client(app, "carlos@ufpi.edu.br")
    resp = c.post("/api/items", data={
        "type": "FOUND", "category": "ACCESSORY", "title": "GEOTESTE invalido2", "location": "Qualquer lugar",
        "description": "Registro com coordenada inválida.", "occurredAt": datetime.now(timezone.utc).date().isoformat(),
        **extra}, content_type="multipart/form-data")
    assert resp.status_code == 422 and resp.json["details"]