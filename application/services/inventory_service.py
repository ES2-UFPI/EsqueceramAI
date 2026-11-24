from application.domain import (CATEGORY_LABEL, FINAL_STATUSES, INVENTORY_STATUSES, INVENTORY_STATUS_LABEL,
                                INVENTORY_TRANSITIONS, item_code)
from application.errors import ApiError, forbidden, not_found
from application.repositories.engagement import add_item_event
from application.repositories.items import find_item_by_id, update_item

STORAGE_LOCATION_MAX = 80


def is_staff(user: dict | None) -> bool:
    """Retorna True apenas para atendentes de posto e administradores."""
    return bool(user and user.get("role") in ("OPERATOR_POST", "ADMIN"))


def require_staff(user: dict | None) -> None:
    if not is_staff(user):
        raise forbidden("Apenas atendentes do posto ou administradores podem gerenciar o inventário físico.")


def clean_storage_location(value: str | None) -> str | None:
    """Normaliza o código de localização física interna (ex.: Prateleira B2 · Gaveta 1)."""
    text = " ".join(str(value or "").split())
    if not text:
        return None
    if len(text) > STORAGE_LOCATION_MAX:
        raise ApiError(f"A localização física deve ter no máximo {STORAGE_LOCATION_MAX} caracteres.", 422,
                       {"storageLocation": ["Código muito longo."]})
    return text


def effective_inventory_status(item: dict) -> str | None:
    """Determina o estado atual do ciclo de vida no posto de coleta."""
    if item.get("inventoryStatus") in INVENTORY_STATUSES:
        return item["inventoryStatus"]
    if not item.get("pointId"):
        return None
    if item.get("status") in ("DELIVERED", "RETURNED"):
        return "DELIVERED"
    if item.get("status") == "ARCHIVED":
        return "DISPOSED"
    return "AWAITING_DROP_OFF"


def allowed_next_statuses(item: dict) -> tuple[str, ...]:
    """Retorna os próximos estados válidos na máquina de estados do item."""
    current = effective_inventory_status(item)
    if not current:
        return ()
    return INVENTORY_TRANSITIONS.get(current, ())


def set_storage_location(user: dict | None, item_id: int, storage_location: str | None) -> dict:
    """Define ou remove a localização física interna de um item (exclusivo para atendentes)."""
    require_staff(user)
    item = find_item_by_id(item_id)
    if not item:
        raise not_found("Registro")
    if not item.get("pointId"):
        raise ApiError("Associe o item a um ponto de coleta antes de definir a localização física interna.", 422,
                       {"storageLocation": ["Item sem ponto de coleta."]})
    cleaned = clean_storage_location(storage_location)
    update_item(item_id, {"storage_location": cleaned})
    note = (f"Localização física interna definida: {cleaned}." if cleaned
            else "Localização física interna removida.")
    add_item_event(item_id=item_id, actor_id=user["id"], status=item["status"], note=note)
    from application.services.item_service import _sync_confirmed_items
    _sync_confirmed_items(item_id, {"storage_location": cleaned}, user, note)
    return {"ok": True, "itemId": item_id, "storageLocation": cleaned}


def transition_inventory_status(user: dict | None, item_id: int, target_status: str,
                                storage_location: str | None = None, note: str | None = None) -> dict:
    """Executa uma transição válida na máquina de estados física do posto de coleta."""
    require_staff(user)
    if target_status not in INVENTORY_STATUSES:
        raise ApiError("Estado de inventário inválido.", 422, {"inventoryStatus": ["Estado inválido."]})
    item = find_item_by_id(item_id)
    if not item:
        raise not_found("Registro")
    if not item.get("pointId"):
        raise ApiError("Apenas itens vinculados a um ponto de coleta possuem ciclo de inventário.", 422)

    current = effective_inventory_status(item)
    allowed = INVENTORY_TRANSITIONS.get(current, ())
    if target_status not in allowed:
        raise ApiError(
            f"Transição inválida: \"{INVENTORY_STATUS_LABEL[current]}\" não pode ir para "
            f"\"{INVENTORY_STATUS_LABEL[target_status]}\".",
            409,
        )

    updates: dict = {"inventory_status": target_status}
    cleaned_loc = item.get("storageLocation")
    if storage_location is not None:
        cleaned_loc = clean_storage_location(storage_location)
        updates["storage_location"] = cleaned_loc

    new_item_status = item["status"]
    if target_status == "DISPOSED" and item["status"] not in FINAL_STATUSES:
        new_item_status = "ARCHIVED"
        updates["status"] = new_item_status
    elif target_status == "DELIVERED" and item["status"] not in FINAL_STATUSES:
        new_item_status = "DELIVERED"
        updates["status"] = new_item_status

    update_item(item_id, updates)
    loc_suffix = f" Localização: {cleaned_loc}." if cleaned_loc and target_status == "STORED" else ""
    event_note = note or (
        f"Ciclo do posto: {INVENTORY_STATUS_LABEL[current]} ➔ {INVENTORY_STATUS_LABEL[target_status]}.{loc_suffix}"
    )
    add_item_event(item_id=item_id, actor_id=user["id"], status=new_item_status, note=event_note)
    return {
        "ok": True,
        "itemId": item_id,
        "inventoryStatus": target_status,
        "inventoryStatusLabel": INVENTORY_STATUS_LABEL[target_status],
        "status": new_item_status,
        "storageLocation": cleaned_loc,
    }


def build_item_label(item: dict) -> dict:
    """Monta os dados exibidos na etiqueta física/visual do pacote."""
    inv_status = effective_inventory_status(item)
    return {
        "id": item["id"],
        "code": item_code(item["id"]),
        "title": item["title"],
        "category": CATEGORY_LABEL.get(item["category"], item["category"]),
        "pointName": item.get("pointName") or "Sem ponto vinculado",
        "pointBuilding": item.get("pointBuilding") or "",
        "storageLocation": item.get("storageLocation") or "Localização não definida",
        "inventoryStatus": inv_status,
        "inventoryStatusLabel": INVENTORY_STATUS_LABEL.get(inv_status, "—") if inv_status else "—",
        "occurredAt": item.get("occurredAt"),
    }
