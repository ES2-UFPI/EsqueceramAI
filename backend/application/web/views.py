from functools import wraps
from urllib.parse import urlencode
from flask import (Blueprint, flash, g, redirect, render_template, request, make_response, url_for)
from application import domain as D
from application.auth import SESSION_COOKIE, can_manage_item, cookie_token, destroy_session, get_current_user
from application.errors import ApiError
from application.repositories.engagement import (count_pending_matches, count_unread_notifications, list_matches,
                                         list_notifications, list_recent_events, mark_all_notifications_read)
from application.repositories.items import items_at_points
from application.repositories.points import create_point, list_points, list_recent_point_activity
from application.services import auth_service, item_service, matching_service
from application.services.seed_service import DEMO_PASSWORD_HINT, DEMO_PERSONAS, ensure_seeded
from application.services.stats_service import get_admin_overview, get_dashboard, get_public_home
from application.validation import Form

bp = Blueprint("web", __name__)

ITEM_FILTER_KEYS = ["q", "tipo", "categoria", "status", "local", "cor", "marca", "modelo", "de", "ate", "ordem",
                    "lat", "lng", "raio"]

# ------------------------------------------------------------------ helpers
@bp.app_template_filter("date")
def _date(v): return D.format_date(v)
@bp.app_template_filter("datetime")
def _datetime(v): return D.format_datetime(v)
@bp.app_template_filter("ago")
def _ago(v): return D.time_ago(v)
@bp.app_template_filter("code")
def _code(v): return D.item_code(v)
@bp.app_template_filter("initials")
def _initials(v): return D.initials(v)
@bp.app_template_filter("firstname")
def _firstname(v): return D.first_name(v)
@bp.app_template_filter("humanize_key")
def _humanize(k):
    import re
    s = re.sub(r"([A-Z])", r" \1", k)
    return s[:1].upper() + s[1:]

@bp.app_context_processor
def inject():
    return {"D": D, "user": get_current_user(), "DEMO_PASSWORD": DEMO_PASSWORD_HINT,
            "qs": lambda base=None, **kw: urlencode({k: v for k, v in {**(base or {}), **kw}.items() if v not in (None, "")})}

def safe_next(value, default="/painel"):
    return value if value and value.startswith("/") and not value.startswith("//") else default

def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            user = get_current_user()
            if not user:
                nxt = request.full_path.rstrip("?")
                return redirect(url_for("web.entrar", next=nxt))
            if roles and user["role"] not in roles:
                return redirect("/painel?erro=permissao")
            return fn(user, *a, **kw)
        return wrapper
    return deco

def shell_ctx(user):
    return {"pending_count": count_pending_matches(user["id"]), "unread_count": count_unread_notifications(user["id"])}

def render_not_found():
    return render_template("not_found.html"), 404

def _form_error(exc: ApiError):
    return {"error": exc.message, "errors": exc.details or {}}

# ------------------------------------------------------------- páginas públicas
@bp.get("/")
def home():
    ensure_seeded()
    top = list_matches(status="PENDING", limit=1)
    return render_template("home.html", data=get_public_home(), points=list_points(True), top=top[0] if top else None)

@bp.route("/entrar", methods=["GET", "POST"])
def entrar():
    nxt = safe_next(request.values.get("next"))
    if get_current_user() and request.method == "GET":
        return redirect(nxt)
    ctx = {"next": nxt, "personas": DEMO_PERSONAS, "values": {}, "error": None, "errors": {}}
    if request.method == "POST":
        try:
            if request.form.get("persona"):
                auth_service.login_demo_user(request.form["persona"])
            else:
                auth_service.login_user(request.form)
            return redirect(nxt)
        except ApiError as exc:
            ctx.update(_form_error(exc), values=request.form)
    return render_template("entrar.html", **ctx)

@bp.route("/cadastrar", methods=["GET", "POST"])
def cadastrar():
    ctx = {"values": {}, "error": None, "errors": {}}
    if request.method == "POST":
        try:
            auth_service.register_user(request.form)
            return redirect("/painel")
        except ApiError as exc:
            ctx.update(_form_error(exc), values=request.form)
    return render_template("cadastrar.html", **ctx)

@bp.route("/recuperar-senha", methods=["GET", "POST"])
def recuperar():
    ctx = {"values": {}, "error": None, "errors": {}}
    if request.method == "POST":
        try:
            auth_service.recover_password(request.form)
            flash("Senha redefinida. Entre com a nova senha.", "ok")
            return redirect("/entrar")
        except ApiError as exc:
            ctx.update(_form_error(exc), values=request.form)
    return render_template("recuperar.html", **ctx)

