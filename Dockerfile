# Usa imagem leve e moderna do Python
FROM python:3.11-slim

# Instala depend�ncias do sistema, incluindo ffmpeg para processar �udios
RUN apt-get update && \
    apt-get install -y ffmpeg gcc libffi-dev libsndfile1-dev && \
    apt-get clean

# Define o diret�rio de trabalho no container
WORKDIR /app

# Copia os arquivos do projeto
COPY . /app

# Atualiza pip, setuptools e wheel SEM CACHE
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Instala depend�ncias do projeto SEM CACHE
RUN pip install --no-cache-dir -r requirements.txt

# Exp�e a porta que o Render usar�
EXPOSE 10000

# Comando para rodar a aplica��o
CMD ["python", "main.py"]
