# providers/tts.py
# Fachada de TTS para a aplicação.
# - Expõe TTSEngine (default_tts) para services.text_to_speech usar
# - Fonte da verdade: services.text_to_speech.speak_bytes
# - Fallbacks tolerantes: ElevenLabs → Google Cloud TTS
from __future__ import annotations

import os
import json
import logging
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# ========= ENV & Defaults =========
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID")
GOOGLE_TTS_VOICE = os.getenv("GOOGLE_TTS_VOICE")  # ex.: 'pt-BR-Wavenet-A'
TTS_LANGUAGE_CODE = os.getenv("TTS_LANGUAGE_CODE", "pt-BR")
TTS_SPEAKING_RATE = float(os.getenv("TTS_SPEAKING_RATE", "1.0"))
TTS_PITCH_SEMITONES = float(os.getenv("TTS_PITCH_SEMITONES", "0.0"))

# ========= Firestore (opcional) para resolver voice_id =========
_get_doc = None
try:
    from services.db import get_doc as _get_doc  # type: ignore
except Exception as e:
    log.info("[providers.tts] services.db.get_doc indisponível: %s", e)
    _get_doc = None  # type: ignore


def resolve_voice_for_uid(uid: Optional[str], explicit_voice: Optional[str] = None) -> Optional[str]:
    """
    Retorna o voice_id a usar (prioridade):
      1) explicit_voice informado
      2) ELEVEN_VOICE_ID (env)
      3) profissionais/{uid}.{elevenVoiceId|voiceId|eleven_voice_id|ttsVoiceId} (ou persona.*)
      4) None
    """
    if explicit_voice:
        return explicit_voice
    if ELEVEN_VOICE_ID:
        return ELEVEN_VOICE_ID
    if not uid or not _get_doc:
        return None
    try:
        prof = _get_doc(f"profissionais/{uid}") or {}
        for k in ("elevenVoiceId", "voiceId", "eleven_voice_id", "ttsVoiceId"):
            v = prof.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        persona = prof.get("persona") or {}
        v2 = persona.get("elevenVoiceId") or persona.get("voiceId")
        if isinstance(v2, str) and v2.strip():
            return v2.strip()
    except Exception as e:
        log.info("[providers.tts] resolve_voice_for_uid falhou: %s", e)
    return None


# ========= Fallbacks diretos (usados apenas se services.text_to_speech falhar) =========
# --- ElevenLabs ---
_eleven_client = None
try:
    if ELEVEN_API_KEY:
        from elevenlabs.client import ElevenLabs  # type: ignore
        from elevenlabs import Voice, VoiceSettings  # type: ignore
        _eleven_client = ElevenLabs(api_key=ELEVEN_API_KEY)
except Exception as e:
    log.info("[providers.tts] ElevenLabs indisponível: %s", e)
    _eleven_client = None


def _tts_eleven_bytes(text: str, voice_id: Optional[str]) -> Optional[Tuple[bytes, str]]:
    """Retorna (bytes, 'audio/mpeg') ou None."""
    if not _eleven_client:
        return None
    try:
        vid = (voice_id or ELEVEN_VOICE_ID or "").strip() or "yNI0cEjjllppsJrp9PWG"
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
        log.info("[providers.tts] Fallback Eleven falhou: %s", e)
    return None


# --- Google Cloud TTS com credenciais inline JSON (ou ADC) ---
_google_tts_client = None
_google_tts_cred_used = None  # "inline_json" | "adc" | None

def _get_google_tts_client():
    global _google_tts_client, _google_tts_cred_used
    if _google_tts_client is not None:
        return _google_tts_client
    try:
        from google.cloud import texttospeech  # type: ignore
        from google.oauth2 import service_account  # type: ignore
    except Exception as e:
        log.info("[providers.tts] Google TTS libs indisponíveis: %s", e)
        _google_tts_client = None
        return None

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
            log.info("[providers.tts] credenciais inline JSON falharam: %s", e)

    try:
        from google.cloud import texttospeech  # reimport harmless
        _google_tts_client = texttospeech.TextToSpeechClient()
        _google_tts_cred_used = "adc"
        return _google_tts_client
    except Exception as e:
        log.info("[providers.tts] Google TTS ADC indisponível: %s", e)
        _google_tts_client = None
        _google_tts_cred_used = None
        return None


