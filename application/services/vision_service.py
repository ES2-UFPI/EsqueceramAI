import base64
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from functools import lru_cache

from application.domain import CATEGORIES, COLORS
from application.services.ai_admin_service import is_ai_enabled_by_admin, monotonic_ms, record_ai_usage

log = logging.getLogger("esqueceram.vision")

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
FALLBACK_MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-3.8-flash")
RETRYABLE_HTTP_CODES = {404, 429, 500, 502, 503, 504}
SUPPORTED_MIMES = ("image/jpeg", "image/png", "image/webp")

_PROMPT = (
    "Analise detalhadamente a fotografia de um objeto para um sistema de achados e perdidos em português. "
    "Extraia o máximo de informações visíveis possível para preencher automaticamente o formulário de cadastro. "
    "Retorne exclusivamente um objeto JSON com as chaves: "
    "\"category\" (exatamente um de: ELECTRONIC, DOCUMENT, ACCESSORY), "
    "\"title\" (título claro do objeto com 2 a 6 palavras), "
    "\"description\" (descrição visual rica e objetiva com formato, textura, estado de conservação, marcas de uso, textos/etiquetas visíveis e detalhes úteis para identificação), "
    "\"color\" (cor predominante considerando iluminação e balanço de branco: escolha a cor base mais próxima entre Preto, Branco, Cinza, Azul, Vermelho, Verde, Amarelo, Rosa, Roxo, Marrom, Laranja, Prata, Dourado e, quando houver tonalidade específica como gelo, grafite ou azul-marinho, informe entre parênteses, ex.: \"Branco (gelo)\", \"Cinza (grafite)\"; vazio se incerto), "
    "\"brand\" (marca ou fabricante visível, ou vazio), "
    "\"model\" (modelo específico visível, ou vazio), "
    "\"attributes\" (objeto JSON com detalhes específicos da categoria escolhida: "
    "se ELECTRONIC use {\"serialNumber\": \"...\", \"compatibility\": \"características técnicas, conexões, tamanho\"}; "
    "se DOCUMENT use {\"documentType\": \"tipo do documento\", \"issuingBody\": \"órgão emissor\"}; "
    "se ACCESSORY use {\"material\": \"material aparente\", \"visualDetails\": \"detalhes visuais, estampas, avarias\"}), "
    "\"visualTags\" (lista de até 8 palavras-chave visuais em minúsculas), "
    "\"visualSummary\" (frase única resumindo o que aparece na foto)."
)


_COMPARE_PROMPT = (
    "Compare estas duas fotografias de um sistema de achados e perdidos em português. "
    "A primeira imagem é do item perdido e a segunda é do item encontrado. "
    "Avalie se as duas fotos mostram o mesmo objeto físico (mesmo modelo, cor, formato, marcas, adesivos ou avarias). "
    "Retorne exclusivamente um objeto JSON com as chaves: "
    "\"similarity\" (número inteiro de 0 a 100 indicando a chance de ser o mesmo objeto), "
    "\"sameObject\" (true ou false), "
    "\"reason\" (frase curta e completa em português, de no máximo 200 caracteres, explicando o motivo visual da pontuação)."
)


def is_vision_enabled() -> bool:
    """Retorna True quando a chave da API Gemini está configurada e a IA está ativa."""
    if not os.getenv("GEMINI_API_KEY", "").strip():
        return False
    try:
        return is_ai_enabled_by_admin()
    except RuntimeError:
        return True


def _match_color(raw_color: str | None) -> str:
    text = (raw_color or "").strip().lower()
    if not text:
        return ""
    for c in COLORS:
        if c.lower() == text or c.lower() in text:
            return c
    return ""


def _extract_custom_color(raw_color: str | None) -> str:
    raw = " ".join(str(raw_color or "").split()).strip()
    if not raw:
        return ""
    m = re.search(r"\(([^)]+)\)", raw)
    if m:
        shade = m.group(1).strip()[:40]
        return shade[:1].upper() + shade[1:] if shade else ""
    if not _match_color(raw):
        return raw[:40]
    return ""


