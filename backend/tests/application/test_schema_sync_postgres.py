"""A sincronização de colunas no PostgreSQL, que é o dialeto de produção.

O default booleano é o ponto delicado: `Boolean` não aceita `0` sem aspas, e o
modelo declara `server_default="0"`.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from application import models
from application.models import Base, Item, User, utcnow

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
        with Session(target) as s:  # linha antiga, gravada antes da coluna existir
            dono = User(name="Dono", email="dono@ufpi.edu.br", password_hash="x", role="USER")
            s.add(dono)
            s.flush()
            s.add(Item(user_id=dono.id, type="FOUND", category="ELECTRONIC", title="Achado",
                       description="com detalhe", location="Biblioteca", occurred_at=utcnow(), status="OPEN"))
            s.commit()
        with target.begin() as conn:  # tabela como estava em produção
            conn.execute(text("ALTER TABLE items DROP COLUMN is_demo"))
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
