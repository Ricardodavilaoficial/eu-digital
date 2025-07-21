FROM python:3.10-slim

# Cria diretório do app
WORKDIR /app

# Copia arquivos
COPY . .

# Instala dependências
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Expõe porta exigida pelo Render
EXPOSE 10000

# Comando para rodar a aplicação
CMD ["python", "main.py"]
