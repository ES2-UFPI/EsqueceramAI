"""Vocabulário de domínio compartilhado por UI, serviços e controllers (src/lib/domain.ts)."""
import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

RECORD_TYPES = ("LOST", "FOUND")
CATEGORIES = ("ELECTRONIC", "DOCUMENT", "ACCESSORY")
STATUSES = ("OPEN", "RESERVED", "RETURNED", "ARCHIVED")
MATCH_STATUSES = ("PENDING", "CONFIRMED", "REJECTED")
ROLES = ("USER", "OPERATOR_POST", "ADMIN")
NOTIFICATION_TYPES = ("MATCH", "UPDATE", "RECOVERY", "SYSTEM")

RECORD_TYPE_LABEL = {"LOST": "Perdido", "FOUND": "Encontrado"}
CATEGORY_LABEL = {"ELECTRONIC": "Eletrônico", "DOCUMENT": "Documento", "ACCESSORY": "Acessório"}
CATEGORY_PLURAL = {"ELECTRONIC": "Eletrônicos", "DOCUMENT": "Documentos", "ACCESSORY": "Acessórios"}
STATUS_LABEL = {"OPEN": "Em aberto", "RESERVED": "Reservado", "RETURNED": "Devolvido", "ARCHIVED": "Arquivado"}
MATCH_STATUS_LABEL = {"PENDING": "Aguardando confirmação", "CONFIRMED": "Confirmado", "REJECTED": "Descartado"}
ROLE_LABEL = {"USER": "Comunidade", "OPERATOR_POST": "Operador de ponto", "ADMIN": "Administrador"}

CATEGORY_FIELDS = {
    "ELECTRONIC": {
        "label": "Eletrônico",
        "hint": "Aparelhos e equipamentos, como celulares, notebooks e fones.",
        "fields": [
            {"name": "serialNumber", "label": "Número de série (opcional)", "placeholder": "Ex.: SN-8821-XP"},
            {"name": "compatibility", "label": "Características técnicas", "placeholder": "Ex.: carregador USB-C, 128 GB"},
        ],
    },
    "DOCUMENT": {
        "label": "Documento",
        "hint": "Documentos acadêmicos e pessoais, como carteiras e diplomas.",
        "fields": [
            {"name": "documentType", "label": "Tipo de documento", "placeholder": "Ex.: Carteira de estudante"},
            {"name": "issuingBody", "label": "Órgão emissor (opcional)", "placeholder": "Ex.: UFPI"},
        ],
    },
    "ACCESSORY": {
        "label": "Acessório",
        "hint": "Itens de uso pessoal, como mochilas, garrafas, chaves e óculos.",
        "fields": [
            {"name": "material", "label": "Material (opcional)", "placeholder": "Ex.: couro sintético"},
            {"name": "visualDetails", "label": "Detalhes visuais", "placeholder": "Ex.: alça rasgada, adesivos coloridos"},
        ],
    },
}

COLORS = ["Preto", "Branco", "Cinza", "Azul", "Verde", "Vermelho", "Rosa", "Roxo", "Amarelo",
          "Laranja", "Marrom", "Bege", "Prata", "Dourado", "Multicor"]

CAMPUS_LOCATIONS = [
    "Biblioteca Central", "Centro de Ciências Humanas e Letras (CCHL)", "Centro de Tecnologia (CT)",
    "Centro de Ciências da Natureza (CCN)", "Centro de Ciências da Saúde (CCS)",
    "Centro de Ciências Agrárias (CCA)", "Restaurante Universitário", "Bloco de Salas Especiais",
    "Praça da Convivência", "Estacionamento Central", "Coordenação do curso", "Laboratórios de pesquisa",
]

CAMPUS_CENTER = {"lat": -5.0563, "lng": -42.7894}
SORT_OPTIONS = [("relevance", "Relevância"), ("recent", "Mais recentes"), ("proximity", "Proximidade")]
PAGE_SIZE = 9

_TZ = ZoneInfo("America/Fortaleza")
_MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def item_code(item_id: int) -> str:
    return f"ESQ-{int(item_id):05d}"


def _aware(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def format_date(value) -> str:
    if not value:
        return "—"
    d = _aware(value).astimezone(_TZ)
    return f"{d.day:02d} de {_MONTHS[d.month - 1]}. de {d.year}"


def format_datetime(value) -> str:
    if not value:
        return "—"
    d = _aware(value).astimezone(_TZ)
    return f"{d.day:02d} de {_MONTHS[d.month - 1]}. de {d.year} {d.hour:02d}:{d.minute:02d}"


def to_input_date(value) -> str:
    if not value:
        return ""
    return _aware(value).astimezone(_TZ).strftime("%Y-%m-%d")


def time_ago(value) -> str:
    diff = (datetime.now(timezone.utc) - _aware(value)).total_seconds()
    minutes = round(diff / 60)
    if minutes < 1:
        return "agora mesmo"
    if minutes < 60:
        return f"há {minutes} min"
    hours = round(minutes / 60)
    if hours < 24:
        return f"há {hours} h"
    days = round(hours / 24)
    if days == 1:
        return "ontem"
    if days < 30:
        return f"há {days} dias"
    months = round(days / 30)
    if months < 12:
        return f"há {months} {'mês' if months == 1 else 'meses'}"
    years = round(months / 12)
    return f"há {years} {'ano' if years == 1 else 'anos'}"


def initials(name: str) -> str:
    return "".join(p[0].upper() for p in name.strip().split()[:2])


def first_name(name: str) -> str:
    parts = name.strip().split()
    return parts[0] if parts else name


def distance_km(lat, lng, to):
    if lat is None or lng is None:
        return None
    r = 6371
    d_lat, d_lng = math.radians(to["lat"] - lat), math.radians(to["lng"] - lng)
    h = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(to["lat"])) * math.sin(d_lng / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(h)) * 10) / 10


def score_level(score: int):
    if score >= 300:
        return {"label": "Guardião do campus", "next": None}
    if score >= 180:
        return {"label": "Embaixador", "next": 300}
    if score >= 90:
        return {"label": "Colaborador", "next": 180}
    if score >= 40:
        return {"label": "Apoiador", "next": 90}
    return {"label": "Iniciante", "next": 40}


def clamp_page(value) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 1
    if not math.isfinite(parsed) or parsed < 1:
        return 1
    return int(parsed)


def is_staff_role(role: str) -> bool:
    return role in ("ADMIN", "OPERATOR_POST")
