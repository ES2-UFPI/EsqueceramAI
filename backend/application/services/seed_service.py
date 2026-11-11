"""Dataset demonstrativo idempotente (src/server/services/seed-service.ts).

Roda uma vez em banco vazio e nunca sobrescreve dados reais.
"""
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from application.auth import hash_password
from application.models import User, db
from application.repositories.engagement import add_item_event, create_notification, list_matches
from application.repositories.items import count_items, create_item, find_item_by_id, set_item_status
from application.repositories.points import count_points, create_point
from application.repositories.users import add_user_score, create_user, find_user_by_email
from application.services.matching_service import decide_match, generate_matches_for_item

DEMO_PASSWORD = "esqueceram123"
DEMO_PASSWORD_HINT = DEMO_PASSWORD


def _px(pid, name="", w=1200, h=627):
    return f"https://images.pexels.com/photos/{pid}/{name or 'pexels-photo-' + str(pid) + '.jpeg'}?auto=compress&cs=tinysrgb&fit=crop&h={h}&w={w}"


IMAGES = {
    "tech": _px(999661), "headphones": _px(8003585), "keys": _px(1416844), "wallet": _px(9053308),
    "bag": _px(412440), "desk": _px(5531408), "campus": _px(31039028),
    "phone": _px(6159, "smartphone-technology-phone-screen.jpg"),
}


def _days_ago(days, hours=10):
    d = datetime.now(timezone.utc) - timedelta(days=days)
    return d.replace(hour=hours, minute=0, second=0, microsecond=0)


@contextmanager
def _quiet_match_emails():
    """O dataset demonstrativo não deve disparar e-mails reais: as sugestões continuam no painel."""
    from application.services import matching_service
    previous = matching_service.NOTIFICATION_THRESHOLD
    matching_service.NOTIFICATION_THRESHOLD = 100  # acima do placar máximo (99)
    try:
        yield
    finally:
        matching_service.NOTIFICATION_THRESHOLD = previous


def _p(key, name, email, phone, role, score, label, description, persona=False):
    return {"key": key, "name": name, "email": email, "phone": phone, "role": role, "score": score,
            "label": label, "description": description, "persona": persona}


DEMO_PEOPLE = [
    _p("ana", "Ana Beatriz Lima", "ana@ufpi.edu.br", "(86) 99911-2233", "USER", 145, "Comunidade",
       "Estudante com itens perdidos e correspondências pendentes.", True),
    _p("carlos", "Carlos Eduardo Rocha", "carlos@ufpi.edu.br", "(86) 98844-7710", "USER", 90, "Comunidade",
       "Estudante que registra itens encontrados.", True),
    _p("maria", "Maria de Sousa", "maria@ufpi.edu.br", "(86) 99622-1188", "USER", 55, "Comunidade", "Estudante da comunidade."),
    _p("joao", "João Pedro Alves", "joao@ufpi.edu.br", "(86) 99433-0021", "USER", 25, "Comunidade", "Estudante da comunidade."),
    _p("lucas", "Lucas Ferreira", "lucas@ufpi.edu.br", "(86) 99277-4455", "USER", 70, "Comunidade", "Estudante da comunidade."),
    _p("renata", "Renata Nunes", "operador@ufpi.edu.br", "(86) 3215-5590", "OPERATOR_POST", 210, "Operador de ponto",
       "Equipe dos pontos de coleta e devoluções.", True),
    _p("marcos", "Marcos Vinícius", "admin@ufpi.edu.br", "(86) 3215-5500", "ADMIN", 320, "Administrador",
       "Gestão de usuários, pontos, categorias e indicadores.", True),
]
DEMO_PERSONAS = [p for p in DEMO_PEOPLE if p["persona"]]
DEMO_ACCOUNTS = [{"role": p["role"], "email": p["email"], "name": p["name"]} for p in DEMO_PERSONAS]

_lock = threading.Lock()
_seeded = False


