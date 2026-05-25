# services/front_assembly.py
# Fase 4A — Montagem, limpeza e humanização determinística de texto.
#
# Regras:
# - Não chama LLM.
# - Não acessa Firestore.
# - Não altera prompts.
# - Apenas manipula strings, limpa ruídos e encadeia cenas.

from __future__ import annotations

import re
from typing import Any, Dict

from services.front_utils import (
    normalize_identity_text as _front_normalize_identity_text,
    split_sentences_pt as _split_sentences_pt,
    looks_like_technical_output as _looks_like_technical_output,
)
from services.front_guards import _looks_explanatory_sentence

def _front_remove_unsafe_nominal_opening(text: str, has_name: bool) -> str:
    """
    Guarda estrutural final para saudação nominal.
    Se o sistema não tem nome confirmado, remove apenas vocativo curto
    inserido na abertura.

    Não usa palavra-chave de profissão/segmento.
    Não altera prompt.
    Não chama modelo.
    """
    try:
        s = str(text or "").strip()
        if not s or has_name:
            return s

        first_line, sep, rest = s.partition("\n")
        head = first_line.strip()

        # Estrutura típica de abertura nominal curta:
        # "X, Y! ..." ou "X, Y. ..."
        # A regra não interpreta profissão/segmento; apenas impede vocativo
        # curto quando o próprio estado diz que não há nome.
        m = re.match(r"^([^,\n!?\.]{1,24}),\s*([^,\n!?\.]{1,32})([!?\.])(\s*)(.*)$", head)
        if not m:
            return s

        opener = str(m.group(1) or "").strip()
        vocative = str(m.group(2) or "").strip()
        punct = str(m.group(3) or "").strip()
        tail = str(m.group(5) or "").strip()

        if not opener or not vocative:
            return s

        safe_head = f"{opener}{punct}"
        if tail:
            safe_head = f"{safe_head} {tail}".strip()

        if sep:
            return f"{safe_head}\n{rest}".strip()
        return safe_head.strip()

    except Exception:
        return str(text or "").strip()


def _reply_has_lead_context(reply: str, lead_name: str = "", lead_segment_raw: str = "") -> bool:
    """
    Valida se a resposta final carregou os sinais humanos mínimos.
    Não valida frase pronta; valida presença estrutural de nome e atividade.
    """
    try:
        text = str(reply or "").lower()
        name = str(lead_name or "").strip().lower()
        seg = str(lead_segment_raw or "").strip().lower()

        if name and name not in text:
            return False

        if seg and seg not in text:
            return False

        return bool(name or seg)
    except Exception:
        return False


def _front_sanitize_lead_name_candidate(value: Any, segment_refs: list | None = None) -> str:
    """
    Guarda estrutural para nome do lead.
    Não usa palavras-chave de profissão/segmento.
    Apenas rejeita textos que coincidam estruturalmente com atividade,
    segmento ou descrição operacional já conhecida no contexto.
    """
    try:
        s = str(value or "").strip()
        if not s:
            return ""

        if len(s) > 32:
            return ""

        tokens = [t for t in s.replace("\n", " ").split(" ") if t.strip()]
        if len(tokens) > 3:
            return ""

        if not any(ch.isalpha() for ch in s):
            return ""

        if any(ch.isdigit() for ch in s):
            return ""

        cand_norm = _front_normalize_identity_text(s)
        cand_tokens = set(cand_norm.split())
        if not cand_norm or not cand_tokens:
            return ""

        for ref in (segment_refs or []):
            ref_norm = _front_normalize_identity_text(ref)
            ref_tokens = set(ref_norm.split())
            if not ref_norm or not ref_tokens:
                continue
            if cand_norm == ref_norm:
                return ""
            if cand_tokens and cand_tokens.issubset(ref_tokens):
                return ""

        return s
    except Exception:
        return ""


def _front_first_text(*vals: Any) -> str:
    """
    Retorna o primeiro texto útil.
    Helper estrutural: não decide intenção, não detecta segmento e não cria conteúdo comercial.
    """
    try:
        for v in vals:
            if isinstance(v, str):
                s = v.strip()
                if s:
                    return s
        return ""
    except Exception:
        return ""


