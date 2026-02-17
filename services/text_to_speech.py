# services/text_to_speech.py
# Wrapper de TTS usado pelo wa_bot.py
# - Prioriza providers/tts (engine modular)
# - Fallback: ElevenLabs (voz clonada) → Google Cloud TTS (OGG/MP3)
# - Retorna (audio_bytes, mime_type)

from __future__ import annotations

import os
import json
import logging
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# Redirect central: usa o fallback com cooldown
from services.tts_fallback import speak_bytes, tts_bytes  # noqa

# =========================
# Envs / defaults
# =========================
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID")

GOOGLE_TTS_VOICE = os.getenv("GOOGLE_TTS_VOICE")          # ex.: pt-BR-Wavenet-A
TTS_LANGUAGE_CODE = os.getenv("TTS_LANGUAGE_CODE", "pt-BR")
TTS_SPEAKING_RATE = float(os.getenv("TTS_SPEAKING_RATE", "1.0"))
TTS_PITCH_SEMITONES = float(os.getenv("TTS_PITCH_SEMITONES", "0.0"))

# força um provedor específico (opcional): "elevenlabs" | "google"
FORCE_TTS_PROVIDER = (os.getenv("FORCE_TTS_PROVIDER") or "").strip().lower()

# =========================
# 1) providers/tts.py (se existir)
# =========================
try:
    from providers.tts import default_tts  # type: ignore
    _PROVIDERS_TTS_OK = True
except Exception:
    _PROVIDERS_TTS_OK = False


def _via_providers_tts(
    text: str,
    voice: Optional[str],
    prefer_mime: str,
) -> Optional[Tuple[bytes, str]]:
    """Usa providers/tts.TTSEngine (se disponível) para sintetizar."""
    if not _PROVIDERS_TTS_OK:
        return None
    try:
        engine = default_tts()
        out = engine.synthesize(text, voice=voice, mime_preference=prefer_mime)
        if out and isinstance(out, tuple) and isinstance(out[0], (bytes, bytearray)):
            return (bytes(out[0]), str(out[1]))
    except Exception as e:
        log.info("[TTS/providers] falhou: %s", e)
    return None


# =========================
# 2) Fallback interno: ElevenLabs → Google TTS
# =========================
# --- ElevenLabs (opcional) ---
_eleven_client = None
try:
    if ELEVEN_API_KEY:
        from elevenlabs.client import ElevenLabs  # type: ignore
        from elevenlabs import Voice, VoiceSettings  # type: ignore
        _eleven_client = ElevenLabs(api_key=ELEVEN_API_KEY)
except Exception as e:
    log.info("[TTS] ElevenLabs indisponível: %s", e)
    _eleven_client = None


def _tts_eleven_bytes(text: str, voice_id: Optional[str] = None) -> Optional[Tuple[bytes, str]]:
    """Gera MP3 via ElevenLabs e retorna (bytes, 'audio/mpeg')."""
    if not _eleven_client:
        return None
    try:
        vid = (voice_id or ELEVEN_VOICE_ID or "").strip() or "yNI0cEjjllppsJrp9PWG"  # fallback interno
        audio_iter = _eleven_client.generate(
            text=text,
            voice=Voice(
                voice_id=vid,
                settings=VoiceSettings(
                    stability=0.75,
                    similarity_boost=0.75,
                    style=0.0,
                    use_speaker_boost=True,
                ),
            ),
            model="eleven_multilingual_v2",
        )
        buf = bytearray()
        for chunk in audio_iter:
            if chunk:
                buf.extend(chunk)
        return (bytes(buf), "audio/mpeg") if buf else None
    except Exception as e:
        log.info("[TTS/Eleven] falhou: %s", e)
        return None


# --- Google Cloud TTS (opcional) ---
_google_tts_client = None
_google_tts_cred_used = None  # "inline_json" | "adc" | None


def _get_google_tts_client():
    """Cria cliente do Google TTS preferindo JSON inline (GOOGLE_APPLICATION_CREDENTIALS_JSON/FIREBASE_*)."""
    global _google_tts_client, _google_tts_cred_used
    if _google_tts_client is not None:
        return _google_tts_client
    try:
        from google.cloud import texttospeech  # type: ignore
        from google.oauth2 import service_account  # type: ignore
    except Exception as e:
        log.info("[TTS] Google Cloud TTS indisponível (libs): %s", e)
        _google_tts_client = None
        return None

    # tenta credencial via JSON embutido (compatível com audio_processing)
    creds_json = (
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        or os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        or os.getenv("FIREBASE_CREDENTIALS_JSON")
    )
    if creds_json:
        try:
            info = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(info)
            _google_tts_client = texttospeech.TextToSpeechClient(credentials=creds)
            _google_tts_cred_used = "inline_json"
            return _google_tts_client
        except Exception as e:
            log.info("[TTS] credenciais inline JSON falharam: %s", e)

    # fallback: ADC (Application Default Credentials)
    try:
        from google.cloud import texttospeech  # reimport safe
        _google_tts_client = texttospeech.TextToSpeechClient()
        _google_tts_cred_used = "adc"
        return _google_tts_client
    except Exception as e:
        log.info("[TTS] Google TTS ADC indisponível: %s", e)
        _google_tts_client = None
        _google_tts_cred_used = None
        return None


