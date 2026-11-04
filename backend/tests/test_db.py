"""
Testes do banco do EsqueceramAI (valida o schema.sql e os models.py).
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))  # permite importar models, init_db...

import psycopg2  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.exc import DBAPIError, IntegrityError  # noqa: E402

from extensions import criar_app_db, db  # noqa: E402
from init_db import banco_local, preparar_banco  # noqa: E402
from models import (  # noqa: E402
    CategoriaItem, Item, Match, Notificacao, OrigemRecompensa, PostoColeta, Recompensa,
    Recuperacao, StatusItem, StatusMatch, StatusRecuperacao, TipoNotificacao, TipoRegistro,
    Usuario, pontuacao_do_usuario, reservar_item,
)

load_dotenv(Path(__file__).parents[1] / ".env")


def _url_de_teste():
    """Devolve a URL do banco '<nome>_test' ou None se não houver banco LOCAL configurado."""
    base = os.environ.get("DATABASE_URL")
    if not base or not banco_local(base):
        return None
    url = make_url(base)
    if not url.database.endswith("_test"):
        url = url.set(database=url.database + "_test")
    assert url.database.endswith("_test")  # trava: nunca rodar no banco real
    return url.render_as_string(hide_password=False)


TEST_URL = _url_de_teste()

TABELAS = {
    "usuario", "perfil", "dispositivo_fcm", "posto_coleta", "posto_operador", "item",
    "match", "recuperacao", "recompensa", "notificacao", "historico_evento",
}


class BancoTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if TEST_URL is None:
            raise unittest.SkipTest("sem DATABASE_URL de um PostgreSQL local")
        try:
            preparar_banco(TEST_URL, reset=True)   # schema limpo a cada grupo de testes
        except psycopg2.OperationalError as erro:
            raise unittest.SkipTest(f"PostgreSQL local indisponível: {erro}")
        cls.ctx = criar_app_db(TEST_URL).app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        cls.ctx.pop()

    def tearDown(self):
        db.session.rollback()
        db.session.execute(text(
            "TRUNCATE usuario, posto_coleta RESTART IDENTITY CASCADE"))  # limpa tudo
        db.session.commit()

    # ---- fábricas auxiliares ----------------------------------------------------------
    def usuario(self, nome="Teste"):
        u = Usuario(nome=nome, email=f"{nome.lower()}@ufpi.edu.br", senha_hash="x")
        db.session.add(u)
        db.session.flush()
        return u

    def item(self, usuario, tipo, **kw):
        kw.setdefault("categoria", CategoriaItem.ELETRONICO)
        kw.setdefault("descricao", "Celular azul")
        i = Item(usuario_id=usuario.id, tipo_registro=tipo, **kw)
        db.session.add(i)
        db.session.flush()
        return i

    def par_com_match(self):
        dono, achador = self.usuario("Dono"), self.usuario("Achador")
        perdido = self.item(dono, TipoRegistro.PERDIDO)
        encontrado = self.item(achador, TipoRegistro.ENCONTRADO)
        m = Match(item_perdido_id=perdido.id, item_encontrado_id=encontrado.id, score=0.9)
        db.session.add(m)
        db.session.flush()
        return dono, achador, perdido, encontrado, m


class TestEstrutura(BancoTestCase):
    def test_todas_as_tabelas_do_diagrama_existem(self):
        rows = db.session.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"))
        existentes = {r[0] for r in rows}
        self.assertEqual(TABELAS - existentes, set())

    def test_conexao_com_o_banco(self):
        self.assertEqual(db.session.execute(text("SELECT 1")).scalar_one(), 1)


class TestItens(BancoTestCase):
    def test_busca_textual_em_portugues(self):
        u = self.usuario()
        self.item(u, TipoRegistro.PERDIDO, descricao="Celular com capinha azul")
        self.item(u, TipoRegistro.ENCONTRADO, descricao="Mochila preta")
        q = select(Item).where(Item.busca.op("@@")(func.plainto_tsquery("portuguese", "celular")))
        self.assertEqual(len(db.session.scalars(q).all()), 1)

    def test_documento_exige_tipo_documento(self):
        u = self.usuario()
        with self.assertRaises(IntegrityError):
            self.item(u, TipoRegistro.PERDIDO, categoria=CategoriaItem.DOCUMENTO, descricao="RG")

    def test_documento_com_tipo_e_aceito(self):
        u = self.usuario()
        i = self.item(u, TipoRegistro.PERDIDO, categoria=CategoriaItem.DOCUMENTO,
                      descricao="RG", atributos={"tipo_documento": "RG"})
        self.assertEqual(i.atributos["tipo_documento"], "RG")

    def test_posto_so_para_item_encontrado(self):
        u = self.usuario()
        posto = PostoColeta(nome="Posto", endereco="Bloco 5")
        db.session.add(posto)
        db.session.flush()
        with self.assertRaises(IntegrityError):
            self.item(u, TipoRegistro.PERDIDO, posto_id=posto.id)


class TestMatchERecuperacao(BancoTestCase):
    def test_match_invertido_e_rejeitado(self):
        _, _, perdido, encontrado, _ = self.par_com_match()
        with self.assertRaises(IntegrityError):
            db.session.add(Match(item_perdido_id=encontrado.id,
                                 item_encontrado_id=perdido.id, score=0.5))
            db.session.flush()

    def test_match_duplicado_e_rejeitado(self):
        _, _, perdido, encontrado, _ = self.par_com_match()
        with self.assertRaises(IntegrityError):
            db.session.add(Match(item_perdido_id=perdido.id,
                                 item_encontrado_id=encontrado.id, score=0.5))
            db.session.flush()

    def test_score_fora_de_0_a_1_e_rejeitado(self):
        dono, achador = self.usuario("A"), self.usuario("B")
        p = self.item(dono, TipoRegistro.PERDIDO)
        e = self.item(achador, TipoRegistro.ENCONTRADO)
        with self.assertRaises(IntegrityError):
            db.session.add(Match(item_perdido_id=p.id, item_encontrado_id=e.id, score=1.5))
            db.session.flush()

    def test_reservar_item_fluxo_completo(self):
        _, _, perdido, encontrado, m = self.par_com_match()
        rec_id = reservar_item(m.id)
        db.session.commit()
        db.session.expire_all()

        self.assertEqual(db.session.get(Match, m.id).status, StatusMatch.CONFIRMADO)
        self.assertEqual(db.session.get(Item, perdido.id).status, StatusItem.RESERVADO)
        self.assertEqual(db.session.get(Item, encontrado.id).status, StatusItem.RESERVADO)
        self.assertEqual(db.session.get(Recuperacao, rec_id).status, StatusRecuperacao.RESERVADA)

    def test_nao_reserva_duas_vezes_o_mesmo_match(self):
        *_, m = self.par_com_match()
        reservar_item(m.id)
        db.session.commit()
        with self.assertRaises(DBAPIError):
            reservar_item(m.id)

    def test_item_ja_reservado_nao_aceita_outro_match(self):
        _, _, _, encontrado, m1 = self.par_com_match()
        outro = self.usuario("Outro")
        perdido2 = self.item(outro, TipoRegistro.PERDIDO)
        m2 = Match(item_perdido_id=perdido2.id, item_encontrado_id=encontrado.id, score=0.7)
        db.session.add(m2)
        db.session.flush()

        reservar_item(m1.id)
        db.session.commit()
        with self.assertRaises(DBAPIError):
            reservar_item(m2.id)


class TestRecompensasENotificacoes(BancoTestCase):
    def test_pontuacao_soma_os_pontos_do_usuario(self):
        u = self.usuario()
        db.session.add_all([
            Recompensa(beneficiario_id=u.id, origem=OrigemRecompensa.REGRA_PONTOS, pontos=10),
            Recompensa(beneficiario_id=u.id, origem=OrigemRecompensa.REGRA_PONTOS, pontos=5),
        ])
        db.session.flush()
        self.assertEqual(pontuacao_do_usuario(u.id), 15)

    def test_email_unico_ignora_maiusculas(self):
        db.session.add(Usuario(nome="A", email="Ana@ufpi.edu.br", senha_hash="x"))
        db.session.flush()
        with self.assertRaises(IntegrityError):
            db.session.add(Usuario(nome="B", email="ana@UFPI.edu.br", senha_hash="x"))
            db.session.flush()

    def test_notificacao_aponta_para_match(self):
        dono, _, _, _, m = self.par_com_match()
        n = Notificacao(usuario_id=dono.id, tipo=TipoNotificacao.MATCH_IDENTIFICADO,
                        titulo="Possível match", corpo="Achamos algo parecido", match_id=m.id)
        db.session.add(n)
        db.session.flush()
        self.assertEqual(len(dono.notificacoes), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
