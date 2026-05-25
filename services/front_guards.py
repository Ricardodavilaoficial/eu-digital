# services/front_guards.py
# Fase 2A — Guards e heurísticas puras do Conversational Front.
#
# Regras:
# - Não chama LLM.
# - Não acessa Firestore.
# - Não altera prompts.
# - Não grava estado.
# - Apenas avalia formato, densidade e segurança de textos.

from __future__ import annotations

import re
from typing import Any, Dict

from services.front_utils import (
    normalize_identity_text as _front_normalize_identity_text,
    looks_like_dialogue_stub as _looks_like_dialogue_stub,
    looks_like_technical_output as _looks_like_technical_output,
    split_sentences_pt as _split_sentences_pt,
)


def _looks_explanatory_sentence(text: str) -> bool:
    try:
        t = str(text or "").strip().lower()
        if not t:
            return False
        if t.startswith(("basicamente", "em resumo", "ou seja", "na prática", "então", "assim")):
            return True
        if "funciona assim" in t or "é o seguinte" in t:
            return True
        return False
    except Exception:
        return False


def _has_operational_shape(text: str) -> bool:
    try:
        t = str(text or "").strip()
        if not t:
            return False

        if len(t) < 28:
            return False

        sentences = [s.strip() for s in _split_sentences_pt(t) if str(s).strip()]
        if not sentences:
            return False

        if len(sentences) >= 2:
            return True

        first = sentences[0]
        if len(first) >= 45 and not first.endswith("?"):
            return True

        return False
    except Exception:
        return False


def _scene_transition_score(text: str) -> int:
    """
    Mede se o texto realmente avança de um estado para outro,
    sem depender de palavras específicas.

    Sinais usados:
    - mais de uma frase útil
    - baixa repetição de abertura entre frases
    - introdução de novos tokens ao longo da sequência
    - sobreposição parcial entre frases adjacentes
      (continuidade sem repetição estática)
    """
    try:
        t = str(text or "").strip()
        if not t:
            return 0

        sentences = [s.strip() for s in _split_sentences_pt(t) if str(s).strip()]
        if len(sentences) < 2:
            return 0

        score = 0

        tokenized = []
        openings = []
        for s in sentences:
            toks = [tok for tok in re.findall(r"\w+", s.lower()) if len(tok) >= 3]
            if toks:
                tokenized.append(toks)
                openings.append(" ".join(toks[:2]))
            else:
                tokenized.append([])
                openings.append("")

        uniq_openings = len({o for o in openings if o})
        if uniq_openings >= max(2, len(openings) - 1):
            score += 1

        introduced = 0
        seen = set()
        for toks in tokenized:
            fresh = [tok for tok in toks if tok not in seen]
            if len(fresh) >= 2:
                introduced += 1
            seen.update(toks)

        if introduced >= 2:
            score += 1

        linked_pairs = 0
        for i in range(len(tokenized) - 1):
            a = set(tokenized[i])
            b = set(tokenized[i + 1])
            if not a or not b:
                continue
            inter = len(a.intersection(b))
            union = len(a.union(b)) or 1
            ratio = inter / union
            if 0.08 <= ratio <= 0.45:
                linked_pairs += 1

        if linked_pairs >= 1:
            score += 1
        if linked_pairs >= 2:
            score += 1

        return score
    except Exception:
        return 0


def _operational_density_score(
    *,
    text: str,
    operational_reference: str,
    reference_example: str,
    effective_segment: str,
    operational_family: str,
) -> int:
    """
    Mede força operacional da resposta sem depender de palavras-chave fixas.

    A lógica é estrutural:
    - existe abertura com atividade principal?
    - existe microcena?
    - existe fechamento com consequência concreta?
    - o texto aproveita ancoragem do banco?
    """
    try:
        t = str(text or "").strip()
        if not t:
            return 0

        score = 0

        sentences = [s.strip() for s in re.split(r"(?<=[\.!\?])\s+", t) if str(s).strip()]
        first = sentences[0] if sentences else ""
        last = sentences[-1] if sentences else ""

        if first and len(first) >= 28:
            score += 1

        transition_score = _scene_transition_score(t)
        if transition_score >= 2:
            score += 2
        elif transition_score == 1:
            score += 1

        if last and len(last) >= 28:
            score += 1

        if str(operational_reference or "").strip():
            score += 1
        if str(reference_example or "").strip():
            score += 1
        if str(effective_segment or "").strip():
            score += 1
        if str(operational_family or "").strip():
            score += 1

        return score
    except Exception:
        return 0


