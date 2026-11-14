"""Regras de negócio da entrega com respaldo legal.

Fluxo:  start_delivery (CPF + documento + e-mail)  →  código enviado ao retirante
        →  confirm_delivery (atendente digita o código)  →  termo em PDF + item com status final "Entregue".

"""
import re
from datetime import timedelta

from application.delivery import models as m
from application.delivery import repository as repo
from application.delivery import security as sec
from application.delivery.cpf import mask_cpf, validate_cpf
from application.delivery.documents import validate_document
from application.delivery.email_service import EmailError, backend_name, mask_email, send_confirmation_code
from application.delivery.receipt import ReceiptData, build_receipt_pdf, receipt_number, verification_code
from application.domain import item_code
from application.errors import ApiError, forbidden, not_found
from application.models import atomic, utcnow
from application.repositories.items import find_item_by_id, items_at_points
from application.services.item_service import change_item_status
from application.validation import Form

ABANDON_AFTER_HOURS = 24
REGISTRATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{3,19}$")


# ------------------------------------------------------------------ permissões
def _require_attendant(user: dict):
    if user["role"] != "OPERATOR_POST":
        raise forbidden("Apenas atendentes de posto de coleta podem registrar entregas.")


def _load(delivery_id: int) -> m.Delivery:
    d = repo.get_delivery(delivery_id)
    if not d:
        raise not_found("Entrega")
    return d


def _load_for_viewer(user: dict, delivery_id: int) -> m.Delivery:
    """Atendente vê as próprias entregas; administrador pode auditar todas."""
    d = _load(delivery_id)
    if user["role"] == "ADMIN" or (user["role"] == "OPERATOR_POST" and d.attendant_id == user["id"]):
        return d
    raise forbidden("Você não tem acesso a esta entrega.")


def _load_for_attendant(user: dict, delivery_id: int) -> m.Delivery:
    """Só o atendente que iniciou a entrega pode confirmar, reenviar ou cancelar."""
    _require_attendant(user)
    d = _load(delivery_id)
    if d.attendant_id != user["id"]:
        raise forbidden("Esta entrega foi iniciada por outro atendente.")
    return d


# ------------------------------------------------------------------- matrícula
def get_registration(user: dict) -> str | None:
    return repo.get_registration(user["id"])


def set_registration(user: dict, number: str) -> str:
    _require_attendant(user)
    number = (number or "").strip().upper()
    if not REGISTRATION_RE.match(number):
        msg = "Use de 4 a 20 caracteres (letras, números, ponto, hífen ou sublinhado)."
        raise ApiError("Matrícula inválida.", 422, {"registrationNumber": [msg]})
    try:
        repo.set_registration(user["id"], number)
    except repo.RegistrationTaken:
        raise ApiError("Esta matrícula já está em uso por outro atendente.", 409,
                       {"registrationNumber": ["Matrícula já cadastrada."]})
    return number


# ------------------------------------------------------------- itens elegíveis
def deliverable_items() -> list[dict]:
    """Itens encontrados, em ponto de coleta, ainda aguardando retirada."""
    return [i for i in items_at_points() if i["type"] == "FOUND" and i["status"] in ("OPEN", "RESERVED")]


def _check_item_available(item_id: int) -> dict:
    item = find_item_by_id(item_id)
    if not item:
        raise not_found("Item")
    if item["type"] != "FOUND":
        raise ApiError("Apenas itens encontrados podem ser entregues no posto.", 422, {"itemId": ["Item não é do tipo encontrado."]})
    if item["pointId"] is None:
        raise ApiError("O item não está vinculado a um ponto de coleta.", 422, {"itemId": ["Item sem ponto de coleta."]})
    if item["status"] not in ("OPEN", "RESERVED"):
        raise ApiError("Este item não está disponível para entrega (já devolvido ou arquivado).", 409)
    return item


