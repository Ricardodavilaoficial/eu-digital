from flask import Flask, render_template
from dotenv import load_dotenv
import os

# Carrega variáveis locais (para testes no Replit ou VS Code)
load_dotenv()

app = Flask(__name__)

# Registra o blueprint principal com a lógica de rotas e IA
from routes.routes import routes
app.register_blueprint(routes)

# Rota raiz (serve a interface HTML)
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
