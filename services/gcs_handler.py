# services/gcs_handler.py

import os
import io
import json
from google.cloud import storage
from google.oauth2 import service_account
from docx import Document
from dotenv import load_dotenv

# Esta linha não deve ser usada no Render.com, pois ele gerencia as variáveis de ambiente.
# load_dotenv()

def get_storage_client():
    """
    Inicializa o cliente do Google Cloud Storage usando credenciais de uma
    variável de ambiente JSON, que é o método recomendado para o Render.com.
    """
    creds_json_content = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")

    if creds_json_content is None:
        raise ValueError(
            "A variável de ambiente GOOGLE_APPLICATION_CREDENTIALS_JSON "
            "não foi encontrada. Por favor, adicione o conteúdo do seu "
            "arquivo de credenciais JSON nela no painel do Render."
        )

    creds_info = json.loads(creds_json_content)
    credentials = service_account.Credentials.from_service_account_info(creds_info)
    
    return storage.Client(credentials=credentials)

storage_client = get_storage_client()

bucket_name = "eu-digital-ricardo"
bucket = storage_client.bucket(bucket_name)

# Cache simples por nome do arquivo
arquivo_cache = {}


def ler_arquivo_docx_especifico(caminho):
    if caminho in arquivo_cache:
        return arquivo_cache[caminho]

    blob = bucket.blob(caminho)
    try:
        docx_bytes = blob.download_as_bytes()
        doc = Document(io.BytesIO(docx_bytes))
        texto = "\n".join([p.text for p in doc.paragraphs])
        conteudo = f"\n\n### Conteúdo do arquivo: {caminho}\n{texto}"
        arquivo_cache[caminho] = conteudo
        return conteudo
    except Exception as e:
        print(f"Erro ao ler o arquivo {caminho} do bucket: {e}")
        return None


def detectar_arquivos_relevantes(pergunta):
    """
    Retorna uma lista de caminhos de arquivos relevantes com base em palavras-chave simples.
    """
    blobs = list(bucket.list_blobs())
    caminhos_relevantes = []
    pergunta_lower = pergunta.lower()

    for blob in blobs:
        if blob.name.endswith(".docx") and not blob.name.startswith("~$"):
            nome = blob.name.lower()
            if any(palavra in nome for palavra in pergunta_lower.split()):
                caminhos_relevantes.append(blob.name)

    return caminhos_relevantes[:3]  # no máximo 3 arquivos


def montar_contexto_para_pergunta(pergunta):
    caminhos = detectar_arquivos_relevantes(pergunta)
    if not caminhos:
        return ""

    contexto = ""
    for caminho in caminhos:
        conteudo_arquivo = ler_arquivo_docx_especifico(caminho)
        if conteudo_arquivo:
            contexto += conteudo_arquivo

    return contexto