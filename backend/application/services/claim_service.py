"""US04 — detalhe oculto e pergunta-chave (#27).

Quem registra um item ENCONTRADO pode guardar um detalhe confidencial (marca de arranhão,
cor da capa interna…) e uma pergunta-chave derivada dele. O detalhe nunca é serializado por
nenhuma listagem: ele vive em ``item_secrets``, numa tabela própria que só este módulo lê.

A resposta é gravada como HMAC (nunca em claro), então o banco não guarda o que basta para
acertar a pergunta. Este módulo cuida só do **cadastro**; o fluxo de reivindicação em si
(mostrar a pergunta, validar e bloquear tentativas) entra nos tickets seguintes.
"""
import hashlib
import hmac
import os
import unicodedata

from application.errors import ApiError, forbidden, not_found
from application.models import ItemSecret, db, utcnow
from application.repositories.engagement import add_item_event
from application.repositories.items import find_item_by_id, is_seeded_item

SECRET_DETAIL_MIN = 3
SECRET_DETAIL_MAX = 200
SECRET_QUESTION_MIN = 10
SECRET_QUESTION_MAX = 160
SECRET_ANSWER_MIN = 2
SECRET_ANSWER_MAX = 80

_TRUE = ("1", "true", "on", "sim")


def _key() -> bytes:
    return (os.getenv("CLAIM_HMAC_KEY") or os.getenv("SECRET_KEY") or "dev-secret").encode()


def normalize_answer(value: str) -> str:
    """Compara sem acentos, caixa ou pontuação: "Notre-Dame" e "notre dame" valem igual."""
    s = unicodedata.normalize("NFD", (value or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = "".join(ch if ch.isalnum() else " " for ch in s)
    return " ".join(s.split())


def answer_hash(item_id: int, answer: str) -> str:
    return hmac.new(_key(), f"claim:{item_id}:{normalize_answer(answer)}".encode(), hashlib.sha256).hexdigest()


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


def _require_owner(user: dict, item: dict):
    if item["userId"] != user["id"] and user["role"] != "ADMIN":
        raise forbidden("Apenas quem registrou o item pode definir a pergunta-chave.")


def save_secret(user: dict, item_id: int, form: dict, *, seeded=None) -> ItemSecret | None:
    """Grava (ou atualiza) o detalhe confidencial a partir do formulário do item.

    ``seeded`` informa o estado *anterior* do item quando quem chama já reescreveu as colunas
    dele (a edição grava as demais colunas antes desta função).
    """
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
    if block is not None and (seeded if seeded is not None else is_seeded_item(item)):
        raise ApiError("Os registros demonstrativos não usam pergunta-chave.", 422)

    if block is None:
        # Só remove quando pedido de forma explícita: atualizações parciais do item
        # (por exemplo, mudar o status) não podem apagar a pergunta-chave sem aviso.
        if current and str(form.get("secretClear") or "").lower() in _TRUE:
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


# ------------------------------------------------------------- #29 reivindicação
def _require_claimable_item(item: dict) -> None:
    if item["type"] != "FOUND":
        raise ApiError("Apenas itens encontrados podem ser reivindicados.", 422)
    if item["status"] not in ("OPEN", "RESERVED"):
        raise ApiError("Este item não está disponível para reivindicação.", 409)


def challenge(item_id: int, user: dict) -> dict | None:
    """Mostra a pergunta-chave a quem vai reivindicar — o detalhe nunca sai daqui."""
    item = find_item_by_id(item_id)
    if not item:
        raise not_found("Registro")
    _require_claimable_item(item)
    secret = get_secret(item_id)
    if not secret:
        return None
    if user["id"] == item["userId"]:
        raise ApiError("Você registrou este item; não é possível reivindicá-lo.", 409)
    return {"itemId": item_id, "question": secret.question}


def question_for(user: dict | None, item: dict) -> str | None:
    """Pergunta exibida na página do item para quem pode reivindicá-lo."""
    if not user or user["id"] == item["userId"] or not _is_claimable(item):
        return None
    secret = get_secret(item["id"])
    return secret.question if secret else None


def _is_claimable(item: dict | None) -> bool:
    return bool(item and item["type"] == "FOUND" and item["status"] in ("OPEN", "RESERVED"))
