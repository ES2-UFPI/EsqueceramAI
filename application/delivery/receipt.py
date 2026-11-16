import io
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from application.delivery.security import mac_hex

TZ = ZoneInfo("America/Fortaleza")
BRAND = colors.HexColor("#0d5c53")
ACCENT = colors.HexColor("#c59b27")
SOFT = colors.HexColor("#e4efec")
TINT = colors.HexColor("#f5f9f8")
LINE = colors.HexColor("#d7d3c6")
MUTED = colors.HexColor("#5c6d68")
INK = colors.HexColor("#172824")

LOGO_PATH = Path(__file__).resolve().parents[1] / "web" / "static" / "logo-esqueceram-ai.png"


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


def _section_table(title: str, rows: list[tuple[str, object]], label_style: ParagraphStyle) -> Table:
    header_style = ParagraphStyle("sec", parent=label_style, fontSize=8.5, textColor=colors.white)
    data = [[Paragraph(escape(title), header_style), ""]]
    for k, v in rows:
        data.append([Paragraph(escape(k), label_style), v])
    t = Table(data, colWidths=[52 * mm, 118 * mm])
    t.setStyle(TableStyle([
        ("SPAN", (0, 0), (1, 0)),
        ("BACKGROUND", (0, 0), (1, 0), BRAND),
        ("TOPPADDING", (0, 0), (1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (1, 0), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 1), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 1), (0, -1), SOFT),
        ("BACKGROUND", (1, 1), (1, -1), colors.white),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE),
        ("BOX", (0, 0), (-1, -1), 0.8, BRAND),
        ("TOPPADDING", (0, 1), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5.5),
    ]))
    return t


