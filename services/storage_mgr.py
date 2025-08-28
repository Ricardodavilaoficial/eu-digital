# services/storage_mgr.py
# Gerência de Storage (Firebase/GCS): upload com dedupe por hash + URL assinada v4
import os
import io
import hashlib
import mimetypes
from datetime import timedelta, datetime, timezone
from typing import Optional, Dict, Any

try:
    from services.db import get_db  # apenas para garantir init do firebase_admin
    import firebase_admin
    from firebase_admin import storage as fb_storage
except Exception as e:
    get_db = None
    fb_storage = None

_SP = timezone(timedelta(hours=-3))

def _bucket_name() -> str:
    b = os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()
    if b:
        return b
    proj = os.getenv("FIREBASE_PROJECT_ID", "").strip()
    if not proj:
        raise RuntimeError("FIREBASE_PROJECT_ID ausente e FIREBASE_STORAGE_BUCKET não definido.")
    return f"{proj}.appspot.com"

def _get_bucket():
    if fb_storage is None:
        raise RuntimeError("firebase_admin.storage indisponível")
    if get_db:
        try:
            get_db()  # força init do app
        except Exception:
            pass
    return fb_storage.bucket(_bucket_name())

def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _now_iso() -> str:
    return datetime.now(_SP).isoformat()

def guess_ext(content_type: str) -> str:
    ext = mimetypes.guess_extension(content_type or "") or ""
    if ext.startswith("."):
        ext = ext[1:]
    return ext or "bin"

def sign_url(gs_path: str, hours: Optional[int] = None) -> str:
    ttl = int(os.getenv("STORAGE_SIGN_URL_TTL_HOURS", "48"))
    if hours is None:
        hours = ttl
    if not gs_path.startswith("gs://"):
        raise ValueError("gs_path deve começar com gs://")
    _, _, rest = gs_path.partition("gs://")
    bucket_name, _, blob_name = rest.partition("/")
    if not blob_name:
        raise ValueError("gs_path inválido")
    bucket = _get_bucket() if bucket_name == _bucket_name() else fb_storage.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    return blob.generate_signed_url(expiration=timedelta(hours=hours), method="GET", version="v4")

def upload_bytes(gs_prefix: str, data: bytes, content_type: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Sobe bytes com path estável por hash -> dedupe automático.
    gs_prefix: exemplo "profissionais/UID/clientes/CLID/media/2025/08"
    Retorna: { "gs_path", "sha256", "size", "contentType", "signedUrl" }
    """
    if not data:
        raise ValueError("dados vazios")
    max_mb = int(os.getenv("MAX_MEDIA_MB", "15"))
    if len(data) > max_mb * 1024 * 1024:
        raise ValueError(f"arquivo excede {max_mb}MB")

    ct = content_type or "application/octet-stream"
    sha = _sha256_hex(data)
    ext = guess_ext(ct)
    # path determinístico por hash => se já existe, reaproveita
    # shard por prefixo do hash para evitar pastas gigantes
    shard = sha[:2]
    blob_name = f"{gs_prefix}/{shard}/{sha}.{ext}"
    bucket = _get_bucket()
    blob = bucket.blob(blob_name)
    if not blob.exists():
        blob.upload_from_file(io.BytesIO(data), size=len(data), content_type=ct)
        blob.metadata = {**(metadata or {}), "sha256": sha, "uploadedAt": _now_iso()}
        blob.patch()
    gs_path = f"gs://{_bucket_name()}/{blob_name}"
    url = sign_url(gs_path)
    return {
        "gs_path": gs_path,
        "sha256": sha,
        "size": len(data),
        "contentType": ct,
        "signedUrl": url,
    }
