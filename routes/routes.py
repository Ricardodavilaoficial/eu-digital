from flask import Blueprint, request, send_file, jsonify
from services.audio_processing import transcrever_audio_google
from services.openai_handler import obter_resposta_openai
from services.text_to_speech import gerar_audio_elevenlabs
from interfaces.web_interface import html_index
import uuid
import traceback
import os
import shutil
from pydub import AudioSegment

routes = Blueprint("routes", __name__)

@routes.route("/", methods=["GET"])
def index():
    return html_index()

@routes.route("/audio", methods=["POST"])
def processar_audio():
    try:
        print("📥 POST /audio recebido")
        print("📎 request.files:", request.files)
        print("📎 request.form:", request.form)
        print("📎 request.content_type:", request.content_type)
        print("📎 request.mimetype:", request.mimetype)
        print("📎 request.headers:", request.headers)

        if 'audio' not in request.files:
            print("❌ Campo 'audio' não encontrado em request.files")
            return jsonify({"error": "Campo 'audio' não encontrado no form-data"}), 400

        audio_file = request.files['audio']

        if audio_file.filename == "":
            print("❌ Nome de arquivo vazio")
            return jsonify({"error": "Arquivo de áudio inválido"}), 400
