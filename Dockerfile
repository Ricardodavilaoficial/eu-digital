# Use uma imagem base Python oficial (Ubuntu-based)
FROM python:3.13-slim-bookworm

# Instale o FFmpeg e outras dependências de sistema necessárias
RUN apt-get update && apt-get install -y ffmpeg --no-install-recommends && rm -rf /var/lib/apt/lists/*

# Crie e defina o diretório de trabalho dentro do contêiner
WORKDIR /app

# Copie os arquivos de dependência do Poetry primeiro para aproveitar o cache do Docker
COPY pyproject.toml poetry.lock ./

# Instale Poetry globalmente e configure-o para criar o venv in-project
# Em seguida, instale as dependências com Poetry
RUN pip install poetry && \
    poetry config virtualenvs.in-project true && \
    poetry install --no-root --no-dev

# Copie o restante do seu código para o contêiner
COPY . .

# Comando para iniciar sua aplicação.
# Ative o ambiente virtual do Poetry e então execute o main.py usando o python desse venv.
# 'source' precisa ser executado dentro de um shell (sh -c).
CMD ["sh", "-c", "source .venv/bin/activate && /app/.venv/bin/python main.py"]