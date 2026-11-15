import csv
import io
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from application import domain
from application.models import CollectionPoint, Item, User, db
from application.services import retention_service
from conftest import persona_client

@pytest.fixture()
def shelf(app, monkeypatch):
    monkeypatch.delenv("STORAGE_RETENTION_DAYS", raising=False)
    owner_id = db.execute(select(User).where(User.email == "carlos@ufpi.edu.br")).scalar_one().id
    point_ids = [p.id for p in db.execute(select(CollectionPoint).order_by(CollectionPoint.id)).scalars()][:2]
    now = datetime.now(timezone.utc)
    made = []

    def _make(*, age=timedelta(days=120), title=None, category="ELECTRONIC", point=0, location="Biblioteca Central",
              color=None, brand=None):
        entered = now - age
        item = Item(user_id=owner_id, type="FOUND", category=category, title=title or f"Item vencido {len(made) + 1}",
                    description="Descrição longa o suficiente para o teste.", location=location, color=color, brand=brand,
                    status="OPEN", occurred_at=entered, point_id=point_ids[point], created_at=entered, updated_at=entered)
        db.add(item)
        db.commit()
        made.append(item.id)
        return item.id
    _make.now = now
    _make.point_ids = point_ids
    yield _make
    for item_id in made:
        row = db.get(Item, item_id)
        if row:
            db.delete(row)
    db.commit()

def _ids(result_or_items):
    items = result_or_items["items"] if isinstance(result_or_items, dict) else result_or_items
    return [i["id"] for i in items]

@pytest.mark.parametrize("path", ["/painel/descarte", "/painel/descarte.csv"])
def test_report_is_restricted_to_staff(app, path):
    anon = app.test_client().get(path)
    assert anon.status_code == 302 and "/entrar" in anon.headers["Location"]
    for persona in ("ana@ufpi.edu.br", "carlos@ufpi.edu.br"):
        r = persona_client(app, persona).get(path)
        assert r.status_code == 302 and r.headers["Location"].endswith("erro=permissao"), persona
    for persona in ("operador@ufpi.edu.br", "admin@ufpi.edu.br"):
        assert persona_client(app, persona).get(path).status_code == 200, persona

def test_page_lists_only_overdue_items(app, shelf):
    shelf(title="Mochila zzlista vencida", age=timedelta(days=120))
    shelf(title="Carregador zzlista recente", age=timedelta(days=10))
    html = persona_client(app, "operador@ufpi.edu.br").get("/painel/descarte?q=zzlista").get_data(as_text=True)
    assert "Mochila zzlista vencida" in html
    assert "Carregador zzlista recente" not in html

def test_page_escapes_item_titles(app, shelf):
    shelf(title="<script>zzxss</script>")
    html = persona_client(app, "admin@ufpi.edu.br").get("/painel/descarte?q=zzxss").get_data(as_text=True)
    assert "<script>zzxss" not in html and "&lt;script&gt;zzxss" in html

def test_page_empty_state(app):
    html = persona_client(app, "operador@ufpi.edu.br").get("/painel/descarte?q=nada-com-este-nome-zzvazio").get_data(as_text=True)
    assert "Nenhum item elegível" in html

def test_page_ignores_invalid_params(app):
    c = persona_client(app, "operador@ufpi.edu.br")
    for qs in ("ponto=abc", "ponto=99999999", "categoria=XYZ", "dias=7", "dias=abc", "ordem=foo", "pagina=-3", "pagina=abc"):
        assert c.get(f"/painel/descarte?{qs}").status_code == 200, qs
        assert c.get(f"/painel/descarte.csv?{qs}").status_code == 200, qs

def test_filter_by_text_ignores_accents_and_matches_code(shelf):
    camera = shelf(title="Câmera zztexto", brand="Canon")
    other = shelf(title="Garrafa zztexto")
    assert _ids(retention_service.filter_disposal_candidates({"q": "camera zztexto"})) == [camera]
    assert _ids(retention_service.filter_disposal_candidates({"q": "CANON"})) == [camera]
    assert _ids(retention_service.filter_disposal_candidates({"q": domain.item_code(other)})) == [other]

