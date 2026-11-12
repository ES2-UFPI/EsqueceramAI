"""A sincronização de colunas no PostgreSQL, que é o dialeto de produção.

O default booleano é o ponto delicado: `Boolean` não aceita `0` sem aspas, e o
modelo declara `server_default="0"`.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from application import models
from application.models import Base

ADMIN_URL = os.getenv("MIGRATION_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="defina MIGRATION_TEST_DATABASE_URL para testar no PostgreSQL")


def test_missing_boolean_column_is_added_with_a_working_default(monkeypatch):
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    name = f"esq_col_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    target = create_engine(make_url(ADMIN_URL).set(database=name))
    try:
        models.Base.metadata.create_all(target)
        with target.begin() as conn:  # tabela de antes do campo existir
            conn.execute(text("ALTER TABLE items DROP COLUMN is_demo"))
            conn.execute(text("INSERT INTO users (name, email, password_hash, role) "
                              "VALUES ('Dono', 'dono@ufpi.edu.br', 'x', 'USUARIO')"))
            conn.execute(text("INSERT INTO items (user_id, type, category, title, description, attributes, "
                              "location, occurred_at, status) VALUES (1, 'FOUND', 'ELECTRONIC', 'Achado', "
                              "'com detalhe', '{}', 'Biblioteca', now(), 'OPEN')"))
        monkeypatch.setattr(models, "engine", target)

        models.init_db()

        assert "is_demo" in {c["name"] for c in inspect(target).get_columns("items")}
        with target.connect() as conn:  # a linha antiga recebe o default
            assert conn.execute(text("SELECT is_demo FROM items")).scalar_one() is False
        models.init_db()  # idempotente
    finally:
        target.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
