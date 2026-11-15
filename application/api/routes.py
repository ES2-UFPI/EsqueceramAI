from flask import Blueprint, Response, g, jsonify, redirect, request
from sqlalchemy import func, select, text
from application.auth import SESSION_COOKIE, cookie_token, destroy_session
from application.delivery.policy import enforce_checkout_policy
from application.domain import (CATEGORIES, MATCH_STATUSES, RECORD_TYPES, ROLES, SORT_OPTIONS, STATUSES, clamp_page,
                                parse_geo_params)
from application.errors import ApiError, forbidden, not_found, unauthorized
from application.http import api_user, controller, cors_headers, read_json
from application.models import User, db
from application.repositories.engagement import (count_unread_notifications, list_matches, list_notifications,
                                         mark_all_notifications_read, mark_notification_read)
from application.repositories.items import item_row_json
from application.repositories.points import create_point, list_points, point_json, update_point
from application.repositories.users import list_users, set_user_active, set_user_role
from application.services import auth_service, claim_service, item_service
from application.services.matching_service import decide_match
from application.services.seed_service import DEMO_PASSWORD_HINT, ensure_seeded, find_demo_persona
from application.services.storage_service import resolve_item_image
from application.validation import Form

bp = Blueprint("api", __name__, url_prefix="/api")

def _one_of(value, allowed):
    return value if value in allowed else None

@bp.route("/<path:_>", methods=["OPTIONS"])
def preflight(_):
    return Response(status=204)

# ------------------------------------------------------------------ auth
@bp.post("/auth/<action>")
@controller
def auth_post(action):
    if action == "register":
        return jsonify(user=auth_service.register_user(read_json())), 201
    if action == "login":
        return jsonify(user=auth_service.login_user(read_json()))
    if action == "demo":
        payload = request.get_json(silent=True) or {}
        user = auth_service.login_demo_user(payload.get("persona"))
        return jsonify(user=user, persona=find_demo_persona(payload.get("persona"))["key"], hint=DEMO_PASSWORD_HINT)
    if action == "recover":
        return jsonify(auth_service.recover_password(read_json()))
    if action == "logout":
        destroy_session(cookie_token())
        resp = jsonify(ok=True)
        resp.delete_cookie(SESSION_COOKIE, path="/")
        return resp
    raise ApiError("Rota de autenticação não encontrada.", 404)

@bp.get("/auth/<action>")
@controller
def auth_get(action):
    if action != "me":
        raise ApiError("Rota de autenticação não encontrada.", 404)
    return jsonify(user=api_user(required=False))

@bp.patch("/auth/<action>")
@controller
def auth_patch(action):
    user = api_user()
    if action == "me":
        return jsonify(user=auth_service.update_profile(user["id"], read_json()))
    if action == "password":
        return jsonify(auth_service.change_password(user["id"], read_json()))
    raise ApiError("Rota de autenticação não encontrada.", 404)

# ------------------------------------------------------------------ itens
@bp.get("/items")
@controller
def items_list():
    a = request.args
    geo, geo_error = parse_geo_params(a.get("lat"), a.get("lng"), a.get("raio"))
    if geo_error:
        raise ApiError(geo_error, 422)
    result = item_service.search_items({
        "q": (a.get("q") or "")[:120] or None, "type": _one_of(a.get("tipo"), RECORD_TYPES),
        "category": _one_of(a.get("categoria"), CATEGORIES), "status": _one_of(a.get("status"), STATUSES),
        "location": (a.get("local") or "")[:120] or None, "color": (a.get("cor") or "")[:40] or None,
        "brand": (a.get("marca") or "")[:60] or None, "model": (a.get("modelo") or "")[:60] or None,
        "from": a.get("de") or None, "to": a.get("ate") or None,
        "sort": _one_of(a.get("ordem"), [v for v, _ in SORT_OPTIONS]), "geo": geo,
        "page": clamp_page(a.get("pagina")), "pageSize": 9})
    return jsonify(result)

@bp.post("/items")
@controller
def items_create():
    user = api_user()
    if "multipart/form-data" not in (request.content_type or ""):
        raise ApiError("Envie os dados do item como multipart/form-data.", 415)
    result = item_service.create_item_from_form(user, request.form.to_dict(), request.files.get("image"))
    return jsonify(item=item_row_json(result["item"]), matches=result["matches"]), 201

@bp.get("/items/<int:item_id>")
@controller
def items_get(item_id):
    detail = item_service.get_item_detail(item_id, api_user(required=False))
    if not detail:
        raise not_found("Registro")
    return jsonify(detail)

@bp.patch("/items/<int:item_id>")
@controller
def items_patch(item_id):
    user = api_user()
    if "multipart/form-data" in (request.content_type or ""):
        item = item_service.update_item_from_form(user, item_id, request.form.to_dict(), request.files.get("image"))
        return jsonify(item=item_row_json(item))
    payload = read_json()
    if payload.get("status") not in STATUSES:
        raise ApiError("Informe um status válido.", 422)
    if payload["status"] == "DELIVERED":
        raise ApiError("O status \"Entregue\" só é definido ao concluir uma entrega com termo de retirada "
                       "(CPF, documento com foto e código de confirmação).", 409)
    enforce_checkout_policy(payload["status"], item_id)  # opcional (DELIVERY_REQUIRE_CHECKOUT)
    return jsonify(item_service.change_item_status(user, item_id, payload["status"], payload.get("note")))

@bp.delete("/items/<int:item_id>")
@controller
def items_delete(item_id):
    return jsonify(item_service.remove_item(api_user(), item_id))

