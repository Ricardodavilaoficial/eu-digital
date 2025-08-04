from flask import Blueprint, request, send_file, jsonify
from services.audio_processing import transcrever_audio_google
from services.openai_handler import obter_resposta_openai
from services.text_to_speech import gerar_audio_elevenlabs
from interfaces.web_interface import html_index
import uuid
from pydub import AudioSegment
import traceback

# Define um blueprint para rotas
routes = Blueprint("routes", __name__)

# Rota principal (interface web)
@routes.route("/", methods=["GET"])
def index():
    return html_index()

# Rota para processar o áudio enviado pelo usuário
@routes.route("/audio", methods=["POST"])
def processar_audio():
    try:
        print("📥 Requisição recebida em /audio")
        print("🔍 request.files:", request.files)
        print("🔍 request.form:", request.form)
        print("🔍 request.content_type:", request.content_type)

        # Captura o arquivo de áudio enviado (corrigido para 'audio')
        audio_file = request.files.get("audio")
        if not audio_file:
            return jsonify({"error": "Nenhum arquivo de áudio enviado"}), 400

        # Gera caminhos únicos para os arquivos temporários
        unique_id = str(uuid.uuid4())
        caminho_original = f"/tmp/{unique_id}_original.webm"
        caminho_wav = f"/tmp/{unique_id}.wav"

        # Salva o áudio enviado
        with open(caminho_original, "wb") as f:
            f.write(audio_file.read())

        # Converte par
