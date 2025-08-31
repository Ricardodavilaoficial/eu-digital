# services/audio_processing.py
# STT (Speech-to-Text) tolerante e alinhado com wa_bot.py:
# - Prioriza Google Cloud Speech-to-Text (economia)
# - Fallback para OpenAI Whisper (se habilitado)
# - Aceita bytes ou caminho de arquivo
# - Converte para WAV 16k mono 16-bit PCM (LINEAR16) automaticamente
from __future__ import annotations

import os
import io
import re
import json
import logging
import traceback
import requests
from typing import Optional, Tuple

# -------- pydub para conversão de formatos --------
try:
    from pydub import AudioSegment  # type: ignore
    _PYDUB_OK = True
except Exception as e:
    logging.info("[audio_processing] pydub indisponível: %s", e)
    _PYDUB_OK = False

# -------- Google Cloud Speech --------
_GOOGLE_SPEECH_CLIENT = None
try:
    from google.cloud import speech  # type: ignore
    from google.oauth2 import service_account  # type: ignore
    _GOOGLE_SPEECH_IMPORTED = True
except Exception as e:
    logging.info("[audio_processing] google-cloud-speech indisponível: %s", e)
    _GOOGLE_SPEECH_IMPORTED = False

# -------- Config / ENV --------
LANG_DEFAULT = os.getenv("STT_LANGUAGE_CODE", "pt-BR")
ENABLE_STT_OPENAI = os.getenv("ENABLE_STT_OPENAI", "true").strip().lower() in ("1", "true", "yes")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
FORCE_STT_PROVIDER = (os.getenv("FORCE_STT_PROVIDER") or "").strip().lower()  # "google" | "whisper" | ""

MIME_TO_PYDUB = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "application/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "mp4",
    "audio/aac": "aac",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
}


# =============================================================================
# Google Speech client (cred em JSON por env, com fallbacks)
# =============================================================================
def _get_google_speech_client():
    global _GOOGLE_SPEECH_CLIENT
    if _GOOGLE_SPEECH_CLIENT:
        return _GOOGLE_SPEECH_CLIENT
    if not _GOOGLE_SPEECH_IMPORTED:
        return None

    # Tentativas de credenciais via env:
    creds_json = (
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        or os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        or os.getenv("FIREBASE_CREDENTIALS_JSON")
    )

    try:
        if creds_json:
            info = json.loads(creds_json)
            credentials = service_account.Credentials.from_service_account_info(info)
            _GOOGLE_SPEECH_CLIENT = speech.SpeechClient(credentials=credentials)
        else:
            # Usa credenciais do ambiente (GOOGLE_APPLICATION_CREDENTIALS path, workload identity etc.)
            _GOOGLE_SPEECH_CLIENT = speech.SpeechClient()
        return _GOOGLE_SPEECH_CLIENT
    except Exception as e:
        logging.exception("[audio_processing] Erro inicializando SpeechClient: %s", e)
        return None


# =============================================================================
# Helpers de áudio
# =============================================================================
def _guess_format_from_mime(mime_type: Optional[str]) -> Optional[str]:
    if not mime_type:
        return None
    key = mime_type.split(";")[0].strip().lower()
    return MIME_TO_PYDUB.get(key)


def _ensure_wav16k_mono(audio_bytes: bytes, mime_type: Optional[str]) -> Optional[bytes]:
    """
    Converte o binário recebido (ogg/mp3/etc) para WAV PCM 16kHz mono (LINEAR16).
    Retorna bytes do WAV pronto para Google STT.
    """
    if not _PYDUB_OK or not audio_bytes:
        return None
    try:
        buf_in = io.BytesIO(audio_bytes)
        fmt = _guess_format_from_mime(mime_type) or None
        # pydub tenta inferir se fmt=None, mas é melhor informar quando soubermos
        seg = AudioSegment.from_file(buf_in, format=fmt)
        seg = seg.set_frame_rate(16000).set_channels(1).set_sample_width(2)  # 16-bit
        out = io.BytesIO()
        seg.export(out, format="wav")
        return out.getvalue()
    except Exception as e:
        logging.info("[audio_processing] Conversão para WAV falhou: %s", e)
        return None


