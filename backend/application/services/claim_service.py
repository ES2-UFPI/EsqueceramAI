"""US04 — validação de posse por detalhe oculto e pergunta-chave.

Como funciona:
  * quem publica um item ENCONTRADO pode guardar um detalhe confidencial e uma
    pergunta-chave (item 27). O detalhe nunca é serializado; a pergunta só aparece
    para quem se dispõe a reivindicar o item (item 28 e 29);
  * ao reivindicar, o usuário responde à pergunta. A resposta é comparada com um
    HMAC gravado no cadastro (item 30);
  * cada usuário tem no máximo três tentativas por item, e o contador não é
    reiniciado por acertos — respondida a pergunta, a posse é validada para sempre
    (item 31). Isso impede adivinhação repetida sem punir quem acertou.
"""
import hashlib
import hmac
import os
import unicodedata

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from application.errors import ApiError, forbidden, not_found
from application.models import CLAIM_BLOCKED, CLAIM_PENDING, CLAIM_VERIFIED, Item, ItemClaim, ItemSecret, db, utcnow
from application.repositories.engagement import add_item_event, create_notifications
from application.repositories.items import find_item_by_id

MAX_FAILED_ATTEMPTS = 3

SECRET_DETAIL_MIN = 3
SECRET_DETAIL_MAX = 200
SECRET_QUESTION_MIN = 10
SECRET_QUESTION_MAX = 160
SECRET_ANSWER_MIN = 2
SECRET_ANSWER_MAX = 80


def _key() -> bytes:
    return (os.getenv("CLAIM_HMAC_KEY") or os.getenv("SECRET_KEY") or "dev-secret").encode()