def _tts_google_bytes(
    text: str,
    language_code: str = TTS_LANGUAGE_CODE,
    voice_name: Optional[str] = GOOGLE_TTS_VOICE,
    want_ogg: bool = False,
    speaking_rate: float = TTS_SPEAKING_RATE,
    pitch_semitones: float = TTS_PITCH_SEMITONES,
) -> Optional[Tuple[bytes, str]]:
    """Gera OGG Opus (ou MP3) via Google TTS e retorna (bytes, mime)."""
    client = _get_google_tts_client()
    if not client:
        return None
    try:
        from google.cloud import texttospeech  # type: ignore

        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice_params = (
            texttospeech.VoiceSelectionParams(language_code=language_code, name=voice_name)
            if voice_name else
            texttospeech.VoiceSelectionParams(language_code=language_code)
        )
        if want_ogg:
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.OGG_OPUS,
                speaking_rate=speaking_rate,
                pitch=pitch_semitones,
            )
            mime = "audio/ogg"
        else:
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=speaking_rate,
                pitch=pitch_semitones,
            )
            mime = "audio/mpeg"

        resp = client.synthesize_speech(
            input=synthesis_input, voice=voice_params, audio_config=audio_config
        )
        data = getattr(resp, "audio_content", None)
        if data:
            return (bytes(data), mime)
    except Exception as e:
        log.info("[TTS/Google] falhou: %s", e)
    return None


# =========================
# API pública (usada pelo wa_bot.py)
# =========================
def _legacy_speak_bytes(
    text: str,
    uid: Optional[str] = None,   # compat (não usado)
    voice: Optional[str] = None, # ElevenLabs: voice_id
    format: str = "audio/ogg",   # "audio/ogg" ou "audio/mpeg"
) -> Optional[Tuple[bytes, str]]:
    """
    Retorna (audio_bytes, mime_type) ou None.
    Ordem de preferência:
      A) providers/tts (se existir)
      B) ElevenLabs (voz clonada) — MP3
      C) Google TTS (OGG/MP3, conforme 'format')
    Observação: mesmo se 'format' pedir OGG, ElevenLabs entrega MP3 (WhatsApp aceita).
    """
    if not text:
        return None

    prefer_mime = (format or "audio/ogg").lower()

    # A) providers/tts
    out = _via_providers_tts(text, voice, prefer_mime)
    if out:
        return out

    # B/C) Fallback direto com opção de forçar provedor
    if FORCE_TTS_PROVIDER == "elevenlabs":
        out = _tts_eleven_bytes(text, voice_id=voice)
        if out:
            return out
        # se falhar, cai para google
        want_ogg = prefer_mime.startswith("audio/ogg")
        return _tts_google_bytes(text, want_ogg=want_ogg)

    if FORCE_TTS_PROVIDER == "google":
        want_ogg = prefer_mime.startswith("audio/ogg")
        out = _tts_google_bytes(text, want_ogg=want_ogg)
        if out:
            return out
        # se falhar, tenta eleven
        return _tts_eleven_bytes(text, voice_id=voice)

    # padrão: Eleven → Google
    out = _tts_eleven_bytes(text, voice_id=voice)
    if out:
        return out

    want_ogg = prefer_mime.startswith("audio/ogg")
    return _tts_google_bytes(text, want_ogg=want_ogg)


# Aliases compatíveis
def synthesize_bytes(*args, **kwargs):
    return speak_bytes(*args, **kwargs)


def speak(*args, **kwargs):
    return speak_bytes(*args, **kwargs)

def text_to_speech(*args, **kwargs):
    return speak_bytes(*args, **kwargs)


# Teste local
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    txt = "Olá! Este é um teste de síntese de voz."
    out = speak_bytes(txt, voice=ELEVEN_VOICE_ID, format="audio/ogg")
    if out:
        audio, mime = out
        ext = ".ogg" if mime == "audio/ogg" else ".mp3"
        path = f"./tts_test{ext}"
        with open(path, "wb") as f:
            f.write(audio)
        print(f"✅ Gerado: {path} ({mime}, {len(audio)} bytes) via {('ElevenLabs' if mime=='audio/mpeg' else 'Google TTS')} cred={_google_tts_cred_used or '-'}")
    else:
        print("⚠️ Nenhum backend TTS disponível.")
