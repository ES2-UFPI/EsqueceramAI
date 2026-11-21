import logging
import math
import os
import re
import unicodedata
import urllib.error
import urllib.request

from application.domain import CATEGORY_LABEL, FINAL_STATUSES
from application.delivery.email_service import EmailError, send_match_notification
from application.errors import ApiError, forbidden, not_found
from application.repositories.engagement import (add_item_event, claim_match_notification, create_notifications,
                                         find_match_by_id, find_match_pairs_for_item, finish_match_notification,
                                         list_matches, match_notifications, update_match_status, upsert_match)
from application.repositories.items import find_item_by_id, list_open_by_type, set_item_status
from application.repositories.users import add_user_score, find_user_by_id
from application.services import storage_service, vision_service

log = logging.getLogger("esqueceram.matching")

MATCH_THRESHOLD = 55
NOTIFICATION_THRESHOLD = int(os.getenv("MATCH_NOTIFY_THRESHOLD", "75"))
VISION_COMPARE_PREFILTER = 60
VISION_COMPARE_MAX_CANDIDATES = 3

STOPWORDS = {"de", "da", "do", "das", "dos", "com", "para", "por", "que", "uma", "um", "na", "no", "nas",
             "nos", "em", "e", "o", "a", "os", "as", "meu", "minha", "encontrado", "encontrada", "perdido",
             "perdida", "acho", "encontrei", "perdi", "favor", "por favor", "the", "and"}


def _round(x: float) -> int:  # Math.round do JS arredonda .5 para cima
    return math.floor(x + 0.5)