def normalize_answer(value: str) -> str:
    """Compara sem acentos, caixa ou pontuação: "Notre-Dame" e "notre dame" valem igual."""
    s = unicodedata.normalize("NFD", (value or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    return " ".join(s.split())


def _mac(item_id: int, answer: str) -> str:
    return hmac.new(_key(), f"claim:{item_id}:{normalize_answer(answer)}".encode(), hashlib.sha256).hexdigest()


def answer_hash(item_id: int, answer: str) -> str:
    return _mac(item_id, answer)


def _check_answer(item_id: int, answer: str, stored_hash: str | None) -> bool:
    if not stored_hash or not normalize_answer(answer):
        return False
    return hmac.compare_digest(_mac(item_id, answer), stored_hash)


# ------------------------------------------------------------------ cadastro
def is_claimable(item: dict | None) -> bool:
    """Só item ENCONTRADO e ainda disponível pode receber pergunta-chave."""
    return bool(item and item["type"] == "FOUND" and item["status"] in ("OPEN", "RESERVED"))


def _require_owner(user: dict, item: dict):
    if item["userId"] != user["id"] and user["role"] != "ADMIN":
        raise forbidden("Apenas quem registrou o item pode definir a pergunta-chave.")


class _IncompleteSecret(Exception):
    pass


def _read_secret(raw: dict) -> dict | None:
    """Bloco preenchido, ou ``None`` quando todos os campos vieram em branco."""
    detail = str(raw.get("secretDetail") or "").strip()[:SECRET_DETAIL_MAX]
    question = str(raw.get("secretQuestion") or "").strip()[:SECRET_QUESTION_MAX]
    answer = str(raw.get("secretAnswer") or "").strip()[:SECRET_ANSWER_MAX]
    if not (detail or question or answer):
        return None
    if len(detail) < SECRET_DETAIL_MIN or len(question) < SECRET_QUESTION_MIN or len(answer) < SECRET_ANSWER_MIN:
        raise _IncompleteSecret
    return {"detail": detail, "question": question, "answer": answer}


def save_secret(user: dict, item_id: int, form: dict) -> ItemSecret | None:
    """Grava (ou atualiza) o detalhe confidencial. ``form`` é o formulário do item."""
    item = find_item_by_id(item_id)
    if not item:
        raise not_found("Registro")
    _require_owner(user, item)
    current = db.get(ItemSecret, item_id)
    try:
        block = _read_secret(form)
    except _IncompleteSecret:
        raise ApiError("Para usar a validação por pergunta, informe o detalhe, a pergunta "
                       f"(mínimo {SECRET_QUESTION_MIN} caracteres) e a resposta.", 422,
                       {"secretQuestion": ["Detalhe, pergunta e resposta são obrigatórios juntos."]})
    if block is not None and item["type"] != "FOUND":
        raise ApiError("Apenas itens encontrados podem ter detalhe oculto.", 422)
    if block is None:
        if current:  # apagou o bloco: deixa de haver validação por pergunta
            db.delete(current)
            db.commit()
            add_item_event(item_id=item_id, actor_id=user["id"], status=item["status"],
                           note="Pergunta-chave removida do registro.")
        return None
    if current:
        current.detail, current.question = block["detail"], block["question"]
        current.answer_hash, current.updated_at = answer_hash(item_id, block["answer"]), utcnow()
        row = current
    else:
        row = ItemSecret(item_id=item_id, detail=block["detail"], question=block["question"],
                         answer_hash=answer_hash(item_id, block["answer"]))
        db.add(row)
    db.commit()
    add_item_event(item_id=item_id, actor_id=user["id"], status=item["status"],
                   note="Pergunta-chave de validação de posse definida.")
    return row


def get_secret(item_id: int) -> ItemSecret | None:
    return db.get(ItemSecret, item_id)


def remove_secret_for_item(item_id: int):
    row = db.get(ItemSecret, item_id)
    if row:
        db.delete(row)
        db.commit()


# ------------------------------------------------------------------ reivindicação
def _load_claim(item_id: int, claimant: dict) -> ItemClaim | None:
    return db.execute(select(ItemClaim).where(ItemClaim.item_id == item_id,
                                              ItemClaim.claimant_id == claimant["id"])).scalar_one_or_none()


def _attempts_left(attempts: int) -> int:
    return max(MAX_FAILED_ATTEMPTS - attempts, 0)


def _require_claimable_item(item: dict) -> None:
    if item["type"] != "FOUND":
        raise ApiError("Apenas itens encontrados podem ser reivindicados.", 422)
    if item["status"] not in ("OPEN", "RESERVED"):
        raise ApiError("Este item não está disponível para reivindicação.", 409)


def challenge(item_id: int, user: dict) -> dict | None:
    """Retorna apenas a pergunta (nunca o detalhe) para quem vai reivindicar o item."""
    item = find_item_by_id(item_id)
    if not item:
        raise not_found("Registro")
    _require_claimable_item(item)
    secret = get_secret(item_id)
    if not secret:
        return None
    if user["id"] == item["userId"]:
        raise ApiError("Você registrou este item; não é possível reivindicá-lo.", 409)
    claim = _load_claim(item_id, user)
    status = claim.status if claim else CLAIM_PENDING
    return {"itemId": item_id, "question": secret.question, "status": status,
            "attemptsLeft": _attempts_left(claim.attempts if claim else 0),
            "verified": status == CLAIM_VERIFIED, "blocked": status == CLAIM_BLOCKED}


def _resolve_claim(item_id: int, user: dict) -> ItemClaim:
    claim = _load_claim(item_id, user)
    try:
        claim = claim or ItemClaim(item_id=item_id, claimant_id=user["id"])
        db.add(claim)
        db.commit()
    except IntegrityError:  # duas requisições simultâneas criaram a mesma linha
        db.rollback()
        claim = _load_claim(item_id, user)
    return claim


def answer(item_id: int, user: dict, response: str) -> dict:
    item = find_item_by_id(item_id)
    if not item:
        raise not_found("Registro")
    _require_claimable_item(item)
    secret = get_secret(item_id)
    if not secret:
        raise ApiError("Este item não usa pergunta de segurança; use a correspondência para validar a posse.", 409)
    if user["id"] == item["userId"]:
        raise ApiError("Você registrou este item; não é possível reivindicá-lo.", 409)

    claim = _resolve_claim(item_id, user)
    if claim.status == CLAIM_BLOCKED:
        raise ApiError("Você atingiu o limite de tentativas para este item.", 429,
                       {"answer": ["Limite de tentativas atingido."]})
    if claim.status == CLAIM_VERIFIED:
        return {"verified": True, "attemptsLeft": _attempts_left(claim.attempts), "blocked": False}

    if not normalize_answer(response):
        raise ApiError("Informe a resposta da pergunta.", 422, {"answer": ["Campo obrigatório."]})

    if _check_answer(item_id, response, secret.answer_hash):
        claim.status, claim.verified_at, claim.last_attempt_at = CLAIM_VERIFIED, utcnow(), utcnow()
        db.commit()
        add_item_event(item_id=item_id, actor_id=user["id"], status=item["status"],
                       note="Posse validada pela pergunta-chave.")
        _notify_owner(item, user)
        return {"verified": True, "attemptsLeft": _attempts_left(claim.attempts), "blocked": False}

    claim.attempts += 1
    claim.last_attempt_at = utcnow()
    if claim.attempts >= MAX_FAILED_ATTEMPTS:
        claim.status = CLAIM_BLOCKED
    db.commit()
    left = _attempts_left(claim.attempts)
    if left <= 0:
        add_item_event(item_id=item_id, actor_id=user["id"], status=item["status"],
                       note="Tentativas de validação de posse esgotadas.")
        raise ApiError("Resposta incorreta. Você atingiu o limite de tentativas para este item.", 429,
                       {"answer": ["Limite de tentativas atingido."]})
    add_item_event(item_id=item_id, actor_id=user["id"], status=item["status"],
                   note=f"Tentativa de validação de posse incorreta ({claim.attempts}/{MAX_FAILED_ATTEMPTS}).")
    raise ApiError(f"Resposta incorreta. Restam {left} tentativa(s).", 422,
                   {"answer": [f"Resposta incorreta. Restam {left} tentativa(s)."]})


def _notify_owner(item: dict, claimant: dict):
    create_notifications([{
        "userId": item["userId"], "type": "RECOVERY",
        "title": "Alguém validou a posse do seu achado",
        "body": f"{claimant['name']} respondeu corretamente à pergunta de segurança de \"{item['title']}\" "
                "e é o provável dono. Combine a retirada no ponto de coleta.",
        "link": f"/itens/{item['id']}",
    }])


def status_for(user: dict | None, item: dict) -> dict:
    """Estado da reivindicação para a página de detalhe (nunca revela o detalhe oculto)."""
    if not user:
        return {"available": False, "reason": "login"}
    if user["id"] == item["userId"]:
        return {"available": False, "reason": "owner"}
    secret = get_secret(item["id"])
    if not secret:
        return {"available": False, "reason": "no-question"}
    if not is_claimable(item):
        return {"available": False, "reason": "unavailable"}
    claim = _load_claim(item["id"], user)
    return {"available": True, "reason": None,
            "status": claim.status if claim else CLAIM_PENDING,
            "attemptsLeft": _attempts_left(claim.attempts if claim else 0),
            "verified": bool(claim and claim.status == CLAIM_VERIFIED),
            "blocked": bool(claim and claim.status == CLAIM_BLOCKED)}
