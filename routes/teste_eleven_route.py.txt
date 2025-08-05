from flask import Blueprint, request, send_file, jsonify
import requests
import os
import io

teste_eleven_route = Blueprint('teste_eleven_route', __name__)

@teste_eleven_route.route('/teste-eleven', methods=['GET'])
def teste_eleven():
    texto = request.args.get('texto', 'Teste de voz')
    voice_id = os.getenv('ELEVEN_VOICE_ID')  # ID da voz clonada ou padrão
    api_key = os.getenv('ELEVEN_API_KEY')    # Sua chave da ElevenLabs

    if not api_key or not voice_id:
        return jsonify({"erro": "Chave ou Voice ID ausentes"}), 500

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json"
    }
    body = {
        "text": texto,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.5
        }
    }

    try:
        response = requests.post(url, headers=headers, json=body)
        response.raise_for_status()
        audio_data = io.BytesIO(response.content)
        return send_file(audio_data, mimetype="audio/mpeg", as_attachment=True, download_name="teste.mp3")
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
