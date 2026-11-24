import io
import json

from conftest import JPEG, persona_client

from application.services import ai_admin_service, vision_service


def test_ai_admin_page_restricted_and_toggles_ai(app, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    anon = app.test_client()
    assert anon.get("/painel/admin/ia").status_code == 302

    user_c = persona_client(app, "ana@ufpi.edu.br")
    assert user_c.get("/painel/admin/ia").headers["Location"].endswith("erro=permissao")

    admin = persona_client(app, "admin@ufpi.edu.br")
    page = admin.get("/painel/admin/ia")
    assert page.status_code == 200
    assert "Controle e uso da IA" in page.get_data(as_text=True)

    with app.app_context():
        assert vision_service.is_vision_enabled() is True

    # Disable AI via admin panel
    off = admin.post("/painel/admin/ia", data={"enabled": "0"}, follow_redirects=True)
    assert off.status_code == 200
    assert "Reativar IA" in off.get_data(as_text=True)
    with app.app_context():
        assert vision_service.is_vision_enabled() is False

    # Re-enable AI via admin panel
    on = admin.post("/painel/admin/ia", data={"enabled": "1"}, follow_redirects=True)
    assert on.status_code == 200
    assert "Desativar IA" in on.get_data(as_text=True)
    with app.app_context():
        assert vision_service.is_vision_enabled() is True


def test_direct_vision_comparison_works_with_single_candidate_and_logs_usage(app, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    captured_payloads = []

    def fake_call(endpoint, raw_payload):
        body = json.loads(raw_payload.decode("utf-8"))
        captured_payloads.append((endpoint, body))
        parts = body["contents"][0]["parts"]
        if len(parts) == 3:
            return {
                "candidates": [{
                    "content": {
                        "parts": [{
                            "text": json.dumps({
                                "similarity": 92,
                                "sameObject": True,
                                "reason": "Mesma garrafa azul com tampa preta e adesivo lateral.",
                            })
                        }]
                    }
                }]
            }
        return {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "category": "ACCESSORY",
                            "title": "Garrafa azul",
                            "description": "Garrafa térmica azul",
                            "color": "Azul",
                            "brand": "",
                            "model": "",
                            "attributes": {"material": "Inox", "visualDetails": "Tampa preta"},
                            "visualTags": ["garrafa", "azul"],
                            "visualSummary": "Garrafa azul com tampa preta",
                        })
                    }]
                }
            }]
        }

    monkeypatch.setattr(vision_service, "_call_gemini", fake_call)

    ana = persona_client(app, "ana@ufpi.edu.br")
    carlos = persona_client(app, "carlos@ufpi.edu.br")

    lost_resp = ana.post(
        "/api/items",
        data={
            "type": "LOST",
            "category": "ACCESSORY",
            "title": "Garrafa térmica perdida",
            "description": "Perdida no bloco de computação",
            "location": "Centro de Tecnologia (CT)",
            "occurredAt": "2026-11-20",
            "image": (io.BytesIO(JPEG), "lost.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
    )
    assert lost_resp.status_code == 201
    lost_id = lost_resp.json["item"]["id"]

    found_resp = carlos.post(
        "/api/items",
        data={
            "type": "FOUND",
            "category": "ACCESSORY",
            "title": "Garrafa encontrada",
            "description": "Achada perto da sala de aula",
            "location": "Centro de Tecnologia (CT)",
            "occurredAt": "2026-11-20",
            "image": (io.BytesIO(JPEG), "found.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
    )
    assert found_resp.status_code == 201
    found_id = found_resp.json["item"]["id"]

    # Confirm direct comparison (3 parts: prompt + 2 inline_data images) was invoked
    assert any(len(p[1]["contents"][0]["parts"]) == 3 for p in captured_payloads)

    matches = ana.get("/api/matches").json["matches"]
    relevant = [m for m in matches if m["lost"]["id"] == lost_id and m["found"]["id"] == found_id]
    assert len(relevant) == 1
    assert relevant[0]["score"] >= 55
    assert any("Comparação visual direta por IA (92%)" in r for r in relevant[0]["reasons"])

    with app.app_context():
        dash = ai_admin_service.get_ai_dashboard()
        assert dash["totalCalls"] >= 2
        assert any(c["operation"] == "COMPARE" and c["success"] for c in dash["recentCalls"])


def test_custom_color_extraction_and_cached_ai_color_similarity(app, monkeypatch):
    from datetime import datetime, timezone
    from application.services import matching_service

    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    vision_service._compare_colors_cached.cache_clear()
    norm = vision_service._normalize_analysis({
        "category": "ACCESSORY",
        "title": "Garrafa gelo",
        "color": "Branco (gelo)",
        "visualTags": ["garrafa"],
        "visualSummary": "Garrafa cor gelo",
    })
    assert norm["color"] == "Branco"
    assert norm["customColor"] == "Gelo"

    calls = []

    def fake_color_call(endpoint, raw_payload):
        calls.append(json.loads(raw_payload.decode("utf-8")))
        return {"candidates": [{"content": {"parts": [{"text": '{"similarity": 85}'}]}}]}

    monkeypatch.setattr(vision_service, "_call_gemini", fake_color_call)

    now = datetime.now(timezone.utc)
    lost = {
        "category": "ACCESSORY",
        "title": "Mochila",
        "description": "Mochila escolar",
        "location": "Biblioteca",
        "color": "Branco",
        "attributes": {"customColor": "Gelo"},
        "occurredAt": now,
    }
    found = {
        "category": "ACCESSORY",
        "title": "Mochila",
        "description": "Mochila escolar",
        "location": "Biblioteca",
        "color": "Cinza",
        "attributes": {"customColor": "Cinza claro"},
        "occurredAt": now,
    }
    with app.app_context():
        res1 = matching_service.score_pair(lost, found)
        res2 = matching_service.score_pair(lost, found)

    assert len(calls) == 1  # cached on second call!
    assert calls[0]["generationConfig"]["maxOutputTokens"] <= 40
    assert any("Cores próximas segundo IA (85%)" in r for r in res1["reasons"])
    assert res1["score"] == res2["score"]


def test_direct_vision_mismatch_penalizes_score_and_preserves_full_reason(app, monkeypatch):
    from application.services import matching_service

    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    long_reason = (
        "Os objetos são diferentes: a primeira imagem mostra uma garrafa térmica Stanley com alça e "
        "acabamento metálico na tampa, enquanto a segunda mostra um copo/caneca térmica preta sem alça lateral."
    )
    assert len(long_reason) > 180

    monkeypatch.setattr(
        vision_service,
        "_call_gemini",
        lambda endpoint, raw: {
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({"similarity": 20, "sameObject": False, "reason": long_reason})
                    }]
                }
            }]
        },
    )
    with app.app_context():
        cmp = vision_service.compare_item_images(b"a", "image/jpeg", b"b", "image/jpeg")
        assert cmp is not None
        assert cmp["reason"] == long_reason

        monkeypatch.setattr(matching_service, "_load_item_image_bytes", lambda _id: (b"img", "image/jpeg"))
        pair = (
            {"id": 1, "title": "Garrafa Stanley"},
            {"id": 2, "title": "Copo térmico"},
            {"score": 72, "reasons": ["Mesma categoria: Acessório"]},
        )
        matching_service._apply_direct_vision_comparison([pair])
        assert pair[2]["score"] == 43  # 72*0.45 + 20*0.55 = 43 (< 55 MATCH_THRESHOLD)
        assert long_reason in pair[2]["reasons"][0]
