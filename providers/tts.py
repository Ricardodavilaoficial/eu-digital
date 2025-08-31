# providers/tts.py
# Fachada de TTS para a aplicação.
# - Prioriza services.text_to_speech.speak_bytes (única fonte da verdade)
# - Fallbacks tolerantes para ElevenLabs e Google Cloud TTS
# - Resolve voice_id por UID (quando disponível em Firestore)
from __future__ import annotations

import os
import logging
from typing import Optional, Tuple

# dotenv é opcional (em produção as envs já costumam estar presentes)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# ========= ENV & Defaults =========
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID")
GOOGLE_TTS_VOICE = os.getenv("GOOGLE_TTS_VOICE")  # ex.: 'pt-BR-Standard-A' ou 'pt-BR-Wavenet-A'
TTS_LANGUAGE_CODE = os.getenv("TTS_LANGUAGE_CODE", "pt-BR")
TTS_SPEAKING_RATE = float(os.getenv("TTS_SPEAKING_RATE", "1.0"))
TTS_PITCH_SEMITONES = float(os.getenv("TTS_PITCH_SEMITONES", "0.0"))

# ========= Firestore (opcional) para resolver voice_id =========
_get_doc = None
try:
    # usamos a mesma lib de DB do projeto, mas sem travar se estiver ausente
    from services.db import get_doc as _get_doc  # type: ignore
except Exception as e:
    logging.info("[providers.tts] services.db.get_doc indisponível: %s", e)
    _get_doc = None  # type: ignore


def resolve_voice_for_uid(uid: Optional[str], explicit_voice: Optional[str] = None) -> Optional[str]:
    """
    Retorna o voice_id a usar (prioridade):
      1) explicit_voice informado na chamada
      2) ELEVEN_VOICE_ID (env)
      3) profissionais/{uid}.elevenVoiceId OU .voiceId (se Firestore disponível)
      4) None (deixa o provider decidir)
    """
    if explicit_voice:
        return explicit_voice
    if ELEVEN_VOICE_ID:
        return ELEVEN_VOICE_ID
    if not uid or not _get_doc:
        return None
    try:
        prof = _get_doc(f"profissionais/{uid}") or {}
        # nomes aceitáveis para o campo:
        for k in ("elevenVoiceId", "voiceId", "eleven_voice_id", "ttsVoiceId"):
            v = prof.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # pode haver dentro de persona
        persona = prof.get("persona") or {}
        v2 = persona.get("elevenVoiceId") or persona.get("voiceId")
        if isinstance(v2, str) and v2.strip():
            return v2.strip()
    except Exception as e:
        logging.info("[providers.tts] resolve_voice_for_uid falhou: %s", e)
    return None


# ========= Fallbacks diretos (só usados se services.text_to_speech não estiver disponível) =========
_eleven_client = None
try:
    if ELEVEN_API_KEY:
        from elevenlabs.client import ElevenLabs  # type: ignore
        from elevenlabs import Voice, VoiceSettings  # type: ignore

        _eleven_client = ElevenLabs(api_key=ELEVEN_API_KEY)
except Exception as e:
    logging.info("[providers.tts] ElevenLabs indisponível: %s", e)
    _eleven_client = None


def _tts_eleven_bytes(text: str, voice_id: Optional[str]) -> Optional[Tuple[bytes, str]]:
    """Fallback ElevenLabs: retorna (bytes, mime='audio/mpeg') ou None."""
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
        if buf:
            return (bytes(buf), "audio/mpeg")
    except Exception as e:
        logging.info("[providers.tts] Fallback Eleven falhou: %s", e)
    return None


_google_tts_client = None
try:
    from google.cloud import texttospeech  # type: ignore
    _google_tts_client = texttospeech.TextToSpeechClient()
except Exception as e:
    logging.info("[providers.tts] Google Cloud TTS indisponível: %s", e)
    _google_tts_client = None


