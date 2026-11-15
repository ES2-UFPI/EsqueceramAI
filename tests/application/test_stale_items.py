import json
import logging
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from application import domain
from application.jobs import stale_items
from application.models import CollectionPoint, Item, User, db
from application.services import retention_service

@pytest.fixture()
def stock(app, monkeypatch):
    monkeypatch.delenv("STORAGE_RETENTION_DAYS", raising=False)
    owner_id = db.execute(select(User).where(User.email == "carlos@ufpi.edu.br")).scalar_one().id
    point_id = db.execute(select(CollectionPoint)).scalars().first().id
    now = datetime.now(timezone.utc)
    made = []

    def _make(*, age, kind="FOUND", status="OPEN", with_point=True, demo=False):
        entered = now - age
        item = Item(user_id=owner_id, type=kind, category="ELECTRONIC", title=f"Item armazenado {len(made) + 1}",
                    description="Descrição longa o suficiente para o teste.", location="Biblioteca Central",
                    status=status, occurred_at=entered, point_id=point_id if with_point else None,
                    is_demo=demo, created_at=entered, updated_at=entered)
        db.add(item)
        db.commit()
        made.append(item.id)
        return item.id
    _make.now = now
    yield _make
    for item_id in made:
        row = db.get(Item, item_id)
        if row:
            db.delete(row)
    db.commit()

def _ids(items):
    return {i["id"] for i in items}

def test_lists_found_item_stored_at_a_point_for_more_than_90_days(stock):
    item_id = stock(age=timedelta(days=91))
    found = {i["id"]: i for i in retention_service.find_overdue_items(now=stock.now)}
    assert item_id in found
    assert found[item_id]["daysStored"] == 91
    assert found[item_id]["code"] == domain.item_code(item_id)
    assert found[item_id]["pointName"]

def test_exactly_90_days_is_not_overdue_yet(stock):
    exactly = stock(age=timedelta(days=90))
    recent = stock(age=timedelta(days=89))
    assert not {exactly, recent} & _ids(retention_service.find_overdue_items(now=stock.now))

@pytest.mark.parametrize("override", [
    {"kind": "LOST"},                    # perdido não fica sob custódia do ponto
    {"with_point": False},               # sem ponto de coleta não está armazenado
    {"status": "RESERVED"},              # retirada em andamento
    {"status": "RETURNED"},
    {"status": "DELIVERED"},
    {"status": "ARCHIVED"},
    {"demo": True},                      # dataset demonstrativo nunca entra na rotina
], ids=["perdido", "sem-ponto", "reservado", "devolvido", "entregue", "arquivado", "demo"])
def test_ineligible_items_are_ignored_even_when_old(stock, override):
    item_id = stock(age=timedelta(days=200), **override)

    assert item_id not in _ids(retention_service.find_overdue_items(now=stock.now))

def test_overdue_items_come_oldest_first(stock):
    newer = stock(age=timedelta(days=100))
    oldest = stock(age=timedelta(days=300))
    middle = stock(age=timedelta(days=150))
    ordered = [i["id"] for i in retention_service.find_overdue_items(now=stock.now) if i["id"] in (newer, oldest, middle)]
    assert ordered == [oldest, middle, newer]

def test_days_argument_overrides_the_default(stock):
    item_id = stock(age=timedelta(days=40))
    assert item_id not in _ids(retention_service.find_overdue_items(now=stock.now))
    assert item_id in _ids(retention_service.find_overdue_items(now=stock.now, days=30))

def test_env_var_sets_the_retention_period(stock, monkeypatch):
    item_id = stock(age=timedelta(days=40))
    monkeypatch.setenv("STORAGE_RETENTION_DAYS", "30")
    report = retention_service.run_daily_check(now=stock.now)
    assert report["retentionDays"] == 30
    assert item_id in _ids(report["items"])

@pytest.mark.parametrize("raw", ["abc", "0", "-5", "1.5"])
def test_invalid_retention_period_fails_loudly(raw):
    with pytest.raises(ValueError):
        domain.parse_retention_days(raw)

@pytest.mark.parametrize("raw", [None, "", "  "])
def test_blank_retention_period_falls_back_to_90_days(raw):
    assert domain.parse_retention_days(raw) == 90

def test_report_summarises_the_check_and_logs_each_overdue_item(stock, caplog):
    item_id = stock(age=timedelta(days=120))
    with caplog.at_level(logging.INFO, logger="esqueceram.retention"):
        report = retention_service.run_daily_check(now=stock.now)
    assert report["checkedAt"] == stock.now
    assert report["retentionDays"] == 90
    assert report["total"] == len(report["items"])
    assert item_id in _ids(report["items"])
    assert domain.item_code(item_id) in caplog.text

def test_check_is_read_only(stock):
    item_id = stock(age=timedelta(days=120))
    before = db.get(Item, item_id)
    status, updated_at = before.status, before.updated_at
    retention_service.run_daily_check(now=stock.now)
    after = db.get(Item, item_id)
    assert (after.status, after.updated_at) == (status, updated_at)

def test_cli_prints_the_json_report(stock, capsys):
    item_id = stock(age=timedelta(days=120))
    assert stale_items.main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["retentionDays"] == 90
    assert report["total"] == len(report["items"])
    assert item_id in _ids(report["items"])

def test_cli_days_flag(stock, capsys):
    item_id = stock(age=timedelta(days=40))
    assert stale_items.main(["--days", "30", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["retentionDays"] == 30
    assert item_id in _ids(report["items"])

def test_cli_exits_with_1_when_the_check_fails(monkeypatch):
    def boom(**_kw):
        raise RuntimeError("banco indisponível")
    monkeypatch.setattr(stale_items, "run_daily_check", boom)
    assert stale_items.main([]) == 1

def test_cli_argparse_errors_exit_with_1_and_help_with_0():
    assert stale_items.main(["--days", "abc"]) == 1
    assert stale_items.main(["--help"]) == 0