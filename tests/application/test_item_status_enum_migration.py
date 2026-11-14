import os
import uuid
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from application import domain
from application import models

ADMIN_URL = os.getenv("MIGRATION_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="defina MIGRATION_TEST_DATABASE_URL para testar no PostgreSQL")

def _values(engine):
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT unnest(enum_range(NULL::item_status))::text"))]

def test_legacy_enum_gains_delivered_in_order_and_is_idempotent(monkeypatch):
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    name = f"esq_enum_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    target = create_engine(make_url(ADMIN_URL).set(database=name))
    try:
        with target.begin() as conn:  # enum como era antes do status "Entregue"
            conn.execute(text("CREATE TYPE item_status AS ENUM ('OPEN','RESERVED','RETURNED','ARCHIVED')"))
        monkeypatch.setattr(models, "engine", target)

        models._sync_item_status_enum()
        assert _values(target) == list(domain.STATUSES)
        models._sync_item_status_enum()  # segunda subida: nada a fazer
        assert _values(target) == list(domain.STATUSES)
    finally:
        target.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()