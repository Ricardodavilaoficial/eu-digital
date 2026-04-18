# -*- coding: utf-8 -*-
"""services/sales_guardrails.py

Guardrails mínimos e estratégicos para o Conversational Front (Vendas SHOW).

Meta:
- reduzir alucinação (principalmente prazos/tempo e "documentação")
- evitar pergunta fraca no final
- manter a IA dona do entendimento (não encher de ifs)
"""

from __future__ import annotations

import re
from typing import Any, Dict


_NUM_TIME_RE = re.compile(r"\b\d+\s*(minutos?|horas?|dias?|semanas?|meses?)\b", re.I)
_FUZZY_TIME_RE = re.compile(r"\b(alguns?\s+minutos?|em\s+poucos\s+minutos?|rapidinho|muito\s+r[aá]pido)\b", re.I)
_DOC_WORD_RE = re.compile(r"\b(documentaç[aã]o|documentos?)\b", re.I)

_WEAK_QUESTIONS_RE = re.compile(
    r"(voc[eê]\s+j[aá]\s+tem\s+tudo\s+pronto\?|qual\s+[ée]\s+o\s+seu\s+tipo\s+de\s+neg[oó]cio\?|posso\s+te\s+ajudar\s+a\s+entender\s+melhor.*\?)",
    re.I,
)

_GENERIC_RE = re.compile(
    r"\b(facilitar\s+a\s+gest[aã]o|otimizar\s+tempo|ferramentas\s+pr[aá]ticas|solu[cç][aã]o\s+inovadora|projetad[ao]\s+para\s+facilitar|oferecendo\s+ferramentas\s+pr[aá]ticas|forma\s+pr[aá]tica\s+e\s+r[aá]pida|poucos\s+cliques)\b",
    re.I,
)

_PROF_WORD_RE = re.compile(
    r"\b(psic[oó]logo|dentista|advogad[oa]|barbeiro|sal[aã]o|cabeleireir[oa]|est[eé]tica|cl[ií]nica)\b",
    re.I,
)


def _safe_preview(text: str, limit: int = 240) -> str:
    try:
        s = str(text or "").strip()
        if len(s) <= limit:
            return s
        return s[: limit - 3].rstrip() + "..."
    except Exception:
        return ""


def _mutation_level(before: str, after: str, mutations: list[str]) -> str:
    try:
        b = str(before or "").strip()
        a = str(after or "").strip()
        if not mutations and b == a:
            return "none"
        if b == a and mutations:
            return "light"
        if not b and a:
            return "semantic_risk"
        if b and not a:
            return "semantic_risk"
        # mudança grande de tamanho costuma indicar recomposição forte
        delta = abs(len(a) - len(b))
        base = max(len(b), 1)
        if (delta / base) >= 0.35:
            return "semantic_risk"
        return "light"
    except Exception:
        return "unknown"


def _looks_like_detailed_scene(text: str) -> bool:
    t = str(text or "").strip().lower()
    if not t:
        return False
    return (
        ("na prática:" in t)
        or ("cliente pede" in t)
        or ("cliente pergunta" in t)
        or ("cliente manda" in t)
        or ("o robô" in t and "resumo" in t)
        or ("painel" in t)
        or ("confirma por escrito" in t)
        or ("fica registrado" in t)
    )


