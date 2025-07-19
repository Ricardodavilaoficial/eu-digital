import os

# Caminho para a pasta
pasta = 'Eu Digital - Ricardo'

# Listar todas as subpastas e arquivos
for raiz, dirs, arquivos in os.walk(pasta):
    for arquivo in arquivos:
        if arquivo.endswith('.txt'):
            caminho_arquivo = os.path.join(raiz, arquivo)
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                conteudo = f.read()
                print(f'Arquivo: {caminho_arquivo}')
                print(f'Conteúdo:\n{conteudo}\n')
