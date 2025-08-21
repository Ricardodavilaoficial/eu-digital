# main.py — MEI Robô (seguro para Render)

from flask import Flask, render_template, jsonify
from dotenv import load_dotenv
import os

# 0) Carrega .env local (não atrapalha no Render)
load_dotenv()

# 1) Cria app (mantém paths padrão; você já usa /templates)
app = Flask(__name__)

# 2) Limites e configs seguras
# Limite de upload (áudio/tabelas). Ajuste se precisar.
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

# 3) CORS apenas para /api/* (frontend local chamando backend no Render)
try:
    from flask_cors import CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
except Exception:
    # Se flask-cors não estiver instalado, segue sem CORS (ambiente já funcionava)
    pass

# 4) Importa e registra blueprints EXISTENTES (que já rodam)
#    Mantemos imports fora de try/except p/ falhas visíveis nos logs.
from routes.routes import routes
from routes.teste_eleven_route import teste_eleven_route
from routes.cupons import cupons_bp
from routes.core_api import core_api

app.register_blueprint(routes)
app.register_blueprint(teste_eleven_route)
app.register_blueprint(cupons_bp)
app.register_blueprint(core_api)

# 5) (Novo) Tenta registrar os blueprints da etapa atual — opcionais
#    Se os arquivos ainda não existirem, NÃO quebramos o deploy.
try:
    from routes.configuracao import config_bp
    app.register_blueprint(config_bp)
except Exception as e:
    # Log leve: rota opcional ausente ou com erro — seguimos em frente
    print(f"[warn] config_bp não registrado: {e}")

try:
    from routes.importar_precos import importar_bp
    app.register_blueprint(importar_bp)
except Exception as e:
    print(f"[warn] importar_bp não registrado: {e}")

# 6) Healthcheck simples (Render / monitoramento)
@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(ok=True)

# 7) Página inicial (mantém sua index.html em /templates)
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

# 8) Execução local / Render
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    # debug=True só em dev; no Render, o WSGI do container ignora isso
    app.run(host="0.0.0.0", port=port, debug=True)
