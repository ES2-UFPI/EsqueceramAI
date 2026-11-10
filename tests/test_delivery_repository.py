import pytest
from sqlalchemy import select, text

from app.delivery import models as m
from app.delivery import repository as repo
from app.models import Item, User, db


def _user(email):
    return db.execute(select(User).where(User.email == email)).scalar_one()


def _delivery(**over):
    base = dict(item_id=None, item_code="ESQ-00001", item_title="Fone", point_name="Biblioteca", attendant_id=None,
                attendant_name="Renata", attendant_registration="ATD-1", recipient_name="Maria Souza",
                recipient_cpf_hash="a" * 64, recipient_cpf_masked="***.982.247-**", recipient_email="m@x.com")
    return repo.create_delivery(**{**base, **over})


def test_tables_created_without_touching_existing_ones(app):
    tables = {r[0] for r in db.execute(text("select name from sqlite_master where type='table'"))}
    assert {"attendant_profiles", "deliveries", "delivery_documents", "delivery_receipts", "delivery_events"} <= tables
    assert {"users", "items", "matches", "notifications"} <= tables
    cols = {r[1] for r in db.execute(text("pragma table_info(users)"))}
    assert "registration_number" not in cols  # tabela de usuários continua intacta


@pytest.fixture()
def clean_registrations(app):
    yield
    db.query(m.AttendantProfile).delete()
    db.commit()


def test_registration_set_update_and_unique(app, clean_registrations):
    op, admin = _user("operador@ufpi.edu.br"), _user("admin@ufpi.edu.br")
    repo.set_registration(op.id, "REG-TESTE-1")
    assert repo.get_registration(op.id) == "REG-TESTE-1"
    repo.set_registration(op.id, "REG-TESTE-2")
    assert repo.get_registration(op.id) == "REG-TESTE-2"
    with pytest.raises(repo.RegistrationTaken):
        repo.set_registration(admin.id, "REG-TESTE-2")
    assert repo.get_registration(admin.id) is None


def test_delivery_lifecycle_document_receipt_events(app):
    d = _delivery()
    assert d.status == m.PENDING and d.code_attempts == 0
    repo.save_document(d.id, mime_type="image/png", size_bytes=3, sha256="b" * 64, data=b"abc")
    repo.save_receipt(d.id, verification_code="ABCDE", sha256="c" * 64, pdf=b"%PDF-")
    repo.add_event(d.id, "CREATED", "teste")
    repo.add_event(d.id, "CONFIRMED")
    assert repo.get_document(d.id).data == b"abc"
    assert repo.get_receipt(d.id).pdf == b"%PDF-"
    assert [e.action for e in repo.list_events(d.id)] == ["CREATED", "CONFIRMED"]
    assert d.id in [x.id for x in repo.list_deliveries()]


def test_snapshot_survives_item_deletion(app):
    owner = _user("carlos@ufpi.edu.br")
    item = Item(user_id=owner.id, type="FOUND", category="ACCESSORY", title="Chave", description="x" * 20,
                location="CT", occurred_at=owner.created_at)
    db.add(item); db.commit()
    d = _delivery(item_id=item.id, item_title="Chave")
    assert [x.id for x in repo.deliveries_for_item(item.id)] == [d.id]
    db.delete(item); db.commit(); db.expire_all()
    kept = repo.get_delivery(d.id)
    assert kept is not None and kept.item_id is None and kept.item_title == "Chave"
