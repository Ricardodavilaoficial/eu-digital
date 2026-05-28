# services/front_policies.py
# Fase 3A — Políticas de tamanho, formatação e truncamento do Conversational Front.
#
# Regras:
# - Não chama LLM.
# - Não acessa Firestore.
# - Apenas aplica regras de tamanho e acabamento de texto.

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Optional, Tuple

from services.front_utils import normalize_identity_text as _front_normalize_identity_text


# Constantes de política de tamanho.
FRONT_TEXT_INITIAL_MAX_CHARS = int(os.getenv("FRONT_TEXT_INITIAL_MAX_CHARS", "850") or 850)
FRONT_TEXT_SCENE_MAX_CHARS = int(os.getenv("FRONT_TEXT_SCENE_MAX_CHARS", "800") or 800)
FRONT_TEXT_SEQUENCE_MAX_CHARS = int(os.getenv("FRONT_TEXT_SEQUENCE_MAX_CHARS", "600") or 600)
FRONT_TEXT_CLOSING_MAX_CHARS = int(os.getenv("FRONT_TEXT_CLOSING_MAX_CHARS", "360") or 360)
FRONT_AUDIO_INITIAL_MAX_CHARS = int(os.getenv("FRONT_AUDIO_INITIAL_MAX_CHARS", "620") or 620)
FRONT_AUDIO_SCENE_MAX_CHARS = int(os.getenv("FRONT_AUDIO_SCENE_MAX_CHARS", "580") or 580)
FRONT_AUDIO_SEQUENCE_MAX_CHARS = int(os.getenv("FRONT_AUDIO_SEQUENCE_MAX_CHARS", "430") or 430)
FRONT_AUDIO_CLOSING_MAX_CHARS = int(os.getenv("FRONT_AUDIO_CLOSING_MAX_CHARS", "280") or 280)


def _front_trim_to_complete_sentence(text: str, max_chars: int) -> str:
    """
    Corta texto apenas no limite de palavra, sem procurar frase completa.
    Usado somente quando a resposta técnica DIRECT já foi aceita pela IA,
    pois nesses casos cortar na última frase completa pode remover a parte
    operacional mais importante da explicação.
    """
    try:
        s = str(text or "").strip()
        if not s:
            return ""

        max_chars = int(max_chars or 0)
        if max_chars <= 0 or len(s) <= max_chars:
            return s

        cut = s[:max_chars].rstrip()
        last_space = cut.rfind(" ")
        min_good = max(220, int(max_chars * 0.70))

        if last_space >= min_good:
            out = cut[:last_space].strip()
        else:
            out = cut.strip()

        out = re.sub(r"[\s,;:–—-]+$", "", out).strip()
        if out and out[-1] not in ".!?":
            out += "."
        return out
    except Exception:
        return str(text or "").strip()


