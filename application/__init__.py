"""Esqueceram AI — aplicação Flask (porta do projeto Next.js + Drizzle)."""
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()

from application.http import JSONProvider, apply_cors, apply_session_cookie, error_response
from application.models import db, init_db


def create_app() -> Flask:
    app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
    app.json_provider_class = JSONProvider
    app.json = JSONProvider(app)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024

    from application import domain
    from urllib.parse import urlencode
    # Globais visíveis também dentro de macros importados (D e qs)
    app.jinja_env.globals.update(
        D=domain,
        qs=lambda base=None, **kw: urlencode({k: v for k, v in {**(base or {}), **kw}.items() if v not in (None, "")}))

    from application import delivery
    delivery.init_app(app)  # módulo de entrega com respaldo legal (tabelas/rotas próprias)

    init_db()  # equivale a `drizzle-kit push` (cria apenas o que falta)

    from application.api.routes import bp as api_bp
    from application.api.mvp import bp as mvp_bp
    from application.web.views import bp as web_bp
    app.register_blueprint(api_bp)
    app.register_blueprint(mvp_bp)
    app.register_blueprint(web_bp)

    @app.after_request
    def _after(resp):
        return apply_session_cookie(apply_cors(resp))

    @app.teardown_appcontext
    def _cleanup(_exc):
        db.remove()

    @app.errorhandler(413)
    def _too_large(_e):
        return jsonify(error="Arquivo muito grande."), 413

    @app.errorhandler(405)
    def _method(e):
        if request.path.startswith("/api/"):
            return jsonify(error="Rota não encontrada."), 404
        return jsonify(error="Método não permitido."), 405

    @app.errorhandler(404)
    def _not_found(e):
        if request.path.startswith("/api/"):
            return jsonify(error="Rota não encontrada."), 404
        from application.web.views import render_not_found
        return render_not_found()

    return app
