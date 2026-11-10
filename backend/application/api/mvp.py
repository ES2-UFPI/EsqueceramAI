"""Adaptador do contrato inicial em português documentado na wiki.

As rotas principais usam o contrato completo em inglês (``/api/items``). Este
blueprint conserva ``/api/itens`` e ``/api/postos`` para o frontend estático e
traduz os nomes para o mesmo modelo persistente, sem uma segunda aplicação.
"""
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import or_, select

from application.models import CollectionPoint, Item, User, db

bp = Blueprint("mvp", __name__, url_prefix="/api")

_TYPES = {"PERDIDO": "LOST", "ENCONTRADO": "FOUND"}
_CATEGORIES = {"ELETRONICO": "ELECTRONIC", "DOCUMENTO": "DOCUMENT", "ACESSORIO": "ACCESSORY"}
_STATUSES = {"ABERTO": "OPEN", "RESERVADO": "RESERVED", "DEVOLVIDO": "RETURNED", "ARQUIVADO": "ARCHIVED"}


def _error(message, status=400):
    return jsonify(erro=message), status


def _visitor():
    user = db.scalar(select(User).where(User.email == "visitante@esqueceram.ai"))
    if not user:
        user = User(name="Visitante", email="visitante@esqueceram.ai", password_hash="!")
        db.add(user)
        db.flush()
    return user


def _item_json(item):
    inverse_type = {value: key for key, value in _TYPES.items()}
    inverse_category = {value: key for key, value in _CATEGORIES.items()}
    inverse_status = {value: key for key, value in _STATUSES.items()}
    point = db.get(CollectionPoint, item.point_id) if item.point_id else None
    return {"id": item.id, "tipo_registro": inverse_type[item.type], "categoria": inverse_category[item.category],
            "descricao": item.description, "cor": item.color, "marca": item.brand, "modelo": item.model,
            "atributos": item.attributes or {}, "localizacao": item.location,
            "data_ocorrencia": item.occurred_at.date().isoformat(), "status": inverse_status[item.status],
            "posto_id": item.point_id, "posto_nome": point.name if point else None,
            "latitude": item.latitude, "longitude": item.longitude, "imagem_url": item.image_url}


@bp.get("/itens")
@bp.get("/busca")
def list_items():
    stmt = select(Item)
    filters = []
    if value := request.args.get("tipo_registro", "").upper():
        if value not in _TYPES:
            return _error("tipo_registro inválido")
        filters.append(Item.type == _TYPES[value])
    if value := request.args.get("categoria", "").upper():
        if value not in _CATEGORIES:
            return _error("categoria inválida")
        filters.append(Item.category == _CATEGORIES[value])
    if value := request.args.get("status", "").upper():
        if value not in _STATUSES:
            return _error("status inválido")
        filters.append(Item.status == _STATUSES[value])
    if term := request.args.get("q", "").strip():
        pattern = f"%{term}%"
        filters.append(or_(Item.title.ilike(pattern), Item.description.ilike(pattern), Item.location.ilike(pattern)))
    return jsonify([_item_json(item) for item in db.scalars(stmt.where(*filters).order_by(Item.created_at.desc())).all()])


@bp.post("/itens")
def create_item():
    data = request.form.to_dict() if request.form else (request.get_json(silent=True) or {})
    record_type = str(data.get("tipo_registro", "")).upper()
    category = str(data.get("categoria", "")).upper()
    description = str(data.get("descricao", "")).strip()
    if record_type not in _TYPES or category not in _CATEGORIES or not description:
        return _error("tipo_registro, categoria e descricao são obrigatórios e válidos")
    if category == "DOCUMENTO" and not (data.get("atributos") or data.get("tipo_documento")):
        return _error("itens da categoria DOCUMENTO exigem atributos.tipo_documento")
    point_id = data.get("posto_id") or None
    try:
        point_id = int(point_id) if point_id else None
        latitude = float(data["latitude"]) if data.get("latitude") else None
        longitude = float(data["longitude"]) if data.get("longitude") else None
    except (TypeError, ValueError):
        return _error("posto_id, latitude ou longitude inválido")
    if point_id and record_type != "ENCONTRADO":
        return _error("apenas itens ENCONTRADOS podem ser entregues em um posto de coleta")
    if point_id and not db.get(CollectionPoint, point_id):
        return _error("posto_id inexistente", 422)
    occurred = data.get("data_ocorrencia")
    try:
        occurred_at = datetime.fromisoformat(occurred).replace(tzinfo=timezone.utc) if occurred else datetime.now(timezone.utc)
    except ValueError:
        return _error("data_ocorrencia inválida")
    item = Item(user_id=_visitor().id, type=_TYPES[record_type], category=_CATEGORIES[category], title=description[:120],
                description=description, location=str(data.get("localizacao") or "Não informado"), color=data.get("cor") or None,
                brand=data.get("marca") or None, model=data.get("modelo") or None, occurred_at=occurred_at,
                point_id=point_id, latitude=latitude, longitude=longitude)
    db.add(item)
    db.commit()
    return jsonify(_item_json(item)), 201


@bp.get("/postos")
def list_points():
    points = db.scalars(select(CollectionPoint).where(CollectionPoint.is_active.is_(True)).order_by(CollectionPoint.name)).all()
    return jsonify([{"id": p.id, "nome": p.name, "endereco": p.building, "latitude": p.latitude,
                     "longitude": p.longitude, "horario_funcionamento": p.opening_hours} for p in points])


@bp.post("/postos")
def create_point():
    data = request.get_json(silent=True) or {}
    name, address = str(data.get("nome", "")).strip(), str(data.get("endereco", "")).strip()
    if not name or not address:
        return _error("nome e endereco são obrigatórios")
    try:
        latitude, longitude = float(data["latitude"]), float(data["longitude"])
    except (KeyError, TypeError, ValueError):
        return _error("latitude e longitude são obrigatórias e numéricas")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return _error("coordenadas fora do intervalo permitido")
    point = CollectionPoint(name=name, building=address, latitude=latitude, longitude=longitude,
                            opening_hours=data.get("horario_funcionamento") or None)
    db.add(point)
    db.commit()
    return jsonify(id=point.id, nome=point.name, endereco=point.building, latitude=point.latitude,
                   longitude=point.longitude, horario_funcionamento=point.opening_hours), 201