def _preserve_technical_direct_reply_size(
    text: str,
    policy: Any,
    *,
    reply_source: str = "",
    response_mode: str = "",
    topic: str = "",
    operational_contract: Any = None,
) -> Tuple[str, Any]:
    """
    Ajusta exclusivamente a política de tamanho para respostas DIRECT de alto
    valor operacional originadas da platform_kb.

    Objetivo:
    - Permitir que respostas técnicas em texto concluam o fluxo operacional.
    - Não alterar prompts.
    - Não liberar microcena.
    - Não afetar áudio.
    - Preservar todas as demais regras globais de tamanho.
    """
    try:
        if not isinstance(text, str) or not text.strip():
            return text, policy

        if not isinstance(policy, dict):
            return text, policy

        if bool(policy.get("is_audio")):
            return text, policy

        contract = (
            operational_contract
            if isinstance(operational_contract, dict)
            else {}
        )

        source = str(reply_source or "").strip()
        mode = str(response_mode or "").strip().upper()
        canonical_topic = str(topic or "").strip().upper()

        is_real_platform_runtime = bool(
            contract.get("hydrated_from_platform_kb")
            or contract.get("hydrated_from_docs")
        )
        is_global_pack_fallback = bool(contract.get("global_pack_fallback"))

        if is_global_pack_fallback and not is_real_platform_runtime:
            return text, policy

        is_platform_runtime = bool(is_real_platform_runtime)

        is_technical_direct = bool(
            source == "front_structured_python_assembly"
            and mode == "DIRECT"
            and canonical_topic in (
                "AGENDA",
                "SERVICOS",
                "PEDIDOS",
                "STATUS",
                "PROCESSO",
                "ORCAMENTO",
            )
            and is_platform_runtime
        )

        if not is_technical_direct:
            return text, policy

        adjusted = dict(policy)
        adjusted["target_chars"] = max(
            int(adjusted.get("target_chars") or 0),
            740,
        )
        adjusted["max_chars"] = max(
            int(adjusted.get("max_chars") or 0),
            820,
        )

        try:
            logging.info(
                "[REPLY_SIZE_POLICY][TECH_DIRECT_APPLIED] "
                "topic=%s source=%s len=%s target=%s max=%s",
                canonical_topic,
                source,
                len(text),
                adjusted.get("target_chars"),
                adjusted.get("max_chars"),
            )
        except Exception:
            pass

        return text, adjusted

    except Exception:
        return text, policy


def _smart_truncate_text(text: str, max_chars: int) -> str:
    """
    Truncamento seguro:
    - evita cortar no meio da palavra
    - tenta manter final de frase
    - não altera conteúdo, só encurta
    """
    try:
        t = str(text or "").strip()
        if not t or len(t) <= max_chars:
            return t

        cut = t[:max_chars].rstrip()

        # tenta cortar no último ponto final
        last_dot = cut.rfind(".")
        if last_dot > int(max_chars * 0.6):
            return cut[: last_dot + 1].strip()

        # senão, corta na última palavra inteira
        last_space = cut.rfind(" ")
        if last_space > int(max_chars * 0.6):
            return cut[:last_space].strip() + "..."

        return cut + "..."
    except Exception:
        return str(text or "")[:max_chars]


