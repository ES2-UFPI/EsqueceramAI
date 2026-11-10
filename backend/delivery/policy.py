"""Política opcional: itens em ponto de coleta só saem pelo formulário de entrega.

Desligada por padrão (o botão "Devolvido" existente continua funcionando). Ative com
DELIVERY_REQUIRE_CHECKOUT=true para que a devolução de itens encontrados em pontos de coleta exija CPF,
documento com foto e código — o único caminho que gera o termo com respaldo legal.
A entrega em si usa o serviço diretamente, portanto não é afetada pela política.
"""
import os

from app.errors import ApiError
from app.repositories.items import find_item_by_id


def checkout_required() -> bool:
    return os.getenv("DELIVERY_REQUIRE_CHECKOUT", "").strip().lower() in ("1", "true", "yes", "sim")


def enforce_checkout_policy(new_status: str, item_id: int) -> None:
    if new_status != "RETURNED" or not checkout_required():
        return
    item = find_item_by_id(item_id)
    if item and item["type"] == "FOUND" and item["pointId"] is not None:
        raise ApiError("Itens em pontos de coleta só podem ser devolvidos pelo formulário de entrega "
                       "(CPF, documento com foto e código de confirmação).", 409)
