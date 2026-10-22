from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app)

def get_conn():
    return psycopg2.connect(
        host="localhost",
        dbname="meubanco",
        user="postgres",
        password="postgres",
    )

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


if __name__ == "__main__":
    app.run(port=3000, debug=True)
