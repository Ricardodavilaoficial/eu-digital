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

# Atualiza o pip e instala as dependências Python
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Expõe a porta que o Render usará
EXPOSE 10000

# Comando para rodar a aplicação
CMD ["python", "main.py"]
