from datetime import datetime, timedelta, timezone

from application.auth import can_manage_item
from application.domain import CATEGORIES, FINAL_STATUSES, RECORD_TYPES, STATUSES
from application.errors import ApiError, forbidden, not_found
from application.repositories.engagement import (add_item_event, create_notifications, list_item_events, list_matches,
                                         list_matches_for_item)
from application.repositories.items import (create_item, delete_item, find_item_by_id, list_items,
                                            set_item_status, update_item)
from application.repositories.points import find_point_by_id
from application.repositories.users import add_user_score
from application.services import claim_service, inventory_service, vision_service
from application.services.matching_service import generate_matches_for_item
from application.services.storage_service import store_item_image
from application.validation import Form, parse_iso

def parse_item_form(form) -> dict:
    """Aceita campos planos e `attributes.<chave>`."""
    raw = {k: v for k, v in form.items() if not k.startswith("attributes.")}
    attributes = {}
    for k, v in form.items():
        if k.startswith("attributes."):
            key = k[len("attributes."):]
            if key and isinstance(v, str) and v.strip():
                attributes[key] = v.strip()[:200]
    f = Form(raw)
    f.choice("type", RECORD_TYPES, "Selecione o tipo de registro.")
    f.choice("category", CATEGORIES, "Selecione uma categoria.")
    f.text("title", min=4, max=120, min_msg="Descreva o item em pelo menos 4 caracteres.", max_msg="Título muito longo.")
    f.text("description", min=15, max=2000, min_msg="Detalhe o item com pelo menos 15 caracteres.", max_msg="Descrição muito longa.")
    f.text("color", max=40, optional=True)
    f.text("brand", max=60, optional=True)
    f.text("model", max=60, optional=True)
    f.text("location", min=3, max=160, min_msg="Informe o local da ocorrência.")
    occurred = f.text("occurredAt", min=1, min_msg="Informe a data da ocorrência.")
    if occurred and not parse_iso(occurred):
        f.errors.setdefault("occurredAt", []).append("Data inválida.")
    f.number("pointId", integer=True, positive=True)
    f.number("latitude", lo=-90, hi=90)
    f.number("longitude", lo=-180, hi=180)
    if (f.data.get("latitude") is None) != (f.data.get("longitude") is None):
        f.errors.setdefault("latitude", []).append("Informe latitude e longitude juntas.")
    data = f.finish()
    data["attributes"] = attributes
    return data


def _to_values(data: dict, user_id: int) -> dict:
    occurred = parse_iso(data["occurredAt"])
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    if occurred > datetime.now(timezone.utc) + timedelta(days=1):
        raise ApiError("A data da ocorrência não pode estar no futuro.", 422, {"occurredAt": ["Data no futuro."]})
    return {"user_id": user_id, "type": data["type"], "category": data["category"], "title": data["title"],
            "description": data["description"], "color": data["color"] or None, "brand": data["brand"] or None,
            "model": data["model"] or None, "attributes": data["attributes"], "location": data["location"],
            "occurred_at": occurred, "point_id": data["pointId"], "latitude": data["latitude"],
            "longitude": data["longitude"]}


def _assert_point(point_id):
    if point_id and not find_point_by_id(point_id):
        raise ApiError("Ponto de coleta inválido.", 422, {"pointId": ["Ponto não encontrado."]})


