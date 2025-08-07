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

# Página inicial renderizada pela interface HTML (usada em testes locais ou debug)
@routes.route("/", methods=["GET"])
def index():
    return html_index()

# Rota para processar um áudio recebido (ex: do WhatsApp ou formulário)
@routes.route("/audio", methods=["POST"])
def processar_audio():
    try:
        print("📥 POST /audio recebido")
        print("🔍 request.files:", request.files)
        print("🔍 request.form:", request.form)
        print("🔍 request.content_type:", request.content_type)
        print("🔍 request.mimetype:", request.mimetype)
        print("🔍 request.headers:", request.headers)

        # Verifica se veio algum arquivo chamado 'audio' no form-data
        if 'audio' not in request.files:
            print("🚫 Campo 'audio' não encontrado em request.files")
            return jsonify({"error": "Campo 'audio' não encontrado no form-data"}), 400

        audio_file = request.files['audio']

        if audio_file.filename == "":
            print("🚫 Nome de arquivo vazio")
            return jsonify({"error": "Arquivo de áudio inválido"}), 400

        # Gera caminho único e temporário para salvar o áudio
        unique_id = str(uuid.uuid4())
        caminho_original = f"/tmp/{unique_id}.webm"
        caminho_wav = f"/tmp/{unique_id}.wav"
        audio_file.save(caminho_original)
        print(f"💾 Áudio salvo em: {caminho_original}")

        # Converte para WAV com padrão ideal para STT
        print("🔄 Convertendo .webm para .wav")
        audio = AudioSegment.from_file(caminho_original)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        audio.export(caminho_wav, format="wav")
        print(f"✅ Conversão concluída: {caminho_wav}")

        # Transcreve o áudio com Google STT
        print("📝 Transcrevendo áudio...")
        texto = transcrever_audio_google(caminho_wav)
        print(f"📄 Texto transcrito: '{texto}'")

        if not texto or len(texto.strip()) == 0:
            print("⚠️ Transcrição vazia ou falhou.")
            return jsonify({"error": "Não foi possível transcrever o áudio"}), 400

        # Gera resposta via OpenAI
        resposta = obter_resposta_openai(texto)
        print(f"🤖 Resposta da IA: '{resposta}'")

        # Converte a resposta em áudio (voz clonada do cliente)
        caminho_audio_resposta = gerar_audio_elevenlabs(resposta)
        print(f"🔊 Caminho do áudio gerado: {caminho_audio_resposta}")

        # Retorna o áudio para o frontend
        return send_file(caminho_audio_resposta, mimetype="audio/mpeg")

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Erro interno: {str(e)}"}), 500
