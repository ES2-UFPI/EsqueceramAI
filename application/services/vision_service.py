import base64
import json
import logging
import os
import urllib.error
import urllib.request

from application.domain import CATEGORIES, COLORS

log = logging.getLogger("esqueceram.vision")

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
FALLBACK_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash")
SUPPORTED_MIMES = ("image/jpeg", "image/png", "image/webp")

_PROMPT = (
    "Analise a fotografia de um objeto para um sistema universitário de achados e perdidos em português. "
    "Retorne exclusivamente um objeto JSON com as chaves: "
    "\"category\" (exatamente um de: ELECTRONIC, DOCUMENT, ACCESSORY), "
    "\"title\" (título curto do objeto com 2 a 6 palavras), "
    "\"description\" (descrição visual objetiva com detalhes visíveis, estado e marcas), "
    "\"color\" (uma cor simples em português, ex.: Preto, Azul, Branco, ou vazio se incerto), "
    "\"brand\" (marca visível ou vazio), "
    "\"model\" (modelo visível ou vazio), "
    "\"visualTags\" (lista de até 8 palavras-chave visuais em minúsculas), "
    "\"visualSummary\" (frase única resumindo o que aparece na foto)."
)


def is_vision_enabled() -> bool:
    """Retorna True quando a chave da API Gemini está configurada."""
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def _match_color(raw_color: str | None) -> str:
    text = (raw_color or "").strip().lower()
    if not text:
        return ""
    for c in COLORS:
        if c.lower() == text or c.lower() in text:
            return c
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
    return {
        "category": category,
        "title": title,
        "description": description,
        "color": _match_color(raw.get("color")),
        "brand": " ".join(str(raw.get("brand") or "").split())[:60],
        "model": " ".join(str(raw.get("model") or "").split())[:60],
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
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def analyze_item_image(image_bytes: bytes, mime_type: str) -> dict | None:
    """Extrai atributos e tags visuais de uma foto usando Gemini Vision."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or not image_bytes or mime_type not in SUPPORTED_MIMES:
        return None
    payload = json.dumps({
        "contents": [{
            "parts": [
                {"text": _PROMPT},
                {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}},
            ]
        }],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }).encode("utf-8")

    body = None
    for model in _candidate_models():
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        try:
            body = _call_gemini(endpoint, payload)
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:240]
            log.warning("Falha ao analisar imagem com IA (modelo %s, HTTP %s): %s", model, exc.code, detail or exc)
            if exc.code == 404:
                continue
            return None
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.warning("Falha ao analisar imagem com IA: %s", exc)
            return None
    if not body:
        return None
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        log.warning("Resposta inválida da IA ao analisar imagem: %s", exc)
        return None
    return _normalize_analysis(parsed)
