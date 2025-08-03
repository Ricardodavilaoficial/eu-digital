from flask import Flask, request, send_file, render_template_string, jsonify
from services.openai_handler import obter_resposta_openai
from services.text_to_speech import gerar_audio_elevenlabs
from routes.media_route import media_routes
from routes.audio_route import audio_blueprint

from services.audio_processing import transcrever_audio_google
from pydub import AudioSegment
import os # Importar 'os' é necessário para acessar variáveis de ambiente
import uuid
import traceback
from dotenv import load_dotenv
from interfaces.web_interface import html_index
# Forçando rebuild no Render

load_dotenv()

app = Flask(__name__)

# Registra rotas externas
from routes.routes import routes

app.register_blueprint(routes)
app.register_blueprint(media_routes)
app.register_blueprint(audio_blueprint)


@app.route("/", methods=["GET"])
def index():
    return html_index()


# As linhas abaixo foram reposicionadas para fora da função 'index'.
# Elas devem estar no nível mais externo do seu arquivo.
if __name__ == "__main__":
    # --- Linha ALTERADA para usar a porta do ambiente Render.com (10000) ---
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
    # --- Fim da linha ALTERADA ---