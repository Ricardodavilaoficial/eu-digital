from flask import Flask, request, send_file, render_template, jsonify
from services.openai_handler import obter_resposta_openai
from services.text_to_speech import gerar_audio_elevenlabs
from routes.media_route import media_route
from routes.audio_route import audio_blueprint

from services.audio_processing import transcrever_audio_google
from pydub import AudioSegment
import os
import uuid
import traceback
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Registra rotas externas
from routes.routes import routes

app.register_blueprint(routes)
app.register_blueprint(media_route, url_prefix="")  # Para funcionar em /audio
app.register_blueprint(audio_blueprint)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")  # Agora usa o HTML salvo na pasta templates

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
