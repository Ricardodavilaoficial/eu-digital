import os
import tempfile
import traceback
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs import Voice, VoiceSettings

# Carrega variáveis do .env
load_dotenv()

# Obtém a chave da ElevenLabs
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")

if not ELEVEN_API_KEY:
    print("❌ ERRO: Variável de ambiente ELEVEN_API_KEY não configurada!")

# Instancia o cliente ElevenLabs
client = ElevenLabs(api_key=ELEVEN_API_KEY)

def gerar_audio_elevenlabs(texto):
    """
    Gera um arquivo de áudio .mp3 com a voz do Ricardo via ElevenLabs.
    Retorna o caminho do arquivo gerado ou None em caso de erro.
    """
    try:
        if not ELEVEN_API_KEY:
            raise Exception("Chave da ElevenLabs não configurada.")

        audio_data = client.generate(
            text=texto,
            voice=Voice(
                voice_id="yNI0cEjjllppsJrp9PWG",
                settings=VoiceSettings(
                    stability=0.75,
                    similarity_boost=0.75,
                    style=0.0,
                    use_speaker_boost=True
                )
            ),
            model="eleven_multilingual_v2"
        )

        # Cria arquivo temporário com áudio
        caminho_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        with open(caminho_temp.name, "wb") as f:
            for chunk in audio_data:
                f.write(chunk)

        return caminho_temp.name

    except Exception as e:
        print(f"❌ Erro ao gerar áudio com ElevenLabs: {e}")
        traceback.print_exc()
        return None


if __name__ == "__main__":
    print("🔊 Testando geração de áudio ElevenLabs localmente...")
    temp_audio_file = gerar_audio_elevenlabs("Olá, Ricardo, este é um teste com a nova função.")
    if temp_audio_file:
        print(f"✅ Áudio gerado em: {temp_audio_file}")
    else:
        print("⚠️ Falha ao gerar áudio.")

