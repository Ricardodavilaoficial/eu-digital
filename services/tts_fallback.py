# services/tts_fallback.py
from __future__ import annotations

import os
import time
import logging
from typing import Optional

log = logging.getLogger(__name__)

# In-memory (por instância). Bom e rápido.
# Se você roda 2+ instâncias, o ideal é também persistir (veja função _persist_cooldown).
_ELEVEN_DISABLED_UNTIL_TS: float = 0.0

def _now() -> float:
    return time.time()

def _cooldown_seconds() -> int:
    try:
        return int(os.getenv("TTS_FAIL_COOLDOWN_SECONDS", "300"))
    except Exception:
        return 300

def _is_eleven_in_cooldown() -> bool:
    global _ELEVEN_DISABLED_UNTIL_TS
    return _now() < float(_ELEVEN_DISABLED_UNTIL_TS or 0.0)

def _set_eleven_cooldown(reason: str = "") -> None:
    global _ELEVEN_DISABLED_UNTIL_TS
    cd = _cooldown_seconds()
    _ELEVEN_DISABLED_UNTIL_TS = _now() + cd
    log.warning("[tts] elevenlabs OFF por %ss. motivo=%s", cd, reason or "-")
    # opcional: persistir (multi-instância)
    _persist_cooldown(until_ts=_ELEVEN_DISABLED_UNTIL_TS, reason=reason)

def _clear_eleven_cooldown() -> None:
    global _ELEVEN_DISABLED_UNTIL_TS
    _ELEVEN_DISABLED_UNTIL_TS = 0.0
    _persist_cooldown(until_ts=0.0, reason="recovered")

def _persist_cooldown(*, until_ts: float, reason: str) -> None:
    """
    Best-effort: salva cooldown num doc global pra sincronizar entre instâncias.
    Se falhar, não quebra nada.
    """
    try:
        # Se você já tem services/db.py com db = firestore.Client()
        from services.db import db  # type: ignore
        db.collection("platform_state").document("tts").set(
            {
                "eleven_disabled_until": float(until_ts),
                "updatedAtEpoch": float(_now()),
                "reason": (reason or "")[:140],
            },
            merge=True,
        )
    except Exception:
        return

def _load_cooldown_from_db() -> None:
    """
    Best-effort: lê cooldown do Firestore pra manter coerência entre instâncias.
    Chame no começo do request de TTS ou 1x por processo (lazy).
    """
    global _ELEVEN_DISABLED_UNTIL_TS
    try:
        from services.db import db  # type: ignore
        doc = db.collection("platform_state").document("tts").get()
        if not doc.exists:
            return
        data = doc.to_dict() or {}
        until_ts = float(data.get("eleven_disabled_until") or 0.0)
        # Só atualiza se for maior que o local
        if until_ts > float(_ELEVEN_DISABLED_UNTIL_TS or 0.0):
            _ELEVEN_DISABLED_UNTIL_TS = until_ts
    except Exception:
        return

def tts_bytes(*, text: str, voice_id: Optional[str] = None, lang: str = "pt-BR") -> bytes:
    """
    Contrato:
      - recebe texto
      - tenta ElevenLabs primeiro
      - se falhar, entra em cooldown e usa Google TTS
      - retorna bytes de áudio (mp3 recomendado)
    """
    text = (text or "").strip()
    if not text:
        return b""

    # 1) PRIMARY: ElevenLabs
    if not _is_eleven_in_cooldown():
        try:
            audio = _tts_elevenlabs(text=text, voice_id=voice_id)
            if audio:
                _clear_eleven_cooldown()
                return audio
            _set_eleven_cooldown("empty_audio")
        except Exception as e:
            _set_eleven_cooldown(f"exception:{type(e).__name__}")

    # 2) FALLBACK: Google TTS (sempre tenta; se falhar, deixa exception subir)
    return _tts_google(text=text, lang=lang)


def speak_bytes(text: str, *, voice_id: Optional[str] = None, lang: str = "pt-BR") -> bytes:
    """
    Wrapper seguro: mantém o contrato antigo (nunca levanta erro pro fluxo principal).
    """
    try:
        return tts_bytes(text=text, voice_id=voice_id, lang=lang)
    except Exception as e:
        log.exception("[tts] google fallback falhou: %s", e)
        return b""
# Backward-compat
# (alguns trechos do projeto ainda podem importar tts_bytes)
# tts_bytes é a função principal; speak_bytes é wrapper seguro


def _tts_elevenlabs(*, text: str, voice_id: Optional[str]) -> bytes:
    """
    Encapsule aqui seu client atual da ElevenLabs.
    Importante: timeout baixo e erro => exception.
    """
    # Exemplo: se você já tem algo como services/elevenlabs_tts.py
    from services.elevenlabs_tts import speak_bytes  # type: ignore

    # Recomendo: speak_bytes(text, voice_id=..., timeout=8) ou algo do tipo
    return speak_bytes(text=text, voice_id=voice_id, timeout=8)

