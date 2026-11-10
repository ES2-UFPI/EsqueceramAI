"""Entrega de itens com respaldo legal (checkout no posto de coleta).

Pacote autocontido: não altera as regras existentes de itens, matches ou notificações.
"""


def init_app(app):
    """Registra as tabelas e as rotas do módulo de entrega."""
    from app.delivery import models  # noqa: F401  (importar registra as tabelas no metadata)
    from app.delivery.api import bp as api_bp
    app.register_blueprint(api_bp)
    from app.delivery.web import bp as web_bp
    app.register_blueprint(web_bp)