def _operational_progress_score(
    *,
    text: str,
    operational_reference: str,
    contract: Dict[str, Any] | None = None,
) -> int:
    """
    Mede se a resposta tem progressão de cena operacional.

    Não usa palavras-chave fixas.
    Observa:
    - quantidade de frases úteis
    - presença de sequência/encadeamento
    - aderência mínima ao ritual do banco
    """
    try:
        t = str(text or "").strip()
        if not t:
            return 0

        score = 0
        sentences = [s.strip() for s in _split_sentences_pt(t) if str(s).strip()]
        if len(sentences) >= 3:
            score += 2
        elif len(sentences) == 2:
            score += 1

        low = t.lower()

        transition_score = _scene_transition_score(t)
        if transition_score >= 3:
            score += 2
        elif transition_score >= 1:
            score += 1

        ritual_steps = []
        c = contract or {}
        raw_ritual = c.get("operational_ritual") or []
        if isinstance(raw_ritual, list):
            ritual_steps = [str(x).strip().lower() for x in raw_ritual if str(x).strip()]

        if ritual_steps:
            overlap = 0
            for step in ritual_steps:
                step_tokens = [tok for tok in re.findall(r"\w+", step) if len(tok) >= 4]
                if not step_tokens:
                    continue
                hit_count = sum(1 for tok in step_tokens if tok in low)
                if hit_count >= max(1, min(2, len(step_tokens))):
                    overlap += 1
            if overlap >= 3:
                score += 3
            elif overlap == 2:
                score += 2
            elif overlap == 1:
                score += 1
        else:
            scene = str(operational_reference or "").strip().lower()
            if scene:
                scene_tokens = [tok for tok in re.findall(r"\w+", scene) if len(tok) >= 5]
                hit_count = sum(1 for tok in scene_tokens[:8] if tok in low)
                if hit_count >= 3:
                    score += 1

        return score
    except Exception:
        return 0


def _observer_voice_score(text: str) -> int:
    """
    Mede se o texto soa como observação externa da operação,
    sem depender de sujeitos fixos ou frases proibidas.

    Sinais:
    - frases sucessivas com aberturas muito parecidas
    - sobreposição excessiva entre frases adjacentes
    - pouca introdução de novos tokens
    """
    try:
        t = str(text or "").strip()
        if not t:
            return 0

        sentences = [s.strip() for s in _split_sentences_pt(t) if str(s).strip()]
        if len(sentences) < 2:
            return 0

        tokenized = []
        openings = []
        for s in sentences:
            toks = [tok for tok in re.findall(r"\w+", s.lower()) if len(tok) >= 3]
            tokenized.append(toks)
            openings.append(" ".join(toks[:2]) if toks else "")

        score = 0

        repeated_openings = len(openings) - len({o for o in openings if o})
        if repeated_openings >= 2:
            score += 1
        if repeated_openings >= 3:
            score += 1

        heavy_overlap_pairs = 0
        for i in range(len(tokenized) - 1):
            a = set(tokenized[i])
            b = set(tokenized[i + 1])
            if not a or not b:
                continue
            inter = len(a.intersection(b))
            union = len(a.union(b)) or 1
            ratio = inter / union
            if ratio > 0.45:
                heavy_overlap_pairs += 1

        if heavy_overlap_pairs >= 1:
            score += 1
        if heavy_overlap_pairs >= 2:
            score += 1

        all_tokens = [tok for toks in tokenized for tok in toks]
        uniq = len(set(all_tokens))
        total = len(all_tokens) or 1
        novelty_ratio = uniq / total

        if novelty_ratio < 0.48:
            score += 1

        return score
    except Exception:
        return 0


