# services/gcs_handler.py

import os
import io
import json # Adicionado para lidar com JSON
from google.cloud import storage
from google.oauth2 import service_account # Adicionado para autenticação com JSON
from docx import Document
from dotenv import load_dotenv

# load_dotenv() # Descomente se você precisar carregar outras variáveis de ambiente do .env localmente

# --- Início da correção para autenticação no Render.com ---

# A linha abaixo não é mais necessária, pois não estamos lendo de um caminho de arquivo local
# credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
# os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

def get_storage_client():
    # Tenta carregar credenciais da variável de ambiente JSON do Render
    if 'GOOGLE_APPLICATION_CREDENTIALS_JSON' in os.environ:
        try:
            creds_info = json.loads(os.environ['GOOGLE_APPLICATION_CREDENTIALS_JSON'])
            credentials = service_account.Credentials.from_service_account_info(creds_info)
            return storage.Client(credentials=credentials)
        except Exception as e:
            print(f"Erro ao carregar credenciais da variável de ambiente GOOGLE_APPLICATION_CREDENTIALS_JSON: {e}")
            # Fallback: Tenta carregar automaticamente (útil para ambientes GCP ou se GOOGLE_APPLICATION_CREDENTIALS for definido de outra forma)
            return storage.Client()
    else:
        # Tenta encontrar credenciais automaticamente (ex: se GOOGLE_APPLICATION_CREDENTIALS for definido para um caminho de arquivo local no desenvolvimento)
        # OU se estiver rodando em um ambiente GCP que fornece credenciais automaticamente
        print("Variável de ambiente 'GOOGLE_APPLICATION_CREDENTIALS_JSON' não encontrada. Tentando autenticação padrão.")
        return storage.Client()

storage_client = get_storage_client() # Inicializa o cliente de storage usando a função

# --- Fim da correção para autenticação no Render.com ---


bucket_name = "eu-digital-ricardo"
bucket = storage_client.bucket(bucket_name)

# Cache simples por nome do arquivo
arquivo_cache = {}


def ler_arquivo_docx_especifico(caminho):
    if caminho in arquivo_cache:
        return arquivo_cache[caminho]

    blob = bucket.blob(caminho)
    docx_bytes = blob.download_as_bytes()
    doc = Document(io.BytesIO(docx_bytes))
    texto = "\n".join([p.text for p in doc.paragraphs])

    conteudo = f"\n\n### Conteúdo do arquivo: {caminho}\n{texto}"
    arquivo_cache[caminho] = conteudo
    return conteudo


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
        if conteudo_arquivo: # Apenas adiciona se o conteúdo não for None (em caso de erro de leitura)
            contexto += conteudo_arquivo

    return contexto