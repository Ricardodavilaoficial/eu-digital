# services/storage_gcs.py
import io, os
from datetime import datetime, timedelta
from google.cloud import storage

# 15 minutos de validade para signed URL (quando público não for possível)
SIGNED_SECS = int(os.getenv("SIGNED_URL_EXPIRES_SECONDS", "900"))

def upload_bytes_and_get_url(uid: str, filename: str, buf: bytes, mimetype: str):
    """
    Sobe bytes para GCS em gs://<STORAGE_BUCKET>/profissionais/<uid>/voz/<filename>
    Tenta tornar público; se não puder, retorna Signed URL v4 (GET).
    Retorna: (url, bucket_name, gcs_path, access_mode)  com access_mode ∈ {"public","signed"}
    """
    bucket_name = os.environ["STORAGE_BUCKET"]  # explodir cedo se não houver
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    gcs_path = f"profissionais/{uid}/voz/{filename}"
    blob = bucket.blob(gcs_path)
    blob.cache_control = "public, max-age=3600"

    blob.upload_from_file(
        io.BytesIO(buf),
        size=len(buf),
        content_type=mimetype,
        rewind=True,
    )

    # Primeiro tentamos público; se a conta ou o bucket não permitirem, caímos para signed.
    try:
        blob.make_public()
        return blob.public_url, bucket_name, gcs_path, "public"
    except Exception:
        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.utcnow() + timedelta(seconds=SIGNED_SECS),
            method="GET",
        )
        return url, bucket_name, gcs_path, "signed"
