import logging
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from application import domain
from application.jobs import stale_items
from application.models import CLAIM_BLOCKED, CLAIM_PENDING, CLAIM_VERIFIED, CollectionPoint, Item, ItemClaim, ItemEvent, User, db
from application.repositories.engagement import list_item_events
from application.repositories.items import set_item_status
from application.services import retention_service
from conftest import persona_client

DISPOSAL = domain.DISPOSAL_STATUS

@pytest.fixture()
def stock(app, monkeypatch):
    monkeypatch.delenv("STORAGE_RETENTION_DAYS", raising=False)
    owner_id = db.execute(select(User).where(User.email == "carlos@ufpi.edu.br")).scalar_one().id
    point_id = db.execute(select(CollectionPoint)).scalars().first().id
    now = datetime.now(timezone.utc)
    made = []

    def _make(*, age, kind="FOUND", status="OPEN", with_point=True, demo=False):
        entered = now - age
        item = Item(user_id=owner_id, type=kind, category="ELECTRONIC", title=f"Item auditado {len(made) + 1}",
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

def _status(item_id):
    row = db.get(Item, item_id)
    db.refresh(row)
    return row.status

def _events(item_id):
    return list(db.execute(select(ItemEvent).where(ItemEvent.item_id == item_id).order_by(ItemEvent.id)).scalars())

def _apply(stock, **kw):
    return retention_service.run_daily_check(now=stock.now, apply=True, **kw)

def test_overdue_item_becomes_available_for_disposal_with_an_audit_event(stock):
    item_id = stock(age=timedelta(days=120))
    report = _apply(stock)
    assert item_id in report["updated"] and report["applied"] is True
    assert _status(item_id) == DISPOSAL
    (event,) = _events(item_id)
    assert event.status == DISPOSAL
    assert event.actor_id is None  # ação do sistema, não de uma pessoa
    for part in ("120 dias", "90 dias", domain.STATUS_LABEL["OPEN"], domain.STATUS_LABEL[DISPOSAL]):
        assert part in event.note

def test_audit_event_shows_in_the_item_timeline_as_a_system_action(stock):
    item_id = stock(age=timedelta(days=120))
    _apply(stock)
    latest = list_item_events(item_id)[0]
    assert latest["status"] == DISPOSAL and latest["actorName"] is None

def test_audit_line_goes_to_the_system_log(stock, caplog):
    item_id = stock(age=timedelta(days=120))
    with caplog.at_level(logging.INFO, logger="esqueceram.audit"):
        _apply(stock)
    lines = [r.getMessage() for r in caplog.records if r.name == "esqueceram.audit"]
    mine = [m for m in lines if domain.item_code(item_id) in m]
    assert len(mine) == 1
    assert f"from=OPEN to={DISPOSAL}" in mine[0] and "actor=system" in mine[0] and "days_stored=120" in mine[0]

@pytest.mark.parametrize("override", [
    {"kind": "LOST"}, {"with_point": False}, {"status": "RESERVED"}, {"status": "RETURNED"},
    {"status": "DELIVERED"}, {"status": "ARCHIVED"}, {"demo": True},
], ids=["perdido", "sem-ponto", "reservado", "devolvido", "entregue", "arquivado", "demo"])
def test_ineligible_items_get_no_status_change_and_no_event(stock, override):
    item_id = stock(age=timedelta(days=200), **override)
    before = _status(item_id)
    _apply(stock)
    assert _status(item_id) == before
    assert _events(item_id) == []

@pytest.mark.parametrize("claim_status, expired", [(CLAIM_PENDING, False), (CLAIM_VERIFIED, False), (CLAIM_BLOCKED, True)])
def test_only_unclaimed_items_expire(stock, claim_status, expired):
    item_id = stock(age=timedelta(days=120))
    claimant = db.execute(select(User).where(User.email == "operador@ufpi.edu.br")).scalar_one()
    claim = ItemClaim(item_id=item_id, claimant_id=claimant.id, status=claim_status)
    db.add(claim)
    db.commit()
    _apply(stock)
    assert (_status(item_id) == DISPOSAL) is expired
    assert len(_events(item_id)) == (1 if expired else 0)

def test_item_within_the_retention_period_is_untouched(stock):
    exactly, recent = stock(age=timedelta(days=90)), stock(age=timedelta(days=89))
    _apply(stock)
    assert [_status(exactly), _status(recent)] == ["OPEN", "OPEN"]
    assert _events(exactly) == [] and _events(recent) == []

def test_second_run_does_not_repeat_the_change_or_the_event(stock):
    item_id = stock(age=timedelta(days=120))
    _apply(stock)
    second = _apply(stock)
    assert item_id not in second["updated"] and item_id not in {i["id"] for i in second["items"]}
    assert len(_events(item_id)) == 1

def test_default_check_stays_read_only(stock):
    item_id = stock(age=timedelta(days=120))
    report = retention_service.run_daily_check(now=stock.now)
    assert report["applied"] is False and report["updated"] == []
    assert _status(item_id) == "OPEN" and _events(item_id) == []

def test_event_failure_rolls_back_the_status_and_does_not_stop_the_other_items(stock, monkeypatch, caplog):
    bad = stock(age=timedelta(days=300))  # o mais antigo é processado primeiro
    good = stock(age=timedelta(days=100))
    real = retention_service.add_item_event

    def flaky(**kw):
        if kw["item_id"] == bad:
            raise RuntimeError("falha simulada")
        return real(**kw)
    monkeypatch.setattr(retention_service, "add_item_event", flaky)
    with caplog.at_level(logging.INFO, logger="esqueceram.audit"):
        report = _apply(stock)
    assert bad in report["failed"] and good in report["updated"]
    assert _status(bad) == "OPEN" and _events(bad) == []
    assert _status(good) == DISPOSAL and len(_events(good)) == 1
    audited = " ".join(r.getMessage() for r in caplog.records if r.name == "esqueceram.audit")
    assert domain.item_code(bad) not in audited and domain.item_code(good) in audited

def test_item_that_changed_during_the_run_is_not_overwritten(stock):
    item_id = stock(age=timedelta(days=120))
    items = retention_service.find_overdue_items(now=stock.now)
    set_item_status(item_id, "RESERVED")  # retirada iniciada depois da consulta
    outcome = retention_service.expire_overdue_items(items, 90)
    assert item_id in outcome["skipped"] and item_id not in outcome["updated"]
    assert _status(item_id) == "RESERVED" and _events(item_id) == []

def test_cli_applies_by_default_and_dry_run_only_lists(stock, capsys):
    dry = stock(age=timedelta(days=120))
    assert stale_items.main(["--dry-run", "--json"]) == 0
    assert _status(dry) == "OPEN" and _events(dry) == []
    assert '"applied": false' in capsys.readouterr().out
    assert stale_items.main(["--json"]) == 0
    assert '"applied": true' in capsys.readouterr().out
    assert _status(dry) == DISPOSAL and len(_events(dry)) == 1

def test_cli_exits_with_1_when_an_item_cannot_be_updated(stock, monkeypatch):
    item_id = stock(age=timedelta(days=120))

    def boom(**_kw):
        raise RuntimeError("falha simulada")
    monkeypatch.setattr(retention_service, "add_item_event", boom)
    assert stale_items.main([]) == 1
    assert _status(item_id) == "OPEN"

def test_items_available_for_disposal_stay_in_the_disposal_panel(stock):
    item_id = stock(age=timedelta(days=120))
    _apply(stock)
    assert item_id in {i["id"] for i in retention_service.filter_disposal_candidates(now=stock.now)}

def test_new_status_is_valid_in_the_api_and_the_pages(app, stock):
    item_id = stock(age=timedelta(days=120))
    _apply(stock)
    staff = persona_client(app, "operador@ufpi.edu.br")
    listed = staff.get("/api/itens?status=DISPONIVEL_DESCARTE")
    assert listed.status_code == 200 and item_id in {i["id"] for i in listed.get_json()}
    detail = staff.get(f"/itens/{item_id}")
    assert detail.status_code == 200 and domain.STATUS_LABEL[DISPOSAL] in detail.get_data(as_text=True)
    assert staff.get(f"/painel/itens?status={DISPOSAL}").status_code == 200

def test_staff_can_set_the_new_status_manually_through_the_api(app, stock):
    item_id = stock(age=timedelta(days=10))
    staff = persona_client(app, "operador@ufpi.edu.br")
    r = staff.patch(f"/api/items/{item_id}", json={"status": DISPOSAL})
    assert r.status_code == 200, r.get_json()
    assert _status(item_id) == DISPOSAL
