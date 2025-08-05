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
        print("\U0001F4E5 POST /audio recebido")
        print("\U0001F50D request.files:", request.files)
        print("\U0001F50D request.form:", request.form)
        print("\U0001F50D request.content_type:", request.content_type)
        print("\U0001F50D request.mimetype:", request.mimetype)
        print("\U0001F50D request.headers:", request.headers)

        if 'audio' not in request.files:
            print("\u274C Campo 'audio' não encontrado em request.files")
            return jsonify({"error": "Campo 'audio' não encontrado no form-data"}), 400

        audio_file = request.files['audio']

        if audio_file.filename == "":
            print("\u274C Nome de arquivo vazio")
            return jsonify({"error": "Arquivo de áudio inválido"}), 400

        unique_id = str(uuid.uuid4())
        caminho_original = f"/tmp/{unique_id}.webm"
        caminho_wav = f"/tmp/{unique_id}.wav"
        caminho_debug_wav = f"/tmp/debug_audios/{unique_id}.wav"

        audio_file.save(caminho_original)
        print(f"\U0001F4BE Áudio .webm salvo em: {caminho_original}")

        print("\U0001F504 Convertendo .webm para .wav...")
        audio = AudioSegment.from_file(caminho_original)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        audio.export(caminho_wav, format="wav")
        print(f"✅ Convertido para WAV: {caminho_wav}")

        os.makedirs("/tmp/debug_audios", exist_ok=True)
        os.system(f"cp {caminho_wav} {caminho_debug_wav}")
        print(f"\U0001F9EA Copia de debug salva em: {caminho_debug_wav}")

        print("\U0001F4DD Enviando para transcrição...")
        texto = transcrever_audio_google(caminho_wav)
        print(f"📄 Texto transcrito: '{texto}'")

        if not texto or texto.strip() == "":
            print("⚠️ Transcrição vazia ou inaudível.")
            return jsonify({"error": "Não foi possível transcrever o áudio"}), 400

        resposta = obter_resposta_openai(texto)
        print("🤖 Resposta da IA:", resposta)

        caminho_audio_resposta = gerar_audio_elevenlabs(resposta)
        print("\U0001F50A Caminho do áudio gerado:", caminho_audio_resposta)

        if not caminho_audio_resposta or not os.path.exists(caminho_audio_resposta):
            print("❌ Caminho do áudio não encontrado ou inválido!")
            return jsonify({"erro": "Falha ao gerar áudio com a IA"}), 500

        return send_file(caminho_audio_resposta, mimetype="audio/mpeg")

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Erro interno: {str(e)}"}), 500