def _normalize_analysis(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    category = raw.get("category") if raw.get("category") in CATEGORIES else "ACCESSORY"
    tags_raw = raw.get("visualTags") if isinstance(raw.get("visualTags"), list) else []
    tags = []
    for t in tags_raw:
        clean = " ".join(str(t or "").strip().lower().split())[:32]
        if clean and clean not in tags:
            tags.append(clean)
        if len(tags) >= 8:
            break
    summary = " ".join(str(raw.get("visualSummary") or "").split())[:240]
    title = " ".join(str(raw.get("title") or "").split())[:120]
    description = str(raw.get("description") or "").strip()[:800]
    if not (summary or title or tags):
        return None
    raw_attrs = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
    allowed_attr_keys = ("serialNumber", "compatibility", "documentType", "issuingBody", "material", "visualDetails")
    attributes = {
        k: " ".join(str(raw_attrs.get(k) or "").split())[:120]
        for k in allowed_attr_keys
        if str(raw_attrs.get(k) or "").strip()
    }
    return {
        "category": category,
        "title": title,
        "description": description,
        "color": _match_color(raw.get("color")),
        "customColor": _extract_custom_color(raw.get("color")),
        "brand": " ".join(str(raw.get("brand") or "").split())[:60],
        "model": " ".join(str(raw.get("model") or "").split())[:60],
        "attributes": attributes,
        "visualTags": tags,
        "visualSummary": summary or title,
    }


def _candidate_models() -> list[str]:
    configured = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip().strip("\"'").removeprefix("models/")
    models = [configured or DEFAULT_GEMINI_MODEL]
    for m in FALLBACK_MODELS:
        if m not in models:
            models.append(m)
    return models


def _call_gemini(endpoint: str, raw_payload: bytes) -> dict:
    req = urllib.request.Request(endpoint, data=raw_payload, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _discover_flash_models(api_key: str, already_tried: set[str]) -> list[str]:
    try:
        with urllib.request.urlopen(f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}", timeout=10) as resp:
            models = json.loads(resp.read().decode("utf-8")).get("models") or []
    except (urllib.error.URLError, OSError, ValueError):
        return []
    found = []
    for m in models:
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        name = str(m.get("name") or "").removeprefix("models/")
        if ("flash" in name or "lite" in name) and name not in already_tried and name not in found:
            found.append(name)
    return found


def _build_vision_payload(image_bytes: bytes, mime_type: str) -> bytes:
    """Monta o payload JSON enviado à API Gemini Vision."""
    payload_dict = {
        "contents": [{
            "parts": [
                {"text": _PROMPT},
                {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}},
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
            "maxOutputTokens": 500,
        },
    }
    return json.dumps(payload_dict).encode("utf-8")


def _request_with_fallback(api_key: str, payload: bytes) -> tuple[dict | None, str]:
    """Executa a chamada ao Gemini com fallback entre modelos e descoberta automática."""
    tried: set[str] = set()
    candidates = _candidate_models()[:3]
    discovered_loaded = False
    idx = 0
    last_model = candidates[0] if candidates else DEFAULT_GEMINI_MODEL
    while idx < len(candidates) and len(tried) < 3:
        model = candidates[idx]
        last_model = model
        idx += 1
        tried.add(model)
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            return _call_gemini(endpoint, payload), model
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:240]
            log.warning("Falha ao analisar imagem com IA (modelo %s, HTTP %s): %s", model, exc.code, detail or exc)
            if exc.code not in RETRYABLE_HTTP_CODES:
                return None, model
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            log.warning("Falha ao analisar imagem com IA (modelo %s): %s", model, exc)
        if idx == len(candidates) and not discovered_loaded and len(tried) < 3:
            discovered_loaded = True
            candidates.extend(_discover_flash_models(api_key, tried))
    return None, last_model


def _parse_gemini_json(body: dict) -> dict | None:
    """Extrai o objeto JSON retornado pelo Gemini Vision."""
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        log.warning("Resposta inválida da IA ao analisar imagem: %s", exc)
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_gemini_response(body: dict) -> dict | None:
    parsed = _parse_gemini_json(body)
    return _normalize_analysis(parsed) if parsed else None


def analyze_item_image(image_bytes: bytes, mime_type: str) -> dict | None:
    """Extrai atributos e tags visuais de uma foto usando Gemini Vision."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or not is_vision_enabled() or not image_bytes or mime_type not in SUPPORTED_MIMES:
        return None
    started = time.monotonic()
    payload = _build_vision_payload(image_bytes, mime_type)
    body, used_model = _request_with_fallback(api_key, payload)
    result = _parse_gemini_response(body) if body else None
    record_ai_usage(
        operation="ANALYZE",
        model=used_model,
        success=result is not None,
        latency_ms=monotonic_ms(started),
        detail=(result or {}).get("title") or "Análise visual de foto",
    )
    return result


def compare_item_images(lost_bytes: bytes, lost_mime: str, found_bytes: bytes, found_mime: str) -> dict | None:
    """Compara diretamente duas imagens (perdido x encontrado) usando Gemini Vision."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if (
        not api_key
        or not is_vision_enabled()
        or not lost_bytes
        or not found_bytes
        or lost_mime not in SUPPORTED_MIMES
        or found_mime not in SUPPORTED_MIMES
    ):
        return None
    started = time.monotonic()
    payload = json.dumps({
        "contents": [{
            "parts": [
                {"text": _COMPARE_PROMPT},
                {"inline_data": {"mime_type": lost_mime, "data": base64.b64encode(lost_bytes).decode("ascii")}},
                {"inline_data": {"mime_type": found_mime, "data": base64.b64encode(found_bytes).decode("ascii")}},
            ]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
            "maxOutputTokens": 350,
        },
    }).encode("utf-8")
    body, used_model = _request_with_fallback(api_key, payload)
    parsed = _parse_gemini_json(body) if body else None
    result = None
    if parsed:
        try:
            sim = max(0, min(100, int(round(float(parsed.get("similarity", 0))))))
        except (TypeError, ValueError):
            sim = 0
        reason = " ".join(str(parsed.get("reason") or "").split())[:360]
        if reason:
            result = {"similarity": sim, "sameObject": bool(parsed.get("sameObject", sim >= 60)), "reason": reason}
    record_ai_usage(
        operation="COMPARE",
        model=used_model,
        success=result is not None,
        latency_ms=monotonic_ms(started),
        detail=f"Similaridade {result['similarity']}%" if result else "Falha na comparação visual",
    )
    return result


@lru_cache(maxsize=256)
def _compare_colors_cached(norm_a: str, norm_b: str) -> int | None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    started = time.monotonic()
    prompt = (
        f'Compare duas cores de objetos perdidos/achados considerando iluminação e ângulo: "{norm_a}" e "{norm_b}". '
        'Retorne JSON: {"similarity": 0 a 100}.'
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.0, "maxOutputTokens": 40},
    }).encode("utf-8")
    body, used_model = _request_with_fallback(api_key, payload)
    parsed = _parse_gemini_json(body) if body else None
    sim = None
    if parsed and "similarity" in parsed:
        try:
            sim = max(0, min(100, int(round(float(parsed["similarity"])))))
        except (TypeError, ValueError):
            sim = None
    record_ai_usage(
        operation="COLOR",
        model=used_model,
        success=sim is not None,
        latency_ms=monotonic_ms(started),
        detail=f"{norm_a} vs {norm_b}: {sim}%" if sim is not None else f"{norm_a} vs {norm_b}: falha",
    )
    return sim


def compare_colors_ai(color_a: str, color_b: str) -> int | None:
    """Compara tonalidades de cor usando IA com cache e baixo custo de tokens."""
    a = " ".join((color_a or "").strip().lower().split())[:40]
    b = " ".join((color_b or "").strip().lower().split())[:40]
    if not a or not b or not is_vision_enabled():
        return None
    if a == b:
        return 100
    pair = (a, b) if a <= b else (b, a)
    return _compare_colors_cached(*pair)