def create_item_from_form(user: dict, form, image=None) -> dict:
    data = parse_item_form(form)
    _assert_point(data["pointId"])
    raw_loc = (form.get("storageLocation") or "").strip() if hasattr(form, "get") else ""
    if raw_loc and not inventory_service.is_staff(user):
        raise forbidden("Apenas atendentes do posto ou administradores podem definir a localização física interna.")
    valid_secret = claim_service.validate_secret(
        user, {"userId": user["id"], "type": data["type"], "isDemo": False}, form
    )
    values = _to_values(data, user["id"])
    if data["pointId"] and data["type"] == "FOUND":
        cleaned_loc = inventory_service.clean_storage_location(raw_loc) if inventory_service.is_staff(user) else None
        if cleaned_loc:
            values["storage_location"] = cleaned_loc
            values["inventory_status"] = "STORED"
        else:
            values["inventory_status"] = "AWAITING_DROP_OFF"
    created = create_item(values)
    claim_service.save_secret(user, created.id, form, valid_secret)
    if image is not None and getattr(image, "filename", ""):
        store_item_image(created.id, image)
        if vision_service.is_vision_enabled() and hasattr(image, "stream"):
            image.stream.seek(0)
            visual = vision_service.analyze_item_image(image.read(), image.mimetype or "")
            if visual:
                update_item(created.id, {"ai_visual": visual})
    add_item_event(item_id=created.id, actor_id=user["id"], status="OPEN",
                   note="Registro de item perdido publicado." if data["type"] == "LOST"
                   else "Registro de item encontrado publicado.")
    return {"item": created, "matches": generate_matches_for_item(created.id)}


def update_item_from_form(user: dict, item_id: int, form, image=None):
    current = find_item_by_id(item_id)
    if not current:
        raise not_found("Registro")
    if not can_manage_item(user, current):
        raise forbidden("Você só pode editar os seus próprios registros.")
    if current["status"] in FINAL_STATUSES:
        raise ApiError("Itens já devolvidos ou entregues não podem ser editados.", 409)
    data = parse_item_form(form)
    _assert_point(data["pointId"])
    raw_loc = (form.get("storageLocation") or "").strip() if hasattr(form, "get") else ""
    if raw_loc and not inventory_service.is_staff(user):
        raise forbidden("Apenas atendentes do posto ou administradores podem definir a localização física interna.")
    values = _to_values(data, current["userId"])
    if inventory_service.is_staff(user) and hasattr(form, "get") and "storageLocation" in form and data["pointId"]:
        values["storage_location"] = inventory_service.clean_storage_location(raw_loc)
    valid_secret = claim_service.validate_secret(user, {**current, "type": values["type"]}, form)
    updated = update_item(item_id, values)
    claim_service.save_secret(user, item_id, form, valid_secret)
    if not updated:
        raise ApiError("Não foi possível atualizar o registro.", 500)
    if image is not None and getattr(image, "filename", ""):
        store_item_image(item_id, image)
    add_item_event(item_id=item_id, actor_id=user["id"], status=current["status"], note="Dados do registro atualizados.")
    generate_matches_for_item(item_id)
    return updated


def remove_item(user: dict, item_id: int):
    current = find_item_by_id(item_id)
    if not current:
        raise not_found("Registro")
    can = can_manage_item(user, current) or (user["role"] == "OPERATOR_POST" and current["pointId"] is not None)
    if not can:
        raise forbidden("Operadores só podem remover registros vinculados a pontos de coleta.")
    delete_item(item_id)
    return {"ok": True}


def change_item_status(user: dict, item_id: int, status: str, note: str | None = None) -> dict:
    if status not in STATUSES:
        raise ApiError("Status inválido.", 422)
    current = find_item_by_id(item_id)
    if not current:
        raise not_found("Registro")
    is_owner = can_manage_item(user, current)
    staff = user["role"] in ("ADMIN", "OPERATOR_POST")
    if not is_owner and not staff:
        raise forbidden("Sem permissão para alterar o status.")
    if not is_owner and user["role"] == "OPERATOR_POST" and current["pointId"] is None and status != "DELIVERED":
        raise forbidden("Operadores gerenciam apenas itens entregues em pontos de coleta.")
    if current["status"] in FINAL_STATUSES and status != current["status"]:
        raise ApiError("Este item já foi devolvido ou entregue e não pode mudar de status.", 409)

    set_item_status(item_id, status)
    if status == "DELIVERED" and current.get("pointId"):
        update_item(item_id, {"inventory_status": "DELIVERED"})
    notes = {"OPEN": note or "Registro reaberto.", "RESERVED": note or "Item reservado para retirada.",
             "RETURNED": note or "Item devolvido ao responsável.", "DELIVERED": note or "Item entregue ao retirante.",
             "ARCHIVED": note or "Registro arquivado.",
             "AVAILABLE_FOR_DISPOSAL": note or "Item marcado como disponível para doação/descarte."}
    add_item_event(item_id=item_id, actor_id=user["id"], status=status, note=notes[status])

    if status in FINAL_STATUSES:
        _handle_recovery(current, user)
    elif status == "ARCHIVED":
        _handle_confirmed_archive(current, user)
        create_notifications([{"userId": current["userId"], "type": "UPDATE", "title": "Registro arquivado",
                               "body": f"O registro \"{current['title']}\" foi arquivado por {user['name']}.",
                               "link": "/painel/itens"}])
    elif status == "OPEN":
        generate_matches_for_item(item_id)
    return {"ok": True, "status": status}


