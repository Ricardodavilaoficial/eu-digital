# services/voice_wa_storage.py
# NOVO — upload de bytes de voz no bucket configurado (STORAGE_BUCKET).
# Não faz conversão; só salva como veio.

from __future__ import annotations

import os
from typing import Optional

from google.cloud import storage  # type: ignore

def _bucket_name() -> str:
    b = (os.environ.get("STORAGE_BUCKET") or "").strip()
    if not b:
        raise RuntimeError("missing_STORAGE_BUCKET")
    return b

def upload_voice_bytes(storage_path: str, content_type: str, data: bytes) -> None:
    if not storage_path:
        raise ValueError("empty_storage_path")
    if data is None:
        raise ValueError("empty_data")

    client = storage.Client()
    bucket = client.bucket(_bucket_name())
    blob = bucket.blob(storage_path)
    blob.upload_from_string(data, content_type=content_type or "application/octet-stream")
    # mantemos privado por padrão; player do front usa signed-url existente (/media/signed-url)