def ensure_demo_accounts() -> dict[str, int]:
    """Cria contas demo ausentes (idempotente). Retorna {persona: user_id}."""
    ids = {}
    for person in DEMO_PEOPLE:
        existing = find_user_by_email(person["email"])
        if existing:
            ids[person["key"]] = existing.id
            continue
        try:
            created = create_user(name=person["name"], email=person["email"], phone=person["phone"],
                                  password_hash=hash_password(DEMO_PASSWORD), role=person["role"])
            ids[person["key"]] = created.id
            if person["score"]:
                add_user_score(created.id, person["score"])
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            print("[seed] could not create demo account", person["email"], exc)
            retry = find_user_by_email(person["email"])
            if retry:
                ids[person["key"]] = retry.id
    return ids


def _item(owner, type_, category, title, description, location, occurred, **kw):
    return {"owner": owner, "type": type_, "category": category, "title": title, "description": description,
            "location": location, "occurredAt": occurred, **kw}


def _only_demo_data() -> bool:
    """True quando o banco só tem as contas demo (nenhum dado real): é seguro popular o dataset demonstrativo.

    Antes, qualquer usuário existente impedia o seed; assim, o login demo em banco vazio criava as contas
    primeiro e o seed nunca rodava (sem itens nem pontos).
    """
    demo_emails = {p["email"] for p in DEMO_PEOPLE}
    real_user = db.execute(select(User.id).where(User.email.notin_(demo_emails)).limit(1)).first()
    return not (real_user or count_items() or count_points())


