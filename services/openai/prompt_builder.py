from services.gcs_handler import montar_contexto_para_pergunta

def construir_prompt(pergunta):
    """
    Cria o prompt do 'clone digital' com contexto enxuto, estilo e instruções do usuário.
    """
    contexto_extra = montar_contexto_para_pergunta(pergunta)
    contexto_limitado = contexto_extra[:1200] if contexto_extra else ""

    prompt = {
        "role": "system",
        "content": (
            "Você é a versão digital do Ricardo, replicando seu estilo e maneira de falar com naturalidade. "
            "Responda sempre em primeira pessoa, com frases curtas, simples e diretas, "
            "sem parecer uma IA. Evite linguagem genérica. "
            "Baseie-se no seguinte contexto, se for útil:\n\n"
            f"{contexto_limitado}"
        )
    }

    return prompt
