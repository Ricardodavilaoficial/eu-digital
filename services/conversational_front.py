# services/conversational_front.py
# Conversational Front v1.0 — MEI Robô
#
# Papel:
# - Intérprete inicial de conversa (vendedor humano)
# - Até MAX_AI_TURNS (hard cap decidido fora)
# - IA entende, responde e devolve metadados simples
#
# Regras:
# - NÃO grava Firestore
# - NÃO chama rotas de envio
# - NÃO gera áudio
# - NÃO executa ações
#
# Saída SEMPRE compatível com o worker
#
# 2026-02

from __future__ import annotations

import logging
from typing import Dict, Any
import json
import re
try:
    from services.pack_engine import render_pack_reply  # type: ignore
except Exception:
    render_pack_reply = None  # type: ignore

import os

# Robustez: resolver de KB (seleciona fatos do Firestore/KB sem entupir tokens)
try:
    from services.kb_resolver import build_kb_context  # type: ignore
except Exception:
    build_kb_context = None  # type: ignore

# Guardrails finais de VENDAS (anti-invenção + CTA forte)
try:
    from services.sales_guardrails import apply_sales_guardrails  # type: ignore
except Exception:
    apply_sales_guardrails = None  # type: ignore
try:
    # SDK novo (openai>=1.x)
    from openai import OpenAI  # type: ignore
    _HAS_OPENAI_CLIENT = True
except Exception:
    OpenAI = None  # type: ignore
    _HAS_OPENAI_CLIENT = False
import openai  # compat SDK antigo

# -----------------------------
# Configuração fixa (produto)
# -----------------------------
MODEL = "gpt-4o-mini"
TEMPERATURE = 0.35
FRONT_ANSWER_MAX_TOKENS = int(os.getenv("FRONT_ANSWER_MAX_TOKENS", "350") or 350)  # saída do modelo (econômico, focado em 1 parágrafo)
FRONT_KB_MAX_CHARS = int(os.getenv("FRONT_KB_MAX_CHARS", "2500") or 2500)          # entrada (snapshot)
FRONT_KB_MAX_CHARS_PACKS_V1 = int(
    os.getenv("FRONT_KB_MAX_CHARS_PACKS_V1", "12000") or 12000
)
FRONT_REPLY_MAX_CHARS = int(os.getenv("FRONT_REPLY_MAX_CHARS", "1500") or 1500)      # corte final aumentado para permitir microcenas SHOW
FRONT_FREE_MODE_MAX_TURNS = int(os.getenv("FRONT_FREE_MODE_MAX_TURNS", "5") or 5)
FRONT_TRACE_ENABLED = (os.getenv("FRONT_TRACE_ENABLED", "1") or "1").strip().lower() in ("1", "true", "yes", "on")

# Feature flag (default ON, mas seguro): seleciona fatos do KB para o prompt (menos alucinação, menos tokens)
FRONT_KB_RESOLVER_ENABLED = (os.getenv("FRONT_KB_RESOLVER_ENABLED", "1") or "1").strip().lower() not in ("0","false","off","no")


_client = OpenAI() if _HAS_OPENAI_CLIENT else None
# -----------------------------
# Enum fechado de tópicos
# -----------------------------
TOPICS = {
    "AGENDA",
    "PRECO",
    "ORCAMENTO",
    "PRODUTO",
    "SERVICOS",
    "PEDIDOS",
    "STATUS",
    "PROCESSO",
    "ATIVAR",
    "WHAT_IS",
    "VOZ",
    "SOCIAL",
    "TRIAL",
    "OTHER",
}

# -----------------------------
# Funções Utilitárias de Texto
# -----------------------------

def _split_sentences_pt(text: str) -> list[str]:
    try:
        t = str(text or "").strip()
        if not t:
            return []
        parts = re.split(r'(?<=[.!?])\s+', t)
        return [p.strip() for p in parts if p.strip()]
    except Exception:
        return [str(text or "").strip()]

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

# -----------------------------
# Prompt base (alma do vendedor)
# -----------------------------

def _infer_segment_from_text(user_text: str, kb_snapshot: str) -> str:
    """Infer a segment from explicit user text, preferring KB-known segment keys."""
    try:
        t = str(user_text or "").strip().lower()
        if not t:
            return ""

        def _norm(s: str) -> str:
            # Normalização agnóstica: apenas remove acentos e caracteres especiais
            return _normalize_lookup_key(s)

        norm = _norm(t)

        candidates = []
        sub_candidates = []
        try:
            obj = json.loads(kb_snapshot) if kb_snapshot and kb_snapshot.lstrip().startswith(("{", "[")) else None
        except Exception:
            obj = None

        if isinstance(obj, dict):
            kb_segments = obj.get("kb_segments_v1") or {}
            if isinstance(kb_segments, dict):
                candidates.extend([str(k).strip().lower() for k in kb_segments.keys() if str(k).strip()])

            kb_subsegments = obj.get("kb_subsegments_v1") or {}
            if isinstance(kb_subsegments, dict):
                sub_candidates = [str(k).strip().lower() for k in kb_subsegments.keys() if str(k).strip()]

            svm = obj.get("segment_value_map_v1") or {}
            if isinstance(svm, dict):
                candidates.extend([str(k).strip().lower() for k in svm.keys() if str(k).strip()])

        for sub in sub_candidates:
            s = _norm(sub.replace("__", " "))
            if s and s in norm:
                return sub

        for seg in candidates:
            s = _norm(seg)
            if s and s in norm:
                return s

        # fallback semântico mínimo para papéis claros
        _txt = (user_text or "").lower()
        if "candidat" in _txt:
            return "politica_atendimento_publico"

        # fallback estrutural por conteúdo real do KB
        try:
            if isinstance(obj, dict):
                kb_subsegments = obj.get("kb_subsegments_v1") or {}
                if isinstance(kb_subsegments, dict) and kb_subsegments:
                    best_sub = _best_doc_match(norm, kb_subsegments, min_score=2)
                    if best_sub:
                        return str(best_sub).strip().lower()

                kb_segments = obj.get("kb_segments_v1") or {}
                if isinstance(kb_segments, dict) and kb_segments:
                    best_seg = _best_doc_match(norm, kb_segments, min_score=2)
                    if best_seg:
                        return str(best_seg).strip().lower()
        except Exception:
            pass

        # fallback final por overlap de chave
        all_candidates = []
        try:
            all_candidates.extend([str(x).strip() for x in sub_candidates if str(x).strip()])
            all_candidates.extend([str(x).strip() for x in candidates if str(x).strip()])
        except Exception:
            all_candidates = []

        best = _best_lookup_key_match(norm, all_candidates, min_score=2)
        if best:
            return str(best).strip().lower()
        return ""
    except Exception:
        return ""


def _infer_operational_family(user_text: str, raw_profession: str = "") -> str:
    """
    Mantido só por compatibilidade.
    A família operacional deve nascer do KB resolvido, não de listas locais.
    """
    return ""

def _normalize_lookup_key(text: str) -> str:
    try:
        s = str(text or "").strip().lower()
        if not s:
            return ""
        repl = {
            "á": "a", "à": "a", "â": "a", "ã": "a",
            "é": "e", "ê": "e",
            "í": "i",
            "ó": "o", "ô": "o", "õ": "o",
            "ú": "u",
            "ç": "c",
        }
        for a, b in repl.items():
            s = s.replace(a, b)
        s = s.replace("-", "_").replace("/", " ").replace(".", " ")
        s = re.sub(r"\s+", " ", s).strip()
        return s
    except Exception:
        return str(text or "").strip().lower()


def _tokenize_lookup_text(text: str) -> list[str]:
    try:
        s = _normalize_lookup_key(text)
        toks = [tok for tok in re.findall(r"[a-z0-9_]+", s) if len(tok) >= 3]
        return toks
    except Exception:
        return []


def _lookup_token_overlap_score(query: str, candidate: str) -> int:
    try:
        q_tokens = set(_tokenize_lookup_text(query))
        c_tokens = set(_tokenize_lookup_text(candidate.replace("__", " ")))
        if not q_tokens or not c_tokens:
            return 0
        overlap = q_tokens.intersection(c_tokens)
        score = len(overlap)

        q_norm = _normalize_lookup_key(query)
        c_norm = _normalize_lookup_key(candidate.replace("__", " "))
        if c_norm and c_norm in q_norm:
            score += 2
        elif q_norm and q_norm in c_norm:
            score += 1

        return score
    except Exception:
        return 0


def _best_lookup_key_match(query: str, candidates: list[str], min_score: int = 2) -> str:
    try:
        q = str(query or "").strip()
        if not q or not candidates:
            return ""

        best_key = ""
        best_score = 0

        for cand in candidates:
            c = str(cand or "").strip()
            if not c:
                continue
            score = _lookup_token_overlap_score(q, c)
            if score > best_score:
                best_score = score
                best_key = c

        return best_key if best_score >= min_score else ""
    except Exception:
        return ""


def _iter_doc_text_fragments(value):
    """
    Extrai fragmentos textuais de forma recursiva.
    Não depende de segmento, profissão ou frase pronta.
    """
    try:
        if value is None:
            return

        if isinstance(value, str):
            s = value.strip()
            if s:
                yield s
            return

        if isinstance(value, (int, float, bool)):
            s = str(value).strip()
            if s:
                yield s
            return

        if isinstance(value, list):
            for item in value:
                yield from _iter_doc_text_fragments(item)
            return

        if isinstance(value, dict):
            for k, v in value.items():
                if str(k).strip().lower() in {"id", "doc_id", "created_at", "updated_at", "handoff_format"}:
                    continue
                yield from _iter_doc_text_fragments(v)
            return
    except Exception:
        return


def _collect_doc_texts(doc: Dict[str, Any]) -> list[str]:
    """
    Coleta todo texto útil do documento de forma estrutural.
    """
    try:
        if not isinstance(doc, dict):
            return []
        out = []
        seen = set()
        for part in _iter_doc_text_fragments(doc):
            norm = re.sub(r"\s+", " ", str(part).strip()).lower()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            out.append(str(part).strip())
        return out
    except Exception:
        return []


def _score_query_against_doc(query: str, doc: Dict[str, Any], doc_key: str = "") -> int:
    """
    Score estrutural entre a consulta e o documento.
    Usa apenas sobreposição textual e sinais negativos do próprio banco.
    """
    try:
        q = str(query or "").strip()
        if not q or not isinstance(doc, dict):
            return 0

        score = 0
        parts = _collect_doc_texts(doc)

        if doc_key:
            parts.append(str(doc_key).strip())

        for part in parts:
            score += _lookup_token_overlap_score(q, part)

        neg = doc.get("negative_keywords") or []
        if isinstance(neg, list):
            neg_hits = 0
            for item in neg:
                neg_hits += _lookup_token_overlap_score(q, str(item or ""))
            if neg_hits:
                score -= neg_hits

        return max(score, 0)
    except Exception:
        return 0


def _best_doc_match(query: str, docs_map: Dict[str, Any], min_score: int = 2) -> str:
    """
    Escolhe o melhor documento do KB pelo conteúdo real do doc.
    """
    try:
        q = str(query or "").strip()
        if not q or not isinstance(docs_map, dict):
            return ""

        best_key = ""
        best_score = 0

        for key, doc in docs_map.items():
            if not isinstance(doc, dict):
                continue
            score = _score_query_against_doc(q, doc, str(key))
            if score > best_score:
                best_score = score
                best_key = str(key).strip()

        if best_score >= min_score:
            return best_key
        return ""
    except Exception:
        return ""


def _family_to_pack_id(family: str) -> str:
    f = str(family or "").strip().lower()
    if f == "agenda":
        return "PACK_A_AGENDA"
    if f == "pedidos":
        return "PACK_C_PEDIDOS"
    if f == "servicos":
        return "PACK_B_SERVICOS"
    if f == "status":
        return "PACK_D_STATUS"
    if f == "triagem":
        return "PACK_B_SERVICOS"
    return ""

def _stable_variant_index(seed_text: str, modulo: int) -> int:
    try:
        s = str(seed_text or "").strip()
        if modulo <= 0:
            return 0
        total = 0
        for ch in s:
            total += ord(ch)
        return total % modulo
    except Exception:
        return 0


def _kb_get_example_line(kb_snapshot: str, segment: str, pack_id: str) -> str:
    """Pull example_line for segment+pack from kb_snapshot (JSON if possible; heuristic fallback)."""
    try:
        if not kb_snapshot or not segment or not pack_id:
            return ""
        # JSON first (preferred)
        try:
            obj = json.loads(kb_snapshot) if kb_snapshot.lstrip().startswith(("{","[")) else None
        except Exception:
            obj = None
        if isinstance(obj, dict):
            # KB novo: subsegmento/segmento
            kb_sub = obj.get("kb_subsegments_v1") or {}
            kb_seg = obj.get("kb_segments_v1") or {}
            seg_key = str(segment or "").strip().lower()

            if isinstance(kb_sub, dict) and seg_key in kb_sub:
                one_liner = str((kb_sub.get(seg_key) or {}).get("one_liner") or "").strip()
                if one_liner:
                    return one_liner

            if isinstance(kb_seg, dict) and seg_key in kb_seg:
                one_liner = str((kb_seg.get(seg_key) or {}).get("one_liner") or "").strip()
                if one_liner:
                    return one_liner

            m = obj.get("segment_value_map_v1") if "segment_value_map_v1" in obj else obj
            if isinstance(m, dict) and segment in m:
                tokens = (m.get(segment) or {}).get("tokens") or {}
                p = tokens.get(pack_id) or {}
                ex = p.get("example_line") or ""
                return str(ex).strip()

        # Heuristic fallback: works with common Firestore export / pretty prints like:
        # dentista (map) ... PACK_A_AGENDA ... example_line (string) ... "Pra consultório..."
        kb = kb_snapshot
        kb_low = kb.lower()
        seg_low = (segment or "").lower()
        pack_low = (pack_id or "").lower()

        seg_pos = kb_low.find(seg_low)
        if seg_pos < 0:
            # last resort: search whole snapshot for pack+example_line
            seg_pos = 0

        # Limit scan window to keep it fast
        window = kb[seg_pos: seg_pos + 5000]

        # Find pack block inside the window
        w_low = window.lower()
        p_pos = w_low.find(pack_low)
        if p_pos >= 0:
            window2 = window[p_pos: p_pos + 2500]
        else:
            window2 = window

        # Find 'example_line' within the narrowed window
        w2_low = window2.lower()
        e_pos = w2_low.find("example_line")
        if e_pos < 0:
            return ""

        tail = window2[e_pos: e_pos + 1200]

        # Strategy:
        # 1) Prefer quoted text after example_line
        q = re.search(r'"([^\n\"]{12,240})"', tail, re.DOTALL)
        if q:
            return q.group(1).strip()

        # 2) Otherwise, take the next meaningful non-empty line that is not '(string)/(map)/(array)'
        lines = [ln.strip() for ln in tail.splitlines()]
        for ln in lines[1:10]:
            if not ln:
                continue
            if ln.startswith("(") and ln.endswith(")"):
                continue
            if ln.lower() in ("string", "map", "array"):
                continue
            if "(string" in ln.lower() or "(map" in ln.lower() or "(array" in ln.lower():
                continue
            # strip trailing type hints like '(string)'
            ln = re.sub(r"\(string\)\s*$", "", ln, flags=re.IGNORECASE).strip()
            if len(ln) >= 12:
                return ln
        return ""
    except Exception:
        return ""


def _kb_get_micro_scene(kb_snapshot: str, pack_id: str) -> str:
    """Pull runtime_short.micro_scene for a given pack from kb_snapshot."""
    try:
        if not kb_snapshot or not pack_id:
            return ""
        try:
            obj = json.loads(kb_snapshot) if kb_snapshot.lstrip().startswith(("{", "[")) else None
        except Exception:
            obj = None
        if isinstance(obj, dict):
            # KB novo: se houver archetypes com micro_scene canônica do fluxo
            kb_arch = obj.get("kb_archetypes_v1") or {}
            if isinstance(kb_arch, dict):
                arch_by_pack = {
                    "PACK_A_AGENDA": ("servico_agendado", "servico_agendado_com_encaixe"),
                    "PACK_B_SERVICOS": ("comercio_catalogo_direto", "comercio_consultivo_presencial", "servico_tecnico_orcamento", "servico_tecnico_visita", "atendimento_profissional_triagem"),
                    "PACK_C_PEDIDOS": ("alimentacao_pedido",),
                    "PACK_D_STATUS": (),
                }
                for aid in arch_by_pack.get((pack_id or "").strip().upper(), ()):
                    d = kb_arch.get(aid) or {}
                    if isinstance(d, dict):
                        ms = str(d.get("micro_scene") or "").strip()
                        if ms:
                            return ms

            packs = obj.get("value_packs_v1") or {}
            if isinstance(packs, dict):
                p = packs.get((pack_id or "").strip().upper()) or {}
                runtime_short = p.get("runtime_short") or {}
                ms = str(runtime_short.get("micro_scene") or "").strip()
                if ms:
                    return ms
        return ""
    except Exception:
        return ""


def _extract_value_line(reply_text: str) -> str:
    """
    Pega a frase de valor antes do 'Na prática:' para reaproveitar o melhor do LLM
    sem deixar a parte prática ficar genérica.
    """
    try:
        r = (reply_text or "").strip()
        if not r:
            return ""
        low = r.lower()
        idx = low.find("na prática:")
        if idx != -1:
            r = r[:idx].strip()
        # pega só a primeira frase
        m = re.split(r"(?<=[\.\!\?])\s+", r, maxsplit=1)
        base = (m[0] if m else r).strip()
        return base.rstrip(".!?").strip()
    except Exception:
        return (reply_text or "").strip()


def _strip_trailing_question(text: str) -> str:
    try:
        t = str(text or "").strip()
        if not t:
            return ""
        if "?" not in t:
            return t
        # remove só a última pergunta/bloco interrogativo no fim
        t = re.sub(r"\s*[^.!\n?]{0,220}\?\s*$", "", t, flags=re.DOTALL).strip()
        t = re.sub(r"\s{2,}", " ", t).strip()
        return t.rstrip(" -–—,;:")
    except Exception:
        return str(text or "").strip()





def _split_user_operational_clauses(user_text: str) -> list[str]:
    """
    Extrai cláusulas operacionais do próprio texto do usuário sem usar
    listas de negócio, palavras-chave por segmento ou frase pronta.
    """
    try:
        t = str(user_text or "").strip()
        if not t:
            return []

        t = re.sub(r"\s{2,}", " ", t).strip()
        t = t.replace("\n", " ")
        t = re.sub(r"[?]+", ".", t)
        t = re.sub(r"[!]+", ".", t)

        raw_parts = re.split(r"\s*(?:,|;|\.|\s+-\s+|\s+e\s+depois\s+|\s+depois\s+|\s+ent[aã]o\s*)", t)
        parts = []

        for part in raw_parts:
            p = re.sub(r"\s{2,}", " ", str(part or "").strip(" .,:;-"))
            p = p.strip()
            if not p:
                continue
            if len(p) < 12:
                continue
            parts.append(p)

        return parts[:6]
    except Exception:
        return []


def _build_user_operational_seed(user_text: str) -> str:
    """
    Constrói um trilho operacional mínimo a partir do relato do usuário.
    Não inventa fatos novos; só reorganiza o que o usuário já descreveu.
    """
    try:
        clauses = _split_user_operational_clauses(user_text)
        if not clauses:
            return ""

        if len(clauses) == 1:
            one = str(clauses[0] or "").strip()
            return one if len(one) >= 24 else ""

        cleaned = []
        seen = set()
        for clause in clauses:
            c = re.sub(r"\s{2,}", " ", str(clause or "").strip(" ."))
            if not c:
                continue
            key = c.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(c)

        if len(cleaned) < 2:
            one = cleaned[0] if cleaned else ""
            return one if len(one) >= 24 else ""

        return " → ".join(cleaned[:5]).strip(" .")
    except Exception:
        return ""

def _needs_discovery_question(
    topic: str,
    confidence: str,
    operational_family: str,
    ai_turns: int,
    effective_segment: str = "",
    needs_clarify: str = "",
    clarify_q: str = "",
    practical_scene_from_kb: str = "",
    example_line: str = "",
    reply_text: str = "",
) -> bool:
    """
    Decide se devemos abrir UMA pergunta de discovery.
    Regra arquitetural:
    - não depender de palavras-chave de negócio;
    - usar os sinais já produzidos pela IA e pelo KB;
    - só perguntar quando realmente ainda não houver operação suficiente
      para responder com utilidade.
    """
    try:
        topic = str(topic or "").upper()
        confidence = str(confidence or "").lower()
        operational_family = str(operational_family or "").strip()
        seg = str(effective_segment or "").strip().lower()
        needs_clarify = str(needs_clarify or "").strip().lower()
        clarify_q = str(clarify_q or "").strip()
        practical_scene_from_kb = str(practical_scene_from_kb or "").strip()
        example_line = str(example_line or "").strip()
        reply_text = str(reply_text or "").strip()

        if ai_turns > 0:
            return False

        # Se já temos ancoragem forte suficiente, não abrir discovery.
        # Mas segmento sozinho não basta se ainda não houver cena/exemplo/fluxo.
        if practical_scene_from_kb:
            return False
        if example_line:
            return False
        if seg and operational_family:
            return False

        # Se a IA já produziu um reply aproveitável, também não perguntar.
        if reply_text:
            return False

        # Clarify explícito do modelo é o sinal mais forte para permitir 1 pergunta.
        if needs_clarify == "yes":
            return True
        if clarify_q:
            return True

        # Discovery só entra quando a clarificação é realmente necessária.
        # Se ainda estamos no turno 0 e não há ancoragem, mas o caso é apenas
        # amplo (não colapsado), preferimos deixar o front tentar responder.
        if needs_clarify == "yes":
            return True

        if clarify_q:
            # Clarify_q sozinho não basta para mandar discovery no turno 0.
            # Ele pode ser só excesso de cautela do modelo.
            if ai_turns > 0:
                return True
            return False

        return False
    except Exception:
        return False

def _should_allow_question(*, user_text: str, kb_context: Dict[str, Any], reply_text: str, understanding: Dict[str, Any], decider: Dict[str, Any]) -> bool:
    try:
        rt = str(reply_text or "").strip()
        if "?" not in rt:
            return False

        question_type = str((decider or {}).get("questionType") or "").strip().lower()
        if question_type in ("clarify", "name", "segment", "link_permission"):
            return True

        topic = str((understanding or {}).get("topic") or "").strip().upper()
        confidence = str((understanding or {}).get("confidence") or "").strip().lower()
        wants_link = bool((kb_context or {}).get("wants_link_explicit"))
        needs_segment = bool((kb_context or {}).get("needs_segment_discovery"))

        # 1) ambiguidade real
        # OTHER com confidence medium não autoriza pergunta por si só.
        if confidence == "low":
            return True
        if topic in ("OTHER", "") and confidence in ("low", ""):
            return True

        # 2) descoberta de segmento/nome
        if needs_segment:
            return True

        # 3) abertura comercial clara para link/ativação
        if wants_link:
            return True

        return False
    except Exception:
        return False


def _extract_json_string_field(raw: str, field_name: str) -> str:
    try:
        s = str(raw or "")
        if not s:
            return ""
        m = re.search(
            rf'"{re.escape(field_name)}"\s*:\s*"((?:\\.|[^"\\])*)"',
            s,
            flags=re.DOTALL,
        )
        if not m:
            return ""
        val = m.group(1)
        val = val.replace(r"\/", "/")
        val = val.replace(r'\"', '"')
        val = val.replace(r"\n", "\n")
        val = val.replace(r"\t", "\t")
        val = val.replace(r"\r", "")
        return str(val).strip()
    except Exception:
        return ""


def _extract_json_object_field(raw: str, field_name: str) -> Dict[str, Any]:
    try:
        s = str(raw or "")
        if not s:
            return {}
        m = re.search(
            rf'"{re.escape(field_name)}"\s*:\s*(\{{.*?\}})',
            s,
            flags=re.DOTALL,
        )
        if not m:
            return {}
        obj = json.loads(m.group(1))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _salvage_free_mode_payload(raw: str) -> Dict[str, Any]:
    try:
        reply = _extract_json_string_field(raw, "replyText")
        spoken = _extract_json_string_field(raw, "spokenText")
        next_step = _extract_json_string_field(raw, "nextStep") or "NONE"
        understanding = _extract_json_object_field(raw, "understanding")
        topic = str((understanding or {}).get("topic") or "").strip().upper() or "OTHER"
        confidence = str((understanding or {}).get("confidence") or "").strip().lower() or "medium"
        if reply:
            return {
                "replyText": reply,
                "spokenText": spoken or reply,
                "understanding": {"topic": topic, "confidence": confidence},
                "nextStep": next_step,
            }
        return {}
    except Exception:
        return {}


def _build_free_mode_family_hint(user_text: str, effective_segment: str = "") -> str:
    """
    Mantido apenas por compatibilidade.
    Não injeta direção textual fixa no prompt.
    """
    return ""


