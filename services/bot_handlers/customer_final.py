# services/bot_handlers/customer_final.py
# Cliente Final — “Modo SHOW” por N turnos + fallback econômico (legacy)
# Objetivo: atender no WABA do profissional usando persona + preços + agenda + acervo (mini-RAG) com controle de custo.

from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, Optional, Tuple

# Turnos “SHOW” (IA mais caprichada) antes de cair no econômico
CUSTOMER_FINAL_AI_TURNS = int(os.getenv("CUSTOMER_FINAL_AI_TURNS", "5") or "5")

# TTL do contador por contato
_TURNS_TTL_SECONDS = int(os.getenv("CUSTOMER_FINAL_TURNS_TTL_SECONDS", "21600") or "21600")  # 6h

# Cache em memória (fallback). Se cache.kv existir no projeto, usamos também.
_turns_mem: Dict[str, Tuple[int, float]] = {}

def _now() -> float:
    return time.time()

def _fs_client():
    try:
        from firebase_admin import firestore  # type: ignore
        return firestore.client()
    except Exception as e:
        logging.warning("[customer_final] firestore indisponível: %s", e)
        return None

def _wa_key_digits(e164_or_any: str) -> str:
    s = (e164_or_any or "").strip()
    if not s:
        return ""
    return "".join(ch for ch in s if ch.isdigit())

def _get_contact_key(uid: str, ctx: Optional[Dict[str, Any]]) -> str:
    """
    Tenta uma chave estável por contato para contar turnos.
    Preferência:
      1) ctx.waKeyDigits (se o worker passou)
      2) ctx.from_e164 / ctx.from_raw
      3) fallback vazio
    """
    if not isinstance(ctx, dict):
        return ""
    for k in ("waKeyDigits", "from_e164", "fromE164", "from_raw", "from"):
        v = str(ctx.get(k) or "").strip()
        if v:
            return _wa_key_digits(v)
    return ""

def _kv_get(uid: str, key: str):
    try:
        from cache.kv import get as kv_get  # type: ignore
        return kv_get(uid, key)
    except Exception:
        return None

def _kv_put(uid: str, key: str, value: Any, ttl_sec: int = 1800) -> bool:
    try:
        from cache.kv import put as kv_put  # type: ignore
        return bool(kv_put(uid, key, value, ttl_sec=ttl_sec))
    except Exception:
        return False

def _turns_key(uid: str, contact_key: str) -> str:
    uid = (uid or "").strip().lower()
    contact_key = (contact_key or "").strip()
    return f"customer_final_turns::{uid}::{contact_key}"[:480]

def _get_and_bump_turns(uid: str, contact_key: str) -> int:
    """
    Incrementa e retorna o número de turnos desta conversa (por TTL).
    """
    if not uid or not contact_key:
        return 1

    k = _turns_key(uid, contact_key)
    now = _now()

    # 1) tenta cache.kv
    row = _kv_get(uid, k)
    if isinstance(row, dict):
        exp = float(row.get("exp") or 0.0)
        n = int(row.get("n") or 0)
        if exp and exp > now:
            n = n + 1
            _kv_put(uid, k, {"n": n, "exp": now + _TURNS_TTL_SECONDS}, ttl_sec=_TURNS_TTL_SECONDS)
            return max(1, n)

    # 2) fallback memória
    n0, exp0 = _turns_mem.get(k, (0, 0.0))
    if exp0 and exp0 > now:
        n1 = int(n0) + 1
    else:
        n1 = 1
    _turns_mem[k] = (n1, now + _TURNS_TTL_SECONDS)

    # best-effort: grava no kv também
    _kv_put(uid, k, {"n": n1, "exp": now + _TURNS_TTL_SECONDS}, ttl_sec=_TURNS_TTL_SECONDS)
    return max(1, n1)

