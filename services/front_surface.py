from services.conversational_front import _normalize_response_mode


def _apply_response_mode_surface(
    *,
    response_mode: str,
    reply_text: str,
    spoken_text: str,
) -> tuple[str, str]:
    """
    Aplica apenas acabamento superficial por response_mode.

    Regras:
    - não decide intenção;
    - não altera response_mode;
    - não toca DISCOVERY identity guard;
    - não toca KB;
    - não toca micro_scene_allowed;
    - não gera conteúdo;
    - apenas normaliza espaços e sincroniza spoken/reply.
    """
    try:
        mode = _normalize_response_mode(response_mode) or "DIRECT"

        if mode == "SCENE":
            reply_text = str(reply_text or "").lstrip()
            spoken_text = str(spoken_text or reply_text or "").lstrip()
        else:
            reply_text = str(reply_text or "").strip()
            spoken_text = str(spoken_text or reply_text or "").strip()

        return reply_text, spoken_text
    except Exception:
        return (
            str(reply_text or "").strip(),
            str(spoken_text or reply_text or "").strip(),
        )


def _restore_final_candidate_if_degraded(
    *,
    reply_text: str,
    final_candidate: str,
) -> str:
    """
    Restaura candidato final quando a resposta degradou para vazia/curta.

    Não chama modelo.
    Não altera política.
    Não toca KB.
    Apenas preserva a melhor versão já produzida pelo fluxo.
    """
    try:
        if (
            final_candidate
            and (not reply_text or len(str(reply_text or "").strip()) < 40)
        ):
            return str(final_candidate or "").strip()
    except Exception:
        pass

    return str(reply_text or "").strip()

