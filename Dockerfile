# Use uma imagem base Python oficial (Ubuntu-based)
FROM python:3.13-slim-bookworm

# Instale o FFmpeg e outras dependências de sistema necessárias
RUN apt-get update && apt-get install -y ffmpeg --no-install-recommends && rm -rf /var/lib/apt/lists/*

# Crie e defina o diretório de trabalho dentro do contêiner
WORKDIR /app

# Copie os arquivos de dependência primeiro para aproveitar o cache do Docker
# Isso otimiza o build, pois se apenas o código mudar, esta camada não precisa ser reconstruída
COPY pyproject.toml poetry.lock requirements.txt ./

# Instale as dependências usando pip a partir do requirements.txt copiado
RUN pip install -r requirements.txt

# Copie o restante do seu código para o contêiner
# Isso inclui main.py, services/, interfaces/, etc.
COPY . .

# Comando para iniciar sua aplicação.
# O Python agora pode encontrar o Flask porque foi instalado globalmente pelo pip.
# Certifique-se de que seu Flask app está configurado para ouvir na porta 10000 (ou na variável de ambiente PORT).
CMD ["python", "main.py"]