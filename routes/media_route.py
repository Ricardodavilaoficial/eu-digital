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

        elif tipo == "audio" and