def _get_robot_persona(ctx: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(ctx, dict):
        return {}
    rp = ctx.get("robotPersona")
    return rp if isinstance(rp, dict) else {}

def _load_prof_catalog_snapshot(uid: str) -> Dict[str, Any]:
    """
    Snapshot curto e barato do “contexto do profissional” pra respostas:
    - config.jeitoAtenderV1 / robotPersona já vem no ctx (ideal)
    - produtosEServicos: nomes, preços, duração
    - schedule_rules: regras básicas
    - email/empresa: pra disparos posteriores (não envia aqui, só ajuda a IA)
    """
    db = _fs_client()
    if not db or not uid:
        return {}

    out: Dict[str, Any] = {}
    try:
        prof = db.collection("profissionais").document(uid).get()
        pdata = prof.to_dict() or {}
        cfg = pdata.get("config") or {}

        # “verdades” mínimas (curtas)
        out["displayName"] = (pdata.get("display_name") or pdata.get("displayName") or pdata.get("nome") or "").strip()
        out["email"] = (pdata.get("email") or pdata.get("contatoEmail") or "").strip()

        # schedule_rules pode estar em doc separado em alguns setups
        out["schedule_rules"] = pdata.get("schedule_rules") or cfg.get("schedule_rules") or {}

    except Exception as e:
        logging.info("[customer_final] snapshot prof falhou: %s", e)

    # produtosEServicos: subcoleção (preferido)
    try:
        items = []
        q = db.collection(f"profissionais/{uid}/produtosEServicos").limit(80).stream()
        for d in q:
            it = d.to_dict() or {}
            nome = (it.get("nome") or it.get("name") or "").strip()
            if not nome:
                continue
            items.append({
                "nome": nome[:60],
                "preco": it.get("precoBase") or it.get("preco") or it.get("valor"),
                "duracaoMin": it.get("duracaoMin") or it.get("duracao") or it.get("tempoMin"),
            })
        if items:
            out["produtosEServicos"] = items
    except Exception:
        # ok: não quebra
        pass

    return out

def _format_catalog_brief(snap: Dict[str, Any]) -> str:
    """
    Converte o snapshot em texto curto (economia de tokens).
    """
    if not isinstance(snap, dict) or not snap:
        return ""

    lines = []
    name = (snap.get("displayName") or "").strip()
    if name:
        lines.append(f"Profissional: {name}")

    items = snap.get("produtosEServicos")
    if isinstance(items, list) and items:
        # até 12 itens pra não estourar
        brief = []
        for it in items[:12]:
            if not isinstance(it, dict):
                continue
            nm = str(it.get("nome") or "").strip()
            if not nm:
                continue
            preco = it.get("preco")
            dur = it.get("duracaoMin")
            extra = []
            if preco is not None and str(preco).strip():
                extra.append(f"R$ {preco}")
            if dur is not None and str(dur).strip():
                extra.append(f"{dur} min")
            if extra:
                brief.append(f"- {nm} ({', '.join(extra)})")
            else:
                brief.append(f"- {nm}")
        if brief:
            lines.append("Serviços:")
            lines.extend(brief)

    return "\n".join(lines).strip()

def _try_acervo(uid: str, text: str) -> Optional[str]:
    """
    Mini-RAG do acervo do profissional (Storage+index por trás via domain.acervo).
    Reaproveita o domínio que já existe no projeto.
    """
    try:
        from domain.acervo import query_acervo_for_uid  # type: ignore
    except Exception:
        return None

    t = (text or "").strip()
    if len(t) < 8:
        return None

    try:
        max_tokens = int(os.getenv("LLM_MAX_TOKENS_ACERVO", "120") or "120")
    except Exception:
        max_tokens = 120

    try:
        res = query_acervo_for_uid(uid=uid, pergunta=t, max_tokens=max_tokens)
        if not isinstance(res, dict):
            return None
        if str(res.get("reason") or "").lower() != "ok":
            return None
        ans = str(res.get("answer") or "").strip()
        return ans or None
    except Exception:
        logging.exception("[customer_final] acervo query falhou")
        return None

def _call_llm_min(text: str, persona: Dict[str, Any], catalog_brief: str) -> str:
    """
    LLM curtinho (gpt-4o-mini), com contexto compacto.
    Não coloca histórico longo. Sem link. Sem viagem.
    """
    model = (os.getenv("CUSTOMER_FINAL_MODEL", "") or os.getenv("LLM_MODEL_ACERVO", "gpt-4o-mini")).strip()
    try:
        max_tokens = int(os.getenv("CUSTOMER_FINAL_MAX_TOKENS", "220") or "220")
    except Exception:
        max_tokens = 220

    # Persona “casca” (tom/emoji/fecho) — simples e barato
    tone = str(persona.get("tone") or "").strip()
    emojis = str(persona.get("emojis") or persona.get("use_emojis") or "").strip().lower() in ("1", "true", "sim", "yes", "on")

    sys = (
        "Você é um atendente de WhatsApp de um pequeno negócio.\n"
        "Seja direto, útil e educado.\n"
        "Use frases curtas.\n"
        "Nunca invente preço ou horário.\n"
        "Se faltar dado, faça 1 pergunta objetiva.\n"
    )
    if tone:
        sys += f"Tom: {tone}.\n"
    if emojis:
        sys += "Pode usar 1 emoji no máximo.\n"

    user = "Mensagem do cliente:\n" + (text or "").strip()
    if catalog_brief:
        user += "\n\nCatálogo/Contexto do profissional (resumo):\n" + catalog_brief

    try:
        # usa requests no padrão do teu worker (mesmo estilo do ycloud_tasks)
        import requests  # type: ignore

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            return "Consigo te ajudar, mas aqui estou sem a chave da IA. Me diz: você quer *preço* ou *agendar*?"

        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ],
        }
        r = requests.post(url, headers=headers, json=payload, timeout=18)
        if r.status_code != 200:
            return "Boa — me diz só qual serviço você quer e, se for agendar, qual dia e horário?"
        j = r.json() or {}
        content = (((j.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        out = (content or "").strip()
        return out[:900] if out else "Me diz: você quer orçamento ou agendar?"
    except Exception:
        return "Me diz rapidinho: é *preço* ou *agendar*?"

def generate_reply(uid: str, text: str, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Retorna dict no padrão do wa_bot:
      { ok, route, replyText, aiMeta, ... }
    """
    uid = (uid or "").strip()
    t = (text or "").strip()
    if not uid or not t:
        return {"ok": True, "route": "customer_final", "replyText": "Oi! Me diz o que você precisa 🙂"}

    persona = _get_robot_persona(ctx)
    contact_key = _get_contact_key(uid, ctx)
    turn_n = _get_and_bump_turns(uid, contact_key) if contact_key else 1

    # 1) Primeiro: tenta acervo (perguntas de conteúdo). Barato e assertivo.
    acervo_ans = _try_acervo(uid, t)
    if acervo_ans:
        return {
            "ok": True,
            "route": "customer_final_acervo",
            "replyText": acervo_ans,
            "aiMeta": {
                "mode": "acervo",
                "turn": turn_n,
                "kbUsed": True,
                "kbSource": "domain.acervo",
            },
        }

    # 2) Modo SHOW (N turnos): LLM curtinho + snapshot compacto do catálogo
    if turn_n <= max(1, CUSTOMER_FINAL_AI_TURNS):
        snap = _load_prof_catalog_snapshot(uid)
        catalog_brief = _format_catalog_brief(snap)
        reply = _call_llm_min(t, persona, catalog_brief)
        return {
            "ok": True,
            "route": "customer_final_ai",
            "replyText": reply,
            "aiMeta": {
                "mode": "ai",
                "turn": turn_n,
                "model": (os.getenv("CUSTOMER_FINAL_MODEL", "") or os.getenv("LLM_MODEL_ACERVO", "gpt-4o-mini")).strip(),
                "catalogBriefChars": len(catalog_brief or ""),
                "personaUsed": bool(persona),
            },
        }

    # 3) Depois: econômico (pede só o essencial)
    return {
        "ok": True,
        "route": "customer_final_econ",
        "replyText": "Perfeito. Pra eu te ajudar sem enrolar: você quer *preço* ou *agendar*? Se for agendar, me diga o dia e o horário.",
        "aiMeta": {"mode": "econ", "turn": turn_n},
    }
