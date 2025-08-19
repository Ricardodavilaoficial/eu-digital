from flask import Flask, render_template
from dotenv import load_dotenv
import os

# Carrega variáveis de ambiente locais (útil fora do Render)
load_dotenv()

# Instancia o Flask
app = Flask(__name__)

# (Opcional) CORS se o frontend chamar direto este backend
try:
    from flask_cors import CORS
    CORS(app, supports_credentials=True)
except Exception:
    pass

# Importa e registra as rotas existentes
from routes.routes import routes
from routes.teste_eleven_route import teste_eleven_route
from routes.cupons import cupons_bp  # sua rota pré-existente

# Importa o pacote novo (Drop A — Core API)
from routes.core_api import core_api

# Registra todos os blueprints (agora com app já criado)
app.register_blueprint(routes)
app.register_blueprint(teste_eleven_route)
app.register_blueprint(cupons_bp)
app.register_blueprint(core_api)

# Página inicial
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