def _check_no_conflicting_delivery(item_id: int):
    now = utcnow()
    for other in repo.deliveries_for_item(item_id):
        if other.status == m.COMPLETED:
            raise ApiError("Este item já tem uma entrega concluída.", 409)
        if other.code_expires_at and other.code_expires_at < now - timedelta(hours=ABANDON_AFTER_HOURS):
            other.status = m.EXPIRED  # abandonada: não bloqueia mais
            repo.save(other)
            repo.add_event(other.id, "EXPIRED", "Entrega abandonada sem confirmação")
            continue
        raise ApiError(f"Já existe uma entrega em andamento (#{other.id}) para este item. Conclua ou cancele-a antes de iniciar outra.", 409)


# ------------------------------------------------------------- e-mail com código
def _dispatch_code(d: m.Delivery, code: str) -> dict:
    d.code_sent_at = utcnow()
    try:
        backend = send_confirmation_code(to=d.recipient_email, name=d.recipient_name, code=code, item_title=d.item_title,
                                         point_name=d.point_name, ttl_minutes=sec.CODE_TTL_MINUTES)
    except EmailError:
        d.email_delivered = False
        repo.save(d)
        repo.add_event(d.id, "CODE_SEND_FAILED", f"Falha ao enviar e-mail para {mask_email(d.recipient_email)}")
        return {"sent": False, "backend": backend_name(),
                "error": "Não foi possível enviar o e-mail agora. Confira o endereço e use \"Reenviar código\"."}
    d.email_delivered = True
    repo.save(d)
    repo.add_event(d.id, "CODE_SENT", f"Código enviado para {mask_email(d.recipient_email)} ({backend})")
    return {"sent": True, "backend": backend, "error": None}


def _issue_code(d: m.Delivery) -> str:
    code = sec.generate_code()
    d.code_hash = sec.hash_code(d.id, code)
    d.code_expires_at = utcnow() + timedelta(minutes=sec.CODE_TTL_MINUTES)
    d.code_attempts = 0
    return code


# ------------------------------------------------------------------ 1) iniciar
def start_delivery(user: dict, form: dict, document_file) -> dict:
    _require_attendant(user)
    registration = repo.get_registration(user["id"])
    if not registration:
        raise ApiError("Cadastre sua matrícula de atendente antes de registrar entregas.", 409,
                       {"registrationNumber": ["Matrícula não cadastrada."]})

    f = Form(form)
    item_id = f.number("itemId", integer=True, positive=True)
    if item_id is None and "itemId" not in f.errors:
        f.errors["itemId"] = ["Selecione o item a ser entregue."]
    name = f.text("recipientName", min=5, min_msg="Informe o nome completo do retirante.", max=120)
    if name and len(name.split()) < 2:
        f.errors.setdefault("recipientName", []).append("Informe nome e sobrenome.")
    cpf_digits = None
    if f.text("cpf", min=1, min_msg="Informe o CPF do retirante."):
        cpf_digits, cpf_error = validate_cpf(f.data["cpf"])
        if cpf_error:
            f.errors.setdefault("cpf", []).append(cpf_error)
    f.email("email", "Informe um e-mail válido para receber o código.")
    document = None
    try:
        document = validate_document(document_file)
    except ApiError as exc:
        f.errors["document"] = [exc.message]
    data = f.finish()  # levanta 422 com todos os erros de uma vez

    item = _check_item_available(item_id)
    _check_no_conflicting_delivery(item_id)

    d = repo.create_delivery(
        item_id=item["id"], item_code=item_code(item["id"]), item_title=item["title"], point_name=item["pointName"],
        attendant_id=user["id"], attendant_name=user["name"], attendant_registration=registration,
        recipient_name=data["recipientName"], recipient_cpf_hash=sec.hash_cpf(cpf_digits),
        recipient_cpf_masked=mask_cpf(cpf_digits), recipient_email=data["email"], status=m.PENDING)
    repo.save_document(d.id, mime_type=document.mime_type, size_bytes=document.size_bytes, sha256=document.sha256, data=document.data)
    repo.add_event(d.id, "CREATED", f"Entrega iniciada por {user['name']} (matrícula {registration}); documento SHA-256 {document.sha256[:16]}…")
    code = _issue_code(d)
    repo.save(d)
    return {"delivery": d, "email": _dispatch_code(d, code)}


