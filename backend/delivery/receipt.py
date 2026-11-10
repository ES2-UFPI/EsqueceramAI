"""Termo digital de entrega em PDF (reportlab).

Conteúdo: carimbo de data/hora, CPF mascarado, identificador do item e matrícula do atendente
responsável, além de hash SHA-256 da imagem do documento e de um código de verificação (HMAC).
"""
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.delivery.security import mac_hex

TZ = ZoneInfo("America/Fortaleza")
BRAND = colors.HexColor("#0d5c53")
SOFT = colors.HexColor("#e4efec")
LINE = colors.HexColor("#d7d3c6")


@dataclass(frozen=True)
class ReceiptData:
    delivery_id: int
    created_at: datetime
    confirmed_at: datetime
    item_code: str
    item_title: str
    point_name: str | None
    recipient_name: str
    cpf_masked: str
    cpf_hash: str            # só entra no código de verificação; nunca é impresso
    email_masked: str
    attendant_name: str
    attendant_registration: str
    document_sha256: str


def receipt_number(delivery_id: int, created_at: datetime) -> str:
    return f"ENT-{created_at.astimezone(TZ).year}-{delivery_id:06d}"


def _utc(dt: datetime) -> datetime:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def format_local(dt: datetime) -> str:
    d = _utc(dt).astimezone(TZ)
    return d.strftime("%d/%m/%Y %H:%M:%S") + " (horário de Fortaleza, UTC-03:00)"


def format_utc(dt: datetime) -> str:
    return _utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def verification_code(d: ReceiptData) -> str:
    """HMAC dos dados essenciais: permite provar que o termo não foi adulterado depois de emitido."""
    payload = "|".join([receipt_number(d.delivery_id, d.created_at), d.item_code, d.cpf_hash, d.attendant_registration,
                        d.document_sha256, format_utc(d.confirmed_at)])
    raw = mac_hex("receipt:" + payload)[:20].upper()
    return "-".join(raw[i:i + 5] for i in range(0, 20, 5))


def build_receipt_pdf(d: ReceiptData) -> tuple[bytes, str]:
    """Retorna (bytes do PDF, código de verificação)."""
    code = verification_code(d)
    number = receipt_number(d.delivery_id, d.created_at)
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=10, leading=14)
    label = ParagraphStyle("label", parent=body, fontName="Helvetica-Bold", fontSize=8.5, textColor=colors.HexColor("#64746f"))
    mono = ParagraphStyle("mono", parent=body, fontName="Courier", fontSize=8, leading=10)
    h1 = ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=BRAND)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11, textColor=colors.HexColor("#3d504b"))

    def P(text, style=body):
        return Paragraph(escape(str(text)), style)

    rows = [
        ("Nº do termo", P(number)),
        ("Data e hora da entrega", Paragraph(f"{escape(format_local(d.confirmed_at))}<br/><font size=8 color='#64746f'>UTC: {format_utc(d.confirmed_at)}</font>", body)),
        ("Identificador do item", P(f"{d.item_code} — {d.item_title}")),
        ("Ponto de coleta", P(d.point_name or "—")),
        ("Retirante", P(d.recipient_name)),
        ("CPF do retirante (mascarado)", P(d.cpf_masked)),
        ("Confirmação por e-mail", Paragraph(f"Código enviado a {escape(d.email_masked)} e confirmado em {escape(format_local(d.confirmed_at))}", body)),
        ("Atendente responsável", P(f"{d.attendant_name} — matrícula {d.attendant_registration}")),
        ("Documento com foto (SHA-256 da imagem)", Paragraph(escape(d.document_sha256), mono)),
    ]
    table = Table([[P(k, label), v] for k, v in rows], colWidths=[52 * mm, 118 * mm])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (0, -1), SOFT),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE), ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    declaration = (
        "O retirante acima identificado declara ter recebido o objeto descrito neste termo, conferindo o item no ato da "
        "entrega. A identidade foi verificada pelo atendente mediante documento oficial com foto, cuja imagem foi "
        "registrada em ambiente privado, e a retirada foi confirmada por código de uso único enviado ao e-mail do retirante."
    )
    story = [
        P("Esqueceram AI · achados e perdidos", small), Spacer(1, 4),
        P("Termo de Entrega de Objeto", h1), Spacer(1, 10), table, Spacer(1, 12),
        P(declaration), Spacer(1, 10),
        Table([[Paragraph(f"<b>Código de verificação:</b> <font name='Courier'>{code}</font>", body)]], colWidths=[170 * mm],
              style=TableStyle([("BOX", (0, 0), (-1, -1), 1, BRAND), ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                                ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)])),
        Spacer(1, 8),
        P("Documento gerado eletronicamente, sem assinatura manuscrita. O CPF completo não é impresso neste termo; a imagem do "
          "documento e os registros de auditoria permanecem armazenados de forma restrita para eventual contestação. "
          "Qualquer alteração dos dados acima invalida o código de verificação.", small),
    ]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64746f"))
        canvas.drawString(20 * mm, 12 * mm, f"{number} · emitido em {format_utc(d.confirmed_at)} · verificação {code}")
        canvas.drawRightString(190 * mm, 12 * mm, "Página 1 de 1")
        canvas.setStrokeColor(BRAND)
        canvas.setLineWidth(3)
        canvas.line(20 * mm, 285 * mm, 190 * mm, 285 * mm)
        canvas.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=22 * mm, bottomMargin=20 * mm,
                      title=f"Termo de Entrega {number}", author="Esqueceram AI", subject=f"Item {d.item_code}").build(
        story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue(), code
