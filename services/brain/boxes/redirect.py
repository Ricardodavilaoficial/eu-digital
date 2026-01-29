\
# services/brain/boxes/redirect.py
# Caixa: REDIRECT (fora do escopo) — respostas curtas, humanas, sem enrolar.

from __future__ import annotations

def render_redirect(intent: str = "") -> str:
    i = (intent or "").strip().upper()

    # Redirecionamento: não promete serviço que não existe; reposiciona rápido e dá saída (link).
    if i == "CUSTOM_SOFTWARE_QUOTE":
        return (
            "Entendi 🙂 A gente não faz programa sob medida.\n"
            "O que a gente faz é o **MEI Robô**: atende seus clientes no WhatsApp, organiza agenda e evita perder venda.\n"
            "Pra ver como funciona e valores: www.meirobo.com.br"
        )

    if i == "PERSONAL_MESSAGE_REQUEST":
        return (
            "Posso te ajudar sim — mas eu não consigo mandar recado pra outra pessoa diretamente.\n"
            "Se você me disser o recado (curtinho) e o nome dele(a), eu te devolvo pronto pra copiar e colar."
        )

    # Genérico (OFFTOPIC)
    return (
        "Entendi 🙂\n"
        "Eu sou o **MEI Robô** e ajudo com atendimento no WhatsApp (agenda, respostas e organização).\n"
        "Se quiser ver como funciona e valores: www.meirobo.com.br"
    )
