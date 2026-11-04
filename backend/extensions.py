from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def url_sqlalchemy(database_url: str) -> str:

    for prefixo in ("postgresql://", "postgres://"):
        if database_url.startswith(prefixo):
            return "postgresql+psycopg2://" + database_url[len(prefixo):]
    return database_url

def criar_app_db(database_url: str) -> Flask:
    app = Flask("esqueceramai_db")
    app.config["SQLALCHEMY_DATABASE_URI"] = url_sqlalchemy(database_url)
    db.init_app(app)
    return app
