from types import SimpleNamespace

from application import models


def test_init_db_uses_advisory_lock_on_postgres(monkeypatch):
    executed = []

    class FakeConn:
        def execute(self, stmt, *args, **kwargs):
            executed.append(str(stmt))

        def commit(self):
            executed.append("COMMIT")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    fake_engine = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        connect=lambda: FakeConn(),
    )
    monkeypatch.setattr(models, "engine", fake_engine)
    monkeypatch.setattr(models.Base.metadata, "create_all", lambda bind: executed.append("CREATE_ALL"))
    monkeypatch.setattr(models, "_sync_missing_columns", lambda: executed.append("SYNC_COLS"))
    monkeypatch.setattr(models, "_sync_item_status_enum", lambda: executed.append("SYNC_ENUM"))

    models.init_db()

    assert executed[0] == f"SELECT pg_advisory_lock({models._INIT_DB_LOCK_ID})"
    assert "CREATE_ALL" in executed
    assert "SYNC_COLS" in executed
    assert "SYNC_ENUM" in executed
    assert f"SELECT pg_advisory_unlock({models._INIT_DB_LOCK_ID})" in executed
    assert executed.index(f"SELECT pg_advisory_lock({models._INIT_DB_LOCK_ID})") < executed.index("CREATE_ALL")
    assert executed.index("CREATE_ALL") < executed.index(f"SELECT pg_advisory_unlock({models._INIT_DB_LOCK_ID})")
