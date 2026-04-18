# -*- coding: utf-8 -*-
"""services/kb_resolver.py

Pequeno "selector" de conhecimento para o Conversational Front (Módulo 1 — Vendas SHOW).

Objetivo:
- Não entupir o prompt com o KB inteiro
- Puxar só fatos e frases que evitam alucinação (ex.: SLA) e ajudam a vender com clareza
- Ser 100% seguro: se falhar, o front segue com o snapshot compacto (fallback)
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict


_TIME_ASK_RE = re.compile(
    r"\b(quanto\s*tempo|demora|prazo|sla|quando\s+(fica|fica\s+pronto|começa)|ativar|ativaç[aã]o)\b",
    re.I,
)
_CANCEL_RE = re.compile(r"\b(cancela|cancelar|sem\s+fidelidade|parar|sair)\b", re.I)
_PRICE_RE = re.compile(r"\b(pre[cç]o|quanto\s+custa|valor|mensalidade|plano|assinatura)\b", re.I)
_TRIAL_RE = re.compile(r"\b(gr[aá]tis|teste\s+gr[aá]tis|trial|testar\s+gr[aá]tis)\b", re.I)
_SIGNUP_LINK_RE = re.compile(r"\b(me\s+manda\s+o\s+link|manda\s+o\s+link|me\s+passa\s+o\s+link|qual\s+o\s+link|onde\s+assino|onde\s+eu\s+assino|me\s+passa\s+o\s+site|qual\s+site|me\s+manda\s+o\s+site|site\s+do\s+mei\s+rob[oó]|link\s+pra\s+assinar)\b", re.I)
_START_RE = re.compile(
    r"\b(quero\s+come[cç]ar(\s+agora)?|vamos\s+come[cç]ar|bora\s+come[cç]ar|quero\s+usar(\s+agora)?|como\s+eu\s+come[cç]o|como\s+come[cç]a)\b",
    re.I,
)


def _try_parse_kb_json(kb_snapshot: str) -> Dict[str, Any]:
    try:
        s = (kb_snapshot or "").strip()
        if not s:
            return {}
        if not (s.startswith("{") or s.startswith("[")):
            return {}
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _get(d: Dict[str, Any], path: str, default: Any = "") -> Any:
    """Get nested path like 'process_facts.process_sla_text'."""
    try:
        cur: Any = d
        for part in path.split("."):
            if not isinstance(cur, dict):
                return default
            cur = cur.get(part)
        return cur if cur is not None else default
    except Exception:
        return default



def _safe_json_loads(s: str) -> Any:
    try:
        ss = (s or "").strip()
        if not ss:
            return None
        if not (ss.startswith("{") or ss.startswith("[")):
            return None
        return json.loads(ss)
    except Exception:
        return None


def _extract_platform_pricing(obj: Any) -> Dict[str, Any]:
    """
    Extrai preço do snapshot quando existir algo equivalente a:
    platform_pricing/current -> current -> display_prices/plans
    Retorna dict vazio se não encontrar.
    """
    out: Dict[str, Any] = {}
    if not isinstance(obj, dict):
        return out

    candidates = []
    # formatos comuns: {"platform_pricing": {"current": {...}}}
    pp = obj.get("platform_pricing")
    if isinstance(pp, dict):
        candidates.append(pp.get("current"))
        # às vezes vem como {"platform_pricing": {"current": {"current": {...}}}}
        c1 = pp.get("current")
        if isinstance(c1, dict):
            candidates.append(c1.get("current"))

    # formatos alternativos: {"platform_pricing/current": {...}}
    key_direct = obj.get("platform_pricing/current")
    if isinstance(key_direct, dict):
        candidates.append(key_direct.get("current") or key_direct)

    # fallback: {"current": {...}} no topo (não ideal, mas ajuda em snapshots compactos)
    top_current = obj.get("current")
    if isinstance(top_current, dict):
        # só aceita se tiver cara de pricing
        if isinstance(top_current.get("display_prices"), dict) or isinstance(top_current.get("plans"), dict):
            candidates.append(top_current)

    # escolhe o primeiro válido
    cur = None
    for c in candidates:
        if isinstance(c, dict) and (isinstance(c.get("display_prices"), dict) or isinstance(c.get("plans"), dict)):
            cur = c
            break
    if not isinstance(cur, dict):
        return out

    disp = cur.get("display_prices") if isinstance(cur.get("display_prices"), dict) else {}
    plans = cur.get("plans") if isinstance(cur.get("plans"), dict) else {}

    # canonical: starter/starter_plus
    starter_disp = str((disp or {}).get("starter") or "").strip()
    plus_disp = str((disp or {}).get("starter_plus") or "").strip()

    starter_plan = (plans or {}).get("starter") if isinstance((plans or {}).get("starter"), dict) else {}
    plus_plan = (plans or {}).get("starter_plus") if isinstance((plans or {}).get("starter_plus"), dict) else {}

    try:
        starter_cents = int(starter_plan.get("price_cents")) if starter_plan.get("price_cents") is not None else None
    except Exception:
        starter_cents = None
    try:
        plus_cents = int(plus_plan.get("price_cents")) if plus_plan.get("price_cents") is not None else None
    except Exception:
        plus_cents = None

    currency = str(cur.get("currency") or "").strip() or "BRL"
    notes = str(cur.get("notes") or "").strip()
    billing_model = str(cur.get("billing_model") or "").strip()
    version = cur.get("version")

    if starter_disp:
        out["starter_display"] = starter_disp
    if plus_disp:
        out["starter_plus_display"] = plus_disp
    if starter_cents is not None:
        out["starter_price_cents"] = starter_cents
    if plus_cents is not None:
        out["starter_plus_price_cents"] = plus_cents
    if currency:
        out["currency"] = currency
    if billing_model:
        out["billing_model"] = billing_model
    if notes:
        out["pricing_notes"] = notes
    if version is not None:
        out["pricing_version"] = version
    return out


def _resolve_pack_id(intent_hint: str) -> str:
    i = str(intent_hint or "").strip().upper()
    if i in ("SCHEDULING", "AGENDA", "AGENDAR"):
        return "PACK_A_AGENDA"
    if i in ("WHAT_IS", "SERVICOS", "PRECO", "PRICING", "TRIAL"):
        return "PACK_B_SERVICOS"
    if i in ("ORCAMENTO", "PEDIDOS", "QUOTE", "ORDER"):
        return "PACK_C_PEDIDOS"
    if i in ("STATUS", "PROCESS", "PROCESS_SLA", "SLA"):
        return "PACK_D_STATUS"
    return ""


def _extract_pack_micro_scene(kb: Dict[str, Any], pack_id: str) -> str:
    try:
        packs = kb.get("value_packs_v1") or {}
        if not isinstance(packs, dict):
            return ""
        pack = packs.get(str(pack_id or "").strip().upper()) or {}
        if not isinstance(pack, dict):
            return ""
        runtime_short = pack.get("runtime_short") or {}
        if not isinstance(runtime_short, dict):
            return ""
        return str(runtime_short.get("micro_scene") or "").strip()
    except Exception:
        return ""


def _extract_segment_example_line(kb: Dict[str, Any], segment_key: str, pack_id: str) -> str:
    try:
        seg_map = kb.get("segment_value_map_v1") or {}
        if not isinstance(seg_map, dict):
            return ""
        seg = seg_map.get(str(segment_key or "").strip().lower()) or {}
        if not isinstance(seg, dict):
            return ""
        tokens = seg.get("tokens") or {}
        if not isinstance(tokens, dict):
            return ""
        pack_tokens = tokens.get(str(pack_id or "").strip().upper()) or {}
        if not isinstance(pack_tokens, dict):
            return ""
        return str(pack_tokens.get("example_line") or "").strip()
    except Exception:
        return ""


def _extract_segment_pack_tokens(kb: Dict[str, Any], segment_key: str, pack_id: str) -> Dict[str, Any]:
    try:
        seg_map = kb.get("segment_value_map_v1") or {}
        if not isinstance(seg_map, dict):
            return {}
        seg = seg_map.get(str(segment_key or "").strip().lower()) or {}
        if not isinstance(seg, dict):
            return {}
        tokens = seg.get("tokens") or {}
        if not isinstance(tokens, dict):
            return {}
        pack_tokens = tokens.get(str(pack_id or "").strip().upper()) or {}
        if not isinstance(pack_tokens, dict):
            return {}
        out: Dict[str, Any] = {}
        for k, v in pack_tokens.items():
            if isinstance(v, (str, int, float, bool)):
                sv = str(v).strip() if not isinstance(v, bool) else v
                if sv != "":
                    out[str(k)] = sv
        return out
    except Exception:
        return {}



def _extract_segment_profile(kb: Dict[str, Any], segment_key: str) -> Dict[str, Any]:
    try:
        out: Dict[str, Any] = {}
        segments = kb.get("segments") or {}
        if isinstance(segments, dict):
            seg = segments.get(str(segment_key or "").strip().lower()) or {}
            if isinstance(seg, dict):
                one_liner = str(seg.get("one_liner") or "").strip()
                one_question = str(seg.get("one_question") or "").strip()
                micro_scene = str(seg.get("micro_scene") or "").strip()
                handoff = seg.get("handoff_format") or []
                if one_liner:
                    out["one_liner"] = one_liner
                if one_question:
                    out["one_question"] = one_question
                if micro_scene:
                    out["micro_scene"] = micro_scene
                if isinstance(handoff, list):
                    out["handoff_format"] = [str(x).strip() for x in handoff if str(x).strip()]
        return out
    except Exception:
        return {}


def _as_clean_list(value: Any) -> list[str]:
    try:
        if not isinstance(value, list):
            return []
        return [str(x).strip() for x in value if str(x).strip()]
    except Exception:
        return []


def _as_clean_scalar_map(value: Any) -> Dict[str, Any]:
    try:
        if not isinstance(value, dict):
            return {}
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(v, (str, int, float, bool)):
                sv = str(v).strip() if not isinstance(v, bool) else v
                if sv != "":
                    out[str(k)] = sv
        return out
    except Exception:
        return {}


def _get_kb_segment_doc(kb: Dict[str, Any], segment_key: str) -> Dict[str, Any]:
    try:
        seg = str(segment_key or "").strip().lower()
        if not seg:
            return {}
        m = kb.get("kb_segments_v1") or {}
        if not isinstance(m, dict):
            return {}
        d = m.get(seg) or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _get_kb_subsegment_doc(kb: Dict[str, Any], subsegment_key: str) -> Dict[str, Any]:
    try:
        sub = str(subsegment_key or "").strip().lower()
        if not sub:
            return {}
        m = kb.get("kb_subsegments_v1") or {}
        if not isinstance(m, dict):
            return {}
        d = m.get(sub) or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _extract_kb_profile(doc: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if not isinstance(doc, dict):
            return {}
        out: Dict[str, Any] = {}

        for key in (
            "name",
            "description",
            "one_liner",
            "one_question",
            "micro_scene",
            "service_noun",
            "customer_noun",
            "conversion_noun",
            "conversation_mode",
            "primary_goal",
            "segment_id",
            "archetype_id",
        ):
            val = str(doc.get(key) or "").strip()
            if val:
                out[key] = val

        handoff = _as_clean_list(doc.get("handoff_format"))
        if handoff:
            out["handoff_format"] = handoff

        common_intents = _as_clean_list(doc.get("common_intents"))
        if common_intents:
            out["common_intents"] = common_intents

        preferred_capabilities = _as_clean_list(doc.get("preferred_capabilities"))
        if preferred_capabilities:
            out["preferred_capabilities"] = preferred_capabilities

        keywords = _as_clean_list(doc.get("keywords"))
        if keywords:
            out["keywords"] = keywords

        negative_keywords = _as_clean_list(doc.get("negative_keywords"))
        if negative_keywords:
            out["negative_keywords"] = negative_keywords

        ritual = _as_clean_list(doc.get("operational_ritual"))
        if ritual:
            out["operational_ritual"] = ritual

        rules = doc.get("operational_rules") or {}
        if isinstance(rules, dict):
            rr: Dict[str, Any] = {}
            for rk in ("must_do", "should_do", "avoid"):
                vals = _as_clean_list(rules.get(rk))
                if vals:
                    rr[rk] = vals
            if rr:
                out["operational_rules"] = rr

        return out
    except Exception:
        return {}


def _get_kb_archetype_doc(kb: Dict[str, Any], archetype_id: str) -> Dict[str, Any]:
    try:
        aid = str(archetype_id or "").strip().lower()
        if not aid:
            return {}
        m = kb.get("kb_archetypes_v1") or {}
        if not isinstance(m, dict):
            return {}
        d = m.get(aid) or {}
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _get_kb_capability_docs(kb: Dict[str, Any], capability_ids: list[str]) -> Dict[str, Dict[str, Any]]:
    try:
        out: Dict[str, Dict[str, Any]] = {}
        m = kb.get("kb_capabilities_v1") or {}
        if not isinstance(m, dict):
            return out
        for cid in capability_ids or []:
            key = str(cid or "").strip()
            if not key:
                continue
            doc = m.get(key) or m.get(key.lower()) or {}
            if isinstance(doc, dict) and doc:
                out[key] = doc
        return out
    except Exception:
        return {}


def _archetype_to_operational_family(archetype_id: str) -> str:
    try:
        a = str(archetype_id or "").strip().lower()
        if not a:
            return ""
        if a in ("servico_agendado", "servico_agendado_com_encaixe"):
            return "agenda"
        if a in ("alimentacao_pedido",):
            return "pedidos"
        if a in ("comercio_catalogo_direto", "comercio_consultivo_presencial", "servico_tecnico_orcamento"):
            return "servicos"
        if a in ("servico_tecnico_visita", "atendimento_profissional_triagem"):
            return "triagem"
        return ""
    except Exception:
        return ""


def _archetype_to_pack_id(archetype_id: str) -> str:
    try:
        a = str(archetype_id or "").strip().lower()
        if a in ("servico_agendado", "servico_agendado_com_encaixe"):
            return "PACK_A_AGENDA"
        if a in ("alimentacao_pedido",):
            return "PACK_C_PEDIDOS"
        if a in ("comercio_catalogo_direto", "comercio_consultivo_presencial", "servico_tecnico_orcamento"):
            return "PACK_B_SERVICOS"
        if a in ("servico_tecnico_visita", "atendimento_profissional_triagem"):
            return "PACK_B_SERVICOS"
        return ""
    except Exception:
        return ""


def _build_scene_from_kb_profile(profile: Dict[str, Any]) -> str:
    try:
        if not isinstance(profile, dict):
            return ""
        micro_scene = str(profile.get("micro_scene") or "").strip()
        one_liner = str(profile.get("one_liner") or "").strip()
        ritual = profile.get("operational_ritual") or []
        service_noun = str(profile.get("service_noun") or "").strip()

        if micro_scene:
            return micro_scene

        if isinstance(ritual, list) and ritual:
            steps = [str(x).strip() for x in ritual if str(x).strip()]
            if steps:
                return " → ".join(steps)

        if one_liner and service_noun:
            return f"Cliente chama por {service_noun} → robô conduz a conversa → próximo passo fica claro."
        if one_liner:
            return one_liner
        return ""
    except Exception:
        return ""


def _norm_text(s: str) -> str:
    try:
        t = str(s or "").strip().lower()
        repl = {
            "á": "a", "à": "a", "ã": "a", "â": "a",
            "é": "e", "ê": "e",
            "í": "i",
            "ó": "o", "ô": "o", "õ": "o",
            "ú": "u",
            "ç": "c",
        }
        for k, v in repl.items():
            t = t.replace(k, v)
        t = re.sub(r"\s{2,}", " ", t)
        return t.strip()
    except Exception:
        return str(s or "").strip().lower()


def _score_kb_doc_match(user_text: str, doc_key: str, doc: Dict[str, Any]) -> int:
    try:
        if not isinstance(doc, dict):
            return 0
        ut = _norm_text(user_text)
        if not ut:
            return 0

        score = 0

        fields_boost = [
            (doc_key, 5),
            (doc.get("name"), 6),
            (doc.get("description"), 2),
            (doc.get("one_liner"), 3),
            (doc.get("micro_scene"), 3),
            (doc.get("service_noun"), 4),
        ]
        for raw, weight in fields_boost:
            val = _norm_text(str(raw or ""))
            if val and val in ut:
                score += weight

        for kw in _as_clean_list(doc.get("keywords")):
            if _norm_text(kw) in ut:
                score += 4

        for ci in _as_clean_list(doc.get("common_intents")):
            if _norm_text(ci.replace("_", " ")) in ut:
                score += 3

        for rk in _as_clean_list(doc.get("operational_ritual")):
            if _norm_text(rk) in ut:
                score += 2

        for nk in _as_clean_list(doc.get("negative_keywords")):
            if _norm_text(nk) in ut:
                score -= 5

        return score
    except Exception:
        return 0


def _infer_segment_from_kb(kb: Dict[str, Any], user_text: str) -> Dict[str, str]:
    try:
        out = {"segment_id": "", "subsegment_id": ""}
        ut = str(user_text or "").strip()
        if not ut:
            return out

        best_sub = ""
        best_sub_score = 0
        sub_map = kb.get("kb_subsegments_v1") or {}
        if isinstance(sub_map, dict):
            for key, doc in sub_map.items():
                if not isinstance(doc, dict):
                    continue
                sc = _score_kb_doc_match(ut, str(key), doc)
                if sc > best_sub_score:
                    best_sub_score = sc
                    best_sub = str(key).strip().lower()

        if best_sub and best_sub_score >= 6:
            parent = str(_get_kb_subsegment_doc(kb, best_sub).get("segment_id") or "").strip().lower()
            out["subsegment_id"] = best_sub
            out["segment_id"] = parent
            return out

        best_seg = ""
        best_seg_score = 0
        seg_map = kb.get("kb_segments_v1") or {}
        if isinstance(seg_map, dict):
            for key, doc in seg_map.items():
                if not isinstance(doc, dict):
                    continue
                sc = _score_kb_doc_match(ut, str(key), doc)
                if sc > best_seg_score:
                    best_seg_score = sc
                    best_seg = str(key).strip().lower()

        if best_seg and best_seg_score >= 6:
            out["segment_id"] = best_seg
            return out

        return out
    except Exception:
        return {"segment_id": "", "subsegment_id": ""}


def _archetype_to_intent_hint(archetype_id: str) -> str:
    try:
        a = str(archetype_id or "").strip().lower()
        if a in ("servico_agendado", "servico_agendado_com_encaixe"):
            return "AGENDA"
        if a in ("alimentacao_pedido",):
            return "PEDIDOS"
        if a in ("comercio_catalogo_direto", "comercio_consultivo_presencial", "servico_tecnico_orcamento"):
            return "SERVICOS"
        if a in ("servico_tecnico_visita", "atendimento_profissional_triagem"):
            return "PROCESSO"
        return ""
    except Exception:
        return ""


def _normalize_operational_family(value: str) -> str:
    try:
        v = str(value or "").strip().lower()
        if not v:
            return ""
        aliases = {
            "pedido": "pedidos",
            "pedidos": "pedidos",
            "agenda": "agenda",
            "agendamento": "agenda",
            "agendamentos": "agenda",
            "servico": "servicos",
            "serviços": "servicos",
            "servicos": "servicos",
            "orcamento": "servicos",
            "orçamento": "servicos",
            "triagem": "triagem",
            "cadastro": "triagem",
            "qualificacao": "triagem",
            "qualificação": "triagem",
            "status": "status",
            "acompanhamento": "status",
        }
        return aliases.get(v, v)
    except Exception:
        return ""


def _pick_family_value(kb: Dict[str, Any], family: str, *keys: str) -> str:
    try:
        fam = str(family or "").strip().lower()
        if not fam:
            return ""
        family_map = _get(kb, "operational_families", {}) or {}
        fam_block = family_map.get(fam) if isinstance(family_map, dict) else {}
        if not isinstance(fam_block, dict):
            fam_block = {}
        for key in keys:
            val = str(fam_block.get(key, "") or "").strip()
            if val:
                return val
    except Exception:
        pass
    return ""


def _build_detailed_scene(*, pack_id: str, pack_micro_scene: str, segment_example_line: str, segment_tokens: Dict[str, Any], segment_profile: Dict[str, Any]) -> str:
    try:
        p = str(pack_id or "").strip().upper()
        ms = str(pack_micro_scene or "").strip()
        ex = str(segment_example_line or "").strip()

        service_noun = str((segment_tokens or {}).get("service_noun") or "atendimento").strip()
        channel_variant = str((segment_tokens or {}).get("channel_variant") or "").strip()
        order_noun = str((segment_tokens or {}).get("order_noun") or "pedido").strip()
        delivery_terms = str((segment_tokens or {}).get("delivery_terms") or "").strip()
        status_noun = str((segment_tokens or {}).get("status_noun") or "status").strip()
        case_example = str((segment_tokens or {}).get("case_example") or "").strip()
        price_policy_hint = str((segment_tokens or {}).get("price_policy_hint") or "").strip()

        detail = ""
        if p == "PACK_A_AGENDA":
            detail = (
                f"Na prática: cliente pede {service_noun}; "
                f"o robô oferece opções válidas"
                f"{(' de ' + channel_variant) if channel_variant else ''}; "
                f"confirma por escrito; fica registrado."
            )
        elif p == "PACK_B_SERVICOS":
            detail = (
                f"Na prática: perguntam sobre {service_noun}; "
                f"o robô responde com base no que você cadastrou; "
                f"explica o essencial; conduz pro próximo passo."
            )
            if price_policy_hint:
                detail += f" {price_policy_hint[:140].rstrip('.')}"
        elif p == "PACK_C_PEDIDOS":
            detail = (
                f"Na prática: o cliente manda o {order_noun} em partes; "
                f"o robô confirma item por item"
                f"{(', ' + delivery_terms) if delivery_terms else ''}; "
                f"entrega resumo pronto pra executar."
            )
        elif p == "PACK_D_STATUS":
            detail = (
                f"Na prática: quando o cliente volta perguntando sobre {status_noun}; "
                f"o robô usa o que foi registrado; "
                f"responde andamento; "
                f"deixa o próximo passo claro."
            )
            if case_example:
                detail += f" Ex.: {case_example}"
        else:
            detail = ms

        parts = []
        if ex:
            parts.append(ex.rstrip("."))
        if detail:
            parts.append(detail.rstrip("."))
        elif ms:
            parts.append(ms.rstrip("."))

        out = " | ".join([x for x in parts if x]).strip()
        out = re.sub(r"\bdentro do SLA informado\.?\b", "", out, flags=re.I).strip(" |.-")
        out = re.sub(r"\s{2,}", " ", out).strip()
        return out
    except Exception:
        return ""

def build_kb_context(
    *,
    kb_snapshot: str,
    user_text: str,
    last_intent: str = "",
    segment_hint: str = "",
    operational_family_hint: str = "",
    topic_hint: str = "",
) -> Dict[str, Any]:
    """Return a compact dict with the most useful KB facts for this turn.

    Design principle:
    - IA é dona do terreno: aqui só selecionamos fatos canônicos e hints úteis.
    - Heurísticas aqui são mínimas e servem apenas como "hint" (não como roteador de conversa).
    """
    kb_obj = _safe_json_loads(kb_snapshot or "")
    kb: Dict[str, Any] = kb_obj if isinstance(kb_obj, dict) else {}

    segment_hint = str(segment_hint or "").strip().lower()
    operational_family_hint = str(operational_family_hint or "").strip().lower()
    topic_hint = str(topic_hint or "").strip().upper()

    ut = (user_text or "").strip()

    # Flags úteis pro guardrail / decisão do LLM (não decidem sozinhas, só ajudam)
    # Regra de prioridade (arquitetura): TRIAL > LINK explícito > PREÇO > SLA > geral
    try:
        is_trial = bool(_TRIAL_RE.search(ut))
        wants_link_explicit = bool(_SIGNUP_LINK_RE.search(ut))
        wants_start = bool(_START_RE.search(ut))
    except Exception:
        is_trial = False
        wants_link_explicit = False
        wants_start = False

    # Intent hint (ultra-leve): serve só pra priorizar fatos, não para decidir conversa
    intent_hint = (topic_hint or last_intent or "").strip().upper() or "OTHER"

    # 🔥 Prioridade absoluta: objeção TRIAL e pedido explícito de link
    # (mesmo que o upstream venha "PRECO", TRIAL precisa vencer para não virar "preço com desculpa".)
    if is_trial:
        intent_hint = "TRIAL"
    elif wants_link_explicit:
        intent_hint = "SIGNUP_LINK"
    elif wants_start:
        intent_hint = "ATIVAR"
    # Heurística mínima (fallback): quando upstream vier OTHER/vazio,
    # reconhece PREÇO / PROCESS_SLA / CANCEL e alguns tópicos básicos.
    elif intent_hint in ("", "OTHER"):
        if _PRICE_RE.search(ut):
            intent_hint = "PRECO"
        elif _TIME_ASK_RE.search(ut):
            intent_hint = "PROCESS_SLA"
        elif _CANCEL_RE.search(ut):
            intent_hint = "CANCEL"
        elif re.search(r"\b(agenda|agendar|marcar\s+hor[aá]rio)\b", ut, re.I):
            intent_hint = "SCHEDULING"
        elif re.search(r"\b(como\s+funciona|o\s+que\s+[ée]|explica)\b", ut, re.I):
            intent_hint = "WHAT_IS"
# Campos mais "anti-alucinação" e mais usados no Vendas SHOW
    process_sla_text = str(_get(kb, "process_facts.process_sla_text", "") or "").strip()
    sla_setup = str(_get(kb, "process_facts.sla_setup", "") or "").strip()
    can_prepare_now = str(
        _get(kb, "can_prepare_now", "") or _get(kb, "process_facts.can_prepare_now", "") or ""
    ).strip()

    # CTA / tom
    openers = _get(kb, "tone_spark.openers", []) or _get(kb, "tone_spark_v1.openers", []) or []
    closers = _get(kb, "tone_spark.closers", []) or []
    if not isinstance(openers, list):
        openers = []
    if not isinstance(closers, list):
        closers = []

    # Segment hints (se existirem no KB)
    segment_question_text = str(
        _get(kb, "segment_handling.segment_question_text", "")
        or _get(kb, "segment_handling_v1.segment_question_text", "")
        or ""
    ).strip()
    segments = _get(kb, "segments", {}) or {}

    # Value props curtas
    value_props = (
        _get(kb, "sales_pills.value_props_top3", [])
        or _get(kb, "value_props_top3", [])
        or _get(kb, "value_props", [])
        or []
    )
    if isinstance(value_props, list):
        value_props = [str(x).strip() for x in value_props if str(x).strip()]
    else:
        value_props = []

    # Pílula de cancelamento (se existir)
    no_fidelity_from_kb = str(_get(kb, "how_it_works_rich.no_fidelity", "") or "").strip()

    ctx: Dict[str, Any] = {"intent_hint": intent_hint}

    # ------------------------------------------------------
    # Resolução principal de segmento/subsegmento no KB novo
    # ------------------------------------------------------
    raw_hint = str(segment_hint or _get(kb, "segment_hint", "") or "").strip().lower()
    subsegment_hint_raw = ""
    segment_hint_raw = raw_hint

    inferred_from_kb = {"segment_id": "", "subsegment_id": ""}
    if not raw_hint:
        inferred_from_kb = _infer_segment_from_kb(kb, ut)
        subsegment_hint_raw = str(inferred_from_kb.get("subsegment_id") or "").strip().lower()
        segment_hint_raw = str(inferred_from_kb.get("segment_id") or "").strip().lower()
    elif "__" in raw_hint:
        subsegment_hint_raw = raw_hint
        seg_from_sub = str(_get_kb_subsegment_doc(kb, subsegment_hint_raw).get("segment_id") or "").strip().lower()
        if seg_from_sub:
            segment_hint_raw = seg_from_sub

    subsegment_doc = _get_kb_subsegment_doc(kb, subsegment_hint_raw)
    segment_doc = _get_kb_segment_doc(kb, segment_hint_raw)

    if segment_hint_raw:
        ctx["segment_hint"] = segment_hint_raw
        ctx["needs_segment_discovery"] = False
        ctx["segment_match_source"] = "hint_or_kb"
    else:
        ctx["needs_segment_discovery"] = True

    if subsegment_hint_raw and subsegment_doc:
        ctx["subsegment_hint"] = subsegment_hint_raw
        ctx["subsegment_match_source"] = "hint_or_kb"

    if segment_hint_raw:
        ctx["segment_id"] = segment_hint_raw
    if subsegment_hint_raw:
        ctx["subsegment_id"] = subsegment_hint_raw

    family_raw = _normalize_operational_family(
        operational_family_hint
        or _get(kb, "operational_family", "")
        or _get(kb, "family_hint", "")
        or ""
    )
    # ------------------------------------------------------
    # Prioridade: KB novo > hints antigos > pack legacy
    # ------------------------------------------------------
    segment_profile = _extract_segment_profile(kb, segment_hint_raw)
    kb_segment_profile = _extract_kb_profile(segment_doc)
    kb_subsegment_profile = _extract_kb_profile(subsegment_doc)

    # Prioridade absoluta: KB novo
    if kb_subsegment_profile:
        merged_profile = kb_subsegment_profile
    elif kb_segment_profile:
        merged_profile = kb_segment_profile
    else:
        merged_profile = segment_profile

    archetype_id = str(
        (kb_subsegment_profile or {}).get("archetype_id")
        or (kb_segment_profile or {}).get("archetype_id")
        or ""
    ).strip().lower()

    if archetype_id:
        ctx["archetype_id"] = archetype_id
        inferred_intent = _archetype_to_intent_hint(archetype_id)
        if inferred_intent:
            intent_hint = inferred_intent
            ctx["intent_hint"] = inferred_intent

    if merged_profile:
        ctx["segment_profile"] = merged_profile

    preferred_capabilities = _as_clean_list(
        (kb_subsegment_profile or {}).get("preferred_capabilities")
        or (kb_segment_profile or {}).get("preferred_capabilities")
    )
    if preferred_capabilities:
        ctx["preferred_capabilities"] = preferred_capabilities

    operational_ritual = _as_clean_list(
        (kb_subsegment_profile or {}).get("operational_ritual")
        or (kb_segment_profile or {}).get("operational_ritual")
    )
    if operational_ritual:
        ctx["operational_ritual"] = operational_ritual

    operational_rules = (
        (kb_subsegment_profile or {}).get("operational_rules")
        or (kb_segment_profile or {}).get("operational_rules")
        or {}
    )
    if isinstance(operational_rules, dict) and operational_rules:
        ctx["operational_rules"] = operational_rules

    if not family_raw:
        family_raw = _archetype_to_operational_family(archetype_id)
    if family_raw:
        ctx["operational_family"] = family_raw

    pack_id = _archetype_to_pack_id(archetype_id) or _resolve_pack_id(intent_hint)
    if pack_id:
        ctx["pack_id"] = pack_id

    pack_micro_scene = ""
    segment_example_line = ""
    segment_tokens: Dict[str, Any] = {}

    # compat com pipeline antigo
    pack_micro_scene = _extract_pack_micro_scene(kb, pack_id)
    if not pack_micro_scene:
        pack_micro_scene = str(
            (kb_subsegment_profile or {}).get("micro_scene")
            or (kb_segment_profile or {}).get("micro_scene")
            or ""
        ).strip()
    if pack_micro_scene:
        ctx["pack_micro_scene"] = pack_micro_scene

    segment_example_line = _extract_segment_example_line(kb, segment_hint_raw, pack_id)
    if not segment_example_line:
        segment_example_line = str(
            (kb_subsegment_profile or {}).get("one_liner")
            or (kb_segment_profile or {}).get("one_liner")
            or ""
        ).strip()
    if segment_example_line:
        ctx["segment_example_line"] = segment_example_line

    segment_tokens = _extract_segment_pack_tokens(kb, segment_hint_raw, pack_id)
    if not segment_tokens:
        token_source = subsegment_doc if isinstance(subsegment_doc, dict) and subsegment_doc else segment_doc
        if isinstance(token_source, dict):
            segment_tokens = _as_clean_scalar_map({
                "service_noun": token_source.get("service_noun"),
                "customer_noun": token_source.get("customer_noun"),
                "conversion_noun": token_source.get("conversion_noun"),
                "conversation_mode": token_source.get("conversation_mode"),
                "primary_goal": token_source.get("primary_goal"),
                "description": token_source.get("description"),
            })
    if segment_tokens:
        ctx["segment_pack_tokens"] = segment_tokens

    if archetype_id:
        archetype_doc = _get_kb_archetype_doc(kb, archetype_id)
        if archetype_doc:
            ctx["archetype_profile"] = archetype_doc

    if preferred_capabilities:
        cap_docs = _get_kb_capability_docs(kb, preferred_capabilities)
        if cap_docs:
            ctx["capabilities_profile"] = cap_docs

    preferred_question = str((segment_profile or {}).get("one_question") or "").strip()
    if not preferred_question:
        preferred_question = str((merged_profile or {}).get("one_question") or "").strip()
    if preferred_question and not segment_hint_raw:
        ctx["segment_question_preferred"] = preferred_question

    try:
        fam = str(ctx.get("operational_family", "") or "").strip().lower()
        if fam:
            if not ctx.get("pack_micro_scene"):
                ctx["pack_micro_scene"] = _pick_family_value(kb, fam, "pack_micro_scene", "micro_scene")
            if not ctx.get("segment_example_line"):
                ctx["segment_example_line"] = _pick_family_value(kb, fam, "example_line", "segment_example_line")
            if not ctx.get("practical_scene_from_kb"):
                ctx["practical_scene_from_kb"] = _pick_family_value(kb, fam, "practical_scene", "practical_scene_from_kb")
    except Exception:
        pass

    if merged_profile.get("micro_scene"):
        ctx["practical_scene_from_kb"] = merged_profile["micro_scene"]

    detailed_scene = _build_scene_from_kb_profile(merged_profile)
    if not detailed_scene:
        detailed_scene = _build_detailed_scene(
            pack_id=pack_id,
            pack_micro_scene=str(ctx.get("pack_micro_scene") or pack_micro_scene or ""),
            segment_example_line=str(ctx.get("segment_example_line") or segment_example_line or ""),
            segment_tokens=segment_tokens,
            segment_profile=merged_profile,
        )
    if detailed_scene:
        ritual_preview = ""
        if operational_ritual:
            ritual_preview = " → ".join([str(x).strip() for x in operational_ritual[:5] if str(x).strip()])

        caps_preview = ""
        if preferred_capabilities:
            caps_preview = ", ".join([str(x).strip().replace("_", " ") for x in preferred_capabilities[:4] if str(x).strip()])

        enriched_scene = detailed_scene
        if ritual_preview and ritual_preview.lower() not in enriched_scene.lower():
            enriched_scene = f"{enriched_scene} | Fluxo: {ritual_preview}"
        if caps_preview:
            ctx["capabilities_preview"] = caps_preview

        ctx["practical_scene_from_kb"] = enriched_scene.strip(" |")

    # Flags úteis pro guardrail (não decidem sozinhas, só ajudam)
    ctx["is_trial"] = bool(is_trial)
    ctx["wants_link_explicit"] = bool(wants_link_explicit)
    ctx["wants_start"] = bool(wants_start)
    ctx["question_policy"] = "abolished_by_default"
    ctx["question_allowed_only_for"] = ["ambiguity", "segment_plus_name", "link_permission"]
    # Objeção explícita (arquitetura): TRIAL é "policy", não só intenção
    if is_trial:
        ctx["objection"] = "TRIAL"


# Exemplo prático: preferir cena do KB novo; legado vira fallback
    try:
        if ctx.get("practical_scene_from_kb"):
            ctx["practical_example_hint"] = str(ctx.get("practical_scene_from_kb") or "").strip()
        else:
            scenario_index = _get(kb, "scenario_index", {}) or {}
            slug = ""
            if intent_hint in ("PRECO", "TRIAL"):
                lst = scenario_index.get("for_intent_price") or []
                if isinstance(lst, list) and lst:
                    slug = str(lst[0]).strip()
            elif intent_hint in ("SCHEDULING", "AGENDA", "AGENDAR"):
                lst = scenario_index.get("for_intent_operational_flow") or []
                if isinstance(lst, list) and lst:
                    slug = str(lst[0]).strip()

            if slug:
                scen = _get(kb, f"operational_value_scenarios.{slug}", "") or ""
                if isinstance(scen, dict):
                    scen = scen.get("text") or ""
                scen = str(scen).strip()
                if scen:
                    ctx["practical_example_hint"] = scen
    except Exception:
        pass

    # Hint de continuação leve para o prompt; sem forçar texto pronto
    if intent_hint in ("PRECO", "TRIAL"):
        ctx["continuation_hint"] = "preço_valor"
    elif intent_hint in ("ATIVAR", "SIGNUP_LINK"):
        ctx["continuation_hint"] = "assinatura_leve"
    else:
        ctx["continuation_hint"] = "uso_pratico"

    # Preço canônico (platform_pricing/current) — não inventa; só usa o que vier do KB.
    try:
        pricing = _extract_platform_pricing(kb)
        if pricing:
            starter_disp = str(pricing.get("starter_display") or "").strip()
            plus_disp = str(pricing.get("starter_plus_display") or "").strip()

            if starter_disp:
                ctx["price_text_exact"] = starter_disp
                ctx["plan_name"] = "Starter"
            if plus_disp:
                ctx["price_text_plus_exact"] = plus_disp
                ctx["plan_name_plus"] = "Starter Plus"

            if pricing.get("starter_price_cents") is not None:
                ctx["price_cents"] = pricing.get("starter_price_cents")
            if pricing.get("starter_plus_price_cents") is not None:
                ctx["price_plus_cents"] = pricing.get("starter_plus_price_cents")

            ctx["currency"] = str(pricing.get("currency") or "BRL")
            if pricing.get("billing_model"):
                ctx["billing_model"] = pricing.get("billing_model")

            # Hint de pricing SHOW (não obriga formato, só dá munição pro LLM não cair em "a partir de")
            if starter_disp:
                parts = [f"Starter: {starter_disp}/mês"]
                if plus_disp:
                    parts.append(f"Starter Plus: {plus_disp}/mês")
                    ctx["pricing_has_two_plans"] = True
                else:
                    ctx["pricing_has_two_plans"] = False
                ctx["pricing_show_hint"] = " | ".join(parts)
                if ctx.get("billing_model"):
                    ctx["pricing_billing_model"] = str(ctx.get("billing_model"))
    except Exception:
        pass

    # no_fidelity: prefere KB; se não vier, usa frase fixa (regra de produto) como fallback.
    if no_fidelity_from_kb:
        ctx["no_fidelity"] = no_fidelity_from_kb
    else:
        ctx["no_fidelity"] = "sem fidelidade"

    # SLA: só se tiver algo no KB
    if process_sla_text:
        ctx["process_sla_text_exact"] = process_sla_text
    elif sla_setup:
        ctx["sla_setup_exact"] = sla_setup

    if can_prepare_now:
        ctx["can_prepare_now"] = can_prepare_now

    if value_props:
        ctx["value_props_top3"] = value_props[:3]

    if segment_question_text:
        ctx["segment_question_text"] = segment_question_text

    # Front: por padrão não perguntar.
    # Só liberar quando houver descoberta real pendente.
    if segment_hint_raw or subsegment_hint_raw:
        ctx["allow_question"] = False
    else:
        ctx["allow_question"] = True

    # 1 CTA forte (fallback): usado só por camadas legadas
    if "cta_question_strong" not in ctx:
        if intent_hint in ("ATIVAR", "SIGNUP_LINK"):
            ctx["cta_question_strong"] = "Quer que eu te passe o caminho mais curto pra começar agora?"
        else:
            ctx["cta_question_strong"] = "Quer que eu te mostre como isso ficaria no teu dia a dia?"

    # Opcional: se o KB tiver perguntas por segmento, deixamos disponível (sem forçar)
    try:
        if isinstance(segments, dict) and segments:
            sample: Dict[str, Any] = {}
            for k in list(segments.keys())[:3]:
                v = segments.get(k) or {}
                if isinstance(v, dict):
                    oq = str(v.get("one_question") or "").strip()
                    ol = str(v.get("one_liner") or "").strip()
                    if oq or ol:
                        sample[k] = {"one_liner": ol, "one_question": oq}
            if sample:
                ctx["segments_sample"] = sample
    except Exception:
        pass

    # Um opener curto (se houver)
    try:
        if openers:
            ctx["opener_hint"] = str(openers[0]).strip()
    except Exception:
        pass

    try:
        if not ctx.get("operational_family"):
            preferred_discovery = str(
                _get(kb, "discovery_question_hint", "")
                or _get(kb, "segment_question_preferred", "")
                or ""
            ).strip()
            if preferred_discovery:
                ctx["discovery_question_hint"] = preferred_discovery
            elif not ctx.get("discovery_question_hint"):
                ctx["discovery_question_hint"] = (
                    "Hoje no WhatsApp, o que você precisa responder ou organizar manualmente para os clientes?"
                )
    except Exception:
        pass

    return ctx
