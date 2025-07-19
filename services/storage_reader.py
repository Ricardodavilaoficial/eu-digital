# Objetivo: Refatorar main.py em arquivos menores e organizados
# Etapas:

# ETAPA 1: Criar estrutura de pastas (caso ainda não tenha)
# ./services/
# ./utils/

# ETAPA 2: Separar responsabilidades em módulos dedicados
# Vamos dividir o main.py nos seguintes arquivos:
#
# 1. services/text_to_speech.py     --> Já existe ✅
# 2. services/audio_processing.py   --> Já existe ✅
# 3. services/storage_reader.py     --> Novo! funções para ler arquivos do bucket
# 4. services/openai_handler.py     --> Novo! lógica de conversa com o GPT
# 5. routes/audio_route.py          --> Novo! lida com a rota POST /audio
# 6. routes/html_route.py           --> Novo! rota GET /
# 7. main.py                        --> Apenas inicia o app e importa as rotas

# ETAPA 3: Começaremos criando o arquivo:
# services/storage_reader.py

from google.cloud import storage
from docx import Document
import io

conteudo_cache = {}  # Agora dicionário por caminho

# Cria cliente global com as credenciais
from google.oauth2 import service_account
import os

credentials = service_account.Credentials.from_service_account_file(
    "gcloud-key.json")
storage_client = storage.Client(credentials=credentials)
BUCKET_NAME = "eu-digital-ricardo"


def ler_arquivo_docx_especifico(caminho_blob):
    if caminho_blob in conteudo_cache:
        return conteudo_cache[caminho_blob]
    try:
        blob = storage_client.bucket(BUCKET_NAME).blob(caminho_blob)
        docx_bytes = blob.download_as_bytes()
        doc = Document(io.BytesIO(docx_bytes))
        texto = "\n".join([p.text for p in doc.paragraphs])
        conteudo_cache[caminho_blob] = texto
        return texto
    except Exception as e:
        print(f"Erro ao ler {caminho_blob}: {e}")
        return ""


def encontrar_arquivos_relevantes(pergunta):
    palavras_chave = pergunta.lower().split()
    arquivos_encontrados = []
    blobs = storage_client.bucket(BUCKET_NAME).list_blobs()

    for blob in blobs:
        if blob.name.endswith(".docx") and not blob.name.startswith("~$"):
            for palavra in palavras_chave:
                if palavra in blob.name.lower():
                    arquivos_encontrados.append(blob.name)
                    break

    return arquivos_encontrados[:
                                3]  # Limite de 3 arquivos para economia de tokens


def montar_contexto_a_partir_da_pergunta(pergunta):
    arquivos = encontrar_arquivos_relevantes(pergunta)
    contexto = ""
    for arquivo in arquivos:
        conteudo = ler_arquivo_docx_especifico(arquivo)
        contexto += f"\n\n### Arquivo: {arquivo}\n{conteudo}"
    return contexto
