# Use uma imagem base Python oficial (Ubuntu-based)
FROM python:3.13-slim-bookworm

# Instale o FFmpeg e outras dependências de sistema necessárias
# O 'apt-get update' é necessário para garantir que as listas de pacotes estejam atualizadas antes de instalar
# O '&& rm -rf /var/lib/apt/lists/*' é para limpar o cache e reduzir o tamanho da imagem final
RUN apt-get update && apt-get install -y ffmpeg --no-install-recommends && rm -rf /var/lib/apt/lists/*

# Crie e defina o diretório de trabalho dentro do contêiner
WORKDIR /app

# Copie TODOS os arquivos do seu projeto para o contêiner ANTES de instalar as dependências Python
COPY . .

# Instale as dependências do Python usando Poetry
# Utilize o --no-root para não instalar o pacote do projeto como um pacote Python (já que é um app)
# A variável PATH é ajustada para incluir o diretório de scripts do venv do Poetry
# Isso permite que os comandos 'python' e 'pip' apontem para o venv
RUN pip install poetry && poetry install --no-root --no-dev && \
    export PATH="/root/.poetry/bin:$PATH" && \
    export PATH="$(poetry env info --path)/bin:$PATH"

# Comando para iniciar sua aplicação
# Este comando agora ativa o ambiente virtual do Poetry e então executa o main.py
CMD ["sh", "-c", "source $(poetry env info --path)/bin/activate && python main.py"]