def _looks_explanatory_reply(
    *,
    text: str,
    operational_reference: str,
    reference_example: str,
    contract: Dict[str, Any] | None = None,
) -> bool:
    """
    Detecta só quando o texto realmente virou explicação genérica.
    Não barra microcena apenas porque está menos densa.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return True

        if len(t) < 60:
            return False

        sentences = [s.strip() for s in _split_sentences_pt(t) if str(s).strip()]
        if len(sentences) < 2:
            return True

        grounded_scene = str(
            operational_reference
            or (contract or {}).get("operational_reference")
            or ""
        ).strip()

        if not grounded_scene:
            return False

        contract_strong = bool(
            (contract or {}).get("hydrated_from_docs")
            and str(reference_example or "").strip()
            and grounded_scene
        )

        transition = _scene_transition_score(t)
        density = _operational_density_score(
            text=t,
            operational_reference=grounded_scene,
            reference_example=reference_example,
            effective_segment=str((contract or {}).get("segment") or "").strip(),
            operational_family=str((contract or {}).get("operational_family") or "").strip(),
        )
        progress = _operational_progress_score(
            text=t,
            operational_reference=grounded_scene,
            contract=contract or {},
        )
        observer_voice = _observer_voice_score(t)

        if transition == 0 and density < 2:
            return True

        if contract_strong:
            if transition <= 1 and progress <= 1:
                return True
            if density <= 3 and progress <= 1:
                return True
            if observer_voice >= 3 and transition <= 1:
                return True

        return False
    except Exception:
        return False


def _is_live_operational_reply(
    *,
    text: str,
    operational_reference: str,
    reference_example: str,
    contract: Dict[str, Any] | None = None,
) -> bool:
    """
    Validação mínima.
    Só barra resposta claramente ruim.
    Não tenta mais medir perfeição estilística.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return False

        if len(t) < 40:
            return False

        if _looks_like_technical_output(t):
            return False

        if _looks_like_dialogue_stub(t):
            return False

        if not _has_operational_shape(t):
            return False

        sentences = [s.strip() for s in _split_sentences_pt(t) if str(s).strip()]
        if len(sentences) >= 4:
            short_count = sum(1 for s in sentences if len(re.findall(r"\w+", s)) <= 4)
            if short_count >= len(sentences):
                return False

        return True
    except Exception:
        return False


def _is_show_micro_scene(
    *,
    text: str,
    operational_reference: str,
    reference_example: str,
    contract: Dict[str, Any] | None = None,
) -> bool:
    """
    Régua estrutural de SHOW.
    Não usa palavras-chave, nem frases prontas, nem listas de efeitos.
    Mede encadeamento, progressão, densidade operacional e fechamento suficiente.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return False

        grounded_scene = str(
            operational_reference
            or (contract or {}).get("operational_reference")
            or ""
        ).strip()

        contract_strong = bool(
            (contract or {}).get("hydrated_from_docs")
            and str(reference_example or "").strip()
            and grounded_scene
        )

        if not _is_live_operational_reply(
            text=t,
            operational_reference=grounded_scene,
            reference_example=reference_example,
            contract=contract or {},
        ):
            return False

        if _looks_like_dialogue_stub(t):
            return False

        sentences = [s.strip() for s in _split_sentences_pt(t) if str(s).strip()]
        if len(sentences) < 3:
            return False

        if len(t) < 140:
            return False

        transition = _scene_transition_score(t)
        density = _operational_density_score(
            text=t,
            operational_reference=grounded_scene,
            reference_example=reference_example,
            effective_segment=str((contract or {}).get("segment") or "").strip(),
            operational_family=str((contract or {}).get("operational_family") or "").strip(),
        )
        progress = _operational_progress_score(
            text=t,
            operational_reference=grounded_scene,
            contract=contract or {},
        )
        observer_voice = _observer_voice_score(t)
        explanatory = _looks_explanatory_reply(
            text=t,
            operational_reference=grounded_scene,
            reference_example=reference_example,
            contract=contract or {},
        )

        if transition < 2:
            return False

        if progress < 2:
            return False

        if density < 3:
            return False

        if contract_strong:
            if explanatory:
                return False
            if progress < 3:
                return False
            if observer_voice >= 3:
                return False

        last = sentences[-1]
        if len(re.findall(r"\w+", last)) < 6:
            return False

        return True
    except Exception:
        return False


def _should_force_kb_rebuild(
    *,
    text: str,
    kb_anchor_strong: bool,
    operational_reference: str,
    reference_example: str,
    effective_segment: str,
    operational_family: str,
    contract: Dict[str, Any] | None = None,
) -> bool:
    """
    Só força rebuild quando a resposta realmente colapsou.
    Não deve rebaixar texto vivo só porque saiu menos formatado.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return True

        if _looks_like_technical_output(t):
            return True

        if _looks_like_dialogue_stub(t):
            return True

        if len(t) < 40:
            return True

        if not _has_operational_shape(t):
            return True

        if _looks_explanatory_reply(
            text=t,
            operational_reference="",
            reference_example=reference_example,
            contract=contract or {},
        ):
            return True

        return False
    except Exception:
        return True


