# Usa imagem leve e moderna do Python
FROM python:3.11-slim

# Instala dependências do sistema, incluindo ffmpeg para processar áudios
RUN apt-get update && \
    apt-get install -y ffmpeg gcc libffi-dev libsndfile1-dev && \
    apt-get clean

# Define o diretório de trabalho no container
WORKDIR /app

# Copia os arquivos do projeto
COPY . /app

# Atualiza pip, setuptools e wheel SEM CACHE
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Instala dependências do projeto SEM CACHE
RUN pip install --no-cache-dir -r requirements.txt

# Expõe a porta que o Render usará
EXPOSE 10000

# Comando para rodar a aplicação
CMD ["python", "main.py"]
