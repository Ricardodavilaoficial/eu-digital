import os
import io
import json
import traceback
from google.cloud import storage
from google.oauth2 import service_account
from docx import Document


def get_storage_client():
    """
    Inicializa o cliente do Google Cloud Storage usando JSON inline (Render.com)
    ou credenciais padrão (local).
    """
    if 'GOOGLE_APPLICATION_CREDENTIALS_JSON' in os.environ:
        try:
            creds_info = json.loads(os.environ['GOOGLE_APPLICATION_CREDENTIALS_JSON'])
            credentials = service_account.Credentials.from_service_account_info(creds_info)
            return storage.Client(credentials=credentials)
        except Exception as e:
            print(f"❌ Erro ao carregar credenciais GCS: {e}")
            traceback.print_exc()
    else:
        print("⚠️ Variável GOOGLE_APPLICATION_CREDENTIALS_JSON não encontrada. Usando fallback padrão.")

    try:
        return storage.Client()
    except Exception as e:
        print(f"❌ Erro ao inicializar GCS Client: {e}")
        traceback.print_exc()
        return None


storage_client = get_storage_client()
bucket_name = "eu-digital-ricardo"
bucket = storage_client.bucket(bucket_name) if storage_client else None

# Cache simples por nome do arquivo
arquivo_cache = {}

def ler_arquivo_docx_especifico(caminho):
    """
    Lê um arquivo .docx do GCS e retorna seu conteúdo como string.
    """
    if not bucket:
        print("❌ Bucket GCS não inicializado.")
        return None

    if caminho in arquivo_cache:
        return arquivo_cache[caminho]

    try:
        blob = bucket.blob(caminho)
        docx_bytes = blob.download_as_bytes()
        doc = Document(io.BytesIO(docx_bytes))
        texto = "\n".join([p.text for p in doc.paragraphs])
        conteudo = f"\n\n### Conteúdo do arquivo: {caminho}\n{texto}"
        arquivo_cache[caminho] = conteudo
        return conteudo
    except Exception as e:
        print(f"❌ Erro ao ler o arquivo '{caminho}' do GCS: {e}")
        traceback.print_exc()
        return None


def detectar_arquivos_relevantes(pergunta):
    """
    Retorna até 3
