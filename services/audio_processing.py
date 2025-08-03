# services/audio_processing.py

import os
import io # Mantenha para uso com BytesIO, se necessário
import json # Adicionado para lidar com JSON da variável de ambiente
from google.cloud import speech
from google.oauth2 import service_account # Adicionado para autenticação via JSON
from pydub import AudioSegment # Necessário se você usar converter_para_wav ou lidar com áudio


# --- Início da correção para autenticação no Render.com ---

def get_speech_client():
    # Tenta carregar credenciais da variável de ambiente JSON do Render
    if 'GOOGLE_APPLICATION_CREDENTIALS_JSON' in os.environ:
        try:
            creds_info = json.loads(os.environ['GOOGLE_APPLICATION_CREDENTIALS_JSON'])
            credentials = service_account.Credentials.from_service_account_info(creds_info)
            return speech.SpeechClient(credentials=credentials)
        except Exception as e:
            print(f"Erro ao carregar credenciais da variável de ambiente GOOGLE_APPLICATION_CREDENTIALS_JSON para Speech: {e}")
            # Fallback: tenta carregar automaticamente (útil para ambientes GCP ou credenciais locais)
            return speech.SpeechClient()
    else:
        # Se a variável de ambiente não estiver definida (ex: em desenvolvimento local),
        # o cliente tentará autenticação padrão ou via GOOGLE_APPLICATION_CREDENTIALS apontando para um arquivo local.
        # Imprime um aviso, mas permite que o app tente iniciar.
        print("Variável de ambiente 'GOOGLE_APPLICATION_CREDENTIALS_JSON' não encontrada. Tentando autenticação padrão para Google Speech-to-Text.")
        return speech.SpeechClient()

# Inicializa o cliente de Speech usando a função acima.
# Esta linha substitui suas antigas linhas de autenticação.
speech_client = get_speech_client()

# --- Fim da correção para autenticação no Render.com ---


def transcrever_audio_google(audio_bytes_or_path, idioma="pt-BR"):
    """
    Transcreve áudio usando a API Google Cloud Speech-to-Text.
    Aceita tanto bytes de áudio quanto um caminho para arquivo (se for o caso).

    Args:
        audio_bytes_or_path (bytes ou str): O conteúdo de áudio em bytes ou o caminho para o arquivo.
        idioma (str): O idioma do áudio (padrão é "pt-BR").

    Returns:
        str: O texto transcrito ou uma string vazia em caso de erro.
    """
    content = None
    if isinstance(audio_bytes_or_path, bytes):
        content = audio_bytes_or_path
    elif isinstance(audio_bytes_or_path, str):
        # Se for um caminho, abre e lê o arquivo
        try:
            with open(audio_bytes_or_path, "rb") as audio_file:
                content = audio_file.read()
        except FileNotFoundError:
            print(f"Erro: Arquivo de áudio não encontrado em {audio_bytes_or_path}")
            return ""
        except Exception as e:
            print(f"Erro ao ler arquivo de áudio {audio_bytes_or_path}: {e}")
            return ""
    else:
        print("Erro: Entrada de áudio inválida. Esperado bytes ou caminho de arquivo.")
        return ""

    if not content:
        return ""

    audio = speech.RecognitionAudio(content=content)

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16, # Mantido conforme seu código original
        sample_rate_hertz=16000, # Mantido conforme seu código original
        language_code=idioma,
    )

    try:
        response = speech_client.recognize(config=config, audio=audio)

        transcricao = ""
        for result in response.results:
            transcricao += result.alternatives[0].transcript + " "
        return transcricao.strip()

    except Exception as e:
        print(f"Erro ao transcrever áudio com Google Speech-to-Text: {e}")
        return ""

# Função de conversão para WAV (mantida, caso seu main.py a use)
def converter_para_wav(audio_file_path):
    """
    Converte um arquivo de áudio para WAV usando pydub.
    """
    try:
        audio = AudioSegment.from_file(audio_file_path)
        wav_file_path = audio_file_path.replace(".mp3", ".wav").replace(".ogg", ".wav") # Ajuste para diferentes extensões
        audio.export(wav_file_path, format="wav")
        return wav_file_path
    except Exception as e:
        print(f"Erro ao converter áudio para WAV com Pydub: {e}")
        return None
        # 🔧 Função adicionada para compatibilidade com audio_route.py
def processar_audio(caminho_arquivo):
    """
    Processa um arquivo de áudio: converte para WAV e transcreve.
    Retorna o texto transcrito.
    """
    try:
        wav_path = converter_para_wav(caminho_arquivo)
        if not wav_path:
            raise Exception("Falha ao converter para WAV.")
        
        texto = transcrever_audio_google(wav_path)
        return texto
    except Exception as e:
        print(f"Erro no processamento de áudio: {e}")
        return ""
