\
# services/brain/router.py
# Cérebro Único (Router) — v1 (econômico)
# - Decide fit/intent/next_step/caixa
# - NÃO gera texto longo por padrão
# - Usa cache (services.cache.kv) quando disponível
# - Integrável por feature flag: BRAIN_MODE=off|shadow|on

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Optional

# Cache helpers (best-effort)
def _kv_get(key: str) -> Optional[dict]:
    try:
        from services.cache import kv  # type: ignore
        return kv.get(key)  # type: ignore
    except Exception:
        return None

def _kv_set(key: str, val: dict, ttl_seconds: int = 3600) -> None:
    try:
        from services.cache import kv  # type: ignore
        kv.set(key, val, ttl_seconds=ttl_seconds)  # type: ignore
    except Exception:
        return None

def _sha1(s: str) -> str:
    import hashlib
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()

def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s[:600]

def _brain_mode() -> str:
    try:
        m = str(os.getenv("BRAIN_MODE", "off") or "off").strip().lower()
    except Exception:
        m = "off"
    # off: desliga
    # shadow: roda e loga, mas não intercepta
    # canary: intercepta só uma fatia (ex.: 10%)
    # on: intercepta sempre (quando route_box != sales_legacy)
    if m not in ("off", "shadow", "canary", "on"):
        m = "off"
    return m

def _canary_allows() -> bool:
    """
    Canary simples (determinístico) por hash do texto normalizado.
    Default: 10% (BRAIN_CANARY_PCT=10).
    """
    try:
        pct = int(os.getenv("BRAIN_CANARY_PCT", "10") or "10")
        pct = max(0, min(100, pct))
    except Exception:
        pct = 10
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    # usa o valor já calculado no cache_key (sha1 do texto), mas aqui fazemos um hash curto
    # para não depender de libs extras.
    try:
        # gera 0..99 estável
        h = _sha1(os.getenv("BRAIN_CANARY_SEED", "v1") + str(time.time_ns()))  # fallback improvável
    except Exception:
        h = _sha1("v1")
    # acima não é determinístico; então fazemos determinístico pelo texto no decide().
    # (Essa função fica disponível, mas a lógica determinística entra no decide().)
    return True

# Minimal detectors (not "gíria catálogo" — só intenção macro)
_SOFTWARE_TERMS = (
    "programa", "programas", "software", "sistema", "sistemas",
    "app", "aplicativo", "site", "website", "plataforma",
    "desenvolver", "desenvolvimento", "programar", "programação",
    "codigo", "código", "automacao", "automação", "integracao", "integração",
)
_RECADO_TERMS = ("recado", "mensagem pro", "mensagem para", "manda um recado", "poderia avisar", "fala pra", "diz pra")
_PRICE_TERMS = ("preço", "preco", "quanto custa", "valor", "mensal", "por mês", "por mes", "assinatura")

def _mentions_meirobo(t: str) -> bool:
    return ("mei robô" in t) or ("mei robo" in t) or ("meirobo" in t)

def _looks_custom_software_quote(t: str) -> bool:
    # Guardrail: se a pessoa está perguntando preço/assinatura da *nossa* plataforma, isso é PRICE/PLANS,
    # não orçamento de software sob medida.
    if any(x in t for x in _PRICE_TERMS) and (
        "plataforma de vocês" in t
        or "plataforma de voces" in t
        or "da plataforma de vocês" in t
        or "da plataforma de voces" in t
        or "a plataforma de vocês" in t
        or "a plataforma de voces" in t
    ):
        return False
    if _mentions_meirobo(t):
        return False
    # Se o único termo de 'software' detectado for 'plataforma', exige evidência forte de sob-medida.
    has_platform = ("plataforma" in t)
    has_other_software = any(x in t for x in _SOFTWARE_TERMS if x != "plataforma")
    if has_platform and (not has_other_software):
        if any(x in t for x in ("sob medida", "pra mim", "para mim", "pra minha", "para minha", "criar", "fazer", "desenvolver", "programar")):
            return True
        return False
    if any(x in t for x in _SOFTWARE_TERMS) and any(x in t for x in _PRICE_TERMS):
        return True
    # Também: "fazem programa?" sem preço explícito
    if any(x in t for x in _SOFTWARE_TERMS) and ("vocês fazem" in t or "voces fazem" in t or "fazem" in t):
        return True
    return False

def _looks_personal_message(t: str) -> bool:
    return any(x in t for x in _RECADO_TERMS) and ("meu filho" in t or "meu marido" in t or "minha esposa" in t or "minha filha" in t)