def _humanize_scene_flow(text: str) -> str:
    """
    Humaniza a microcena quando ela vier serializada em trilho
    (ex.: 'cliente faz X → robô faz Y → cliente avança → robô conduz').
    Não inventa conteúdo; só transforma a sequência em frase mais falada.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return ""

        parts = [p.strip(" .;:-") for p in re.split(r"\s*(?:→|->|=>|\|)\s*", t) if str(p).strip()]
        if len(parts) <= 1:
            return t.rstrip(". ")

        normalized = []
        for i, part in enumerate(parts):
            p = re.sub(r"\s{2,}", " ", str(part or "").strip())
            if not p:
                continue
            if i > 0:
                p = p[:1].lower() + p[1:] if len(p) > 1 else p.lower()
            normalized.append(p)

        if not normalized:
            return t.rstrip(". ")

        if len(normalized) == 2:
            out = normalized[0] + " e " + normalized[1]
        else:
            out = ", ".join(normalized[:-1]) + " e " + normalized[-1]

        out = re.sub(r"\s{2,}", " ", out).strip(" .")
        return out
    except Exception:
        return str(text or "").strip().rstrip(". ")


def _looks_like_structural_scene_payload(text: str) -> bool:
    """
    Detecta saída operacional ainda crua.
    Escopo restrito: usado apenas em response_mode SCENE / retornos operacionais.
    """
    try:
        t = re.sub(r"\s{2,}", " ", str(text or "").strip())
        if not t:
            return False

        if re.search(r"\s(?:→|->|=>|\|)\s", t):
            return True

        if re.search(r"\s\+\s", t):
            return True

        clauses = [p.strip() for p in re.split(r"\s*,\s*", t) if p.strip()]
        if len(clauses) >= 4:
            short_clauses = sum(1 for p in clauses if len(p.split()) <= 7)
            if short_clauses >= 3:
                return True

        return False
    except Exception:
        return False


def _derive_ritual_from_scene(text: str) -> list[str]:
    """
    Deriva passos estruturais a partir de uma microcena serializada.
    Não inventa conteúdo; apenas transforma a cena em steps reutilizáveis.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return []

        parts = [p.strip(" .;:-") for p in re.split(r"\s*(?:→|->|=>|\|)\s*", t) if str(p).strip()]
        if len(parts) <= 1:
            return []

        steps = []
        for p in parts:
            s = re.sub(r"\s{2,}", " ", str(p or "").strip())
            if s:
                steps.append(s)
        return steps[:6]
    except Exception:
        return []


