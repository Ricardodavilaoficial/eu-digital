from flask import Flask, render_template
from dotenv import load_dotenv
import os

# Carrega variáveis de ambiente locais (útil para testes fora do Render.com)
load_dotenv()

# Instancia o Flask
app = Flask(__name__)

# Importa e registra as rotas existentes
from routes.routes import routes
from routes.teste_eleven_route import teste_eleven_route
from routes.cupons import cupons_bp  # nova rota de cupons

app.register_blueprint(routes)
app.register_blueprint(teste_eleven_route)
app.register_blueprint(cupons_bp)

# Página inicial
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
