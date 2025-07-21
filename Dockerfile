# Use uma imagem base Python oficial (Ubuntu-based)
FROM python:3.13-slim-bookworm

# Instale o FFmpeg e outras dependências de sistema necessárias
RUN apt-get update && apt-get install -y ffmpeg --no-install-recommends && rm -rf /var/lib/apt/lists/*

# Crie e defina o diretório de trabalho dentro do contêiner
WORKDIR /app

# Copie TODOS os arquivos do seu projeto para o contêiner
COPY . .

# Instale Poetry globalmente e instale as dependências.
# Explicitamente defina o local do venv do Poetry dentro do contêiner.
# Isso garante que o Render.com possa encontrá-lo e que o Poetry saiba onde está.
RUN pip install poetry && \
    poetry config virtualenvs.in-project true && \
    poetry install --no-root --no-dev

# Comando para iniciar sua aplicação.
# Ative o ambiente virtual do Poetry e então execute o main.py.
# 'source' precisa ser executado dentro de um shell (sh -c).
CMD ["sh", "-c", "source .venv/bin/activate && /app/.venv/bin/python main.py"]