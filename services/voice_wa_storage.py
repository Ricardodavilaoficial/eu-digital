# services/voice_wa_storage.py
# NOVO — upload cru do áudio para o bucket do projeto.
#
# ENVs:
# - STORAGE_BUCKET=mei-robo-prod.firebasestorage.app   (já é canônico no teu projeto)

from __future__ import annotations

import os
from typing import Optional

from google.cloud import storage  # type: ignore

def upload_voice_bytes(storage_path: str, content_type: str, data: bytes) -> str:
    bucket_name = (os.environ.get("STORAGE_BUCKET") or "").strip()
    if not bucket_name:
        raise RuntimeError("missing_STORAGE_BUCKET")
    if not storage_path:
        raise ValueError("missing_storage_path")

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(storage_path)

    # PATCH: GCS espera content_type como str; às vezes chega como bytes
    if isinstance(content_type, (bytes, bytearray)):
        try:
            content_type = content_type.decode("utf-8", errors="ignore")
        except Exception:
            content_type = ""
    elif content_type is None:
        content_type = ""
    elif not isinstance(content_type, str):
        content_type = str(content_type)

    blob.upload_from_string(data, content_type=(content_type or "application/octet-stream"))
    return storage_path
