# Dockerfile - produção (Render + Gunicorn)
FROM python:3.11-slim

# Logs sem buffer / sem .pyc
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Dependências do sistema (enxutas)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg git curl libffi-dev libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Python deps
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

EXPOSE 10000

# Gunicorn lendo a porta do Render ($PORT)
# (shell form para interpolar $PORT corretamente)
CMD gunicorn -w 2 -k gthread -b 0.0.0.0:$PORT main:app
