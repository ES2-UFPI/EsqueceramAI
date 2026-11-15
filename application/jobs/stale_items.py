import argparse
import json
import logging
import sys
from application.models import db
from application.services.retention_service import run_daily_check

log = logging.getLogger("esqueceram.retention")

def _serializable(report: dict) -> dict:
    return {
        "checkedAt": report["checkedAt"].isoformat(),
        "retentionDays": report["retentionDays"],
        "total": report["total"],
        "items": [{**it, "enteredAt": it["enteredAt"].isoformat()} for it in report["items"]],
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verifica itens armazenados além do prazo de guarda.")
    parser.add_argument("--days", type=int, default=None, help="prazo de guarda em dias (padrão: 90)")
    parser.add_argument("--json", action="store_true", help="imprime o relatório em JSON")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        report = run_daily_check(days=args.days)
    except Exception:
        log.exception("Falha na verificação diária de itens armazenados.")
        return 1
    finally:
        db.remove()
    if args.json:
        print(json.dumps(_serializable(report), ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())