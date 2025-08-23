# services/gcs_handler.py
# Upload/Download no Google Cloud Storage com credenciais robustas
# Compatível com: from services import gcs_handler; gcs_handler.upload_fileobj(...)

import os
import io
import json
import traceback
from datetime import timedelta

from google.cloud import storage
from google.oauth2 import service_account

# Opcional, apenas se usar leitura de .docx no bucket
try:
    from docx import Document
    _DOCX_OK = True
except Exception:
    _DOCX_OK = False


# ----------------------------
# Inicialização do GCS Client
# ----------------------------
def get_storage_client():
    """
    Prioridade das credenciais:
      1) GOOGLE_APPLICATION_CREDENTIALS_JSON (conteúdo JSON inline)
      2) FIREBASE_SERVICE_ACCOUNT_JSON (mesma chave usada no Firestore)
      3) GOOGLE_APPLICATION_CREDENTIALS (caminho para arquivo .json)
      4) ADC (Application Default Credentials)
    """
    # 1) JSON inline (preferido no Render)
    json_inline = (
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        or os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")  # compat
    )
    if json_inline:
        try:
            creds_info = json.loads(json_inline)
            credentials = service_account.Credentials.from_service_account_info(creds_info)
            print("[GCS] Using inline JSON credentials.")
            return storage.Client(credentials=credentials, project=creds_info.get("project_id"))
        except Exception as e:
            print(f"[GCS][ERR] Invalid inline JSON credentials: {e}")
            traceback.print_exc()

    # 2) Caminho de arquivo
    json_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if json_path:
        if os.path.exists(json_path):
            try:
                credentials = service_account.Credentials.from_service_account_file(json_path)
                print(f"[GCS] Using GOOGLE_APPLICATION_CREDENTIALS file: {json_path}")
                return storage.Client(credentials=credentials)
            except Exception as e:
                print(f"[GCS][ERR] Failed to load credentials from file: {e}")
                traceback.print_exc()
        else:
            print(f"[GCS][WARN] File not found at GOOGLE_APPLICATION_CREDENTIALS: {json_path}")

    # 3) ADC (último recurso, ex.: local dev com `gcloud auth application-default login`)
    try:
        print("[GCS] Using Application Default Credentials (ADC).")
        return storage.Client()
    except Exception as e:
        print(f"[GCS][ERR] Failed to init ADC client: {e}")
        traceback.print_exc()
        return None


# Client e Bucket globais (simples)
_storage_client = get_storage_client()

# Defina no Render: GCS_BUCKET = seu-bucket
_BUCKET_FALLBACK = "eu-digital-ricardo"  # fallback antigo; pode trocar p/ bucket do mei-robo-prod
_BUCKET_NAME = os.environ.get("GCS_BUCKET") or _BUCKET_FALLBACK

_bucket = _storage_client.bucket(_BUCKET_NAME) if _storage_client else None
if _bucket is None:
    print("[GCS][WARN] Bucket não inicializado. Verifique credenciais e variável GCS_BUCKET.")


# ----------------------------
# Helpers de Upload/Download
# ----------------------------
def _ensure_bucket():
    global _bucket
    if _bucket is None:
        raise RuntimeError("Bucket GCS não inicializado. Verifique credenciais e GCS_BUCKET.")
    return _bucket


def upload_fileobj(file_obj, dest_path: str, content_type: str = None, public: bool = True,
                   cache_control: str = "public, max-age=3600", signed_url_minutes: int = 15) -> str:
    """
    Sobe um arquivo (objeto file-like) para o bucket no caminho `dest_path`.
    Retorna URL pública (se public=True) OU uma Signed URL com validade de `signed_url_minutes`.
    """
    bucket = _ensure_bucket()
    blob = bucket.blob(dest_path)
    try:
        blob.cache_control = cache_control
        blob.upload_from_file(file_obj, content_type=content_type)

        if public:
            try:
                blob.make_public()
                return blob.public_url
            except Exception as e:
                print(f"[GCS][WARN] make_public falhou, gerando Signed URL: {e}")

        # Signed URL (fallback ou quando public=False)
        url = blob.generate_signed_url(expiration=timedelta(minutes=signed_url_minutes), method="GET")
        return url
    except Exception as e:
        print(f"[GCS][ERR] upload_fileobj failed for {dest_path}: {e}")
        traceback.print_exc()
        raise


