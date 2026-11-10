"""Páginas do checkout de entrega (restritas ao perfil de atendente do posto)."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.delivery import service
from app.errors import ApiError
from app.web.views import login_required, safe_next, shell_ctx

bp = Blueprint("delivery_web", __name__, url_prefix="/painel/entregas", template_folder="templates",
               static_folder="static", static_url_path="/delivery-static")

STATUS_UI = {"PENDING": ("Aguardando confirmação", "warn"), "COMPLETED": ("Concluída", "found"),
             "CANCELLED": ("Cancelada", ""), "EXPIRED": ("Expirada", "")}


def _ctx(user, **kw):
    return {**shell_ctx(user), "active": "/painel/entregas", "STATUS": STATUS_UI, **kw}


def _fail(exc: ApiError, to):
    flash(exc.message, "error")
    return redirect(to)


def _flash_email(email: dict, masked: str):
    if email["sent"]:
        hint = " Modo desenvolvimento: o e-mail foi impresso no console do servidor." if email["backend"] == "console" else ""
        flash(f"Código de confirmação enviado para {masked}.{hint}", "ok")
    else:
        flash(email["error"], "error")


@bp.get("/")
@login_required("OPERATOR_POST", "ADMIN")
def lista(user):
    rows = [service.delivery_dict(d) for d in service.list_for_user(user)]
    return render_template("delivery/list.html", deliveries=rows, **_ctx(user))


@bp.route("/nova", methods=["GET", "POST"])
@login_required("OPERATOR_POST")
def nova(user):
    registration = service.get_registration(user)
    ctx = dict(registration=registration, items=service.deliverable_items(), error=None, errors={},
               values=request.form if request.method == "POST" else {"itemId": request.args.get("item", "")})
    if request.method == "POST":
        try:
            result = service.start_delivery(user, request.form.to_dict(), request.files.get("document"))
        except ApiError as exc:
            ctx.update(error=exc.message, errors=exc.details or {})
            return render_template("delivery/new.html", **_ctx(user, **ctx))
        d = service.delivery_dict(result["delivery"])
        _flash_email(result["email"], d["emailMasked"])
        return redirect(url_for(".confirmar", delivery_id=d["id"]))
    return render_template("delivery/new.html", **_ctx(user, **ctx))


@bp.post("/matricula")
@login_required("OPERATOR_POST")
def matricula(user):
    try:
        service.set_registration(user, request.form.get("registrationNumber", ""))
        flash("Matrícula cadastrada.", "ok")
    except ApiError as exc:
        flash((exc.details or {}).get("registrationNumber", [exc.message])[0], "error")
    return redirect(safe_next(request.form.get("next"), url_for(".nova")))


@bp.get("/<int:delivery_id>")
@login_required("OPERATOR_POST", "ADMIN")
def detalhe(user, delivery_id):
    try:
        d = service.delivery_dict(service.get_for_user(user, delivery_id), detail=True)
    except ApiError as exc:
        return _fail(exc, url_for(".lista"))
    return render_template("delivery/detail.html", d=d, verify=None, **_ctx(user))


@bp.post("/<int:delivery_id>/verificar")
@login_required("OPERATOR_POST", "ADMIN")
def verificar(user, delivery_id):
    try:
        d = service.delivery_dict(service.get_for_user(user, delivery_id), detail=True)
        result = service.verify_delivery(user, delivery_id, request.form.get("cpf", ""))
    except ApiError as exc:
        return _fail(exc, url_for(".lista"))
    return render_template("delivery/detail.html", d=d, verify=result, **_ctx(user))


@bp.get("/<int:delivery_id>/confirmar")
@login_required("OPERATOR_POST")
def confirmar(user, delivery_id):
    try:
        d = service.delivery_dict(service.get_for_user(user, delivery_id))
    except ApiError as exc:
        return _fail(exc, url_for(".lista"))
    if d["status"] != "PENDING":
        return redirect(url_for(".detalhe", delivery_id=delivery_id))
    return render_template("delivery/confirm.html", d=d, error=None, **_ctx(user))


@bp.post("/<int:delivery_id>/confirmar")
@login_required("OPERATOR_POST")
def confirmar_post(user, delivery_id):
    try:
        service.confirm_delivery(user, delivery_id, request.form.get("code", ""))
    except ApiError as exc:
        if exc.status in (422, 410):    # código incorreto/expirado: fica na tela para tentar de novo
            d = service.delivery_dict(service.get_for_user(user, delivery_id))
            return render_template("delivery/confirm.html", d=d, error=exc.message, **_ctx(user))
        return _fail(exc, url_for(".detalhe", delivery_id=delivery_id))
    flash("Entrega concluída! O termo de entrega foi emitido.", "ok")
    return redirect(url_for(".detalhe", delivery_id=delivery_id))


@bp.post("/<int:delivery_id>/reenviar")
@login_required("OPERATOR_POST")
def reenviar(user, delivery_id):
    try:
        result = service.resend_code(user, delivery_id)
    except ApiError as exc:
        return _fail(exc, url_for(".confirmar", delivery_id=delivery_id))
    _flash_email(result["email"], service.delivery_dict(result["delivery"])["emailMasked"])
    return redirect(url_for(".confirmar", delivery_id=delivery_id))


@bp.post("/<int:delivery_id>/cancelar")
@login_required("OPERATOR_POST")
def cancelar(user, delivery_id):
    try:
        service.cancel_delivery(user, delivery_id)
        flash("Entrega cancelada.", "ok")
    except ApiError as exc:
        return _fail(exc, url_for(".detalhe", delivery_id=delivery_id))
    return redirect(url_for(".lista"))
