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
    return _pick_pack_by_intent(intent) or "PACK_B_SERVICOS"


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

    seg = (segment or "").strip().lower()
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

    rm = (render_mode or "").strip().lower()
    if rm not in ("short", "long"):
        rm = str(policy.get("default_render_mode") or "short").strip().lower() or "short"

    # Render
    if rm == "long":
        txt = _safe_str(((pack.get("runtime_long") or {}) if isinstance(pack, dict) else {}).get("text"))
    else:
        txt = _safe_str(((pack.get("runtime_short") or {}) if isinstance(pack, dict) else {}).get("micro_scene"))

    reply = _fill_template(txt, slots)

    # Complemento leve (exemplo) se existir e não ficou redundante
    ex = _safe_str(slots.get("example_line"))
    if ex and ex not in reply:
        # 2 linhas no máximo
        if reply.endswith("."):
            reply = reply + " " + ex
        else:
            reply = reply + ". " + ex

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

    return {"replyText": reply.strip(), "packId": chosen_pack, "segment": seg, "renderMode": rm}
