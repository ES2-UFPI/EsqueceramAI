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
RADIUS_OPTIONS = (0.2, 0.5, 1, 2, 5)
MIN_RADIUS_KM, MAX_RADIUS_KM = 0.05, 50
EARTH_RADIUS_KM = 6371
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

def haversine_km(lat1, lng1, lat2, lng2) -> float:
    d_lat, d_lng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    h = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, h)))

def distance_km(lat, lng, to):
    if lat is None or lng is None:
        return None
    return round(haversine_km(lat, lng, to["lat"], to["lng"]) * 10) / 10

def format_distance(km) -> str:
    if km is None:
        return ""
    if km < 0.01:
        return "menos de 10 m"
    meters = round(km * 100) * 10
    if meters < 1000:
        return f"{meters} m"
    return f"{km:.1f}".replace(".", ",") + " km"

def bounding_box(lat, lng, radius_km):
    d_lat = math.degrees(radius_km / EARTH_RADIUS_KM)
    cos_lat = math.cos(math.radians(lat))
    d_lng = math.degrees(radius_km / (EARTH_RADIUS_KM * cos_lat)) if cos_lat > 1e-9 else 360.0
    lng_min, lng_max = lng - d_lng, lng + d_lng
    if lng_min < -180 or lng_max > 180:
        lng_min = lng_max = None
    return lat - d_lat, lat + d_lat, lng_min, lng_max

def _blank(value) -> bool:
    return value is None or str(value).strip() == ""

def _to_float(value):
    n = float(str(value).strip().replace(",", "."))
    if not math.isfinite(n):
        raise ValueError
    return n

def parse_geo_params(lat, lng, radius_km):
    if _blank(lat) and _blank(lng) and _blank(radius_km):
        return None, None
    if _blank(lat) or _blank(lng):
        return None, "Informe latitude e longitude do ponto de referência para filtrar por localização."
    try:
        la, ln = _to_float(lat), _to_float(lng)
    except ValueError:
        return None, "Latitude e longitude devem ser números."
    if not -90 <= la <= 90:
        return None, "Latitude deve estar entre -90 e 90."
    if not -180 <= ln <= 180:
        return None, "Longitude deve estar entre -180 e 180."
    radius = None
    if not _blank(radius_km):
        try:
            radius = _to_float(radius_km)
        except ValueError:
            return None, "O raio deve ser um número em quilômetros."
        if not MIN_RADIUS_KM <= radius <= MAX_RADIUS_KM:
            return None, f"O raio deve estar entre {MIN_RADIUS_KM:g} e {MAX_RADIUS_KM:g} km."
    return {"lat": la, "lng": ln, "radiusKm": radius}, None

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