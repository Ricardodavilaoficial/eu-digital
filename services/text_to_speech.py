import os
import tempfile
import traceback
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs import Voice, VoiceSettings

# Carrega variáveis do .env para ambiente local
load_dotenv()

# Obtém a chave da ElevenLabs da variável de ambiente
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")

if not ELEVEN_API_KEY:
    print("❌ ERRO: Variável de ambiente ELEVEN_API_KEY não configurada!")

# Inicializa o cliente ElevenLabs somente se a chave estiver definida
client = ElevenLabs(api_key=ELEVEN_API_KEY) if ELEVEN_API_KEY else None

def gerar_audio_elevenlabs(texto):
    """
    Gera um arquivo de áudio .mp3 com a voz do Ricardo via ElevenLabs.
    Retorna o caminho do arquivo gerado ou None em caso de erro.
    """
    try:
        if not client:
            raise Exception("Cliente ElevenLabs não configurado corretamente.")

        audio_data = client.audio.generate(
            text=texto,
            voice=Voice(
                voice_id="pTx3O7lpdS2VfDrrK4Gl",
                name="Ricardo Original",
                settings=VoiceSettings(
                    stability=0.75,
                    similarity_boost=0.75,
                    style=0.0,
                    use_speaker_boost=True
                )
            ),
            model="eleven_multilingual_v2"
        )

        caminho_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        with open(caminho_temp.name, "wb") as f:
            f.write(audio_data.content)

        return caminho_temp.name
