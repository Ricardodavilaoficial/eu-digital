# services/audio_processing.py
import os, io, json, logging, traceback
from typing import Optional
from google.cloud import speech
from google.oauth2 import service_account

# --- Client Google Speech ---
def _get_speech_client() -> Optional[speech.SpeechClient]:
    # Tenta credencial inline JSON (GOOGLE_APPLICATION_CREDENTIALS_JSON)
    try:
        js = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        if js:
            info = json.loads(js)
            creds = service_account.Credentials.from_service_account_info(info)
            logging.info("[GCS] Using inline JSON credentials.")
            return speech.SpeechClient(credentials=creds)
    except Exception as e:
        logging.info("[GCS] inline creds failed: %s", e)

    # Fallback: usa GOOGLE_APPLICATION_CREDENTIALS (arquivo) ou ADC
    try:
        return speech.SpeechClient()
    except Exception as e:
        logging.error("[GCS] SpeechClient init error: %s", e)
        return None

_speech_client = _get_speech_client()

# --- Utils: converter para WAV 16k mono (se possível) ---
def _to_wav16k(audio_bytes: bytes, mime_type: str = "audio/ogg") -> Optional[bytes]:
    """
    Converte com pydub/ffmpeg para WAV 16k mono. Se não der, retorna None.
    """
    try:
        from pydub import AudioSegment  # requer ffmpeg instalado na imagem
        seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format=None)  # deixa pydub detectar
        seg = seg.set_frame_rate(16000).set_channels(1)
        out = io.BytesIO()
        seg.export(out, format="wav")
        return out.getvalue()
    except Exception as e:
        logging.info("[STT] _to_wav16k fallback (sem pydub/ffmpeg): %s", e)
        return None

# --- STT principal (bytes) ---
def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = "pt-BR") -> str:
    """
    Transcreve bytes de áudio usando Google Cloud Speech.
    Preferimos converter para WAV 16k LINEAR16 (mais estável).
    """
    if not audio_bytes:
        return ""
    if not _speech_client:
        logging.error("[STT] Speech client unavailable.")
        return ""

    # Tenta converter para WAV 16k mono (LINEAR16). Se falhar, tenta direto.
    wav = _to_wav16k(audio_bytes, mime_type=mime_type)
    try:
        if wav:
            audio = speech.RecognitionAudio(content=wav)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code=language,
            )
        else:
            # Fallback: tenta decodificação direta (OGG_OPUS costuma vir do WhatsApp)
            audio = speech.RecognitionAudio(content=audio_bytes)
            # Heurística leve para escolher encoding
            enc = speech.RecognitionConfig.AudioEncoding.OGG_OPUS if "ogg" in (mime_type or "").lower() else speech.RecognitionConfig.AudioEncoding.ENCODING_UNSPECIFIED
            config = speech.RecognitionConfig(
                encoding=enc,
                language_code=language,
            )

        resp = _speech_client.recognize(config=config, audio=audio)
        text = " ".join(alt.transcript for r in resp.results for alt in r.alternatives[:1]).strip()
        logging.info("[STT] ok len=%s", len(text))
        return text
    except Exception as e:
        logging.error("[STT] recognize error: %s", e)
        traceback.print_exc()
        return ""

# --- STT por caminho de arquivo ---
def transcribe_audio_file(path: str, language: str = "pt-BR") -> str:
    try:
        with open(path, "rb") as f:
            b = f.read()
        # tenta inferir mime por extensão
        ext = (os.path.splitext(path)[1] or "").lower()
        mime = "audio/ogg" if ext in (".ogg", ".oga") else ("audio/mpeg" if ext in (".mp3",) else "audio/wav")
        return transcribe_audio_bytes(b, mime_type=mime, language=language)
    except Exception as e:
        logging.error("[STT] file read error: %s", e)
        return ""

# --- ALIASES PÚBLICOS / COMPATIBILIDADE ---
def stt_transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = "pt-BR") -> str:
    return transcribe_audio_bytes(audio_bytes, mime_type=mime_type, language=language)

def speech_to_text(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = "pt-BR") -> str:
    return transcribe_audio_bytes(audio_bytes, mime_type=mime_type, language=language)

# compat antigo (esperado por routes/routes.py)
def transcrever_audio_google(audio_bytes_or_path, idioma: str = "pt-BR") -> str:
    """
    Compat: aceita bytes ou caminho e delega para a nova função.
    """
    try:
        if isinstance(audio_bytes_or_path, (bytes, bytearray)):
            return transcribe_audio_bytes(bytes(audio_bytes_or_path), mime_type="audio/ogg", language=idioma)
        if isinstance(audio_bytes_or_path, str):
            return transcribe_audio_file(audio_bytes_or_path, language=idioma)
    except Exception:
        pass
    return ""

# aliases extras comuns que o wa_bot procura dinamicamente
def transcrever_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = "pt-BR") -> str:
    return transcribe_audio_bytes(audio_bytes, mime_type=mime_type, language=language)  # chama a principal

def transcrever_audio(*args, **kwargs):
    # tenta mapear assinaturas variadas
    try:
        if args and isinstance(args[0], (bytes, bytearray)):
            return transcribe_audio_bytes(args[0], kwargs.get("mime_type", "audio/ogg"), kwargs.get("language", "pt-BR"))
        if args and isinstance(args[0], str):
            return transcribe_audio_file(args[0], kwargs.get("language", "pt-BR"))
    except Exception:
        pass
    return ""
