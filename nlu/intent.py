# nlu/intent.py
"""
MEI Robô — NLU v1 (stub inicial)
Objetivo: fornecer um ponto único de detecção de intenção sem alterar o comportamento atual.
Por padrão, o sistema continua usando o "legacy" (services/openai/nlu_intent.py).
Quando NLU_MODE=v1, este módulo passa a ser utilizado.
"""

from typing import Dict

# Mapa mínimo de intenções suportadas nesta fase
SUPPORTED = {
    "preco",       # quanto custa / preço / valores
    "agendar",     # agenda / marcar horário / quando tem vaga
    "faq",         # perguntas gerais/frequentes
    "saudacao",    # oi / olá / bom dia
    "desconhecida"
}

def _heuristics(text: str) -> str:
    t = (text or "").lower()

    # preço
    if any(k in t for k in ["preço", "preco", "quanto custa", "valor", "custa", "tabela"]):
        return "preco"

    # agendamento
    if any(k in t for k in ["agendar", "agenda", "marcar", "horário", "horario", "quando posso", "quando tem"]):
        return "agendar"

    # saudação
    if any(k in t for k in ["oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "e aí", "e ai"]):
        return "saudacao"

    # faq (bem amplo ainda)
    if any(k in t for k in ["onde fica", "endereço", "endereco", "funciona", "horas", "abre", "fecha"]):
        return "faq"

    return "desconhecida"

def detect_intent(text: str) -> Dict:
    """
    Retorna um dicionário padronizado de intenção.
    Não dispara ações nem consulta preços — apenas classifica.
    """
    intent = _heuristics(text)
    confidence = 0.65 if intent != "desconhecida" else 0.35

    return {
        "intent": intent,
        "confidence": confidence,
        "version": "v1-stub",
    }
