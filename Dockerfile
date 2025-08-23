# Dockerfile - produ��o (Render + Gunicorn) - est�vel p/ pydub + ffmpeg
FROM python:3.11-slim

# Logs sem buffer / sem .pyc
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Depend�ncias do sistema (enxutas)
# - ffmpeg: necess�rio pro pydub
# - build-essential: compila wheels nativas quando necess�rio
# - libsndfile1: alguns libs de �udio usam
# - git/curl: �teis p/ instalar deps e diagn�sticos
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg git curl libffi-dev libsndfile1 build-essential \
    && rm -rf /var/lib/apt/lists/*

# Use o path padr�o do Render para evitar surpresas em paths relativos
WORKDIR /opt/render/project/src

# Instale deps primeiro p/ melhor cache
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copie o restante do app
COPY . .

# Render define $PORT em runtime (n�o precisa expor, mas mant�m por clareza)
EXPOSE 10000

# IMPORTANTE: se seu app principal � app.py, use app:app
# (Se for main.py, troque para main:app)
# Shell form para interpolar $PORT corretamente
CMD gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT app:app
