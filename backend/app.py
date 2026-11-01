import json
import os
import uuid
from datetime import date
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5500")
CORS(app, resources={r"/api/*": {"origins": frontend_origin}})
def database_url():
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL não configurada")
    return value

def get_connection():
    return psycopg2.connect(database_url())

def initialize_database():
    connection = get_connection()
    try:
        with connection:
            with connection.cursor() as cursor:
                pass
    finally:
        connection.close()
        get_connection.cache_clear()

@app.get("/")
def raiz():
    return jsonify({"status": "API Esqueceram AI no ar"})

@app.get("/api/itens")
def listar():
    return jsonify(itens)

@app.post("/api/itens")
def criar():
    dados = request.get_json(silent=True)
    if not dados or not dados.get("nome") or not dados.get("local"):
        return jsonify({"erro": "nome e local são obrigatórios"}), 400
    item = {"id": len(itens) + 1, "nome": dados["nome"], "local": dados["local"]}
    itens.append(item)
    return jsonify(item), 201

@app.post("/api/posto")
@app.post("/posto")
def criar_posto():
    dados = request.get_json(silent=True)
    required_fields = ("nome", "endereco", "latitude", "longitude")
    if not dados or any(dados.get(field) is None for field in required_fields):
        return jsonify({"erro": "nome, endereco, latitude e longitude são obrigatórios"}), 400

    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO posto_coleta (nome, endereco, latitude, longitude, ativo)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    dados["nome"],
                    dados["endereco"],
                    dados["latitude"],
                    dados["longitude"],
                    dados.get("ativo", True),
                ),
            )
            posto = cur.fetchone()
    finally:
        conn.close()

    return jsonify(posto), 201

@app.get("/api/health")
def health():
    return jsonify({"status": "UP"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
