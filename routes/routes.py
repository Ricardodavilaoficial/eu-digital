from flask import Blueprint, request, send_file, jsonify
from services.audio_processing import transcrever_audio_google
from services.openai_handler import obter_resposta_openai
from services.text_to_speech import gerar_audio_elevenlabs
from interfaces.web_interface import html_index
import uuid
from pydub import AudioSegment
import traceback

routes = Blueprint("routes", __name__)

@routes.route("/", methods=["GET"])
def index():
    return html_index()

@routes.route("/audio", methods=["POST"])
def processar_audio():

    try:
        print("📥 POST /audio recebido")
        print("🔍 request.content_type:", request.content_type)
        print("🔍 request.files.keys():", list(request.files.keys()))
        print("🔍 request.form.keys():", list(request.form.keys()))

        print("📥 request.content_type:", request.content_type)
        print("📥 request.files:", request.files)
        print("📥 request.form:", request.form)
        if not audio_file:
            print("🚫 Nenhum arquivo encontrado no campo 'audio' ou 'file'")
            return jsonify({"error": "Nenhum arquivo de áudio enviado"}), 400

        unique_id = str(uuid.uuid4())
        caminho_original = f"/tmp/{unique_id}_original.webm"
        caminho_wav = f"/tmp/{unique_id}.wav"

        with open(caminho_original, "wb") as f:
            f.write(audio_file.read())

        print("🔄 Convertendo .webm para .wav")
        audio = AudioSegment.from_file(caminho_original)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        audio.export(caminho_wav, format="wav")

        print("📝 Transcrevendo áudio...")
        texto = transcrever_audio_google(caminho_wav)
        print(f"📄 Texto transcrito: {texto}")

        if not texto:
            return jsonify({"error": "Não foi possível transcrever o áudio"}), 400

        resposta = obter_resposta_openai(texto)
        print(f"🤖 Resposta da IA: {resposta}")

        caminho_resposta_audio = gerar_audio_elevenlabs(resposta)
        print(f"🔊 Áudio gerado: {caminho_resposta_audio}")

        return send_file(caminho_resposta_audio, mimetype="audio/mpeg")

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