@bp.post("/sair")
def sair():
    destroy_session(cookie_token())
    resp = make_response(redirect("/"))
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp

def _item_filters(args, page_key="pagina"):
    return {"q": args.get("q") or None, "type": args.get("tipo") or None, "category": args.get("categoria") or None,
            "status": args.get("status") or None, "location": args.get("local") or None, "color": args.get("cor") or None,
            "brand": args.get("marca") or None, "model": args.get("modelo") or None, "from": args.get("de") or None,
            "to": args.get("ate") or None, "sort": args.get("ordem") or None, "page": D.clamp_page(args.get(page_key)),
            "pageSize": D.PAGE_SIZE}

def _clean(f):
    allowed = {"type": D.RECORD_TYPES, "category": D.CATEGORIES, "status": D.STATUSES, "sort": [v for v, _ in D.SORT_OPTIONS]}
    return {k: (v if k not in allowed or v in allowed[k] else None) for k, v in f.items()}

@bp.get("/itens")
def itens():
    ensure_seeded()
    filters = request.args.to_dict()
    geo, geo_error = D.parse_geo_params(filters.get("lat"), filters.get("lng"), filters.get("raio"))
    query = _clean(_item_filters(request.args))
    query["geo"] = geo  # filtro inválido não derruba a página: avisamos e listamos sem ele
    result = item_service.search_items(query)
    base = {k: filters.get(k) for k in ITEM_FILTER_KEYS}
    return render_template("itens.html", result=result, f=filters, base=base, points=list_points(True),
                           geo=geo, geo_error=geo_error)

@bp.get("/itens/<int:item_id>")
def item_detalhe(item_id):
    viewer = get_current_user()
    detail = item_service.get_item_detail(item_id, viewer)
    if not detail:
        return render_not_found()
    pending = [m for m in detail["matches"] if m["status"] == "PENDING"]
    confirmed = any(m["status"] == "CONFIRMED" for m in detail["matches"])
    return render_template("item_detalhe.html", d=detail, item=detail["item"], pending=pending, confirmed=confirmed,
                           is_staff=bool(viewer and viewer["role"] in ("ADMIN", "OPERATOR_POST")),
                           is_owner=bool(viewer and viewer["id"] == detail["item"]["userId"]))

# ------------------------------------------------------------------- painel
@bp.get("/correspondencias/<int:match_id>")
def correspondencia(match_id):
    """Página do link enviado por e-mail: o usuário confirma o match ou descarta o falso positivo."""
    viewer = get_current_user()
    match = matching_service.get_match_for_decision(match_id)
    if not match:
        return render_not_found()
    is_owner = bool(viewer and viewer["id"] in (match["lost"]["ownerId"], match["found"]["ownerId"]))
    is_staff = bool(viewer and viewer["role"] in ("ADMIN", "OPERATOR_POST"))
    return render_template("match_decisao.html", m=match, can=is_owner or is_staff,
                           needs_login=viewer is None and match["status"] == "PENDING")


@bp.get("/painel")
@login_required()
def painel(user):
    if request.args.get("erro") == "permissao":
        flash("Você não tem permissão para acessar essa área.", "error")
    return render_template("painel.html", d=get_dashboard(user), **shell_ctx(user), active="/painel")

@bp.get("/painel/itens")
@login_required()
def painel_itens(user):
    filters = _clean(_item_filters(request.args))
    result = item_service.list_my_items(user, filters)
    return render_template("painel_itens.html", result=result, f=request.args.to_dict(), **shell_ctx(user), active="/painel/itens")

def _item_form_context(user, values, error=None, errors=None, item=None):
    return {"values": values, "error": error, "errors": errors or {}, "item": item, "points": list_points(True),
            **shell_ctx(user), "active": "/painel/itens"}

@bp.route("/painel/itens/novo", methods=["GET", "POST"])
@login_required()
def item_novo(user):
    values = {"type": request.args.get("tipo", "LOST"), "category": "ELECTRONIC"}
    if request.method == "POST":
        try:
            result = item_service.create_item_from_form(user, request.form.to_dict(), request.files.get("image"))
            n = result["matches"]
            flash("Registro publicado!" + (f" Encontramos {n} possível(is) correspondência(s)." if n else ""), "ok")
            return redirect(f"/itens/{result['item'].id}")
        except ApiError as exc:
            return render_template("item_form.html", mode="new", **_item_form_context(user, request.form, exc.message, exc.details))
    return render_template("item_form.html", mode="new", **_item_form_context(user, values))