def _resolve_reply_size_policy(
    *,
    ai_turns: int = 0,
    msg_type: str = "",
    response_mode: str = "",
    next_step: str = "",
    topic: str = "",
    kb_rich: bool = False,
    confidence: str = "",
    needs_clarify: str = "",
    clarify_q: str = "",
    effective_segment: str = "",
    question_type: str = "broad",
) -> Dict[str, Any]:
    """
    Define tamanho alvo por necessidade estrutural.
    O código decide o limite; a IA apenas escreve dentro da janela.
    """
    try:
        turns = int(ai_turns or 0)
    except Exception:
        turns = 0

    mt = str(msg_type or "").strip().lower()
    mode = str(response_mode or "").strip().upper()
    ns = str(next_step or "").strip().upper()
    tp = str(topic or "").strip().upper()
    conf = str(confidence or "").strip().lower()
    nc = str(needs_clarify or "").strip().lower()
    cq = str(clarify_q or "").strip()
    seg = str(effective_segment or "").strip()
    is_punctual = (str(question_type).strip().lower() == "punctual")

    is_audio = mt in ("audio", "voice", "ptt")
    is_closing = ns == "SEND_LINK" or mode == "CLOSING"
    is_discovery = mode == "DISCOVERY" or nc == "yes" or bool(cq)
    is_scene = mode == "SCENE"
    practical_topic = tp in ("AGENDA", "SERVICOS", "PEDIDOS", "STATUS", "PROCESSO", "ORCAMENTO")
    light_topic = tp in ("SOCIAL", "OTHER", "")

    rich_scene_need = bool(
        kb_rich
        and is_scene
        and practical_topic
        and conf == "high"
        and bool(seg)
    )

    medium_direct_need = bool(
        kb_rich
        and mode in ("DIRECT", "SCENE")
        and not light_topic
        and conf in ("high", "medium")
        and not rich_scene_need
    )

    light_need = bool(
        is_discovery
        or light_topic
        or conf in ("low", "")
        or not kb_rich
        or is_punctual
    )

    if is_punctual:
        rich_scene_need = False
        medium_direct_need = False

    if is_closing:
        max_chars = FRONT_AUDIO_CLOSING_MAX_CHARS if is_audio else FRONT_TEXT_CLOSING_MAX_CHARS
        target_chars = int(max_chars * 0.78)
        max_tokens = 90 if is_audio else 110
        label = "closing"
    elif is_audio:
        if rich_scene_need:
            max_chars = min(FRONT_AUDIO_INITIAL_MAX_CHARS, 560)
            target_chars = 470
            max_tokens = 170
            label = "audio_scene_rich"
        elif medium_direct_need:
            max_chars = min(FRONT_AUDIO_SCENE_MAX_CHARS, 460)
            target_chars = 380
            max_tokens = 145
            label = "audio_direct_medium"
        else:
            max_chars = FRONT_AUDIO_SEQUENCE_MAX_CHARS
            target_chars = 330
            max_tokens = 130
            label = "audio_light"
    else:
        if rich_scene_need:
            max_chars = FRONT_TEXT_INITIAL_MAX_CHARS
            target_chars = 700
            max_tokens = 270
            label = "text_scene_rich"
        elif medium_direct_need:
            if not seg:
                max_chars = min(FRONT_TEXT_SCENE_MAX_CHARS, 560)
                target_chars = 450
                max_tokens = 175
            else:
                max_chars = FRONT_TEXT_SCENE_MAX_CHARS
                target_chars = 560
                max_tokens = 220
            label = "text_direct_medium"
        elif light_need:
            max_chars = min(FRONT_TEXT_SEQUENCE_MAX_CHARS, 520)
            target_chars = 360
            max_tokens = 150
            label = "text_light"
        else:
            max_chars = FRONT_TEXT_SEQUENCE_MAX_CHARS
            target_chars = 430
            max_tokens = 170
            label = "text_default"

    return {
        "label": label,
        "target_chars": int(target_chars),
        "max_chars": int(max_chars),
        "max_tokens": int(max_tokens),
        "is_audio": bool(is_audio),
        "rich_scene_need": bool(rich_scene_need),
        "medium_direct_need": bool(medium_direct_need),
        "light_need": bool(light_need),
        "question_type": str(question_type or "broad"),
    }


def _apply_reply_size_policy(text: str, policy: Dict[str, Any] | None = None) -> str:
    """
    Aplica a política de tamanho já definida para a resposta final.
    Esta função deve respeitar integralmente os limites calculados em
    _resolve_reply_size_policy(...).
    """
    if not policy:
        return str(text or "").strip()

    s = str(text or "").strip()
    if not s:
        return ""

    try:
        max_chars = int(policy.get("max_chars") or 0)
    except Exception:
        max_chars = 0

    if max_chars <= 0:
        return s

    if len(s) <= max_chars:
        return s

    # ---------------------------------------------------------------
    # Truncamento inteligente
    #
    # Preserva a política de tamanho existente e apenas melhora o
    # ponto de corte, evitando terminar no meio de palavras.
    #
    # Estratégia:
    # 1) Respeita exatamente max_chars.
    # 2) Procura o último delimitador de frase no trecho permitido.
    # 3) Se não encontrar, corta no último espaço.
    # 4) Como fallback, usa o corte bruto.
    # ---------------------------------------------------------------
    clipped = s[:max_chars]

    # Procura final natural de frase suficientemente próximo do fim.
    sentence_cut = max(
        clipped.rfind("."),
        clipped.rfind("!"),
        clipped.rfind("?"),
    )

    # Só utiliza a pontuação se ela não descartar conteúdo demais.
    # Mantém ao menos ~70% do orçamento disponível.
    if sentence_cut >= int(max_chars * 0.70):
        natural = clipped[: sentence_cut + 1].rstrip()
        if natural:
            return natural

    # Fallback: corta no último espaço.
    word_cut = clipped.rfind(" ")
    if word_cut >= int(max_chars * 0.70):
        natural = clipped[:word_cut].rstrip()
        if natural:
            return natural

    # Último fallback: corte bruto.
    return clipped.rstrip()