def _stabilize_scene_base(text: str) -> str:
    """
    Normaliza uma cena-base operacional sem inventar conteúdo novo.
    Prioriza manter a sequência e limpar serialização ruim.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return ""

        t = re.sub(r"(?i)^\s*na prática:\s*", "", t).strip()
        t = re.sub(r"\s*(?:\-\>|\=\>|\|)\s*", " → ", t)
        t = re.sub(r"\s{2,}", " ", t).strip(" .")

        steps = _derive_ritual_from_scene(t)
        if steps:
            cleaned_steps = [re.sub(r"\s{2,}", " ", str(s or "").strip(" .")) for s in steps if str(s).strip()]
            return " → ".join(cleaned_steps).strip(" .")

        return t
    except Exception:
        return str(text or "").strip()


def _split_scene_steps(text: str) -> list[str]:
    try:
        t = str(text or "").strip()
        if not t:
            return []
        parts = [p.strip(" .;:-") for p in re.split(r"\s*(?:→|->|=>|\|)\s*", t) if str(p).strip()]
        if parts:
            return [re.sub(r"\s{2,}", " ", p).strip() for p in parts if str(p).strip()]
        sentences = [s.strip(" .;:-") for s in _split_sentences_pt(t) if str(s).strip()]
        return [re.sub(r"\s{2,}", " ", s).strip() for s in sentences if str(s).strip()]
    except Exception:
        return []


def _normalize_scene_compare(text: str) -> str:
    try:
        s = str(text or "").strip().lower()
        if not s:
            return ""
        s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
        s = re.sub(r"\s{2,}", " ", s).strip()
        return s
    except Exception:
        return str(text or "").strip().lower()


def _is_scene_echo(text: str, reference: str) -> bool:
    """
    Detecta quando a 'cena' é praticamente o mesmo conteúdo do relato/exemplo.
    """
    try:
        a = _normalize_scene_compare(text)
        b = _normalize_scene_compare(reference)
        if not a or not b:
            return False
        if a == b:
            return True
        if len(a) >= 24 and len(b) >= 24:
            if a in b or b in a:
                return True
        return False
    except Exception:
        return False


def _strip_scene_narrator(text: str) -> str:
    """
    Limpeza mínima de superfície.
    Não tenta decidir forma viva por lista de sujeitos.
    """
    try:
        s = str(text or "").strip()
        if not s:
            return ""
        s = re.sub(r"\s{2,}", " ", s).strip(" .")
        return s
    except Exception:
        return str(text or "").strip()


def _humanize_ritual_flow(ritual_steps: list[str]) -> str:
    """
    Transforma etapas em fluxo operacional corrido.
    Não inventa fatos; só reorganiza os passos já existentes.
    """
    try:
        cleaned = []
        seen = set()

        for raw in ritual_steps:
            s = _strip_scene_narrator(str(raw or "").strip().rstrip("."))
            s = re.sub(r"\s{2,}", " ", s).strip(" .")
            if not s:
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(s)

        if not cleaned:
            return ""

        if len(cleaned) == 1:
            one = cleaned[0]
            return one[:1].upper() + one[1:] + "." if len(one) > 1 else one.upper() + "."

        first = cleaned[0]
        first = first[:1].upper() + first[1:] if len(first) > 1 else first.upper()

        tail = []
        for step in cleaned[1:]:
            s = step[:1].lower() + step[1:] if len(step) > 1 else step.lower()
            tail.append(s)

        if len(tail) == 1:
            out = f"{first}, {tail[0]}"
        elif len(tail) == 2:
            out = f"{first}, {tail[0]} e {tail[1]}"
        else:
            out = f"{first}, " + ", ".join(tail[:-1]) + " e " + tail[-1]

        out = re.sub(r"\s{2,}", " ", out).strip(" .")
        return out + "."
    except Exception:
        return ""


def _render_structured_operational_steps(steps: list[str]) -> str:
    """
    Monta microcena a partir de passos estruturais.
    Não inventa fatos; só encadeia o que já veio da base/modelo.
    """
    try:
        cleaned = []
        seen = set()

        for raw in steps:
            s = re.sub(r"\s{2,}", " ", str(raw or "").strip(" .,:;-"))
            if not s:
                continue

            key = re.sub(r"\W+", "", s).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(s)

        if len(cleaned) < 2:
            return ""

        normalized = []
        for i, s in enumerate(cleaned[:5]):
            piece = s[:1].upper() + s[1:] if i == 0 and len(s) > 1 else (
                s.upper() if i == 0 else (s[:1].lower() + s[1:] if len(s) > 1 else s.lower())
            )
            normalized.append(piece)

        out = normalized[0]
        for piece in normalized[1:]:
            out = f"{out}, {piece}"

        out = _sanitize_user_facing_reply(out)
        out = re.sub(r"\s{2,}", " ", out).strip(" .")

        return out + "." if out else ""
    except Exception:
        return ""


def _render_progressive_operational_flow(steps: list[str]) -> str:
    """
    Render estrutural e direto.
    Sem IA, sem narrador e sem embelezamento.
    """
    try:
        cleaned = []
        seen = set()

        for raw in steps:
            s = re.sub(r"\s{2,}", " ", str(raw or "").strip(" .,:;-"))
            if not s:
                continue
            key = re.sub(r"\W+", "", s).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(s)

        if len(cleaned) < 3:
            return ""

        first = cleaned[0][:1].upper() + cleaned[0][1:] if len(cleaned[0]) > 1 else cleaned[0].upper()
        tail = []
        seen_roots = set()

        for s in cleaned[1:6]:
            root = re.sub(r"\W+", "", s.lower())[:25]

            if root in seen_roots:
                continue

            seen_roots.add(root)

            piece = s[:1].lower() + s[1:] if len(s) > 1 else s.lower()
            tail.append(piece)

        out = first

        for piece in tail:
            if not out.endswith("."):
                out += "."
            out += " " + piece

        # melhora encadeamento mínimo
        out = re.sub(r"\s{2,}", " ", out).strip(" .")

        return out + "."
    except Exception:
        return ""


def _heal_algorithmic_micro_scene(text: str) -> str:
    """
    Ajuste leve de texto.
    Preserva todo o conteúdo e apenas organiza a forma.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return ""

        t = re.sub(
            r"^(Aqui está|Exemplo:|Cena:|Na prática:|Veja como funciona:)\s*",
            "",
            t,
            flags=re.IGNORECASE
        ).strip()

        t = re.sub(r"\s{2,}", " ", t).strip()

        if t and not t.endswith((".", "!", "?")):
            t += "."

        return t
    except Exception:
        return str(text or "").strip()