def build_receipt_pdf(d: ReceiptData) -> tuple[bytes, str]:
    """Retorna (bytes do PDF, código de verificação)."""
    code = verification_code(d)
    number = receipt_number(d.delivery_id, d.created_at)
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK)
    label = ParagraphStyle("label", parent=body, fontName="Helvetica-Bold", fontSize=8.5, textColor=MUTED)
    mono = ParagraphStyle("mono", parent=body, fontName="Courier", fontSize=8, leading=10, textColor=INK)
    h1 = ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=BRAND)
    sub = ParagraphStyle("sub", parent=body, fontSize=8.5, leading=11.5, textColor=MUTED)
    right_meta = ParagraphStyle("rmeta", parent=body, alignment=2, fontSize=8.5, leading=11.5, textColor=MUTED)
    right_num = ParagraphStyle("rnum", parent=body, alignment=2, fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=BRAND)

    def P(text, style=body):
        return Paragraph(escape(str(text)), style)

    if LOGO_PATH.exists():
        left_brand = Image(str(LOGO_PATH), width=48 * mm, height=8 * mm)
    else:
        left_brand = P("Esqueceram AI", h1)

    header = Table(
        [[left_brand,
          Paragraph(f"<font size=8 color='#5c6d68'>TERMO Nº</font><br/><b>{escape(number)}</b><br/>"
                    f"<font size=7.5 color='#5c6d68'>Achados e Perdidos · UFPI</font>", right_num)]],
        colWidths=[102 * mm, 68 * mm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    banner = Table(
        [[Paragraph("<b>Termo Digital de Entrega e Devolução de Objeto</b><br/>"
                    "<font size=8.5 color='#5c6d68'>Comprovante oficial de retirada presencial mediante "
                    "conferência documental e código único.</font>", h1)]],
        colWidths=[170 * mm],
    )
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TINT),
        ("LINEBEFORE", (0, 0), (0, -1), 3.5, BRAND),
        ("LINEBELOW", (0, 0), (-1, -1), 0.8, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))

    item_section = _section_table(
        "1. DADOS DO OBJETO DEVOLVIDO",
        [
            ("Identificador do item", Paragraph(f"<b>{escape(d.item_code)}</b> — {escape(d.item_title)}", body)),
            ("Ponto de coleta", P(d.point_name or "—")),
            ("Data e hora da entrega", Paragraph(f"{escape(format_local(d.confirmed_at))}<br/>"
                                                 f"<font size=7.5 color='#5c6d68'>UTC: {format_utc(d.confirmed_at)}</font>", body)),
        ],
        label,
    )

    recipient_section = _section_table(
        "2. DADOS DO RETIRANTE E CONFERÊNCIA",
        [
            ("Retirante", P(d.recipient_name)),
            ("CPF do retirante (mascarado)", P(d.cpf_masked)),
            ("Confirmação por e-mail", Paragraph(f"Código enviado a {escape(d.email_masked)} e confirmado em {escape(format_local(d.confirmed_at))}", body)),
            ("Atendente responsável", P(f"{d.attendant_name} — matrícula {d.attendant_registration}")),
            ("Documento com foto (SHA-256)", Paragraph(escape(d.document_sha256), mono)),
        ],
        label,
    )

    declaration = Table(
        [[Paragraph("<b>3. DECLARAÇÃO DE RECEBIMENTO</b><br/>"
                    "O retirante acima identificado declara ter recebido o objeto descrito neste termo, conferindo o item no ato da "
                    "entrega. A identidade foi verificada pelo atendente mediante documento oficial com foto, cujo arquivo foi "
                    "registrado em ambiente privado, e a retirada foi confirmada por código de uso único enviado ao e-mail do retirante.",
                    body)]],
        colWidths=[170 * mm],
    )
    declaration.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TINT),
        ("LINEBEFORE", (0, 0), (0, -1), 3, BRAND),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))

    auth_title = ParagraphStyle("auth_t", parent=label, fontSize=8.5, textColor=colors.white)
    auth_box = Table(
        [
            [Paragraph("ASSINATURA ELETRÔNICA E INTEGRIDADE", auth_title), ""],
            [Paragraph(f"<b>Código de verificação:</b> <font name='Courier-Bold' size=10.5 color='#0d5c53'>{code}</font>", body),
             Paragraph(f"Emitido em {format_utc(d.confirmed_at)}", right_meta)],
        ],
        colWidths=[112 * mm, 58 * mm],
    )
    auth_box.setStyle(TableStyle([
        ("SPAN", (0, 0), (1, 0)),
        ("BACKGROUND", (0, 0), (1, 0), BRAND),
        ("BACKGROUND", (0, 1), (1, 1), SOFT),
        ("BOX", (0, 0), (-1, -1), 1, BRAND),
        ("VALIGN", (0, 1), (-1, 1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4.5),
        ("TOPPADDING", (0, 1), (-1, 1), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
    ]))

    story = [
        header,
        Spacer(1, 4),
        banner,
        Spacer(1, 10),
        item_section,
        Spacer(1, 8),
        recipient_section,
        Spacer(1, 9),
        declaration,
        Spacer(1, 9),
        auth_box,
        Spacer(1, 7),
        P("Documento gerado eletronicamente pelo sistema Esqueceram AI, dispensando assinatura manuscrita. O CPF completo não é "
          "impresso neste termo; o documento com foto e os registros de auditoria permanecem armazenados de forma restrita para "
          "eventual contestação. Qualquer alteração dos dados acima invalida o código de verificação.", sub),
    ]

    def chrome(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(BRAND)
        canvas.setLineWidth(3)
        canvas.line(20 * mm, 286 * mm, 190 * mm, 286 * mm)
        canvas.setStrokeColor(ACCENT)
        canvas.setLineWidth(1)
        canvas.line(20 * mm, 284.5 * mm, 190 * mm, 284.5 * mm)
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.6)
        canvas.line(20 * mm, 17 * mm, 190 * mm, 17 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, 12 * mm, f"Esqueceram AI · {number} · emitido em {format_utc(d.confirmed_at)} · verificação {code}")
        canvas.drawRightString(190 * mm, 12 * mm, f"Página {doc.page} de {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
                      title=f"Termo de Entrega {number}", author="Esqueceram AI", subject=f"Item {d.item_code}").build(
        story, onFirstPage=chrome, onLaterPages=chrome)
    return buf.getvalue(), code
