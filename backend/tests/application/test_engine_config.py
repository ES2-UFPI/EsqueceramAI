"""O engine não pode deixar o psycopg 3 preparar statements.

O pooler do Supabase reaproveita a sessão do PostgreSQL entre conexões lógicas,
então o nome `_pg3_0` de um prepared statement já existe quando outro worker
prepara o mesmo SQL — e o worker morre no boot com DuplicatePreparedStatement.
"""
from sqlalchemy.engine import make_url

from application import models


def test_sqlite_keeps_check_same_thread(app):
    assert models.engine.dialect.name == "sqlite"
    assert models._CONNECT_ARGS == {"check_same_thread": False}


def test_psycopg3_disables_statement_preparation():
    # a decisão é feita na importação, a partir do DATABASE_URL em uso
    url = make_url("postgresql://u:p@pooler.supabase.com:5432/postgres")
    assert url.get_backend_name() == "postgresql"
    assert url.drivername in ("postgresql", "postgresql+psycopg")

    if models._PSYCOPG3:
        assert models._CONNECT_ARGS == {"prepare_threshold": None}
