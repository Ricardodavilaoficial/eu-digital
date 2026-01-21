# Dockerfile - produo (Render + Gunicorn)
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
# Dependncias do sistema
# -------------------------
# ffmpeg        -> pydub / udio
# libsndfile1   -> libs de udio
# build-essential / libffi-dev -> wheels nativas
# git / curl    -> diagnsticos e deps
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
# Diretrio da aplicao
# -------------------------
WORKDIR /app

# -------------------------
# Dependncias Python (camada separada = cache saudvel)
# -------------------------
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# -------------------------
# Cdigo da aplicao (ANTI-CACHE SILENCIOSO)
# -------------------------
COPY . /app

# -------------------------
# Porta (Render injeta PORT em runtime)
# -------------------------
# EXPOSE 10000  # (Cloud Run)
# ENV PORT=10000  # (Cloud Run)

# -------------------------
# Inicializao (nico ponto de entrada)
# server.py -> app.py (como vocs j usam)
# -------------------------
CMD sh -c "gunicorn app:app -k gthread --workers 2 --threads 8 --bind 0.0.0.0:${PORT:-8080} --access-logfile - --error-logfile -"
