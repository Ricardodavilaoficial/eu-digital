# routes/audio_route.py

from flask import Blueprint, request, send_file
from services.audio_processing import processar_audio
import os
import uuid

audio_blueprint = Blueprint("audio", __name__)

@audio_blueprint.route("/audio", methods=["POST"])
def handle_audio():
    if "file" not in request.files:
        return "Arquivo de áudio não encontrado", 400

    arquivo = request.files["file"]
    if not arquivo:
        return "Arquivo inválido", 400

    nome_temp = f"temp_{uuid.uuid4()}.webm"
    caminho_temp = os.path.join("/tmp", nome_temp)
    arquivo.save(caminho_temp)

    caminho_resposta = processar_audio(caminho_temp)

    if not caminho_resposta:
        return "Erro ao processar o áudio", 500

    return send_file(caminho_resposta, mimetype="audio/mpeg")
