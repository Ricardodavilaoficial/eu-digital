import os
import openai
import traceback

from services.gcs_handler import montar_contexto_para_pergunta
from services.openai.prompt_manager import gerar_prompt_base
from services.openai.history_manager import (
    limpar_e_iniciar,
    adicionar_entrada,
    obter_historico
)

openai.api_key = os.getenv("OPENAI_API_KEY")

def obter_resposta_openai(pergunta, cliente="Ricardo"):
    try:
        print(f"\n📨 Pergunta recebida: {pergunta}")

        # Tenta montar contexto relevante do Firestore/Storage
        contexto_extra = montar_contexto_para_pergunta(pergunta)
        print(f"📚 Contexto montado (parcial): {contexto_extra[:100]}...")

        # Gera o prompt base com identidade do cliente
        prompt_base = gerar_prompt_base(cliente, contexto_extra)

        # Se for a primeira interação ou histórico estiver limpo, reinicia
        if not obter_historico():
            limpar_e_iniciar(prompt_base)

        # Decide se vai usar GPT-4 ou GPT-3.5 baseado na pergunta
        usar_gpt_4 = (
            len(pergunta.split()) > 15
            or "detalhe" in pergunta.lower()
            or "explique" in pergunta.lower()
            or "aprofund" in pergunta.lower()
        )
        modelo_escolhido = "gpt-4" if usar_gpt_4 else "gpt-3.5-turbo"
        print(f"🤖 Modelo escolhido: {modelo_escolhido}")

        # Adiciona a pergunta ao histórico
        adicionar_entrada("user", pergunta)

        # Gera resposta com histórico enxuto
        resposta = openai.ChatCompletion.create(
            model=modelo_escolhido,
            messages=obter_historico()
        )

        if not resposta or not resposta.choices or not resposta.choices[0].message:
            print("⚠️ Resposta da IA vazia ou inválida.")
            return "Desculpe, não consegui formular uma resposta agora."

        resposta_texto = resposta.choices[0].message.content.strip()
        print(f"✅ Resposta gerada: {resposta_texto}")

        # Adiciona resposta ao histórico
        adicionar_entrada("assistant", resposta_texto)

        return resposta_texto

    except Exception as e:
        print("❌ Erro ao gerar resposta com OpenAI:")
        traceback.print_exc()
        return "Desculpe, houve um problema ao tentar responder."
