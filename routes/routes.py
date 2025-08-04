from flask import Blueprint, request, send_file, jsonify
from services.audio_processing import transcrever_audio_google
from services.openai_handler import obter_resposta_openai
from services.text_to_speech import gerar_audio_elevenlabs
from interfaces.web_interface import html_index
import uuid
from pydub import AudioSegment
import traceback
import os

routes = Blueprint("routes", __name__)

@routes.route("/", methods=["GET"])
def index():
    return html_index()

@routes.route("/audio", methods=["POST"])
def processar_audio():
    try:
        print("📥 POST /audio recebido")
        print("🔍 request.files:", request.files)

        audio_file = request.files.get("audio")
        if not audio_file:
            return jsonify({"error": "Nenhum arquivo de áudio enviado"}), 400

        unique_id = str(uuid.uuid4())
        caminho_original = f"/tmp/{unique_id}.webm"
        caminho_wav = f"/tmp/{unique_id}.wav"

        audio_file.save(caminho_original)

        print("🔄 Convertendo .webm para .wav")
        audio = AudioSegment.from_file(caminho_original)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        audio.export(caminho_wav, format="wav")

        print("📝 Transcrevendo áudio...")
        texto = transcrever_audio_google(caminho_wav)
        print("📄 Texto transcrito:", texto)

        if not texto:
            return jsonify({"error": "Não foi possível transcrever o áudio"}), 400

        resposta = obter_resposta_openai(texto)
        print("🤖 Resposta da IA:", resposta)

        caminho_audio_resposta = gerar_audio_elevenlabs(resposta)
        print("🔊 Caminho do áudio gerado:", caminho_audio_resposta)

        return send_file(caminho_audio_resposta, mimetype="audio/mpeg")

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Erro interno: {str(e)}"}), 500
