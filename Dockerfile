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
# requirements pode estar na raiz OU dentro de mei-robo-whatsapp-webhook/
# copiamos o que existir, sem quebrar o build.
COPY requirements*.txt /tmp/req_root/
COPY mei-robo-whatsapp-webhook/requirements*.txt /tmp/req_webhook/

RUN set -eux; \
    if [ -f /tmp/req_root/requirements.txt ]; then \
        cp /tmp/req_root/requirements.txt /app/requirements.txt; \
    elif [ -f /tmp/req_webhook/requirements.txt ]; then \
        cp /tmp/req_webhook/requirements.txt /app/requirements.txt; \
    else \
        echo "ERROR: requirements.txt not found in build context"; \
        ls -la /; ls -la /tmp; ls -la /tmp/req_root || true; ls -la /tmp/req_webhook || true; \
        exit 1; \
    fi
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
# Default (pode ser sobrescrito via ENV no Cloud Run)
ENV GUNICORN_CMD_ARGS="-k gthread --workers 1 --threads 16 --timeout 30 --graceful-timeout 10 --access-logfile - --error-logfile -"

CMD sh -c "exec gunicorn app:app --bind 0.0.0.0:${PORT:-8080} $GUNICORN_CMD_ARGS"