def upload_bytes(data: bytes, dest_path: str, content_type: str = None, public: bool = True,
                 cache_control: str = "public, max-age=3600", signed_url_minutes: int = 15) -> str:
    """Versão com bytes em memória."""
    bucket = _ensure_bucket()
    blob = bucket.blob(dest_path)
    try:
        blob.cache_control = cache_control
        blob.upload_from_string(data, content_type=content_type)

        if public:
            try:
                blob.make_public()
                return blob.public_url
            except Exception as e:
                print(f"[GCS][WARN] make_public falhou, gerando Signed URL: {e}")

        url = blob.generate_signed_url(expiration=timedelta(minutes=signed_url_minutes), method="GET")
        return url
    except Exception as e:
        print(f"[GCS][ERR] upload_bytes failed for {dest_path}: {e}")
        traceback.print_exc()
        raise


def download_bytes(path: str) -> bytes:
    """Baixa um blob como bytes. Lança exceção se falhar."""
    bucket = _ensure_bucket()
    blob = bucket.blob(path)
    try:
        return blob.download_as_bytes()
    except Exception as e:
        print(f"[GCS][ERR] download_bytes failed for {path}: {e}")
        traceback.print_exc()
        raise


# ----------------------------
# Funções DOCX (opcionais)
# ----------------------------
_arquivo_cache = {}

def ler_arquivo_docx_especifico(caminho: str):
    """
    Lê um arquivo .docx do GCS e retorna seu conteúdo como string.
    Mantida por compatibilidade com seu fluxo atual.
    """
    if not _DOCX_OK:
        print("[DOCX][WARN] 'python-docx' não disponível. Adicione 'python-docx' ao requirements.txt se precisar.")
        return None

    try:
        if caminho in _arquivo_cache:
            return _arquivo_cache[caminho]

        data = download_bytes(caminho)
        doc = Document(io.BytesIO(data))
        texto = "\n".join(p.text for p in doc.paragraphs)
        conteudo = f"\n\n### Conteúdo do arquivo: {caminho}\n{texto}"
        _arquivo_cache[caminho] = conteudo
        return conteudo
    except Exception as e:
        print(f"[DOCX][ERR] Erro ao ler DOCX '{caminho}': {e}")
        traceback.print_exc()
        return None


def detectar_arquivos_relevantes(pergunta: str):
    """
    Busca simples por palavras da pergunta nos nomes dos .docx do bucket.
    Retorna até 3 caminhos.
    """
    bucket = _ensure_bucket()
    try:
        caminhos_relevantes = []
        pergunta_lower = (pergunta or "").lower().split()

        for blob in bucket.list_blobs():
            name = blob.name.lower()
            if name.endswith(".docx") and not name.startswith("~$"):
                if any(p in name for p in pergunta_lower):
                    caminhos_relevantes.append(blob.name)

        return caminhos_relevantes[:3]
    except Exception as e:
        print(f"[DOCX][ERR] Erro ao detectar arquivos relevantes: {e}")
        traceback.print_exc()
        return []


def montar_contexto_para_pergunta(pergunta: str):
    """
    Concatena o conteúdo de até 3 arquivos relevantes (DOCX) em uma única string.
    """
    try:
        caminhos = detectar_arquivos_relevantes(pergunta)
        if not caminhos:
            return ""

        contexto = ""
        for caminho in caminhos:
            conteudo = ler_arquivo_docx_especifico(caminho)
            if conteudo:
                contexto += conteudo

        return contexto
    except Exception as e:
        print(f"[DOCX][ERR] Erro ao montar contexto: {e}")
        traceback.print_exc()
        return ""
