# services/storage_gcs.py 
import io, os, json, logging
from datetime import datetime, timedelta
from google.cloud import storage
from google.api_core.exceptions import NotFound, Forbidden
from google.oauth2 import service_account

# 15 minutos de validade para signed URL (quando público não for possível)
SIGNED_SECS = int(os.getenv("SIGNED_URL_EXPIRES_SECONDS", "900"))

_STORAGE_SCOPES = [
    "https://www.googleapis.com/auth/devstorage.read_write",
    "https://www.googleapis.com/auth/cloud-platform",
]


def _build_credentials():
    """
    Tenta montar credenciais a partir de variáveis de ambiente com JSON inline:
      - FIREBASE_SERVICE_ACCOUNT_JSON
      - GOOGLE_APPLICATION_CREDENTIAL  (alguns projetos usam este nome)
    Se nada existir, retorna None (ADC padrão do ambiente).
    """
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON") or os.getenv("GOOGLE_APPLICATION_CREDENTIAL")
    if not raw:
        return None
    try:
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=_STORAGE_SCOPES)
    except Exception as e:
        logging.error("[gcs] Credenciais inline inválidas: %s", e)
        raise


def _get_client():
    """
    Cria o cliente GCS com projeto (quando disponível) e, se possível, com
    credenciais derivadas das variáveis de ambiente acima. Se não houver,
    usa ADC padrão (GOOGLE_APPLICATION_CREDENTIALS PATH, Metadata, etc).
    """
    project = os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    creds = _build_credentials()
    try:
        return storage.Client(project=project, credentials=creds) if creds else storage.Client(project=project)
    except Exception as e:
        logging.exception("[gcs] storage.Client() falhou: %s", e)
        raise


def upload_bytes_and_get_url(uid: str, filename: str, buf: bytes, mimetype: str):
    """
    Sobe bytes para GCS em gs://<STORAGE_BUCKET>/profissionais/<uid>/voz/<filename>
    Tenta tornar público; se não puder, retorna Signed URL v4 (GET).
    Retorna: (url, bucket_name, gcs_path, access_mode)  com access_mode ∈ {"public","signed"}
    """
    bucket_name = os.getenv("STORAGE_BUCKET")
    if not bucket_name:
        raise RuntimeError("STORAGE_BUCKET ausente nas variáveis de ambiente")

    client = _get_client()
    try:
        bucket = client.bucket(bucket_name)
    except Exception as e:
        logging.exception("[gcs] client.bucket('%s') falhou: %s", bucket_name, e)
        raise

    gcs_path = f"profissionais/{uid}/voz/{filename}"
    blob = bucket.blob(gcs_path)
    blob.cache_control = "public, max-age=3600"
    blob.content_type = (mimetype or "application/octet-stream")

    try:
        blob.upload_from_file(
            io.BytesIO(buf),
            size=len(buf),
            content_type=blob.content_type,
            rewind=True,
        )
    except NotFound as e:
        logging.error("[gcs] Bucket '%s' não encontrado ao subir '%s': %s", bucket_name, gcs_path, e)
        raise
    except Forbidden as e:
        logging.error("[gcs] Sem permissão para escrever em '%s/%s': %s", bucket_name, gcs_path, e)
        raise
    except Exception as e:
        logging.exception("[gcs] upload_from_file falhou em '%s/%s': %s", bucket_name, gcs_path, e)
        raise

    # Tenta público; se falhar, Signed URL v4
    try:
        blob.make_public()
        return blob.public_url, bucket_name, gcs_path, "public"
    except Exception as e:
        logging.warning("[gcs] make_public falhou, usando Signed URL: %s", e)
        try:
            url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.utcnow() + timedelta(seconds=SIGNED_SECS),
                method="GET",
            )
            return url, bucket_name, gcs_path, "signed"
        except Exception as e2:
            logging.exception("[gcs] generate_signed_url falhou para '%s/%s': %s", bucket_name, gcs_path, e2)
            raise


def upload_acervo_bytes_and_get_url(uid: str, rel_path: str, buf: bytes, mimetype: str):
    """
    Sobe bytes para GCS em gs://<STORAGE_BUCKET>/profissionais/<uid>/acervo/<rel_path>

    - uid: UID do profissional dono do acervo
    - rel_path: caminho relativo dentro de "acervo/" (ex.: "original/<id>.pdf", "consulta/<id>.md")
    - buf: conteúdo em bytes
    - mimetype: tipo MIME (ex.: "text/plain", "application/pdf", "text/markdown")

    Retorna: (url, bucket_name, gcs_path, access_mode)
      onde access_mode ∈ {"public", "signed"}.
    """
    bucket_name = os.getenv("STORAGE_BUCKET")
    if not bucket_name:
        raise RuntimeError("STORAGE_BUCKET ausente nas variáveis de ambiente")

    client = _get_client()
    try:
        bucket = client.bucket(bucket_name)
    except Exception as e:
        logging.exception("[gcs] client.bucket('%s') falhou: %s", bucket_name, e)
        raise

    gcs_path = f"profissionais/{uid}/acervo/{rel_path}"
    blob = bucket.blob(gcs_path)
    blob.cache_control = "public, max-age=3600"
    blob.content_type = (mimetype or "application/octet-stream")

    try:
        blob.upload_from_file(
            io.BytesIO(buf),
            size=len(buf),
            content_type=blob.content_type,
            rewind=True,
        )
    except NotFound as e:
        logging.error("[gcs] Bucket '%s' não encontrado ao subir '%s': %s", bucket_name, gcs_path, e)
        raise
    except Forbidden as e:
        logging.error("[gcs] Sem permissão para escrever em '%s/%s': %s", bucket_name, gcs_path, e)
        raise
    except Exception as e:
        logging.exception("[gcs] upload_from_file falhou em '%s/%s': %s", bucket_name, gcs_path, e)
        raise

    # Tenta público; se falhar, Signed URL v4
    try:
        blob.make_public()
        return blob.public_url, bucket_name, gcs_path, "public"
    except Exception as e:
        logging.warning("[gcs] make_public falhou (acervo), usando Signed URL: %s", e)
        try:
            url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.utcnow() + timedelta(seconds=SIGNED_SECS),
                method="GET",
            )
            return url, bucket_name, gcs_path, "signed"
        except Exception as e2:
            logging.exception("[gcs] generate_signed_url falhou para '%s/%s' (acervo): %s", bucket_name, gcs_path, e2)
            raise


# === NOVO HELPER: assinatura V4 on-demand para leitura ===
def sign_v4_read_url(bucket_name: str, object_key: str, expires_seconds: int = None, inline: bool = True) -> str:
    """
    Gera Signed URL (V4) de leitura para um objeto no GCS.
    - bucket_name: ex.: 'mei-robo-prod.firebasestorage.app' (SEM .appspot.com)
    - object_key : ex.: 'voices/<UID>/voz_teste.mp3'
    - expires_seconds: segundos de validade (default: SIGNED_SECS)
    - inline: True para sugerir abertura inline no navegador
    """
    if not bucket_name:
        raise RuntimeError("bucket_name ausente em sign_v4_read_url")
    if not object_key:
        raise RuntimeError("object_key ausente em sign_v4_read_url")

    client = _get_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_key)

    params = {
        "version": "v4",
        "expiration": timedelta(seconds=(expires_seconds or SIGNED_SECS)),
        "method": "GET",
    }
    if inline:
        params["response_disposition"] = "inline"

    return blob.generate_signed_url(**params)
