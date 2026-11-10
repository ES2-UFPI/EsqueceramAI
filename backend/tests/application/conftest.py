"""Fixtures de teste: banco SQLite temporário isolado (definido ANTES de importar a aplicação)."""
import os
import tempfile
import sys
from pathlib import Path

# Os testes vivem dentro de ``backend/tests``; disponibiliza o pacote do
# backend sem depender do diretório em que o pytest foi chamado.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_tmp = tempfile.mkdtemp(prefix="esqueceram-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SECRET_KEY"] = "test-secret"
for var in ("SMTP_HOST", "EMAIL_BACKEND", "DELIVERY_REQUIRE_CHECKOUT", "DEMO_LOGIN_DISABLED"):
    os.environ.pop(var, None)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def app():
    from application import create_app
    application = create_app()
    application.config["TESTING"] = True
    application.test_client().get("/api/health")  # popula o seed demonstrativo
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------- helpers de entrega
import io  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-" * 20
VALID_CPF = "529.982.247-25"


def persona_client(app, email):
    c = app.test_client()
    assert c.post("/api/auth/demo", json={"persona": email}).status_code == 200
    return c


@pytest.fixture()
def attendant(app):
    """Cliente logado como atendente (operador) com matrícula cadastrada."""
    c = persona_client(app, "operador@ufpi.edu.br")
    assert c.put("/api/attendant/registration", json={"registrationNumber": "ATD-2024-0117"}).status_code == 200
    return c


@pytest.fixture()
def make_item(app):
    from sqlalchemy import select
    from application.models import CollectionPoint, Item, User, db
    counter = {"n": 0}

    def _make(*, kind="FOUND", status="OPEN", with_point=True, owner="carlos@ufpi.edu.br"):
        counter["n"] += 1
        owner_row = db.execute(select(User).where(User.email == owner)).scalar_one()
        point = db.execute(select(CollectionPoint)).scalars().first() if with_point else None
        item = Item(user_id=owner_row.id, type=kind, category="ELECTRONIC", title=f"Item de teste {counter['n']}",
                    description="Descrição longa o suficiente para o teste.", location="Biblioteca Central", status=status,
                    occurred_at=datetime.now(timezone.utc) - timedelta(days=1), point_id=point.id if point else None)
        db.add(item)
        db.commit()
        return item.id
    return _make


@pytest.fixture()
def sent_codes(monkeypatch):
    """Captura o código "enviado por e-mail" (em vez de depender do console/SMTP)."""
    from application.delivery import service
    box = []

    def fake(**kw):
        box.append(kw)
        return "console"
    monkeypatch.setattr(service, "send_confirmation_code", fake)
    return box


def delivery_form(item_id, **over):
    data = {"itemId": str(item_id), "recipientName": "Maria de Sousa Lima", "cpf": VALID_CPF,
            "email": "maria@exemplo.com", "document": (io.BytesIO(JPEG), "rg.jpg", "image/jpeg")}
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


def start(client, item_id, **over):
    return client.post("/api/deliveries", data=delivery_form(item_id, **over), content_type="multipart/form-data")