def _tts_google(*, text: str, lang: str = "pt-BR") -> bytes:
    """
    Google Cloud Text-to-Speech. Saída MP3.
    """
    from google.cloud import texttospeech  # type: ignore

    client = texttospeech.TextToSpeechClient()

    synthesis_input = texttospeech.SynthesisInput(text=text)
    # Preferir voz explícita (ex.: pt-BR-Neural2-B / pt-BR-Wavenet-B).
    # Se não houver, força MALE pra evitar cair no default (geralmente feminino).
    voice_name = (os.getenv("GOOGLE_TTS_VOICE") or "").strip()
    language_code = (os.getenv("TTS_LANGUAGE_CODE") or lang or "pt-BR").strip()
    if voice_name:
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        )
    else:
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            ssml_gender=texttospeech.SsmlVoiceGender.MALE,
        )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
    )

    resp = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    return bytes(resp.audio_content or b"")



def _tts_google_owner_clone(*, text: str, voice_cloning_key: str, lang: str = "pt-BR") -> bytes:
    """
    Google Chirp / Instant Custom Voice.

    A chave da voz clonada deve vir de configuração segura.
    Nunca logar voice_cloning_key.

    Se a biblioteca/ambiente não suportar voice_clone, esta função levanta erro
    e o chamador institucional cai para o Google padrão.
    """
    try:
        from google.cloud import texttospeech_v1beta1 as texttospeech  # type: ignore
    except Exception:
        from google.cloud import texttospeech  # type: ignore

    client = texttospeech.TextToSpeechClient()

    synthesis_input = texttospeech.SynthesisInput(text=text)
    language_code = (os.getenv("TTS_LANGUAGE_CODE") or lang or "pt-BR").strip()

    voice_clone = texttospeech.VoiceCloneParams(
        voice_cloning_key=voice_cloning_key,
    )
    voice = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        voice_clone=voice_clone,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
    )

    resp = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    return bytes(resp.audio_content or b"")


def tts_institutional_bytes(
    *,
    text: str,
    voice_id: Optional[str] = None,
    lang: str = "pt-BR",
    mime: str = "audio/mpeg",
    tts_owner: Optional[str] = None,
    telemetry: Optional[dict] = None,
) -> bytes:
    """
    TTS institucional/vendas do MEI Robô.

    Escopo:
      - Google padrão atual como default absoluto.
      - Google voz clonada do dono apenas quando explicitamente ativada.
      - Em qualquer falha, volta para Google padrão.
      - Não usa ElevenLabs.
      - Não altera o contrato amplo de tts_bytes().
    """
    text = (text or "").strip()
    if not text:
        return b""

    tel = telemetry if isinstance(telemetry, dict) else None

    raw_mode = (os.getenv("INSTITUTIONAL_GOOGLE_TTS_MODE") or "standard").strip().lower()
    if raw_mode in ("", "default", "google", "google_standard"):
        mode = "standard"
    else:
        mode = raw_mode

    fallback_reason = ""

    def _record(*, voice_mode: str, provider_effective: str, reason: str, ok: bool) -> None:
        if tel is not None:
            try:
                tel.update(
                    {
                        "voiceMode": voice_mode,
                        "providerEffective": provider_effective,
                        "fallbackReason": reason or "",
                        "textLen": len(text),
                        "mime": mime or "audio/mpeg",
                        "ttsOwner": (tts_owner or ""),
                        "ok": bool(ok),
                    }
                )
            except Exception:
                pass

    if mode not in ("standard", "owner_clone"):
        fallback_reason = "invalid_mode"
        audio = _tts_google(text=text, lang=lang)
        _record(
            voice_mode="standard",
            provider_effective="google",
            reason=fallback_reason,
            ok=bool(audio),
        )
        return audio

    if mode == "owner_clone":
        clone_key = (os.getenv("INSTITUTIONAL_GOOGLE_TTS_OWNER_CLONE_KEY") or "").strip()
        if clone_key:
            try:
                audio = _tts_google_owner_clone(
                    text=text,
                    voice_cloning_key=clone_key,
                    lang=lang,
                )
                if audio:
                    _record(
                        voice_mode="owner_clone",
                        provider_effective="google_owner_clone",
                        reason="",
                        ok=True,
                    )
                    return audio
                fallback_reason = "owner_clone_empty_audio"
            except Exception as e:
                fallback_reason = f"owner_clone_failed:{type(e).__name__}"
        else:
            fallback_reason = "missing_owner_clone_key"

        audio = _tts_google(text=text, lang=lang)
        _record(
            voice_mode="owner_clone",
            provider_effective="google",
            reason=fallback_reason,
            ok=bool(audio),
        )
        if fallback_reason:
            log.info(
                "[tts][institutional] owner_clone fallback provider=google reason=%s textLen=%s owner=%s",
                fallback_reason,
                len(text),
                tts_owner or "",
            )
        return audio

    audio = _tts_google(text=text, lang=lang)
    _record(
        voice_mode="standard",
        provider_effective="google",
        reason="",
        ok=bool(audio),
    )
    return audio
