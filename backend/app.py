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

@app.get("/api/health")
def health():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
