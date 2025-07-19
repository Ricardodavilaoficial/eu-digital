from google.cloud import speech
from google.oauth2 import service_account
import os

credentials = service_account.Credentials.from_service_account_file(
    "gcloud-key.json")

speech_client = speech.SpeechClient(credentials=credentials)


def transcrever_audio_google(caminho_wav):
    with open(caminho_wav, "rb") as audio_file:
        content = audio_file.read()

    audio = speech.RecognitionAudio(content=content)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code="pt-BR",
    )

    response = speech_client.recognize(config=config, audio=audio)

    for result in response.results:
        return result.alternatives[0].transcript

    return ""
