# routes/media_route.py

from flask import Blueprint, request, jsonify, send_file
from services.openai_handler import obter_resposta_openai
from services.text_to_speech import gerar_audio_elevenlabs
from services.audio_processing import transcrever_audio_google
from services.gcs_handler import bucket
import uuid
import os
from pydub import AudioSegment
import mimetypes
import traceback

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

            audio = AudioSegment.from_file(caminho_webm)
            audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            audio.export(caminho_wav, format="wav")

            texto_transcrito = transcrever_audio_google(caminho_wav)
            resposta = obter_resposta_openai(texto_transcrito)
            caminho_audio = gerar_audio_elevenlabs(resposta)

            return jsonify({
                "transcricao": texto_transcrito,
                "mensagem": resposta,
                "audio": caminho_audio
            })

        elif tipo in ["imagem", "pdf", "video"] and arquivo:
            nome_arquivo = f"uploads/{usuario}/{uuid.uuid4()}_{arquivo.filename}"
            blob = bucket.blob(nome_arquivo)
            blob.upload_from_file(arquivo)

            resposta = f"Recebi seu arquivo aqui 🤙 Assim que possível dou uma olhada nisso!"
            caminho_audio = gerar_audio_elevenlabs(resposta)

            return jsonify({
                "mensagem": resposta,
                "audio": caminho_audio
            })

        else:
            return jsonify({"erro": "Formato de mensagem não reconhecido ou incompleto."}), 400

    except Exception as e:
        traceback.print_exc()
        return jsonify({"erro": f"Erro ao processar mensagem: {e}"}), 500


# ✅ NOVA ROTA /audio para o botão do HTML
@media_route.route("/audio", methods=["POST"])
def receber_audio():
    try:
        print("🧪 Arquivos recebidos:", request.files)  # DEBUG no Render
        if "file" not in request.files:
            return jsonify({"erro": "
