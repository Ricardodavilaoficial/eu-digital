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
        # Captura o arquivo de áudio enviado
        audio_file = request.files.get("file")
        if not audio_file:
            return jsonify({"error": "Nenhum arquivo de áudio enviado"}), 400

        # Gera caminhos únicos para os arquivos temporários
        unique_id = str(uuid.uuid4())
        caminho_original = f"/tmp/{unique_id}_original.webm"
        caminho_wav = f"/tmp/{unique_id}.wav"

        # Salva o áudio enviado
        with open(caminho_original, "wb") as f:
            f.write(audio_file.read())

        # Converte para WAV compatível com a API de transcrição
        audio = AudioSegment.from_file(caminho_original)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        audio.export(caminho_wav, format="wav")

        # Transcreve o áudio para texto
        texto = transcrever_audio_google(caminho_wav)
        if not texto:
            return jsonify({"error": "Não foi possível transcrever o áudio"}), 400

        # Consulta o OpenAI com o texto transcrito
        resposta = obter_resposta_openai(texto)

        # Gera a resposta em áudio com a voz clonada
        caminho_resposta_audio = gerar_audio_elevenlabs(resposta)

        # Retorna o áudio gerado para o navegador
        return send_file(caminho_resposta_audio, mimetype="audio/mpeg")

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