def decide_from_sales_signals(
    *,
    text_in: str,
    stage: str,
    st: Dict[str, Any],
    nlu: Dict[str, Any],
    dec: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Decide "caixa" usando sinais já existentes do sales_lead (sem nova chamada de IA).
    Retorna um dict (plano) e, se handled=True, já inclui reply_text (early return).
    """
    mode = _brain_mode()
    t = _norm_text(text_in)

    # Cache key por texto (só para decisões out_of_scope/clarify — baratas e repetíveis)
    cache_key = f"brain:sales:v1:{_sha1(t)}:{_sha1(str(stage or ''))}"
    if mode in ("shadow", "on"):
        cached = _kv_get(cache_key)
        if isinstance(cached, dict) and cached.get("v") == 1:
            # shadow respeita: não handle
            if mode == "shadow":
                cached = dict(cached)
                cached["handled"] = False
                return cached
            return cached

    # Extract core signals
    route = str((nlu or {}).get("route") or "sales").strip().lower()
    intent = str((nlu or {}).get("intent") or "").strip().upper()
    conf = str((nlu or {}).get("confidence") or "").strip().lower()
    needs_clar = bool((nlu or {}).get("needs_clarification")) or bool((dec or {}).get("needs_clarification"))
    risk = str((nlu or {}).get("risk") or "").strip().lower() or "low"

    # Normalize confidence label
    if conf not in ("high", "mid", "low"):
        conf = "mid"

    plan: Dict[str, Any] = {
        "v": 1,
        "mode": mode,
        "route": route,
        "intent": intent or "OTHER",
        "confidence_label": conf,
        "risk": risk,
        "fit": "in_scope",
        "next_step": str((nlu or {}).get("next_step") or "").strip().upper(),
        "route_box": "sales_legacy",
        "handled": False,
        "reply_text": "",
        "reason": "",
    }


    # Canary: trata como "shadow" para a maioria e "on" para uma fatia determinística.
    # Determinístico por hash do texto (t).
    if mode == "canary":
        try:
            pct = int(os.getenv("BRAIN_CANARY_PCT", "10") or "10")
            pct = max(0, min(100, pct))
        except Exception:
            pct = 10
        bucket = int(_sha1(t)[:2], 16)  # 0..255
        hit = (bucket % 100) < pct
        plan["canary_hit"] = bool(hit)
        if not hit:
            # vira shadow (loga, não intercepta)
            plan["mode"] = "shadow"
            mode = "shadow"


    # 1) NLU/Decider pediu clarificação: router respeita (mas shadow não interrompe)
    if needs_clar:
        plan["fit"] = "unclear"
        plan["intent"] = plan["intent"] or "OTHER"
        plan["route_box"] = "clarify"
        plan["next_step"] = "ASK_ONE_Q"
        plan["reason"] = "nlu_needs_clarification"
        if mode == "on":
            from services.brain.boxes.clarify import render_one_question  # lazy
            q = str((nlu or {}).get("clarifying_question") or (dec or {}).get("clarifying_question") or "").strip()
            plan["reply_text"] = render_one_question(q)
            plan["handled"] = True

    # 2) Detecta OUT_OF_SCOPE (software sob demanda / recado pessoal)
    #    Usa sinais da NLU quando ela marcou OFFTOPIC, mas também usa detector econômico.
    if not plan["handled"]:
        off_topic = (route in ("offtopic", "off_topic", "off-topic")) or (intent == "OFFTOPIC")
        custom_quote = _looks_custom_software_quote(t)
        personal_msg = _looks_personal_message(t)

        if off_topic or custom_quote or personal_msg:
            plan["fit"] = "out_of_scope"
            if custom_quote:
                plan["intent"] = "CUSTOM_SOFTWARE_QUOTE"
                plan["reason"] = "custom_software_quote"
            elif personal_msg:
                plan["intent"] = "PERSONAL_MESSAGE_REQUEST"
                plan["reason"] = "personal_message_request"
            else:
                plan["intent"] = "OFFTOPIC"
                plan["reason"] = "nlu_offtopic"

            plan["route_box"] = "redirect"
            plan["next_step"] = "REDIRECT"

            if mode == "on":
                from services.brain.boxes.redirect import render_redirect  # lazy
                plan["reply_text"] = render_redirect(plan["intent"])
                plan["handled"] = True

    # shadow mode: nunca interrompe (só log)
    if mode == "shadow":
        plan["handled"] = False
        plan["reply_text"] = ""

    # Cache only when mode in shadow/on (and only for out_of_scope/unclear)
    if mode in ("shadow", "on"):
        if plan.get("fit") in ("out_of_scope", "unclear"):
            _kv_set(cache_key, plan, ttl_seconds=int(os.getenv("BRAIN_CACHE_TTL_SECONDS", "86400") or "86400"))

    return plan
