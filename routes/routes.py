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
        print("🔍 request.form:", request.form)
        print("🔍 request.content_type:", request.content_type)
        print("🔍 request.mimetype:", request.mimetype)
        print("🔍 request.headers:", request.headers)

        # Verifica se veio algum arquivo
        if 'audio' not in request.files:
            print("🚫 Campo 'audio' não encontrado em request.files")
            return jsonify({"error": "Campo 'audio' não encontrado no form-data"}), 400

        audio_file = request.files['audio']

        if audio_file.filename == "":
            print("🚫 Nome de arquivo vazio")
            return jsonify({"error": "Arquivo de áudio inválido"}), 400

        # Gera caminhos únicos
        unique_id = str(uuid.uuid4())
        caminho_original = f"/tmp/{unique_id}.webm"
        caminho_wav = f"/tmp/{unique_id}.wav"
        caminho_debug_wav = f"/tmp/debug_audios/{unique_id}.wav"

        # Salva o arquivo original
        audio_file.save(caminho_original)
        print(f"💾 Áudio .webm salvo em: {caminho_original}")

        # Converte para .wav
        print("🔄 Convertendo .webm para .wav...")
        audio = AudioSegment.from_file(caminho_original)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        audio.export(caminho_wav, format="wav")
        print(f"✅ Convertido para WAV: {caminho_wav}")

        # Salva uma cópia para debug
        os.makedirs("/tmp/debug_audios", exist_ok=True)
        os.system(f"cp {caminho_wav} {caminho_debug_wav}")
        print(f"🧪 Copia de debug salva em: {caminho_debug_wav}")

        # Transcreve o áudio
        print("📝 Enviando para transcrição...")
        texto = transcrever_audio_google(caminho_wav)
        print(f"📄 Texto transcrito: '{texto}'")

        if not texto or texto.strip() == "":
            print("⚠️ Transcrição vazia ou inaudível.")
            return jsonify({"error": "Não foi possível transcrever o áudio"}), 400

        # IA responde
        resposta = obter_resposta_openai(texto)
        print("🤖 Resposta da IA:", resposta)

        # Converte resposta em áudio
        caminho_audio_resposta = gerar_audio_elevenlabs(resposta)
        print("🔊 Caminho do áudio gerado:", caminho_audio_resposta)

        return send_file(caminho_audio_resposta, mimetype="audio/mpeg")

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Erro interno: {str(e)}"}), 500
