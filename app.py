# app.py — entrypoint para runtime Python do Render (produção)
# Reúne tudo que estava no main.py + blueprints existentes e novos.

import os
from flask import Flask, render_template, jsonify

# 1) Cria app
app = Flask(__name__)

# 2) Limites e CORS (para frontend local chamar /api/* com segurança)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

try:
    from flask_cors import CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
except Exception:
    pass  # se flask-cors não estiver, o app ainda sobe (mas habilite no requirements)

# 3) Blueprints já existentes (do seu projeto)
from routes.routes import routes
from routes.teste_eleven_route import teste_eleven_route
from routes.cupons import cupons_bp
from routes.core_api import core_api

app.register_blueprint(routes)
app.register_blueprint(teste_eleven_route)
app.register_blueprint(cupons_bp)
app.register_blueprint(core_api)

# 4) Blueprints novos (opcionais — try/except para não quebrar)
try:
    from routes.configuracao import config_bp
    app.register_blueprint(config_bp)
except Exception as e:
    print(f"[warn] config_bp não registrado: {e}")

try:
    from routes.importar_precos import importar_bp
    app.register_blueprint(importar_bp)
except Exception as e:
    print(f"[warn] importar_bp não registrado: {e}")

# 5) Healthcheck
@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(ok=True, scope="app")

# 6) Página inicial (usa /templates/index.html)
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")
