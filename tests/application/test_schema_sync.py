import pytest
from sqlalchemy import inspect, text

from application import models
from application.models import Base


@pytest.fixture()
def banco(app):
    return models.engine


def _colunas(engine, tabela):
    return {c["name"] for c in inspect(engine).get_columns(tabela)}


def test_init_db_adds_column_missing_from_an_existing_table(banco):
    with banco.begin() as conn:
        conn.execute(text("ALTER TABLE items DROP COLUMN is_demo"))
    assert "is_demo" not in _colunas(banco, "items")

    models.init_db()

    assert "is_demo" in _colunas(banco, "items")
    with banco.connect() as conn:
        conn.execute(text("SELECT lost_item.is_demo FROM items AS lost_item LIMIT 1"))


def test_init_db_is_idempotent_when_schema_is_complete(banco):
    models.init_db()
    antes = sorted(_colunas(banco, "items"))

    models.init_db()

    assert sorted(_colunas(banco, "items")) == antes


def test_every_model_column_exists_after_init_db(banco):
    models.init_db()
    for table in Base.metadata.sorted_tables:
        faltando = {c.name for c in table.columns} - _colunas(banco, table.name)
        assert not faltando, f"{table.name} sem as colunas {faltando}"
