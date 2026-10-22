import json
import os
import uuid
from datetime import date
from functools import lru_cache
import psycopg2
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

@lru_cache(maxsize=1)
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
# Recebe os dados enviados pelo HTML e salva no banco
@app.route("/posto", methods=["POST"])
def criar_posto():
    dados = request.get_json()

    conn = get_conn()
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
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