def _tts_google_bytes(
    text: str,
    want_ogg: bool,
    language_code: str = TTS_LANGUAGE_CODE,
    voice_name: Optional[str] = GOOGLE_TTS_VOICE,
    speaking_rate: float = TTS_SPEAKING_RATE,
    pitch_semitones: float = TTS_PITCH_SEMITONES,
) -> Optional[Tuple[bytes, str]]:
    """Fallback Google TTS: retorna (bytes, mime) ou None (OGG/MP3)."""
    if not _google_tts_client:
        return None
    try:
        from google.cloud import texttospeech  # type: ignore

        synthesis_input = texttospeech.SynthesisInput(text=text)
        if voice_name:
            voice_params = texttospeech.VoiceSelectionParams(
                language_code=language_code, name=voice_name
            )
        else:
            voice_params = texttospeech.VoiceSelectionParams(language_code=language_code)

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

        resp = _google_tts_client.synthesize_speech(
            input=synthesis_input, voice=voice_params, audio_config=audio_config
        )
        content = getattr(resp, "audio_content", None)
        if content:
            return (bytes(content), mime)
    except Exception as e:
        logging.info("[providers.tts] Fallback Google TTS falhou: %s", e)
    return None


# ========= API pública =========
def speak_bytes(
    text: str,
    uid: Optional[str] = None,
    voice: Optional[str] = None,
    format: str = "audio/ogg",
) -> Optional[Tuple[bytes, str]]:
    """
    Único ponto de entrada recomendado.
    - Tenta usar services.text_to_speech.speak_bytes (implementação oficial do projeto)
    - Se falhar, usa fallbacks (ElevenLabs e Google TTS) de forma tolerante.
    Retorna (audio_bytes, mime) ou None.
    """
    if not text:
        return None

    # 1) Tenta usar o módulo oficial
    try:
        import services.text_to_speech as tts  # type: ignore
        # Passa 'voice' já resolvido por UID, se não vier na chamada
        resolved_voice = resolve_voice_for_uid(uid, explicit_voice=voice)
        out = tts.speak_bytes(text, uid=uid, voice=resolved_voice, format=format)
        if out:
            return out
    except Exception as e:
        logging.info("[providers.tts] services.text_to_speech indisponível/erro: %s", e)

    # 2) Fallbacks
    resolved_voice = resolve_voice_for_uid(uid, explicit_voice=voice)

    # 2a) ElevenLabs (voz clonada)
    if ELEVEN_API_KEY:
        eleven = _tts_eleven_bytes(text, resolved_voice)
        if eleven:
            return eleven  # MP3 (aceito pelo WhatsApp)

    # 2b) Google TTS (honra format)
    want_ogg = (format or "").lower().startswith("audio/ogg")
    google = _tts_google_bytes(text, want_ogg=want_ogg)
    if google:
        return google

    return None


# Aliases por compatibilidade
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
    - Caso contrário, tenta importar providers/wa_send.send_audio.
    Retorna (ok, resp_dict).
    """
    audio = speak_bytes(text, uid=uid, voice=voice, format=format)
    if not audio:
        return False, {"error": "tts_unavailable"}
    audio_bytes, mime_type = audio

    # preferir função injetada (mais testável)
    if callable(send_audio_fn):
        try:
            ok, resp = send_audio_fn(to, audio_bytes, mime_type)
            return bool(ok), resp or {}
        except Exception as e:
            logging.exception("[providers.tts] send_audio_fn falhou: %s", e)
            return False, {"error": repr(e)}

    # fallback para nosso módulo de envio
    try:
        from services.wa_send import send_audio  # type: ignore
        ok, resp = send_audio(to, audio_bytes, mime_type)
        return bool(ok), resp or {}
    except Exception as e:
        logging.exception("[providers.tts] services.wa_send.send_audio falhou: %s", e)
        return False, {"error": repr(e)}
