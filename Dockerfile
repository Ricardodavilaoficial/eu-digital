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

# Atualiza o pip e instala as depend�ncias Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Exp�e a porta que o Render usar�
EXPOSE 10000

# Comando para rodar a aplica��o
CMD ["python", "main.py"]
