"""Testes dos endpoints HTTP (#9, #11, #13/#14/#15) sem depender de banco.

Os testes de integração com PostgreSQL vivem em test_db.py e são pulados
automaticamente quando não há um banco local configurado.
"""
import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

os.environ["FRONTEND_ORIGIN"] = "http://localhost:8080"

import app as modulo_app  # noqa: E402
from app import app  # noqa: E402


@pytest.fixture()
def cliente():
    app.config.update(TESTING=True)
    return app.test_client()


class ConexaoFalsa:
    """Imita o subconjunto de psycopg2 usado pelos endpoints."""

    def __init__(self, item=None, itens=None, posto=None, postos=None):
        self.item = item
        self.itens = itens or []
        self.posto = posto
        self.postos = postos or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def close(self):
        pass

    def cursor(self, cursor_factory=None):
        return CursorFalso(self)

    def commit(self):
        pass


class CursorFalso:
    def __init__(self, conexao):
        self.conexao = conexao
        self._resultado = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        normalizado = " ".join(sql.split()).lower()
        if normalizado.startswith("select id from usuario"):
            self._resultado = {"id": 1}
        elif "insert into item" in normalizado:
            self._resultado = {
                "id": 7,
                "tipo_registro": params[1],
                "categoria": params[2],
                "descricao": params[3],
                "imagem_url": params[12],
                "status": "ABERTO",
            }
        elif "insert into posto_coleta" in normalizado:
            self._resultado = {"id": 3, "nome": params[0], "endereco": params[1]}
        elif "from item i" in normalizado:
            self._resultado = self.conexao.itens
        elif "from posto_coleta" in normalizado:
            self._resultado = self.conexao.postos

    def fetchone(self):
        return self._resultado

    def fetchall(self):
        return self._resultado or []


def test_health(cliente):
    response = cliente.get("/api/health")

    assert response.status_code == 200
    assert response.json == {"status": "UP"}


def test_raiz_responde(cliente):
    assert cliente.get("/").status_code == 200


def test_listar_itens_aplica_filtros(cliente, monkeypatch):
    consultas = []

    def conexao_falsa():
        return ConexaoFalsa(itens=[{"id": 1, "descricao": "Celular azul"}])

    monkeypatch.setattr(modulo_app, "get_connection", conexao_falsa)
    original = CursorFalso.execute

    def espiao(self, sql, params=None):
        consultas.append((" ".join(sql.split()), params))
        return original(self, sql, params)

    monkeypatch.setattr(CursorFalso, "execute", espiao)

    resposta = cliente.get("/api/itens?q=celular&status=aberto&tipo_registro=perdido")

    assert resposta.status_code == 200
    assert resposta.json[0]["descricao"] == "Celular azul"
    sql, params = consultas[-1]
    assert "busca @@ plainto_tsquery" in sql
    assert "status = %s" in sql and "tipo_registro = %s" in sql
    assert params[:3] == ["celular", "ABERTO", "PERDIDO"]


def test_listar_itens_rejeita_status_invalido(cliente):
    resposta = cliente.get("/api/itens?status=INVENTADO")

    assert resposta.status_code == 400
    assert "status" in resposta.json["erro"]


def test_listar_itens_rejeita_limite_nao_numerico(cliente):
    assert cliente.get("/api/itens?limite=abc").status_code == 400


def test_criar_item_exige_descricao(cliente):
    resposta = cliente.post("/api/itens", json={"tipo_registro": "PERDIDO", "categoria": "ELETRONICO"})

    assert resposta.status_code == 400
    assert "descricao" in resposta.json["erro"]


def test_criar_item_valida_tipo_registro(cliente):
    resposta = cliente.post(
        "/api/itens",
        json={"tipo_registro": "TALVEZ", "categoria": "ELETRONICO", "descricao": "x"},
    )

    assert resposta.status_code == 400


def test_criar_item_valida_categoria(cliente):
    resposta = cliente.post(
        "/api/itens",
        json={"tipo_registro": "PERDIDO", "categoria": "ANIMAL", "descricao": "x"},
    )

    assert resposta.status_code == 400


def test_criar_item_documento_exige_tipo_documento(cliente):
    resposta = cliente.post(
        "/api/itens",
        json={"tipo_registro": "PERDIDO", "categoria": "DOCUMENTO", "descricao": "RG"},
    )

    assert resposta.status_code == 400
    assert "tipo_documento" in resposta.json["erro"]


def test_criar_item_perdido_nao_aceita_posto(cliente):
    resposta = cliente.post(
        "/api/itens",
        json={
            "tipo_registro": "PERDIDO",
            "categoria": "ELETRONICO",
            "descricao": "Celular",
            "posto_id": 1,
        },
    )

    assert resposta.status_code == 400
    assert "ENCONTRADOS" in resposta.json["erro"]


def test_criar_item_valida_coordenadas(cliente):
    resposta = cliente.post(
        "/api/itens",
        json={
            "tipo_registro": "ENCONTRADO",
            "categoria": "ELETRONICO",
            "descricao": "Celular",
            "latitude": "abc",
        },
    )

    assert resposta.status_code == 400


def test_criar_item_persiste_e_devolve_201(cliente, monkeypatch):
    monkeypatch.setattr(modulo_app, "get_connection", lambda: ConexaoFalsa())

    resposta = cliente.post(
        "/api/itens",
        json={"tipo_registro": "ENCONTRADO", "categoria": "ELETRONICO", "descricao": "Mochila preta"},
    )

    assert resposta.status_code == 201
    assert resposta.json["id"] == 7
    assert resposta.json["status"] == "ABERTO"


def test_criar_item_rejeita_imagem_de_formato_invalido(cliente, tmp_path, monkeypatch):
    monkeypatch.setattr(modulo_app, "UPLOAD_DIR", str(tmp_path))
    dados = {
        "tipo_registro": "ENCONTRADO",
        "categoria": "ELETRONICO",
        "descricao": "Mochila",
        "imagem": (io.BytesIO(b"conteudo"), "nota.txt"),
    }

    resposta = cliente.post("/api/itens", data=dados, content_type="multipart/form-data")

    assert resposta.status_code == 400
    assert "formato" in resposta.json["erro"]


def test_criar_item_salva_imagem_em_upload(cliente, tmp_path, monkeypatch):
    monkeypatch.setattr(modulo_app, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(modulo_app, "get_connection", lambda: ConexaoFalsa())
    dados = {
        "tipo_registro": "ENCONTRADO",
        "categoria": "ELETRONICO",
        "descricao": "Mochila",
        "imagem": (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "foto.png"),
    }

    resposta = cliente.post("/api/itens", data=dados, content_type="multipart/form-data")

    assert resposta.status_code == 201
    assert resposta.json["imagem_url"].startswith("/api/uploads/")
    arquivos = list(tmp_path.iterdir())
    assert len(arquivos) == 1 and arquivos[0].suffix == ".png"
