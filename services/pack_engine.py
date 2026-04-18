# services/pack_engine.py
# Deterministic Value Pack renderer (packs_v1)
# - Seleciona 1 pack
# - Aplica defaults + tokens do segmento
# - Renderiza short/long sem misturar legacy
from __future__ import annotations

import re
from typing import Any, Dict, Optional


def _safe_str(x: Any) -> str:
    try:
        return str(x or "").strip()
    except Exception:
        return ""


def _fill_template(tpl: str, slots: Dict[str, str]) -> str:
    s = tpl or ""
    for k, v in (slots or {}).items():
        s = s.replace("{{" + k + "}}", str(v))
    # limpa placeholders que sobraram
    s = re.sub(r"\{\{[a-zA-Z0-9_]+\}\}", "", s)
    # normaliza espaços
    s = re.sub(r"[ \t]+", " ", s).strip()
    return s


def _pick_pack_by_intent(intent: str) -> str:
    i = (intent or "").strip().upper()
    if i in ("AGENDA", "SCHEDULE"):
        return "PACK_A_AGENDA"
    if i in ("SERVICOS", "SERVICES", "PRECO", "PRICING", "WHAT_IS"):
        return "PACK_B_SERVICOS"
    if i in ("PEDIDOS", "ORDERS"):
        return "PACK_C_PEDIDOS"
    if i in ("STATUS", "PROCESSO", "PROCESS", "ATIVAR", "ACTIVATE"):
        return "PACK_D_STATUS"
    return ""


def _as_clean_list(value: Any) -> list[str]:
    try:
        if not isinstance(value, list):
            return []
        return [str(x).strip() for x in value if str(x).strip()]
    except Exception:
        return []


def _as_clean_scalar_map(value: Any) -> Dict[str, str]:
    try:
        if not isinstance(value, dict):
            return {}
        out: Dict[str, str] = {}
        for k, v in value.items():
            if v is None:
                continue
            if isinstance(v, (str, int, float, bool)):
                sv = str(v).strip() if not isinstance(v, bool) else str(v)
                if sv != "":
                    out[str(k)] = sv
        return out
    except Exception:
        return {}


