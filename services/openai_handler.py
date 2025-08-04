import openai
import os
from services.gcs_handler import montar_contexto_para_pergunta

openai.api_key = os.getenv("OPENAI_API_KEY")

# Histórico temporário de conversas recentes
chat_history = []

def obter_resposta_openai(pergunta):
    try:
        print(f"\n📨 Pergunta recebida: {pergunta}")
        
        # Novo: monta um contexto enxuto baseado na pergunta
        contexto_extra = montar_contexto_para_pergunta(pergunta)
        print(f"📚 Contexto montado: {contexto_extra[:100]}...")  # Exibe só os primeiros 100 caracteres

        # Limpa o histórico se já está muito longo
        if len(chat_history) > 6:
            chat_history.clear()

        # Adiciona o prompt inicial apenas se o histórico estiver vazio
        if not chat_history:
            chat_history.append({
                "role": "system",
                "content": (
                    "Você é a versão digital do Ricardo, uma cópia fiel de sua mente, memórias e modo de falar. "
                    "Sempre responda em primeira pessoa, como se fosse o próprio Ricardo. "
                    "Use linguagem natural, clara e direta. "
                    "Responda de forma curta e objetiva, a menos que o usuário peça mais detalhes. "
                    "Use o contexto abaixo como base de conhecimento:\n\n" + contexto_extra
                )
            })

        # Adiciona a pergunta do usuário ao histórico
        chat_history.append({"role": "user", "content": pergunta})

        # Escolhe o modelo (GPT-3.5 ou GPT-4) com base na complexidade
        usar_gpt_4 = (
            len(pergunta.split()) > 15
            or "detalhe" in pergunta.lower()
            or "explique" in pergunta.lower()
            or "aprofund" in pergunta.lower()
        )

        modelo_escolhido = "gpt-4" if usar_gpt_4 else "gpt-3.5-turbo"
        print(f"🤖 Modelo escolhido: {modelo_escolhido}")

        resposta = openai.ChatCompletion.create(
            model=modelo_escolhido,
            messages=chat_history
        )

        resposta_texto = resposta.choices[0].message.content.strip()
        print(f"✅ Resposta gerada: {resposta_texto}")

        # Adiciona a resposta da IA ao histórico
        chat_history.append({"role": "assistant", "content": resposta_texto})

        return resposta_texto

    except Exception as e:
        print("❌ Erro com OpenAI:", e)
        return "Desculpe, houve um problema ao tentar responder."