def _parse_free_mode_text_response(
    raw: str,
    *,
    topic_hint: str = "OTHER",
    confidence_hint: str = "medium",
) -> Dict[str, Any]:
    """
    Em free_mode, a IA pode devolver texto livre.
    Este helper transforma texto puro em payload compatível com o worker.
    """
    try:
        txt = _sanitize_user_facing_reply(raw)
        txt = re.sub(r"\s{2,}", " ", txt).strip()

        if not txt:
            return {}

        topic = str(topic_hint or "OTHER").strip().upper() or "OTHER"
        if topic not in TOPICS:
            topic = "OTHER"

        confidence = str(confidence_hint or "medium").strip().lower() or "medium"
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"

        return {
            "replyText": txt,
            "spokenText": txt,
            "understanding": {
                "topic": topic,
                "confidence": confidence,
            },
            "nextStep": "NONE",
            "shouldEnd": False,
            "nameUse": "none",
            "prefersText": False,
            "replySource": "front_free_text",
        }
    except Exception:
        return {}


def _build_scene_hint_block(*, family_hint: str, micro_scene: str, example_line: str, practical_scene_from_kb: str) -> str:
    """
    Enxuga contexto adicional de cena antes de injetar no system_prompt.
    Prioridade:
    1) practical_scene_from_kb
    2) example_line + micro_scene
    3) micro_scene
    4) example_line
    family_hint entra só como apoio, sem duplicar a mesma cena.
    """
    try:
        fh = str(family_hint or "").strip()
        ms = str(micro_scene or "").strip()
        ex = str(example_line or "").strip()
        ps = str(practical_scene_from_kb or "").strip()

        parts = []

        if fh:
            parts.append("Direção operacional prioritária:\n" + fh)

        if ps:
            parts.append("Cena preferencial do KB:\n" + ps)
        else:
            if ex and ms:
                parts.append("Referência de exemplo do segmento:\n" + ex)
                parts.append("Microcena sugerida:\n" + ms)
            elif ms:
                parts.append("Microcena sugerida:\n" + ms)
            elif ex:
                parts.append("Referência de exemplo do segmento:\n" + ex)

        return "\n\n".join([p for p in parts if p]).strip()
    except Exception:
        return ""




def compress_kb_context(kb_text: str, limit: int = 900) -> str:
    """
    Compacta o contexto do Firestore para reduzir ruído.
    Mantém apenas partes mais informativas.
    """

    if not kb_text:
        return ""

    kb_text = kb_text.strip()

    if len(kb_text) <= limit:
        return kb_text

    # quebra em linhas
    parts = [p.strip() for p in kb_text.split("\n") if p.strip()]

    # remove duplicações simples
    seen = set()
    filtered = []

    for p in parts:
        key = p.lower()[:80]
        if key not in seen:
            seen.add(key)
            filtered.append(p)

    compact = " ".join(filtered)

    return compact[:limit]


def build_dynamic_context_frame(segment: str, kb_text: str) -> str:
    """
    Cria enquadramento cognitivo para a IA
    sem usar palavras-chave ou scripts.
    """

    segment = segment or "negócio local"

    return (
        f"O usuário descreve uma situação comum de um {segment}. "
        "A resposta deve mostrar como o robô ajuda na conversa real com o cliente. "
        "Mostre de forma natural o que acontece quando o cliente manda mensagem "
        "e como o robô conduz o próximo passo. "
        "Evite explicar software; descreva a cena prática. "
        f"\n\nContexto disponível:\n{kb_text}"
    )


def _build_user_scene_block(*, practical_scene_from_kb: str, example_line: str, kb_section: str, kb_compact: str) -> str:
    """
    Enxuga o payload do usuário para evitar duplicação entre:
    - practical_scene_from_kb
    - example_line
    - KB Context
    - KB SNAPSHOT COMPACTO
    Mantém fallback do snapshot, mas prioriza o que já foi selecionado.
    """
    try:
        ps = str(practical_scene_from_kb or "").strip()
        ex = str(example_line or "").strip()
        ks = str(kb_section or "").strip()
        kc = str(kb_compact or "").strip()

        parts = []

        if ps:
            parts.append("[REGRA CRÍTICA DE GERAÇÃO]\nA microcena DEVE ser construída a partir da CENA PREFERENCIAL DO KB.\n- O KB é a fonte da verdade.\n- O exemplo abaixo NÃO define comportamento.\n- O exemplo serve apenas para tom e ritmo.\n- Se houver conflito, IGNORE o exemplo.\n- NUNCA invente etapas que não estejam no KB.")
            parts.append(f"[CENA PREFERENCIAL]\n{ps}")
        elif ex:
            parts.append(f"[EXEMPLO DO SEGMENTO]\n{ex}")
        else:
            if ex:
                parts.append(f"[EXEMPLO DO SEGMENTO]\n{ex}")

        if ks:
            parts.append(ks)

        if kc:
            parts.append("[KB SNAPSHOT COMPACTO — FALLBACK]\n" + kc)

        return "\n\n".join([p for p in parts if p]).strip()
    except Exception:
        return str(kb_compact or "").strip()


def _de_genericize_free_mode_text(text: str) -> str:
    # IA TOTAL: não reescrever semântica por regex.
    # Mantemos só uma higiene textual mínima.
    try:
        t = str(text or "").strip()
        if not t:
            return ""
        t = re.sub(r"\s+\?", "?", t)
        t = re.sub(r"\.\s*\.", ".", t)
        t = re.sub(r"\s+,", ",", t)
        t = re.sub(r"\s+\.", ".", t)
        t = re.sub(r"\s{2,}", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip(" \n")
    except Exception:
        return str(text or "").strip()


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


def _looks_like_dialogue_stub(text: str) -> bool:
    """
    Detecta saídas em formato de falas rotuladas, script curto ou abertura solta.
    Regra estrutural: sem listas por segmento e sem frases prontas.
    """
    try:
        t = str(text or "").strip()
        if not t:
            return True

        if len(t) < 24:
            return True

        sentences = [s.strip() for s in _split_sentences_pt(t) if str(s).strip()]
        first = sentences[0] if sentences else t

        if len(sentences) == 1 and "?" in t:
            return True

        # rótulos de fala / script
        if re.search(r"(^|\n)\s*\*{0,2}[A-Za-zÀ-ÿ _-]{2,20}\*{0,2}\s*:", t):
            return True

        if re.search(r"(^|\n)\s*[-–—]\s*[A-Za-zÀ-ÿ _-]{2,20}\s*:", t):
            return True

        # abertura com sinal típico de fala roteirizada
        if re.match(r'^[\-\–\—"\“\”\'«»]', first):
            return True

        if first.endswith("?"):
            return True

        return False
    except Exception:
        return False

def _has_strong_kb_anchor(
    *,
    kb_context: Dict[str, Any],
    effective_segment: str,
    operational_family: str,
    practical_scene_from_kb: str,
    example_line: str,
    selected_pack_id: str,
) -> bool:
    """
    Mede se o banco novo já deu base suficiente para a IA responder
    sem cair em fallback genérico.
    Não decide texto. Só mede força de ancoragem.
    """
    try:
        score = 0
        if str(effective_segment or "").strip():
            score += 2
        if str((kb_context or {}).get("subsegment_hint") or "").strip():
            score += 2
        if str((kb_context or {}).get("archetype_id") or "").strip():
            score += 2
        if str(operational_family or "").strip():
            score += 1
        if str(practical_scene_from_kb or "").strip():
            score += 3
        if str(example_line or "").strip():
            score += 2
        if str(selected_pack_id or "").strip():
            score += 1
        return score >= 6
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
    practical_scene_from_kb: str,
    example_line: str,
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

        if str(practical_scene_from_kb or "").strip():
            score += 1
        if str(example_line or "").strip():
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
    practical_scene_from_kb: str,
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
            scene = str(practical_scene_from_kb or "").strip().lower()
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
    practical_scene_from_kb: str,
    example_line: str,
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
            practical_scene_from_kb
            or (contract or {}).get("practical_scene_from_kb")
            or ""
        ).strip()

        if not grounded_scene:
            return False

        contract_strong = bool(
            (contract or {}).get("hydrated_from_docs")
            and str(example_line or "").strip()
            and grounded_scene
        )

        transition = _scene_transition_score(t)
        density = _operational_density_score(
            text=t,
            practical_scene_from_kb=grounded_scene,
            example_line=example_line,
            effective_segment=str((contract or {}).get("segment") or "").strip(),
            operational_family=str((contract or {}).get("operational_family") or "").strip(),
        )
        progress = _operational_progress_score(
            text=t,
            practical_scene_from_kb=grounded_scene,
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
    practical_scene_from_kb: str,
    example_line: str,
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
    practical_scene_from_kb: str,
    example_line: str,
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
            practical_scene_from_kb
            or (contract or {}).get("practical_scene_from_kb")
            or ""
        ).strip()

        contract_strong = bool(
            (contract or {}).get("hydrated_from_docs")
            and str(example_line or "").strip()
            and grounded_scene
        )

        if not _is_live_operational_reply(
            text=t,
            practical_scene_from_kb=grounded_scene,
            example_line=example_line,
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
            practical_scene_from_kb=grounded_scene,
            example_line=example_line,
            effective_segment=str((contract or {}).get("segment") or "").strip(),
            operational_family=str((contract or {}).get("operational_family") or "").strip(),
        )
        progress = _operational_progress_score(
            text=t,
            practical_scene_from_kb=grounded_scene,
            contract=contract or {},
        )
        observer_voice = _observer_voice_score(t)
        explanatory = _looks_explanatory_reply(
            text=t,
            practical_scene_from_kb=grounded_scene,
            example_line=example_line,
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
    practical_scene_from_kb: str,
    example_line: str,
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
            practical_scene_from_kb="",
            example_line=example_line,
            contract=contract or {},
        ):
            return True

        return False
    except Exception:
        return True

def _preferred_topic_from_kb(*, kb_context: Dict[str, Any], current_topic: str) -> str:
    """
    Determina topic preferido com base no KB.
    Evita que casos ancorados caiam em OTHER.
    """
    try:
        topic = str(current_topic or "").strip().upper() or "OTHER"
        intent_hint = str((kb_context or {}).get("intent_hint") or "").strip().upper()
        if intent_hint in TOPICS and intent_hint not in ("OTHER", ""):
            return intent_hint

        archetype = str((kb_context or {}).get("archetype_id") or "").strip().lower()
        primary_goal = str(
            ((kb_context or {}).get("segment_profile") or {}).get("primary_goal") or ""
        ).lower()

        # prioridade por archetype
        if archetype == "servico_tecnico_visita":
            return "PROCESSO"

        if archetype in ("comercio_catalogo_direto", "alimentacao_pedido"):
            return "PRODUTO"

        if archetype == "comercio_consultivo_presencial":
            return "SERVICOS"

        if archetype in ("servico_agendado", "servico_agendado_com_encaixe"):
            return "AGENDA"

        if "visita" in primary_goal:
            return "PROCESSO"

        if "compra" in primary_goal or "reserva" in primary_goal:
            return "PRODUTO"

        if "agendar" in primary_goal or "marcar" in primary_goal:
            return "AGENDA"

        family = str((kb_context or {}).get("operational_family") or "").strip().lower()
        fam_map = {
            "agenda": "AGENDA",
            "pedidos": "PEDIDOS",
            "servicos": "SERVICOS",
            "triagem": "PROCESSO",
            "status": "STATUS",
        }
        if family in fam_map:
            return fam_map[family]

        pack_id = str((kb_context or {}).get("pack_id") or "").strip().upper()
        pack_map = {
            "PACK_A_AGENDA": "AGENDA",
            "PACK_B_SERVICOS": "SERVICOS",
            "PACK_C_PEDIDOS": "PEDIDOS",
            "PACK_D_STATUS": "STATUS",
        }
        if pack_id in pack_map:
            return pack_map[pack_id]
        return topic
    except Exception:
        return str(current_topic or "").strip().upper() or "OTHER"


def _build_kb_anchor_reply(
    *,
    practical_scene_from_kb: str,
    example_line: str,
    clarify_q: str = "",
    contract: Dict[str, Any] | None = None,
) -> str:
    """
    Fallback mínimo e alinhado ao princípio de IA soberana:
    usa o que o banco já trouxe, sem transformar example_line em resposta final.
    """
    try:
        stable_scene = _stabilize_scene_base(str(practical_scene_from_kb or "").strip())
        generated = _generate_micro_scene_with_model(
            practical_scene_from_kb=practical_scene_from_kb,
            contract=contract or {},
        )

        scene_text = str(generated or "").strip()
        if not scene_text and stable_scene:
            scene_text = _compose_grounded_scene_with_progression(
                practical_scene_from_kb=practical_scene_from_kb,
                contract=contract or {},
                example_line=str(example_line or "").strip(),
            )

        if not scene_text and stable_scene:
            scene_text = _compose_grounded_scene_with_progression(
                practical_scene_from_kb=practical_scene_from_kb,
                contract=contract or {},
                example_line=str(example_line or "").strip(),
            )

        scene_text = _sanitize_user_facing_reply(scene_text)
        scene_text = re.sub(r"\s{2,}", " ", scene_text).strip(" .")

        if scene_text:
            if _is_live_operational_reply(
                text=scene_text,
                practical_scene_from_kb=practical_scene_from_kb,
                example_line=str(example_line or "").strip(),
                contract=contract or {},
            ):
                return scene_text.rstrip(".") + "."

        rebuilt = _build_last_resort_operational_reply(
            practical_scene_from_kb="",
            example_line=str(example_line or "").strip(),
            contract=contract or {},
            clarify_q=clarify_q,
        )
        if rebuilt:
            return rebuilt

        return str(clarify_q or "").strip()
    except Exception:
        return str(clarify_q or "").strip()


def _build_last_resort_operational_reply(
    *,
    practical_scene_from_kb: str,
    example_line: str,
    contract: Dict[str, Any] | None = None,
    clarify_q: str = "",
) -> str:
    """
    Último recurso canônico.
    Nunca devolve a cena-base crua.
    Só libera texto se a forma final já vier minimamente viva.
    """
    try:
        c = dict(contract or {})
        stable_scene = _stabilize_scene_base(str(practical_scene_from_kb or "").strip())
        ex = str(example_line or "").strip()

        if not stable_scene:
            return str(clarify_q or "").strip()

        rebuilt = _compose_grounded_scene_with_progression(
            practical_scene_from_kb=practical_scene_from_kb,
            contract=c,
            example_line=ex,
        )
        rebuilt = _sanitize_user_facing_reply(rebuilt)
        rebuilt = re.sub(r"\s{2,}", " ", str(rebuilt or "")).strip(" .")

        if rebuilt and _is_live_operational_reply(
            text=rebuilt,
            practical_scene_from_kb="",
            example_line=ex,
            contract=c,
        ):
            return rebuilt.rstrip(".") + "."

        generated = _generate_micro_scene_with_model(
            practical_scene_from_kb=practical_scene_from_kb,
            contract=c,
        )
        generated = _sanitize_user_facing_reply(generated)
        generated = re.sub(r"\s{2,}", " ", str(generated or "")).strip(" .")

        if generated and "→" in generated:
            return generated.rstrip(".") + "."

        return str(clarify_q or "").strip()
    except Exception:
        return str(clarify_q or "").strip()

def _kb_get_segment_scene(kb_snapshot: str, segment_key: str) -> str:
    """
    Puxa a cena diretamente do banco novo para segmento/subsegmento.
    Prioridade:
    1) kb_subsegments_v1[segment_key].micro_scene
    2) kb_segments_v1[segment_key].micro_scene
    3) one_liner + ritual operacional resumido
    4) ritual operacional resumido
    """
    try:
        if not kb_snapshot or not segment_key:
            return ""
        obj = json.loads(kb_snapshot) if kb_snapshot and kb_snapshot.lstrip().startswith(("{", "[")) else None
        if not isinstance(obj, dict):
            return ""

        seg = str(segment_key or "").strip().lower()
        doc = {}

        kb_sub = obj.get("kb_subsegments_v1") or {}
        if isinstance(kb_sub, dict):
            d = kb_sub.get(seg) or {}
            if isinstance(d, dict) and d:
                doc = d

        if not doc:
            kb_seg = obj.get("kb_segments_v1") or {}
            if isinstance(kb_seg, dict):
                d = kb_seg.get(seg) or {}
                if isinstance(d, dict) and d:
                    doc = d

        if not isinstance(doc, dict) or not doc:
            return ""

        ms = str(doc.get("micro_scene") or "").strip()
        if ms:
            return ms

        one_liner = str(doc.get("one_liner") or "").strip()

        ritual = doc.get("operational_ritual") or []
        if isinstance(ritual, list):
            steps = [str(x).strip() for x in ritual if str(x).strip()]
            if one_liner and steps:
                return one_liner.rstrip(". ") + " → " + " → ".join(steps[:5])
            if steps:
                return " → ".join(steps[:5])

        if one_liner:
            return one_liner
        return ""
    except Exception:
        return ""




def _refresh_operational_anchor(
    *,
    kb_snapshot: str,
    kb_context: Dict[str, Any],
    effective_segment: str,
    selected_pack_id: str,
    operational_family: str,
) -> Dict[str, str]:
    """
    Refaz a leitura operacional do banco antes da composição final.
    Isso reduz deriva do texto e reforça a cena correta sem engessar wording.
    """
    try:
        seg = str(
            (kb_context or {}).get("effective_subsegment")
            or (kb_context or {}).get("subsegment_hint")
            or effective_segment
            or ""
        ).strip()
        pack_id = str(selected_pack_id or "").strip().upper()

        example_line = str((kb_context or {}).get("segment_example_line") or "").strip()
        practical_scene = str((kb_context or {}).get("practical_scene_from_kb") or "").strip()
        micro_scene = str((kb_context or {}).get("pack_micro_scene") or "").strip()
        family = str(
            (kb_context or {}).get("operational_family")
            or operational_family
            or ""
        ).strip()

        if seg and not example_line:
            example_line = _kb_get_example_line(kb_snapshot, seg, pack_id)

        if seg and not practical_scene:
            practical_scene = _kb_get_segment_scene(kb_snapshot, seg)

        if not practical_scene and micro_scene:
            practical_scene = micro_scene

        if not practical_scene and seg and pack_id:
            practical_scene = _compose_practical_scene(
                kb_snapshot=kb_snapshot,
                segment_key=seg,
                pack_id=pack_id,
            )

        return {
            "example_line": str(example_line or "").strip(),
            "practical_scene_from_kb": str(practical_scene or "").strip(),
            "operational_family": str(family or "").strip(),
        }
    except Exception:
        return {
            "example_line": str((kb_context or {}).get("segment_example_line") or "").strip(),
            "practical_scene_from_kb": str((kb_context or {}).get("practical_scene_from_kb") or "").strip(),
            "operational_family": str((kb_context or {}).get("operational_family") or operational_family or "").strip(),
        }


def _find_kb_map_anywhere(obj: Any, target_key: str, max_depth: int = 4) -> Dict[str, Any]:
    """
    Procura um mapa do KB em qualquer nível razoável do snapshot.
    Resolve casos em que o snapshot não vem com kb_* na raiz direta.
    """
    try:
        if max_depth < 0:
            return {}

        if isinstance(obj, dict):
            direct = obj.get(target_key)
            if isinstance(direct, dict):
                return direct

            for _, v in obj.items():
                found = _find_kb_map_anywhere(v, target_key, max_depth=max_depth - 1)
                if isinstance(found, dict) and found:
                    return found

        elif isinstance(obj, list):
            for item in obj:
                found = _find_kb_map_anywhere(item, target_key, max_depth=max_depth - 1)
                if isinstance(found, dict) and found:
                    return found

        return {}
    except Exception:
        return {}


