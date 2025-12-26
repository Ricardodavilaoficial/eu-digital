# services/institutional_tts_media.py
from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Optional

from services.text_to_speech import speak_bytes
from services import gcs_handler


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def generate_institutional_audio_url(text: str, *, content_type: str = "audio/mpeg") -> Optional[str]:
    """
    Gera áudio institucional (MP3) e retorna uma Signed URL (GET) para envio no WhatsApp.

    Regras:
    - NÃO grava Firestore.
    - NÃO chama /media/signed-url (evita token interno).
    - Salva em sandbox/<SANDBOX_UID>/institutional_tts/YYYY/MM/DD/<uuid>.mp3
    """
    enabled = _env("INSTITUTIONAL_TTS_ENABLED", "0").lower() in ("1", "true", "yes", "on")
    if not enabled:
        return None

    voice_id = _env("INSTITUTIONAL_VOICE_ID", "")
    if not voice_id:
        return None

    body = (text or "").strip()
    if not body:
        return None

    # 1) ElevenLabs TTS -> bytes (mp3)
    try:
        audio_bytes = speak_bytes(text=body, voice_id=voice_id)
    except Exception:
        return None

    if not audio_bytes:
        return None

    # 2) Path canônico (global, sem profissionais/{uid})
    sandbox_uid = _env("SANDBOX_UID", "demo_uid")
    now = datetime.utcnow()
    obj = f"sandbox/{sandbox_uid}/institutional_tts/{now:%Y/%m/%d}/{uuid.uuid4().hex}.mp3"

    # 3) Upload no GCS + Signed GET URL
    try:
        signed_min = int(_env("SIGNED_URL_EXPIRES_MIN", "15") or "15")
        url = gcs_handler.upload_bytes(
            data=audio_bytes,
            dest_path=obj,
            content_type=content_type,
            public=False,
            cache_control="public, max-age=60",
            signed_url_minutes=signed_min,
        )
        return url
    except Exception:
        return None