def _front_remove_known_open_question_tail(text: str, candidates: Optional[list[str]] = None) -> str:
    """
    Remove cauda de pergunta aberta já conhecida pelo próprio contexto,
    inclusive quando ela perdeu o ponto de interrogação no trim.

    Não classifica profissão/segmento.
    Não usa lista de palavras-chave de negócio.
    """
    try:
        s = str(text or "").strip()
        if not s:
            return ""

        for cand in candidates or []:
            c = str(cand or "").strip()
            if not c:
                continue

            norm_s = _front_normalize_identity_text(s)
            norm_c = _front_normalize_identity_text(c)
            if not norm_c:
                continue

            pos = norm_s.rfind(norm_c)
            if pos < 0:
                continue

            # Remove apenas quando a cauda conhecida aparece perto do fim.
            if len(norm_s) - pos <= len(norm_c) + 8:
                raw_pos = max(0, len(s) - (len(norm_s) - pos))
                return s[:raw_pos].strip(" .,!?:;-\n\t")

        return s
    except Exception:
        return str(text or "").strip()


def _front_clean_free_mode_tail(text: str) -> str:
    """
    Limpa resíduos finais deixados por remoção de cauda aberta.
    Atua apenas no fim do texto, sem classificar profissão/segmento
    e sem depender de prompt.
    """
    try:
        s = str(text or "").strip()
        if not s:
            return ""

        # Remove fragmentos muito curtos no fim, como "Ho", gerados por
        # corte imperfeito de uma pergunta aberta removida.
        parts = s.split()
        if len(parts) >= 2 and len(parts[-1]) <= 2 and parts[-1].isalpha():
            s = " ".join(parts[:-1]).strip()

        s = s.strip(" ,;:-\n\t")

        if s and s[-1] not in ".!?":
            s = s.rstrip() + "."
        return s
    except Exception:
        return str(text or "").strip()


def _front_trim_free_mode_sentence(text: str, limit: int = 820) -> str:
    """
    Corte local para o FREE_MODE: preserva frase completa quando possível.
    Evita depender de versões duplicadas de _front_trim_to_complete_sentence.
    """
    try:
        s = str(text or "").strip()
        if not s:
            return ""
        # Mesmo quando o texto já vem abaixo do limite, ele pode ter sido
        # truncado antes por alguma camada anterior do pipeline.
        # Neste caso, não basta acrescentar ponto: isso gera saídas como
        # "confere a duração do serviço e.".
        #
        # A regra é estrutural:
        # - se já termina em frase completa, preserva;
        # - se não termina em pontuação, tenta voltar para a última frase
        #   completa útil;
        # - se não houver frase completa útil, aplica o acabamento antigo.
        if len(s) <= int(limit):
            if s[-1:] in ".!?":
                return _front_clean_free_mode_tail(s)

            last = max(s.rfind("."), s.rfind("!"), s.rfind("?"))
            if last >= 220:
                return _front_clean_free_mode_tail(s[: last + 1])

            return _front_clean_free_mode_tail(s)

        cut = s[: int(limit)].rstrip()
        last = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
        if last >= 220:
            return _front_clean_free_mode_tail(cut[: last + 1])

        return _front_clean_free_mode_tail(_front_trim_to_word_boundary_limit(cut, int(limit)))
    except Exception:
        return str(text or "").strip()[:limit].strip()
