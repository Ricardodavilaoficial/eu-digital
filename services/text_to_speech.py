# services/text_to_speech.py

import os
import tempfile
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs import Voice, VoiceSettings

load_dotenv() # Carrega as variáveis do .env (para uso local)

# Obter a chave da ElevenLabs da variável de ambiente
# É CRÍTICO que esta variável (ELEVEN_API_KEY) seja configurada no Render.com também!
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")

if not ELEVEN_API_KEY:
    print("ERRO: Variável de ambiente ELEVEN_API_KEY não configurada!")
    # No Render, isso causará um erro se não estiver configurado lá.

# Inicializa o cliente ElevenLabs. A autenticação agora é feita aqui.
client = ElevenLabs(api_key=ELEVEN_API_KEY)

# Função única para gerar áudio com ElevenLabs
def gerar_audio_elevenlabs(texto):
    try:
        # A ElevenLabs API agora usa 'client.generate' ou 'client.audio.generate'
        # e aceita um objeto Voice. Você pode definir a Voice ID diretamente aqui.
        # "Ricardo Original" deve ser o ID da sua voz personalizada no ElevenLabs.
        audio_data = client.audio.generate(
            text=texto,
            voice=Voice(
                voice_id="pTx3O7lpdS2VfDrrK4Gl", # Este é o ID da voz "Ricardo" que você tem
                name="Ricardo Original", # Nome da voz (opcional, mas bom para clareza)
                settings=VoiceSettings(stability=0.75, similarity_boost=0.75, style=0.0, use_speaker_boost=True) # Ajuste estes parâmetros se precisar
            ),
            model="eleven_multilingual_v2" # Modelo de voz (pode ser "eleven_english_v2", etc.)
        )

        # O objeto retornado agora tem um método .save() ou o conteúdo pode ser acessado via .content
        caminho_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        
        # Salva o áudio no arquivo temporário. 'audio_data' é um objeto ResponseBytes.
        with open(caminho_temp.name, "wb") as f:
            f.write(audio_data.content) # Acessa o conteúdo binário do áudio

        return caminho_temp.name

    except Exception as e:
        print(f"Erro ao gerar áudio com ElevenLabs: {e}")
        return None

# Você pode manter este bloco para testes locais, se desejar.
if __name__ == "__main__":
    print("Testando geração de áudio ElevenLabs localmente...")
    if ELEVEN_API_KEY:
        try:
            temp_audio_file = gerar_audio_elevenlabs("Olá, Ricardo, este é um teste de áudio com a sua nova função.")
            if temp_audio_file:
                print(f"Áudio gerado e salvo em: {temp_audio_file}")
                # Aqui você pode adicionar lógica para reproduzir ou limpar o arquivo temporário
                # import soundfile as sf
                # import sounddevice as sd
                # audio_data, samplerate = sf.read(temp_audio_file)
                # sd.play(audio_data, samplerate)
                # sd.wait()
                # os.remove(temp_audio_file) # Limpa o arquivo após o teste
            else:
                print("Falha ao gerar áudio de teste.")
        except Exception as e:
            print(f"Erro durante o teste local: {e}")
    else:
        print("ElevenLabs API Key não configurada para teste local.")