def _audit_operational_reply(
    *,
    text: str,
    contract: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Audita se a resposta respeita o trilho operacional do banco.
    Sem depender de frases prontas.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return {"ok": False, "reason": "empty"}

        low = t.lower()
        allowed_next_step = str((contract or {}).get("allowed_next_step") or "none").strip().lower()
        archetype_id = str((contract or {}).get("archetype_id") or "").strip().lower()
        topic = str((contract or {}).get("topic") or "").strip().upper()
        has_scene = bool((contract or {}).get("has_practical_scene"))

        # estrutura mínima: só barra colapso real
        if _looks_like_dialogue_stub(t):
            return {"ok": False, "reason": "dialogue_stub"}

        if not _has_operational_shape(t):
            return {"ok": False, "reason": "weak_shape"}

        practical_scene = str((contract or {}).get("operational_reference") or "").strip()
        reference_example = str((contract or {}).get("reference_example") or "").strip()

        if not _is_live_operational_reply(
            text=t,
            operational_reference="",
            reference_example=reference_example,
            contract=contract or {},
        ):
            return {"ok": False, "reason": "non_live_operational_form"}

        # deriva operacional:
        # visita técnica não deve escorregar para agenda completa
        if allowed_next_step == "visita":
            if (
                "agendar" in low
                or "agendada" in low
                or "horário" in low
                or "horario" in low
                or "data e horário" in low
                or "data e horario" in low
            ):
                return {"ok": False, "reason": "drifted_to_schedule"}

        # comércio consultivo presencial não deve virar agenda formal
        if allowed_next_step == "visita_loja" and archetype_id == "comercio_consultivo_presencial":
            if (
                "agendar" in low
                or "agendada" in low
                or "data e horário" in low
                or "data e horario" in low
                or "horário" in low
                or "horario" in low
            ):
                return {"ok": False, "reason": "invented_store_schedule"}

        # catálogo direto não deve virar fluxo genérico demais
        if allowed_next_step == "reserva_ou_compra" and topic not in ("PRODUTO", "PRECO", "SERVICOS"):
            return {"ok": False, "reason": "wrong_topic_for_catalog"}

        return {"ok": True, "reason": "ok"}
    except Exception:
        return {"ok": False, "reason": "audit_error"}


def _looks_like_bureaucratic_stub(text: str) -> bool:
    try:
        t = str(text or "").strip().lower()
        if not t:
            return True
        if t in ("dentro do sla informado.", "até 7 dias úteis.", "ate 7 dias uteis."):
            return True
        if len(t) < 40 and ("sla" in t or "dias úteis" in t or "dias uteis" in t):
            return True
        return False
    except Exception:
        return False


def _reply_mentions_name_request(text: str) -> bool:
    try:
        t = str(text or "").strip().lower()
        if not t:
            return False
        return bool(
            re.search(r"\b(nome|teu nome|seu nome|como tu te chama|como você se chama)\b", t)
        )
    except Exception:
        return False


def _front_identity_request_is_valid(text: str) -> bool:
    """
    Valida se uma pergunta/solicitação é realmente de identidade.
    Não valida profissão, segmento específico ou palavras de negócio.
    Apenas exige que o texto peça nome de forma estrutural.
    """
    try:
        return _reply_mentions_name_request(text)
    except Exception:
        return False


def _front_has_identity_request_tail(text: str, identity_question: str = "") -> bool:
    """
    Verifica se o texto já termina com uma solicitação de identidade.

    Importante:
    - não basta o texto mencionar "nome" dentro de uma explicação técnica;
    - "o robô pergunta o nome..." não é pedido de nome ao lead;
    - a validação precisa olhar a cauda do texto, onde ficam pedidos reais.

    Não usa lista de segmentos/profissões.
    Não altera prompt.
    Não chama modelo.
    """
    try:
        s = str(text or "").strip()
        if not s:
            return False

        tail = s[-180:].strip()
        norm_tail = _front_normalize_identity_text(tail)

        q = str(identity_question or "").strip()
        if q:
            norm_q = _front_normalize_identity_text(q)
            # Quando já temos a pergunta de identidade calculada, só aceitamos
            # como "pedido já presente" se a cauda terminar exatamente nela.
            # Isso evita confundir explicações como "o robô pergunta o nome"
            # com um pedido real de nome ao lead.
            return bool(norm_q and norm_tail.endswith(norm_q))

        return _front_identity_request_is_valid(tail)
    except Exception:
        return False