def _kb_lookup_operational_docs(
    *,
    kb_snapshot: str,
    effective_segment: str,
    kb_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Hidrata documentos reais do banco para fortalecer o contrato operacional.
    Prioridade:
    1) subsegmento
    2) archetype referenciado pelo subsegmento
    3) segmento macro
    """
    try:
        raw = str(kb_snapshot or "").strip()
        obj = None

        if raw.startswith("{") or raw.startswith("["):
            try:
                obj = json.loads(raw)
            except Exception:
                obj = None

        if not isinstance(obj, (dict, list)):
            logging.info(
                "[CONVERSATIONAL_FRONT][KB_LOOKUP] snapshot_not_json seg=%s",
                str(effective_segment or "").strip().lower(),
            )
            return {"subsegment_doc": {}, "segment_doc": {}, "archetype_doc": {}}

        seg_key = str(effective_segment or "").strip().lower()
        hinted_sub = str((kb_context or {}).get("subsegment_hint") or "").strip().lower()
        user_probe = " ".join(
            [
                str(effective_segment or "").strip(),
                str((kb_context or {}).get("segment_hint") or "").strip(),
                str((kb_context or {}).get("subsegment_hint") or "").strip(),
                str((kb_context or {}).get("segment_example_line") or "").strip(),
                str((kb_context or {}).get("practical_scene_from_kb") or "").strip(),
            ]
        ).strip()

        kb_sub = _find_kb_map_anywhere(obj, "kb_subsegments_v1")
        kb_seg = _find_kb_map_anywhere(obj, "kb_segments_v1")
        kb_arch = _find_kb_map_anywhere(obj, "kb_archetypes_v1")

        sub_doc: Dict[str, Any] = {}
        seg_doc: Dict[str, Any] = {}
        arch_doc: Dict[str, Any] = {}

        # 1) busca direta do subsegmento
        if seg_key and isinstance(kb_sub, dict):
            d = kb_sub.get(seg_key) or {}
            if isinstance(d, dict) and d:
                sub_doc = d

        # 2) fallback tolerante por chave normalizada
        if not sub_doc and seg_key and isinstance(kb_sub, dict):
            norm_target = seg_key.replace("-", "_").replace(" ", "_")
            for k, d in kb_sub.items():
                kk = str(k or "").strip().lower().replace("-", "_").replace(" ", "_")
                if not isinstance(d, dict):
                    continue
                if kk == norm_target:
                    sub_doc = d
                    break

        # 3) fallback tolerante por contenção
        if not sub_doc and seg_key and isinstance(kb_sub, dict):
            for k, d in kb_sub.items():
                kk = str(k or "").strip().lower()
                if not isinstance(d, dict):
                    continue
                if seg_key in kk or kk in seg_key:
                    sub_doc = d
                    break

        # 4) fallback estrutural por overlap de tokens
        if not sub_doc and seg_key and isinstance(kb_sub, dict):
            best_sub_key = _best_lookup_key_match(seg_key, list(kb_sub.keys()), min_score=2)
            if best_sub_key:
                d = kb_sub.get(best_sub_key) or {}
                if isinstance(d, dict) and d:
                    sub_doc = d

        # 5) se o effective_segment vier macro, tenta promover para subsegmento real
        if not sub_doc and isinstance(kb_sub, dict) and kb_sub:
            promoted_sub_key = ""

            if hinted_sub and hinted_sub in kb_sub:
                promoted_sub_key = hinted_sub

            if not promoted_sub_key and user_probe:
                best_sub_key = _best_doc_match(user_probe, kb_sub, min_score=2)
                if best_sub_key and "__" in str(best_sub_key):
                    promoted_sub_key = str(best_sub_key).strip().lower()

            if promoted_sub_key:
                d = kb_sub.get(promoted_sub_key) or {}
                if isinstance(d, dict) and d:
                    sub_doc = d
                    seg_key = promoted_sub_key

        segment_id = str(
            (sub_doc or {}).get("segment_id")
            or (kb_context or {}).get("segment_id")
            or ""
        ).strip().lower()

        if segment_id and isinstance(kb_seg, dict):
            d = kb_seg.get(segment_id) or {}
            if isinstance(d, dict) and d:
                seg_doc = d

        if not seg_doc and segment_id and isinstance(kb_seg, dict):
            norm_segment = segment_id.replace("-", "_").replace(" ", "_")
            for k, d in kb_seg.items():
                kk = str(k or "").strip().lower().replace("-", "_").replace(" ", "_")
                if not isinstance(d, dict):
                    continue
                if kk == norm_segment:
                    seg_doc = d
                    break
        if not seg_doc and segment_id and isinstance(kb_seg, dict):
            best_seg_key = _best_lookup_key_match(segment_id, list(kb_seg.keys()), min_score=2)
            if best_seg_key:
                d = kb_seg.get(best_seg_key) or {}
                if isinstance(d, dict) and d:
                    seg_doc = d

        archetype_id = str(
            (sub_doc or {}).get("archetype_id")
            or (kb_context or {}).get("archetype_id")
            or ""
        ).strip().lower()

        if archetype_id and isinstance(kb_arch, dict):
            d = kb_arch.get(archetype_id) or {}
            if isinstance(d, dict) and d:
                arch_doc = d

        if not arch_doc and archetype_id and isinstance(kb_arch, dict):
            norm_arch = archetype_id.replace("-", "_").replace(" ", "_")
            for k, d in kb_arch.items():
                kk = str(k or "").strip().lower().replace("-", "_").replace(" ", "_")
                if not isinstance(d, dict):
                    continue
                if kk == norm_arch:
                    arch_doc = d
                    break
        if not arch_doc and archetype_id and isinstance(kb_arch, dict):
            best_arch_key = _best_lookup_key_match(archetype_id, list(kb_arch.keys()), min_score=2)
            if best_arch_key:
                d = kb_arch.get(best_arch_key) or {}
                if isinstance(d, dict) and d:
                    arch_doc = d

        logging.info(
            "[CONVERSATIONAL_FRONT][KB_LOOKUP] seg=%s sub_keys=%s seg_keys=%s arch_keys=%s found_sub=%s found_seg=%s found_arch=%s segment_id=%s archetype_id=%s",
            seg_key,
            len(kb_sub or {}),
            len(kb_seg or {}),
            len(kb_arch or {}),
            bool(sub_doc),
            bool(seg_doc),
            bool(arch_doc),
            segment_id,
            archetype_id,
        )

        return {
            "subsegment_doc": sub_doc if isinstance(sub_doc, dict) else {},
            "segment_doc": seg_doc if isinstance(seg_doc, dict) else {},
            "archetype_doc": arch_doc if isinstance(arch_doc, dict) else {},
        }
    except Exception as e:
        logging.warning(
            "[CONVERSATIONAL_FRONT][KB_LOOKUP] error seg=%s err=%s",
            str(effective_segment or "").strip().lower(),
            e,
        )
        return {"subsegment_doc": {}, "segment_doc": {}, "archetype_doc": {}}

def _infer_segment_from_docs(
    *,
    user_text: str,
    kb_snapshot: str,
    kb_context: Dict[str, Any],
) -> str:
    """
    Tenta descobrir o melhor segmento/subsegmento usando o texto do usuário
    e as chaves reais do KB, com matching estrutural.
    """
    try:
        raw = str(kb_snapshot or "").strip()
        if not raw or not (raw.startswith("{") or raw.startswith("[")):
            return ""

        obj = json.loads(raw)
        if not isinstance(obj, (dict, list)):
            return ""

        kb_sub = _find_kb_map_anywhere(obj, "kb_subsegments_v1")
        kb_seg = _find_kb_map_anywhere(obj, "kb_segments_v1")

        hinted = str(
            (kb_context or {}).get("subsegment_hint")
            or (kb_context or {}).get("segment_hint")
            or ""
        ).strip()

        search_text = " ".join(
            [
                str(user_text or "").strip(),
                hinted,
            ]
        ).strip()

        if isinstance(kb_sub, dict) and kb_sub:
            best_sub = _best_doc_match(search_text, kb_sub, min_score=2)
            if best_sub:
                return str(best_sub).strip().lower()

        if isinstance(kb_seg, dict) and kb_seg:
            best_seg = _best_doc_match(search_text, kb_seg, min_score=2)
            if best_seg:
                return str(best_seg).strip().lower()

        candidates = []
        if isinstance(kb_sub, dict):
            candidates.extend([str(k).strip() for k in kb_sub.keys() if str(k).strip()])
        if isinstance(kb_seg, dict):
            candidates.extend([str(k).strip() for k in kb_seg.keys() if str(k).strip()])

        best = _best_lookup_key_match(search_text, candidates, min_score=2)
        return str(best or "").strip().lower()
    except Exception:
        return ""


def _merge_real_kb_operational_context(
    *,
    kb_context: Dict[str, Any],
    docs: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Enriquece kb_context com os docs reais do banco.
    Não inventa nada; só preenche lacunas.
    """
    try:
        ctx = dict(kb_context or {})
        sub_doc = (docs or {}).get("subsegment_doc") or {}
        seg_doc = (docs or {}).get("segment_doc") or {}
        use_seg = not bool(sub_doc)
        arch_doc = (docs or {}).get("archetype_doc") or {}
        subsegment_key = str((sub_doc or {}).get("id") or "").strip()
        if subsegment_key:
            ctx["subsegment_hint"] = subsegment_key
            ctx["effective_subsegment"] = subsegment_key

        def _pick(*vals: Any) -> str:
            for v in vals:
                s = str(v or "").strip()
                if s:
                    return s
            return ""

        segment_profile = dict(ctx.get("segment_profile") or {})

        archetype_id = _pick(
            ctx.get("archetype_id"),
            sub_doc.get("archetype_id"),
            arch_doc.get("id"),
        )
        if archetype_id:
            ctx["archetype_id"] = archetype_id

        segment_id = _pick(
            ctx.get("segment_id"),
            sub_doc.get("segment_id"),
            seg_doc.get("id"),
        )
        if segment_id:
            ctx["segment_id"] = segment_id

        primary_goal = _pick(
            segment_profile.get("primary_goal"),
            sub_doc.get("primary_goal"),
            arch_doc.get("primary_goal"),
            seg_doc.get("primary_goal"),
        )
        if primary_goal:
            segment_profile["primary_goal"] = primary_goal

        service_noun = _pick(
            segment_profile.get("service_noun"),
            sub_doc.get("service_noun"),
            arch_doc.get("service_noun"),
            seg_doc.get("customer_noun"),
        )
        if service_noun:
            segment_profile["service_noun"] = service_noun

        handoff_format = _pick(
            segment_profile.get("handoff_format"),
            sub_doc.get("handoff_format"),
            arch_doc.get("handoff_format"),
            seg_doc.get("handoff_format"),
        )
        if handoff_format:
            segment_profile["handoff_format"] = handoff_format

        customer_noun = _pick(
            segment_profile.get("customer_noun"),
            sub_doc.get("customer_noun"),
            arch_doc.get("customer_noun"),
            seg_doc.get("customer_noun"),
        )
        if customer_noun:
            segment_profile["customer_noun"] = customer_noun

        conversion_noun = _pick(
            segment_profile.get("conversion_noun"),
            sub_doc.get("conversion_noun"),
            arch_doc.get("conversion_noun"),
            seg_doc.get("conversion_noun"),
        )
        if conversion_noun:
            segment_profile["conversion_noun"] = conversion_noun

        operational_ritual = (
            segment_profile.get("operational_ritual")
            or sub_doc.get("operational_ritual")
            or arch_doc.get("operational_ritual")
            or seg_doc.get("operational_ritual")
            or []
        )
        cleaned_ritual = [str(x).strip() for x in operational_ritual if str(x).strip()] if isinstance(operational_ritual, list) else []

        if not cleaned_ritual:
            derived_scene = _pick(
                ctx.get("practical_scene_from_kb"),
                sub_doc.get("micro_scene"),
                arch_doc.get("micro_scene"),
                seg_doc.get("micro_scene"),
            )
            cleaned_ritual = _derive_ritual_from_scene(derived_scene)

        if cleaned_ritual:
            segment_profile["operational_ritual"] = cleaned_ritual

        preferred_capabilities = (
            segment_profile.get("preferred_capabilities")
            or sub_doc.get("preferred_capabilities")
            or arch_doc.get("preferred_capabilities")
            or seg_doc.get("preferred_capabilities")
            or []
        )
        if isinstance(preferred_capabilities, list):
            caps = [str(x).strip() for x in preferred_capabilities if str(x).strip()]
            if caps:
                segment_profile["preferred_capabilities"] = caps

        common_intents = (
            segment_profile.get("common_intents")
            or sub_doc.get("common_intents")
            or arch_doc.get("common_intents")
            or seg_doc.get("common_intents")
            or []
        )
        if isinstance(common_intents, list):
            intents = [str(x).strip() for x in common_intents if str(x).strip()]
            if intents:
                segment_profile["common_intents"] = intents

        catalog_groups = (
            segment_profile.get("catalog_groups")
            or sub_doc.get("catalog_groups")
            or arch_doc.get("catalog_groups")
            or seg_doc.get("catalog_groups")
            or []
        )
        if isinstance(catalog_groups, list):
            groups = [str(x).strip() for x in catalog_groups if str(x).strip()]
            if groups:
                segment_profile["catalog_groups"] = groups

        operational_rules = (
            segment_profile.get("operational_rules")
            or sub_doc.get("operational_rules")
            or arch_doc.get("operational_rules")
            or seg_doc.get("operational_rules")
            or {}
        )
        if isinstance(operational_rules, dict) and operational_rules:
            segment_profile["operational_rules"] = operational_rules

        if segment_profile:
            ctx["segment_profile"] = segment_profile

        if not str(ctx.get("segment_example_line") or "").strip():
            one_liner = _pick(
                sub_doc.get("one_liner"),
                arch_doc.get("one_liner"),
                (seg_doc.get("one_liner") if use_seg else ""),
            )
            if one_liner:
                ctx["segment_example_line"] = one_liner

        if not str(ctx.get("practical_scene_from_kb") or "").strip():
            micro_scene = _pick(
                sub_doc.get("micro_scene"),
                arch_doc.get("micro_scene"),
                (seg_doc.get("micro_scene") if use_seg else ""),
            )
            if micro_scene:
                ctx["practical_scene_from_kb"] = micro_scene

        if not str(ctx.get("operational_family") or "").strip():
            family = _pick(
                sub_doc.get("conversation_mode"),
                arch_doc.get("conversation_mode"),
                seg_doc.get("conversation_mode"),
            )
            if family:
                ctx["operational_family"] = family

        return ctx
    except Exception:
        return dict(kb_context or {})



