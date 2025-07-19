import os
import tempfile
from elevenlabs import generate, save, set_api_key

# Define a chave da ElevenLabs a partir do .env
set_api_key(os.getenv("ELEVEN_API_KEY"))


# Função única para gerar áudio com ElevenLabs
def gerar_audio_elevenlabs(texto):
    audio = generate(
        text=texto,
        voice=
        "Ricardo Original",  # Certifique-se de que o nome corresponde ao que está salvo no ElevenLabs
        model="eleven_multilingual_v2")
    caminho_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    save(audio, caminho_temp.name)
    return caminho_temp.name
