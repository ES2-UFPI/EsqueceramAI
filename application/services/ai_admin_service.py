"""Telemetria de uso da IA e controle administrativo (sem tabelas extras)."""
import json
import os
import time
from sqlalchemy import select

from application.models import Notification, User, db

_CONFIG_PREFIX = "[AI_CONFIG] "
_CALL_PREFIX = "[AI_CALL] "


def _any_admin_id() -> int | None:
    row = db.execute(
        select(User.id).where(User.role == "ADMIN", User.is_active.is_(True)).order_by(User.id.asc()).limit(1)
    ).scalar_one_or_none()
    if row is not None:
        return row
    return db.execute(select(User.id).order_by(User.id.asc()).limit(1)).scalar_one_or_none()


def is_ai_enabled_by_admin() -> bool:
    """Retorna True salvo se o administrador tiver desativado a IA no painel."""
    try:
        row = db.execute(
            select(Notification.body)
            .where(Notification.type == "SYSTEM", Notification.title.like(f"{_CONFIG_PREFIX}%"))
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if not row:
            return True
        payload = json.loads(row)
        return bool(payload.get("enabled", True))
    except Exception:
        return True


def set_ai_enabled_by_admin(admin_user_id: int, enabled: bool) -> None:
    """Ativa ou desativa o uso da IA em tempo de execução para todos os workers."""
    state_label = "ativada" if enabled else "desativada"
    db.add(Notification(
        user_id=admin_user_id,
        type="SYSTEM",
        title=f"{_CONFIG_PREFIX}IA {state_label}",
        body=json.dumps({"enabled": bool(enabled)}),
        link="/painel/admin/ia",
        is_read=True,
    ))
    db.add(Notification(
        user_id=admin_user_id,
        type="SYSTEM",
        title=f"[ADMIN] IA {state_label} pelo administrador",
        body=f"Uso da IA Gemini Vision foi {state_label} no painel administrativo.",
        link="/painel/admin/ia",
        is_read=True,
    ))
    db.commit()


def record_ai_usage(
    *,
    operation: str,
    model: str,
    success: bool,
    latency_ms: int,
    detail: str = "",
    user_id: int | None = None,
) -> None:
    """Registra uma chamada à IA para exibição no painel administrativo e logs."""
    try:
        uid = user_id or _any_admin_id()
        if not uid:
            return
        payload = {
            "operation": operation,
            "model": model or "desconhecido",
            "success": bool(success),
            "latencyMs": max(0, int(latency_ms)),
            "detail": (detail or "")[:180],
        }
        status_txt = "Sucesso" if success else "Falha"
        db.add(Notification(
            user_id=uid,
            type="SYSTEM",
            title=f"{_CALL_PREFIX}{operation} · {payload['model']} ({status_txt})",
            body=json.dumps(payload, ensure_ascii=False),
            link="/painel/admin/ia",
            is_read=True,
        ))
        db.commit()
    except Exception:
        db.rollback()


def _breakdown(items: list[str]) -> list[dict]:
    counts: dict[str, int] = {}
    for key in items:
        counts[key] = counts.get(key, 0) + 1
    return [{"key": k, "total": v} for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def get_ai_dashboard(limit: int = 50) -> dict:
    """Agrega métricas, gráficos e histórico recente de uso da IA."""
    from application.services import vision_service

    rows = db.execute(
        select(Notification)
        .where(Notification.type == "SYSTEM", Notification.title.like(f"{_CALL_PREFIX}%"))
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    ).scalars().all()

    calls = []
    for r in rows:
        try:
            meta = json.loads(r.body)
        except ValueError:
            meta = {}
        calls.append({
            "operation": meta.get("operation", "ANALYZE"),
            "model": meta.get("model", "—"),
            "success": bool(meta.get("success", False)),
            "latencyMs": int(meta.get("latencyMs", 0)),
            "detail": meta.get("detail", ""),
            "createdAt": r.created_at,
        })

    total = len(calls)
    success_calls = sum(1 for c in calls if c["success"])
    failed_calls = total - success_calls
    success_rate = round((success_calls / total) * 100) if total else 0
    avg_latency = round(sum(c["latencyMs"] for c in calls) / total) if total else 0

    api_key_ok = bool(os.getenv("GEMINI_API_KEY", "").strip())
    admin_enabled = is_ai_enabled_by_admin()
    candidates = vision_service._candidate_models()

    return {
        "apiKeyConfigured": api_key_ok,
        "adminEnabled": admin_enabled,
        "effectiveEnabled": api_key_ok and admin_enabled,
        "defaultModel": candidates[0] if candidates else vision_service.DEFAULT_GEMINI_MODEL,
        "fallbackModels": candidates[1:],
        "totalCalls": total,
        "successCalls": success_calls,
        "failedCalls": failed_calls,
        "successRate": success_rate,
        "avgLatencyMs": avg_latency,
        "operationBreakdown": _breakdown([c["operation"] for c in calls]),
        "modelBreakdown": _breakdown([c["model"] for c in calls]),
        "statusBreakdown": _breakdown(["Sucesso" if c["success"] else "Falha" for c in calls]),
        "recentCalls": calls[:20],
    }


def monotonic_ms(start_ts: float) -> int:
    return int((time.monotonic() - start_ts) * 1000)