def _handle_confirmed_archive(item: dict, actor: dict):
    related = [m for m in list_matches(status="CONFIRMED", limit=20)
               if m["lost"]["id"] == item["id"] or m["found"]["id"] == item["id"]]
    for m in related:
        other = m["found"] if m["lost"]["id"] == item["id"] else m["lost"]
        if other["status"] in ("RESERVED", "OPEN"):
            set_item_status(other["id"], "ARCHIVED")
            add_item_event(item_id=other["id"], actor_id=actor["id"], status="ARCHIVED",
                           note=f"Registro arquivado automaticamente após o arquivamento do item vinculado \"{item['title']}\".")
            if other["ownerId"] != actor["id"]:
                create_notifications([{"userId": other["ownerId"], "type": "UPDATE", "title": "Registro vinculado arquivado",
                                       "body": f"O registro \"{other['title']}\" foi arquivado porque \"{item['title']}\" foi arquivado.",
                                       "link": f"/itens/{other['id']}"}])


def _handle_recovery(item: dict, actor: dict):
    related = [m for m in list_matches(status="CONFIRMED", limit=20)
               if m["lost"]["id"] == item["id"] or m["found"]["id"] == item["id"]]
    owners = set()
    for m in related:
        other = m["found"] if m["lost"]["id"] == item["id"] else m["lost"]
        owners.add(other["ownerId"])
        if other["status"] in ("RESERVED", "OPEN"):
            set_item_status(other["id"], "RETURNED")
            add_item_event(item_id=other["id"], actor_id=actor["id"], status="RETURNED",
                           note="Devolução concluída em conjunto com o registro correspondente.")
    owners.add(item["userId"])
    recipients = [i for i in owners if i != actor["id"]]
    add_user_score(item["userId"], 40 if item["type"] == "FOUND" else 15)
    if recipients:
        create_notifications([{"userId": uid, "type": "RECOVERY", "title": "Item recuperado com sucesso",
                               "body": f"\"{item['title']}\" foi devolvido. Obrigado por ajudar a comunidade acadêmica!",
                               "link": f"/itens/{item['id']}"} for uid in recipients])


def get_item_detail(item_id: int, viewer: dict | None):
    item = find_item_by_id(item_id)
    if not item:
        return None
    staff = bool(viewer and viewer["role"] in ("ADMIN", "OPERATOR_POST"))
    if item["status"] == "ARCHIVED" and not (staff or (viewer and viewer["id"] == item["userId"])):
        return None
    if not staff:
        item["storageLocation"] = None
    item["inventoryStatus"] = inventory_service.effective_inventory_status(item)
    return {"item": item, "matches": list_matches_for_item(item_id), "timeline": list_item_events(item_id),
            "canManage": bool(viewer and can_manage_item(viewer, item)),
            "claim": claim_service.status_for(viewer, item),
            "hasSecret": claim_service.get_secret(item_id) is not None,
            "inventory": {
                "status": item["inventoryStatus"],
                "allowedNext": inventory_service.allowed_next_statuses(item) if staff else (),
            }}


def search_items(filters: dict):
    return list_items(filters)


def list_my_items(user: dict, filters: dict):
    return list_items({**filters, "ownerId": user["id"], "includeArchived": True})
