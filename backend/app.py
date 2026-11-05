import json
import os
import uuid
from datetime import date

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__)

# Adaptação para Produção: Libera o CORS especificamente para o GitHub Pages
CORS(app, resources={r"/api/*": {"origins": "https://es2-ufpi.github.io"}})

TIPO_REGISTRO = {"PERDIDO", "ENCONTRADO"}
CATEGORIA = {"ELETRONICO", "DOCUMENTO", "ACESSORIO"}
STATUS_ITEM = {"ABERTO", "RESERVADO", "DEVOLVIDO", "ARQUIVADO"}

EXTENSOES_IMAGEM = {"png", "jpg", "jpeg", "gif", "webp"}
TAMANHO_MAXIMO_IMAGEM = 5 * 1024 * 1024  # 5 MB
UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "storage"))
EMAIL_USUARIO_PADRAO = os.getenv("EMAIL_USUARIO_PADRAO", "anonimo@esqueceram.ai")


def database_url():
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL não configurada")
    return value


def get_connection():
    return psycopg2.connect(database_url())


def usuario_padrao(cur):
    """Enquanto não há autenticação (Sprint 2), todo item precisa de um autor válido."""
    cur.execute("SELECT id FROM usuario WHERE lower(email) = lower(%s)", (EMAIL_USUARIO_PADRAO,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute(
        """
        INSERT INTO usuario (nome, email, senha_hash, papel)
        VALUES (%s, %s, %s, 'USUARIO')
        RETURNING id
        """,
        ("Visitante", EMAIL_USUARIO_PADRAO, "!"),
    )
    return cur.fetchone()["id"]


def extensao_valida(nome_arquivo):
    return "." in nome_arquivo and nome_arquivo.rsplit(".", 1)[1].lower() in EXTENSOES_IMAGEM


def salvar_imagem(arquivo):
    """Grava a foto em UPLOAD_DIR e devolve a URL pública servida pela API."""
    if not extensao_valida(arquivo.filename):
        raise ValueError("formato de imagem não suportado (use png, jpg, jpeg, gif ou webp)")

    conteudo = arquivo.read(TAMANHO_MAXIMO_IMAGEM + 1)
    if len(conteudo) > TAMANHO_MAXIMO_IMAGEM:
        raise ValueError("imagem maior que 5 MB")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    nome = f"{uuid.uuid4().hex}.{arquivo.filename.rsplit('.', 1)[1].lower()}"
    with open(os.path.join(UPLOAD_DIR, nome), "wb") as destino:
        destino.write(conteudo)
    return f"/api/uploads/{nome}"


def erro(mensagem, codigo=400):
    return jsonify({"erro": mensagem}), codigo


@app.get("/")
def raiz():
    return jsonify({"status": "API Esqueceram AI no ar"})


@app.get("/api/health")
def health():
    return jsonify({"status": "UP"})


@app.get("/api/uploads/<nome_arquivo>")
def obter_imagem(nome_arquivo):
    return send_from_directory(UPLOAD_DIR, nome_arquivo)


@app.post("/api/itens")
def criar_item():
    """US01/US02 (#9): cadastra um item perdido ou encontrado."""
    if request.files.get("imagem") or request.form:
        dados = request.form.to_dict()
        arquivo = request.files.get("imagem")
    else:
        dados = request.get_json(silent=True) or {}
        arquivo = None

    if not isinstance(dados, dict) or not dados:
        return erro("corpo da requisição ausente ou inválido")

    tipo = str(dados.get("tipo_registro", "")).upper()
    categoria = str(dados.get("categoria", "")).upper()
    descricao = str(dados.get("descricao", "")).strip()

    if tipo not in TIPO_REGISTRO:
        return erro("tipo_registro deve ser PERDIDO ou ENCONTRADO")
    if categoria not in CATEGORIA:
        return erro("categoria deve ser ELETRONICO, DOCUMENTO ou ACESSORIO")
    if not descricao:
        return erro("descricao é obrigatória")

    atributos = dados.get("atributos") or {}
    if isinstance(atributos, str):
        try:
            atributos = json.loads(atributos)
        except json.JSONDecodeError:
            return erro("atributos deve ser um objeto JSON")
    if not isinstance(atributos, dict):
        return erro("atributos deve ser um objeto JSON")
    if categoria == "DOCUMENTO" and not atributos.get("tipo_documento"):
        return erro("itens da categoria DOCUMENTO exigem atributos.tipo_documento")

    try:
        posto_id = int(dados["posto_id"]) if dados.get("posto_id") else None
    except (TypeError, ValueError):
        return erro("posto_id inválido")
    if posto_id is not None and tipo != "ENCONTRADO":
        return erro("apenas itens ENCONTRADOS podem ser entregues em um posto de coleta")

    try:
        latitude = float(dados["latitude"]) if dados.get("latitude") else None
        longitude = float(dados["longitude"]) if dados.get("longitude") else None
    except (TypeError, ValueError):
        return erro("latitude e longitude devem ser numéricas")

    try:
        imagem_url = salvar_imagem(arquivo) if arquivo else dados.get("imagem_url")
    except ValueError as exc:
        return erro(str(exc))

    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                usuario_id = int(dados["usuario_id"]) if dados.get("usuario_id") else None
            except (TypeError, ValueError):
                return erro("usuario_id inválido")
            if usuario_id is None:
                usuario_id = usuario_padrao(cur)

            try:
                cur.execute(
                    """
                    INSERT INTO item (
                        usuario_id, tipo_registro, categoria, descricao, cor, marca, modelo,
                        atributos, localizacao, latitude, longitude, data_ocorrencia,
                        imagem_url, posto_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        usuario_id,
                        tipo,
                        categoria,
                        descricao,
                        dados.get("cor") or None,
                        dados.get("marca") or None,
                        dados.get("modelo") or None,
                        Json(atributos),
                        dados.get("localizacao") or None,
                        latitude,
                        longitude,
                        dados.get("data_ocorrencia") or date.today(),
                        imagem_url,
                        posto_id,
                    ),
                )
            except psycopg2.errors.ForeignKeyViolation:
                return erro("posto_id ou usuario_id inexistente", 422)
            item = cur.fetchone()
    finally:
        conn.close()

    return jsonify(item), 201


@app.get("/api/itens")
def listar_itens():
    """US01/US02 (#11): lista e busca itens com filtros por palavra-chave e status."""
    try:
        limite = min(max(int(request.args.get("limite", 50)), 1), 200)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        return erro("limite e offset devem ser inteiros")

    filtros, valores = [], []

    termo = (request.args.get("q") or "").strip()
    if termo:
        filtros.append("busca @@ plainto_tsquery('portuguese', %s)")
        valores.append(termo)

    status = request.args.get("status")
    if status:
        status = status.upper()
        if status not in STATUS_ITEM:
            return erro("status inválido")
        filtros.append("status = %s")
        valores.append(status)

    tipo = request.args.get("tipo_registro")
    if tipo:
        tipo = tipo.upper()
        if tipo not in TIPO_REGISTRO:
            return erro("tipo_registro inválido")
        filtros.append("tipo_registro = %s")
        valores.append(tipo)

    categoria = request.args.get("categoria")
    if categoria:
        categoria = categoria.upper()
        if categoria not in CATEGORIA:
            return erro("categoria inválida")
        filtros.append("categoria = %s")
        valores.append(categoria)

    posto_id = request.args.get("posto_id")
    if posto_id:
        try:
            filtros.append("posto_id = %s")
            valores.append(int(posto_id))
        except ValueError:
            return erro("posto_id inválido")

    onde = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    consulta = f"""
        SELECT i.*, p.nome AS posto_nome
        FROM item i
        LEFT JOIN posto_coleta p ON p.id = i.posto_id
        {onde}
        ORDER BY i.criado_em DESC, i.id DESC
        LIMIT %s OFFSET %s
    """

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(consulta, valores + [limite, offset])
            itens = cur.fetchall()
    finally:
        conn.close()

    return jsonify(itens)


@app.get("/api/itens/<int:item_id>")
def obter_item(item_id):
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT i.*, p.nome AS posto_nome
                FROM item i
                LEFT JOIN posto_coleta p ON p.id = i.posto_id
                WHERE i.id = %s
                """,
                (item_id,),
            )
            item = cur.fetchone()
    finally:
        conn.close()

    if item is None:
        return erro("item não encontrado", 404)
    return jsonify(item)


@app.post("/api/postos")
@app.post("/api/posto")
@app.post("/posto")
def criar_posto():
    """US03 (#13/#14/#15): cadastra um ponto de coleta."""
    dados = request.get_json(silent=True)
    campos = ("nome", "endereco", "latitude", "longitude")
    if not dados or any(dados.get(campo) is None for campo in campos):
        return erro("nome, endereco, latitude e longitude são obrigatórios")

    try:
        latitude = float(dados["latitude"])
        longitude = float(dados["longitude"])
    except (TypeError, ValueError):
        return erro("latitude e longitude devem ser numéricas")
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        return erro("latitude deve estar entre -90 e 90 e longitude entre -180 e 180")

    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO posto_coleta
                    (nome, endereco, latitude, longitude, horario_funcionamento, ativo)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    dados["nome"],
                    dados["endereco"],
                    latitude,
                    longitude,
                    dados.get("horario_funcionamento"),
                    dados.get("ativo", True),
                ),
            )
            posto = cur.fetchone()
    finally:
        conn.close()

    return jsonify(posto), 201


@app.get("/api/postos")
def listar_postos():
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM posto_coleta ORDER BY nome")
            postos = cur.fetchall()
    finally:
        conn.close()

    return jsonify(postos)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
