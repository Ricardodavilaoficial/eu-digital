# Use uma imagem base Python oficial (Ubuntu-based)
FROM python:3.13-slim-bookworm

# Instale o FFmpeg e outras dependências de sistema necessárias
RUN apt-get update && apt-get install -y ffmpeg --no-install-recommends && rm -rf /var/lib/apt/lists/*

# Crie e defina o diretório de trabalho dentro do contêiner
WORKDIR /app

# Copie o requirements.txt primeiro para otimizar o cache
COPY requirements.txt ./

# Instale as dependências usando pip
RUN pip install -r requirements.txt

# Copie o restante do seu código para o contêiner
COPY . .

# O Render.com usará o "Start Command" nas configurações do serviço.
# Este CMD aqui é um fallback, mas o Start Command do Render terá prioridade.
CMD ["python", "main.py"]