# Usa imagem leve do Python
FROM python:3.11-slim

# Garante que o sistema tenha as depend�ncias b�sicas para compilar pacotes e usar o FFmpeg
RUN apt-get update && apt-get install -y ffmpeg gcc libffi-dev libsndfile1-dev && apt-get clean

# Define diret�rio de trabalho
WORKDIR /app

# Copia todos os arquivos do projeto para o container
COPY . /app

# Atualiza pip e instala depend�ncias
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Exp�e a porta usada pelo Render.com
EXPOSE 10000

# Comando para iniciar o app
CMD ["python", "main.py"]