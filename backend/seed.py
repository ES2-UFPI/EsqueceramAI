#Dados de exemplo para desenvolvimento LOCAL
import os
from werkzeug.security import generate_password_hash
from extensions import criar_app_db, db
from init_db import banco_local
from models import (
    CategoriaItem, Item, Match, PapelUsuario, Perfil, PostoColeta, PostoOperador,
    TipoRegistro, Usuario,
)

def run_seed() -> None:
    url = os.environ["DATABASE_URL"]
    if not banco_local(url):
        raise RuntimeError("--seed recusado: só é permitido em banco local "
                           "(criaria usuários com senha de teste).")
    app = criar_app_db(url)
    with app.app_context():
        if db.session.query(Usuario).first():
            print("Seed ignorado: já existem usuários no banco.")
            return

        senha = generate_password_hash("senha123")  # senha de TESTE; nunca use em produção
        admin = Usuario(nome="Admin", email="admin@ufpi.edu.br", senha_hash=senha,
                        papel=PapelUsuario.ADMIN)
        operador = Usuario(nome="Operador CCN", email="operador@ufpi.edu.br", senha_hash=senha,
                           papel=PapelUsuario.OPERADOR_POSTO)
        joana = Usuario(nome="Joana", email="joana@ufpi.edu.br", senha_hash=senha,
                        perfil=Perfil(telefone="86999990001"))
        julia = Usuario(nome="Júlia", email="julia@ufpi.edu.br", senha_hash=senha,
                        perfil=Perfil(telefone="86999990002"))

        posto = PostoColeta(nome="Posto de Coleta CCN", endereco="Bloco 5, CCN - UFPI, Teresina-PI",
                            horario_funcionamento="Seg a Sex, 8h às 18h")
        posto.operadores.append(PostoOperador(usuario=operador))
        db.session.add_all([admin, operador, joana, julia, posto])
        db.session.flush()

        perdido = Item(
            usuario=joana, tipo_registro=TipoRegistro.PERDIDO, categoria=CategoriaItem.ELETRONICO,
            descricao="Celular com capinha azul, tela trincada no canto", cor="azul",
            marca="Samsung", modelo="Galaxy A54", localizacao="Biblioteca Central")
        encontrado = Item(
            usuario=julia, tipo_registro=TipoRegistro.ENCONTRADO, categoria=CategoriaItem.ELETRONICO,
            descricao="Celular Samsung com capa azul achado no corredor", cor="azul",
            marca="Samsung", modelo="Galaxy A54", localizacao="Corredor do Bloco 5", posto=posto)
        rg = Item(
            usuario=julia, tipo_registro=TipoRegistro.ENCONTRADO, categoria=CategoriaItem.DOCUMENTO,
            descricao="Carteira de identidade encontrada no refeitório",
            atributos={"tipo_documento": "RG", "orgao_emissor": "SSP-PI"}, posto=posto)
        db.session.add_all([perdido, encontrado, rg])
        db.session.flush()

        db.session.add(Match(item_perdido_id=perdido.id, item_encontrado_id=encontrado.id,
                             score=0.91))
        db.session.commit()
        print("Seed aplicado: 4 usuários (senha 'senha123'), 1 posto, 3 itens, 1 match.")