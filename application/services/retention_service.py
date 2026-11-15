import logging
import os
from datetime import datetime, timedelta, timezone
from application.domain import STORED_STATUSES, item_code, parse_retention_days
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