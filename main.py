from flask import Flask, render_template
from dotenv import load_dotenv
import os

# Carrega variáveis de ambiente locais (útil para testes fora do Render.com)
load_dotenv()

app = Flask(__name__)

# Importa e registra as rotas
from routes.routes import routes
from routes.teste_eleven_route import teste_eleven_route
app.register_blueprint(routes)
app.register_blueprint(teste_eleven_route)

# Página inicial
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)