def normalize(value) -> str:
    s = unicodedata.normalize("NFD", (value or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(value) -> set[str]:
    return {w for w in normalize(value).split(" ") if len(w) > 2 and w not in STOPWORDS}


def overlap_ratio(a: set, b: set) -> float:
    if not a or not b:
        return 0
    return len(a & b) / min(len(a), len(b))


def shared_words(a, b) -> list[str]:
    right = tokens(b)
    return [w for w in tokens(a) if w in right][:4]


def _visual_tokens(item: dict) -> set[str]:
    v = item.get("aiVisual") or {}
    if not isinstance(v, dict):
        return set()
    parts = [v.get("visualSummary") or "", " ".join(v.get("visualTags") or []), v.get("brand") or "", v.get("color") or ""]
    return tokens(" ".join(parts))


def _text_tokens(item: dict) -> set[str]:
    return tokens(" ".join(str(item.get(k) or "") for k in ("title", "description", "color", "brand", "model")))


def _full_color(item: dict) -> str:
    base = str(item.get("color") or "").strip()
    custom = str((item.get("attributes") or {}).get("customColor") or "").strip()
    if base and custom and custom.lower() not in base.lower():
        return f"{base} ({custom})"
    return custom or base


def _score_metadata(lost: dict, found: dict) -> tuple[int, list[str]]:
    """Pontua compatibilidade de cor (incluindo cor exata via IA), marca e modelo."""
    score = 0
    reasons: list[str] = []

    lc_full, fc_full = _full_color(lost), _full_color(found)
    lc, fc = normalize(lc_full), normalize(fc_full)
    if lc and fc:
        if lc == fc or normalize(lost.get("color")) and normalize(lost.get("color")) == normalize(found.get("color")):
            score += 16
            reasons.append(f"Cor compatível: {lc_full}")
        elif overlap_ratio(tokens(lc_full), tokens(fc_full)) > 0:
            score += 8
            reasons.append(f"Tons próximos: {lc_full} / {fc_full}")
        else:
            sim = vision_service.compare_colors_ai(lc_full, fc_full)
            if sim is not None and sim >= 60:
                score += max(6, _round(sim * 0.14))
                reasons.append(f"Cores próximas segundo IA ({sim}%): {lc_full} / {fc_full}")

    lb, fb = normalize(lost.get("brand")), normalize(found.get("brand"))
    if lb and fb:
        if lb == fb:
            score += 12
            reasons.append(f"Marca em comum: {lost['brand']}")
        elif lb in fb or fb in lb:
            score += 7
            reasons.append("Marcas semelhantes")

    lm, fm = normalize(lost.get("model")), normalize(found.get("model"))
    if lm and fm:
        if lm == fm:
            score += 12
            reasons.append(f"Modelo em comum: {lost['model']}")
        elif overlap_ratio(tokens(lost.get("model")), tokens(found.get("model"))) > 0.4:
            score += 6
            reasons.append("Modelo parecido")

    return score, reasons


def _score_text_fields(lost: dict, found: dict) -> tuple[int, list[str]]:
    """Pontua similaridade entre título, descrição e local."""
    score = 0
    reasons: list[str] = []

    title_overlap = overlap_ratio(tokens(lost["title"]), tokens(found["title"]))
    if title_overlap > 0:
        score += _round(title_overlap * 16)
        words = shared_words(lost["title"], found["title"])
        if words:
            reasons.append(f"Título com termos em comum: {', '.join(words)}")

    desc_overlap = overlap_ratio(tokens(lost["description"]), tokens(found["description"]))
    if desc_overlap > 0:
        score += _round(desc_overlap * 12)
        if desc_overlap >= 0.3:
            reasons.append("Descrições muito parecidas")

    loc_overlap = overlap_ratio(tokens(lost["location"]), tokens(found["location"]))
    if loc_overlap > 0:
        score += _round(loc_overlap * 10)
        words = shared_words(lost["location"], found["location"])
        if words:
            reasons.append(f"Mesmo local: {', '.join(words)}")

    return score, reasons


def _score_time_proximity(lost: dict, found: dict) -> tuple[int, list[str]]:
    """Pontua proximidade temporal entre os registros."""
    diff_days = abs((lost["occurredAt"] - found["occurredAt"]).total_seconds()) / 86400
    if diff_days <= 1:
        return 14, ["Registros com menos de 1 dia de diferença"]
    if diff_days <= 3:
        return 10, ["Registros com até 3 dias de diferença"]
    if diff_days <= 7:
        return 6, []
    if diff_days <= 30:
        return 2, []
    return 0, []


def _score_attributes(lost: dict, found: dict) -> tuple[int, list[str]]:
    """Pontua atributos específicos coincidentes."""
    found_attr_values = [f"{k}:{v}" for k, v in (found.get("attributes") or {}).items()]
    found_desc = normalize(found["description"])
    reasons: list[str] = []
    hits = 0
    for key, value in (lost.get("attributes") or {}).items():
        n = normalize(value)
        if not n:
            continue
        if any(n in normalize(e) for e in found_attr_values) or n in found_desc:
            hits += 1
            label = re.sub(r"([A-Z])", r" \1", key).lower()
            reasons.append(f"Atributo coincidente: {label}")
    return min(hits * 5, 10), reasons


def _score_visual_ai(lost: dict, found: dict) -> tuple[int, list[str]]:
    """Pontua compatibilidade com base na análise visual por IA."""
    lv, fv = _visual_tokens(lost), _visual_tokens(found)
    if lv and fv:
        vis_overlap = overlap_ratio(lv, fv)
        if vis_overlap > 0:
            shared = sorted(lv & fv)[:4]
            return _round(vis_overlap * 14), [f"Análise visual por IA compatível: {', '.join(shared)}"]
    elif lv or fv:
        vis_side = lv or fv
        text_side = _text_tokens(found if lv else lost)
        cross_overlap = overlap_ratio(vis_side, text_side)
        if cross_overlap > 0:
            shared = sorted(vis_side & text_side)[:4]
            return _round(cross_overlap * 10), [f"Foto analisada por IA compatível com a descrição: {', '.join(shared)}"]
    return 0, []


def score_pair(lost: dict, found: dict) -> dict:
    """Pontuador determinístico: cada motivo é legível para explicar a sugestão."""
    if lost["category"] != found["category"]:
        return {"score": 0, "reasons": []}

    score = 26
    reasons = [f"Mesma categoria: {CATEGORY_LABEL[lost['category']]}"]

    for scorer in (_score_metadata, _score_text_fields, _score_time_proximity, _score_attributes, _score_visual_ai):
        pts, sub_reasons = scorer(lost, found)
        score += pts
        reasons.extend(sub_reasons)

    return {"score": max(0, min(99, score)), "reasons": reasons[:5]}


def _load_item_image_bytes(item_id: int) -> tuple[bytes, str] | None:
    resolved = storage_service.resolve_item_image(item_id)
    if not resolved:
        return None
    if resolved[0] == "bytes":
        _, mime, data = resolved
        return bytes(data), mime
    if resolved[0] == "redirect":
        _, url = resolved
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                mime = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
                data = resp.read(storage_service.MAX_BYTES + 1)
                if data and len(data) <= storage_service.MAX_BYTES and mime in vision_service.SUPPORTED_MIMES:
                    return data, mime
        except (urllib.error.URLError, OSError, ValueError):
            return None
    return None


def _apply_direct_vision_comparison(scored_pairs: list[tuple[dict, dict, dict]]) -> None:
    """Compara diretamente as fotos dos melhores pares pré-filtrados usando Gemini Vision."""
    if not vision_service.is_vision_enabled():
        return
    eligible = [pair for pair in scored_pairs if pair[2]["score"] > VISION_COMPARE_PREFILTER]
    eligible.sort(key=lambda pair: pair[2]["score"], reverse=True)
    cache: dict[int, tuple[bytes, str] | None] = {}

    for lost, found, result in eligible[:VISION_COMPARE_MAX_CANDIDATES]:
        if lost["id"] not in cache:
            cache[lost["id"]] = _load_item_image_bytes(lost["id"])
        if found["id"] not in cache:
            cache[found["id"]] = _load_item_image_bytes(found["id"])
        lost_img = cache[lost["id"]]
        found_img = cache[found["id"]]
        if not lost_img or not found_img:
            continue
        cmp = vision_service.compare_item_images(lost_img[0], lost_img[1], found_img[0], found_img[1])
        if not cmp:
            continue
        blended = _round(result["score"] * 0.45 + cmp["similarity"] * 0.55)
        if cmp["sameObject"] or cmp["similarity"] >= 60:
            result["score"] = max(0, min(99, max(result["score"], blended)))
        else:
            result["score"] = max(0, min(99, blended))
        result["reasons"] = [f"Comparação visual direta por IA ({cmp['similarity']}%): {cmp['reason']}", *result["reasons"]][:5]


def generate_matches_for_item(item_id: int) -> int:
    """Gera/atualiza sugestões de um item e notifica os dois responsáveis."""
    item = find_item_by_id(item_id)
    if not item or item["status"] == "ARCHIVED" or item["status"] in FINAL_STATUSES:
        return 0
    opposite = list_open_by_type("FOUND" if item["type"] == "LOST" else "LOST")
    candidates = [c for c in opposite if c["userId"] != item["userId"] and c["category"] == item["category"]]
    if not candidates:
        return 0
    existing = {(m.lost_item_id, m.found_item_id) for m in find_match_pairs_for_item(item["id"])}
    scored_pairs = []
    for cand in candidates:
        lost = item if item["type"] == "LOST" else cand
        found = item if item["type"] == "FOUND" else cand
        scored_pairs.append((lost, found, score_pair(lost, found)))

    _apply_direct_vision_comparison(scored_pairs)

    created = 0
    for lost, found, result in scored_pairs:
        if result["score"] < MATCH_THRESHOLD:
            continue
        match = upsert_match(lost_item_id=lost["id"], found_item_id=found["id"], score=result["score"], reasons=result["reasons"])
        if (lost["id"], found["id"]) not in existing:
            created += 1
            create_notifications([
                {"userId": lost["userId"], "type": "MATCH", "title": "Encontramos uma possível correspondência",
                 "body": f"O item \"{found['title']}\" pode ser o seu \"{lost['title']}\". Similaridade de {result['score']}%.",
                 "link": "/painel/matches"},
                {"userId": found["userId"], "type": "MATCH", "title": "Seu achado pode ter um dono",
                 "body": f"O item \"{found['title']}\" tem {result['score']}% de similaridade com \"{lost['title']}\".",
                 "link": "/painel/matches"},
            ])
        if result["score"] >= NOTIFICATION_THRESHOLD:
            notify_match(match.id, lost, found, result)
    return created


def notify_match(match_id: int, lost: dict, found: dict, result: dict) -> int:
    recipient = find_user_by_id(lost["userId"])
    if not recipient or not recipient.email:
        return 0
    if not claim_match_notification(match_id=match_id, user_id=recipient.id, channel="EMAIL"):
        return 0  # já notificado (idempotência) ou outro processo reservou o envio
    try:
        backend = send_match_notification(to=recipient.email, name=recipient.name, lost=lost, found=found,
                                          score=result["score"], reasons=result["reasons"], match_id=match_id)
    except EmailError as exc:
        finish_match_notification(match_id=match_id, user_id=recipient.id, channel="EMAIL", status="FAILED", error=str(exc)[:300])
        log.warning("Falha ao notificar correspondência %s: %s", match_id, exc)
        return 0
    finish_match_notification(match_id=match_id, user_id=recipient.id, channel="EMAIL", status="SENT", error=None)
    return 1


def suggestions_for_user(user_id: int, limit=6):
    return list_matches(user_id=user_id, status="PENDING", limit=limit)


def global_pending_matches(limit=20):
    return list_matches(status="PENDING", limit=limit)


def get_match_for_decision(match_id: int) -> dict | None:
    """Detalhe de uma correspondência para a página do link enviado por e-mail."""
    match = find_match_by_id(match_id)
    if not match:
        return None
    return {**match, "notifications": match_notifications(match_id)}


def decide_match(user: dict, match_id: int, action: str, note: str | None = None) -> dict:
    match = find_match_by_id(match_id)
    if not match:
        raise not_found("Correspondência")
    lost, found = match["lost"], match["found"]
    is_owner = user["id"] in (lost["ownerId"], found["ownerId"])
    if not is_owner and user["role"] not in ("ADMIN", "OPERATOR_POST"):
        raise forbidden("Apenas os responsáveis pelo item ou a equipe podem decidir esta correspondência.")
    if match["status"] != "PENDING":
        raise ApiError("Esta correspondência já foi decidida.", 409)

    if action == "reject":
        update_match_status(match["id"], "REJECTED", user["id"])
        add_item_event(item_id=lost["id"], actor_id=user["id"], status=lost["status"],
                       note=note or f"Correspondência com \"{found['title']}\" descartada.")
        if is_owner:
            recipient = found["ownerId"] if lost["ownerId"] == user["id"] else lost["ownerId"]
        else:
            recipient = lost["ownerId"]
        create_notifications([{"userId": recipient, "type": "UPDATE", "title": "Correspondência descartada",
                               "body": f"A sugestão entre \"{lost['title']}\" e \"{found['title']}\" foi descartada.",
                               "link": "/painel/matches"}])
        return {"status": "REJECTED"}

    update_match_status(match["id"], "CONFIRMED", user["id"])
    if lost["status"] == "OPEN":
        set_item_status(lost["id"], "RESERVED")
    if found["status"] == "OPEN":
        set_item_status(found["id"], "RESERVED")
    add_item_event(item_id=lost["id"], actor_id=user["id"], status="RESERVED",
                   note=note or f"Correspondência confirmada com \"{found['title']}\". Combinar a retirada.")
    add_item_event(item_id=found["id"], actor_id=user["id"], status="RESERVED",
                   note=note or f"Correspondência confirmada com \"{lost['title']}\". Item reservado para retirada.")
    add_user_score(user["id"], 20)
    create_notifications([
        {"userId": lost["ownerId"], "type": "MATCH", "title": "Correspondência confirmada 🎉",
         "body": f"Sua perda \"{lost['title']}\" foi vinculada a \"{found['title']}\". Combine a retirada em um ponto de coleta.",
         "link": f"/itens/{found['id']}"},
        {"userId": found["ownerId"], "type": "MATCH", "title": "Correspondência confirmada 🎉",
         "body": f"O item \"{found['title']}\" será devolvido ao responsável por \"{lost['title']}\".",
         "link": f"/itens/{lost['id']}"},
    ])
    return {"status": "CONFIRMED"}
