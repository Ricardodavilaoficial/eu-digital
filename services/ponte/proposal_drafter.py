def draft_proposal(event):
    extracted = event.get("extracted") or {}
    classification = event.get("classification") or {}
    language = extracted.get("language") or event.get("source_language") or "pt-BR"
    title = extracted.get("opportunity_title") or "seu projeto"
    description = extracted.get("description") or ""
    fit_level = classification.get("fit_level", "pendente")
    recommended_action = classification.get("recommended_action", "revisar_manualmente")

    if language == "en":
        body = (
            "Hello, I read your project and understood that you need help with "
            f"{title}.\n\n"
            "I can help by first reviewing the requirements, confirming the safest scope, "
            "and proposing a controlled implementation plan. My focus is automation, web workflows, "
            "AI-assisted customer service and reliable operational routines.\n\n"
            "Before starting, I would like to confirm the current process, the systems involved, "
            "and which actions should remain under manual approval.\n\n"
            "This is a draft proposal and should be reviewed before submission."
        )
    else:
        body = (
            f"Ola, li sua oportunidade sobre {title} e entendi que voce precisa de apoio "
            "para estruturar uma solucao segura e operacional.\n\n"
            "Posso ajudar revisando o fluxo atual, separando o que deve ser automatizado do que "
            "precisa continuar com aprovacao humana, e propondo uma implementacao controlada. "
            "Tenho foco em automacao, atendimento, IA aplicada, WhatsApp, web e processos comerciais.\n\n"
            "Antes de iniciar, eu confirmaria o escopo, os sistemas envolvidos e quais acoes podem "
            "ser executadas com seguranca.\n\n"
            "Este e um rascunho e deve ser revisado antes de qualquer envio."
        )

    return {
        "draft_text": body,
        "draft_language": "en" if language == "en" else "pt-BR",
        "fit_level": fit_level,
        "recommended_action": recommended_action,
        "requires_human_approval": True,
        "dry_run": True,
        "source_description_excerpt": description[:240],
    }
