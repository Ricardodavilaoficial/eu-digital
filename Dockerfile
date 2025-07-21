# Use uma imagem base Python oficial (Ubuntu-based)
FROM python:3.13-slim-bookworm

# Instale o FFmpeg e outras dependências de sistema necessárias
RUN apt-get update && apt-get install -y ffmpeg --no-install-recommends && rm -rf /var/lib/apt/lists/*

# Crie e defina o diretório de trabalho dentro do contêiner
WORKDIR /app

# Copie TODOS os arquivos do seu projeto para o contêiner
COPY . .

# Instale Poetry e as dependências do Python.
# O Python virtual environment criado pelo Poetry será '.venv' no WORKDIR.
# Garanta que o Poetry e os binários do venv estejam no PATH.
RUN pip install poetry && \
    poetry install --no-root --no-dev

# Comando para iniciar sua aplicação.
# Agora, vamos chamar o Python DENTRO do ambiente virtual do Poetry diretamente.
# Isso garante que todos os pacotes instalados (como Flask) sejam encontrados.
CMD ["/usr/local/bin/python", "-m", "poetry", "run", "python", "main.py"]