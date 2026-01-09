# Dockerfile - produção (Render + Gunicorn)
# Blindado contra cache fantasma e deploy silencioso

FROM python:3.11-slim

# -------------------------
# Identidade da imagem (BLINDAGEM)
# -------------------------
ARG APP_TAG=prod
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown

ENV APP_TAG=${APP_TAG} \
    GIT_COMMIT=${GIT_COMMIT} \
    BUILD_TIME=${BUILD_TIME}

# -------------------------
# Python runtime hygiene
# -------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# -------------------------
# Dependências do sistema
# -------------------------
# ffmpeg        -> pydub / áudio
# libsndfile1   -> libs de áudio
# build-essential / libffi-dev -> wheels nativas
# git / curl    -> diagnósticos e deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        curl \
        libffi-dev \
        libsndfile1 \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# -------------------------
# Diretório da aplicação
# -------------------------
WORKDIR /app

# -------------------------
# Dependências Python (camada separada = cache saudável)
# -------------------------
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# -------------------------
# Código da aplicação (ANTI-CACHE SILENCIOSO)
# -------------------------
COPY . /app

# -------------------------
# Porta (Render injeta PORT em runtime)
# -------------------------
EXPOSE 10000
ENV PORT=10000

# -------------------------
# Inicialização (único ponto de entrada)
# server.py -> app.py (como vocês já usam)
# -------------------------
CMD gunicorn server:app \
    -k gthread \
    --workers 2 \
    --threads 8 \
    --bind 0.0.0.0:$PORT \
    --access-logfile - \
    --error-logfile -
