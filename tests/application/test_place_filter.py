import math
from datetime import datetime, timedelta, timezone
import pytest
from application import domain as D

# Ponto de referência longe do seed (mesma convenção de test_geo_filter.py).
REF = (-5.0, -42.0)
GEO = {"lat": REF[0], "lng": REF[1]}

def _offset(lat_km=0.0, lng_km=0.0):
    return (REF[0] + lat_km / 111.195, REF[1] + lng_km / (111.195 * math.cos(math.radians(REF[0]))))

# domínio (sem banco)
@pytest.mark.parametrize("raw,folded", [("São  LUÍS ", "sao luis"), ("Fátima", "fatima"), ("", ""), (None, ""),
                                         ("  Ininga,   Teresina ", "ininga, teresina")])
def test_fold_text(raw, folded):
    assert D.fold_text(raw) == folded

@pytest.mark.parametrize("term,fields", [
    ("sao luis", ("Avenida São Luís",)),               # sem acento acha com acento
    ("SÃO LUÍS", ("avenida sao luis",)),               # com acento acha sem acento
    ("ininga", ("Bairro Ininga",)),                    # caixa
    ("geo c", ("Local geo C",)),                       # trecho contíguo, como era antes
    ("teca central", ("Biblioteca Central",)),         # substring no meio da palavra continua valendo
    ("Ininga, Teresina", ("Teresina", "Ininga")),      # palavras em campos diferentes, qualquer ordem
    ("bibli ininga", ("Biblioteca", None, "Ininga")),  # cada palavra inicia uma palavra
    ("", ("qualquer",)), ("   ", ("qualquer",)),       # termo vazio não filtra
])
def test_matches_place_casa(term, fields):
    assert D.matches_place(term, *fields)

@pytest.mark.parametrize("term,fields", [
    ("geo c", ("Local geo A",)),                      
    ("parnaiba", ("Teresina", "Ininga")),
    ("ininga parnaiba", ("Ininga", "Teresina")),       
    ("teca ininga", ("Biblioteca", "Ininga")),         
    ("ininga", (None, None)),
])
def test_matches_place_nao_casa(term, fields):
    assert not D.matches_place(term, *fields)

#teste
@pytest.fixture(scope="module")
def place_items(app):
    from sqlalchemy import select
    from application.models import CollectionPoint, Item, User, db
    owner = db.execute(select(User).where(User.email == "carlos@ufpi.edu.br")).scalar_one()
    point = CollectionPoint(name="Guarita Central", building="Rua dos Ipês, Fátima")
    db.add(point)
    db.commit()
    spec = {  # chave: (tipo, local digitado no registro, ponto de coleta, coordenadas)
        "A": ("LOST", "Ininga, Teresina", None, _offset()),
        "B": ("FOUND", "Corredor do Bloco 5", point.id, (None, None)),
        "C": ("FOUND", "Biblioteca Central", None, _offset(lng_km=3.0)),
        "D": ("FOUND", "Avenida São Luís", None, (None, None)),
    }
    ids = {}
    for key, (kind, location, point_id, (lat, lng)) in spec.items():
        item = Item(user_id=owner.id, type=kind, category="ELECTRONIC", title=f"PLACETESTE {key}",
                    description="Descrição longa o suficiente para o teste.", location=location, point_id=point_id,
                    occurred_at=datetime.now(timezone.utc) - timedelta(days=1), latitude=lat, longitude=lng)
        db.add(item)
        db.commit()
        ids[key] = item.id
    yield ids
    for item_id in ids.values():
        db.delete(db.get(Item, item_id))
    db.delete(db.get(CollectionPoint, point.id))
    db.commit()

def _search(client, **params):
    resp = client.get("/api/items", query_string={"q": "PLACETESTE", **params})
    assert resp.status_code == 200, resp.json
    return sorted(i["title"].split()[-1] for i in resp.json["items"]), resp.json

# API principal
def test_sem_filtro_de_local_traz_todos(client, place_items):
    assert _search(client)[0] == ["A", "B", "C", "D"]

def test_local_ignora_acentos_e_caixa(client, place_items):
    assert _search(client, local="sao luis")[0] == ["D"]
    assert _search(client, local="SÃO LUÍS")[0] == ["D"]
    assert _search(client, local="iningá")[0] == ["A"]

def test_local_aceita_palavras_em_qualquer_ordem(client, place_items):
    assert _search(client, local="Teresina, Ininga")[0] == ["A"]

def test_local_tambem_olha_o_ponto_de_coleta(client, place_items):
    assert _search(client, local="guarita")[0] == ["B"]   # nome do ponto
    assert _search(client, local="fatima")[0] == ["B"]    # endereço do ponto
    assert _search(client, local="central")[0] == ["B", "C"]  # ponto de B + local de C

def test_local_inexistente_nao_traz_nada(client, place_items):
    names, body = _search(client, local="Parnaíba")
    assert names == [] and body["total"] == 0 and body["totalPages"] == 1

def test_local_em_branco_nao_filtra(client, place_items):
    assert _search(client, local="   ")[0] == ["A", "B", "C", "D"]

def test_local_combina_com_outros_filtros(client, place_items):
    assert _search(client, local="central", tipo="FOUND")[0] == ["B", "C"]
    assert _search(client, local="central", tipo="LOST")[0] == []
    assert _search(client, local="ininga", tipo="LOST")[0] == ["A"]

def test_local_combina_com_raio(client, place_items):
    assert _search(client, local="central", **GEO, raio=1)[0] == []
    assert _search(client, local="central", **GEO, raio=5)[0] == ["C"]
    assert _search(client, local="central", **GEO)[0] == ["B", "C"] 

def test_total_e_paginas_refletem_o_local(client, place_items):
    names, body = _search(client, local="central", pagina=1)
    assert body["total"] == 2 and body["totalPages"] == 1
    assert _search(client, local="central", pagina=2)[0] == []

def _mvp(client, **params):
    resp = client.get("/api/itens", query_string={"q": "PLACETESTE", **params})
    assert resp.status_code == 200
    return resp.json

def test_mvp_localizacao_ignora_acentos(client, place_items):
    assert [i["localizacao"] for i in _mvp(client, localizacao="sao luis")] == ["Avenida São Luís"]

def test_mvp_localizacao_olha_o_posto(client, place_items):
    found = _mvp(client, localizacao="fátima")
    assert [i["posto_nome"] for i in found] == ["Guarita Central"]
    assert found[0]["posto_endereco"] == "Rua dos Ipês, Fátima"

def test_mvp_localizacao_sem_resultado(client, place_items):
    assert _mvp(client, localizacao="Parnaíba") == []

# página web
def test_pagina_filtra_por_local_e_mostra_o_termo(client, place_items):
    html = client.get("/itens", query_string={"q": "PLACETESTE", "local": "sao luis"}).get_data(as_text=True)
    assert "PLACETESTE D" in html
    assert "PLACETESTE A" not in html and "PLACETESTE B" not in html and "PLACETESTE C" not in html
    assert "1 registro(s) encontrado(s) para “sao luis”" in html
    assert 'name="local" value="sao luis"' in html 

def test_pagina_tem_um_unico_campo_de_local_na_barra_principal(client):
    html = client.get("/itens").get_data(as_text=True)
    assert html.count('name="local"') == 1
    assert 'placeholder="Cidade, bairro ou local"' in html
    assert "registro(s) encontrado(s) para" not in html 