def _get_kb_segments(kb: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(kb, dict):
        return {}
    m = kb.get("kb_segments_v1") or {}
    return m if isinstance(m, dict) else {}


def _get_kb_subsegments(kb: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(kb, dict):
        return {}
    m = kb.get("kb_subsegments_v1") or {}
    return m if isinstance(m, dict) else {}


def _get_kb_archetypes(kb: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(kb, dict):
        return {}
    m = kb.get("kb_archetypes_v1") or {}
    return m if isinstance(m, dict) else {}


def _get_kb_capabilities(kb: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(kb, dict):
        return {}
    m = kb.get("kb_capabilities_v1") or {}
    return m if isinstance(m, dict) else {}


def _resolve_segment_and_subsegment(
    kb: Dict[str, Any],
    segment: Optional[str],
) -> Dict[str, Any]:
    seg_raw = (segment or "").strip().lower()
    out: Dict[str, Any] = {
        "segment_key": "",
        "subsegment_key": "",
        "segment_doc": {},
        "subsegment_doc": {},
    }
    if not seg_raw:
        return out

    segs = _get_kb_segments(kb)
    subs = _get_kb_subsegments(kb)

    if "__" in seg_raw:
        sub_doc = subs.get(seg_raw) or {}
        if isinstance(sub_doc, dict) and sub_doc:
            out["subsegment_key"] = seg_raw
            out["subsegment_doc"] = sub_doc
            parent = _safe_str(sub_doc.get("segment_id")).lower()
            if parent:
                out["segment_key"] = parent
                seg_doc = segs.get(parent) or {}
                if isinstance(seg_doc, dict):
                    out["segment_doc"] = seg_doc
            return out

    seg_doc = segs.get(seg_raw) or {}
    if isinstance(seg_doc, dict) and seg_doc:
        out["segment_key"] = seg_raw
        out["segment_doc"] = seg_doc
        return out

    return out


def _merge_segment_profile(segment_doc: Dict[str, Any], subsegment_doc: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(segment_doc, dict):
        out.update(segment_doc)
    if isinstance(subsegment_doc, dict):
        out.update(subsegment_doc)
    return out


def _archetype_to_pack_id(archetype_id: str) -> str:
    a = (archetype_id or "").strip().lower()
    if a in ("servico_agendado", "servico_agendado_com_encaixe"):
        return "PACK_A_AGENDA"
    if a in ("alimentacao_pedido",):
        return "PACK_C_PEDIDOS"
    if a in ("comercio_catalogo_direto", "comercio_consultivo_presencial", "servico_tecnico_orcamento"):
        return "PACK_B_SERVICOS"
    if a in ("servico_tecnico_visita", "atendimento_profissional_triagem"):
        return "PACK_B_SERVICOS"
    return ""


def _intent_to_pack_fallback(intent: str) -> str:
    chosen = _pick_pack_by_intent(intent)
    return chosen or "PACK_B_SERVICOS"


def _extract_profile_slots(profile: Dict[str, Any]) -> Dict[str, str]:
    if not isinstance(profile, dict):
        return {}
    return _as_clean_scalar_map(
        {
            "service_noun": profile.get("service_noun"),
            "customer_noun": profile.get("customer_noun"),
            "conversion_noun": profile.get("conversion_noun"),
            "conversation_mode": profile.get("conversation_mode"),
            "primary_goal": profile.get("primary_goal"),
            "description": profile.get("description"),
            "one_liner": profile.get("one_liner"),
            "micro_scene": profile.get("micro_scene"),
        }
    )


def _build_reply_from_kb_profile(profile: Dict[str, Any], *, render_mode: str) -> str:
    if not isinstance(profile, dict):
        return ""

    micro_scene = _safe_str(profile.get("micro_scene"))
    one_liner = _safe_str(profile.get("one_liner"))
    ritual = _as_clean_list(profile.get("operational_ritual"))
    caps = _as_clean_list(profile.get("preferred_capabilities"))
    archetype_id = _safe_str(profile.get("archetype_id")).lower()
    service_noun = _safe_str(profile.get("service_noun")) or "atendimento"

    if render_mode == "short":
        if micro_scene:
            return micro_scene
        if ritual:
            return " → ".join(ritual[:5])
        return one_liner

    parts: list[str] = []
    if one_liner:
        parts.append(one_liner.rstrip(".") + ".")

    if micro_scene:
        ms = micro_scene.strip()
        if not re.search(r"^\s*na\s+pr[aá]tica\b", ms, re.I):
            ms = "Na prática: " + ms
        parts.append(ms.rstrip(".") + ".")
    elif ritual:
        parts.append("Na prática: " + " → ".join(ritual[:5]).rstrip(".") + ".")
    else:
        parts.append(f"Na prática: o cliente chama sobre {service_noun} e o robô conduz para o próximo passo claro.")

    if caps:
        if archetype_id == "alimentacao_pedido":
            parts.append("Ele conduz o pedido sem deixar solto item, entrega ou retirada, endereço e pagamento.")
        elif archetype_id in ("servico_agendado", "servico_agendado_com_encaixe"):
            parts.append("Ele organiza a conversa até a confirmação do horário ou encaixe.")
        elif archetype_id in ("comercio_catalogo_direto", "comercio_consultivo_presencial"):
            parts.append("Ele ajuda a afunilar opção, disponibilidade e próximo passo de compra ou visita.")
        elif archetype_id in ("servico_tecnico_visita", "atendimento_profissional_triagem"):
            parts.append("Ele coleta o essencial e deixa a visita, triagem ou encaminhamento bem amarrado.")

    reply = " ".join([p.strip() for p in parts if p.strip()]).strip()
    reply = re.sub(r"\s{2,}", " ", reply).strip()
    return reply


def _get_policy(kb: Dict[str, Any]) -> Dict[str, Any]:
    pb = (kb.get("answer_playbook_v1") or {}) if isinstance(kb, dict) else {}
    return (pb.get("pack_selection_policy_v1") or {}) if isinstance(pb, dict) else {}


def _get_segment_map(kb: Dict[str, Any]) -> Dict[str, Any]:
    pb = (kb.get("answer_playbook_v1") or {}) if isinstance(kb, dict) else {}
    return (pb.get("segment_value_map_v1") or {}) if isinstance(pb, dict) else {}


def _get_segment_template(kb: Dict[str, Any]) -> Dict[str, Any]:
    pb = (kb.get("answer_playbook_v1") or {}) if isinstance(kb, dict) else {}
    return (pb.get("segment_template_v1") or {}) if isinstance(pb, dict) else {}


def _select_pack_id(kb: Dict[str, Any], *, intent: str, segment: Optional[str], pack_id: Optional[str]) -> str:
    # 1) pack_id explícito (se válido)
    if pack_id:
        return pack_id

    # 1.5) KB novo: archetype do segmento/subsegmento
    resolved = _resolve_segment_and_subsegment(kb, segment)
    merged = _merge_segment_profile(
        resolved.get("segment_doc") if isinstance(resolved.get("segment_doc"), dict) else {},
        resolved.get("subsegment_doc") if isinstance(resolved.get("subsegment_doc"), dict) else {},
    )
    arch = _safe_str(merged.get("archetype_id")).lower()
    if arch:
        chosen = _archetype_to_pack_id(arch)
        if chosen:
            return chosen

    seg = (segment or "").strip().lower()
    svm = _get_segment_map(kb)
    segd = svm.get(seg) if isinstance(svm, dict) else None

    # 2) preferred_packs do segmento
    if isinstance(segd, dict):
        pref = segd.get("preferred_packs") or []
        if isinstance(pref, list) and pref:
            return _safe_str(pref[0])

    # 3) template por profile (por intent)
    st = _get_segment_template(kb)
    dp = (st.get("default_preferred_packs_by_profile") or {}) if isinstance(st, dict) else {}
    profile = ""
    i = (intent or "").strip().upper()
    if i in ("PEDIDOS", "ORDERS"):
        profile = "by_orders"
    elif i in ("AGENDA", "SCHEDULE"):
        profile = "by_schedule"
    elif i in ("STATUS", "PROCESSO", "PROCESS"):
        profile = "by_status"
    elif i in ("ATIVAR", "ACTIVATE"):
        profile = "by_status"
    elif i in ("SERVICOS", "SERVICES", "PRECO", "PRICING", "WHAT_IS"):
        profile = "by_schedule"
    packs = (dp.get(profile) or []) if isinstance(dp, dict) else []
    if isinstance(packs, list) and packs:
        return _safe_str(packs[0])

    # 4) fallback por intent
    return _intent_to_pack_fallback(intent)


def _apply_tokens(pack: Dict[str, Any], seg_tokens: Dict[str, Any]) -> Dict[str, str]:
    slots: Dict[str, str] = {}
    ss = pack.get("segment_slots") if isinstance(pack, dict) else None
    if isinstance(ss, dict):
        for k, vd in ss.items():
            if isinstance(vd, dict) and "default" in vd:
                slots[k] = _safe_str(vd.get("default"))

    # override tokens
    if isinstance(seg_tokens, dict):
        for k, v in seg_tokens.items():
            if v is None:
                continue
            slots[k] = _safe_str(v)
    return slots


def render_pack_reply(
    kb: Dict[str, Any],
    *,
    intent: str,
    segment: Optional[str] = None,
    pack_id: Optional[str] = None,
    render_mode: str = "short",
) -> Dict[str, Any]:
    policy = _get_policy(kb)
    svm = _get_segment_map(kb)

    # ------------------------------------------------------
    # REGRA COMERCIAL: OTHER vira SERVICOS no módulo 1
    # Evita resposta genérica e garante valor prático
    # ------------------------------------------------------
    if (intent or "").strip().upper() == "OTHER":
        intent = "WHAT_IS"

    resolved = _resolve_segment_and_subsegment(kb, segment)
    seg = _safe_str(resolved.get("segment_key")).lower()
    subseg = _safe_str(resolved.get("subsegment_key")).lower()
    seg_doc = resolved.get("segment_doc") if isinstance(resolved.get("segment_doc"), dict) else {}
    subseg_doc = resolved.get("subsegment_doc") if isinstance(resolved.get("subsegment_doc"), dict) else {}
    merged_profile = _merge_segment_profile(seg_doc, subseg_doc)

    segd = svm.get(seg) if isinstance(svm, dict) else None

    chosen_pack = _select_pack_id(kb, intent=intent, segment=seg or None, pack_id=pack_id)
    packs = kb.get("value_packs_v1") if isinstance(kb, dict) else None
    pack = packs.get(chosen_pack) if isinstance(packs, dict) else None
    if not isinstance(pack, dict):
        chosen_pack = "PACK_B_SERVICOS"
        pack = (packs or {}).get(chosen_pack) if isinstance(packs, dict) else {}

    # respeita do_not_use
    try:
        dnu = (segd.get("do_not_use") or []) if isinstance(segd, dict) else []
        if isinstance(dnu, list) and chosen_pack in dnu:
            chosen_pack = "PACK_B_SERVICOS"
            pack = (packs or {}).get(chosen_pack) if isinstance(packs, dict) else pack
    except Exception:
        pass

    seg_tokens = {}
    try:
        if isinstance(segd, dict):
            tmap = segd.get("tokens") or {}
            if isinstance(tmap, dict):
                seg_tokens = tmap.get(chosen_pack) or {}
    except Exception:
        seg_tokens = {}

    slots = _apply_tokens(pack, seg_tokens if isinstance(seg_tokens, dict) else {})

    # KB novo pode complementar/substituir tokens do pack antigo
    kb_slots = _extract_profile_slots(merged_profile)
    if kb_slots:
        slots.update(kb_slots)

    rm = (render_mode or "").strip().lower()
    if rm not in ("short", "long"):
        rm = str(policy.get("default_render_mode") or "short").strip().lower() or "short"

    # ------------------------------------------------------
    # Prioridade de render:
    # 1) KB novo (segmento/subsegmento real)
    # 2) pack legacy
    # ------------------------------------------------------
    reply = _build_reply_from_kb_profile(merged_profile, render_mode=rm)
    if not reply:
        if rm == "long":
            txt = _safe_str(((pack.get("runtime_long") or {}) if isinstance(pack, dict) else {}).get("text"))
        else:
            txt = _safe_str(((pack.get("runtime_short") or {}) if isinstance(pack, dict) else {}).get("micro_scene"))
        reply = _fill_template(txt, slots)

    # Complemento leve (exemplo) se existir e não ficou redundante
    ex = _safe_str(slots.get("example_line")) or _safe_str(merged_profile.get("one_liner"))
    if ex and ex not in reply:
        ex2 = ex.strip()
        # força "exemplo real" com framing consistente do Módulo 1
        if not re.search(r"^\s*na\s+pr[aá]tica\b", ex2, re.I):
            ex2 = "Na prática: " + ex2
        # 2 linhas no máximo
        if reply.endswith("."):
            reply = reply + "\n" + ex2
        else:
            reply = reply + ".\n" + ex2

    # Segment handling: se não tem segmento e policy manda perguntar só se needed
    ask_seg = False
    seg_q = ""
    try:
        sh = policy.get("segment_handling") or {}
        if isinstance(sh, dict):
            ask_only_if_needed = bool(sh.get("ask_segment_only_if_needed"))
            seg_q = _safe_str(sh.get("segment_question_text") or "Qual é seu tipo de negócio?")
            if not seg and not ask_only_if_needed:
                ask_seg = True
    except Exception:
        pass

    if ask_seg and seg_q:
        # garante 1 pergunta (se já tem ?, não anexa)
        if "?" not in reply:
            reply = (reply.rstrip(".") + ". " + seg_q).strip()

    # ✅ Contrato harmonizado com conversational_front/wa_bot:
    # - "ok" para o caller decidir se aplica
    # - "segmentKey" (canônico) + "segment" (compat)
    # - "spokenText" sempre presente (por padrão vazio)
    return {
        "ok": True,
        "replyText": reply.strip(),
        "spokenText": "",
        "packId": chosen_pack,
        "renderMode": rm,
        "segmentKey": seg,
        "subsegmentKey": subseg,
        "segment": seg,
        "replySource": "pack_engine",
    }
