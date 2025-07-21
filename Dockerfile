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
RUN pip install poetry && poetry install --no-root

# Comando para iniciar sua aplicação
# Ajuste 'main.py' se o nome do seu arquivo principal for diferente
CMD ["poetry", "run", "python", "main.py"]
