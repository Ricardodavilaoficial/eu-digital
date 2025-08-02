# Usa imagem leve do Python
FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg

# Define diretório de trabalho
WORKDIR /app

# Copia todos os arquivos do projeto para o container
COPY . /app

# Atualiza pip e instala dependências
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Expõe a porta usada pelo Render.com (você já está usando a 10000 corretamente)
EXPOSE 10000

# Comando para iniciar o app
CMD ["python", "main.py"]
