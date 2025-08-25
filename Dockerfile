# Dockerfile - produ��o (Render + Gunicorn) - est�vel p/ pydub + ffmpeg
FROM python:3.11-slim

# Logs sem buffer / sem .pyc
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Depend�ncias do sistema (enxutas)
# - ffmpeg: necess�rio pro pydub
# - build-essential: compila wheels nativas quando necess�rio
# - libsndfile1: algumas libs de �udio usam
# - git/curl: �teis p/ instalar deps e diagn�sticos
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg git curl libffi-dev libsndfile1 build-essential \
    && rm -rf /var/lib/apt/lists/*

# Path padr�o do Render; mant�m imports relativos do projeto
WORKDIR /opt/render/project/src
ENV PYTHONPATH=/opt/render/project/src

# Instala deps primeiro p/ melhor cache
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copia o restante do app
COPY . .

# Render define $PORT em runtime (EXPOSE � opcional, mas ajuda em DX)
EXPOSE 10000
ENV PORT=10000

# Inicia o app PRINCIPAL da raiz (app.py -> app)
# - gthread p/ IO (webhook/HTTP) + threads extras
# - logs no stdout/stderr (Render capta)
CMD gunicorn app:app \
    -k gthread \
    --workers 2 \
    --threads 8 \
    --bind 0.0.0.0:$PORT \
    --access-logfile - \
    --error-logfile -
