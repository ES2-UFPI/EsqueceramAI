"""Ponto de entrada único do backend EsqueceramAI.

O código de domínio fica em ``application``: controllers, services e
repositories. Este módulo pequeno é o alvo de Gunicorn, testes e Render.
"""
from application import create_app


app = create_app()


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