def _sanitize_user_facing_reply(text: str) -> str:
    """
    Limpeza final antes de devolver ao usuário.
    Remove vazamento técnico, normaliza duplicações simples
    e faz higiene textual mínima sem reescrever conteúdo.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return ""

        # remove pack id no começo ou no meio
        t = re.sub(r"^\s*PACK_[A-Z_]+\s*[\.\:\-–—]?\s*", "", t, flags=re.I).strip()
        t = re.sub(r"\s+PACK_[A-Z_]+\s*[\.\:\-–—]?\s*", " ", t, flags=re.I).strip()

        # remove blocos técnicos conhecidos
        t = re.sub(r"\b(segment_value_map_v1|value_packs_v1|runtime_short)\b", "", t, flags=re.I)

        # normaliza duplicação de Na prática
        t = re.sub(r"(?i)\bna prática:\s*na prática:\s*", "Na prática: ", t).strip()

        # limpa pontuação/spacing quebrado
        t = re.sub(r"\s{2,}", " ", t).strip()
        t = re.sub(r"\.\s*\.", ".", t).strip()
        t = re.sub(r"\bo contrato será considerado encerrado\b", "", t, flags=re.I).strip()
        t = re.sub(r"\bcontrato\b", "", t, flags=re.I).strip()
        t = re.sub(r"\s{2,}", " ", t).strip(" \n.,;:-")
        return t
    except Exception:
        return str(text or "").strip()


def _compose_operational_reply(
    *,
    reply_text: str,
    operational_reference: str,
    reference_example: str,
    operational_family: str,
    contract: Dict[str, Any] | None = None,
) -> str:
    """
    Preserva a resposta da IA como principal.
    O front só limpa ruído mínimo sem recompor a resposta.
    """
    try:
        rt = _sanitize_user_facing_reply(reply_text)

        if not rt:
            return ""

        if _looks_like_technical_output(rt):
            return _sanitize_user_facing_reply(rt)

        return rt
    except Exception:
        return _sanitize_user_facing_reply(reply_text)


def wrap_show_response(text: str) -> str:
    """
    Organiza resposta da IA em narrativa prática
    sem alterar o conteúdo gerado.
    """
    try:
        text = _sanitize_user_facing_reply(text)
        return str(text or "").strip()
    except Exception:
        return str(text or "").strip()


def _replace_last_question(text: str, new_question: str) -> str:
    try:
        t = str(text or "").strip()
        nq = str(new_question or "").strip()
        if not t:
            return nq
        if not nq:
            return t
        qpos = t.rfind("?")
        if qpos == -1:
            if not t.endswith((".", "!", ":")):
                t += "."
            return (t + " " + nq).strip()
        prefix = t[:qpos + 1].strip()
        prefix = re.sub(r"[^\s?!\.]+\?$", "", prefix).strip()
        if prefix and not prefix.endswith(("?", ".", "!")):
            prefix += "."
        return ((prefix + " " + nq).strip() if prefix else nq).strip()
    except Exception:
        return str(text or "").strip()


def _drop_explanatory_opening(text: str) -> str:
    """
    Remove a abertura genérica se ela vier com cara de explicação.
    Mantém o restante intacto.
    """
    try:
        sentences = _split_sentences_pt(text)
        if not sentences:
            return str(text or "").strip()
        if _looks_explanatory_sentence(sentences[0]):
            return " ".join(sentences[1:]).strip()
        return str(text or "").strip()
    except Exception:
        return str(text or "").strip()


def _drop_abstract_closing(text: str) -> str:
    """
    Remove fechamento abstrato quando ele não traz consequência concreta.
    """
    try:
        sentences = _split_sentences_pt(text)
        if len(sentences) < 2:
            return str(text or "").strip()
        last = sentences[-1]
        if _looks_explanatory_sentence(last):
            return " ".join(sentences[:-1]).strip()
        return str(text or "").strip()
    except Exception:
        return str(text or "").strip()


def _front_finalize_reply_surface(
    text: str,
    *,
    has_name: bool = True,
    max_chars: int | None = None,
    ensure_punctuation: bool = True,
) -> str:
    """
    Orquestra limpeza final de superfície para uma resposta ao usuário.

    Não decide intenção.
    Não acessa KB.
    Não chama LLM.
    Não altera prompt.
    Apenas centraliza saneamento textual já existente.
    """
    try:
        out = _sanitize_user_facing_reply(text)
        out = _front_remove_unsafe_nominal_opening(out, has_name=has_name)

        if max_chars and max_chars > 0:
            out = _front_trim_to_complete_sentence(out, int(max_chars))

        if ensure_punctuation and out and out[-1] not in ".!?":
            out = out.rstrip() + "."

        return out
    except Exception:
        return str(text or "").strip()