def _seed():
    if not _only_demo_data():
        ensure_demo_accounts()  # já existem dados reais: garante apenas os logins demo
        return
    created = ensure_demo_accounts()

    library = create_point(name="Biblioteca Central", building="Biblioteca Central / CCHL",
                           description="Balcão de achados e perdidos no térreo, ao lado do setor de empréstimos.",
                           openingHours="Seg a sex, 8h às 21h", contact="biblioteca@ufpi.edu.br", latitude=-5.0575, longitude=-42.796)
    restaurant = create_point(name="Restaurante Universitário", building="RU / Praça da Convivência",
                              description="Entrega de itens encontrados no balcão de atendimento do restaurante.",
                              openingHours="Seg a sex, 11h às 14h", contact="ru@ufpi.edu.br", latitude=-5.0555, longitude=-42.7876)
    technology = create_point(name="Bloco de Tecnologia", building="CT / Coordenação de Engenharia",
                              description="Ponto oficial para eletrônicos e materiais de laboratório.",
                              openingHours="Seg a sex, 8h às 18h", contact="ct@ufpi.edu.br", latitude=-5.0592, longitude=-42.7901)
    administration = create_point(name="Administração Central", building="Reitoria / Protocolo",
                                  description="Documentos e objetos de valor ficam sob responsabilidade da administração.",
                                  openingHours="Seg a sex, 7h30 às 19h", contact="protocolo@ufpi.edu.br", latitude=-5.0538, longitude=-42.7935)

    I = _item
    seed_items = [
        I("carlos", "FOUND", "ELECTRONIC", "Fone Bluetooth JBL preto encontrado",
          "Fone JBL Tune 510BT preto encontrado em uma mesa da sala de estudo do segundo andar. Está carregando e funcionando normalmente.",
          "Biblioteca Central", _days_ago(2, 15), color="Preto", brand="JBL", model="Tune 510BT",
          attributes={"serialNumber": "JBL-510-9921", "compatibility": "Carregador USB-C"},
          pointId=library.id, latitude=-5.0575, longitude=-42.796, imageUrl=IMAGES["headphones"]),
        I("ana", "LOST", "ELECTRONIC", "Fone JBL Tune 510BT perdido",
          "Perdi meu fone JBL Tune 510BT preto após estudar na Biblioteca Central. O cabo é USB-C e tenho a nota fiscal.",
          "Biblioteca Central", _days_ago(3, 18), color="Preto", brand="JBL", model="Tune 510BT",
          attributes={"serialNumber": "JBL-510-9921", "compatibility": "USB-C"}, latitude=-5.0575, longitude=-42.796),
        I("renata", "FOUND", "DOCUMENT", "Carteira de estudante da UFPI encontrada",
          "Carteira de estudante encontrada na fila do RU, em bom estado. Está guardada no balcão do Restaurante Universitário.",
          "Restaurante Universitário", _days_ago(1, 13), color="Azul",
          attributes={"documentType": "Carteira de estudante", "issuingBody": "UFPI"},
          pointId=restaurant.id, latitude=-5.0555, longitude=-42.7876, imageUrl=IMAGES["wallet"]),
        I("joao", "LOST", "DOCUMENT", "Carteira de estudante perdida no RU",
          "Perdi minha carteira de estudante azul da UFPI no Restaurante Universitário, curso de Direito, matrícula 2023.",
          "Restaurante Universitário", _days_ago(2, 12), color="Azul",
          attributes={"documentType": "Carteira de estudante", "issuingBody": "UFPI"}, latitude=-5.0555, longitude=-42.7876),
        I("ana", "LOST", "ACCESSORY", "Garrafa térmica laranja perdida",
          "Garrafa térmica laranja de 750 ml com adesivo do curso de Engenharia de Produção na lateral. Deixei no Centro de Tecnologia.",
          "Centro de Tecnologia (CT)", _days_ago(5, 9), color="Laranja", brand="Stanley",
          attributes={"material": "Aço inox", "visualDetails": "Adesivo do curso de Engenharia"}, latitude=-5.0592, longitude=-42.7901),
        I("maria", "FOUND", "ACCESSORY", "Garrafa térmica laranja no CT",
          "Encontrei uma garrafa térmica laranja de aço inox com adesivos coloridos esquecida no laboratório. Entreguei na coordenação.",
          "Centro de Tecnologia (CT)", _days_ago(4, 17), color="Laranja",
          attributes={"material": "Aço inox", "visualDetails": "Adesivos coloridos"},
          pointId=technology.id, latitude=-5.0592, longitude=-42.7901),
        I("carlos", "FOUND", "ACCESSORY", "Mochila cinza com chaveiro encontrada",
          "Mochila cinza com chaveiro de pelúcia encontrada no estacionamento central. Contém cadernos de cálculo.",
          "Estacionamento Central", _days_ago(6, 20), color="Cinza", brand="Nike",
          attributes={"material": "Poliéster", "visualDetails": "Chaveiro de pelúcia"},
          pointId=administration.id, latitude=-5.0548, longitude=-42.7922, imageUrl=IMAGES["bag"]),
        I("maria", "LOST", "ACCESSORY", "Mochila Nike cinza perdida",
          "Levei minha mochila Nike cinza com chaveiro de pelúcia para a aula e não a encontrei mais. Havia cadernos e uma calculadora dentro.",
          "Estacionamento Central", _days_ago(7, 19), color="Cinza", brand="Nike",
          attributes={"material": "Poliéster", "visualDetails": "Chaveiro de pelúcia"}, latitude=-5.0548, longitude=-42.7922),
        I("renata", "FOUND", "ELECTRONIC", "Celular Samsung azul encontrado na praça",
          "Samsung Galaxy A54 azul encontrado na Praça da Convivência, com capinha transparente e tela trincada no canto.",
          "Praça da Convivência", _days_ago(9, 16), color="Azul", brand="Samsung", model="Galaxy A54",
          attributes={"serialNumber": "R58T92KLMNP", "compatibility": "Carregador USB-C"},
          pointId=restaurant.id, latitude=-5.0555, longitude=-42.7876, imageUrl=IMAGES["phone"]),
        I("carlos", "LOST", "ELECTRONIC", "Celular Samsung Galaxy A54 perdido",
          "Meu Samsung Galaxy A54 azul com capinha transparente sumiu perto da Praça da Convivência. A tela tem uma trinca pequena.",
          "Praça da Convivência", _days_ago(10, 14), color="Azul", brand="Samsung", model="Galaxy A54",
          attributes={"serialNumber": "R58T92KLMNP", "compatibility": "USB-C"}, latitude=-5.0555, longitude=-42.7876),
        I("renata", "FOUND", "DOCUMENT", "Diploma de graduação em nome de Lucas Ferreira",
          "Diploma de graduação em Engenharia Elétrica encontrado na Coordenação do curso. Entregue na Biblioteca Central.",
          "Coordenação do curso", _days_ago(15, 11), color="Branco",
          attributes={"documentType": "Diploma", "issuingBody": "UFPI"}, pointId=library.id, latitude=-5.0575, longitude=-42.796),
        I("lucas", "LOST", "DOCUMENT", "Diploma de graduação extraviado",
          "Meu diploma de graduação em Engenharia Elétrica foi extraviado após a colação de grau. Emitido pela UFPI.",
          "Centro de Tecnologia (CT)", _days_ago(21, 10), color="Branco",
          attributes={"documentType": "Diploma", "issuingBody": "UFPI"}, latitude=-5.0592, longitude=-42.7901),
        I("carlos", "FOUND", "ACCESSORY", "Chaves com chaveiro de bicicleta encontradas",
          "Molho de chaves em metal com chaveiro de bicicleta azul encontrado próximo ao CCN. Está na Administração Central.",
          "Centro de Ciências da Natureza (CCN)", _days_ago(3, 8), color="Prata",
          attributes={"material": "Metal", "visualDetails": "Chaveiro de bicicleta azul"},
          pointId=administration.id, latitude=-5.0581, longitude=-42.7952, imageUrl=IMAGES["keys"]),
        I("lucas", "LOST", "ACCESSORY", "Chaves da bicicleta perdidas no CCN",
          "Perdi minhas chaves da bicicleta com um chaveiro azul no Centro de Ciências da Natureza. São três chaves de metal.",
          "Centro de Ciências da Natureza (CCN)", _days_ago(4, 18), color="Prata",
          attributes={"material": "Metal", "visualDetails": "Chaveiro azul"}, latitude=-5.0581, longitude=-42.7952),
        I("renata", "FOUND", "ELECTRONIC", "Notebook Dell prata no laboratório",
          "Notebook Dell Latitude prata esquecido no laboratório de pesquisa. Guardado com carregador no Bloco de Tecnologia.",
          "Laboratórios de pesquisa", _days_ago(12, 16), color="Prata", brand="Dell", model="Latitude 3420",
          attributes={"serialNumber": "DLL-3420-7781", "compatibility": "Carregador 65W"},
          pointId=technology.id, latitude=-5.0592, longitude=-42.7901, imageUrl=IMAGES["tech"]),
        I("lucas", "LOST", "ELECTRONIC", "Notebook Dell Latitude perdido",
          "Notebook Dell Latitude 3420 prata com carregador esquecido no laboratório de pesquisa do CT.",
          "Laboratórios de pesquisa", _days_ago(13, 15), color="Prata", brand="Dell", model="Latitude 3420",
          attributes={"serialNumber": "DLL-3420-7781", "compatibility": "65W"}, latitude=-5.0592, longitude=-42.7901),
        I("ana", "LOST", "ACCESSORY", "Guarda-chuva vermelho perdido na Reitoria",
          "Guarda-chuva vermelho com cabo de madeira esquecido no saguão da Reitoria durante a chuva da tarde.",
          "Administração Central", _days_ago(1, 17), color="Vermelho",
          attributes={"material": "Nylon", "visualDetails": "Cabo de madeira"},
          latitude=-5.0538, longitude=-42.7935, imageUrl=IMAGES["desk"]),
        I("maria", "FOUND", "ACCESSORY", "Caderno de Cálculo encontrado no bloco",
          "Caderno universitário com anotações de Cálculo I encontrado na sala 204. Nome parcialmente apagado na capa.",
          "Bloco de Salas Especiais", _days_ago(8, 10), color="Bege",
          attributes={"material": "Papel", "visualDetails": "Nome apagado na capa"},
          pointId=library.id, latitude=-5.0568, longitude=-42.7896, imageUrl=IMAGES["campus"]),
    ]

    created_items = []
    for e in seed_items:
        owner_id = created.get(e["owner"])
        if not owner_id:
            continue
        row = create_item({
            "user_id": owner_id, "type": e["type"], "category": e["category"], "title": e["title"],
            # prefixo usado por `repositories.items.is_seeded_item` (bloqueia pergunta secreta)
            "description": f"Registro demonstrativo: {e['description']}",
            "color": e.get("color"), "brand": e.get("brand"), "model": e.get("model"),
            "attributes": e.get("attributes", {}), "location": e["location"], "occurred_at": e["occurredAt"],
            "point_id": e.get("pointId"), "latitude": e.get("latitude"), "longitude": e.get("longitude"),
            "image_url": e.get("imageUrl")})
        created_items.append({"id": row.id, "title": e["title"]})
        add_item_event(item_id=row.id, actor_id=owner_id, status="OPEN",
                       note="Registro de item perdido publicado." if e["type"] == "LOST" else "Registro de item encontrado publicado.")
        with _quiet_match_emails():
            generate_matches_for_item(row.id)

    operator = find_user_by_email("operador@ufpi.edu.br")
    operator_id = operator.id if operator else created["renata"]
    staff_user = {"id": operator_id, "name": "Renata Nunes", "email": "operador@ufpi.edu.br", "phone": None,
                  "avatarUrl": None, "role": "OPERATOR_POST", "score": 230}

    pending = list_matches(status="PENDING", limit=40)
    phone_pair = next((m for m in pending if "Samsung" in m["lost"]["title"] and "Samsung" in m["found"]["title"]), None)
    if phone_pair:
        decide_match(staff_user, phone_pair["id"], "confirm", "Retirada combinada no Restaurante Universitário.")

    diploma = next((e for e in created_items if "Diploma de graduação em nome" in e["title"]), None)
    if diploma and find_item_by_id(diploma["id"]):
        set_item_status(diploma["id"], "RETURNED")
        add_item_event(item_id=diploma["id"], actor_id=operator_id, status="RETURNED",
                       note="Documento retirado pelo responsável na Biblioteca Central.")

    for uid in created.values():
        create_notification(userId=uid, type="SYSTEM", title="Bem-vindo(a) ao Esqueceram AI",
                            body="A plataforma da comunidade acadêmica da UFPI para reunir pessoas e objetos perdidos.", link="/painel")
    if created.get("ana"):
        create_notification(userId=created["ana"], type="UPDATE", title="Sugestão de correspondência atualizada",
                            body="Seu fone JBL pode estar na Biblioteca Central. Confira a sugestão de correspondência.", link="/painel/matches")
    if created.get("carlos"):
        create_notification(userId=created["carlos"], type="RECOVERY", title="Seu achado foi devolvido",
                            body="O celular Samsung encontrado na praça foi devolvido ao proprietário. Você ganhou 40 pontos!", link="/painel")


def ensure_seeded():
    """Executa o seed uma única vez por processo; falhas não ficam em cache (nova tentativa na próxima chamada)."""
    global _seeded
    if _seeded:
        return
    with _lock:
        if _seeded:
            return
        try:
            _seed()
            from application.delivery.seed import ensure_demo_attendant  # matrícula da conta demo do atendente
            ensure_demo_attendant()
            _seeded = True
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            print("[seed] failed", exc)


def find_demo_persona(persona: str | None) -> dict:
    n = (persona or "").strip().lower()
    return next((p for p in DEMO_PERSONAS if p["key"] == n or p["email"] == n), DEMO_PERSONAS[0])
