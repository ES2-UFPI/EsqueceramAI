import os
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)

# Permite requisições locais vindas do frontend na porta 80
frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost")
CORS(app, resources={r"/api/*": {"origins": [frontend_origin, "http://localhost:5500"]}})

# Endpoints do Backend (Retornam estritamente JSON)
@app.get("/api/health")
def health():
    return jsonify({"status": "healthy", "scope": "global_api"})

@app.get("/api/itens")
def get_itens():
    # Exemplo de retorno simulado de banco
    return jsonify([
        {"id": 1, "nome": "Item Exemplo A"},
        {"id": 2, "nome": "Item Exemplo B"}
    ])

@app.get("/api/usuarios")
def get_usuarios():
    return jsonify([
        {"id": 101, "username": "arthur_dev"}
    ])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