# ----------------------------------------------------------------- 2) reenviar
def resend_code(user: dict, delivery_id: int) -> dict:
    d = _load_for_attendant(user, delivery_id)
    _ensure_pending(d)
    now = utcnow()
    if d.code_sent_at:
        wait = sec.RESEND_COOLDOWN_SECONDS - int((now - d.code_sent_at).total_seconds())
        if wait > 0:
            raise ApiError(f"Aguarde {wait} s para reenviar o código.", 429)
    if d.resend_count >= sec.MAX_RESENDS:
        raise ApiError("Limite de reenvios atingido. Cancele esta entrega e inicie outra.", 429)
    d.resend_count += 1
    code = _issue_code(d)
    repo.save(d)
    return {"delivery": d, "email": _dispatch_code(d, code)}


def _ensure_pending(d: m.Delivery):
    if d.status == m.COMPLETED:
        raise ApiError("Esta entrega já foi concluída.", 409)
    if d.status != m.PENDING:
        raise ApiError("Esta entrega foi cancelada ou expirou. Inicie uma nova.", 409)


# ----------------------------------------------------------------- 3) confirmar
def _receipt_data(d: m.Delivery, document_sha256: str, confirmed_at) -> ReceiptData:
    return ReceiptData(delivery_id=d.id, created_at=d.created_at, confirmed_at=confirmed_at, item_code=d.item_code,
                       item_title=d.item_title, point_name=d.point_name, recipient_name=d.recipient_name,
                       cpf_masked=d.recipient_cpf_masked, cpf_hash=d.recipient_cpf_hash, email_masked=mask_email(d.recipient_email),
                       attendant_name=d.attendant_name, attendant_registration=d.attendant_registration,
                       document_sha256=document_sha256)


