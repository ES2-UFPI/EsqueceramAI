"""US09 - notificação automática de correspondência (score mínimo, template, idempotência e decisão)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from application.models import CollectionPoint, Item, Match, MatchNotification, User, db
from application.repositories.users import find_user_by_email
from application.services import matching_service
from conftest import persona_client

LOST_TITLE = "Mochila Nike cinza perdida na biblioteca central"
FOUND_TITLE = "Mochila Nike cinza encontrada na biblioteca central"


@pytest.fixture()
def make_pair(app):
    """Cria um par perdido/encontrado quase idêntico e devolve uma fábrica de itens."""
    owner = db.execute(select(User).where(User.email == "carlos@ufpi.edu.br")).scalar_one()
    finder = db.execute(select(User).where(User.email == "operador@ufpi.edu.br")).scalar_one()
    point = db.execute(select(CollectionPoint)).scalars().first()
    made = []

    def _make(*, title, kind):
        row = Item(user_id=(owner if kind == "LOST" else finder).id, type=kind, category="ELECTRONIC",
                   title=title, description="Mochila cinza Nike com caderno e chaveiro azul dentro.",
                   color="Cinza", brand="Nike", location="Biblioteca Central",
                   occurred_at=datetime.now(timezone.utc) - timedelta(hours=2),
                   point_id=point.id if point and kind == "FOUND" else None)
        db.add(row)
        db.commit()
        made.append(row.id)
        return row.id

    yield _make
    for item_id in made:
        match_ids = [m.id for m in db.scalars(select(Match).where(
            (Match.lost_item_id == item_id) | (Match.found_item_id == item_id)))]
        if match_ids:
            db.query(MatchNotification).filter(MatchNotification.match_id.in_(match_ids)).delete(synchronize_session=False)
            db.query(Match).filter(Match.id.in_(match_ids)).delete(synchronize_session=False)
        db.delete(db.get(Item, item_id))
    db.commit()


@pytest.fixture()
def own_threshold(monkeypatch):
    """Permite forçar o limiar de notificação sem afetar o limiar de sugestão."""
    def _set(value):
        monkeypatch.setattr(matching_service, "NOTIFICATION_THRESHOLD", value)
    return _set


def _make_pair(make_pair):
    return make_pair(title=LOST_TITLE, kind="LOST"), make_pair(title=FOUND_TITLE, kind="FOUND")


def _match(lost_id, found_id):
    return db.execute(select(Match).where(Match.lost_item_id == lost_id,
                                          Match.found_item_id == found_id)).scalar_one()


# ------------------------------------------------------------------ gatilho
def test_score_alto_envia_email_com_link_do_card(make_pair, _capture_emails):
    lost_id, found_id = _make_pair(make_pair)
    matching_service.generate_matches_for_item(found_id)

    match = _match(lost_id, found_id)
    assert match.score >= matching_service.NOTIFICATION_THRESHOLD
    email = next(e for e in _capture_emails if LOST_TITLE in e["body"])
    assert email["to"] == "carlos@ufpi.edu.br"
    assert f"/correspondencias/{match.id}" in email["body"]
    assert f"/correspondencias/{match.id}" in email["html"]
    assert f"{match.score}%" in email["subject"]
    ledger = db.execute(select(MatchNotification).where(MatchNotification.match_id == match.id)).scalars().all()
    assert [(n.user_id, n.status) for n in ledger] == [(find_user_by_email("carlos@ufpi.edu.br").id, "SENT")]


def test_score_baixo_cria_sugestao_mas_nao_envia_email(make_pair, _capture_emails, own_threshold):
    own_threshold(100)  # o placar é limitado a 99: nenhum par alcança o limiar
    lost_id, found_id = _make_pair(make_pair)
    matching_service.generate_matches_for_item(found_id)

    assert _match(lost_id, found_id)
    assert _capture_emails == []
    assert db.execute(select(MatchNotification).where(MatchNotification.match_id == _match(lost_id, found_id).id)).scalars().all() == []


def test_descricao_diferente_nao_alcanca_o_limiar_padrao(make_pair, _capture_emails):
    matching_service.generate_matches_for_item(make_pair(title="Mochila Nike encontrada", kind="FOUND"))
    assert matching_service.NOTIFICATION_THRESHOLD == 75
    assert not [e for e in _capture_emails if "Mochila Nike encontrada" in e["body"]]


# ------------------------------------------------------------- idempotência
def test_reprocessar_nao_duplica_o_email(make_pair, _capture_emails):
    _, found_id = _make_pair(make_pair)
    matching_service.generate_matches_for_item(found_id)
    matching_service.generate_matches_for_item(found_id)

    assert len([e for e in _capture_emails if LOST_TITLE in e["body"]]) == 1


def test_reserva_repetida_do_mesmo_aviso_falha(make_pair):
    lost_id, found_id = _make_pair(make_pair)
    matching_service.generate_matches_for_item(found_id)
    match = _match(lost_id, found_id)
    user_id = find_user_by_email("carlos@ufpi.edu.br").id

    from application.repositories.engagement import claim_match_notification
    assert claim_match_notification(match_id=match.id, user_id=user_id, channel="EMAIL") is False


def test_falha_de_smtp_fica_registrada_e_pode_ser_reenviada(make_pair, monkeypatch, _capture_emails):
    from application.delivery import email_service
    lost_id, found_id = _make_pair(make_pair)
    state = {"attempts": 0}

    def flaky(to, subject, body, html_body=None):
        state["attempts"] += 1
        if state["attempts"] == 1:
            raise email_service.EmailError("SMTP fora do ar")
        _capture_emails.append({"to": to, "subject": subject, "body": body, "html": html_body})
        return "console"
    monkeypatch.setattr(email_service, "send_email", flaky)

    matching_service.generate_matches_for_item(found_id)
    match = _match(lost_id, found_id)
    failed = db.execute(select(MatchNotification).where(MatchNotification.match_id == match.id)).scalar_one()
    assert failed.status == "FAILED" and "SMTP fora do ar" in failed.error

    matching_service.generate_matches_for_item(found_id)  # próxima execução tenta de novo
    assert db.execute(select(MatchNotification).where(MatchNotification.match_id == match.id)).scalar_one().status == "SENT"
    assert state["attempts"] == 2


# ------------------------------------------------------------- decisão do usuário
def test_pagina_do_aviso_permite_confirmar(app, make_pair):
    lost_id, found_id = _make_pair(make_pair)
    match = matching_service.upsert_match(lost_item_id=lost_id, found_item_id=found_id, score=90, reasons=["Mesma cor"])
    client = persona_client(app, "carlos@ufpi.edu.br")

    page = client.get(f"/correspondencias/{match.id}").get_data(as_text=True)
    assert FOUND_TITLE in page and "É o meu item, confirmar" in page

    assert client.patch(f"/api/matches/{match.id}", json={"action": "confirm"}).status_code == 200
    assert db.get(Match, match.id).status == "CONFIRMED"
    assert "Correspondência já respondida" in client.get(f"/correspondencias/{match.id}").get_data(as_text=True)


def test_pagina_do_aviso_permite_rejeitar_o_falso_positivo(app, make_pair):
    lost_id, found_id = _make_pair(make_pair)
    match = matching_service.upsert_match(lost_item_id=lost_id, found_item_id=found_id, score=90, reasons=["Mesma cor"])
    client = persona_client(app, "carlos@ufpi.edu.br")

    assert client.patch(f"/api/matches/{match.id}", json={"action": "reject"}).status_code == 200
    assert db.get(Match, match.id).status == "REJECTED"


def test_visitante_ve_o_item_mas_precisa_entrar_para_responder(app, make_pair):
    lost_id, found_id = _make_pair(make_pair)
    match = matching_service.upsert_match(lost_item_id=lost_id, found_item_id=found_id, score=90, reasons=["Mesma cor"])

    page = app.test_client().get(f"/correspondencias/{match.id}").get_data(as_text=True)
    assert FOUND_TITLE in page
    assert f"/entrar?next=/correspondencias/{match.id}" in page
    assert "É o meu item, confirmar" not in page


def test_outro_usuario_nao_pode_decidir(app, make_pair):
    lost_id, found_id = _make_pair(make_pair)
    match = matching_service.upsert_match(lost_item_id=lost_id, found_item_id=found_id, score=90, reasons=["Mesma cor"])
    client = persona_client(app, "maria@ufpi.edu.br")

    assert client.patch(f"/api/matches/{match.id}", json={"action": "confirm"}).status_code == 403
    assert db.get(Match, match.id).status == "PENDING"
