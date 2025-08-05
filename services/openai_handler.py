import openai
import os
import traceback
from services.gcs_handler import montar_contexto_para_pergunta

openai.api_key = os.getenv("OPENAI_API_KEY")

# Histórico temporário de conversas recentes
chat_history = []

def obter_resposta_openai(pergunta):
    try:
        print(f"\n📨 Pergunta recebida: {pergunta}")

        # Monta contexto a partir dos arquivos do usuário
        contexto_extra = montar_contexto_para_pergunta(pergunta)
        print(f"📚 Contexto montado: {contexto_extra[:100]}...")  # Mostra apenas os 100 primeiros caracteres

        # Define prompt do "Ricardo digital"
        prompt_base = {
            "role": "system",
            "content": (
                "Você é a versão digital do Ricardo, uma cópia fiel de sua mente, memórias e modo de falar. "
                "Sempre responda em primeira pessoa, como se fosse o próprio Ricardo. "
                "Use linguagem natural, clara e direta. "
                "Responda de forma curta e objetiva, a menos que o usuário peça mais detalhes. "
                "Use o contexto abaixo como base de conhecimento:\n\n" + contexto_extra
            )
        }

        # Limpa o histórico e mantém apenas o prompt inicial se houver risco de ultrapassar tokens
        if len(chat_history) > 3:
            chat_history.clear()

        if not chat_history:
            chat_history.append(prompt_base)

        # Adiciona a pergunta do usuário
        chat_history.append({"role": "user", "content": pergunta})

        # Escolhe o modelo: GPT-3.5 por padrão, GPT-4 apenas se for um pedido mais elaborado
        usar_gpt_4 = (
            len(pergunta.split()) > 15
            or "detalhe" in pergunta.lower()
            or "explique" in pergunta.lower()
            or "aprofund" in pergunta.lower()
        )
        modelo_escolhido = "gpt-4" if usar_gpt_4 else "gpt-3.5-turbo"
        print(f"🤖 Modelo escolhido: {modelo_escolhido}")

        # Gera a resposta da IA
        resposta = openai.ChatCompletion.create(
            model=modelo_escolhido,
            messages=chat_history
        )

        if not resposta or not resposta.choices or not resposta.choices[0].message:
            print("⚠️ Resposta da IA vazia ou inválida.")
            return "Desculpe, não consegui formular uma resposta agora."

        resposta_texto = resposta.choices[0].message.content.strip()
        print(f"✅ Resposta gerada: {resposta_texto}")

        # Armazena resposta no histórico
        chat_history.append({"role": "assistant", "content": resposta_texto})

        return resposta_texto

    except Exception as e:
        print("❌ Erro ao gerar resposta com OpenAI:")
        traceback.print_exc()
        return "Desculpe, houve um problema ao tentar responder."
