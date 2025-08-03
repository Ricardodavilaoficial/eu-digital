from flask import Blueprint, request, jsonify, send_file
from services.openai_handler import obter_resposta_openai
from services.text_to_speech import gerar_audio_elevenlabs
from services.audio_processing import transcrever_audio_google
from services.gcs_handler import bucket
import uuid
import os
from pydub import AudioSegment
from pydub.utils import which
import mimetypes
import traceback

# 🔧 Corrige o caminho do ffmpeg no ambiente Render
AudioSegment.converter = which("ffmpeg")

media_route = Blueprint("media_route", __name__)

@media_route.route("/mensagem", methods=["POST"])
def receber_mensagem():
    try:
        tipo = request.form.get("tipo")  # texto, audio, imagem, pdf...
        usuario = request.form.get("usuario") or "cliente_desconhecido"
        arquivo = request.files.get("file")
        texto = request.form.get("texto")

        if tipo == "texto" and texto:
            resposta = obter_resposta_openai(texto)
            caminho_audio = gerar_audio_elevenlabs(resposta)
            return jsonify({
                "mensagem": resposta,
                "audio": caminho_audio
            })

        elif tipo == "audio" and arquivo:
            temp_id = str(uuid.uuid4())
            caminho_webm = f"/tmp/{temp_id}.webm"
            caminho_wav = f"/tmp/{temp_id}.wav"

            with open(caminho_webm, "wb") as f:
                f.write(arquivo.read())

            try:
                print("📥 Tentando abrir áudio com pydub (formato webm)...")
                audio = AudioSegment.from_file(caminho_webm, format="webm")
                audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
                audio.export(caminho_wav, format="wav")
            except Exception as e:
                print("❌ Erro ao processar áudio webm:", e)
                return jsonify({"erro": f"Erro ao converter áudio: {e}"}), 500

            texto_transcrito = transcrever_audio_google(caminho_wav)
            resposta = obter_resposta_openai(texto_transcrito)
            caminho_audio = gerar_audio_elevenlabs(resposta)

            return jsonify({
                "transcricao": texto_transcrito,
                "mensagem": resposta,
                "audio": caminho_audio
