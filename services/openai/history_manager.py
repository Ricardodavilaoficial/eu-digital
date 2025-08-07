# Histórico global controlado por sessão (no futuro: por usuário)
chat_history = []

def limpar_e_iniciar(prompt_base):
    """
    Limpa o histórico e reinicia com o prompt base do clone digital.
    """
    global chat_history
    chat_history = [prompt_base]
    return chat_history

def adicionar_entrada(role, conteudo):
    """
    Adiciona uma nova mensagem ao histórico (user ou assistant).
    """
    global chat_history
    chat_history.append({"role": role, "content": conteudo})

    # Se estiver muito longo, reduz o histórico mantendo o essencial
    if len(chat_history) > 6:
        chat_history = [chat_history[0]] + chat_history[-4:]

def obter_historico():
    """
    Retorna o histórico atual para ser usado na chamada da OpenAI.
    """
    return chat_history
