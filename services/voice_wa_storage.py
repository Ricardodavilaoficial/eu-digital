# services/voice_wa_storage.py
# NOVO — upload cru do áudio para o bucket do projeto.
#
# ENVs:
# - STORAGE_BUCKET=mei-robo-prod.firebasestorage.app   (já é canônico no teu projeto)

from __future__ import annotations

import os
import re
from typing import Optional, Any

from google.cloud import storage  # type: ignore


_MIME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,63}/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,127}$")


def _sanitize_content_type(content_type: Any) -> str:
    """Return a safe MIME type string (or "" to force fallback).

    We MUST NOT pass raw/binary or header-breaking values into requests/GCS.
    """
    if content_type is None:
        return ""

    # If bytes arrive (buggy caller), do a best-effort decode but be strict after.
    if isinstance(content_type, (bytes, bytearray)):
        # Binary payloads (e.g., starting with "OggS") must never become headers.
        # Decode ignoring errors, then validate strictly below.
        try:
            s = bytes(content_type).decode("utf-8", errors="ignore")
        except Exception:
            return ""
    else:
        try:
            s = content_type if isinstance(content_type, str) else str(content_type)
        except Exception:
            return ""

    s = s.strip()

    # Reject anything that can break HTTP headers or looks like binary/junk.
    if not s:
        return ""
    if "\r" in s or "\n" in s or "\x00" in s:
        return ""
    # Reject non-printable control chars (ASCII < 32) and DEL (127)
    if any((ord(ch) < 32) or (ord(ch) == 127) for ch in s):
        return ""
    # Keep it simple: no parameters (e.g., "; charset=") for safety.
    if ";" in s:
        return ""

    # Validate basic "type/subtype" shape.
    if not _MIME_RE.match(s):
        return ""

    return s


def upload_voice_bytes(storage_path: str, content_type: Optional[str], data: bytes) -> str:
    bucket_name = (os.environ.get("STORAGE_BUCKET") or "").strip()
    if not bucket_name:
        raise RuntimeError("missing_STORAGE_BUCKET")
    if not storage_path:
        raise ValueError("missing_storage_path")

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(storage_path)

    # PATCH: GCS/requests esperam content_type como str "limpa".
    # Se vier lixo/binário (ex.: áudio começando com "OggS..."), forçamos fallback seguro.
    safe_ct = _sanitize_content_type(content_type)

    blob.upload_from_string(data, content_type=(safe_ct or "application/octet-stream"))
    return storage_path

