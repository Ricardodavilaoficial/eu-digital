# services/institutional_tts_media.py
from __future__ import annotations

import os
import uuid
import requests
from typing import Optional

from services.text_to_speech import speak_bytes
from services.auth import get_id_token_for_internal_call

MEDIA_SIGNED_URL_ENDPOINT = "/media/signed-url"

def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()

def generate_institutional_audio_url(
    text: str,
    base_url: str,
) -> Optional[str]:
    """
    Gera áudio institucional (MP3), faz upload via Signed URL
    e retorna a downloadUrl. Não grava Firestore.
    """
    if not text:
        return None

    # Feature flag
    if _env("INSTITUTIONAL_TTS_ENABLED", "0") in ("0", "false", "False"):
        return None

    voice_id = _env("INSTITUTIONAL_VOICE_ID", "")
    if not voice_id:
        return None

    # 1) Gera bytes MP3 via ElevenLabs (já testado)
    audio_bytes, mime = speak_bytes(
        text=text,
        voice=voice_id,
        mime_type="audio/mpeg",
    )

    if not audio_bytes:
        return None

    # 2) Pede signed URLs
    filename = f"tts_lead_{uuid.uuid4().hex}.mp3"
    token = get_id_token_for_internal_call()

    resp = requests.post(
        f"{base_url}{MEDIA_SIGNED_URL_ENDPOINT}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "contentType": "audio/mpeg",
            "filename": filename,
        },
        timeout=10,
    )
    data = resp.json() if resp.ok else {}
    upload_url = data.get("uploadUrl")
    download_url = data.get("downloadUrl")

    if not upload_url or not download_url:
        return None

    # 3) Upload do MP3 (PUT)
    put = requests.put(
        upload_url,
        data=audio_bytes,
        headers={"Content-Type": "audio/mpeg"},
        timeout=10,
    )
    if not put.ok:
        return None

    return download_url
