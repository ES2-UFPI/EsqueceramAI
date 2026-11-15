"""Endpoints REST da entrega (mesmos padrões de erro/CORS/autenticação da API existente)."""
from flask import Blueprint, Response, jsonify, request

from application.delivery import service
from application.http import api_user, controller, read_json

bp = Blueprint("delivery_api", __name__, url_prefix="/api")


@bp.get("/attendant/registration")
@controller
def registration_get():
    user = api_user()
    service._require_attendant(user)
    return jsonify(registrationNumber=service.get_registration(user))


@bp.put("/attendant/registration")
@controller
def registration_put():
    user = api_user()
    return jsonify(registrationNumber=service.set_registration(user, read_json().get("registrationNumber", "")))


@bp.get("/deliveries")
@controller
def deliveries_list():
    user = api_user()
    return jsonify(deliveries=[service.delivery_dict(d) for d in service.list_for_user(user)])


@bp.post("/deliveries")
@controller
def deliveries_create():
    user = api_user()
    result = service.start_delivery(user, request.form.to_dict(), request.files.get("document"))
    return jsonify(delivery=service.delivery_dict(result["delivery"]), email=result["email"]), 201


@bp.get("/deliveries/<int:delivery_id>")
@controller
def deliveries_get(delivery_id):
    return jsonify(delivery=service.delivery_dict(service.get_for_user(api_user(), delivery_id), detail=True))


@bp.post("/deliveries/<int:delivery_id>/confirm")
@controller
def deliveries_confirm(delivery_id):
    d = service.confirm_delivery(api_user(), delivery_id, read_json().get("code", ""))
    return jsonify(delivery=service.delivery_dict(d, detail=True))


@bp.post("/deliveries/<int:delivery_id>/resend")
@controller
def deliveries_resend(delivery_id):
    result = service.resend_code(api_user(), delivery_id)
    return jsonify(delivery=service.delivery_dict(result["delivery"]), email=result["email"])


@bp.post("/deliveries/<int:delivery_id>/cancel")
@controller
def deliveries_cancel(delivery_id):
    return jsonify(delivery=service.delivery_dict(service.cancel_delivery(api_user(), delivery_id)))


@bp.post("/deliveries/<int:delivery_id>/verify")
@controller
def deliveries_verify(delivery_id):
    payload = request.get_json(silent=True) or {}
    return jsonify(service.verify_delivery(api_user(), delivery_id, payload.get("cpf")))


@bp.get("/deliveries/<int:delivery_id>/receipt")
@controller
def deliveries_receipt(delivery_id):
    d, receipt = service.get_receipt_pdf(api_user(), delivery_id)
    return Response(receipt.pdf, mimetype="application/pdf", headers={
        "Content-Disposition": f'inline; filename="termo-entrega-{service.delivery_dict(d)["receiptNumber"]}.pdf"',
        "Cache-Control": "private, no-store"})


@bp.get("/deliveries/<int:delivery_id>/document")
@controller
def deliveries_document(delivery_id):
    _, doc = service.get_document_image(api_user(), delivery_id)
    return Response(doc.data, mimetype=doc.mime_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
