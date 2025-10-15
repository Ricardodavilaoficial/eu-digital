# services/gcs_handler.py
# Upload/Download no Google Cloud Storage com credenciais robustas
# Compatível com: from services import gcs_handler; gcs_handler.upload_fileobj(...)

import os
import io
import re
import traceback
from datetime import timedelta

# >>> usa APENAS o helper centralizado (evita conflito de nomes)
from services.gcp_creds import get_storage_client as gcp_get_storage_client

# Opcional, apenas se usar leitura de .docx no bucket
try:
    from docx import Document
    _DOCX_OK = True
except Exception:
    _DOCX_OK = False


# ----------------------------
# Resolvedor de nome de bucket
# ----------------------------
def _resolve_gcs_bucket_name():
    """
    Ordem segura para descobrir o NOME REAL do bucket GCS (não o domínio de download):
      1) STORAGE_GCS_BUCKET (ex.: mei-robo-prod.appspot.com)
      2) Se não houver, derivar de STORAGE_BUCKET:
         - "NOME.firebasestorage.app" -> "NOME.appspot.com"
         - Se já vier "NOME.appspot.com", mantém
      3) Se ainda não houver, usar GCS_BUCKET (legado)
      4) Fallback (ajuste conforme seu projeto, se necessário)
    """
    # 1) Preferir env dedicada para GCS
    b = (os.environ.get("STORAGE_GCS_BUCKET") or "").strip()
    if b:
        return b

    # 2) Derivar de STORAGE_BUCKET quando vier domínio web do Firebase Storage
    s = (os.environ.get("STORAGE_BUCKET") or "").strip()
    if s:
        if s.endswith(".appspot.com"):
            return s
        m = re.match(r"^([a-z0-9\-]+)\.firebasestorage\.app$", s)
        if m:
            return f"{m.group(1)}.appspot.com"

    # 3) Legado
    gcs_bucket_legacy = (os.environ.get("GCS_BUCKET") or "").strip()
    if gcs_bucket_legacy:
        return gcs_bucket_legacy

    # 4) Fallback (ajuste se necessário)
    return "eu-digital-ricardo"


# ----------------------------
# Inicialização do Bucket
# ----------------------------
def _init_bucket():
    try:
        client = gcp_get_storage_client()
    except Exception as e:
        print(f"[GCS][ERR] get_storage_client falhou: {e}")
        traceback.print_exc()
        return None

    bucket_name = _resolve_gcs_bucket_name()
    if not bucket_name:
        print("[GCS][ERR] Bucket não configurado. Defina STORAGE_GCS_BUCKET ou STORAGE_BUCKET ou GCS_BUCKET.")
        return None

    print(f"[GCS] Using bucket: {bucket_name}")
    return client.bucket(bucket_name)


# Client/Bucket globais (simples)
_bucket = _init_bucket()
if _bucket is None:
    print("[GCS][WARN] Bucket não inicializado. Verifique credenciais e variáveis de ambiente.")


# ----------------------------
# Helpers de Upload/Download
# ----------------------------
def _ensure_bucket():
    global _bucket
    if _bucket is None:
        _bucket = _init_bucket()
        if _bucket is None:
            raise RuntimeError("Bucket GCS não inicializado. Verifique credenciais e STORAGE_GCS_BUCKET/STORAGE_BUCKET/GCS_BUCKET.")
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
