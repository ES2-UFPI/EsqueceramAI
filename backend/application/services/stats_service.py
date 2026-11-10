"""Indicadores de dashboard, home pública e administração (src/server/services/stats-service.ts)."""
from application.models import Item
from application.repositories.engagement import (count_matches, count_pending_matches, count_unread_notifications, list_matches)
from application.repositories.items import (count_by_category, count_by_status, count_items, monthly_series, recent_items)
from application.repositories.points import count_points, list_points
from application.repositories.users import count_users, count_users_by_role, list_users, top_contributors


def _scope_counts(owner_id=None) -> dict:
    def n(*extra):
        conds = ([Item.user_id == owner_id] if owner_id else []) + list(extra)
        return count_items(*conds)
    return {"lostActive": n(Item.type == "LOST", Item.status.in_(["OPEN", "RESERVED"])),
            "foundActive": n(Item.type == "FOUND", Item.status.in_(["OPEN", "RESERVED"])),
            "reserved": n(Item.status == "RESERVED"), "returned": n(Item.status == "RETURNED"), "total": n()}


def get_dashboard(user: dict) -> dict:
    staff = user["role"] in ("ADMIN", "OPERATOR_POST")
    scope = None if staff else user["id"]
    personal, glob = _scope_counts(user["id"]), _scope_counts()
    global_pending = count_pending_matches()
    return {
        "isStaff": staff, "myScore": user["score"],
        "lostActive": personal["lostActive"], "foundActive": personal["foundActive"],
        "pendingMatches": global_pending if staff else count_pending_matches(user["id"]),
        "recoveriesInProgress": personal["reserved"], "returned": personal["returned"], "myItems": personal["total"],
        "recent": recent_items(6, scope), "suggestions": list_matches(user_id=scope, status="PENDING", limit=4),
        "unread": count_unread_notifications(user["id"]),
        "chart": {"status": count_by_status(scope), "category": count_by_category(scope),
                  "monthly": monthly_series(6), "contributors": top_contributors(5)},
        "global": {"lostActive": glob["lostActive"], "foundActive": glob["foundActive"],
                   "pendingMatches": global_pending, "returned": glob["returned"],
                   "users": count_users(), "points": count_points()},
    }


def get_public_home() -> dict:
    s = _scope_counts()
    return {"lostActive": s["lostActive"], "foundActive": s["foundActive"], "returned": s["returned"],
            "users": count_users(), "points": count_points(), "recent": recent_items(6)}


def get_admin_overview(query: str | None = None) -> dict:
    returned, total = count_items(Item.status == "RETURNED"), count_items()
    return {
        "userCount": count_users(),
        "roleBreakdown": [{"key": r["role"], "total": r["total"]} for r in count_users_by_role()],
        "statusBreakdown": count_by_status(), "categoryBreakdown": count_by_category(),
        "monthly": monthly_series(6), "contributors": top_contributors(6),
        "confirmed": count_matches("CONFIRMED"), "rejected": count_matches("REJECTED"),
        "pending": count_pending_matches(), "points": list_points(), "users": list_users(q=query),
        "recoveryRate": round(returned / total * 100) if total else 0,
    }
