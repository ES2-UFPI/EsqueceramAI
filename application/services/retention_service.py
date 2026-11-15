import csv
import io
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from application.domain import CATEGORY_LABEL, STORED_STATUSES, fold_text, format_date, item_code, parse_retention_days
from application.repositories.items import list_stored_entered_before

log = logging.getLogger("esqueceram.retention")

def retention_days() -> int:
    return parse_retention_days(os.getenv("STORAGE_RETENTION_DAYS"))

def find_overdue_items(now: datetime | None = None, days: int | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    days = parse_retention_days(days) if days is not None else retention_days()
    cutoff = now - timedelta(days=days)
    items = list_stored_entered_before(cutoff, STORED_STATUSES)
    for it in items:
        it["code"] = item_code(it["id"])
        it["daysStored"] = (now - it["enteredAt"]).days
    return items

def run_daily_check(now: datetime | None = None, days: int | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    days = parse_retention_days(days) if days is not None else retention_days()
    items = find_overdue_items(now=now, days=days)
    for it in items:
        log.info("Item vencido: %s \"%s\" no ponto \"%s\" há %d dias (entrada em %s)",
                 it["code"], it["title"], it["pointName"], it["daysStored"], it["enteredAt"].date().isoformat())
    log.info("Verificação concluída: %d item(ns) armazenado(s) há mais de %d dias.", len(items), days)
    return {"checkedAt": now, "retentionDays": days, "total": len(items), "items": items}

DISPOSAL_PAGE_SIZE = 20
DISPOSAL_SORTS = (("antigos", "Mais antigos primeiro"), ("recentes", "Mais recentes primeiro"), ("titulo", "Título (A–Z)"))
EXTRA_DAY_OPTIONS = (120, 180, 365)
CSV_HEADER = ("Código", "Título", "Categoria", "Ponto de coleta", "Local onde foi encontrado", "Cor", "Marca",
              "Data de entrada", "Dias armazenado")

def day_options() -> list[int]:
    days = retention_days()
    return [d for d in EXTRA_DAY_OPTIONS if d > days]

def _filter(items: list[dict], f: dict, now: datetime) -> list[dict]:
    if f.get("minDays"):
        limit = now - timedelta(days=f["minDays"])
        items = [i for i in items if i["enteredAt"] < limit]
    if f.get("pointId"):
        items = [i for i in items if i["pointId"] == f["pointId"]]
    if f.get("category"):
        items = [i for i in items if i["category"] == f["category"]]
    if term := fold_text(f.get("q")):
        fields = ("code", "title", "location", "brand", "color", "pointName")
        items = [i for i in items if term in fold_text(" ".join(str(i[k] or "") for k in fields))]
    if f.get("sort") == "recentes":
        items = items[::-1]
    elif f.get("sort") == "titulo":
        items = sorted(items, key=lambda i: (fold_text(i["title"]), i["id"]))
    return items

def filter_disposal_candidates(filters: dict | None = None, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    return _filter(find_overdue_items(now=now), filters or {}, now)

def search_disposal_candidates(filters: dict | None = None, page: int = 1, page_size: int = DISPOSAL_PAGE_SIZE,
                               now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    base = find_overdue_items(now=now)
    items = _filter(base, filters or {}, now)
    pages = max(1, math.ceil(len(items) / page_size))
    page = min(max(page, 1), pages)
    return {"items": items[(page - 1) * page_size:page * page_size], "total": len(items), "page": page,
            "pageSize": page_size, "totalPages": pages, "eligible": len(base),
            "points": len({i["pointId"] for i in base}), "oldestDays": max((i["daysStored"] for i in base), default=0),
            "retentionDays": retention_days()}

def _safe_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text

def disposal_csv(items: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for i in items:
        writer.writerow([_safe_cell(v) for v in (i["code"], i["title"], CATEGORY_LABEL.get(i["category"], i["category"]),
                                                 i["pointName"], i["location"], i["color"], i["brand"],
                                                 format_date(i["enteredAt"]), i["daysStored"])])
    return "\ufeff" + out.getvalue()