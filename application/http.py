"""Infraestrutura HTTP compartilhada: CORS, JSON, erros e wrappers de autenticação (src/server/http.ts)."""
import os
from datetime import date, datetime, timezone
from functools import wraps

from flask import Response, g, jsonify, request
from flask.json.provider import DefaultJSONProvider
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError

from application.auth import SESSION_COOKIE, authenticate
from application.errors import ApiError, forbidden, unauthorized


class JSONProvider(DefaultJSONProvider):
    ensure_ascii = False
    sort_keys = False

    @staticmethod
    def default(o):
        if isinstance(o, datetime):
            if o.tzinfo is None:
                o = o.replace(tzinfo=timezone.utc)
            return o.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if isinstance(o, date):
            return o.isoformat()
        return DefaultJSONProvider.default(o)


def cors_headers() -> dict:
    """Monta CORS para uma origem permitida, nunca uma lista no cabeçalho.

    ``Access-Control-Allow-Origin`` aceita apenas um valor. Em produção a
    origem vem de ``FRONTEND_ORIGIN`` (GitHub Pages); localhost permanece
    disponível apenas para desenvolvimento.
    """
    configured = os.getenv("CORS_ORIGINS") or os.getenv("FRONTEND_ORIGIN", "")
    allowed = {origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()}
    allowed.update({"http://localhost:5500", "http://127.0.0.1:5500"})
    origin = (request.headers.get("Origin") or "").rstrip("/")
    headers = {"Access-Control-Allow-Methods": "GET, POST, PATCH, PUT, DELETE, OPTIONS",
               "Access-Control-Allow-Headers": "Content-Type, Authorization",
               "Access-Control-Max-Age": "86400", "Vary": "Origin"}
    if origin in allowed:
        headers["Access-Control-Allow-Origin"] = origin
    return headers


def error_response(error: Exception):
    if isinstance(error, ApiError):
        return jsonify(error=error.message, details=error.details), error.status
    if isinstance(error, ProgrammingError):
        return jsonify(error="O banco de dados ainda não foi inicializado. Reinicie a aplicação para criar as tabelas e tente novamente."), 503
    if isinstance(error, (OperationalError, DBAPIError)):
        return jsonify(error="Não foi possível conectar ao banco. Verifique a variável DATABASE_URL."), 503
    print("[api] unexpected error", repr(error))
    return jsonify(error="Erro inesperado no servidor. Tente novamente."), 500


def read_json() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("Corpo da requisição inválido.", 400)
    return data


def api_user(required=True):
    user = authenticate()
    if required and not user:
        raise unauthorized()
    return user


def controller(fn):
    """Equivale ao wrapper `controller()`: captura erros de domínio/validação."""
    @wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as exc:  # noqa: BLE001
            from application.models import db
            db.rollback()
            return error_response(exc)
    return wrapper


def apply_cors(resp: Response) -> Response:
    if request.path.startswith("/api/"):
        for k, v in cors_headers().items():
            resp.headers.setdefault(k, v)
    return resp


def apply_session_cookie(resp: Response) -> Response:
    new = g.get("new_session")
    if new:
        token, expires = new
        resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Lax", path="/", expires=expires)
    return resp
