from sqlalchemy.exc import IntegrityError

from application import models


def test_init_db_handles_concurrent_create_all_race(monkeypatch):
    calls = []

    def fake_create_all(bind):
        calls.append("CREATE_ALL")
        raise IntegrityError("CREATE TABLE ...", {}, Exception("pg_class_relname_nsp_index"))

    monkeypatch.setattr(models.Base.metadata, "create_all", fake_create_all)
    monkeypatch.setattr(models, "_sync_missing_columns", lambda: calls.append("SYNC_COLS"))
    monkeypatch.setattr(models, "_sync_item_status_enum", lambda: calls.append("SYNC_ENUM"))

    models.init_db()

    assert calls == ["CREATE_ALL", "SYNC_COLS", "SYNC_ENUM"]