def confirm_delivery(user: dict, delivery_id: int, code: str) -> m.Delivery:
    d = _load_for_attendant(user, delivery_id)
    _ensure_pending(d)
    code = (code or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ApiError("Informe o código de 6 dígitos enviado ao retirante.", 422, {"code": ["Código deve ter 6 dígitos."]})
    if d.code_expires_at is None or utcnow() > d.code_expires_at:
        repo.add_event(d.id, "CODE_EXPIRED", "Tentativa com código expirado")
        raise ApiError("O código expirou. Reenvie um novo código ao retirante.", 410, {"code": ["Código expirado."]})

    if not sec.verify_code(d.id, code, d.code_hash):
        d.code_attempts += 1
        left = sec.MAX_ATTEMPTS - d.code_attempts
        if left <= 0:
            d.status = m.CANCELLED
            repo.save(d)
            repo.add_event(d.id, "LOCKED", "Entrega cancelada após tentativas incorretas")
            raise ApiError("Muitas tentativas incorretas. A entrega foi cancelada por segurança; inicie uma nova.", 429)
        repo.save(d)
        repo.add_event(d.id, "CODE_WRONG", f"Código incorreto ({d.code_attempts}/{sec.MAX_ATTEMPTS})")
        raise ApiError(f"Código incorreto. Restam {left} tentativa(s).", 422, {"code": [f"Código incorreto. Restam {left}."]})

    # código correto: valida o item, gera o termo (sem efeitos colaterais) e só então devolve o item
    item = find_item_by_id(d.item_id) if d.item_id else None
    if not item or item["status"] not in ("OPEN", "RESERVED"):
        raise ApiError("O item não está mais disponível para entrega (foi removido, devolvido ou arquivado).", 409)
    document = repo.get_document(d.id)
    confirmed_at = utcnow()
    receipt = _receipt_data(d, document.sha256, confirmed_at)
    pdf, vcode = build_receipt_pdf(receipt)

    number = receipt_number(d.id, d.created_at)
    with atomic():  # tudo ou nada: item "Entregue", entrega concluída, termo e auditoria juntos
        change_item_status(user, d.item_id, "DELIVERED", note=f"Entrega registrada no termo {number}.")
        d.status, d.confirmed_at, d.code_hash = m.COMPLETED, confirmed_at, None
        repo.save(d)
        repo.save_receipt(d.id, verification_code=vcode, sha256=sec.sha256_hex(pdf), pdf=pdf)
        repo.add_event(d.id, "CONFIRMED", f"Entrega confirmada; termo {number} emitido (verificação {vcode})")
    return d


# ------------------------------------------------------------------ cancelar
def cancel_delivery(user: dict, delivery_id: int) -> m.Delivery:
    d = _load_for_attendant(user, delivery_id)
    _ensure_pending(d)
    d.status, d.code_hash = m.CANCELLED, None
    repo.save(d)
    repo.add_event(d.id, "CANCELLED", f"Cancelada por {user['name']}")
    return d


# ----------------------------------------------------------------- consultas
def list_for_user(user: dict) -> list[m.Delivery]:
    if user["role"] == "ADMIN":
        return repo.list_deliveries()
    _require_attendant(user)
    return repo.list_deliveries(attendant_id=user["id"])


def get_for_user(user: dict, delivery_id: int) -> m.Delivery:
    return _load_for_viewer(user, delivery_id)


def get_receipt_pdf(user: dict, delivery_id: int):
    d = _load_for_viewer(user, delivery_id)
    receipt = repo.get_receipt(d.id)
    if d.status != m.COMPLETED or not receipt:
        raise not_found("Termo de entrega")
    return d, receipt


def get_document_image(user: dict, delivery_id: int):
    d = _load_for_viewer(user, delivery_id)
    doc = repo.get_document(d.id)
    if not doc:
        raise not_found("Documento")
    return d, doc


def verify_delivery(user: dict, delivery_id: int, cpf: str | None = None) -> dict:
    """Apoio a contestações: confere integridade do termo/documento e (opcional) se um CPF é o do retirante."""
    d = _load_for_viewer(user, delivery_id)
    out = {"deliveryId": d.id, "receiptNumber": receipt_number(d.id, d.created_at), "status": d.status}
    doc, receipt = repo.get_document(d.id), repo.get_receipt(d.id)
    out["documentIntact"] = bool(doc and sec.sha256_hex(doc.data) == doc.sha256)
    if receipt:
        recomputed = verification_code(_receipt_data(d, doc.sha256, d.confirmed_at))
        out["receiptIntact"] = sec.sha256_hex(receipt.pdf) == receipt.sha256 and recomputed == receipt.verification_code
        out["verificationCode"] = receipt.verification_code
    else:
        out["receiptIntact"] = None
    if cpf is not None:
        digits, error = validate_cpf(cpf)
        out["cpfMatches"] = bool(digits) and sec.hash_cpf(digits) == d.recipient_cpf_hash
        if error:
            out["cpfError"] = error
    return out


# ------------------------------------------------------------- serialização
def delivery_dict(d: m.Delivery, *, detail: bool = False) -> dict:
    now = utcnow()
    out = {
        "id": d.id, "receiptNumber": receipt_number(d.id, d.created_at), "status": d.status,
        "itemId": d.item_id, "itemCode": d.item_code, "itemTitle": d.item_title, "pointName": d.point_name,
        "recipientName": d.recipient_name, "cpfMasked": d.recipient_cpf_masked, "emailMasked": mask_email(d.recipient_email),
        "attendantName": d.attendant_name, "attendantRegistration": d.attendant_registration,
        "createdAt": d.created_at, "confirmedAt": d.confirmed_at, "codeExpiresAt": d.code_expires_at,
        "codeExpired": bool(d.status == m.PENDING and d.code_expires_at and d.code_expires_at < now),
        "attemptsLeft": max(sec.MAX_ATTEMPTS - d.code_attempts, 0), "emailDelivered": d.email_delivered,
        "hasReceipt": d.status == m.COMPLETED,
    }
    if detail:
        doc, receipt = repo.get_document(d.id), repo.get_receipt(d.id)
        item = find_item_by_id(d.item_id) if d.item_id else None
        out["itemStatus"] = item["status"] if item else None  # status final do item (DELIVERED após a conclusão)
        out["documentSha256"] = doc.sha256 if doc else None
        out["verificationCode"] = receipt.verification_code if receipt else None
        out["events"] = [{"action": e.action, "detail": e.detail, "createdAt": e.created_at} for e in repo.list_events(d.id)]
    return out