@bp.route("/painel/itens/<int:item_id>/editar", methods=["GET", "POST"])
@login_required()
def item_editar(user, item_id):
    detail = item_service.get_item_detail(item_id, user)
    if not detail:
        return render_not_found()
    item = detail["item"]
    if not can_manage_item(user, item):
        flash("Você só pode editar os seus próprios registros.", "error")
        return redirect(f"/itens/{item_id}")
    if request.method == "POST":
        try:
            item_service.update_item_from_form(user, item_id, request.form.to_dict(), request.files.get("image"))
            flash("Registro atualizado.", "ok")
            return redirect(f"/itens/{item_id}")
        except ApiError as exc:
            return render_template("item_form.html", mode="edit", **_item_form_context(user, request.form, exc.message, exc.details, item))
    values = {k: item[k] if item[k] is not None else "" for k in ("type", "category", "title", "description", "color",
                                                                    "brand", "model", "location", "pointId", "latitude", "longitude")}
    values["occurredAt"] = D.to_input_date(item["occurredAt"])
    for k, v in item["attributes"].items():
        values[f"attributes.{k}"] = v
    return render_template("item_form.html", mode="edit", **_item_form_context(user, values, item=item))

@bp.get("/painel/matches")
@login_required()
def painel_matches(user):
    status = request.args.get("status") if request.args.get("status") in D.MATCH_STATUSES else "PENDING"
    staff = user["role"] in ("ADMIN", "OPERATOR_POST")
    scope_global = staff and request.args.get("escopo") == "global"
    matches = list_matches(user_id=None if scope_global else user["id"], status=status, limit=50)
    return render_template("painel_matches.html", matches=matches, status=status, scope_global=scope_global, staff=staff,
                           **shell_ctx(user), active="/painel/matches")

@bp.route("/painel/notificacoes", methods=["GET", "POST"])
@login_required()
def painel_notificacoes(user):
    if request.method == "POST":
        mark_all_notifications_read(user["id"])
        return redirect("/painel/notificacoes")
    return render_template("painel_notificacoes.html", notifications=list_notifications(user["id"], 50),
                           **shell_ctx(user), active="/painel/notificacoes")

@bp.route("/painel/perfil", methods=["GET", "POST"])
@login_required()
def painel_perfil(user):
    ctx = {"error": None, "errors": {}, "form": None}
    if request.method == "POST":
        ctx["form"] = request.form.get("_form")
        try:
            if ctx["form"] == "password":
                auth_service.change_password(user["id"], request.form)
                flash("Senha alterada com sucesso.", "ok")
            else:
                auth_service.update_profile(user["id"], request.form)
                flash("Perfil atualizado.", "ok")
            return redirect("/painel/perfil")
        except ApiError as exc:
            ctx.update(_form_error(exc))
    me = auth_service.get_profile(user["id"])
    return render_template("painel_perfil.html", me=me, level=D.score_level(me["score"]), **ctx,
                           **shell_ctx(me), active="/painel/perfil")

@bp.route("/painel/pontos", methods=["GET", "POST"])
@login_required()
def painel_pontos(user):
    staff = user["role"] in ("ADMIN", "OPERATOR_POST")
    error, errors = None, {}
    if request.method == "POST":
        if not staff:
            return redirect("/painel?erro=permissao")
        f = Form(request.form)
        f.text("name", min=3, min_msg="Informe o nome do ponto.")
        f.text("building", min=2, min_msg="Informe o prédio ou referência.")
        f.text("description", max=400, optional=True)
        f.text("openingHours", max=120, optional=True)
        f.text("contact", max=120, optional=True)
        try:
            d = f.finish()
            create_point(name=d["name"], building=d["building"], description=d["description"] or None,
                         openingHours=d["openingHours"] or None, contact=d["contact"] or None)
            flash("Ponto de coleta criado.", "ok")
            return redirect("/painel/pontos")
        except ApiError as exc:
            error, errors = exc.message, exc.details
    return render_template("painel_pontos.html", points=list_points(not staff), staff=staff, error=error, errors=errors,
                           values=request.form, **shell_ctx(user), active="/painel/pontos")

@bp.get("/painel/operador")
@login_required("OPERATOR_POST", "ADMIN")
def painel_operador(user):
    items = items_at_points()
    return render_template("painel_operador.html", points=list_points(), items=items, activity=list_recent_point_activity(6),
                           **shell_ctx(user), active="/painel/operador")

@bp.get("/painel/admin")
@login_required("ADMIN")
def painel_admin(user):
    return render_template("painel_admin.html", o=get_admin_overview(request.args.get("q") or None), q=request.args.get("q", ""),
                           me=user, **shell_ctx(user), active="/painel/admin")