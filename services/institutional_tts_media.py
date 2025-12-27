# services/institutional_tts_media.py
from __future__ import annotations

import json
import math
import os
import uuid
import urllib.request
from datetime import datetime
from typing import Optional, Tuple

from services.gcs_handler import upload_bytes


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _is_enabled() -> bool:
    v = _env("INSTITUTIONAL_TTS_ENABLED", "0").lower()
    return v in ("1", "true", "yes", "on")


def _signed_url_minutes() -> int:
    """
    Preferência:
      1) INSTITUTIONAL_TTS_SIGNED_URL_TTL (segundos)
      2) SIGNED_URL_EXPIRES_MIN (minutos)
    """
    ttl_s = _env("INSTITUTIONAL_TTS_SIGNED_URL_TTL", "")
    if ttl_s:
        try:
            s = int(ttl_s)
            if s <= 0:
                return 15
            # arredonda pra cima (ex.: 900s => 15min)
            return max(1, int(math.ceil(s / 60.0)))
        except Exception:
            return 15

    # compat antigo
    try:
        return int(_env("SIGNED_URL_EXPIRES_MIN", "15") or "15")
    except Exception:
        return 15


def _tts_base_url_local() -> str:
    """
    Chama o próprio backend localmente (evita sair pro Cloudflare/YCloud).
    Render normalmente expõe PORT.
    """
    port = _env("PORT", "10000") or "10000"
    return f"http://127.0.0.1:{port}".rstrip("/")


def _call_internal_tts(text: str, voice_id: str, mime: str) -> Optional[Tuple[bytes, str]]:
    """
    Usa o endpoint /api/voz/tts que você já provou que gera audio/mpeg quando recebe voice_id.
    Retorna (audio_bytes, mime_type) ou None (fail-safe).
    """
    base = _tts_base_url_local()
    url = f"{base}/api/voz/tts"

    payload = {
        "text": text,
        "voice_id": voice_id,
        "mime": mime,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        # timeout curto pra não travar o lead
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = getattr(resp, "status", 200)
            if int(status) != 200:
                return None

            audio_bytes = resp.read() or b""
            if not audio_bytes:
                return None

            content_type = resp.headers.get("Content-Type") or mime or "audio/mpeg"
            return (audio_bytes, content_type)
    except Exception:
        return None


def generate_institutional_audio_url(text: str) -> Optional[str]:
    """
    Gera áudio institucional e retorna uma Signed URL curta (GCS).
    - Sem Firestore
    - Uso: apenas LEAD
    - Fail-safe: se falhar, retorna None (caller faz fallback pra texto)
    """
    if not _is_enabled():
        return None

    voice_id = _env("INSTITUTIONAL_VOICE_ID", "")
    if not voice_id:
        return None

    # compat: aceita INSTITUTIONAL_TTS_MIME (novo) e INSTITUTIONAL_TTS_FORMAT (antigo)
    out_mime = _env("INSTITUTIONAL_TTS_MIME", "") or _env("INSTITUTIONAL_TTS_FORMAT", "audio/mpeg") or "audio/mpeg"

    spoken = _call_internal_tts(text=text, voice_id=voice_id, mime=out_mime)
    if not spoken:
        return None

    audio_bytes, mime_type = spoken

    now = datetime.utcnow()
    ext = "mp3" if "mpeg" in (mime_type or "").lower() else "bin"
    obj = f"sandbox/institutional_tts/{now:%Y/%m/%d}/{uuid.uuid4().hex}.{ext}"

    url = upload_bytes(
        data=audio_bytes,
        dest_path=obj,
        content_type=mime_type or "audio/mpeg",
        public=False,
        cache_control="private, max-age=0",
        signed_url_minutes=_signed_url_minutes(),
    )
    return (url or None)
