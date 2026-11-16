import io
import json
import urllib.error
from datetime import datetime, timezone

from application.models import Item, ItemImage, db
from application.services import matching_service, vision_service
from conftest import persona_client

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class _FakeResp:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._raw


def _gemini_payload(data: dict) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(data)}]}}]}


def test_analyze_item_image_returns_none_without_key_or_on_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert vision_service.is_vision_enabled() is False
    assert vision_service.analyze_item_image(PNG, "image/png") is None

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    def boom(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(vision_service.urllib.request, "urlopen", boom)
    assert vision_service.analyze_item_image(PNG, "image/png") is None


def test_analyze_item_image_normalizes_gemini_response(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    sample = {
        "category": "ELECTRONIC",
        "title": "Fone Bluetooth JBL preto",
        "description": "Fone intra-auricular preto com estojo de carregamento.",
        "color": "preto",
        "brand": "JBL",
        "model": "Tune 230NC",
        "visualTags": ["Fone", "Bluetooth", "Preto", "Estojo", "JBL"],
        "visualSummary": "Estojo de fone sem fio preto da marca JBL.",
    }
    monkeypatch.setattr(vision_service.urllib.request, "urlopen", lambda *_a, **_kw: _FakeResp(_gemini_payload(sample)))
    res = vision_service.analyze_item_image(PNG, "image/png")
    assert res is not None
    assert res["category"] == "ELECTRONIC"
    assert res["color"] == "Preto"
    assert res["brand"] == "JBL"
    assert "fone" in res["visualTags"] and "jbl" in res["visualTags"]


def test_vision_analyze_endpoint(app, monkeypatch):
    anon = app.test_client()
    assert anon.post("/api/vision/analyze").status_code == 401

    user = persona_client(app, "carlos@ufpi.edu.br")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert user.post("/api/vision/analyze").status_code == 503

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    bad = user.post(
        "/api/vision/analyze",
        data={"image": (io.BytesIO(b"GIF89a"), "anim.gif", "image/gif")},
        content_type="multipart/form-data",
    )
    assert bad.status_code == 422

    sample = {
        "category": "ACCESSORY",
        "title": "Garrafa térmica azul",
        "description": "Garrafa metálica azul com tampa preta.",
        "color": "Azul",
        "brand": "Stanley",
        "model": "",
        "visualTags": ["garrafa", "termica", "azul", "metalica"],
        "visualSummary": "Garrafa térmica metálica azul.",
    }
    monkeypatch.setattr(vision_service.urllib.request, "urlopen", lambda *_a, **_kw: _FakeResp(_gemini_payload(sample)))
    ok = user.post(
        "/api/vision/analyze",
        data={"image": (io.BytesIO(PNG), "garrafa.png", "image/png")},
        content_type="multipart/form-data",
    )
    assert ok.status_code == 200
    body = ok.get_json()
    assert body["enabled"] is True and body["analysis"]["brand"] == "Stanley"


def test_matching_uses_ai_visual_cross_and_photo_to_photo():
    now = datetime.now(timezone.utc)
    base_lost = {
        "category": "ACCESSORY", "title": "Mochila perdida", "description": "Esqueci no corredor.",
        "location": "CCHL", "occurredAt": now, "attributes": {},
        "aiVisual": {"visualSummary": "Mochila preta com chaveiro vermelho", "visualTags": ["mochila", "preta", "chaveiro", "vermelho"]},
    }
    base_found = {
        "category": "ACCESSORY", "title": "Mochila encontrada", "description": "Deixada na mesa.",
        "location": "CCHL", "occurredAt": now, "attributes": {},
        "aiVisual": {"visualSummary": "Mochila escolar preta com chaveiro vermelho", "visualTags": ["mochila", "preta", "chaveiro", "vermelho"]},
    }
    both = matching_service.score_pair(base_lost, base_found)
    assert any("Análise visual por IA compatível" in r for r in both["reasons"])

    no_ai_found = {**base_found, "aiVisual": None, "description": "Mochila preta com chaveiro vermelho encontrada na mesa."}
    cross = matching_service.score_pair(base_lost, no_ai_found)
    assert any("Foto analisada por IA compatível com a descrição" in r for r in cross["reasons"])
    assert both["score"] >= cross["score"]


def test_item_creation_stores_image_and_ai_visual(app, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    sample = {
        "category": "ACCESSORY",
        "title": "Óculos de grau preto",
        "description": "Armação preta retangular.",
        "color": "Preto",
        "brand": "",
        "model": "",
        "visualTags": ["oculos", "armacao", "preta"],
        "visualSummary": "Óculos de grau com armação preta retangular.",
    }
    monkeypatch.setattr(vision_service.urllib.request, "urlopen", lambda *_a, **_kw: _FakeResp(_gemini_payload(sample)))
    user = persona_client(app, "carlos@ufpi.edu.br")
    r = user.post(
        "/api/items",
        data={
            "type": "FOUND", "category": "ACCESSORY", "title": "Óculos encontrados",
            "description": "Encontrado próximo à cantina do CT.", "location": "Centro de Tecnologia",
            "occurredAt": "2026-11-10", "image": (io.BytesIO(PNG), "oculos.png", "image/png"),
        },
        content_type="multipart/form-data",
    )
    assert r.status_code == 201
    item_id = r.get_json()["item"]["id"]
    row = db.get(Item, item_id)
    assert row.ai_visual is not None and row.ai_visual["visualSummary"] == sample["visualSummary"]
    img = db.query(ItemImage).filter_by(item_id=item_id).one_or_none()
    assert img is not None and img.size_bytes == len(PNG)
    assert sample["visualSummary"] in user.get(f"/itens/{item_id}").get_data(as_text=True)
    db.delete(row)
    db.commit()


def test_item_form_renders_camera_and_photo_before_details(app):
    user = persona_client(app, "carlos@ufpi.edu.br")
    html = user.get("/painel/itens/novo").get_data(as_text=True)
    for needle in ('id="item-cam-open"', 'id="item-image-capture"', 'capture="environment"', 'data-vision-analyze'):
        assert needle in html
    assert html.index('name="image"') < html.index('name="title"') < html.index('name="description"')
    css = user.get("/static/style.css").get_data(as_text=True)
    assert ".photo-actions" in css and "min-height:44px" in css


def test_analyze_falls_back_to_next_model_on_404(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_MODEL", "models/gemini-inexistente")
    tried = []
    sample = {
        "category": "ACCESSORY", "title": "Chaveiro", "description": "Chaveiro prateado.",
        "color": "Prata", "brand": "", "model": "", "visualTags": ["chaveiro"], "visualSummary": "Chaveiro prateado.",
    }

    def fake_open(req, timeout=15):
        tried.append(req.full_url)
        if "gemini-inexistente" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error":"not found"}'))
        return _FakeResp(_gemini_payload(sample))

    monkeypatch.setattr(vision_service.urllib.request, "urlopen", fake_open)
    res = vision_service.analyze_item_image(PNG, "image/png")
    assert res is not None and res["title"] == "Chaveiro"
    assert len(tried) == 2 and "gemini-inexistente:generateContent" in tried[0]


def test_analyze_falls_back_on_503_and_timeout(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    sample = {
        "category": "ACCESSORY", "title": "Garrafa", "description": "Garrafa azul.",
        "color": "Azul", "brand": "", "model": "", "visualTags": ["garrafa"], "visualSummary": "Garrafa azul.",
    }
    calls = []

    def fake_open(req, timeout=25):
        calls.append(req.full_url)
        if "gemini-3.8-flash:" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 503, "Unavailable", {}, io.BytesIO(b'{"error":"high demand"}'))
        if "gemini-3.5-flash-lite:" in req.full_url:
            raise TimeoutError("The read operation timed out")
        return _FakeResp(_gemini_payload(sample))

    monkeypatch.setattr(vision_service.urllib.request, "urlopen", fake_open)
    res = vision_service.analyze_item_image(PNG, "image/png")
    assert res is not None and res["title"] == "Garrafa"
    assert len(calls) >= 3