def test_filter_by_point_and_category(shelf):
    a = shelf(title="Item zzfiltro a", point=0, category="ELECTRONIC")
    b = shelf(title="Item zzfiltro b", point=1, category="DOCUMENT")
    base = {"q": "zzfiltro"}
    assert _ids(retention_service.filter_disposal_candidates({**base, "pointId": shelf.point_ids[0]})) == [a]
    assert _ids(retention_service.filter_disposal_candidates({**base, "pointId": shelf.point_ids[1]})) == [b]
    assert _ids(retention_service.filter_disposal_candidates({**base, "category": "DOCUMENT"})) == [b]
    assert _ids(retention_service.filter_disposal_candidates({**base, "pointId": shelf.point_ids[0], "category": "DOCUMENT"})) == []

def test_filter_by_minimum_days(shelf):
    old = shelf(title="Item zzdias antigo", age=timedelta(days=400))
    mid = shelf(title="Item zzdias medio", age=timedelta(days=150))
    base = {"q": "zzdias"}
    assert _ids(retention_service.filter_disposal_candidates(base)) == [old, mid]
    assert _ids(retention_service.filter_disposal_candidates({**base, "minDays": 180})) == [old]
    assert _ids(retention_service.filter_disposal_candidates({**base, "minDays": 500})) == []

def test_sort_orders(shelf):
    novo = shelf(title="Bolsa zzordem", age=timedelta(days=100))
    velho = shelf(title="Anel zzordem", age=timedelta(days=300))
    meio = shelf(title="Caneta zzordem", age=timedelta(days=200))
    base = {"q": "zzordem"}
    assert _ids(retention_service.filter_disposal_candidates(base)) == [velho, meio, novo]
    assert _ids(retention_service.filter_disposal_candidates({**base, "sort": "recentes"})) == [novo, meio, velho]
    assert _ids(retention_service.filter_disposal_candidates({**base, "sort": "titulo"})) == [velho, novo, meio]

def test_pagination_clamps_the_page(shelf):
    ids = [shelf(title=f"Item zzpag {n}", age=timedelta(days=120 + n)) for n in range(5)]
    f = {"q": "zzpag", "sort": "recentes"}
    first = retention_service.search_disposal_candidates(f, page=1, page_size=2)
    last = retention_service.search_disposal_candidates(f, page=99, page_size=2)
    assert (first["total"], first["totalPages"], first["page"]) == (5, 3, 1)
    assert _ids(first) == ids[:2]
    assert (last["page"], _ids(last)) == (3, ids[4:])
    assert retention_service.search_disposal_candidates(f, page=0, page_size=2)["page"] == 1

def test_summary_counts_all_eligible_items_regardless_of_filters(shelf):
    shelf(title="Item zzresumo", age=timedelta(days=500))
    result = retention_service.search_disposal_candidates({"q": "zzresumo"})
    assert result["total"] == 1
    assert result["eligible"] >= 1
    assert result["oldestDays"] >= 500
    assert result["points"] >= 1
    assert result["retentionDays"] == 90

def test_csv_export_respects_filters(app, shelf):
    shelf(title="Fone zzcsv a", point=0, location="Sala; 12", color="Preto")
    shelf(title="Fone zzcsv b", point=1)
    r = persona_client(app, "operador@ufpi.edu.br").get(f"/painel/descarte.csv?q=zzcsv&ponto={shelf.point_ids[0]}")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    assert r.headers["Content-Disposition"].startswith("attachment; filename=")
    assert r.data.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(r.data.decode("utf-8-sig")), delimiter=";"))
    assert tuple(rows[0]) == retention_service.CSV_HEADER
    assert len(rows) == 2 and rows[1][1] == "Fone zzcsv a" and rows[1][4] == "Sala; 12" and rows[1][5] == "Preto"

def test_csv_neutralizes_spreadsheet_formulas(app, shelf):
    shelf(title='=HYPERLINK("http://x.test";"zzformula")')
    r = persona_client(app, "admin@ufpi.edu.br").get("/painel/descarte.csv?q=zzformula")
    rows = list(csv.reader(io.StringIO(r.data.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 2 and rows[1][1].startswith("'=")
