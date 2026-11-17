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
INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#4b5563")
BORDER = colors.HexColor("#374151")
GRID = colors.HexColor("#9ca3af")

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


def build_receipt_pdf(d: ReceiptData) -> tuple[bytes, str]:
    """Retorna (bytes do PDF, código de verificação) em layout estilo boleto/recibo branco."""
    code = verification_code(d)
    number = receipt_number(d.delivery_id, d.created_at)
    base = getSampleStyleSheet()
    val = ParagraphStyle("val", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=12.5, textColor=INK)
    val_b = ParagraphStyle("valb", parent=val, fontName="Helvetica-Bold")
    mono = ParagraphStyle("mono", parent=val, fontName="Courier", fontSize=8, leading=10, textColor=INK)
    title_st = ParagraphStyle("title", parent=val, fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=INK)
    num_st = ParagraphStyle("num", parent=val, alignment=2, fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=INK)
    small = ParagraphStyle("small", parent=val, fontSize=8, leading=11, textColor=MUTED)

    def cell(lbl: str, value_html: str, style=val) -> Paragraph:
        return Paragraph(f"<font size=7 color='#4b5563'><b>{escape(lbl.upper())}</b></font><br/>{value_html}", style)

    logo = Image(str(LOGO_PATH), width=42 * mm, height=7 * mm) if LOGO_PATH.exists() else Paragraph("<b>Esqueceram AI</b>", title_st)

    top_bar = Table(
        [[logo,
          Paragraph("<b>Termo Digital de Entrega de Objeto</b><br/><font size=8 color='#4b5563'>Comprovante de devolução · UFPI</font>", title_st),
          Paragraph(f"<font size=7 color='#4b5563'>NÚMERO DO TERMO</font><br/>{escape(number)}", num_st)]],
        colWidths=[46 * mm, 82 * mm, 42 * mm],
    )
    top_bar.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 1.4, BORDER),
        ("LINEAFTER", (0, 0), (1, 0), 0.6, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    # Grade estilo boleto (células todas brancas com rótulo pequeno no topo e valor abaixo)
    grid_rows = [
        [cell("Código do item", f"<b>{escape(d.item_code)}</b>"),
         cell("Descrição do objeto", escape(d.item_title)),
         cell("Ponto de coleta", escape(d.point_name or "—"))],
        [cell("Retirante", escape(d.recipient_name)),
         cell("CPF (mascarado)", escape(d.cpf_masked)),
         cell("Confirmação por e-mail", escape(d.email_masked))],
        [cell("Atendente responsável", f"{escape(d.attendant_name)} · mat. {escape(d.attendant_registration)}"),
         cell("Data e hora da entrega", f"{escape(format_local(d.confirmed_at))}<br/><font size=7.5 color='#4b5563'>UTC: {format_utc(d.confirmed_at)}</font>"),
         ""],
        [cell("Documento com foto (SHA-256 da imagem)", f"<font name='Courier' size=8>{escape(d.document_sha256)}</font>"), "", ""],
    ]
    boleto = Table(grid_rows, colWidths=[44 * mm, 76 * mm, 50 * mm])
    boleto.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 1.0, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, GRID),
        ("SPAN", (1, 2), (2, 2)),
        ("SPAN", (0, 3), (2, 3)),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    declaration = Table(
        [[Paragraph(
            "<font size=7 color='#4b5563'><b>DECLARAÇÃO DE RECEBIMENTO</b></font><br/>"
            "Declaro ter conferido e recebido o objeto descrito acima neste termo. A identidade do retirante foi verificada pelo "
            "atendente mediante documento oficial com foto (armazenado de forma restrita) e confirmada por código único enviado "
            "ao e-mail informado.",
            val,
        )]],
        colWidths=[170 * mm],
    )
    declaration.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.8, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    auth_strip = Table(
        [[cell("ASSINATURA ELETRÔNICA · CÓDIGO DE VERIFICAÇÃO", f"<font name='Courier-Bold' size=10.5>{code}</font>"),
          cell("EMISSÃO ELETRÔNICA (UTC)", escape(format_utc(d.confirmed_at)), val_b)]],
        colWidths=[118 * mm, 52 * mm],
    )
    auth_strip.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 1.0, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    story = [
        top_bar,
        Spacer(1, 6),
        boleto,
        Spacer(1, 6),
        declaration,
        Spacer(1, 6),
        auth_strip,
        Spacer(1, 6),
        Paragraph(
            "Documento gerado eletronicamente pelo sistema Esqueceram AI, dispensando assinatura manuscrita. "
            "O CPF completo não é impresso neste termo; qualquer alteração dos dados invalida o código de verificação.",
            small,
        ),
    ]

    def chrome(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.6)
        canvas.line(20 * mm, 16 * mm, 190 * mm, 16 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(20 * mm, 11.5 * mm, f"Esqueceram AI · {number} · verificação {code}")
        canvas.drawRightString(190 * mm, 11.5 * mm, f"Página {doc.page} de {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
                      title=f"Termo de Entrega {number}", author="Esqueceram AI", subject=f"Item {d.item_code}").build(
        story, onFirstPage=chrome, onLaterPages=chrome)
    return buf.getvalue(), code