def _strip_extra_questions(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    # Mantém no máximo a primeira pergunta
    parts = t.split("?")
    if len(parts) <= 2:
        return t
    return (parts[0] + "?").strip()


def _replace_last_question(text: str, new_q: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    if "?" not in t:
        return (t + " " + new_q).strip()
    # troca a última pergunta inteira por new_q
    # heurística: corta do último '?' para trás até um delimitador
    last_q = t.rfind("?")
    cut = t.rfind(".", 0, last_q)
    cut2 = t.rfind("\n", 0, last_q)
    cut = max(cut, cut2)
    if cut == -1:
        return new_q
    return (t[: cut + 1].strip() + " " + new_q).strip()


def apply_sales_guardrails(
    *,
    reply_text: str,
    spoken_text: str,
    topic: str,
    confidence: str,
    user_text: str,
    kb_context: Dict[str, Any],
) -> Dict[str, str]:
    r = (reply_text or "").strip()
    s = (spoken_text or "").strip()
    reply_before = r
    spoken_before = s
    flags: Dict[str, Any] = {}
    mutations: list[str] = []

    segment_hint = str((kb_context or {}).get("segment_hint") or "").strip().lower()
    intent_hint = str((kb_context or {}).get("intent_hint") or "").strip().upper()
    price_text_exact = str((kb_context or {}).get("price_text_exact") or "").strip()
    price_text_plus_exact = str((kb_context or {}).get("price_text_plus_exact") or "").strip()
    no_fidelity = str((kb_context or {}).get("no_fidelity") or "").strip()
    is_trial = bool((kb_context or {}).get("is_trial"))
    practical_example_hint = str((kb_context or {}).get("practical_example_hint") or "").strip()
    practical_scene_from_kb = str((kb_context or {}).get("practical_scene_from_kb") or "").strip()
    question_hint_strong = str((kb_context or {}).get("question_hint_strong") or "").strip()
    continuation_hint = str((kb_context or {}).get("continuation_hint") or "").strip()
    no_free_trial = str((kb_context or {}).get("no_free_trial") or "").strip()
    sla_exact = str((kb_context or {}).get("process_sla_text_exact") or "").strip()
    sla_setup = str((kb_context or {}).get("sla_setup_exact") or "").strip()
    free_mode = bool((kb_context or {}).get("free_mode"))
    allow_docs_word = bool(_DOC_WORD_RE.search(sla_exact)) or bool(_DOC_WORD_RE.search(sla_setup))
    has_detailed_scene = _looks_like_detailed_scene(r) or _looks_like_detailed_scene(practical_scene_from_kb)

    # ----------------------------------------------------------
    # PREÇO: guardrail factual, não renderer.
    # Regra de arquitetura:
    # - preço canônico vem exclusivamente de platform_pricing/current
    # - este módulo não deve reconstruir a resposta inteira
    # - a IA continua dona da fala; aqui só sinalizamos contexto factual
    # ----------------------------------------------------------
    topic_upper = (topic or "").strip().upper()
    is_price = topic_upper == "PRECO" or intent_hint == "PRECO"
    flags["is_price"] = bool(is_price)
    flags["is_trial"] = bool(is_trial or intent_hint in ("TRIAL", "FREE_TRIAL"))
    flags["free_mode"] = bool(free_mode)
    flags["has_detailed_scene"] = bool(has_detailed_scene)
    if is_price and price_text_exact:
        flags["price_canonical_available"] = True
        flags["price_source"] = "platform_pricing/current"
        if price_text_plus_exact:
            flags["price_has_two_plans"] = True
        else:
            flags["price_has_two_plans"] = False
        if no_fidelity:
            flags["no_fidelity_available"] = True
        if not free_mode:
            flags["price_rewrite_suppressed"] = True


    # ----------------------------------------------------------
    # TRIAL/GRÁTIS: guardrail factual, não renderer.
    # Regra de arquitetura:
    # - não prometer teste grátis
    # - não mandar link acidental
    # - não reconstruir a resposta inteira
    # ----------------------------------------------------------
    if is_trial or intent_hint in ("TRIAL", "FREE_TRIAL"):
        flags["trial_policy_detected"] = True
        flags["trial_source"] = "kb_context"
        if no_free_trial:
            flags["trial_canonical_text_available"] = True
        if no_fidelity:
            flags["no_fidelity_available"] = True
        if price_text_exact:
            flags["price_canonical_available"] = True
            flags["price_source"] = "platform_pricing/current"
        if price_text_plus_exact:
            flags["price_has_two_plans"] = True
        else:
            flags["price_has_two_plans"] = False
        if not free_mode:
            flags["trial_rewrite_suppressed"] = True

        # Remove qualquer URL acidental sem reescrever o corpo.
        if r and re.search(r"https?://\S+", r):
            r = re.sub(r"https?://\S+", "", r).strip()
            mutations.append("strip_trial_accidental_url")
        if s and re.search(r"https?://\S+", s):
            s = re.sub(r"https?://\S+", "", s).strip()
            mutations.append("strip_trial_accidental_url_spoken")



    # 0) Anti-floreio genérico + anti-chute de profissão quando não sabemos segmento
    try:
        if r and _GENERIC_RE.search(r):
            flags["generic_language_detected"] = True
            r = _GENERIC_RE.sub("", r)
            r = re.sub(r"\s{2,}", " ", r).strip()
            mutations.append("strip_generic_language")

        # Se não sabemos o segmento, não cite profissões (ex.: psicólogo)
        if r and (not segment_hint) and _PROF_WORD_RE.search(r) and (not _PROF_WORD_RE.search(user_text or "")):
            flags["invented_profession_detected"] = True
            r = _PROF_WORD_RE.sub("seu negócio", r).strip()
            mutations.append("replace_invented_profession")

        # não criar resposta SHOW aqui; guardrail não deve virar gerador
    except Exception:
        pass

    # 1) Anti-invenção de prazo/tempo: se tiver SLA exato no KB, use ele e limpe outros tempos
    if intent_hint in ("PROCESS_SLA", "PROCESS", "ACTIVATE", "SLA"):
        if sla_exact or sla_setup:
            # remove números/tempos que não sejam o SLA oficial
            r = _NUM_TIME_RE.sub("", r).strip()
            r = _FUZZY_TIME_RE.sub("", r).strip()
            # garante o SLA oficial (texto do KB)
            sla_line = sla_exact or sla_setup
            if sla_line and sla_line.lower() not in r.lower():
                r = (r + ("\n" if r else "") + sla_line).strip()
        else:
            # não tem SLA no KB -> linguagem segura SEM número
            r = _NUM_TIME_RE.sub("", r).strip()
            r = _FUZZY_TIME_RE.sub("em poucos dias", r).strip()

    # 2) Anti-"documentação" genérica (quando não está explícito no KB)
    if r and _DOC_WORD_RE.search(r) and not allow_docs_word:
        flags["docs_word_sanitized"] = True
        r = _DOC_WORD_RE.sub("o básico", r).strip()
        mutations.append("replace_docs_word")



    # ativação continua com a IA; aqui não reconstruímos a resposta

    # 2.5) Anti-genérico: corta “corporativês” sem reconstruir a resposta.
    # Guardrail não deve virar redator nem reinjetar valor/microcena aqui.
    if r and _GENERIC_RE.search(r):
        flags["generic_language_detected_after_pass"] = True
        r = _GENERIC_RE.sub(" ", r)
        r = re.sub(r"\s{2,}", " ", r).strip()
        mutations.append("strip_generic_language_second_pass")
        flags["generic_rewrite_suppressed"] = True


    # 3) Detectar pergunta sem reescrever a resposta.
    # Produto: perguntas foram abolidas, salvo exceções tratadas no front.
    strong_q = str((kb_context or {}).get("cta_question_strong") or "").strip()
    if (not free_mode) and r and _WEAK_QUESTIONS_RE.search(r):
        flags["weak_question_detected"] = True
        flags["weak_question_rewrite_suppressed"] = True
    else:
        # Se terminar com pergunta muito genérica, apenas sinaliza.
        if (not free_mode) and r.endswith("?") and re.search(r"\b(come[çc]ar|entender|servi[çc]os\s+dispon[ií]veis)\b", r, re.I):
            flags["weak_question_detected"] = True
            flags["weak_question_rewrite_suppressed"] = True

    if "?" in r:
        flags["question_detected"] = True
    if "?" in s:
        flags["spoken_question_detected"] = True

    # 4) No máximo 1 pergunta (última barreira)
    r = _strip_extra_questions(r)
    s = _strip_extra_questions(s)
    if r != (reply_text or "").strip():
        flags["reply_changed"] = True
    if s != (spoken_text or "").strip():
        flags["spoken_changed"] = True

    # Guardrail não injeta CTA automático.

    # No free_mode, protege fatos mas preserva a autonomia da IA.
    if free_mode:
        # não recoloca CTA/pergunta, não reconstrói resposta
        # só faz higiene mínima
        r = re.sub(r"\s{2,}", " ", r).strip()
        s = re.sub(r"\s{2,}", " ", s).strip()
        mutations.append("free_mode_whitespace_hygiene")

    if not s:
        s = r
        mutations.append("spoken_fallback_to_reply")

    if len(s) > 240:
        s = s[:237].rstrip() + "..."
        mutations.append("spoken_truncate_240")

    return {
        "reply_text": r,
        "spoken_text": s,
        "flags": flags,
        "mutations": mutations,
        "mutation_level": _mutation_level(reply_before, r, mutations),
        "debug_before": {
            "reply_text": _safe_preview(reply_before),
            "spoken_text": _safe_preview(spoken_before),
        },
        "debug_after": {
            "reply_text": _safe_preview(r),
            "spoken_text": _safe_preview(s),
        },
    }