def _build_operational_contract(
    *,
    kb_snapshot: str,
    kb_context: Dict[str, Any],
    effective_segment: str,
    practical_scene_from_kb: str,
    example_line: str,
    operational_family: str,
    topic: str,
) -> Dict[str, Any]:
    """
    Constrói um contrato auditável do trilho operacional.
    Não é frase pronta; é estrutura de governança.
    """
    try:
        docs = _kb_lookup_operational_docs(
            kb_snapshot=kb_snapshot,
            effective_segment=effective_segment,
            kb_context=kb_context if isinstance(kb_context, dict) else {},
        )

        sub_doc = (docs or {}).get("subsegment_doc") or {}
        seg_doc = (docs or {}).get("segment_doc") or {}
        arch_doc = (docs or {}).get("archetype_doc") or {}
        segment_profile = (kb_context or {}).get("segment_profile") or {}
        use_seg = not bool(sub_doc)
        use_profile = not bool(sub_doc)

        def _pick_str(*vals: Any) -> str:
            for v in vals:
                s = str(v or "").strip()
                if s:
                    return s
            return ""

        archetype_id = _pick_str(
            (kb_context or {}).get("archetype_id"),
            (sub_doc or {}).get("archetype_id"),
            (arch_doc or {}).get("id"),
        ).lower()

        primary_goal = _pick_str(
            (segment_profile.get("primary_goal") if use_profile else ""),
            (sub_doc or {}).get("primary_goal"),
            (arch_doc or {}).get("primary_goal"),
            ((seg_doc or {}).get("primary_goal") if use_seg else ""),
        ).lower()

        service_noun = _pick_str(
            (segment_profile.get("service_noun") if use_profile else ""),
            (sub_doc or {}).get("service_noun"),
            (arch_doc or {}).get("service_noun"),
            ((seg_doc or {}).get("service_noun") if use_seg else ""),
        ).lower()

        handoff_format = _pick_str(
            segment_profile.get("handoff_format"),
            (sub_doc or {}).get("handoff_format"),
            (arch_doc or {}).get("handoff_format"),
            (seg_doc or {}).get("handoff_format"),
        ).lower()

        customer_noun = _pick_str(
            segment_profile.get("customer_noun"),
            segment_profile.get("customer_noun"),
            (sub_doc or {}).get("customer_noun"),
            (arch_doc or {}).get("customer_noun"),
            (seg_doc or {}).get("customer_noun"),
        ).lower()

        conversion_noun = _pick_str(
            (segment_profile.get("conversion_noun") if use_profile else ""),
            (sub_doc or {}).get("conversion_noun"),
            (arch_doc or {}).get("conversion_noun"),
            ((seg_doc or {}).get("conversion_noun") if use_seg else ""),
        ).lower()

        operational_ritual = (
            (segment_profile.get("operational_ritual") if use_profile else [])
            or (sub_doc or {}).get("operational_ritual")
            or (arch_doc or {}).get("operational_ritual")
            or ((seg_doc or {}).get("operational_ritual") if use_seg else [])
            or []
        )
        ritual_steps = [str(x).strip() for x in operational_ritual if str(x).strip()] if isinstance(operational_ritual, list) else []

        if not ritual_steps:
            ritual_steps = _derive_ritual_from_scene(
                _pick_str(
                    practical_scene_from_kb,
                    (sub_doc or {}).get("micro_scene"),
                    (arch_doc or {}).get("micro_scene"),
                    (seg_doc or {}).get("micro_scene"),
                )
            )

        preferred_capabilities = (
            (segment_profile.get("preferred_capabilities") if use_profile else [])
            or (sub_doc or {}).get("preferred_capabilities")
            or (arch_doc or {}).get("preferred_capabilities")
            or ((seg_doc or {}).get("preferred_capabilities") if use_seg else [])
            or []
        )
        capability_list = [str(x).strip() for x in preferred_capabilities if str(x).strip()] if isinstance(preferred_capabilities, list) else []

        common_intents = (
            (segment_profile.get("common_intents") if use_profile else [])
            or (sub_doc or {}).get("common_intents")
            or (arch_doc or {}).get("common_intents")
            or ((seg_doc or {}).get("common_intents") if use_seg else [])
            or []
        )
        intent_list = [str(x).strip() for x in common_intents if str(x).strip()] if isinstance(common_intents, list) else []

        catalog_groups = (
            (segment_profile.get("catalog_groups") if use_profile else [])
            or (sub_doc or {}).get("catalog_groups")
            or (arch_doc or {}).get("catalog_groups")
            or ((seg_doc or {}).get("catalog_groups") if use_seg else [])
            or []
        )
        group_list = [str(x).strip() for x in catalog_groups if str(x).strip()] if isinstance(catalog_groups, list) else []

        operational_rules = (
            (segment_profile.get("operational_rules") if use_profile else {})
            or (sub_doc or {}).get("operational_rules")
            or (arch_doc or {}).get("operational_rules")
            or ((seg_doc or {}).get("operational_rules") if use_seg else {})
            or {}
        )
        rule_map = operational_rules if isinstance(operational_rules, dict) else {}

        contract_family = _pick_str(
            operational_family,
            (kb_context or {}).get("operational_family"),
            (sub_doc or {}).get("conversation_mode"),
            (arch_doc or {}).get("conversation_mode"),
            (seg_doc or {}).get("conversation_mode"),
        ).lower()

        # exemplo/cena reais do banco
        has_example_line = bool(
            str(example_line or "").strip()
            or str((sub_doc or {}).get("one_liner") or "").strip()
            or str(((seg_doc or {}).get("one_liner") if use_seg else "") or "").strip()
            or str((arch_doc or {}).get("one_liner") or "").strip()
        )

        has_practical_scene = bool(
            str(practical_scene_from_kb or "").strip()
            or str((sub_doc or {}).get("micro_scene") or "").strip()
            or str((arch_doc or {}).get("micro_scene") or "").strip()
            or str(((seg_doc or {}).get("micro_scene") if use_seg else "") or "").strip()
        )

        allowed_next_step = "none"

        archetype_to_next = {
            "comercio_consultivo_presencial": "visita_loja",
            "comercio_catalogo_direto": "reserva_ou_compra",
            "servico_tecnico_visita": "visita",
            "servico_agendado": "agendamento",
            "servico_agendado_com_encaixe": "agendamento",
            "alimentacao_pedido": "pedido",
        }

        family_to_next = {
            "agenda": "agendamento",
            "pedidos": "pedido",
        }

        if archetype_id in archetype_to_next:
            allowed_next_step = archetype_to_next[archetype_id]
        elif contract_family in family_to_next:
            allowed_next_step = family_to_next[contract_family]

        if not customer_noun:
            customer_noun = ""

        if not conversion_noun:
            conversion_noun = ""

        return {
            "segment": str(
                (sub_doc or {}).get("id")
                or (kb_context or {}).get("effective_subsegment")
                or (kb_context or {}).get("subsegment_hint")
                or effective_segment
                or ""
            ).strip(),
            "topic": str(topic or "").strip().upper(),
            "archetype_id": archetype_id,
            "primary_goal": primary_goal,
            "service_noun": service_noun,
            "customer_noun": customer_noun,
            "conversion_noun": conversion_noun,
            "handoff_format": handoff_format,
            "operational_family": contract_family,
            "operational_ritual": ritual_steps,
            "preferred_capabilities": capability_list,
            "common_intents": intent_list,
            "catalog_groups": group_list,
            "operational_rules": rule_map,
            "has_example_line": has_example_line,
            "has_practical_scene": has_practical_scene,
            "allowed_next_step": allowed_next_step,
            "hydrated_from_docs": bool(sub_doc or seg_doc or arch_doc),
            "practical_scene_from_kb": str(practical_scene_from_kb or "").strip(),
            "example_line": str(example_line or "").strip(),
        }
    except Exception:
        return {
            "segment": str(
                (kb_context or {}).get("effective_subsegment")
                or (kb_context or {}).get("subsegment_hint")
                or effective_segment
                or ""
            ).strip(),
            "topic": str(topic or "").strip().upper(),
            "archetype_id": "",
            "primary_goal": "",
            "service_noun": "",
            "customer_noun": "",
            "conversion_noun": "",
            "handoff_format": "",
            "operational_family": str(operational_family or "").strip().lower(),
            "operational_ritual": [],
            "preferred_capabilities": [],
            "common_intents": [],
            "catalog_groups": [],
            "operational_rules": {},
            "has_example_line": bool(str(example_line or "").strip()),
            "has_practical_scene": bool(str(practical_scene_from_kb or "").strip()),
            "allowed_next_step": "none",
            "hydrated_from_docs": False,
            "practical_scene_from_kb": str(practical_scene_from_kb or "").strip(),
            "example_line": str(example_line or "").strip(),
        }



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

        practical_scene = str((contract or {}).get("practical_scene_from_kb") or "").strip()
        example_line = str((contract or {}).get("example_line") or "").strip()

        if not _is_live_operational_reply(
            text=t,
            practical_scene_from_kb="",
            example_line=example_line,
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

def _looks_like_technical_output(text: str) -> bool:
    try:
        t = str(text or "").strip()
        if not t:
            return False
        if t.startswith("PACK_"):
            return True
        if "\nPACK_" in t:
            return True
        if "segment_value_map_v1" in t or "value_packs_v1" in t:
            return True
        return False
    except Exception:
        return False


def _clean_scene_text(text: str) -> str:
    try:
        t = str(text or "").strip()
        if not t:
            return ""
        t = re.sub(r"^\s*PACK_[A-Z_]+\s*", "", t, flags=re.I).strip()
        t = re.sub(r"^\s*Na prática:\s*", "", t, flags=re.I).strip()
        t = re.sub(r"\s*\|\s*Fluxo:.*$", "", t, flags=re.I).strip()
        t = re.sub(r"\s{2,}", " ", t).strip()
        return t.rstrip(". ")
    except Exception:
        return str(text or "").strip()


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

def _expand_scene_steps(
    *,
    practical_scene_from_kb: str,
    contract: Dict[str, Any] | None = None,
) -> list[str]:
    """
    Expande a cena em micro-etapas encadeadas.
    Não cria fatos novos; apenas reaproveita:
    - practical_scene_from_kb
    - operational_ritual
    - example_line
    """
    try:
        c = dict(contract or {})
        steps: list[str] = []

        ritual = c.get("operational_ritual") or []
        if isinstance(ritual, list):
            steps.extend([re.sub(r"\s{2,}", " ", str(x).strip(" .")) for x in ritual if str(x).strip()])

        if not steps:
            steps.extend(_split_scene_steps(practical_scene_from_kb))

        example_line = str(c.get("example_line") or "").strip()
        if example_line and not steps:
            ex_steps = _split_scene_steps(example_line)
            if ex_steps:
                first_ex = ex_steps[0]
                if first_ex and first_ex.lower() not in {s.lower() for s in steps}:
                    steps.append(first_ex)

        cleaned: list[str] = []
        seen = set()
        for s in steps:
            ss = re.sub(r"\s{2,}", " ", str(s or "").strip(" ."))
            ss = _strip_scene_narrator(ss)
            if not ss:
                continue
            key = ss.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(ss)

        return cleaned[:8]
    except Exception:
        return _split_scene_steps(practical_scene_from_kb)


def _select_structured_scene_steps(
    *,
    practical_scene_from_kb: str,
    contract: Dict[str, Any] | None = None,
    model_steps: list[str] | None = None,
) -> list[str]:
    """
    Seleciona uma sequência estrutural única para a microcena.
    Prioridade:
    1) steps do modelo
    2) ritual operacional
    3) cena-base quebrada em etapas
    """
    try:
        c = dict(contract or {})
        out: list[str] = []
        seen = set()

        sources: list[list[str]] = []

        if isinstance(model_steps, list):
            sources.append([str(x).strip() for x in model_steps if str(x).strip()])

        ritual = c.get("operational_ritual") or []
        if isinstance(ritual, list):
            sources.append([str(x).strip() for x in ritual if str(x).strip()])

        base_steps = _split_scene_steps(practical_scene_from_kb)
        if base_steps:
            sources.append(base_steps)

        for group in sources:
            for raw in group:
                s = re.sub(r"\s{2,}", " ", str(raw or "").strip(" .,:;-"))
                s = _strip_scene_narrator(s)
                if not s:
                    continue
                key = re.sub(r"\W+", "", s).lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append(s)

        # garante que sempre tenta puxar do texto do usuário
        if len(out) < 3 and practical_scene_from_kb:
            extra = _split_scene_steps(practical_scene_from_kb)
            for s in extra:
                key = re.sub(r"\W+", "", s).lower()
                if key not in seen:
                    seen.add(key)
                    out.append(s)

        return out[:10]
    except Exception:
        return []


def _expand_structural_steps_from_contract_with_model(
    *,
    practical_scene_from_kb: str,
    contract: Dict[str, Any] | None = None,
    example_line: str = "",
) -> list[str]:
    """
    Expande a microcena em mais passos estruturais usando apenas
    o contrato operacional já resolvido.

    Não escreve resposta final.
    Não usa palavras-chave no código.
    Não usa frases prontas por segmento.
    """
    try:
        if _HAS_OPENAI_CLIENT and _client is None:
            return []

        c = dict(contract or {})

        base_steps = _select_structured_scene_steps(
            practical_scene_from_kb="",
            contract=c,
            model_steps=None,
        )

        if len(base_steps) < 2:
            return []

        payload = {
            "segment": str(c.get("segment") or "").strip(),
            "topic": str(c.get("topic") or "").strip().upper(),
            "archetype_id": str(c.get("archetype_id") or "").strip(),
            "primary_goal": str(c.get("primary_goal") or "").strip(),
            "service_noun": str(c.get("service_noun") or "").strip(),
            "customer_noun": str(c.get("customer_noun") or "").strip(),
            "conversion_noun": str(c.get("conversion_noun") or "").strip(),
            "handoff_format": [],
            "operational_family": str(c.get("operational_family") or "").strip(),
            "operational_ritual": c.get("operational_ritual") or [],
            "preferred_capabilities": c.get("preferred_capabilities") or [],
            "common_intents": c.get("common_intents") or [],
            "catalog_groups": c.get("catalog_groups") or [],
            "allowed_next_step": str(c.get("allowed_next_step") or "").strip(),
            "practical_scene_from_kb": str(practical_scene_from_kb or "").strip(),
            "example_line": str(example_line or c.get("example_line") or "").strip(),
            "base_steps": base_steps,
        }

        system = """
Você recebe um contrato operacional já resolvido.

Sua tarefa é expandir a microcena em passos estruturais curtos e encadeados.

Regras:
- não escrever resposta final
- não explicar
- não resumir de fora
- não usar diálogo
- não usar fala de personagem
- não inventar fatos fora do contrato
- aproveitar ritual, capabilities, handoff, goal e next_step
- cada passo deve puxar o próximo
- a sequência deve ficar mais rica e mais concreta
- depois da interação inicial, continue a cadeia operacional
- inclua consequência visível quando ela estiver implícita no contrato
- prefira continuidade operacional a resumo curto
- a sequência deve soar natural e próxima da fala do dia a dia
- evitar linguagem técnica, burocrática ou com cara de manual
- preferir passos que o lead consiga visualizar acontecendo
- não incluir emoção, sentimento ou reação do cliente
- não incluir narrador ou descrição externa
- não usar linguagem figurativa ou expressiva
- cada passo deve representar uma ação concreta do fluxo
- devolver somente JSON

Formato:
{"steps":["passo 1","passo 2","passo 3","passo 4"]}
"""

        user_prompt = json.dumps(payload, ensure_ascii=False)

        if _HAS_OPENAI_CLIENT and _client is not None:
            resp = _client.chat.completions.create(
                model=MODEL,
                temperature=0.2,
                max_tokens=260,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = str(resp.choices[0].message.content or "").strip()
        else:
            resp = openai.ChatCompletion.create(
                model=MODEL,
                temperature=0.2,
                max_tokens=260,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = str(resp["choices"][0]["message"]["content"] or "").strip()

        obj = json.loads(raw)
        steps = obj.get("steps") or []
        if not isinstance(steps, list):
            return []

        out = []
        seen = set()

        
        for raw_step in steps:
            s = re.sub(r"\s{2,}", " ", str(raw_step or "").strip(" .,:;-"))
            if not s:
                continue
            
            key = re.sub(r"\W+", "", s).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(s)

        # remove steps semanticamente repetidos
        dedup = []
        seen_roots = set()

        for s in out:
            root = re.sub(r"(robô|cliente|atendimento|fluxo)\s+", "", s.lower())
            root = re.sub(r"\W+", "", root)

            if root in seen_roots:
                continue

            seen_roots.add(root)
            dedup.append(s)

        out = dedup

        # limita expansão excessiva sem progressão
        if len(out) > 8:
            out = out[:8]

        return out
    except Exception:
        return []


def _compose_grounded_scene_with_progression(
    *,
    practical_scene_from_kb: str,
    contract: Dict[str, Any] | None = None,
    example_line: str = "",
) -> str:
    """
    Monta microcena operacional a partir de estrutura.
    Não reaproveita prosa narrada como resposta final.
    """
    try:
        c = dict(contract or {})
        stable_scene = _stabilize_scene_base(practical_scene_from_kb)
        ex = str(example_line or c.get("example_line") or "").strip()

        model_expanded_steps = _expand_structural_steps_from_contract_with_model(
            practical_scene_from_kb="",
            contract=c,
            example_line=ex,
        )

        steps = _select_structured_scene_steps(
            practical_scene_from_kb="",
            contract=c,
            model_steps=model_expanded_steps if model_expanded_steps else None,
        )

        ritual = c.get("operational_ritual") or []
        if isinstance(ritual, list):
            ritual_steps = [str(x).strip() for x in ritual if str(x).strip()]
            if len(ritual_steps) >= 3:
                steps = ritual_steps + steps

        cleaned: list[str] = []

        def _phase_signature(s: str) -> str:
            tokens = re.findall(r"\w+", s.lower())

            # pega só as 2 primeiras palavras relevantes
            core = [t for t in tokens if len(t) > 3][:2]
            return " ".join(core)

        def _semantic_key(text: str) -> str:
            tokens = re.findall(r"\w+", text.lower())
            # remove palavras comuns operacionais
            tokens = [t for t in tokens if t not in {"o", "a", "de", "do", "da", "e", "no", "na"}]
            # ordena para reduzir variação
            tokens = sorted(tokens)
            return " ".join(tokens[:6])  # limita ruído

        def _is_semantic_duplicate(a: str, b: str) -> bool:
            ta = set(re.findall(r"\w+", a.lower()))
            tb = set(re.findall(r"\w+", b.lower()))
            if not ta or not tb:
                return False
            inter = len(ta & tb)
            ratio = inter / max(len(ta), len(tb))
            return ratio >= 0.7

        def _strip_subject(s: str) -> str:
            return str(s or "").strip()

        seen = set()

        for raw in steps:
            s = re.sub(r"\s{2,}", " ", str(raw or "").strip(" .,:;-"))
            if not s:
                continue
            if ex and _is_scene_echo(s, ex):
                continue
            s = _strip_subject(s)
            key = _semantic_key(s)
            if not key or key in seen:
                continue

            is_dup = False
            for existing in cleaned:
                if _is_semantic_duplicate(s, existing):
                    is_dup = True
                    break

            if is_dup:
                continue

            seen.add(key)
            cleaned.append(s)

        phase_seen = set()

        filtered = []

        for s in cleaned:
            sig = _phase_signature(s)

            if sig in phase_seen:
                continue

            phase_seen.add(sig)
            filtered.append(s)

        cleaned = filtered

        if len(cleaned) < 4:
            return ""

        # Se o KB veio rico, preserve mais do fluxo em vez de achatar.
        hydrated = bool(c.get("hydrated_from_docs"))
        allowed_next_step = str(c.get("allowed_next_step") or "").strip().lower()

        if len(cleaned) >= 4:
            if hydrated:
                # preserva a sequência quase inteira quando a cena veio do banco
                cleaned = cleaned[:6]
            else:
                cleaned = cleaned[:6]

        # não injeta consequência automática aqui.
        # o fluxo principal deve vir só da estrutura já resolvida.

        steps_for_render = cleaned[:8]

        def _join_progression(steps: list[str]) -> str:
            if not steps:
                return ""

            out = steps[0]

            for s in steps[1:]:
                out += " → " + s

            return out

        steps_for_render = [s.strip() for s in steps_for_render if s.strip()]
        out = _render_progressive_operational_flow(steps_for_render)
        out = _sanitize_user_facing_reply(out)
        out = re.sub(r"\s{2,}", " ", str(out or "")).strip(" .")

        if not out:
            return ""

        if ex and _is_scene_echo(out, ex):
            return ""

        return out.rstrip(".") + "."
    except Exception:
        return ""

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


def _build_structural_last_resort_reply(
    *,
    practical_scene_from_kb: str,
    contract: Dict[str, Any] | None = None,
) -> str:
    """
    Último fallback estrutural.
    Não escreve prosa livre; apenas monta uma microcena
    mais rica a partir da melhor sequência disponível.
    """
    try:
        c = dict(contract or {})

        stable_scene = _stabilize_scene_base(practical_scene_from_kb)
        ex = str(c.get("example_line") or "").strip()

        model_expanded_steps = _expand_structural_steps_from_contract_with_model(
            practical_scene_from_kb="",
            contract=c,
            example_line=ex,
        )

        steps = _select_structured_scene_steps(
            practical_scene_from_kb="",
            contract=c,
            model_steps=model_expanded_steps if model_expanded_steps else None,
        )

        cleaned = []
        seen = set()

        for raw in steps:
            s = re.sub(r"\s{2,}", " ", str(raw or "").strip(" .,:;-"))
            if not s:
                continue
            if ex and _is_scene_echo(s, ex):
                continue
            key = re.sub(r"\W+", "", s).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(s)

        if len(cleaned) < 4:
            return ""

        out = _render_progressive_operational_flow(cleaned[:8])
        out = _sanitize_user_facing_reply(out)
        out = re.sub(r"\s{2,}", " ", str(out or "")).strip(" .")

        return (out + ".") if out else ""
    except Exception:
        return ""

def _generate_micro_scene_with_model(
    *,
    practical_scene_from_kb: str,
    contract: Dict[str, Any] | None = None,
) -> str:
    try:
        if _HAS_OPENAI_CLIENT and _client is None:
            return ""

        c = dict(contract or {})

        if not c.get("operational_ritual"):
            practical_scene_from_kb = (practical_scene_from_kb or "") + " Esse atendimento acontece diretamente pelo WhatsApp, com o cliente conversando com o MEI Robô."
            c["operational_ritual"] = _derive_ritual_from_scene(
                c.get("practical_scene_from_kb") or practical_scene_from_kb
            )

        base_scene = _render_progressive_operational_flow(
            _select_structured_scene_steps(
                practical_scene_from_kb="",
                contract=c,
                model_steps=None,
            )[:8]
        )

        system = """
Você recebe um contexto operacional de atendimento já resolvido.

Sua tarefa é agir como um Vendedor Consultivo vibrante, empático e especialista.
Mostre ao lead uma situação real acontecendo no dia a dia dele, em uma sequência operacional rica em detalhes técnicos.

Regras obrigatórias:

[REGRA CRÍTICA DE GERAÇÃO - O PONTO DE EQUILÍBRIO]
A microcena DEVE ser construída a partir da CENA PREFERENCIAL DO KB.
- O KB é a fonte da verdade, mas o texto dele pode estar "seco" ou em tópicos.
- Sua missão é DRAMATIZAR essa cena: foque na ação visível que o cliente final experimenta no WhatsApp. Dê vida e fluidez contando a ação operacional prática.
- FIDELIDADE ABSOLUTA: NUNCA invente etapas, botões ou funcionalidades que não estejam no KB. Embeleze a *forma* de falar, não o *conteúdo* técnico.
- O exemplo abaixo serve apenas para tom e ritmo. Se houver conflito com o KB, IGNORE o exemplo.

1. EMPATIA INICIAL: Agradeça o contato na primeira frase. Se tiver o nome do lead, use-o.
2. MICRO-CENA TÉCNICA (SHOW): Descreva o fluxo exato no WhatsApp. Fale direcionando a posse ao lead (ex: "Quando o seu cliente chama...", "o seu MEI Robô pergunta...", "na sua conta").
3. ZERO LINGUAGEM DE SISTEMA/GESTÃO: Proibido usar termos burocráticos como "registra o tema", "organiza o encaminhamento", "garante o próximo passo", "gerencia". Descreva o que o robô *fala* ou *envia* na prática.
4. ZERO ABSTRAÇÃO E RESUMOS: Proibido usar frases de marketing ("traz agilidade", "comunicação fluida").
5. FECHAMENTO SECO E DIRETO: Termine na última ação concreta do robô. NUNCA adicione uma frase de conclusão genérica no final.
6. SEM DIÁLOGOS FAKES: Não use aspas para simular falas. Descreva a AÇÃO.
7. COMPACTO E DENSO: 1 parágrafo curto (máx. ~3 a 4 frases), direto e sem explicação adicional.
8. PERGUNTAS ESTRATÉGICAS: Se o nome do lead NÃO estiver disponível, peça-o educadamente no final. Se o segmento de atuação não estiver claro, pergunte qual é o segmento dele no final.

[EXEMPLO DE TOM, DENSIDADE E ESTRUTURA ESPERADA]
"Olá [Nome], muito obrigado pelo seu contato! Quando o seu cliente chama no WhatsApp para pedir um agendamento, o seu MEI Robô pergunta o nome e qual seria o procedimento, consulta na configuração que você fez na sua conta qual o tempo de execução e propõe alternativas de horários. Seu cliente escolhe uma ou pede outras opções. Quando é escolhido um horário, é enviado ali mesmo um texto confirmando o que foi agendado. Após a confirmação, este agendamento vai para o seu e-mail e, no dia marcado às 06:30 da manhã, é enviado um resumo de todos os serviços do dia. O seu cliente também recebe um WhatsApp de lembrete 2 horas antes. Você pode consultar tudo no painel da sua conta. A propósito, qual é o seu segmento de atuação para eu te dar exemplos mais precisos?"

Use o KB como base para abastecer os detalhes da operação.
Retorne somente o texto final.
"""

        payload = {
            "segment": str(c.get("segment") or "").strip(),
            "topic": str(c.get("topic") or "").strip().upper(),
            "archetype_id": str(c.get("archetype_id") or "").strip(),
            "primary_goal": str(c.get("primary_goal") or "").strip(),
            "service_noun": str(c.get("service_noun") or "").strip(),
            "customer_noun": str(c.get("customer_noun") or "").strip(),
            "conversion_noun": str(c.get("conversion_noun") or "").strip(),
            "allowed_next_step": str(c.get("allowed_next_step") or "").strip(),
            "operational_family": str(c.get("operational_family") or "").strip(),
            "practical_scene_from_kb": str(practical_scene_from_kb or c.get("practical_scene_from_kb") or "").strip(),
            "base_scene": str(base_scene or "").strip(),
            "example_line": "" if str(practical_scene_from_kb or c.get("practical_scene_from_kb") or "").strip() else str(c.get("example_line") or "").strip(),
            "operational_ritual": c.get("operational_ritual") or [],
            "preferred_capabilities": c.get("preferred_capabilities") or [],
            "common_intents": c.get("common_intents") or [],
            "handoff_format": c.get("handoff_format") or [],
            "hydrated_from_docs": bool(c.get("hydrated_from_docs")),
            "user_context": str(c.get("user_context") or "").strip(),
        }

        user_prompt = json.dumps(payload, ensure_ascii=False)

        if _HAS_OPENAI_CLIENT and _client is not None:
            resp = _client.chat.completions.create(
                model=MODEL,
                temperature=0.40,
                max_tokens=350,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            ai_response = str(resp.choices[0].message.content or "").strip()
        else:
            resp = openai.ChatCompletion.create(
                model=MODEL,
                temperature=0.40,
                max_tokens=350,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            ai_response = str(resp["choices"][0]["message"]["content"] or "").strip()

        raw_text = str(ai_response or "").strip()
        if not raw_text:
            return base_scene

        scene_base = str(practical_scene_from_kb or "").strip()
        if len(scene_base) > 1200:
            scene_base = scene_base[:1200]

        micro_scene = str(raw_text or "").strip()

        candidate = _sanitize_user_facing_reply(micro_scene)
        candidate = _drop_explanatory_opening(candidate)
        candidate = _drop_abstract_closing(candidate)
        candidate = re.sub(r"\s{2,}", " ", candidate).strip(" .")
        if candidate:
            micro_scene = candidate

        if not micro_scene:
            rebuilt = _sanitize_user_facing_reply(base_scene)
            rebuilt = re.sub(r"\s{2,}", " ", str(rebuilt or "")).strip(" .")

            if rebuilt and _is_live_operational_reply(
                text=rebuilt,
                practical_scene_from_kb="",
                example_line=str(c.get("example_line") or "").strip(),
                contract=c,
            ):
                micro_scene = rebuilt


        try:
            sentences = [s.strip() for s in _split_sentences_pt(micro_scene) if str(s).strip()]
            if len(sentences) >= 3:
                repeated_openings = 0
                openings = []
                for s in sentences:
                    toks = [tok for tok in re.findall(r"\w+", s.lower()) if len(tok) >= 3]
                    openings.append(" ".join(toks[:2]) if toks else "")
                repeated_openings = len(openings) - len({o for o in openings if o})
                if repeated_openings >= max(2, len(sentences) - 2):
                    micro_scene = ""
        except Exception:
            pass

        density = _operational_density_score(
            text=micro_scene,
            practical_scene_from_kb="",
            example_line=str(c.get("example_line") or "").strip(),
            effective_segment=str(c.get("segment") or "").strip(),
            operational_family=str(c.get("operational_family") or "").strip(),
        )

        progress = _operational_progress_score(
            text=micro_scene,
            practical_scene_from_kb="",
            contract=c,
        )

        try:
            if micro_scene and _looks_explanatory_reply(
                text=micro_scene,
                practical_scene_from_kb="",
                example_line=str(c.get("example_line") or "").strip(),
                contract=c,
            ):
                micro_scene = ""
        except Exception:
            pass

        if not micro_scene:
            return ""

        if len(micro_scene.strip()) < 40:
            return ""

        if _looks_like_dialogue_stub(micro_scene):
            return ""

        if _looks_like_technical_output(micro_scene):
            return ""

        return micro_scene.rstrip(".") + "."
    except Exception:
        try:
            return _compose_grounded_scene_with_progression(
                practical_scene_from_kb="",
                contract=contract or {},
                example_line=str((contract or {}).get("example_line") or "").strip(),
            )
        except Exception:
            return ""
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




def _upgrade_operational_reply_with_model(
    *,
    base_text: str,
    practical_scene_from_kb: str,
    example_line: str,
    contract: Dict[str, Any] | None = None,
) -> str:
    """
    Segunda camada:
    pega um fluxo operacional já correto e reescreve contando a ação
    operacional concreta, encadeada e convincente, sem inventar nada fora
    do contrato.
    """
    try:
        c = contract or {}

        system = """
Você recebe um texto operacional correto, mas que pode estar "seco" ou robótico.

Sua tarefa é reescrever esse texto como um vendedor consultivo. O objetivo é DRAMATIZAR a atividade real contada, fazendo o lead visualizar o funcionamento exato no dia a dia dele, focando na ação visível.

Regras obrigatórias (O Ponto de Equilíbrio):
1. VALORIZE A CENA (SHOW): Transforme a sequência de ações em uma narrativa fluida e natural. Faça o lead visualizar o robô conversando com o cliente dele.
2. FIDELIDADE ABSOLUTA: NÃO invente funcionalidades, botões ou etapas que não estejam no texto base ou no `operational_ritual`. Embeleze a *forma* de falar, não o *conteúdo* técnico.
3. TOM VIBRANTE E EMPÁTICO: Agradeça o contato na primeira frase. Se tiver o nome do lead, use-o.
4. ZERO LINGUAGEM DE SISTEMA/GESTÃO: Proibido usar termos burocráticos como "registra o tema", "organiza o encaminhamento", "garante o próximo passo". Descreva a ação prática (ex: "ele avisa", "ele envia").
5. FECHAMENTO SECO E DIRETO: Termine na última ação concreta. NUNCA adicione frases de resumo ou conclusão genérica (ex: "mantendo a comunicação fluida", "facilitando a vida").
6. SEM DIÁLOGOS FAKES: Descreva a ação acontecendo, não invente falas entre aspas.
7. CONCISO, MAS ENVOLVENTE: Mantenha em 1 parágrafo (3 a 4 frases). Conecte as frases, não faça parecer uma lista de tópicos.
8. PERGUNTAS ESTRATÉGICAS: Se faltar o nome do lead ou o segmento de atuação dele, inclua um pedido educado no final da mensagem.

[EXEMPLO DE TOM E ESTRUTURA ESPERADA]
"Muito obrigado pelo contato! Quando o seu cliente chama no WhatsApp para pedir um agendamento, o seu MEI Robô pergunta o nome e qual seria o procedimento, consulta na configuração da sua conta o tempo de execução e propõe alternativas de horários. Quando o cliente escolhe, é enviado um texto confirmando o agendamento. Após a confirmação, isso vai para o seu e-mail e, no dia marcado às 06:30, é enviado um resumo dos serviços do dia. O seu cliente também recebe um lembrete 2 horas antes. Você acompanha tudo pelo painel. Me conta, qual é o seu segmento de atuação e como posso te chamar?"

Retorne somente o texto final.
"""

        user = f"""
[TEXTO BASE]
{str(base_text or '').strip()}

[BASE OPERACIONAL DO KB]
practical_scene_from_kb: {str(practical_scene_from_kb or '').strip()}
example_line: {str(example_line or '').strip()}
primary_goal: {str(c.get('primary_goal') or '').strip()}
allowed_next_step: {str(c.get('allowed_next_step') or '').strip()}
operational_ritual: {json.dumps(c.get('operational_ritual') or [], ensure_ascii=False)}
service_noun: {str(c.get('service_noun') or '').strip()}
operational_family: {str(c.get('operational_family') or '').strip()}

[INSTRUÇÃO FINAL]
Reescreva detalhando a operação no dia a dia do cliente.
Use a base para enriquecer a resposta.
"""

        resp = _call_openai_for_front(
            system=system,
            user=user,
            max_tokens=350,
            temperature=0.40,
        )

        upgraded = str(resp or "").strip()
        upgraded = _sanitize_user_facing_reply(upgraded)
        upgraded = _drop_explanatory_opening(upgraded)
        upgraded = _drop_abstract_closing(upgraded)
        upgraded = re.sub(r"\s{2,}", " ", upgraded).strip(" .")

        return upgraded

    except Exception:
        return ""
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


def _generate_consequence_with_model(contract: Dict[str, Any] | None = None) -> str:
    """
    Gera UM passo final de consequência usando apenas o contrato.
    Não escreve resposta inteira.
    Não usa template por segmento.
    """
    try:
        if _HAS_OPENAI_CLIENT and _client is None:
            return ""

        c = dict(contract or {})
        payload = {
            "primary_goal": str(c.get("primary_goal") or "").strip(),
            "conversion_noun": str(c.get("conversion_noun") or "").strip(),
            "service_noun": str(c.get("service_noun") or "").strip(),
            "customer_noun": str(c.get("customer_noun") or "").strip(),
            "allowed_next_step": str(c.get("allowed_next_step") or "").strip(),
            "handoff_format": [],
            "preferred_capabilities": c.get("preferred_capabilities") or [],
            "operational_ritual": c.get("operational_ritual") or [],
        }

        has_material = any([
            payload["primary_goal"],
            payload["conversion_noun"],
            payload["service_noun"],
            payload["customer_noun"],
            payload["allowed_next_step"],
            bool(payload["handoff_format"]),
            bool(payload["preferred_capabilities"]),
            bool(payload["operational_ritual"]),
        ])
        if not has_material:
            return ""

        system = """
Você recebe um contrato operacional.

Sua tarefa é devolve apenas UM passo final de consequência operacional.

Regras:
- uma única frase curta
- sem explicar
- sem slogan
- sem personagem
- sem diálogo
- sem linguagem de software
- não usar linguagem interna de processo
- não mencionar contrato, encerramento, conclusão formal ou validação
- não escrever como status administrativo
- deve soar como consequência natural do fluxo
- não invente fatos fora do contrato
- não repetir etapas já típicas de abertura ou meio
- preferir fechamento concreto e curto

Formato JSON:
{"consequence":"..."}
"""

        user_prompt = json.dumps(payload, ensure_ascii=False)

        if _HAS_OPENAI_CLIENT and _client is not None:
            resp = _client.chat.completions.create(
                model=MODEL,
                temperature=0.2,
                max_tokens=80,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = str(resp.choices[0].message.content or "").strip()
        else:
            resp = openai.ChatCompletion.create(
                model=MODEL,
                temperature=0.2,
                max_tokens=80,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = str(resp["choices"][0]["message"]["content"] or "").strip()

        obj = json.loads(raw)
        consequence = re.sub(r"\s{2,}", " ", str(obj.get("consequence") or "").strip(" .,:;-"))
        return consequence
    except Exception:
        return ""


def _build_contract_consequence(contract: Dict[str, Any] | None) -> str:
    """
    Consequência final vinda do contrato.
    Sem frase pronta fixa no código.
    """
    try:
        return _generate_consequence_with_model(contract or {})
    except Exception:
        return ""


def _compose_operational_reply(
    *,
    reply_text: str,
    practical_scene_from_kb: str,
    example_line: str,
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


def _build_kb_show_reply(
    *,
    kb_context: Dict[str, Any],
    practical_scene_from_kb: str,
    example_line: str,
    effective_segment: str,
    operational_family: str,
    contract: Dict[str, Any] | None = None,
) -> str:
    """
    Quando o KB ancora forte, devolve a microcena viva.
    Não cola example_line como cabeçalho explicativo.
    """
    try:
        stable_scene = _stabilize_scene_base(str(practical_scene_from_kb or "").strip())

        deterministic_scene = ""

        generated = _generate_micro_scene_with_model(
            practical_scene_from_kb=practical_scene_from_kb,
            contract=contract or {},
        ).strip()

        scene_text = str(generated or "").strip()
        if not scene_text and stable_scene:
            scene_text = _compose_grounded_scene_with_progression(
                practical_scene_from_kb=practical_scene_from_kb,
                contract=contract or {},
                example_line=str(example_line or "").strip(),
            )

        if not scene_text and stable_scene:
            scene_text = _compose_grounded_scene_with_progression(
                practical_scene_from_kb=practical_scene_from_kb,
                contract=contract or {},
                example_line=str(example_line or "").strip(),
            )

        scene_text = _sanitize_user_facing_reply(scene_text)
        scene_text = re.sub(r"\s{2,}", " ", scene_text).strip(" .")

        if scene_text and _is_show_micro_scene(
            text=scene_text,
            practical_scene_from_kb="",
            example_line=str(example_line or "").strip(),
            contract=contract or {},
        ):
            return scene_text.rstrip(".") + "."

        return _build_last_resort_operational_reply(
            practical_scene_from_kb=practical_scene_from_kb,
            example_line=str(example_line or "").strip(),
            contract=contract or {},
            clarify_q="",
        )
    except Exception:
        return ""
def _compose_practical_scene(*, kb_snapshot: str, segment_key: str, pack_id: str) -> str:
    """
    Monta o 'Na prática:' a partir de:
    - example_line do segmento (quando houver)
    - micro_scene do pack (quando houver)
    """
    try:
        ex = _kb_get_example_line(kb_snapshot, segment_key, pack_id).strip()
        ms = _kb_get_micro_scene(kb_snapshot, pack_id).strip()

        parts = []
        if ex:
            parts.append(ex.rstrip(".") + ".")
        if ms:
            ms_txt = ms
            if not ms_txt.lower().startswith("na prática:"):
                ms_txt = "Na prática: " + ms_txt
            parts.append(ms_txt.rstrip(".") + ".")

        return " ".join([p for p in parts if p]).strip()
    except Exception:
        return ""


def _merge_value_and_scene(value_line: str, practical_scene: str, question: str = "") -> str:
    """
    Resposta final:
    1) valor em 1 frase
    2) Na prática: microcena fiel ao produto
    3) pergunta útil, se existir
    """
    try:
        out = []
        v = (value_line or "").strip()
        p = (practical_scene or "").strip()
        q = (question or "").strip()

        if v:
            out.append(v.rstrip(".!?") + ".")
        if p:
            out.append(p)
        if q:
            out.append(q)
        return " ".join([x for x in out if x]).strip()
    except Exception:
        return " ".join([x for x in [(value_line or "").strip(), (practical_scene or "").strip(), (question or "").strip()] if x]).strip()


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


def _regenerate_more_concrete(
    *,
    user_text: str,
    state_summary: Dict[str, Any],
    kb_snapshot: str,
    previous_reply: str,
    previous_topic: str,
    previous_confidence: str,
    kb_seed_reply: str = "",
) -> str:
    """
    Segunda tentativa curta: a IA reescreve a própria resposta,
    mais concreta e menos publicitária.
    """
    try:
        if _HAS_OPENAI_CLIENT and _client is None:
            return ""

        system = (
            "Reescreva a resposta abaixo em português do Brasil.\n"
            "Objetivo: transformar em microcena operacional viva.\n"
            "Mantenha o mesmo sentido e não invente fatos fora da base.\n"
            "Não explique de fora.\n"
            "Não use sujeito narrador explícito no começo das frases.\n"
            "Evite construções genéricas; quando necessário, use MEI Robô como agente da ação.\n"
            "Quando envolver resposta em áudio, afirme de forma natural e contextual que o MEI Robô responde com a voz do próprio profissional/contratante, digitalizada e configurada com o seu jeito de falar.\n"
            "Use esta questão da voz digitalizada e configurada, como diferencial sempre que fizer sentido na conversa, sem depender de frase fixa.\n"
            "Comece direto no acontecimento.\n"
            "Mostre uma etapa puxando a próxima.\n"
            "Feche no último efeito operacional visível, de forma curta e direta, sem fazer perguntas ou continuar a conversa.\n"
            "Evite frases finais explicativas ou de benefício; termine na ação concluída.\n"
            "Não use slogan.\n"
            "Não termine com pergunta.\n"
            "Responda somente com o texto final."
        )

        prompt = (
            f"Mensagem do lead: {user_text}\n\n"
            f"Topic atual: {previous_topic}\n"
            f"Confidence atual: {previous_confidence}\n\n"
            f"Resposta atual:\n{previous_reply}\n\n"
            f"Base operacional do KB:\n{kb_seed_reply or ''}\n\n"
            "Reescreva como uma situação real acontecendo no WhatsApp, "
            "mostrando a sequência da ação até o resultado, sem transformar em explicação."
        )

        if _HAS_OPENAI_CLIENT and _client is not None:
            resp = _client.chat.completions.create(
                model=MODEL,
                temperature=0.35,
                max_tokens=180,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            out = str(resp.choices[0].message.content or "").strip()
        else:
            resp = openai.ChatCompletion.create(  # type: ignore
                model=MODEL,
                temperature=0.35,
                max_tokens=180,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            out = str(resp["choices"][0]["message"]["content"] or "").strip()

        return out.strip()
    except Exception:
        return ""


def _resolve_best_operational_reply(
    *,
    current_reply: str,
    current_spoken: str,
    user_text: str,
    state_summary: Dict[str, Any],
    kb_snapshot: str,
    kb_context: Dict[str, Any],
    effective_segment: str,
    operational_family: str,
    selected_pack_id: str,
    practical_scene_from_kb: str,
    example_line: str,
    question: str,
    topic: str,
    confidence: str,
    kb_anchor_strong: bool,
    operational_contract: Dict[str, Any] | None = None,
    base_operational_contract: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    """
    Resolve a melhor resposta operacional em trilho único:
    1) mantém a resposta atual se ela já estiver boa
    2) tenta regeneração forte com base no KB
    3) cai para fallback canônico do KB
    """
    try:
        current_reply = str(current_reply or "").strip()
        current_spoken = str(current_spoken or "").strip()
        contract = operational_contract if isinstance(operational_contract, dict) and operational_contract else (
            base_operational_contract if isinstance(base_operational_contract, dict) else {}
        )

        refreshed_anchor = _refresh_operational_anchor(
            kb_snapshot=kb_snapshot,
            kb_context=kb_context if isinstance(kb_context, dict) else {},
            effective_segment=effective_segment,
            selected_pack_id=selected_pack_id,
            operational_family=operational_family,
        )

        refreshed_example_line = str((refreshed_anchor or {}).get("example_line") or example_line or "").strip()
        refreshed_scene = str((refreshed_anchor or {}).get("practical_scene_from_kb") or practical_scene_from_kb or "").strip()

        if current_reply:
            current_audit = _audit_operational_reply(
                text=current_reply,
                contract=contract,
            )
            current_is_mild = _looks_explanatory_reply(
                text=current_reply,
                practical_scene_from_kb=refreshed_scene or practical_scene_from_kb,
                example_line=refreshed_example_line or example_line,
                contract=contract,
            )
            current_is_echo = _is_scene_echo(current_reply, refreshed_example_line or example_line) or _is_scene_echo(
                current_reply,
                user_text,
            )

            if (
                bool((current_audit or {}).get("ok"))
                and not current_is_mild
                and not current_is_echo
                and _is_live_operational_reply(
                    text=current_reply,
                    practical_scene_from_kb=refreshed_scene or practical_scene_from_kb,
                    example_line=refreshed_example_line or example_line,
                    contract=contract,
                )
            ):
                final_reply = current_reply
                reply_text = final_reply
                return {
                    "reply_text": reply_text,
                    "spoken_text": current_spoken or reply_text,
                    "reply_source": "front_keep_current",
                }

        if not refreshed_scene:
            ritual_steps = [
                str(x).strip()
                for x in (contract.get("operational_ritual") or [])
                if str(x).strip()
            ]
            if len(ritual_steps) >= 2:
                refreshed_scene = " → ".join(ritual_steps[:5]).strip()
            else:
                refreshed_scene = ""

        kb_seed_reply = (
            _build_kb_show_reply(
                kb_context=kb_context if isinstance(kb_context, dict) else {},
                practical_scene_from_kb="",
                example_line=refreshed_example_line,
                effective_segment=effective_segment,
                operational_family=operational_family,
                contract=contract,
            )
            or _build_kb_anchor_reply(
                practical_scene_from_kb="",
                example_line=refreshed_example_line,
                clarify_q=(question if not effective_segment else ""),
                contract=contract,
            )
        )

        best_effort = (
            _compose_grounded_scene_with_progression(
                practical_scene_from_kb=refreshed_scene or practical_scene_from_kb,
                contract=contract,
                example_line=refreshed_example_line or example_line,
            ).strip()
            or _generate_micro_scene_with_model(
                practical_scene_from_kb=refreshed_scene or practical_scene_from_kb,
                contract=contract,
            ).strip()
        )

        if best_effort:
            return {
                "reply_text": best_effort,
                "spoken_text": best_effort,
                "reply_source": "front_resolved_best_effort",
            }

    except Exception:
        final_reply = str(current_reply or "").strip()
        reply_text = final_reply
        return {
            "reply_text": reply_text,
            "spoken_text": str(current_spoken or reply_text or "").strip(),
            "reply_source": "front_resolved_error_fallback",
        }



def _infer_understanding_temperature(
    *,
    user_text: str,
    topic: str,
    confidence: str,
    needs_clarify: str,
    clarify_q: str,
    next_step: str,
) -> tuple[str, str, str, str, str]:
    """
    Calibra a 'temperatura de entendimento' sem depender 100% do LLM.
    Regras:
    - OTHER nunca sai como high.
    - Frases de ação explícita sobem para ATIVAR.
    - Ambiguidade útil vira clarify, não resposta falsa-confiante.
    """
    try:
        t = (topic or "OTHER").strip().upper()
        c = (confidence or "low").strip().lower()
        nc = (needs_clarify or "no").strip().lower()
        cq = (clarify_q or "").strip()
        ns = (next_step or "NONE").strip().upper()

        # 1) OTHER nunca deve sair como high
        if t == "OTHER" and c == "high":
            c = "medium"

        # 2) OTHER não deve virar clarify automático.
        # Em caso amplo, preferimos deixar o front tentar responder
        # em vez de abrir pergunta por reflexo.

        return t, c, nc, cq, ns
    except Exception:
        return (
            (topic or "OTHER").strip().upper() or "OTHER",
            (confidence or "low").strip().lower() or "low",
            (needs_clarify or "no").strip().lower() or "no",
            (clarify_q or "").strip(),
            (next_step or "NONE").strip().upper() or "NONE",
        )



def _should_downgrade_premature_narrow_topic(
    *,
    topic: str,
    confidence: str,
    ai_turns: int,
    effective_segment: str = "",
    operational_family: str = "",
    practical_scene_from_kb: str = "",
    example_line: str = "",
    reply_text: str = "",
    next_step: str = "",
) -> bool:
    """
    Evita que o front assuma cedo demais um trilho estreito
    (ex.: agenda/pedidos/serviços) sem ancoragem suficiente.

    Regra arquitetural:
    - não usa palavras-chave;
    - usa apenas sinais semânticos já produzidos pelo fluxo;
    - se ainda não há base concreta, preferimos ambiguidade útil
      a uma resposta específica demais.
    """
    try:
        topic = str(topic or "").strip().upper()
        confidence = str(confidence or "").strip().lower()
        seg = str(effective_segment or "").strip()
        fam = str(operational_family or "").strip()
        ps = str(practical_scene_from_kb or "").strip()
        ex = str(example_line or "").strip()
        rt = str(reply_text or "").strip()
        ns = str(next_step or "").strip().upper()

        if ai_turns > 0:
            return False

        if ns == "SEND_LINK":
            return False

        # Se já existe qualquer ancoragem concreta, não rebaixa.
        if seg or fam or ps or ex:
            return False

        # Só protege contra trilhos operacionais estreitos.
        if topic not in ("AGENDA", "PEDIDOS", "SERVICOS", "ORCAMENTO", "STATUS", "PROCESSO"):
            return False

        # Quando o próprio modelo veio muito seguro num tema estreito
        # sem nenhuma base externa, isso é sinal de chute precoce.
        if confidence == "high":
            return True

        # Também protege respostas estreitas já montadas no turno 0.
        if rt:
            return True

        return False
    except Exception:
        return False



SYSTEM_PROMPT = """
Você é o MEI Robô, um assistente automatizado que atende clientes via WhatsApp.

IMPORTANTE:
- Você não realiza atendimento presencial
- Todas as interações acontecem pelo WhatsApp

Você recebe uma estrutura operacional já resolvida (contrato do KB).

Sua tarefa é agir como um Vendedor Consultivo vibrante, empático e especialista.
Transforme essa estrutura em uma resposta conversada, mostrando o funcionamento técnico na prática, para que o lead perceba o valor através dos detalhes operacionais.

Regras de Ouro:
1. EMPATIA INICIAL: Comece a resposta com o nome do lead (se disponível) e um agradecimento natural. Se não estiver, peça o nome de forma natural no final da mensagem (deixando claro que é opcional).
2. IDENTIFIQUE O SEGMENTO: Se o segmento do lead não estiver claro, pergunte no final. Se já souber, use o KB para montar a cena.
3. MICRO-CENA TÉCNICA (SHOW): Descreva o fluxo acontecendo no WhatsApp. Fale diretamente para o lead (ex: "Quando o seu cliente chama...", "o seu MEI Robô faz..."). Inclua detalhes práticos do KB (confirmações, lembretes, painel).
4. ZERO ABSTRAÇÃO: Não use frases feitas como "ganhe tempo" ou "facilita sua vida". O convencimento deve vir da riqueza de detalhes do processo.
5. SEM DIÁLOGOS FAKES: Não use aspas para simular falas. Descreva a ação.
6. COMPACTO E DENSO: 1 parágrafo curto (máx. ~3 a 4 frases), direto e sem explicação adicional.
7. PERGUNTAS: Faça perguntas APENAS para descobrir o nome ou o segmento (se faltarem).
8. SE O CLIENTE QUER ASSINAR/COMPRAR (ATIVAR): Apenas agradeça, diga o nome dele e confirme o envio do link. NÃO conte história, NÃO gere microcena. Seja direto.

IMPORTANTE: Responda SEMPRE em formato JSON com a seguinte estrutura:
{
  "replyText": "sua resposta aqui",
  "understanding": {
    "topic": "ATIVAR se o cliente quiser comprar/assinar, senão OTHER",
    "confidence": "high, medium ou low"
  },
  "nextStep": "SEND_LINK se o cliente pediu o link/assinatura, senão NONE"
}
"""




FREE_MODE_APPEND_PROMPT = """
MODO IA TOTAL:
- Encantar e demonstrar valor rápido
- Mostrar na prática
- Conversar de forma natural
"""


def _truncate(s: str, max_chars: int) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    return s[:max_chars].rstrip()

def _compact_kb_snapshot(s: str) -> str:
    """Reduz tokens sem perder conteúdo: remove excesso de whitespace."""
    import re  # safety: evita NameError se alguém mexer imports
    s = (s or "").strip()
    if not s:
        return ""
    # colapsa espaços e linhas em branco
    s = re.sub(r"[\t ]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    # remove separadores muito longos (----/====)
    s = re.sub(r"(?m)^[=\-]{6,}$", "", s).strip()
    return s


def _call_openai_for_front(*, system: str, user: str, temperature: float = 0.2, max_tokens: int = 180) -> str:
    try:
        if _HAS_OPENAI_CLIENT and _client is None:
            return ""

        if _HAS_OPENAI_CLIENT and _client is not None:
            resp = _client.chat.completions.create(
                model=MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return str(resp.choices[0].message.content or "").strip()

        resp = openai.ChatCompletion.create(
            model=MODEL,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return str(resp["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return ""


def _prepare_kb_snapshot_buffers(kb_snapshot: str) -> tuple[str, str, bool]:
    """
    Se o snapshot vier em JSON válido (packs_v1), preserva a cópia completa
    para lookup/runtime interno e cria uma cópia curta só para o prompt.

    Isso evita quebrar o lookup do banco novo sem inflar tokens no modelo.
    """
    try:
        raw = str(kb_snapshot or "").strip()
        if not raw:
            return "", "", False

        json_ok = False
        if raw.startswith("{") or raw.startswith("["):
            try:
                parsed = json.loads(raw)
                json_ok = isinstance(parsed, (dict, list))
            except Exception:
                json_ok = False

        if json_ok:
            runtime_snapshot = raw[:FRONT_KB_MAX_CHARS_PACKS_V1].rstrip()
            prompt_snapshot = _compact_kb_snapshot(_truncate(raw, FRONT_KB_MAX_CHARS))
            return runtime_snapshot, prompt_snapshot, True

        runtime_snapshot = _truncate(raw, FRONT_KB_MAX_CHARS)
        prompt_snapshot = _compact_kb_snapshot(runtime_snapshot)
        return runtime_snapshot, prompt_snapshot, False
    except Exception:
        raw = _truncate(str(kb_snapshot or ""), FRONT_KB_MAX_CHARS)
        return raw, _compact_kb_snapshot(raw), False




def _try_parse_kb_json(kb_snapshot: str) -> Dict[str, Any] | None:
    try:
        raw = str(kb_snapshot or "").strip()
        if raw and (raw.startswith("{") or raw.startswith("[")):
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        return None
    return None



def _kb_get_process_sla_text(kb: Dict[str, Any] | None, kb_snapshot_raw: str) -> str:
    """Retorna o texto de SLA/ativação vindo do KB (sem inventar)."""
    try:
        if isinstance(kb, dict):
            pf = kb.get("process_facts")
            if isinstance(pf, dict):
                t = str(pf.get("process_sla_text") or "").strip()
                if t:
                    return t
                t = str(pf.get("sla_setup") or "").strip()
                if t:
                    return t
            # fallback: algumas KBs guardam em outro nível
            ap = kb.get("answer_playbook_v1")
            if isinstance(ap, dict):
                pf2 = ap.get("process_facts")
                if isinstance(pf2, dict):
                    t = str(pf2.get("process_sla_text") or "").strip()
                    if t:
                        return t
                    t = str(pf2.get("sla_setup") or "").strip()
                    if t:
                        return t
    except Exception:
        pass

    # Heurística mínima: se o snapshot textual contiver um SLA explícito, preserva.
    try:
        s = (kb_snapshot_raw or "").lower()
        if "7 dias úteis" in s or "7 dias uteis" in s:
            return "até 7 dias úteis"
    except Exception:
        pass

    return ""


def _sanitize_unverified_time_claims(reply: str, kb: Dict[str, Any] | None, kb_snapshot_raw: str) -> str:
    """Bloqueia promessas de tempo não verificadas (minutos/horas/dias) e troca por SLA do KB ou linguagem segura."""
    import re

    r = str(reply or "").strip()
    if not r:
        return ""

    # Se o KB já contém o trecho de tempo usado, não mexe.
    kb_low = (kb_snapshot_raw or "").lower()
    r_low = r.lower()
    sla = _kb_get_process_sla_text(kb, kb_snapshot_raw)

    time_markers = (
        "minuto", "minutos", "hora", "horas", "hoje", "amanhã", "semana", "semanas",
        "em poucos minutos", "alguns minutos", "leva poucos minutos", "leva alguns minutos",
    )
    has_time = any(m in r_low for m in time_markers) or bool(re.search(r"\b\d+\s*(min|minutos|h|hora|horas|dia|dias|semana|semanas)\b", r_low))
    if not has_time:
        return r

    # Se a frase de tempo aparece no KB (mesma substring), aceita.
    try:
        # pega janelas pequenas para checar presença no KB
        m = re.search(r"(leva\s+[^\.\!\?]{0,40})", r_low)
        if m and m.group(1) and m.group(1) in kb_low:
            return r
    except Exception:
        pass

    # Troca por SLA do KB quando existir; senão, linguagem segura sem número.
    safe = (sla.strip() if sla else "")

    # Remove sentenças que prometem minutos/horas e injeta safe.
    parts = re.split(r"(?<=[\.\!\?])\s+", r)
    kept: list[str] = []
    removed = False
    for p in parts:
        pl = p.lower()
        if any(m in pl for m in time_markers) or re.search(r"\b\d+\s*(min|minutos|h|hora|horas|dia|dias|semana|semanas)\b", pl):
            removed = True
            continue
        kept.append(p)
    r2 = " ".join([k for k in kept if k.strip()]).strip()
    if removed:
        # Só injeta texto se houver SLA canônico real no KB.
        # Sem SLA explícito, apenas remove a promessa temporal.
        if safe:
            if r2:
                dot = r2.find(".")
                if 0 < dot < 220:
                    r2 = r2[: dot + 1] + f" {safe}." + r2[dot + 1 :]
                else:
                    r2 = f"{safe}. {r2}".strip()
            else:
                r2 = f"{safe}.".strip()
    return r2.strip()


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


def _upgrade_weak_question(reply: str, topic: str, intent: str) -> str:
    # IA TOTAL: não trocar pergunta da IA por CTA pronta.
    return str(reply or "").strip()

def _pick_pack_for_intent(intent: str, pack_id: str = "") -> str:
    p = (pack_id or "").strip().upper()
    if p:
        return p
    i = (intent or "").strip().upper()
    if i in ("AGENDA",):
        return "PACK_A_AGENDA"
    if i in ("SERVICOS", "WHAT_IS", "PRECO", "TRIAL"):
        return "PACK_B_SERVICOS"
    if i in ("PEDIDOS", "ORCAMENTO"):
        return "PACK_C_PEDIDOS"
    if i in ("STATUS", "PROCESSO"):
        return "PACK_D_STATUS"
    return ""


def _segment_example_line(kb: Dict[str, Any], segment_key: str, pack_id: str) -> str:
    try:
        seg = (segment_key or "").strip().lower()
        if not seg:
            return ""
        kb_sub = (kb or {}).get("kb_subsegments_v1") or {}
        if isinstance(kb_sub, dict):
            d = kb_sub.get(seg) or {}
            if isinstance(d, dict):
                ex = str(d.get("one_liner") or "").strip()
                if ex:
                    return ex
        kb_seg = (kb or {}).get("kb_segments_v1") or {}
        if isinstance(kb_seg, dict):
            d = kb_seg.get(seg) or {}
            if isinstance(d, dict):
                ex = str(d.get("one_liner") or "").strip()
                if ex:
                    return ex
        svm = (kb or {}).get("segment_value_map_v1") or {}
        seg_obj = svm.get(seg) or svm.get(seg.lower()) or {}
        tokens = (seg_obj.get("tokens") or {})
        pack_obj = tokens.get((pack_id or "").strip().upper()) or {}
        ex = str(pack_obj.get("example_line") or "").strip()
        return ex
    except Exception:
        return ""



def _pack_practical_add(pack_id: str) -> str:
    """Mantido por compatibilidade; microcena deve vir preferencialmente do KB."""
    return ""

def _segment_micro_flow(kb: Dict[str, Any], segment_key: str, intent: str, pack_id: str) -> str:
    """Gera um 'SHOW' curto: 1 frase de exemplo + 1 frase de micro-fluxo (sem tutorial)."""
    try:
        ex = _segment_example_line(kb, segment_key, pack_id)
        if not ex:
            return ""        
        add = _pack_practical_add(pack_id)
        if add:
            return (ex.rstrip(".") + ". " + add).strip()
        return ex
    except Exception:
        return ""

# -----------------------------
# Função principal
# -----------------------------
def handle(*, user_text: str, state_summary: Dict[str, Any], kb_snapshot: str = "") -> Dict[str, Any]:
    """
    Entrada:
      - user_text: texto do usuário
      - state_summary: { ai_turns, is_lead, name_hint }

    Saída (contrato fixo):
      {
        replyText: str,
        understanding: { topic, confidence },
        nextStep: "NONE" | "SEND_LINK",
        shouldEnd: bool,
        nameUse: "none|greet|empathy|clarify",
        prefersText: bool
      }
    """

    ai_turns = int(state_summary.get("ai_turns") or 0)

    # ----------------------------------------------------------
    # BLINDAGEM ESTRUTURAL DO FLUXO
    # Nunca deixar parse/fail-safe depender de variável não inicializada.
    # ----------------------------------------------------------
    data: Dict[str, Any] = {}
    understanding: Dict[str, Any] = {}
    decider: Dict[str, Any] | None = None
    token_usage: Dict[str, Any] = {}

    topic = "OTHER"
    intent = "OTHER"
    confidence = "low"
    needs_clarify = "no"
    clarify_q = ""
    next_step = "NONE"
    should_end = False
    name_use = "none"
    reply_text = ""
    spoken_text = ""
    _final_candidate = None

    last_intent = str(state_summary.get("last_intent") or "").strip().upper()
    last_user_goal = str(state_summary.get("last_user_goal") or "").strip()
    name_hint = str(state_summary.get("name_hint") or "").strip()
    segment_hint = str(state_summary.get("segment_hint") or "").strip()
    is_lead = bool(state_summary.get("is_lead") or False)
    kb_snapshot, kb_compact, kb_snapshot_json_ok = _prepare_kb_snapshot_buffers(kb_snapshot)

    try:
        logging.info(
            "[CONVERSATIONAL_FRONT][KB_SNAPSHOT_IN] runtime_chars=%s prompt_chars=%s json_ok=%s",
            len(kb_snapshot or ""),
            len(kb_compact or ""),
            kb_snapshot_json_ok,
        )
    except Exception:
        pass

    # Sinal simples para o modelo: já sabemos o nome?
    has_name = bool(name_hint)

    # fast-path comercial removido:
    # intenção de ativação/link deve nascer do entendimento da IA
    # e/ou de sinais estruturados do KB/contexto, nunca de regex local.


    # kb_compact já foi preparado acima:
    # - snapshot completo para lookup/runtime
    # - snapshot curto para o prompt

    # Seletor de fatos do KB (menos tokens, menos "chute")
    kb_context: Dict[str, Any] = {}
    try:
        if FRONT_KB_RESOLVER_ENABLED and build_kb_context is not None:
            inferred_segment_for_kb = ""
            try:
                inferred_segment_for_kb = _infer_segment_from_text(user_text, kb_snapshot)
            except Exception:
                inferred_segment_for_kb = ""

            operational_family_hint = ""
            try:
                operational_family_hint = _infer_operational_family(user_text, segment_hint or inferred_segment_for_kb)
            except Exception:
                operational_family_hint = ""

            try:
                kb_context = build_kb_context(
                    kb_snapshot=kb_snapshot,
                    user_text=user_text,
                    last_intent=(last_intent or ""),
                    segment_hint=(segment_hint or inferred_segment_for_kb or ""),
                    operational_family_hint=operational_family_hint,
                    topic_hint=(last_intent or ""),
                )
            except TypeError:
                # compat com assinatura antiga
                kb_context = build_kb_context(
                    kb_snapshot=kb_snapshot,
                    user_text=user_text,
                    last_intent=(last_intent or ""),
                )
    except Exception:
        kb_context = {}

    operational_family = ""
    try:
        operational_family = str((kb_context or {}).get("operational_family", "") or "")
    except Exception:
        operational_family = ""

    micro_scene = ""

    # ----------------------------------------------------------
    # ✅ ARQUITETURA: Objeção de produto tem prioridade máxima
    # (TRIAL/GRÁTIS nunca pode ser engolido por PREÇO)
    # ----------------------------------------------------------
    force_trial = False
    try:
        if isinstance(kb_context, dict):
            ih = str(kb_context.get("intent_hint") or "").strip().upper()
            ob = str(kb_context.get("objection") or "").strip().upper()
            it = bool(kb_context.get("is_trial") is True)
            force_trial = it or (ih == "TRIAL") or (ob == "TRIAL")
    except Exception:
        force_trial = False

    # Lead hint opcional: evita o modelo chutar profissão quando não sabemos segmento
    try:
        if segment_hint and isinstance(kb_context, dict):
            kb_context["segment_hint"] = segment_hint
    except Exception:
        pass

    inferred_segment = ""
    try:
        if not segment_hint:
            inferred_segment = _infer_segment_from_text(user_text, kb_snapshot)
    except Exception:
        inferred_segment = ""

    kb_segment_hint = ""
    try:
        if isinstance(kb_context, dict):
            kb_segment_hint = str(
                kb_context.get("subsegment_hint")
                or kb_context.get("segment_hint")
                or ""
            ).strip()
    except Exception:
        kb_segment_hint = ""

    effective_segment = (
        str((kb_context or {}).get("subsegment_hint") or "").strip()
        or str(segment_hint or "").strip()
        or str(kb_segment_hint or "").strip()
        or str(inferred_segment or "").strip()
    )

    # se ainda estivermos num macro conhecido, tenta promover para subsegmento real
    try:
        if effective_segment and "__" not in effective_segment:
            promoted_segment = _infer_segment_from_docs(
                user_text=user_text,
                kb_snapshot=kb_snapshot,
                kb_context=kb_context if isinstance(kb_context, dict) else {},
            )
            if promoted_segment and "__" in str(promoted_segment):
                effective_segment = str(promoted_segment).strip()
    except Exception:
        pass

    # ----------------------------------------------------------
    # SEGUNDA INFERÊNCIA DE SEGMENTO
    # Quando a primeira inferência vier fraca, tenta casar o texto
    # com as chaves reais do KB antes da hidratação principal.
    # ----------------------------------------------------------
    try:
        inferred_from_docs = _infer_segment_from_docs(
            user_text=user_text,
            kb_snapshot=kb_snapshot,
            kb_context=kb_context if isinstance(kb_context, dict) else {},
        )
        if inferred_from_docs:
            inferred_from_docs = str(inferred_from_docs).strip()

            # sempre promove subsegmento sobre macro
            if "__" in inferred_from_docs:
                effective_segment = inferred_from_docs
            elif not effective_segment:
                effective_segment = inferred_from_docs
    except Exception:
        pass

    # ----------------------------------------------------------
    # HIDRATAÇÃO REAL DO CONTEXTO OPERACIONAL
    # Usa os docs reais do banco para preencher lacunas antes de
    # qualquer refresh de âncora ou montagem de contrato.
    # ----------------------------------------------------------
    try:
        real_kb_docs = _kb_lookup_operational_docs(
            kb_snapshot=kb_snapshot,
            effective_segment=effective_segment,
            kb_context=kb_context if isinstance(kb_context, dict) else {},
        )
        kb_context = _merge_real_kb_operational_context(
            kb_context=kb_context if isinstance(kb_context, dict) else {},
            docs=real_kb_docs,
        )
        logging.info(
            "[CONVERSATIONAL_FRONT][KB_CTX_ENRICH] seg=%s archetype=%s segment_id=%s example=%s scene=%s family=%s",
            str(effective_segment or "").strip(),
            str((kb_context or {}).get("archetype_id") or "").strip(),
            str((kb_context or {}).get("segment_id") or "").strip(),
            bool(str((kb_context or {}).get("segment_example_line") or "").strip()),
            bool(str((kb_context or {}).get("practical_scene_from_kb") or "").strip()),
            str((kb_context or {}).get("operational_family") or "").strip(),
        )
    except Exception:
        pass

    # ----------------------------------------------------------
    # RE-HIDRATAÇÃO ASSISTIDA
    # Se ainda veio magro, tenta mais uma vez com o melhor segmento
    # inferido a partir do texto + snapshot real.
    # ----------------------------------------------------------
    try:
        docs_hydrated = bool(
            isinstance(real_kb_docs, dict)
            and (
                real_kb_docs.get("subsegment_doc")
                or real_kb_docs.get("segment_doc")
                or real_kb_docs.get("archetype_doc")
            )
        )

        if not docs_hydrated:
            reinforced_segment = _infer_segment_from_docs(
                user_text=user_text,
                kb_snapshot=kb_snapshot,
                kb_context=kb_context if isinstance(kb_context, dict) else {},
            )

            if reinforced_segment and reinforced_segment != effective_segment:
                effective_segment = str(reinforced_segment).strip()

                real_kb_docs = _kb_lookup_operational_docs(
                    kb_snapshot=kb_snapshot,
                    effective_segment=effective_segment,
                    kb_context=kb_context if isinstance(kb_context, dict) else {},
                )
                kb_context = _merge_real_kb_operational_context(
                    kb_context=kb_context if isinstance(kb_context, dict) else {},
                    docs=real_kb_docs,
                )
    except Exception:
        pass

    try:
        if effective_segment and isinstance(kb_context, dict):
            if "__" in str(effective_segment):
                kb_context["subsegment_hint"] = str(effective_segment).strip()
            else:
                kb_context["segment_hint"] = str(effective_segment).strip()
            kb_context["needs_segment_discovery"] = False
    except Exception:
        pass

    try:
        if (
            not str((kb_context or {}).get("discovery_question_hint") or "").strip()
            and not practical_scene_from_kb
            and not example_line
            and not operational_family
        ):
            kb_context["discovery_question_hint"] = ""
    except Exception:
        pass

    question = ""
    preferred_discovery_question = str(
        (kb_context or {}).get("discovery_question_hint")
        or (kb_context or {}).get("segment_question_preferred")
        or ""
    ).strip()
    if not effective_segment and preferred_discovery_question:
        question = preferred_discovery_question

    free_mode = bool(is_lead and ai_turns <= FRONT_FREE_MODE_MAX_TURNS)
    try:
        if isinstance(kb_context, dict):
            kb_context["free_mode"] = free_mode
    except Exception:
        pass

    kb_section = ""
    try:
        if kb_context:
            kb_section = "KB Context (selected facts):\n" + json.dumps(kb_context, ensure_ascii=False)
    except Exception:
        kb_section = ""

    selected_pack_id = str((kb_context or {}).get("pack_id") or "").strip().upper()
    micro_scene = str((kb_context or {}).get("pack_micro_scene") or "").strip()
    practical_scene_from_kb = str((kb_context or {}).get("practical_scene_from_kb") or "").strip()
    example_line = str((kb_context or {}).get("segment_example_line") or "").strip()
    if selected_pack_id and not micro_scene:
        micro_scene = _kb_get_micro_scene(kb_snapshot, selected_pack_id)
    if selected_pack_id and not example_line:
        example_line = _kb_get_example_line(kb_snapshot, effective_segment, selected_pack_id)
    if effective_segment and not practical_scene_from_kb:
        practical_scene_from_kb = _kb_get_segment_scene(kb_snapshot, effective_segment)
    if not practical_scene_from_kb and micro_scene:
        practical_scene_from_kb = micro_scene

    # ----------------------------------------------------------
    # REFRESH DA ÂNCORA OPERACIONAL
    # Antes da resposta final, revisitamos o banco para reforçar
    # a melhor cena e o melhor exemplo disponível.
    # ----------------------------------------------------------
    refreshed_anchor = _refresh_operational_anchor(
        kb_snapshot=kb_snapshot,
        kb_context=kb_context if isinstance(kb_context, dict) else {},
        effective_segment=effective_segment,
        selected_pack_id=selected_pack_id,
        operational_family=operational_family,
    )
    example_line = str((refreshed_anchor or {}).get("example_line") or example_line or "").strip()
    practical_scene_from_kb = str((refreshed_anchor or {}).get("practical_scene_from_kb") or practical_scene_from_kb or "").strip()
    operational_family = str((refreshed_anchor or {}).get("operational_family") or operational_family or "").strip()

    # o example_line só nasce de cena real do KB; nunca do relato do usuário
    if not example_line and practical_scene_from_kb and not _is_scene_echo(practical_scene_from_kb, user_text):
        derived_steps = _split_scene_steps(practical_scene_from_kb)
        if len(derived_steps) >= 2:
            example_line = str(derived_steps[0] or "").strip()

    # ----------------------------------------------------------
    # CONTRATO OPERACIONAL BASE (consolidado cedo)
    # A partir daqui, toda microcena/rebuild/regeneração deve usar
    # a mesma base operacional consolidada.
    # ----------------------------------------------------------
    base_operational_contract = _build_operational_contract(
        kb_snapshot=kb_snapshot,
        kb_context=kb_context if isinstance(kb_context, dict) else {},
        effective_segment=effective_segment,
        practical_scene_from_kb=practical_scene_from_kb,
        example_line=example_line,
        operational_family=operational_family,
        topic="OTHER",
    )

    # ----------------------------------------------------------
    # PRIORIDADE DO KB (nova arquitetura)
    # Se já temos material suficiente do banco, usamos isso
    # como base da resposta e deixamos a IA apenas adaptar.
    # ----------------------------------------------------------
    kb_anchor_available = bool(
        practical_scene_from_kb
        or example_line
        or operational_family
        or selected_pack_id
    )
    kb_anchor_strong = False

    system_prompt = SYSTEM_PROMPT
    if free_mode:
        system_prompt += "\n" + FREE_MODE_APPEND_PROMPT + "\n"

        # ----------------------------------------------------------
        # RACIOCÍNIO SITUACIONAL (faz a IA pensar na conversa real)
        # ----------------------------------------------------------
        system_prompt += (
            "\nAntes de responder, entenda a situação real do cliente.\n"
            "Visualize a conversa acontecendo no WhatsApp.\n"
            "Mostre o fluxo acontecendo em sequência real\n"
            "Evite explicar software; descreva a cena prática acontecendo.\n"
        )
    family_hint = _build_free_mode_family_hint(user_text, effective_segment)
    scene_hint_block = _build_scene_hint_block(
        family_hint=family_hint,
        micro_scene=micro_scene,
        example_line=example_line,
        practical_scene_from_kb="",
    )
    if scene_hint_block:
        system_prompt += "\n" + scene_hint_block + "\n"

    user_scene_block = _build_user_scene_block(
        practical_scene_from_kb="",
        example_line=example_line,
        kb_section=kb_section,
        kb_compact=kb_compact,
    )

    try:
        if not operational_family:
            operational_family = str(
                _infer_operational_family(user_text, effective_segment)
                or ""
            ).strip()
    except Exception:
        operational_family = operational_family or ""

    kb_anchor_available = bool(
        practical_scene_from_kb
        or example_line
        or operational_family
        or selected_pack_id
    )
    real_scene_for_anchor = practical_scene_from_kb if not _is_scene_echo(practical_scene_from_kb, user_text) else ""
    real_example_for_anchor = example_line if not _is_scene_echo(example_line, user_text) else ""

    kb_anchor_strong = _has_strong_kb_anchor(
        kb_context=kb_context if isinstance(kb_context, dict) else {},
        effective_segment=effective_segment,
        operational_family=operational_family,
        practical_scene_from_kb=real_scene_for_anchor,
        example_line=real_example_for_anchor,
        selected_pack_id=selected_pack_id,
    )

    kb_show_reply_seed = ""
    kb_forced_topic = ""
    if not practical_scene_from_kb:
        practical_scene_from_kb = ""
    if free_mode and kb_anchor_strong and effective_segment:
        kb_forced_topic = _preferred_topic_from_kb(
            kb_context=kb_context if isinstance(kb_context, dict) else {},
            current_topic="OTHER",
        )
        if kb_forced_topic not in TOPICS or kb_forced_topic in ("OTHER", "WHAT_IS"):
            archetype_id = str((kb_context or {}).get("archetype_id") or "").strip().lower()
            if archetype_id in ("servico_tecnico_visita", "atendimento_profissional_triagem"):
                kb_forced_topic = "PROCESSO"
            elif archetype_id in ("servico_agendado", "servico_agendado_com_encaixe"):
                kb_forced_topic = "AGENDA"
            elif archetype_id == "alimentacao_pedido":
                kb_forced_topic = "PEDIDOS"
            else:
                kb_forced_topic = "SERVICOS"

        kb_show_reply_seed = _build_kb_show_reply(
            kb_context=kb_context if isinstance(kb_context, dict) else {},
            practical_scene_from_kb="",
            example_line=example_line,
            effective_segment=effective_segment,
            operational_family=operational_family,
            contract=base_operational_contract if 'base_operational_contract' in locals() else {},
        )

        try:
            if kb_forced_topic and isinstance(kb_context, dict):
                kb_context["topic_hint_from_kb"] = kb_forced_topic
        except Exception:
            pass

    user_payload = (
        f"[MENSAGEM DO USUÁRIO]\n{user_text}\n\n"
        f"[ESTADO]\n"
        f"turno={ai_turns}\n"
        f"is_lead={'true' if is_lead else 'false'}\n"
        f"has_name={'true' if has_name else 'false'}\n"
        + (f"name_hint={name_hint}\n" if has_name else "")
        + (f"segment_hint={effective_segment}\n" if effective_segment else "")
        + (f"operational_family={operational_family}\n" if operational_family else "")
        + f"last_intent={last_intent or 'NONE'}\n"
        + f"last_user_goal={last_user_goal or 'NONE'}\n\n"
        + (
            "[BASE OPERACIONAL DO KB]\n"
            f"practical_scene_from_kb: {str(practical_scene_from_kb or '').strip()}\n"
            f"example_line: {str(example_line or '').strip()}\n"
            f"primary_goal: {str((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get('primary_goal') or '').strip()}\n"
            f"allowed_next_step: {str((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get('allowed_next_step') or '').strip()}\n"
            f"operational_ritual: {json.dumps((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get('operational_ritual') or [], ensure_ascii=False)}\n\n"
            if (
                str(practical_scene_from_kb or '').strip()
                or str(example_line or '').strip()
                or ((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get('primary_goal'))
                or ((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get('allowed_next_step'))
                or ((operational_contract if 'operational_contract' in locals() else base_operational_contract if 'base_operational_contract' in locals() else {}).get('operational_ritual'))
            )
            else ""
        )
        + (user_scene_block + "\n\n" if user_scene_block else "")
    )

    # ----------------------------------------------------------
    # Se o KB já trouxe cena operacional, reforçamos isso
    # para evitar improviso genérico do modelo.
    # ----------------------------------------------------------
    if kb_anchor_available:
        system_prompt += (
            "\n\nREGRA ADICIONAL:\n"
            "Se o KB trouxer archetype, ritual, capabilities, cena ou exemplo, trate isso como a melhor representação operacional do caso neste turno.\n"
            "Você continua soberano para redigir com naturalidade.\n"
            "Evite trocar por outro tipo de fluxo quando a ancoragem do KB estiver clara.\n"
            "Se houver subsegmento claro, trate-o como confirmado neste turno.\n"
            "Se houver archetype consultivo, preserve visita ou especialista quando isso vier do KB.\n"
            "Se houver archetype de visita técnica, preserve triagem mínima antes de confirmar a visita.\n"
            "Mostre a conversa acontecendo.\n"
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_payload},
    ]

    try:
        # ----------------------------------------------------------
        # Chamada ao modelo (compat: SDK novo e antigo)
        # ----------------------------------------------------------
        if _HAS_OPENAI_CLIENT and _client is not None:
            req_kwargs = {
                "model": MODEL,
                "temperature": TEMPERATURE,
                "max_tokens": FRONT_ANSWER_MAX_TOKENS,
                "messages": messages,
            }

            # Só força JSON fora do free_mode.
            # Em free_mode a IA pode responder em texto livre.
            if not free_mode:
                req_kwargs["response_format"] = {"type": "json_object"}

            resp = _client.chat.completions.create(**req_kwargs)
            raw = str(resp.choices[0].message.content or "").strip()
            # usage no SDK novo
            token_usage = {}
            try:
                u = getattr(resp, "usage", None)
                if u:
                    token_usage = {
                        "input_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
                        "output_tokens": int(getattr(u, "completion_tokens", 0) or 0),
                        "total_tokens": int(getattr(u, "total_tokens", 0) or 0),
                    }
            except Exception:
                token_usage = {}
        else:
            # SDK antigo (openai<1.x)
            resp = openai.ChatCompletion.create(  # type: ignore
                model=MODEL,
                temperature=TEMPERATURE,
                max_tokens=FRONT_ANSWER_MAX_TOKENS,
                messages=messages,
            )
            raw = (resp["choices"][0]["message"]["content"] or "").strip()
            # usage no SDK antigo
            token_usage = {}
            try:
                u = resp.get("usage") or {}
                token_usage = {
                    "input_tokens": int(u.get("prompt_tokens") or 0),
                    "output_tokens": int(u.get("completion_tokens") or 0),
                    "total_tokens": int(u.get("total_tokens") or 0),
                }
            except Exception:
                token_usage = {}


        # raw já foi preenchido acima (compat)

        # ----------------------------------------------------------
        # FREE MODE: a IA pode responder em texto livre.
        # Só tentamos JSON se houver cara de objeto JSON.
        # ----------------------------------------------------------
        raw_json = raw
        cleaned = str(raw or "").strip()

        if free_mode:
            looks_like_json = cleaned.startswith("{") or cleaned.startswith("```json") or cleaned.startswith("```")

            if not looks_like_json:
                preferred_topic_hint = _preferred_topic_from_kb(
                    kb_context=kb_context if isinstance(kb_context, dict) else {},
                    current_topic="OTHER",
                )
                if kb_forced_topic and kb_forced_topic in TOPICS:
                    preferred_topic_hint = kb_forced_topic

                free_text_payload = _parse_free_mode_text_response(
                    cleaned,
                    topic_hint=preferred_topic_hint,
                    confidence_hint=("high" if kb_anchor_strong else "medium"),
                )
                if free_text_payload and str(free_text_payload.get("replyText") or "").strip():
                    data = free_text_payload
                else:
                    raw_text_candidate = _sanitize_user_facing_reply(cleaned)
                    raw_text_candidate = re.sub(r"\s{2,}", " ", raw_text_candidate).strip()

                    if raw_text_candidate:
                        data = {
                            "replyText": raw_text_candidate,
                            "spokenText": raw_text_candidate,
                            "understanding": {
                                "topic": preferred_topic_hint if preferred_topic_hint in TOPICS else "OTHER",
                                "confidence": ("high" if kb_anchor_strong else "medium"),
                            },
                            "nextStep": "NONE",
                            "shouldEnd": False,
                            "nameUse": "none",
                            "prefersText": False,
                            "replySource": "front_raw_fallback",
                        }
                    else:
                        data = {}
            else:
                try:
                    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.I)
                    cleaned = re.sub(r"^```\s*", "", cleaned, flags=re.I)
                    cleaned = re.sub(r"\s*```$", "", cleaned)

                    m = re.search(r"\{[\s\S]*\}", cleaned, flags=re.DOTALL)
                    if m:
                        raw_json = m.group(0)
                    else:
                        raw_json = cleaned

                    data = json.loads(raw_json)
                except Exception:
                    repaired = re.sub(r",(\s*[}\]])", r"\1", raw_json)
                    try:
                        data = json.loads(repaired)
                        raw_json = repaired
                    except Exception as e:
                        logging.warning(
                            "[CONVERSATIONAL_FRONT][JSON_FAIL_SAFE] usando resposta textual da IA | err=%s",
                            e,
                        )

                        salvaged = {}
                        try:
                            salvaged = _salvage_free_mode_payload(repaired or raw_json or raw)
                        except Exception:
                            salvaged = {}

                        if salvaged and str((salvaged or {}).get("replyText") or "").strip():
                            data = salvaged
                        else:
                            preferred_topic_hint = _preferred_topic_from_kb(
                                kb_context=kb_context if isinstance(kb_context, dict) else {},
                                current_topic="OTHER",
                            )
                            if kb_forced_topic and kb_forced_topic in TOPICS:
                                preferred_topic_hint = kb_forced_topic

                            free_text_payload = _parse_free_mode_text_response(
                                str(raw or ""),
                                topic_hint=preferred_topic_hint,
                                confidence_hint=("high" if kb_anchor_strong else "medium"),
                            )
                            if free_text_payload and str(free_text_payload.get("replyText") or "").strip():
                                data = free_text_payload
                            else:
                                raw_text_candidate = _sanitize_user_facing_reply(str(raw or ""))
                                raw_text_candidate = re.sub(r"\s{2,}", " ", raw_text_candidate).strip()

                                if raw_text_candidate:
                                    data = {
                                        "replyText": raw_text_candidate,
                                        "spokenText": raw_text_candidate,
                                        "understanding": {
                                            "topic": preferred_topic_hint if preferred_topic_hint in TOPICS else "OTHER",
                                            "confidence": ("high" if kb_anchor_strong else "medium"),
                                        },
                                        "nextStep": "NONE",
                                        "shouldEnd": False,
                                        "nameUse": "none",
                                        "prefersText": False,
                                        "replySource": "front_raw_fallback",
                                    }
                                else:
                                    data = {}
        else:
            # Fora do free_mode, mantém protocolo JSON.
            try:
                cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.I)
                cleaned = re.sub(r"^```\s*", "", cleaned, flags=re.I)
                cleaned = re.sub(r"\s*```$", "", cleaned)

                m = re.search(r"\{[\s\S]*\}", cleaned, flags=re.DOTALL)
                if m:
                    raw_json = m.group(0)
                else:
                    raw_json = cleaned

                data = json.loads(raw_json)
            except Exception:
                repaired = re.sub(r",(\s*[}\]])", r"\1", raw_json)
                try:
                    data = json.loads(repaired)
                    raw_json = repaired
                except Exception as e:
                    logging.warning(
                        "[CONVERSATIONAL_FRONT][JSON_FAIL_SAFE] usando resposta textual da IA | err=%s",
                        e,
                    )
                    data = {}

        # ----------------------------------------------------------
        # Parse canônico do decider (packs_v1): por padrão pode vir sem replyText final.
        # ----------------------------------------------------------
        understanding = data.get("understanding") or {}

        intent = str(
            data.get("intent")
            or understanding.get("intent")
            or understanding.get("topic")
            or "OTHER"
        ).strip().upper()

        confidence = str(
            data.get("confidence")
            or understanding.get("confidence")
            or "low"
        ).strip().lower()

        needs_clarify = str(
            data.get("needsClarify")
            or understanding.get("needsClarify")
            or "no"
        ).strip().lower()

        clarify_q = str(
            data.get("clarifyQuestion")
            or understanding.get("clarifyQuestion")
            or ""
        ).strip()

        pack_profile = str(data.get("packProfile") or understanding.get("packProfile") or "generic").strip()
        render_mode = str(data.get("renderMode") or understanding.get("renderMode") or "short").strip().lower()
        segment_key = str(data.get("segmentKey") or understanding.get("segmentKey") or "").strip()
        segment_conf = str(data.get("segmentConfidence") or understanding.get("segmentConfidence") or "low").strip().lower()
        should_ask_segment = str(data.get("shouldAskSegment") or "no").strip().lower()
        pack_id = str(data.get("packId") or (data.get("decider") or {}).get("packId") or "").strip()

        # Back-compat: alguns retornos antigos ainda vêm com replyText/spokenText
        reply_text = str(data.get("replyText") or "").strip()
        spoken_text = str(data.get("spokenText") or "").strip()

        payload_reply_source = str(data.get("replySource") or "").strip()
        if payload_reply_source:
            reply_source = payload_reply_source

        if free_mode and reply_text and not spoken_text:
            spoken_text = reply_text

        if free_mode and not reply_text:
            raw_text_candidate = _sanitize_user_facing_reply(str(raw or ""))
            raw_text_candidate = re.sub(r"\s{2,}", " ", raw_text_candidate).strip()

            if raw_text_candidate:
                reply_text = raw_text_candidate
                if not spoken_text:
                    spoken_text = raw_text_candidate
                if not str(reply_source or "").strip():
                    reply_source = "front_raw_fallback"

        # Compat: topic é o intent (mantém contrato anterior)
        topic = intent
        if topic not in TOPICS:
            topic = "OTHER"

        next_step = str(data.get("nextStep") or data.get("next_step") or "NONE").strip().upper()
        if next_step not in ("NONE", "SEND_LINK"):
            next_step = "NONE"

        should_end = bool(data.get("shouldEnd")) or bool(data.get("should_end"))


        # ----------------------------------------------------------
        # Temperatura de entendimento (heurística local)
        # - evita OTHER + high
        # - sobe intenção de ação explícita para ATIVAR
        # - força clarify quando a frase ficou ambígua
        # ----------------------------------------------------------
        topic, confidence, needs_clarify, clarify_q, next_step = _infer_understanding_temperature(
            user_text=user_text,
            topic=topic,
            confidence=confidence,
            needs_clarify=needs_clarify,
            clarify_q=clarify_q,
            next_step=next_step,
        )

        preferred_topic = _preferred_topic_from_kb(
            kb_context=kb_context if isinstance(kb_context, dict) else {},
            current_topic=topic,
        )

        if kb_forced_topic and kb_forced_topic in TOPICS and kb_forced_topic not in ("OTHER", "WHAT_IS"):
            preferred_topic = kb_forced_topic

        has_kb_direction = bool(
            kb_anchor_strong
            or str(effective_segment or "").strip()
            or str((kb_context or {}).get("subsegment_hint") or "").strip()
            or str((kb_context or {}).get("archetype_id") or "").strip()
        )

        if has_kb_direction and preferred_topic in TOPICS and preferred_topic not in ("OTHER", "WHAT_IS"):
            topic = preferred_topic
            if confidence == "low":
                confidence = "medium"
            if kb_anchor_strong and confidence == "medium":
                confidence = "high"

        operational_contract = _build_operational_contract(
            kb_snapshot=kb_snapshot,
            kb_context=kb_context if isinstance(kb_context, dict) else {},
            effective_segment=effective_segment,
            practical_scene_from_kb=practical_scene_from_kb,
            example_line=example_line,
            operational_family=operational_family,
            topic=topic,
        )

        try:
            if isinstance(operational_contract, dict):
                operational_contract["user_context"] = str(user_text or "").strip()
        except Exception:
            pass

        if not isinstance(operational_contract, dict) or not operational_contract:
            operational_contract = base_operational_contract if 'base_operational_contract' in locals() else {}

        try:
            if (
                isinstance(operational_contract, dict)
                and isinstance(base_operational_contract, dict)
                and not str(operational_contract.get("practical_scene_from_kb") or "").strip()
                and not list(operational_contract.get("operational_ritual") or [])
            ):
                base_ritual = [
                    str(x).strip()
                    for x in (base_operational_contract.get("operational_ritual") or [])
                    if str(x).strip()
                ]
                if base_ritual:
                    operational_contract["operational_ritual"] = base_ritual[:5]
        except Exception:
            pass


        # Guard semântico:
        # se o modelo escolheu cedo demais um trilho estreito sem ancoragem real,
        # rebaixa para ambiguidade útil e permite UMA pergunta.
        if (not kb_anchor_strong) and _should_downgrade_premature_narrow_topic(
            topic=topic,
            confidence=confidence,
            ai_turns=ai_turns,
            effective_segment=effective_segment,
            operational_family=operational_family,
            practical_scene_from_kb="",
            example_line=example_line,
            reply_text=reply_text,
            next_step=next_step,
        ):
            topic = "OTHER"
            confidence = "medium"
            needs_clarify = "yes"
            next_step = "NONE"
            if not clarify_q:
                clarify_q = str(question or "").strip()
            reply_text = ""
            spoken_text = ""

        # ----------------------------------------------------------
        # ✅ ARQUITETURA: aplica prioridade TRIAL (policy gate)
        # Se o KB marcou TRIAL, o front NÃO deixa o LLM cair em PREÇO.
        # ----------------------------------------------------------
        if force_trial:
            intent = "TRIAL"
            topic = "TRIAL"
            # Nunca fechar/mandar link em TRIAL
            next_step = "NONE"
            should_end = False
            # Evita linguagem que soa como "trial disfarçado"
            try:
                for bad in ("experimentar", "teste", "testar", "trial"):
                    if bad in (reply_text or "").lower():
                        # não apaga a frase "não oferece teste grátis"; só remove "experimentar/testar planos"
                        reply_text = re.sub(r"\b(experimentar|testar)\b[^\.\!\?]{0,80}", "", reply_text, flags=re.I).strip()
                        spoken_text = re.sub(r"\b(experimentar|testar)\b[^\.\!\?]{0,80}", "", spoken_text, flags=re.I).strip()
                        break
            except Exception:
                pass

        # name_use: só 4 valores no contrato
        name_use = str(data.get("nameUse") or "none").strip().lower()
        if name_use not in ("none", "greet", "empathy", "clarify"):
            name_use = "none"

        # Se for decider-only, seguimos para fail-safe.
        # Nos primeiros turnos (free_mode), a prioridade é a IA falar com texto próprio.
        decider_only = False
        decider = None
        reply_source = "front"
        if (not free_mode) and next_step != "SEND_LINK":
            decider_only = True
            decider = {
                "intent": intent,
                "confidence": confidence,
                "needsClarify": needs_clarify,
                "clarifyQuestion": clarify_q,
                "packProfile": pack_profile,
                "renderMode": render_mode,
                "segmentKey": segment_key,
                "segmentConfidence": segment_conf,
                "shouldAskSegment": should_ask_segment,
            }
            # NOTE: fora do free_mode ainda pode seguir para render/Fail-safe.
            out = {
                "replyText": "",
                "spokenText": "",
                "understanding": {
                    "topic": topic,
                    "intent": intent,
                    "confidence": confidence,
                    "needsClarify": needs_clarify,
                    "clarifyQuestion": clarify_q,
                    "packProfile": pack_profile,
                    "renderMode": render_mode,
                    "segmentKey": segment_key,
                    "segmentConfidence": segment_conf,
                    "shouldAskSegment": should_ask_segment,
                },
                "decider": decider,
                "nextStep": "NONE",
                "shouldEnd": False,
                "nameUse": ("clarify" if needs_clarify == "yes" or should_ask_segment == "yes" else "none"),
                "prefersText": False,
                "replySource": "front_decider",
                "kbSnapshotSizeChars": len(kb_snapshot or ""),
                "tokenUsage": token_usage or {},
            }
            reply_source = "front_decider"

        # IMPORTANTE:
        # daqui para frente usamos a confidence já recalibrada pela heurística local.
        if confidence not in ("high", "medium", "low"):
            confidence = "low"

        
        # ----------------------------------------------------------
        # ✅ "TOM DO LINK": o link é uma AÇÃO (fechar) — não uma palavra.
        # Regras:
        # 1) Nunca mandar link em pergunta de "grátis/trial".
        # 2) Pode mandar link se o usuário pedir explicitamente.
        # 3) Pode mandar link se o LLM decidiu SEND_LINK com confiança alta
        #    e o lead já está claramente pronto (ex.: depois de 2+ turnos), mesmo sem dizer "link".
        # ----------------------------------------------------------
        is_trial = bool(force_trial)

        if is_trial and next_step == "SEND_LINK":
            next_step = "NONE"

        # IA Soberana: Se a IA decidiu SEND_LINK com confiança alta, liberamos mesmo no turno 0.
        allow_send_link = (
            next_step == "SEND_LINK"
            and (not is_trial)
            and confidence == "high"
            and needs_clarify != "yes"
        )

        if allow_send_link:
            base = str((kb_context or {}).get("signup_url") or "").strip()
            if not base:
                base = (os.getenv("FRONTEND_BASE") or "https://www.meirobo.com.br").strip()

            # Preserva o texto gerado pela IA e apenas injeta o link se faltar
            reply_text = str(reply_text or "").strip()
            if base not in reply_text:
                if reply_text:
                    qpos = reply_text.find("?")
                    if qpos != -1:
                        reply_text = (reply_text[: qpos]).rstrip()
                    if not reply_text.endswith((".", "!", ":")):
                        reply_text += "."
                    reply_text = f"{reply_text}\n{base}"
                else:
                    reply_text = base

            spoken_text = reply_text

            needs_clarify = "no"
            confidence = "high"
            intent = "SIGNUP_LINK"
            next_step = "SEND_LINK"

        elif next_step == "SEND_LINK" and not allow_send_link:
            # Bloqueia SEND_LINK automático quando não houve pedido explícito / sinais fortes
            next_step = "NONE"
            should_end = False



        # ----------------------------------------------------------
        # FREE MODE: nos primeiros turnos do lead, a IA responde direto.
        # Preserva fast-path de link e guardrails leves, mas pula pack_engine
        # e remontagens rígidas de microcena/template.
        # ----------------------------------------------------------
        if free_mode and next_step != "SEND_LINK":
            if _needs_discovery_question(
                topic,
                confidence,
                operational_family,
                ai_turns,
                effective_segment=effective_segment,
                needs_clarify=needs_clarify,
                clarify_q=clarify_q,
                practical_scene_from_kb="",
                example_line=example_line,
                reply_text=reply_text,
            ):
                discovery_q = ""
                try:
                    discovery_q = str((kb_context or {}).get("discovery_question_hint", "") or "").strip()
                except Exception:
                    discovery_q = ""

                if not discovery_q:
                    try:
                        # só cria discovery se realmente não houver trilho operacional suficiente
                        has_anchor = bool(practical_scene_from_kb or example_line or operational_family)
                        if not has_anchor:
                            discovery_q = str(clarify_q or "").strip()
                    except Exception:
                        pass

                return {
                    "replyText": discovery_q,
                    "spokenText": discovery_q,
                    "understanding": {
                        "topic": "OTHER",
                        "intent": "DISCOVERY",
                        "confidence": confidence,
                    },
                    "nextStep": "DISCOVERY",
                    "shouldEnd": False,
                    "nameUse": "clarify",
                    "prefersText": False,
                    "replySource": "front_discovery",
                    "kbSnapshotSizeChars": len(kb_snapshot or ""),
                    "tokenUsage": token_usage if isinstance(token_usage, dict) else {},
                }

            generated = ""
            if next_step != "SEND_LINK":
                generated = _generate_micro_scene_with_model(
                    practical_scene_from_kb="",
                    contract=operational_contract if 'operational_contract' in locals() else {},
                ).strip()

            if generated:
                generated_live = _is_live_operational_reply(
                    text=generated,
                    practical_scene_from_kb="",
                    example_line=example_line,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )

                generated_show = _is_show_micro_scene(
                    text=generated,
                    practical_scene_from_kb="",
                    example_line=example_line,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )

                # ============================================================
                # SEGUNDA CAMADA — REESCRITA OPERACIONAL CONCRETA
                # entra no caminho principal da IA, não no fallback
                # ============================================================
                if generated:
                    upgraded = _upgrade_operational_reply_with_model(
                        base_text=generated,
                        practical_scene_from_kb="",
                        example_line=example_line,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    )

                    upgraded_live = _is_live_operational_reply(
                        text=upgraded,
                        practical_scene_from_kb="",
                        example_line=example_line,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    ) if upgraded else False

                    upgraded_show = _is_show_micro_scene(
                        text=upgraded,
                        practical_scene_from_kb="",
                        example_line=example_line,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    ) if upgraded else False

                    _upgrade_contract_strong = bool(
                        ((operational_contract if 'operational_contract' in locals() else {}) or {}).get("hydrated_from_docs")
                        and str(example_line or "").strip()
                        and str((((operational_contract if 'operational_contract' in locals() else {}) or {}).get("practical_scene_from_kb") or "")).strip()
                    )

                    if upgraded and len(str(upgraded).strip()) > 40:
                        if _upgrade_contract_strong:
                            # Contrato forte: preservar a primeira microcena boa.
                            # Upgrade só entra se elevar de fato (SHOW quando antes não era).
                            keep_upgraded = bool(
                                upgraded_show and not generated_show
                            )
                        else:
                            # Sem contrato forte: ainda permitimos upgrade,
                            # mas removemos completamente o incentivo por tamanho.
                            keep_upgraded = bool(
                                (upgraded_show and not generated_show)
                                or (upgraded_live and not generated_live)
                            )

                        if keep_upgraded:
                            generated = upgraded
                            generated_live = upgraded_live
                            generated_show = upgraded_show

                structured = ""
                structured_live = False
                structured_show = False

                # fallback estrutural só entra se a IA principal falhar de verdade
                if not generated or len(str(generated).strip()) < 40:
                    structured = _compose_grounded_scene_with_progression(
                        practical_scene_from_kb="",
                        contract=operational_contract if 'operational_contract' in locals() else {},
                        example_line=example_line,
                    )

                    if not structured:
                        structured = _build_structural_last_resort_reply(
                            practical_scene_from_kb="",
                            contract=operational_contract if 'operational_contract' in locals() else {},
                        )

                    if structured:
                        structured_live = _is_live_operational_reply(
                            text=structured,
                            practical_scene_from_kb="",
                            example_line=example_line,
                            contract=operational_contract if 'operational_contract' in locals() else {},
                        )
                        structured_show = _is_show_micro_scene(
                            text=structured,
                            practical_scene_from_kb="",
                            example_line=example_line,
                            contract=operational_contract if 'operational_contract' in locals() else {},
                        )

                if generated_show:
                    reply_text = generated
                    spoken_text = generated
                    reply_source = "front_ia_soberana"
                elif generated:
                    reply_text = generated
                    spoken_text = generated
                    reply_source = "front_operational_upgrade"
                elif structured_show:
                    reply_text = structured
                    spoken_text = structured
                    reply_source = "front_fallback_structural"
                elif structured_live:
                    reply_text = structured
                    spoken_text = structured
                    reply_source = "front_fallback_structural"
                else:
                    reply_text = str(question or clarify_q or "").strip()
                    spoken_text = reply_text
                    reply_source = "front_free_mode_empty"

            kb_reply = _build_kb_anchor_reply(
                practical_scene_from_kb="",
                example_line=example_line,
                clarify_q=(question if not effective_segment else ""),
                contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
            )

            if kb_anchor_strong and kb_reply:
                needs_resolution = (
                    (not str(reply_text or "").strip())
                    or _looks_like_technical_output(reply_text)
                    or (
                        _looks_like_bureaucratic_stub(reply_text)
                        and not str(reply_source or "").strip().startswith(("front_free_text", "front_raw_fallback"))
                    )
                    or (
                        _should_force_kb_rebuild(
                            text=reply_text,
                            kb_anchor_strong=kb_anchor_strong,
                            practical_scene_from_kb="",
                            example_line=example_line,
                            effective_segment=effective_segment,
                            operational_family=operational_family,
                            contract=operational_contract if 'operational_contract' in locals() else {},
                        )
                        and not str(reply_source or "").strip().startswith(("front_free_text", "front_raw_fallback", "front_free_mode"))
                    )
                )

                if needs_resolution:
                    resolved = _resolve_best_operational_reply(
                        current_reply=reply_text,
                        current_spoken=spoken_text,
                        user_text=user_text,
                        state_summary=state_summary,
                        kb_snapshot=kb_snapshot,
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        effective_segment=effective_segment,
                        operational_family=operational_family,
                        selected_pack_id=selected_pack_id,
                        practical_scene_from_kb="",
                        example_line=example_line,
                        question=question,
                        topic=topic,
                        confidence=confidence,
                        kb_anchor_strong=kb_anchor_strong,
                        operational_contract=operational_contract if 'operational_contract' in locals() else {},
                        base_operational_contract=base_operational_contract if 'base_operational_contract' in locals() else {},
                    )

                    reply_text = str((resolved or {}).get("reply_text") or "").strip()
                    spoken_text = str((resolved or {}).get("spoken_text") or reply_text).strip()
                    reply_source = str((resolved or {}).get("reply_source") or "front_resolved").strip()

                    if not spoken_text:
                        spoken_text = reply_text

                    should_end = False
                    if next_step != "SEND_LINK":
                        next_step = "NONE"
            elif not reply_text:
                reply_text = kb_reply
                if not reply_text and question and not effective_segment:
                    reply_text = question
                if not spoken_text:
                    spoken_text = reply_text
                reply_source = "front_free_mode_fallback"

            try:
                operational_reply = bool(
                    str(topic or "").upper() in ("PEDIDOS", "SERVICOS", "PROCESSO", "STATUS", "AGENDA")
                    and "na prática:" in str(reply_text or "").lower()
                )
            except Exception:
                operational_reply = False

            if operational_reply and next_step != "SEND_LINK":
                should_end = False

            reply_text = reply_text[:FRONT_REPLY_MAX_CHARS].rstrip()
            spoken_text = (spoken_text or reply_text or "")[:FRONT_REPLY_MAX_CHARS].rstrip()

            try:
                _reply_before_sanitize = str(reply_text or "").strip()
                _spoken_before_sanitize = str(spoken_text or "").strip()
                _kb_obj = _try_parse_kb_json(kb_snapshot)
                reply_text = _sanitize_unverified_time_claims(reply_text, _kb_obj, kb_snapshot)
                spoken_text = _sanitize_unverified_time_claims(spoken_text, _kb_obj, kb_snapshot)

                # Nunca deixar o saneamento burocrático matar a resposta de vitrine.
                if _looks_like_bureaucratic_stub(reply_text):
                    kb_fallback = _build_kb_anchor_reply(
                        practical_scene_from_kb="",
                        example_line=example_line,
                        clarify_q=(question if not effective_segment else ""),
                    )
                    reply_text = (
                        kb_fallback
                        or _reply_before_sanitize
                        or question
                        or "Hoje no WhatsApp, o que você precisa responder ou organizar manualmente para os clientes?"
                    )
                if _looks_like_bureaucratic_stub(spoken_text):
                    kb_fallback = _build_kb_anchor_reply(
                        practical_scene_from_kb="",
                        example_line=example_line,
                        clarify_q=(question if not effective_segment else ""),
                    )
                    spoken_text = (
                        kb_fallback
                        or _spoken_before_sanitize
                        or reply_text
                    )
            except Exception:
                pass

            try:
                reply_text = _de_genericize_free_mode_text(reply_text)
                spoken_text = _de_genericize_free_mode_text(spoken_text)
            except Exception:
                pass

            reply_text = str(reply_text or "").strip()

            ia_locked = False
            try:
                if (
                    str(reply_source or "").strip() == "front_ia_soberana"
                    and (ia_accepted or _is_show_micro_scene(
                        text=reply_text,
                        practical_scene_from_kb="",
                        example_line=example_line,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    ))
                ):
                    ia_locked = True
            except Exception:
                ia_locked = False

            if not ia_locked:
                try:
                    grounded_scene = str(practical_scene_from_kb or "").strip()
                    grounded_ritual = [
                        str(x).strip()
                        for x in ((operational_contract if 'operational_contract' in locals() else {}) or {}).get("operational_ritual", [])
                        if str(x).strip()
                    ]

                    # não reconstruir estruturalmente quando já existe resposta
                    reply_text = str(reply_text or "").strip()
                    spoken_text = str(spoken_text or reply_text).strip()
                except Exception:
                    pass

                try:
                    if (
                        reply_text
                        and len(reply_text.strip()) >= 60
                        and _is_show_micro_scene(
                            text=reply_text,
                            practical_scene_from_kb="",
                            example_line=example_line,
                            contract=operational_contract if 'operational_contract' in locals() else {},
                        )
                    ):
                        _final_candidate = reply_text.strip()
                except Exception:
                    pass

            # ----------------------------------------------------------
            # COMPOSIÇÃO OPERACIONAL
            # A IA cria a resposta; o front apenas organiza a narrativa
            # para manter a cena operacional clara.
            # ----------------------------------------------------------
            if not ia_locked:
                try:
                    composed_reply = _compose_operational_reply(
                        reply_text=reply_text,
                        practical_scene_from_kb="",
                        example_line=example_line,
                        operational_family=operational_family,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    )
                    if composed_reply:
                        reply_text = composed_reply
                        if not spoken_text:
                            spoken_text = composed_reply
                except Exception:
                    pass

                try:
                    final_live = _is_live_operational_reply(
                        text=reply_text,
                        practical_scene_from_kb="",
                        example_line=example_line,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    )
                    if final_live and reply_text:
                        _final_candidate = str(reply_text).strip()
                except Exception:
                    pass

            try:
                logging.info(
                    "[CONVERSATIONAL_FRONT][IA_SOVEREIGN_CHECK] source=%s live=%s chars=%s",
                    str(reply_source or "").strip(),
                    bool(
                        True if ia_accepted else _is_live_operational_reply(
                            text=reply_text,
                            practical_scene_from_kb="",
                            example_line=example_line,
                            contract=operational_contract if 'operational_contract' in locals() else {},
                        )
                    ),
                    len(str(reply_text or "")),
                )
            except Exception:
                pass

            try:
                reply_text = wrap_show_response(reply_text)
            except Exception:
                pass

            try:
                if kb_anchor_strong and kb_reply:
                    if _looks_like_technical_output(reply_text) or not str(reply_text or "").strip():
                        reply_text = kb_show_reply_seed or kb_reply
                    if _looks_like_technical_output(spoken_text) or not str(spoken_text or "").strip():
                        spoken_text = kb_show_reply_seed or kb_reply
            except Exception:
                pass

            # Fase 3:
            # não abrir uma segunda cascata completa de rebuild aqui.
            # A resolução principal já aconteceu no resolvedor único acima.
            if practical_scene_from_kb and len(str(reply_text or "")) > 40:
                try:
                    if _should_force_kb_rebuild(
                        text=reply_text,
                        kb_anchor_strong=kb_anchor_strong,
                        practical_scene_from_kb="",
                        example_line=example_line,
                        effective_segment=effective_segment,
                        operational_family=operational_family,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    ):
                        resolved = _resolve_best_operational_reply(
                            current_reply=reply_text,
                            current_spoken=spoken_text,
                            user_text=user_text,
                            state_summary=state_summary,
                            kb_snapshot=kb_snapshot,
                            kb_context=kb_context if isinstance(kb_context, dict) else {},
                            effective_segment=effective_segment,
                            operational_family=operational_family,
                            selected_pack_id=selected_pack_id,
                            practical_scene_from_kb="",
                            example_line=example_line,
                            question=question,
                            topic=topic,
                            confidence=confidence,
                            kb_anchor_strong=kb_anchor_strong,
                            operational_contract=operational_contract if 'operational_contract' in locals() else {},
                            base_operational_contract=base_operational_contract if 'base_operational_contract' in locals() else {},
                        )
                        candidate = str((resolved or {}).get("reply_text") or "").strip()

                        if (
                            candidate
                            and not (ia_accepted or _is_live_operational_reply(
                                text=reply_text,
                                practical_scene_from_kb="",
                                example_line=example_line,
                                contract=operational_contract if 'operational_contract' in locals() else {},
                            ))
                        ):
                            reply_text = candidate
                            spoken_text = str((resolved or {}).get("spoken_text") or spoken_text or candidate).strip()
                            reply_source = str((resolved or {}).get("reply_source") or reply_source or "front_resolved_retry").strip()
                except Exception:
                    pass

            try:
                # IA TOTAL: não remontar pergunta, não injetar proposta, não trocar fechamento.
                # Só aplica a política de perguntas abolidas e uma higiene mínima.
                if reply_text and ("?" in reply_text):
                    if not _should_allow_question(
                        user_text=user_text,
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        reply_text=reply_text,
                        understanding={"topic": topic, "confidence": confidence},
                        decider=decider if isinstance(decider, dict) else {},
                    ):
                        reply_text = _strip_trailing_question(reply_text)
                if spoken_text and ("?" in spoken_text):
                    if not _should_allow_question(
                        user_text=user_text,
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        reply_text=spoken_text,
                        understanding={"topic": topic, "confidence": confidence},
                        decider=decider if isinstance(decider, dict) else {},
                    ):
                        spoken_text = _strip_trailing_question(spoken_text)
                reply_text = re.sub(r"\s{2,}", " ", str(reply_text or "")).strip(" \n")
                spoken_text = re.sub(r"\s{2,}", " ", str(spoken_text or "")).strip(" \n")
            except Exception:
                pass

            reply_text = _sanitize_user_facing_reply(reply_text)
            spoken_text = _sanitize_user_facing_reply(spoken_text or reply_text)

            reply_text = _smart_truncate_text(reply_text, FRONT_REPLY_MAX_CHARS)
            spoken_text = _smart_truncate_text(spoken_text, FRONT_REPLY_MAX_CHARS)

            if _looks_like_technical_output(reply_text):
                fallback_specific = _build_kb_anchor_reply(
                    practical_scene_from_kb="",
                    example_line=example_line,
                    clarify_q=(question if not effective_segment else ""),
                    contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
                )
                reply_text = fallback_specific or _build_contract_consequence(
                    operational_contract if 'operational_contract' in locals() else
                    (base_operational_contract if 'base_operational_contract' in locals() else {})
                )

            if _looks_like_technical_output(spoken_text):
                spoken_text = reply_text

            if not spoken_text:
                spoken_text = reply_text


            # 🔒 GUARDA FINAL — impedir saída vazia ou fallback burro
            try:
                _rt = str(reply_text or "").strip()

                if not _rt or len(_rt) < 40:
                    forced = ""

                    if operational_contract:
                        forced = _build_kb_show_reply(
                            kb_context=kb_context if isinstance(kb_context, dict) else {},
                            practical_scene_from_kb="",
                            example_line=example_line,
                            effective_segment=effective_segment,
                            operational_family=operational_family,
                            contract=operational_contract,
                        )

                    if (not forced or len(forced.strip()) < 40) and base_operational_contract:
                        forced = _build_kb_show_reply(
                            kb_context=kb_context if isinstance(kb_context, dict) else {},
                            practical_scene_from_kb="",
                            example_line=example_line,
                            effective_segment=effective_segment,
                            operational_family=operational_family,
                            contract=base_operational_contract,
                        )

                    if not forced or len(forced.strip()) < 40:
                        forced = _build_kb_anchor_reply(
                            practical_scene_from_kb="",
                            example_line=example_line,
                            clarify_q="",
                            contract=operational_contract if operational_contract else base_operational_contract,
                        )

                    if forced and len(forced.strip()) >= 40:
                        reply_text = forced
                        if not spoken_text or len(str(spoken_text or "").strip()) < 40:
                            spoken_text = forced
            except Exception:
                pass

            # 🧠 restaura melhor versão se degradou no meio do fluxo
            try:
                if (_final_candidate 
                    and (not reply_text or len(reply_text.strip()) < 40)):
                    reply_text = _final_candidate
            except Exception:
                pass

            if not str(reply_text or "").strip():
                steps = _split_scene_steps(user_text)

                if len(steps) >= 2:
                    rebuilt = _render_progressive_operational_flow(steps[:6])
                else:
                    rebuilt = ""

                if rebuilt:
                    reply_text = rebuilt
                    spoken_text = rebuilt
                    reply_source = "front_from_user_flow"

            try:
                logger.info(
                    "[IA_SOVEREIGN_CHECK] source=%s is_live=%s len=%s",
                    reply_source,
                    True if ia_accepted else _is_live_operational_reply(
                        text=reply_text,
                        practical_scene_from_kb="",
                        example_line=example_line,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    ),
                    len(reply_text or ""),
                )
            except Exception:
                pass

            ia_live = bool(
                _is_live_operational_reply(
                    text=reply_text,
                    practical_scene_from_kb="",
                    example_line=example_line,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )
            )

            ia_density = _operational_density_score(
                text=reply_text,
                practical_scene_from_kb="",
                example_line=example_line,
                effective_segment=str((operational_contract if 'operational_contract' in locals() else {}).get("segment") or "").strip(),
                operational_family=str((operational_contract if 'operational_contract' in locals() else {}).get("operational_family") or "").strip(),
            )

            ia_text = str(reply_text or "").strip()

            ia_show = bool(
                _is_show_micro_scene(
                    text=ia_text,
                    practical_scene_from_kb="",
                    example_line=example_line,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )
            )

            ia_live_final = bool(
                _is_live_operational_reply(
                    text=ia_text,
                    practical_scene_from_kb="",
                    example_line=example_line,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )
            )

            _contract_strong = bool(
                (operational_contract if 'operational_contract' in locals() else {}).get("hydrated_from_docs")
                and example_line
                and str(((operational_contract if 'operational_contract' in locals() else {}) or {}).get("practical_scene_from_kb") or "").strip()
            )

            _not_explanatory = not _looks_explanatory_reply(
                text=str(reply_text or ""),
                practical_scene_from_kb="",
                example_line=example_line,
                contract=operational_contract if 'operational_contract' in locals() else {},
            )

            _source_now = str(reply_source or "").strip()

            if _contract_strong and _source_now == "front_operational_upgrade":
                accepted = bool(ia_show)
            else:
                accepted = bool(
                    _source_now in ("front_ia_soberana", "front_operational_upgrade")
                    and (
                        ia_show
                        or (ia_live_final and (not _contract_strong or _not_explanatory))
                    )
                )
            ia_accepted = accepted

            if accepted:
                final_reply = str(reply_text or "").strip()
                final_spoken = str(spoken_text or final_reply).strip()
                reply_text = final_reply
                spoken_text = final_spoken
                reply_source = "front_ia_soberana"

            if not accepted:
                current_text = str(reply_text or "").strip()

                current_show = bool(
                    current_text and _is_show_micro_scene(
                        text=current_text,
                        practical_scene_from_kb="",
                        example_line=example_line,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    )
                )

                current_live = bool(
                    current_text and _is_live_operational_reply(
                        text=current_text,
                        practical_scene_from_kb="",
                        example_line=example_line,
                        contract=operational_contract if 'operational_contract' in locals() else {},
                    )
                )

                current_is_mild = _looks_explanatory_reply(
                    text=current_text,
                    practical_scene_from_kb="",
                    example_line=example_line,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )

                _current_not_explanatory = not _looks_explanatory_reply(
                    text=current_text,
                    practical_scene_from_kb="",
                    example_line=example_line,
                    contract=operational_contract if 'operational_contract' in locals() else {},
                )

                if _contract_strong and str(reply_source or "").strip() == "front_operational_upgrade":
                    _accept_current = bool(current_show)
                else:
                    _accept_current = bool(
                        current_show
                        or (current_live and (not _contract_strong or _current_not_explanatory))
                    )

                if _accept_current:
                    accepted = True
                    if str(reply_source or "").strip() not in ("front_ia_soberana", "front_operational_upgrade"):
                        reply_source = "front_operational_upgrade"
                else:
                    fallback = ""
                    if (
                        (not current_text)
                        or len(current_text) < 40
                        or _looks_like_technical_output(current_text)
                        or (_contract_strong and current_is_mild)
                    ):
                        fallback = (
                            _compose_grounded_scene_with_progression(
                                practical_scene_from_kb="",
                                contract=operational_contract if 'operational_contract' in locals() else {},
                                example_line=example_line,
                            ).strip()
                            or _build_structural_last_resort_reply(
                                practical_scene_from_kb="",
                                contract=operational_contract if 'operational_contract' in locals() else {},
                            ).strip()
                        )

                    if fallback:
                        reply_text = fallback
                        spoken_text = fallback
                        reply_source = "front_fallback_structural"

            logging.info(
                "[IA_FINAL_DECISION] source=%s accepted=%s len=%s live=%s density=%s",
                str(reply_source or "").strip(),
                accepted,
                len(str(reply_text or "")),
                ia_live if 'ia_live' in locals() else None,
                ia_density if 'ia_density' in locals() else None,
            )

            try:
                spoken_text = _strip_trailing_question(spoken_text or reply_text)
            except Exception:
                spoken_text = str(spoken_text or reply_text or "").strip()

            out = {
                "replyText": reply_text,
                "spokenText": spoken_text,
                "understanding": {
                    "topic": topic,
                    "intent": topic,
                    "confidence": confidence,
                    "needsClarify": needs_clarify,
                    "clarifyQuestion": clarify_q,
                },
                "nextStep": next_step,
                "shouldEnd": should_end,
                "nameUse": name_use,
                "prefersText": (next_step == "SEND_LINK"),
                "replySource": (reply_source or "front_free_mode"),
                "kbSnapshotSizeChars": len(kb_snapshot or ""),
                "tokenUsage": token_usage,
                "operationalContract": operational_contract if 'operational_contract' in locals() else {},
            }

            if decider_only and isinstance(decider, dict):
                out["decider"] = decider

            logging.info(
                "[CONVERSATIONAL_FRONT][FREE_MODE] ai_turns=%s topic=%s confidence=%s nextStep=%s shouldEnd=%s kbChars=%s tok=%s source=%s contract=%s docs=%s hydrated=%s",
                ai_turns,
                topic,
                confidence,
                next_step,
                should_end,
                len(kb_snapshot or ""),
                token_usage or {},
                (reply_source or "front_free_mode"),
                operational_contract if 'operational_contract' in locals() else {},
                real_kb_docs if 'real_kb_docs' in locals() else {},
                bool((operational_contract or {}).get("hydrated_from_docs")) if 'operational_contract' in locals() and isinstance(operational_contract, dict) else False,
            )
            return out



# ✅ packs_v1: fora do free_mode, ainda pode renderizar reply via Pack Engine quando o LLM devolver só o decider.
        try:
            # heurística leve: "como funciona" às vezes cai em OTHER; tratamos como WHAT_IS.
            _ut = (user_text or "").strip().lower()
            if intent == "OTHER" and ("como funciona" in _ut or "como que funciona" in _ut or "funciona" in _ut or "o que é" in _ut or "o que eh" in _ut):
                intent = "WHAT_IS"
                topic = "WHAT_IS"

            if not reply_text:
                _kb = None
                try:
                    if kb_snapshot and str(kb_snapshot).strip().startswith("{"):
                        _kb = json.loads(str(kb_snapshot))
                except Exception:
                    _kb = None

                if isinstance(_kb, dict) and (
                    _kb.get("value_packs_v1")
                    or _kb.get("answer_playbook_v1")
                    or _kb.get("kb_segments_v1")
                    or _kb.get("kb_subsegments_v1")
                    or _kb.get("kb_archetypes_v1")
                ):
                    try:
                        from services.pack_engine import render_pack_reply  # type: ignore
                        rend = render_pack_reply(
                            kb=_kb,
                            intent=intent or "WHAT_IS",
                            segment=((segment_key or effective_segment) or None),
                            pack_id=(pack_id or None),
                            render_mode=(render_mode or "short"),
                        ) or {}
                        if rend.get("ok") and str(rend.get("replyText") or "").strip():
                            reply_text = str(rend.get("replyText") or "").strip()
                            if not spoken_text and str(rend.get("spokenText") or "").strip():
                                spoken_text = str(rend.get("spokenText") or "").strip()
                            reply_source = "pack_engine"
                            pack_id = str(rend.get("packId") or pack_id or "").strip()
                            segment_key = str(rend.get("segmentKey") or segment_key or effective_segment or "").strip()
                            render_mode = str(rend.get("renderMode") or render_mode or "short").strip().lower()
                    except Exception:
                        pass

            # fallback humano (sem depender do Firestore) quando ainda ficar vazio
            if not reply_text and (intent in ("WHAT_IS", "OTHER")):
                reply_text = (
                    "O MEI Robô vira um atendente no seu WhatsApp: responde cliente, organiza agenda, orçamento e pedido sem te prender no celular. "
                    "Na prática: o cliente chama, o robô conduz o básico, confirma por escrito e adianta seu atendimento sem conversa perdida."
                )
                if question:
                    reply_text = f"{reply_text} {question}"

            # IA TOTAL: só compõe cena externa se o modelo NÃO respondeu.
            # Se reply_text já existe, ele é dono da fala.
            try:
                if next_step != 'SEND_LINK' and (not reply_text):
                    _seg = (segment_key or '').strip() or effective_segment or _infer_segment_from_text(user_text, kb_snapshot)
                    _pack = _pick_pack_for_intent(intent, pack_id)
                    if _pack and intent in ("WHAT_IS", "AGENDA", "SERVICOS", "PEDIDOS", "ORCAMENTO", "STATUS", "PROCESSO"):
                        practical_scene = ""
                        if _seg:
                            practical_scene = _compose_practical_scene(
                                kb_snapshot=kb_snapshot,
                                segment_key=_seg,
                                pack_id=_pack,
                            )

                        if practical_scene:
                            value_line = _extract_value_line(reply_text)
                            reply_text = _merge_value_and_scene(value_line, practical_scene, question)

                        if not practical_scene:
                            ms = _kb_get_micro_scene(kb_snapshot, _pack)
                            if ms:
                                practical_scene = ms if ms.lower().startswith("na prática:") else f"Na prática: {ms}"
                        if not practical_scene:
                            practical_scene = _pack_practical_add(_pack)

                        value_line = _extract_value_line(reply_text)
                        if not value_line:
                            value_line = "O MEI Robô atende seus clientes no WhatsApp e adianta seu trabalho sem te prender no celular"

                        ask_tail = ""
                        if not _seg:
                            ask_tail = question
                        elif not has_name and ai_turns >= 1:
                            ask_tail = question

                        reply_text = _merge_value_and_scene(value_line, practical_scene, ask_tail)
                        if not spoken_text:
                            spoken_text = reply_text
                        else:
                            spoken_text = _merge_value_and_scene(_extract_value_line(spoken_text), practical_scene, ask_tail)
                        reply_source = 'scene_composed'
            except Exception:
                pass
        except Exception:
            pass

        # Se a decisão foi clarificar, respeita a pergunta curta antes do fail-safe genérico.
        if not reply_text and needs_clarify == "yes" and clarify_q:
            if question and not effective_segment:
                reply_text = question
                if not spoken_text:
                    spoken_text = question
            else:
                reply_text = clarify_q
                if not spoken_text:
                    spoken_text = clarify_q
            reply_source = "front_clarify"

        # Fail-safe: nunca devolver reply vazio (evita saída "muda" em produção)
        if not reply_text or len(str(reply_text).strip()) < 40:
            try:
                if operational_contract or base_operational_contract:
                    if not practical_scene_from_kb:
                        practical_scene_from_kb = ""
                    forced = _build_kb_show_reply(
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        practical_scene_from_kb="",
                        example_line=example_line,
                        effective_segment=effective_segment,
                        operational_family=operational_family,
                        contract=operational_contract or base_operational_contract,
                    )
                    if forced and len(forced.strip()) >= 40:
                        reply_text = forced
                    else:
                        raise ValueError("forced_empty")
                else:
                    raise ValueError("no_contract")
            except Exception:
                # só cai no fallback genérico se REALMENTE não tiver nada
                pass

        if not reply_text or len(str(reply_text).strip()) < 40:
            reply_text = question or "Me conta um pouco melhor o teu cenário."
            topic = "OTHER"
            confidence = "low"
            next_step = "NONE"
            should_end = False
            name_use = "clarify"

        # ✅ Produto: SEND_LINK = venda fechada (link-only, sem pergunta)
        try:
            if next_step == "SEND_LINK":
                should_end = True
                url = (os.getenv("FRONTEND_BASE") or "https://www.meirobo.com.br").strip()
                rt0 = (reply_text or "").strip()
                # IA Soberana: apenas garante que o link está presente, sem reescrever com frase pronta
                if ("http://" not in rt0) and ("https://" not in rt0):
                    if rt0:
                        qpos = rt0.find("?")
                        if qpos != -1:
                            rt0 = (rt0[: qpos]).rstrip()
                        if not rt0.endswith((".", "!", ":")):
                            rt0 += "."
                        reply_text = f"{rt0}\n{url}"
                    else:
                        reply_text = url
                st0 = (spoken_text or reply_text or "").strip()
                spoken_text = st0
        except Exception:
            pass

        # daqui para baixo: pós-processamento do front
        front_reply_before_post = reply_text
        front_spoken_before_post = spoken_text

        # Corte final:
        # quando o contrato veio hidratado do KB, faz só limpeza leve.
        hydrated_contract = bool(
            (operational_contract if 'operational_contract' in locals() else {}).get("hydrated_from_docs")
            or (base_operational_contract if 'base_operational_contract' in locals() else {}).get("hydrated_from_docs")
            or kb_anchor_strong
        )

        reply_text = _sanitize_user_facing_reply(reply_text)
        spoken_text = _sanitize_user_facing_reply(spoken_text or reply_text)

        if not hydrated_contract:
            reply_text = _smart_truncate_text(reply_text, FRONT_REPLY_MAX_CHARS)
            spoken_text = _smart_truncate_text(spoken_text, FRONT_REPLY_MAX_CHARS)

        # Regra de produto: perguntas foram abolidas, salvo exceções controladas.
        if reply_text and ("?" in reply_text):
            try:
                if not _should_allow_question(
                    user_text=user_text,
                    kb_context=kb_context if isinstance(kb_context, dict) else {},
                    reply_text=reply_text,
                    understanding=understanding if isinstance(understanding, dict) else {},
                    decider=decider if isinstance(decider, dict) else {},
                ):
                    reply_text = _strip_trailing_question(reply_text)
                    try:
                        debug_info = debug_info if isinstance(debug_info, dict) else {}
                        debug_info["question_stripped_by_policy"] = True
                    except Exception:
                        pass
            except Exception:
                pass

        if spoken_text and ("?" in spoken_text):
            try:
                if not _should_allow_question(
                    user_text=user_text,
                    kb_context=kb_context if isinstance(kb_context, dict) else {},
                    reply_text=spoken_text,
                    understanding=understanding if isinstance(understanding, dict) else {},
                    decider=decider if isinstance(decider, dict) else {},
                ):
                    spoken_text = _strip_trailing_question(spoken_text)
            except Exception:
                pass



        # ----------------------------------------------------------
        # Guardrails mínimos (robustos, sem virar "frase pronta")
        # - bloquear prazos/tempos inventados
        # - não recriar pergunta/CTA por fora da IA
        # ----------------------------------------------------------
        try:
            _kb_obj = _try_parse_kb_json(kb_snapshot)

            reply_text = _sanitize_unverified_time_claims(reply_text, _kb_obj, kb_snapshot)
            spoken_text = _sanitize_unverified_time_claims(spoken_text, _kb_obj, kb_snapshot)
        except Exception:
            pass

        try:
            # não remontar a resposta aqui; a IA já recebeu a cena do KB no prompt
            pass
        except Exception:
            pass

        # Guardrails finais (anti-invenção), fora do free_mode.
        try:
            if (not free_mode) and apply_sales_guardrails is not None:
                gr = apply_sales_guardrails(
                    reply_text=reply_text,
                    spoken_text=spoken_text,
                    topic=topic,
                    confidence=confidence,
                    user_text=user_text,
                    kb_context=kb_context if isinstance(kb_context, dict) else {},
                )
                guardrail_reply_before = reply_text
                guardrail_spoken_before = spoken_text
                if isinstance(gr, dict):
                    reply_text = str(gr.get("reply_text") or reply_text or "").strip()
                    spoken_text = str(gr.get("spoken_text") or spoken_text or "").strip()
        except Exception:
            pass



        try:
            reply_text = wrap_show_response(reply_text)
        except Exception:
            pass

        reply_text = _sanitize_user_facing_reply(reply_text)
        spoken_text = _sanitize_user_facing_reply(spoken_text or reply_text)

        if _looks_like_technical_output(reply_text):
            reply_text = _build_contract_consequence(
                operational_contract if 'operational_contract' in locals() else
                (base_operational_contract if 'base_operational_contract' in locals() else {})
            )
        if _looks_like_technical_output(spoken_text):
            spoken_text = reply_text

        if not spoken_text:
            spoken_text = reply_text


        # 🔒 GUARDA FINAL — impedir saída vazia ou fallback burro
        try:
            _rt = str(reply_text or "").strip()

            if not _rt or len(_rt) < 40:
                if operational_contract:
                    if not practical_scene_from_kb:
                        practical_scene_from_kb = ""
                    forced = _build_kb_show_reply(
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        practical_scene_from_kb="",
                        example_line=example_line,
                        effective_segment=effective_segment,
                        operational_family=operational_family,
                        contract=operational_contract,
                    )
                    if forced and len(forced.strip()) >= 40:
                        reply_text = forced
                elif base_operational_contract:
                    if not practical_scene_from_kb:
                        practical_scene_from_kb = ""
                    forced = _build_kb_show_reply(
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        practical_scene_from_kb="",
                        example_line=example_line,
                        effective_segment=effective_segment,
                        operational_family=operational_family,
                        contract=base_operational_contract,
                    )
                    if forced and len(forced.strip()) >= 40:
                        reply_text = forced
        except Exception:
            pass

        # 🧠 restaura melhor versão se degradou no meio do fluxo
        try:
            if (_final_candidate 
                and (not reply_text or len(reply_text.strip()) < 40)):
                reply_text = _final_candidate
        except Exception:
            pass

        # 🔒 última garantia: não sair com resposta fraca quando há contexto
        try:
            if not reply_text or len(reply_text.strip()) < 40:
                forced = (
                    kb_show_reply_seed
                    or _build_kb_show_reply(
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        practical_scene_from_kb="",
                        example_line=example_line,
                        effective_segment=effective_segment,
                        operational_family=operational_family,
                        contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
                    )
                    or _build_kb_anchor_reply(
                        practical_scene_from_kb="",
                        example_line=example_line,
                        clarify_q="",
                        contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
                    )
                )
                if forced and len(forced.strip()) >= 40:
                    reply_text = forced
                    spoken_text = forced
        except Exception:
            pass

        out = {
            "replyText": reply_text,
            "spokenText": spoken_text,
            "understanding": {
                "topic": topic,
                # Harmoniza com o resto do pipeline (sales_lead/outbox)
                "intent": topic,
                "confidence": confidence,
                "needsClarify": needs_clarify,
                "clarifyQuestion": clarify_q,
            },
            "nextStep": next_step,
            "shouldEnd": should_end,
            "nameUse": name_use,
            # ✅ Regra canônica: texto só quando for SEND_LINK (link copiável).
            # Caso contrário, o worker decide o canal (entra áudio -> sai áudio).
            "prefersText": (next_step == "SEND_LINK"),
            # Auditoria: quem respondeu
            "replySource": (reply_source or "front"),
            # Probe leve do snapshot (ajuda a ver se o front "passou fome")
            "kbSnapshotSizeChars": len(kb_snapshot or ""),
            # Telemetria de custo (best-effort)
            "tokenUsage": token_usage,
        }

        # Mantém o decider no retorno quando existir (p/ roteamento/auditoria downstream).
        if decider_only and isinstance(decider, dict):
            out["decider"] = decider

        # -----------------------------
        # Observabilidade leve
        # -----------------------------
        logging.info(
            "[CONVERSATIONAL_FRONT] ai_turns=%s topic=%s confidence=%s nextStep=%s shouldEnd=%s kbChars=%s tok=%s",
            ai_turns,
            topic,
            confidence,
            next_step,
            should_end,
            len(kb_snapshot or ""),
            token_usage or {},
        )

        if not reply_text:
            reply_text = question or "Me conta um pouco melhor o teu cenário."
            should_end = False
            out["replyText"] = reply_text
            out["spokenText"] = reply_text
            out["shouldEnd"] = should_end

        # ------------------------------------------------------------
        # FRONT FAILSAFE
        # garante que o conversational_front nunca devolva reply vazio
        # evitando que o WA_BOT caia no box_decider
        # ------------------------------------------------------------
        if (not reply_text) or (not str(reply_text).strip()) or _looks_like_technical_output(reply_text):
            logging.warning(
                "[CONVERSATIONAL_FRONT][FAILSAFE_REPLY] reply vazio detectado, usando pergunta de descoberta"
            )

            reply_text = (
                question
                or clarify_q
                or "Me conta um pouco melhor o teu cenário."
            )

            should_end = False
            next_step = "DISCOVERY"
            out["replyText"] = reply_text
            out["spokenText"] = reply_text
            out["shouldEnd"] = should_end
            out["nextStep"] = next_step

        return out

    except Exception as e:
        # Fail-safe absoluto: nunca quebrar o fluxo
        logging.exception("[CONVERSATIONAL_FRONT] erro, fallback silencioso: %s | user_text=%r", e, user_text)

        if free_mode:
            kb_fallback = ""
            try:
                kb_fallback = (
                    _build_kb_show_reply(
                        kb_context=kb_context if isinstance(kb_context, dict) else {},
                        practical_scene_from_kb="" if 'practical_scene_from_kb' in locals() else "",
                        example_line=example_line if 'example_line' in locals() else "",
                        effective_segment=effective_segment if 'effective_segment' in locals() else "",
                        operational_family=operational_family if 'operational_family' in locals() else "",
                        contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
                    )
                    or _build_kb_anchor_reply(
                        practical_scene_from_kb="" if 'practical_scene_from_kb' in locals() else "",
                        example_line=example_line if 'example_line' in locals() else "",
                        clarify_q=question if 'question' in locals() else "",
                        contract=operational_contract if 'operational_contract' in locals() else (base_operational_contract if 'base_operational_contract' in locals() else {}),
                    )
                )
            except Exception:
                kb_fallback = ""

            if kb_fallback:
                reply_text = kb_fallback
            elif question:
                reply_text = question
            else:
                reply_text = (
                    question
                    or clarify_q
                    or "Me conta um pouco melhor o teu cenário."
                )
            if _looks_like_technical_output(reply_text):
                reply_text = (
                    question
                    or clarify_q
                    or "Me conta um pouco melhor o teu cenário."
                )
            spoken_text = reply_text
        else:
            reply_text = "Me conta um pouquinho melhor o que você quer resolver?"
            spoken_text = reply_text

        error_out = {
            "replyText": reply_text,
            "spokenText": spoken_text,
            "understanding": {
                "topic": "OTHER",
                "confidence": "low",
            },
            "nextStep": "NONE",
            "shouldEnd": False,
            "nameUse": "clarify",
            # ✅ Em erro, NÃO forçar texto: deixa o worker decidir canal (entra áudio -> sai áudio).
            "prefersText": False,
            "replySource": "front_error",
            "kbSnapshotSizeChars": len((kb_snapshot or "")),
            "tokenUsage": {},
        }

        aiMeta = error_out.setdefault("aiMeta", {})

        # 🔒 Normalização de tipos (evita string "True"/"False")
        aiMeta["kbUsed"] = bool(aiMeta.get("kbUsed"))
        aiMeta["kbRequiredOk"] = bool(aiMeta.get("kbRequiredOk"))

        aiMeta.setdefault("usedFallback", False)

        aiMeta["responseOrigin"] = "conversational_front"

        aiMeta["kbHasContext"] = bool(aiMeta.get("kbDocPath"))

        return error_out