@bp.get("/images/<int:item_id>")
@controller
def images_get(item_id):
    # O bucket `item-images` é privado: nunca serve bytes a anônimos.
    if not api_user(required=False):
        raise unauthorized("Faça login para visualizar imagens dos itens.")
    image = resolve_item_image(item_id)
    if not image:
        return Response("Imagem não encontrada", status=404)
    if image[0] == "redirect":
        return redirect(image[1], 302)
    _, mime, data = image
    return Response(data, mimetype=mime, headers={"Cache-Control": "private, max-age=120", "Content-Length": str(len(data))})

# ---------------------------------------------------------------- posse (US04)
@bp.get("/items/<int:item_id>/challenge")
@controller
def items_challenge(item_id):
    """A pergunta-chave para o reclamante responder — o detalhe oculto nunca sai daqui."""
    result = claim_service.challenge(item_id, api_user())
    if result is None:
        raise ApiError("Este item não usa pergunta de segurança.", 404)
    return jsonify(challenge=result)


@bp.post("/items/<int:item_id>/claim")
@controller
def items_claim(item_id):
    payload = read_json()
    return jsonify(claim_service.answer(item_id, api_user(), payload.get("answer", "")))


# ---------------------------------------------------------------- matches
@bp.get("/matches")
@controller
def matches_list():
    user = api_user()
    status = _one_of(request.args.get("status"), MATCH_STATUSES)
    is_global = request.args.get("escopo") == "global" and user["role"] in ("ADMIN", "OPERATOR_POST")
    return jsonify(matches=list_matches(user_id=None if is_global else user["id"], status=status, limit=50))

@bp.patch("/matches/<int:match_id>")
@controller
def matches_patch(match_id):
    user = api_user()
    payload = read_json()
    if payload.get("action") not in ("confirm", "reject"):
        raise ApiError("Ação inválida. Use 'confirm' ou 'reject'.", 422)
    return jsonify(decide_match(user, match_id, payload["action"], payload.get("note")))

# ---------------------------------------------------------- notificações
@bp.get("/notifications")
@controller
def notifications_get():
    user = api_user()
    return jsonify(notifications=list_notifications(user["id"], 50), unread=count_unread_notifications(user["id"]))

@bp.patch("/notifications")
@controller
def notifications_patch():
    user = api_user()
    payload = read_json()
    if payload.get("all"):
        mark_all_notifications_read(user["id"])
    elif payload.get("id"):
        mark_notification_read(payload["id"], user["id"])
    return jsonify(ok=True, unread=count_unread_notifications(user["id"]))

# ----------------------------------------------------------------- pontos
def _point_form(raw):
    f = Form(raw)
    f.text("name", min=3, min_msg="Informe o nome do ponto.")
    f.text("building", min=2, min_msg="Informe o prédio ou referência.")
    f.text("description", max=400, optional=True)
    f.text("openingHours", max=120, optional=True)
    f.text("contact", max=120, optional=True)
    f.number("latitude", lo=-90, hi=90)
    f.number("longitude", lo=-180, hi=180)
    return f.finish()

@bp.get("/points")
@controller
def points_get():
    return jsonify(points=list_points(request.args.get("todos") != "1"))

@bp.post("/points")
@controller
def points_post():
    user = api_user()
    if user["role"] not in ("ADMIN", "OPERATOR_POST"):
        raise forbidden("Apenas operadores e administradores podem criar pontos de coleta.")
    d = _point_form(read_json())
    point = create_point(name=d["name"], building=d["building"], description=d["description"] or None,
                         openingHours=d["openingHours"] or None, contact=d["contact"] or None,
                         latitude=d["latitude"], longitude=d["longitude"])
    return jsonify(point=point_json(point)), 201

@bp.patch("/points")
@controller
def points_patch():
    user = api_user()
    if user["role"] not in ("ADMIN", "OPERATOR_POST"):
        raise forbidden("Apenas operadores e administradores podem alterar pontos de coleta.")
    payload = read_json()
    if not payload.get("id"):
        return jsonify(error="Informe o identificador do ponto."), 422
    point = update_point(payload["id"], isActive=payload.get("isActive"), openingHours=payload.get("openingHours"),
                         description=payload.get("description"))
    return jsonify(point=point_json(point) if point else None)

# ------------------------------------------------------------------ admin
def _require_admin():
    user = api_user()
    if user["role"] != "ADMIN":
        raise forbidden("Acesso restrito à administração.")
    return user

@bp.get("/admin/users")
@controller
def admin_users_get():
    _require_admin()
    return jsonify(users=list_users(q=request.args.get("q") or None, role=_one_of(request.args.get("papel"), ROLES)))

@bp.patch("/admin/users")
@controller
def admin_users_patch():
    admin = _require_admin()
    p = read_json()
    uid = p.get("userId")
    if not uid:
        return jsonify(error="Informe o usuário."), 422
    if uid == admin["id"] and p.get("role") and p["role"] != "ADMIN":
        return jsonify(error="Você não pode remover o seu próprio acesso de administrador."), 422
    if p.get("role"):
        if p["role"] not in ROLES:
            return jsonify(error="Papel inválido."), 422
        set_user_role(uid, p["role"])
    if isinstance(p.get("isActive"), bool):
        if uid == admin["id"] and not p["isActive"]:
            return jsonify(error="Você não pode desativar a sua própria conta."), 422
        set_user_active(uid, p["isActive"])
    return jsonify(ok=True)

# ----------------------------------------------------------------- health
@bp.get("/health")
def health():
    try:
        db.execute(text("select 1"))
        ensure_seeded()
        total = db.scalar(select(func.count()).select_from(User)) or 0
        return jsonify(status="healthy", service="esqueceram-ai", users=int(total))
    except Exception as exc:  # noqa: BLE001
        print("[health] database check failed", repr(exc))
        return jsonify(status="unhealthy"), 500