def _tts_google_bytes(
    text: str,
    want_ogg: bool,
    language_code: str = TTS_LANGUAGE_CODE,
    voice_name: Optional[str] = GOOGLE_TTS_VOICE,
    speaking_rate: float = TTS_SPEAKING_RATE,
    pitch_semitones: float = TTS_PITCH_SEMITONES,
) -> Optional[Tuple[bytes, str]]:
    """Retorna (bytes, mime) ou None (OGG/MP3)."""
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
        content = getattr(resp, "audio_content", None)
        if content:
            return (bytes(content), mime)
    except Exception as e:
        log.info("[providers.tts] Fallback Google TTS falhou: %s", e)
    return None


# ========= TTSEngine (usado por services.text_to_speech) =========
class TTSEngine:
    """
    Engine de TTS que prioriza services.text_to_speech.speak_bytes.
    """
    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        uid: Optional[str] = None,
        mime_preference: str = "audio/ogg",
    ) -> Optional[Tuple[bytes, str]]:
        if not text:
            return None

        # 1) fonte da verdade do projeto
        try:
            import services.text_to_speech as tts  # lazy import evita ciclo
            resolved_voice = resolve_voice_for_uid(uid, explicit_voice=voice)
            out = tts.speak_bytes(text, uid=uid, voice=resolved_voice, format=mime_preference)
            if out:
                return out
        except Exception as e:
            log.info("[providers.tts] services.text_to_speech indisponível/erro: %s", e)

        # 2) fallbacks locais (Eleven → Google)
        resolved_voice = resolve_voice_for_uid(uid, explicit_voice=voice)
        eleven = _tts_eleven_bytes(text, resolved_voice)
        if eleven:
            return eleven

        want_ogg = (mime_preference or "audio/ogg").lower().startswith("audio/ogg")
        return _tts_google_bytes(text, want_ogg=want_ogg)


def default_tts() -> TTSEngine:
    """Fábrica usada por services.text_to_speech."""
    return TTSEngine()


# ========= API direta (compat) =========
def speak_bytes(
    text: str,
    uid: Optional[str] = None,
    voice: Optional[str] = None,
    format: str = "audio/ogg",
) -> Optional[Tuple[bytes, str]]:
    eng = default_tts()
    return eng.synthesize(text=text, voice=voice, uid=uid, mime_preference=format)


def synthesize_bytes(*args, **kwargs):
    return speak_bytes(*args, **kwargs)

def tts_bytes(*args, **kwargs):
    return speak_bytes(*args, **kwargs)

def speak(*args, **kwargs):
    return speak_bytes(*args, **kwargs)

def text_to_speech(*args, **kwargs):
    return speak_bytes(*args, **kwargs)


# ========= helper opcional para envio direto por WhatsApp =========
def send_tts_whatsapp(
    to: str,
    text: str,
    uid: Optional[str] = None,
    voice: Optional[str] = None,
    format: str = "audio/ogg",
    send_audio_fn=None,
) -> Tuple[bool, dict]:
    """
    Gera TTS e envia pelo WhatsApp.
    - Se 'send_audio_fn' vier, usa (to, audio_bytes, mime_type).
    - Caso contrário, tenta services.wa_send.send_audio.
    """
    audio = speak_bytes(text, uid=uid, voice=voice, format=format)
    if not audio:
        return False, {"error": "tts_unavailable"}
    audio_bytes, mime_type = audio

    if callable(send_audio_fn):
        try:
            ok, resp = send_audio_fn(to, audio_bytes, mime_type)
            return bool(ok), resp or {}
        except Exception as e:
            logging.exception("[providers.tts] send_audio_fn falhou: %s", e)
            return False, {"error": repr(e)}

    try:
        from services.wa_send import send_audio  # type: ignore
        ok, resp = send_audio(to, audio_bytes, mime_type)
        return bool(ok), resp or {}
    except Exception as e:
        logging.exception("[providers.tts] services.wa_send.send_audio falhou: %s", e)
        return False, {"error": repr(e)}