# =============================================================================
# Google STT
# =============================================================================
def _stt_google_from_bytes(audio_bytes: bytes, mime_type: Optional[str], language: str) -> str:
    client = _get_google_speech_client()
    if not client:
        return ""

    wav_bytes = _ensure_wav16k_mono(audio_bytes, mime_type)
    if not wav_bytes:
        # Se já for WAV 16k mono, tentamos direto mesmo assim
        wav_bytes = audio_bytes

    try:
        audio = speech.RecognitionAudio(content=wav_bytes)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code=language or LANG_DEFAULT,
            enable_automatic_punctuation=True,
        )
        resp = client.recognize(config=config, audio=audio)
        parts = []
        for result in getattr(resp, "results", []):
            alt = (getattr(result, "alternatives", None) or [])
            if not alt:
                continue
            txt = getattr(alt[0], "transcript", "") or ""
            if txt:
                parts.append(txt.strip())
        return " ".join(parts).strip()
    except Exception as e:
        logging.info("[audio_processing] Google STT falhou: %s", e)
        return ""


# =============================================================================
# OpenAI Whisper fallback
# =============================================================================
def _stt_whisper_from_bytes(audio_bytes: bytes, mime_type: Optional[str], language: str) -> str:
    try:
        if not (ENABLE_STT_OPENAI and OPENAI_API_KEY and audio_bytes):
            return ""
        lang = "pt" if (language or LANG_DEFAULT).lower().startswith("pt") else (language or LANG_DEFAULT).split("-")[0]
        files = {"file": ("audio.ogg", audio_bytes, (mime_type or "audio/ogg"))}
        data = {"model": "whisper-1", "language": lang}
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        r = requests.post("https://api.openai.com/v1/audio/transcriptions", headers=headers, files=files, data=data, timeout=60)
        js = {}
        try:
            js = r.json()
        except Exception:
            pass
        text = (js.get("text") if isinstance(js, dict) else "") or ""
        return text.strip()
    except Exception as e:
        logging.info("[audio_processing] Whisper fallback erro: %s", e)
        return ""


# =============================================================================
# APIs públicas (compatíveis com wa_bot.py)
# =============================================================================
def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = LANG_DEFAULT) -> str:
    """
    STT principal para bytes.
    - Prioriza Google
    - Fallback para Whisper (se habilitado)
    """
    if not audio_bytes:
        return ""

    provider = FORCE_STT_PROVIDER
    if provider == "google":
        out = _stt_google_from_bytes(audio_bytes, mime_type, language)
        return out or ""
    if provider == "whisper":
        out = _stt_whisper_from_bytes(audio_bytes, mime_type, language)
        return out or ""

    # padrão: tenta Google → Whisper
    txt = _stt_google_from_bytes(audio_bytes, mime_type, language)
    if txt:
        return txt
    return _stt_whisper_from_bytes(audio_bytes, mime_type, language)


def transcribe_audio(audio_bytes_or_path, mime_type: str = "audio/ogg", language: str = LANG_DEFAULT) -> str:
    """
    Aceita bytes OU caminho do arquivo.
    """
    try:
        if isinstance(audio_bytes_or_path, (bytes, bytearray)):
            return transcribe_audio_bytes(bytes(audio_bytes_or_path), mime_type=mime_type, language=language)
        if isinstance(audio_bytes_or_path, str):
            with open(audio_bytes_or_path, "rb") as f:
                data = f.read()
            # tenta inferir mime pelo sufixo se o caller não souber
            if not mime_type or mime_type == "auto":
                lower = audio_bytes_or_path.lower()
                if lower.endswith(".mp3"):
                    mime_type = "audio/mpeg"
                elif lower.endswith(".wav"):
                    mime_type = "audio/wav"
                elif lower.endswith(".ogg") or lower.endswith(".opus"):
                    mime_type = "audio/ogg"
                elif lower.endswith(".aac"):
                    mime_type = "audio/aac"
                elif lower.endswith(".m4a"):
                    mime_type = "audio/mp4"
            return transcribe_audio_bytes(data, mime_type=mime_type, language=language)
        logging.info("[audio_processing] entrada inválida em transcribe_audio (bytes ou path esperado).")
        return ""
    except Exception as e:
        logging.exception("[audio_processing] transcribe_audio erro: %s", e)
        return ""


# Aliases aceitáveis pelo wa_bot.py
def stt_transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = LANG_DEFAULT) -> str:
    return transcribe_audio_bytes(audio_bytes, mime_type=mime_type, language=language)

def speech_to_text(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = LANG_DEFAULT) -> str:
    return transcribe_audio_bytes(audio_bytes, mime_type=mime_type, language=language)

def stt_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = LANG_DEFAULT) -> str:
    return transcribe_audio_bytes(audio_bytes, mime_type=mime_type, language=language)

def transcrever_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = LANG_DEFAULT) -> str:
    return transcribe_audio_bytes(audio_bytes, mime_type=mime_type, language=language)

def transcrever_audio(audio_bytes_or_path, mime_type: str = "audio/ogg", language: str = LANG_DEFAULT) -> str:
    return transcribe_audio(audio_bytes_or_path, mime_type=mime_type, language=language)
