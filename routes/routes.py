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
        print("🔍 request.files:", request.files)
        print("🔍 request.form:", request.form)

        # Tenta obter o arquivo com os dois nomes possíveis
        audio_file = request.files.get("audio") or request.files.get("file")
        if not audio_file:
            print("🚫 Nenhum arquivo encontrado no campo 'audio' ou 'file'")
            return jsonify({"error": "Nenhum arquivo de áudio enviado"}), 400

        # Gera caminhos temporários únicos
        unique_id = str(uuid.uuid4())
        caminho_original = f"/tmp/{unique_id}_original.webm"
        caminho_wav = f"/tmp/{unique_id}.wav"

        # Salva o arquivo .webm temporário
        with open(caminho_original, "wb") as f:
            f.write(audio_file.read())

        # Converte para WAV
        print("🔄 Convertendo .webm para .wav")
        audio = AudioSegment.from_file(caminho_original)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        audio.export(caminho_wav, format="wav")

        # Transcrição
        print("📝 Transcrevendo áudio...")
        texto = transcrever_audio_google(caminho_wav)
        print(f"📄 Texto transcrito: {texto}")

        if not texto:
            return jsonify({"error": "Não foi possível transcrever o áudio"}), 400

        # Geração da resposta com OpenAI
        resposta = obter_resposta_openai(texto)
        print(f"🤖 Resposta da IA: {resposta}")

        # Geração de áudio com ElevenLabs
        caminho_resposta_audio = gerar_audio_elevenlabs(resposta)
        print(f"🔊 Áudio gerado: {caminho_resposta_audio}")

        # Retorno final
        return send_file(caminho_resposta_audio, mimetype="audio/mpeg")

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500