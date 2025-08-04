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
        # Tenta pegar tanto "audio" quanto "file"
        audio_file = request.files.get("audio") or request.files.get("file")
        if not audio_file:
            return jsonify({"error": "Nenhum arquivo de áudio enviado"}), 400

        # Gera caminhos únicos para os arquivos temporários
        unique_id = str(uuid.uuid4())
        caminho_original = f"/tmp/{unique_id}_original.webm"
        caminho_wav = f"/tmp/{unique_id}.wav"

        with open(caminho_original, "wb") as f:
            f.write(audio_file.read())

        # Converte para WAV
        audio = AudioSegment.from_file(caminho_original)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        audio.export(caminho_wav, format="wav")

        texto = transcrever_audio_google(caminho_wav)
        if not texto:
            return jsonify({"error": "Não foi possível transcrever o áudio"}), 400

        resposta = obter_resposta_openai(texto)
        caminho_resposta_audio = gerar_audio_elevenlabs(resposta)

        return send_file(caminho_resposta_audio, mimetype="audio/mpeg")

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
