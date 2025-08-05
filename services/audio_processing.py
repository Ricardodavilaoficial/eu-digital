import os
import io
import json
import traceback
from google.cloud import speech
from google.oauth2 import service_account
from pydub import AudioSegment


def get_speech_client():
    """
    Inicializa o cliente da Google Cloud Speech usando credenciais do JSON embutido ou do ambiente.
    """
    if 'GOOGLE_APPLICATION_CREDENTIALS_JSON' in os.environ:
        try:
            creds_info = json.loads(os.environ['GOOGLE_APPLICATION_CREDENTIALS_JSON'])
            credentials = service_account.Credentials.from_service_account_info(creds_info)
            return speech.SpeechClient(credentials=credentials)
        except Exception as e:
            print(f"❌ Erro ao carregar credenciais GCS: {e}")
            traceback.print_exc()
    else:
        print("⚠️ Variável GOOGLE_APPLICATION_CREDENTIALS_JSON não encontrada. Usando fallback padrão.")

    try:
        return speech.SpeechClient()
    except Exception as e:
        print(f"❌ Erro ao inicializar GCS Client: {e}")
        traceback.print_exc()
        return None


speech_client = get_speech_client()


def transcrever_audio_google(audio_bytes_or_path, idioma="pt-BR"):
    """
    Transcreve áudio usando a API Google Cloud Speech-to-Text.
    """
    try:
        if not speech_client:
            print("❌ SpeechClient não inicializado.")
            return ""

        content = None
        if isinstance(audio_bytes_or_path, bytes):
            content = audio_bytes_or_path
        elif isinstance(audio_bytes_or_path, str):
            with open(audio_bytes_or_path, "rb") as audio_file:
                content = audio_file.read()
        else:
            print("❌ Formato de áudio inválido. Esperado bytes ou caminho para arquivo.")
            return ""

        if not content:
            print("⚠️ Conteúdo de áudio vazio.")
            return ""

        audio = speech.RecognitionAudio(content=content)

        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code=idioma,
        )

        response = speech_client.recognize(config=config, audio=audio)

        transcricao = " ".join(result.alternatives[0].transcript for result in response.results)
        return transcricao.strip()

    except Exception as e:
        print(f"❌ Erro ao transcrever áudio: {e}")
        traceback.print_exc()
        return ""


def converter_para_wav(audio_file_path):
    """
    Converte um arquivo de áudio para WAV usando pydub.
    """
    try:
        audio = AudioSegment.from_file(audio_file_path)
        wav_file_path = audio_file_path.rsplit(".", 1)[0] + ".wav"
        audio.export(wav_file_path, format="wav")
        return wav_file_path
    except Exception as e:
        print(f"❌ Erro ao converter áudio para WAV: {e}")
        traceback.print_exc()
        return None


def processar_audio(caminho_arquivo):
    """
    Processa um arquivo de áudio: converte para WAV e transcreve.
    """
    try:
        wav_path = converter_para_wav(caminho_arquivo)
        if not wav_path:
            raise Exception("Falha ao converter para WAV.")
        
        texto = transcrever_audio_google(wav_path)
        return texto
    except Exception as e:
        print(f"❌ Erro no processamento de áudio: {e}")
        traceback.print_exc()
        return ""
