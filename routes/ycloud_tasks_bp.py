# routes/ycloud_tasks_bp.py
from __future__ import annotations


import json
import os
import json
import time
from datetime import datetime
import random
import re


def _backend_base(request) -> str:
    """
    Resolve a base URL interna para chamadas /api/voz/* feitas pelo WORKER.
    Blindagem: se BACKEND_BASE apontar pro webhook, usamos host_url do request (worker).
    """
    base = (os.environ.get("BACKEND_BASE_URL") or os.environ.get("BACKEND_BASE") or "").strip().rstrip("/")
    host = (getattr(request, "host_url", "") or "").strip().rstrip("/")

    if base.startswith("http://"):
        from google.cloud import storage
        from services.gcp_creds import get_storage_client
        base = "https://" + base[len("http://"):]
    if host.startswith("http://"):
        host = "https://" + host[len("http://"):]

    # se não tiver base, usa o host atual (normal em Cloud Run)
    if not base:
        return host

    # blindagem: se base aponta pro webhook, e host atual NÃO é webhook, força host (worker)
    if ("mei-robo-webhook" in base) and host and ("mei-robo-webhook" not in host):
        return host

    return base

import hashlib
import logging
import uuid
import datetime
  # type: ignore
from typing import Any, Dict, Optional, Tuple


def _ensure_send_link_in_reply(reply: str, next_step: str) -> str:
    """
    Regra canônica: se next_step == SEND_LINK, a resposta precisa conter o link (FRONTEND_BASE).
    Evita o bug: "vou te mandar o link" sem link.
    """
    try:
        ns = str(next_step or "").strip().upper()
        r = str(reply or "").strip()
        if ns != "SEND_LINK":
            return r

        base = (os.environ.get("FRONTEND_BASE") or "").strip().rstrip("/")
        if not base:
            return r  # sem base configurada, não inventa
        # já tem o link? não duplica
        if base.lower() in r.lower():
            return r
        # já tem algum http? não força (pode ser outro link gerado)
        if re.search(r"https?://", r, re.I):
            return r
        # anexa o link no final
        if r and not r.endswith((".", "!", "?", ":")):
            r = r + "."
        return (r + "\n" + base).strip()
    except Exception:
        return str(reply or "").strip()

import requests

from flask import Blueprint, request, jsonify

from services.phone_utils import digits_only as _digits_only_c, to_plus_e164 as _to_plus_e164_c

logger = logging.getLogger("mei_robo.ycloud_tasks")

# Limites para manter "entra áudio -> sai áudio" sem 413 no /api/voz/tts
_SUPPORT_TTS_MAX_CHARS = int(os.environ.get("SUPPORT_TTS_MAX_CHARS", "650") or "650")
_SUPPORT_TTS_RETRY_MAX_CHARS = int(os.environ.get("SUPPORT_TTS_RETRY_MAX_CHARS", "420") or "420")
_SUPPORT_WA_TEXT_MAX_CHARS = int(os.environ.get("SUPPORT_WA_TEXT_MAX_CHARS", "900") or "900")

_SALES_TTS_MODE = (os.environ.get("SALES_TTS_MODE") or "on").strip().lower()  # on|off
_SALES_TTS_MODEL = (os.environ.get("SALES_TTS_MODEL") or "gpt-4o-mini").strip()
_SALES_TTS_MAX_TOKENS = int(os.environ.get("SALES_TTS_MAX_TOKENS", "220") or "220")
_SALES_TTS_MAX_CHARS = int(os.environ.get("SALES_TTS_MAX_CHARS", "520") or "520")
_SALES_SITE_URL = (os.environ.get("MEI_ROBO_SITE_URL") or "www.meirobo.com.br").strip()


_SUPPORT_TTS_SUMMARY_MODE = (os.environ.get("SUPPORT_TTS_SUMMARY_MODE") or "off").strip().lower()  # on|off
_SUPPORT_TTS_SUMMARY_MODEL = (os.environ.get("SUPPORT_TTS_SUMMARY_MODEL") or "gpt-4o-mini").strip()
_SUPPORT_TTS_SUMMARY_MAX_TOKENS = int(os.environ.get("SUPPORT_TTS_SUMMARY_MAX_TOKENS", "140") or "140")

# TTS conceitual (quando há kbContext): gera fala humana usando o artigo como CONTEXTO (não script)
_SUPPORT_TTS_CONCEPT_MODE = (os.environ.get("SUPPORT_TTS_CONCEPT_MODE") or "on").strip().lower()  # on|off
_SUPPORT_TTS_CONCEPT_MODEL = (os.environ.get("SUPPORT_TTS_CONCEPT_MODEL") or _SUPPORT_TTS_SUMMARY_MODEL).strip()
_SUPPORT_TTS_CONCEPT_MAX_TOKENS = int(os.environ.get("SUPPORT_TTS_CONCEPT_MAX_TOKENS", "220") or "220")
_SUPPORT_TTS_CONCEPT_KB_MAX_CHARS = int(os.environ.get("SUPPORT_TTS_CONCEPT_KB_MAX_CHARS", "1400") or "1400")



# Humanização (nome só de vez em quando)
_SUPPORT_NAME_MIN_GAP_SECONDS = int(os.environ.get("SUPPORT_NAME_MIN_GAP_SECONDS", "600") or "600")  # 10min

# Cache leve do "persona pack" do Firestore
_SUPPORT_PERSONA_CACHE: Dict[str, Any] = {}
_SUPPORT_PERSONA_CACHE_AT: float = 0.0
_SUPPORT_PERSONA_CACHE_TTL = int(os.environ.get("SUPPORT_PERSONA_TTL_SECONDS", "600") or "600")

# Memória em-processo (não persistente) para evitar repetir nome
_LAST_NAME_SPOKEN_AT: Dict[str, float] = {}


# Memória em-processo para VENDAS (cadência separada: fechamento pode repetir nome sem esperar 10min)
_LAST_SALES_NAME_SPOKEN_AT: Dict[str, float] = {}

# Memória em-processo para CTA do site (evita spam de link a cada áudio)
_LAST_SALES_SITE_CTA_AT: Dict[str, float] = {}


def _strip_leading_name_prefix(text: str, name: str) -> tuple[str, bool]:
    """Remove prefixo 'Nome,' no início (case-insensitive)."""
    try:
        t = (text or "").strip()
        nm = (name or "").strip()
        if not t or not nm:
            return text, False
        # Aceita: "Nome, ..." | "Nome - ..." | "Nome — ..."
        pat = r"^\s*" + re.escape(nm) + r"\s*([,\-–—:])\s*"
        if re.match(pat, t, flags=re.IGNORECASE):
            t2 = re.sub(pat, "", t, count=1, flags=re.IGNORECASE).lstrip()
            return t2, True
        return text, False
    except Exception:
        return text, False


# ==========================================================
# UX: gate de uso do nome no ÁUDIO (IA sinaliza; código autoriza)
# - Texto NÃO leva nome por padrão (produto).
# - Áudio pode levar nome com cadência (sem “Roberto, Roberto…”).
# ==========================================================
_LAST_NAME_TEXT_USED: Dict[str, str] = {}   # wa_key -> "roberto" (lower)

def _maybe_name_prefix(
    *,
    tts_text: str,
    name_use: str,
    display_name: str,
    wa_key_effective: str,
) -> tuple[str, bool]:
    """
    Retorna (tts_text_com_prefixo, name_used).
    Regras:
    - Só aplica se IA pediu (name_use != 'none')
    - Só aplica se tiver display_name e wa_key_effective
    - Cadência por gap (env) + evita repetir nome já usado
    - Não aplica se o nome já estiver no texto
    """
    try:
        if not tts_text or not wa_key_effective:
            return tts_text, False
        nm = (display_name or "").strip()
        if not nm:
            return tts_text, False
        nu = (name_use or "").strip().lower()
        if not nu or nu == "none":
            return tts_text, False

        low = tts_text.lower()
        if nm.lower() in low:
            return tts_text, False

        # Gap de segurança (default 6 min)
        try:
            gap = int(os.getenv("SALES_NAME_SPOKEN_MIN_GAP_SECONDS", "360") or "360")
        except Exception:
            gap = 360

        now = time.time()
        last_at = float(_LAST_NAME_SPOKEN_AT.get(wa_key_effective) or 0.0)
        last_nm = str(_LAST_NAME_TEXT_USED.get(wa_key_effective) or "").strip().lower()
        if (now - last_at) < float(gap):
            return tts_text, False
        if last_nm and last_nm == nm.lower():
            return tts_text, False

        out = f"{nm}, " + tts_text.lstrip()

        _LAST_NAME_SPOKEN_AT[wa_key_effective] = now
        _LAST_NAME_TEXT_USED[wa_key_effective] = nm.lower()
        return out, True
    except Exception:
        return tts_text, False



# Memória em-processo para "spice" (saudação do Firestore) com cadência
_LAST_SPICE_AT = {}          # wa_key -> epoch seconds
_LAST_SPICE_TEXT = {}        # wa_key -> last greeting used

# ==========================================================
# UX: gate de uso do nome (IA sinaliza; código autoriza)
# - IA deve sinalizar em understanding: name_use = empathy|clarify|confirm|none
# - Código aplica com gap + anti-repetição e registra no speaker_state
# ==========================================================
_SALES_NAME_MIN_GAP_SECONDS = int(os.environ.get("SALES_NAME_MIN_GAP_SECONDS", str(_SUPPORT_NAME_MIN_GAP_SECONDS)) or str(_SUPPORT_NAME_MIN_GAP_SECONDS))

def _norm_name_token(n: str) -> str:
    try:
        t = str(n or "").strip()
    except Exception:
        return ""
    if not t:
        return ""
    # usa só o primeiro nome (mais natural no áudio)
    return t.split()[0][:24]

def _get_last_name_used_epoch(wa_key: str) -> float:
    if not wa_key:
        return 0.0
    try:
        # cache em memória (mais barato)
        v = _LAST_NAME_SPOKEN_AT.get(wa_key)  # type: ignore[name-defined]
        if isinstance(v, (int, float)) and v:
            return float(v)
    except Exception:
        pass
    # fallback: lê speaker_state (best-effort)
    try:
        snap = _speaker_db().collection(_SPEAKER_COLL).document(wa_key).get()
        data = snap.to_dict() or {}
        v = data.get("lastNameUsedAtEpoch") or 0.0
        return float(v or 0.0)
    except Exception:
        return 0.0

def _mark_name_used(wa_key: str, name_use: str) -> None:
    if not wa_key:
        return
    now = time.time()
    try:
        _LAST_NAME_SPOKEN_AT[wa_key] = now  # type: ignore[name-defined]
    except Exception:
        pass
    try:
        _speaker_db().collection(_SPEAKER_COLL).document(wa_key).set({
            "lastNameUsedAt": _fs_admin().SERVER_TIMESTAMP,  # type: ignore[name-defined]
            "lastNameUsedAtEpoch": now,
            "lastNameUse": str(name_use or "")[:20],
        }, merge=True)
    except Exception:
        pass

def _maybe_name_prefix_legacy(*, wa_key: str, display_name: str, base_text: str, understanding: dict) -> str:
    """Aplica nome no começo (raramente) conforme sinal da IA + regras mecânicas."""
    try:
        name_use = str((understanding or {}).get("name_use") or (understanding or {}).get("nameUse") or "").strip().lower()
    except Exception:
        name_use = ""
    if name_use in ("", "none", "0", "false"):
        return base_text
    nm = _norm_name_token(display_name)
    if not nm:
        return base_text
    t = (base_text or "").strip()
    if not t:
        return base_text
    # não duplica se nome já está no texto
    try:
        if re.search(r"\b" + re.escape(nm) + r"\b", t, flags=re.IGNORECASE):
            return base_text
    except Exception:
        pass
    # gap + anti-consecutivo
    last = _get_last_name_used_epoch(wa_key)
    gap = float(_SALES_NAME_MIN_GAP_SECONDS or 0)
    if last and gap and (time.time() - last) < gap:
        return base_text
    _mark_name_used(wa_key, name_use)
    return (f"{nm}, {t}").strip()

def _maybe_apply_name_to_tts(
    *,
    text: str,
    name_use: str,
    contact_name: str | None,
    speaker_state,
    now_ts: float,
    min_gap_seconds: int = 120,
):
    """Aplica nome no áudio (TTS) apenas quando a IA sinaliza, com gate de cadência."""
    try:
        nu = str(name_use or "").strip().lower()
    except Exception:
        nu = ""
    if not text or not contact_name or nu == "none":
        return text, ""

    try:
        last = float((speaker_state or {}).get("last_name_used_at") or 0.0)
    except Exception:
        last = 0.0
    if (now_ts - last) < float(min_gap_seconds or 0):
        return text, ""

    try:
        if str(contact_name).lower() in str(text).lower():
            return text, ""
    except Exception:
        pass

    prefixed = f"{contact_name}, {str(text).lstrip()}"
    try:
        if isinstance(speaker_state, dict):
            speaker_state["last_name_used_at"] = now_ts
    except Exception:
        pass
    return prefixed, str(contact_name or "").strip()


ycloud_tasks_bp = Blueprint("ycloud_tasks_bp", __name__)


_IDENTITY_MODE = (os.environ.get("IDENTITY_MODE") or "on").strip().lower()  # on|off


def _upload_audio_bytes_to_signed_url(*, b: bytes, audio_debug: dict, tag: str = "ttsAck", ext: str = "mp3", content_type: str = "audio/mpeg") -> str:
    """
    Reusa o MESMO esquema de bytes_upload_signed que já funciona no worker:
    Storage -> upload_from_string -> generate_signed_url.
    """
    try:
        if not b or len(b) < 200:
            audio_debug[tag] = {"ok": False, "reason": f"empty_audio_bytes:{ext}"}
            return ""

        # Validação leve (não bloquear formatos): só garante que tem bytes suficientes

          # type: ignore
        from services.gcp_creds import get_storage_client
        import uuid
        # usa o módulo datetime (já importado no topo) para acessar datetime + timedelta

        bucket_name = os.environ.get("STORAGE_BUCKET", "").strip()
        if not bucket_name:
            audio_debug[tag] = {"ok": False, "reason": "missing_STORAGE_BUCKET"}
            return ""

        now = datetime.datetime.utcnow()
        obj = f"sandbox/institutional_tts_ack/{now:%Y/%m/%d}/{uuid.uuid4().hex}.{ext}"

        client = get_storage_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(obj)
        blob.upload_from_string(b, content_type=(content_type or "application/octet-stream"))

        exp_s = int(os.environ.get("SIGNED_URL_EXPIRES_SECONDS", "900") or "900")
        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(seconds=exp_s),
            method="GET",
        )

        audio_debug[tag] = {"ok": True, "mode": "bytes_upload_signed", "bytes": len(b), "ct": (content_type or ""), "object": obj}
        return url
    except Exception as e:
        audio_debug[tag] = {"ok": False, "reason": f"upload_exc:{type(e).__name__}:{str(e)[:120]}"}
        return ""


def _db():
    """Firestore client canônico: sempre via firebase_admin.
    - Determinístico em Render e Cloud Run.
    - Evita ADC (GOOGLE_APPLICATION_CREDENTIALS) apontar para projeto errado.
    """
    from services.firebase_admin_init import ensure_firebase_admin  # type: ignore
    ensure_firebase_admin()
    from firebase_admin import firestore as admin_fs  # type: ignore
    return admin_fs.client()


def _db_admin():
    try:
        from firebase_admin import firestore as admin_fs  # type: ignore
        return admin_fs.client()
    except Exception:
        return None


def _fs_admin():
    """Atalhos de sentinelas do firebase-admin firestore (evita misturar com google.cloud.firestore)."""
    from services.firebase_admin_init import ensure_firebase_admin  # type: ignore
    ensure_firebase_admin()
    from firebase_admin import firestore as admin_fs  # type: ignore
    return admin_fs


def _sha1_id(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()

def _sha1(s: str) -> str:
    import hashlib
    return hashlib.sha1((s or "").encode("utf-8", errors="ignore")).hexdigest()



def _get_support_persona() -> Dict[str, Any]:
    """
    Lê platform_kb/support (doc) e extrai persona/tom/taboos.
    Cache TTL em memória do processo.
    """
    global _SUPPORT_PERSONA_CACHE_AT, _SUPPORT_PERSONA_CACHE
    now = time.time()
    if _SUPPORT_PERSONA_CACHE and (now - (_SUPPORT_PERSONA_CACHE_AT or 0.0)) < _SUPPORT_PERSONA_CACHE_TTL:
        return _SUPPORT_PERSONA_CACHE
    try:
        db = _db_admin() or _db()
        snap = db.collection("platform_kb").document("support").get()
        data = snap.to_dict() or {}
        out = {
            "persona_description": str(data.get("persona_description") or "").strip(),
            "tone_rules": data.get("tone_rules") or [],
            "taboos": data.get("taboos") or [],
            "persona_spice": data.get("persona_spice") or {},
        }
        _SUPPORT_PERSONA_CACHE = out
        _SUPPORT_PERSONA_CACHE_AT = now
        return out
    except Exception:
        return _SUPPORT_PERSONA_CACHE or {}

_SALES_KB_CACHE: Dict[str, Any] = {}
_SALES_KB_CACHE_AT: float = 0.0
_SALES_KB_TTL = int(os.environ.get("SALES_KB_TTL_SECONDS", "600") or "600")

def _get_sales_kb() -> Dict[str, Any]:
    """
    Lê platform_kb/sales (doc) e extrai tom/regras/segmentos/objeções/preços.
    Cache TTL em memória do processo.
    """
    global _SALES_KB_CACHE_AT, _SALES_KB_CACHE
    now = time.time()
    if _SALES_KB_CACHE and (now - (_SALES_KB_CACHE_AT or 0.0)) < _SALES_KB_TTL:
        return _SALES_KB_CACHE
    try:
        db = _db_admin() or _db()
        snap = db.collection("platform_kb").document("sales").get()
        data = snap.to_dict() or {}
        # Mantém shape simples (Firestore é a verdade; IA decide como usar)
        out = {
            # Núcleo (já usado hoje)
            "tone_rules": data.get("tone_rules") or [],
            "behavior_rules": data.get("behavior_rules") or [],
            "ethical_guidelines": data.get("ethical_guidelines") or [],
            "identity_positioning": str(data.get("identity_positioning") or "").strip(),
            "value_props": data.get("value_props") or [],
            "how_it_works": data.get("how_it_works") or [],
            "qualifying_questions": data.get("qualifying_questions") or [],
            "pricing_behavior": data.get("pricing_behavior") or [],
            "pricing_facts": data.get("pricing_facts") or {},
            "pricing_teasers": data.get("pricing_teasers") or [],
            "plans": data.get("plans") or {},
            "segments": data.get("segments") or {},
            "objections": data.get("objections") or {},

            # Expansão do KB (Firestore é a verdade — evita “capar” vendas no áudio)
            "availability_policy": data.get("availability_policy") or {},
            "brand_guardrails": data.get("brand_guardrails") or [],
            "closing_behaviors": data.get("closing_behaviors") or [],
            "closing_guidance": data.get("closing_guidance") or [],
            "closing_styles": data.get("closing_styles") or {},
            "commercial_positioning": data.get("commercial_positioning") or {},
            "conversation_limits": str(data.get("conversation_limits") or "").strip(),
            "cta_variations": data.get("cta_variations") or [],
            "depth_policy": str(data.get("depth_policy") or "").strip(),
            "discovery_policy": data.get("discovery_policy") or [],
            "empathy_triggers": data.get("empathy_triggers") or [],
            "example_templates": data.get("example_templates") or {},
            "how_it_works_long": data.get("how_it_works_long") or [],
            "how_it_works_rich": data.get("how_it_works_rich") or {},
            "steps": data.get("steps") or [],
            "how_to_get_started": str(data.get("how_to_get_started") or "").strip(),
            "how_to_get_started_long": str(data.get("how_to_get_started_long") or "").strip(),
            "identity_disclosure": data.get("identity_disclosure") or {},
            "intent_guidelines": data.get("intent_guidelines") or {},
            "kb_catalog": data.get("kb_catalog") or {},
            "kb_need_allowed": data.get("kb_need_allowed") or [],
            "kb_policy": data.get("kb_policy") or {},
            "memory_positioning": data.get("memory_positioning") or {},
            "operational_capabilities": data.get("operational_capabilities") or {},
            "operational_examples": data.get("operational_examples") or {},
            "operational_examples_long": data.get("operational_examples_long") or {},
            "operational_flows": data.get("operational_flows") or {},
            "operational_value_scenarios": data.get("operational_value_scenarios") or {},
            "process_facts": data.get("process_facts") or {},
            "product_boundaries": data.get("product_boundaries") or [],
            "sales_audio_modes": data.get("sales_audio_modes") or {},
            "sales_energy": str(data.get("sales_energy") or "").strip(),
            "sales_pills": data.get("sales_pills") or {},
            "segment_pills": data.get("segment_pills") or {},
            "support_scope": data.get("support_scope") or [],
            "tone_rules_full": data.get("tone_rules") or [],  # compat/clareza
            "value_in_action_blocks": data.get("value_in_action_blocks") or {},
            "voice_positioning": data.get("voice_positioning") or {},
        }
        _SALES_KB_CACHE = out
        _SALES_KB_CACHE_AT = now
        return out
    except Exception:
        return _SALES_KB_CACHE or {}

def _strip_links_for_audio(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = re.sub(r"https?://\S+", "", t).strip()
    # evita ler domínio em voz
    if _SALES_SITE_URL:
        t = t.replace(_SALES_SITE_URL, "").strip()
    t = t.replace("www.", "").strip()
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


def _keep_sales_surface_from_bot(*, wa_out: dict | None = None, uid: str = "") -> bool:
    """
    Em vendas, se o bot/front já entregou a superfície falável,
    o worker não deve remodelar essa camada.
    """
    try:
        if str(uid or "").strip():
            return False

        out = dict(wa_out or {})

        if str(out.get("spokenText") or "").strip():
            return True

        if str(out.get("ttsText") or out.get("tts_text") or "").strip():
            return True

        route = str(out.get("route") or "").strip().lower()
        reply_source = str(out.get("replySource") or out.get("reply_source") or "").strip().lower()

        if route in ("front", "conversational_front", "conversationalfront"):
            return True

        if reply_source in ("front", "pack_engine", "pack_engine_fallback_default"):
            return True

        return False
    except Exception:
        return False

def _openai_sales_speech(reply_text: str, user_text: str, kb: Dict[str, Any], name_hint: str = "", mode: str = "demo") -> str:
    """
    Gera fala curta de VENDAS (15–30s) com 1 micro-exemplo operacional.
    - Sem frases prontas: a IA reescreve sempre.
    - Sem links.
    - demo: 2–4 frases + 1 pergunta final (qualificação leve)
    - close: 2–5 frases, SEM pergunta, com CTA + despedida (vendedor na dose certa)
    """
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return ""
    base = _strip_links_for_audio(reply_text)
    if not base:
        return ""

    kb = kb or {}
    # --- KB compacto (anti-tokens): usa sales_pills quando existir; fallback seguro ---
    pills = kb.get("sales_pills") or {}

    def _clip(s: str, n: int) -> str:
        s = (s or "").strip()
        if not s:
            return ""
        s = re.sub(r"\s+", " ", s).strip()
        return s[:n]

    def _first_n(arr: Any, n: int) -> list:
        if not isinstance(arr, list):
            return []
        return arr[:n]

    ctx = {
        # 1–2 linhas no máximo (ou vazio)
        "identity_blurb": _clip(str(pills.get("identity_blurb") or kb.get("identity_positioning") or ""), 260),
        # top3 benefícios curtos
        "value_props_top3": _first_n(pills.get("value_props_top3") or kb.get("value_props") or [], 3),
        # 3 passos curtos
        "how_it_works_3steps": _first_n(pills.get("how_it_works_3steps") or kb.get("how_it_works") or [], 3),
        # tom e limites (curto)
        "tone_rules": _first_n(kb.get("tone_rules") or [], 5),
        "behavior_rules": _first_n(kb.get("behavior_rules") or [], 6),
        "closing_guidance": _first_n(kb.get("closing_guidance") or [], 4),
        "ethical_guidelines": _first_n(kb.get("ethical_guidelines") or [], 4),
        # perguntas curtas (no máximo 2)
        "qualifying_questions": _first_n(kb.get("qualifying_questions") or [], 2),
        # preço (fatos pequenos OK)
        "pricing_behavior": _first_n(kb.get("pricing_behavior") or [], 4),
        "pricing_facts": kb.get("pricing_facts") or {},
        "pricing_blurb": _clip(str(pills.get("pricing_blurb") or ""), 220),
        "cta_one_liners": _first_n(pills.get("cta_one_liners") or [], 3),
    }

    mode = (mode or "demo").strip().lower()
    if mode not in ("demo", "close"):
        mode = "demo"

    # Regras por modo
    # Defaults (evita UnboundLocalError)
    mode_rules = ""
    structure = ""

    if mode == "close":
        mode_rules = (
            "- MODO: FECHAMENTO.\n"
            "- Não faça pergunta.\n"
            "- Seja vendedor humano na dose certa: confiante, alegre e direto.\n"
            "- Convide para ativar/assinar sem urgência falsa.\n"
            "- Termine com despedida curta usando o nome (se existir).\n"
        )
        structure = "2–5 frases curtas, sem pergunta."
    else:
        mode_rules = (
            "- MODO: DEMONSTRAÇÃO.\n"
            "- 2–4 frases curtas + 1 pergunta final.\n"
            "- Pergunta final objetiva (qualificar), sem abrir conversa infinita.\n"
        )
        structure = "2–4 frases + 1 pergunta final."

    sys = (
        "Você é o MEI Robô institucional de VENDAS falando por áudio no WhatsApp.\n"
        "Objetivo: soar humano, alegre e direto, e fazer a pessoa se enxergar usando a plataforma.\n"
        "Regras obrigatórias:\n"
        "- Nada de discurso de vendedor, nada de texto pronto.\n"
        "- Sem bastidores técnicos.\n"
        "- Sem links, sem ler domínio/site.\n"
        f"{mode_rules}"
        f"- Estrutura: {structure}\n"
        "- Inclua UM micro-exemplo operacional (entrada → confirmação → resumo pro MEI).\n"
        "- Se citar preço, só use se estiver em pricing_facts; caso contrário, fale sem números.\n"
        "Responda SOMENTE com o texto final."
    )

    user = {
        "nome_se_existir": (name_hint or "")[:40],
        "mensagem_do_lead": (user_text or "")[:220],
        "replyText_canonico": base[:520],
        "kb": ctx,
        "modo": mode,
    }

    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": _SALES_TTS_MODEL,
                "temperature": 0.25,
                "max_tokens": int(_SALES_TTS_MAX_TOKENS),
                "messages": [
                    {"role": "system", "content": sys},
                    {"role": "user", "content": json.dumps(user, ensure_ascii=False, separators=(",", ":"))},
                ],
            },
            timeout=18,
        )
        if r.status_code != 200:
            return ""
        j = r.json() or {}
        content = (((j.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        out = _strip_links_for_audio((content or "").strip())
        if len(out) < 10:
            return ""
        # hard cap
        return out[:900]
    except Exception:
        return ""



def _digits_only(s: str) -> str:
    return _digits_only_c(s)


def _to_plus_e164(raw: str) -> str:
    return _to_plus_e164_c(raw)


_NAME_OVERRIDE_TTL = int(os.environ.get("SUPPORT_NAME_OVERRIDE_TTL_SECONDS", "3600") or "3600")  # 1h




# --- WABA owner resolve (multi-WABA): resolve o UID do profissional pelo número DESTINO (to_e164) ---
def _wa_key_digits(e164: str) -> str:
    s = (e164 or '').strip()
    if not s:
        return ''
    return ''.join(ch for ch in s if ch.isdigit())

def _resolve_owner_uid_by_to_e164(to_e164: str) -> str:
    """Resolve UID do profissional dono do WABA (destino).
    Ordem:
      1) waba_owner_links/{waKeyDigits} -> {uid, fromE164} (preferido)
      2) fallback query: profissionais where waba.fromE164 == to_e164
    Safe-by-default: retorna '' em qualquer falha.
    """
    try:
        to_e164_norm = _to_plus_e164(to_e164)
        if not to_e164_norm:
            return ''
        inst = _to_plus_e164(os.environ.get('YCLOUD_WA_FROM_E164') or '')
        if inst and to_e164_norm == inst:
            return ''
        wa_key = _wa_key_digits(to_e164_norm)
        if wa_key:
            try:
                snap = _db().collection('waba_owner_links').document(wa_key).get()
                if snap and snap.exists:
                    data = snap.to_dict() or {}
                    uid = (data.get('uid') or '').strip()
                    fromE = _to_plus_e164(data.get('fromE164') or '')
                    if uid and (not fromE or fromE == to_e164_norm):
                        return uid
            except Exception:
                pass
        # Fallback: query direta (pode exigir índice, mas é single-field)
        try:
            q = _db().collection('profissionais').where('waba.fromE164', '==', to_e164_norm).limit(2).stream()
            uids = [d.id for d in q]
            if not uids:
                return ''
            if len(uids) > 1:
                logger.warning('[tasks] multiple_waba_owners to=%s uids=%s', to_e164_norm, uids)
            return uids[0]
        except Exception:
            return ''
    except Exception:
        return ''

# ==========================================================
# IDENTIDADE PREMIUM (interlocutor ativo por waKey)
# - Filtro econômico por gatilhos (barato)
# - IA só quando necessário (curta, JSON)
# - Estado persistido garante 2ª mensagem certa
# ==========================================================
_SPEAKER_TTL = int(os.environ.get("SUPPORT_SPEAKER_TTL_SECONDS", "21600") or "21600")  # 6h
_SPEAKER_COLL = (os.environ.get("SPEAKER_STATE_COLL") or "platform_speaker_state").strip()

def _speaker_db():
    return _db_admin() or _db()

def _get_owner_name(uid: str) -> str:
    """Tenta inferir nome do MEI (dono da conta) para permitir 'voltei / sou o Ricardo' etc."""
    if not uid:
        return ""
    try:
        prof = _db().collection("profissionais").document(uid).get()
        data = prof.to_dict() or {}
        # tenta chaves comuns no teu projeto
        for k in ("display_name", "displayName", "nome", "name"):
            v = (data.get(k) or "").strip()
            if v:
                return v
    except Exception:
        pass
    return ""

def _get_active_speaker(wa_key: str) -> str:
    if not wa_key:
        return ""
    try:
        snap = _speaker_db().collection(_SPEAKER_COLL).document(wa_key).get()
        if not snap.exists:
            return ""
        data = snap.to_dict() or {}
        exp = float(data.get("expiresAt") or 0.0)
        if exp and time.time() > exp:
            return ""
        nm = str(data.get("displayName") or "").strip()
        return nm
    except Exception:
        return ""

def _set_active_speaker(wa_key: str, display_name: str, source: str, confidence: float = 0.0) -> None:
    if not wa_key or not display_name:
        return
    now = time.time()
    try:
        _speaker_db().collection(_SPEAKER_COLL).document(wa_key).set(
            {
                "displayName": display_name,
                "source": source,
                "confidence": float(confidence or 0.0),
                "updatedAt": now,
                "expiresAt": now + _SPEAKER_TTL,
            },
            merge=True,
        )
    except Exception as e:
        logger.warning("[speaker] falha ao salvar waKey=%s err=%s", wa_key, str(e)[:120])

def _looks_like_identity_signal(text: str) -> bool:
    """Filtro econômico: só chama IA quando tem cheiro de troca/auto-identificação."""
    t = (text or "").strip().lower()
    if not t:
        return False
    # sinais fortes e baratos
    signals = (
        "meu nome é",
        "aqui é",
        "quem fala é",
        "sou o",
        "sou a",
        "prazer",
        "voltei",
        "sou eu",
        "de novo",
        "me chama de",
        "pode me chamar",
        "fala com",
        "passa pro",
        "agora é",
        "agora sou",
        "é o",
        "é a",
    )
    return any(s in t for s in signals)

def _openai_extract_speaker(text: str, owner_name: str = "", active_name: str = "") -> Tuple[str, float, str]:
    """
    IA focada: decide nome do interlocutor ativo.
    Retorna: (name, confidence, reason) — name vazio = não identificou.
    """
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return ("", 0.0, "missing_api_key")

    # Modelo: barato e suficiente
    model = (os.environ.get("IDENTITY_LLM_MODEL") or "gpt-4o-mini").strip()
    t = (text or "").strip()
    if not t:
        return ("", 0.0, "empty_text")

    # prompt curto e objetivo (JSON-only)
    sys = """You extract the ACTIVE speaker name from a single WhatsApp message in Portuguese.
    Return ONLY valid JSON.
    Rules:
    - If the message is self-identification, return that name.
    - If the message indicates returning to the owner (e.g., "voltei", "agora sou eu de novo") and owner_name is known, return owner_name.
    - Avoid third-person mentions (e.g., "o papo é com o José") unless it\'s clearly the speaker.
    - Name can be nickname (e.g., "Banana", "Zé").
    JSON schema:
    { "identified": true|false, "name": "...", "confidence": 0..1, "reason": "..." }
    """
    user = {
        "text": t[:300],
        "owner_name": (owner_name or "")[:60],
        "current_active_name": (active_name or "")[:60],
    }

    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0.0,
                "max_tokens": 120,
                "messages": [
                    {"role": "system", "content": sys},
                    {"role": "user", "content": str(user)},
                ],
            },
            timeout=18,
        )
        if r.status_code != 200:
            return ("", 0.0, f"http_{r.status_code}")
        j = r.json() or {}
        content = (((j.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        content = (content or "").strip()
        # parse JSON safely
        try:
            import json as _json
            data = _json.loads(content)
        except Exception:
            # tenta extrair bloco {...}
            m = re.search(r"\{.*\}", content, flags=re.DOTALL)
            if not m:
                return ("", 0.0, "non_json")
            import json as _json
            data = _json.loads(m.group(0))

        identified = bool(data.get("identified"))
        name = str(data.get("name") or "").strip()
        conf = float(data.get("confidence") or 0.0)
        reason = str(data.get("reason") or "").strip()[:120]
        if not identified or not name:
            return ("", conf, reason or "not_identified")
        # hard cap: evita string gigante
        name = name[:40]
        return (name, conf, reason or "ok")
    except Exception as e:
        return ("", 0.0, f"exc:{type(e).__name__}")


def _detect_name_override(text: str) -> str:
    try:
        t = (text or "").strip()
        if not t:
            return ""
        # padrões comuns (inclui "aqui quem fala é X", "aqui é o X")
        m = re.search(
            r"\b("
            r"meu nome é|me chamo|sou o|sou a|"
            r"aqui quem fala é|aqui quem tá falando é|aqui é o|aqui é a|"
            r"quem fala é|quem tá falando é"
            r")\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'\- ]{1,40})\b",
            t,
            re.IGNORECASE,
        )
        if not m:
            return ""
        name = (m.group(2) or "").strip()
        name = re.sub(r"\s+", " ", name)
        # corta excessos comuns
        name = re.sub(r"\b(da|do|de)\b.*$", "", name, flags=re.IGNORECASE).strip()
        if len(name) < 2:
            return ""
        return name
    except Exception:
        return ""


def _set_name_override(wa_key: str, name: str) -> None:
    if not wa_key or not name:
        return
    now = time.time()
    db = _db_admin()
    if not db:
        logger.warning("[nameOverride] admin firestore indisponível; não salvou waKey=%s", wa_key)
        return
    try:
        db.collection("platform_name_overrides").document(wa_key).set({
            "name": name,
            "updatedAt": now,
            "expiresAt": now + _NAME_OVERRIDE_TTL,
        }, merge=True)
    except Exception as e:
        logger.warning("[nameOverride] falha ao salvar waKey=%s err=%s", wa_key, str(e)[:120])


def _get_name_override(wa_key: str) -> str:
    if not wa_key:
        return ""
    db_read = _db_admin() or _db()
    try:
        doc = db_read.collection("platform_name_overrides").document(wa_key).get()
        if not doc.exists:
            return ""
        data = doc.to_dict() or {}
        exp = float(data.get("expiresAt") or 0.0)
        if exp and time.time() <= exp:
            return str(data.get("name") or "").strip()
    except Exception:
        pass
    return ""

def _apply_name_override(reply_text: str, override_name: str) -> str:
    if not override_name:
        return reply_text
    s = (reply_text or "").strip()

    # Só troca saudação no começo (não mexe no corpo)
    # "Oi, Edson!" / "Olá Edson!" / "Olá, Edson!"
    s2 = re.sub(
        r"^(oi|olá)\s*,?\s*[^!?.\n]{1,60}([!?.])",
        rf"\1, {override_name}\2",
        s,
        flags=re.IGNORECASE,
    )
    return s2


def _shorten_for_speech(text: str, max_chars: int) -> str:
    """
    Encurta texto para TTS de forma segura e 'falável'.
    Heurística leve (barata): corta em limite e tenta terminar em pontuação.
    """
    t = (text or "").strip()
    if not t:
        return ""
    if max_chars <= 60:
        max_chars = 60
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars].strip()
    # tenta finalizar no último . ! ? (melhor pra fala)
    m = re.search(r"^(.{40,})([.!?])[^.!?]*$", cut)
    if m:
        return (m.group(1) + m.group(2)).strip()
    # fallback: remove resto e fecha com ponto
    cut = cut.rstrip(",;:-")
    return (cut + ".").strip()


def _shorten_for_whatsapp(text: str, max_chars: int) -> str:
    """
    Encurta texto de fallback (quando áudio falhar), evitando paredão e corte feio no WhatsApp.
    """
    t = (text or "").strip()
    if not t:
        return ""
    if max_chars <= 120:
        max_chars = 120
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars].strip()
    # tenta cortar em fim de frase/linha
    m = re.search(r"^(.{80,})([.!?])[^.!?]*$", cut)
    if m:
        return (m.group(1) + m.group(2)).strip()
    return (cut.rstrip(",;:-") + "…").strip()


def _clean_for_speech(text: str) -> str:
    """
    Limpa marcas visuais e bullets que soam péssimo no TTS.
    Mantém o conteúdo, mas deixa 'falável'.
    """
    t = (text or "").strip()
    if not t:
        return ""
    # remove emojis/badges comuns de seção
    t = t.replace("✅", "").replace("📌", "").replace("⚠️", "").replace("🏗️", "").replace("🛠️", "")
    # remove bullets e hífens de lista no meio
    t = re.sub(r"\s*-\s+", " ", t)
    # remove colchetes e pipes típicos de tabelas/links
    t = t.replace("|", " ").replace("[", "").replace("]", "")
    # colapsa espaços
    t = re.sub(r"\s+", " ", t).strip()
    return t







def _clean_for_tts(text: str) -> str:
    """
    Limpeza específica para TTS (áudio).
    Mantém o replyText intacto no WhatsApp, mas remove ruídos que soam estranhos ao falar:
    - aspas "..." e quotes “...”
    - aspas soltas remanescentes
    """
    t = _clean_for_speech(text)
    if not t:
        return ""

    # remove aspas/quotes envolvendo trechos curtos ("maionese X" -> maionese X)
    try:
        t = re.sub(r'[“"]([^”"]+)[”"]', r"\1", t)
    except Exception:
        pass

    # remove quotes soltas que sobraram
    t = t.replace('"', "").replace("“", "").replace("”", "")

    # colapsa espaços de novo
    t = re.sub(r"\s+", " ", t).strip()
    # remove aspas que soam estranho no TTS
    t = t.replace('"', "").replace("“", "").replace("”", "").replace("‘", "").replace("’", "")
    return t

def _expand_units_for_speech(text: str) -> str:
    if not text:
        return text or ""
    t = str(text)
    # 5 MB / 5MB -> 5 megabytes
    t = re.sub(r"\b(\d+)\s*MB\b", r"\1 megabytes", t, flags=re.IGNORECASE)
    # 2 GB / 2GB -> 2 gigabytes
    t = re.sub(r"\b(\d+)\s*GB\b", r"\1 gigabytes", t, flags=re.IGNORECASE)
    # casos soltos: MB / GB
    t = re.sub(r"\bMB\b", "megabytes", t, flags=re.IGNORECASE)
    t = re.sub(r"\bGB\b", "gigabytes", t, flags=re.IGNORECASE)
    return t


def _pick_support_greeting(persona: dict, wa_key: str, name: str, is_informal: bool) -> str:
    try:
        if not persona or not name:
            return ""

        spice = persona.get("persona_spice") or {}
        greetings = spice.get("greetings") or persona.get("greetings") or []
        rules = spice.get("rules") or persona.get("rules") or {}
        if not greetings:
            return ""

        if rules.get("use_only_if_user_is_informal") and (not is_informal):
            return ""

        # cadência
        min_minutes = int(rules.get("min_minutes_between_spices") or 60)
        now = int(time.time())
        last_at = int(_LAST_SPICE_AT.get(wa_key) or 0)
        if last_at and (now - last_at) < (min_minutes * 60):
            return ""

        # evitar repetir o mesmo em sequência
        last_txt = (_LAST_SPICE_TEXT.get(wa_key) or "").strip()
        opts = [g for g in greetings if str(g).strip()]
        if rules.get("never_repeat_same_spice_in_sequence") and last_txt:
            opts2 = [g for g in opts if str(g).strip() != last_txt]
            if opts2:
                opts = opts2

        if not opts:
            return ""

        g = str(random.choice(opts)).strip()
        g = g.replace("{nome}", name).strip()

        _LAST_SPICE_AT[wa_key] = now
        _LAST_SPICE_TEXT[wa_key] = g
        return g
    except Exception:
        return ""

def _openai_rewrite_for_speech(text: str, display_name: str = "") -> str:
    """
    Reescreve em PT-BR para fala humana (2-3 frases) + 1 pergunta no fim.
    Barato: só roda quando SUPPORT_TTS_SUMMARY_MODE=on e canal é áudio.
    """
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return ""
    t = (text or "").strip()
    if not t:
        return ""

    persona = _get_support_persona()
    persona_desc = str(persona.get("persona_description") or "").strip()
    tone_rules = persona.get("tone_rules") or []
    taboos = persona.get("taboos") or []
    spice = persona.get("persona_spice") or {}

    # prompt curto e MAIS “com alma” (sem virar bordão)
    sys = (
        "Você é um atendente humano de suporte falando por áudio no WhatsApp.\n"
        f"PERSONA: {persona_desc}\n"
        f"TOM (regras): {tone_rules}\n"
        f"EVITE (tabu): {taboos}\n"
        f"TEMPEROS (use raramente e só se combinar): {spice}\n"
        "Transforme o texto abaixo em uma resposta FALADA curta em português do Brasil:\n"
        "- 2 a 3 frases curtas\n"
        "- sem listas, sem emojis e sem tom corporativo\n"
        "- NÃO comece com 'Olá, você pode...' (isso soa bot)\n"
        "- se tiver nome, use no máximo 1 vez e só se não tiver sido usado recentemente\n"
        "- termine com 1 pergunta curta para entender o objetivo\n"
        "Responda SOMENTE com o texto final."
    )

    user = {"name": (display_name or "")[:40], "text": t[:900]}
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": _SUPPORT_TTS_SUMMARY_MODEL,
                "temperature": 0.2,
                "max_tokens": _SUPPORT_TTS_SUMMARY_MAX_TOKENS,
                "messages": [
                    {"role": "system", "content": sys},
                    {"role": "user", "content": str(user)},
                ],
            },
            timeout=18,
        )
        if r.status_code != 200:
            return ""
        j = r.json() or {}
        content = (((j.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        out = (content or "").strip()
        # guarda rail simples
        if len(out) < 10:
            return ""
        return out[:900]
    except Exception:
        return ""



def _openai_generate_concept_speech(question: str, kb_context: str, display_name: str = "") -> str:
    """
    Gera fala curta e humana (15–30s) para perguntas conceituais.
    Usa kb_context como CONTEXTO (não como texto a ser lido).
    Só roda quando canal é áudio e SUPPORT_TTS_CONCEPT_MODE=on.
    """
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return ""
    q = (question or "").strip()
    ctx = (kb_context or "").strip()
    if not q or not ctx:
        return ""

    persona = _get_support_persona()
    persona_desc = str(persona.get("persona_description") or "").strip()
    tone_rules = persona.get("tone_rules") or []
    taboos = persona.get("taboos") or []
    spice = persona.get("persona_spice") or {}

    ctx = ctx[: max(200, int(_SUPPORT_TTS_CONCEPT_KB_MAX_CHARS))]

    sys = (
    "Você é um atendente humano de suporte falando por áudio no WhatsApp.\n"
    "Sua missão: responder de forma CALMA e EXPLICATIVA, sem virar manual.\n"
    f"PERSONA: {persona_desc}\n"
    f"TOM (regras): {tone_rules}\n"
    f"EVITE (tabu): {taboos}\n"
    f"TEMPEROS (use raramente e só se combinar): {spice}\n"
    "\n"
    "Regras obrigatórias:\n"
    "- NÃO comece com saudação (nada de 'oi', 'olá', 'fala', 'Faaala', 'Graaande').\n"
    "- NÃO use o nome da pessoa.\n"
    "- Sem emojis, sem CAPS, sem múltiplas exclamações.\n"
    "- 2–4 frases curtas + 1 pergunta final.\n"
    "- Se citar limites, use 'megabytes/gigabytes' por extenso (nunca 'MB/GB').\n"
    "\n"
    "DICAS:\n"
    "- use o CONTEXTO apenas para não inventar, NÃO leia o texto\n"
    "- português do Brasil, tom humano\n"
    "Responda SOMENTE com o texto final."
)

    user = {
        "name": (display_name or "")[:40],
        "pergunta": q[:240],
        "contexto_base": ctx,
    }

    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": _SUPPORT_TTS_CONCEPT_MODEL,
                "temperature": 0.2,
                "max_tokens": int(_SUPPORT_TTS_CONCEPT_MAX_TOKENS),
                "messages": [
                    {"role": "system", "content": sys},
                    {"role": "user", "content": str(user)},
                ],
            },
            timeout=18,
        )
        if r.status_code != 200:
            return ""
        j = r.json() or {}
        content = (((j.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        out = (content or "").strip()
        if len(out) < 10:
            return ""
        # hard cap para não estourar TTS
        return out[:900]
    except Exception:
        return ""


def _make_tts_text(reply_text: str, display_name: str, *, add_acervo_cta: bool = True) -> str:
    """
    Constrói o texto falado (TTS) com tom humano:
    - abre com nome quando disponível e quando não há saudação
    - limpa bullets/ícones
    - fecha com porta aberta curta
    """
    base = _clean_for_tts(reply_text)
    if not base:
        return ""

    # Se já começa com "oi/olá", não inventa saudação.
    starts_greet = bool(re.match(r"^(oi|olá)\b", base, flags=re.IGNORECASE))

    # Nome só se houver e se não ficar repetitivo
    nm = (display_name or "").strip()
    if nm and not starts_greet:
        # abre humano e curto
        base = f"{nm}, te explico rapidinho. {base}"

    # Porta aberta curta (não vira vendedor)
    if not re.search(r"[.!?]\s*$", base):
        base = base.strip() + "."
    if add_acervo_cta:
        base = base + " Se quiser, me diz o que você quer guardar no acervo: texto, foto ou PDF?"
    return base.strip()


def _idempotency_once(event_key: str, ttl_seconds: int = 86400) -> bool:
    """
    Retorna True se é primeira vez. False se já processou.
    (Idempotência hard em Firestore)
    """
    doc_id = _sha1_id(event_key)
    ref = _db().collection("platform_tasks_dedup").document(doc_id)
    snap = ref.get()
    if snap.exists:
        return False
    now = time.time()
    ref.set({
        "eventKey": event_key,
        "createdAt": now,
        "expiresAt": now + max(3600, int(ttl_seconds or 86400)),
    }, merge=False)
    return True

@ycloud_tasks_bp.route("/tasks/ycloud-inbound", methods=["GET", "POST"])
# Compat: algumas configurações de Cloud Tasks/blueprint acabam chamando com path duplicado
# Ex.: POST /tasks/ycloud-inbound/tasks/ycloud-inbound (vimos 405 em produção)
@ycloud_tasks_bp.route("/tasks/ycloud-inbound/tasks/ycloud-inbound", methods=["GET", "POST"])
def ycloud_inbound_worker():
    """
    Cloud Tasks worker (YCloud inbound).
    Guardrails:
      - Always returns a valid Flask response (never None).
      - Keeps behavior compatible with Render; adds only defensive wrapping.
    """
    # Ping GET (diagnóstico)
    if request.method == "GET":
        logger.info("[tasks] early_return reason=%s", "PING_GET")
        return jsonify({"ok": True, "route": "tasks/ycloud-inbound", "methods": ["GET", "POST"]}), 200

    # Auth simples via secret (modo Render)
    secret = (os.environ.get("CLOUD_TASKS_SECRET") or "").strip()
    got = (
        (request.headers.get("X-MR-Tasks-Secret") or "").strip()
        or (request.headers.get("X-CloudTasks-Secret") or "").strip()
        or (request.headers.get("X-Cloudtasks-Secret") or "").strip()
    )
    if (not secret) or (not got) or (got != secret):
        g6 = (got[:6] + "...") if got else "NONE"
        s6 = (secret[:6] + "...") if secret else "NONE"
        logger.warning(
            "[tasks] unauthorized: bad secret got=%s expected=%s ua=%s",
            g6, s6, (request.headers.get("User-Agent") or "")[:60]
        )
        logger.info("[tasks] early_return reason=%s got=%s", "UNAUTHORIZED_SECRET", g6)
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        data = request.get_json(silent=True) or {}
        event_key = (data.get("eventKey") or "").strip()
        payload = data.get("payload") or {}

        # ==========================================================
        # DEDUPE (produção): garante idempotência por eventKey
        # Se o mesmo eventKey cair 2x (retry YCloud/Tasks), NÃO reenviar outbound.
        # ==========================================================
        try:
            _wamid_d = str((payload or {}).get("wamid") or (payload or {}).get("messageId") or "")
        except Exception:
            _wamid_d = ""
        try:
            _ek = str(event_key or "").strip()
            _wm = str(_wamid_d or "").strip()
            # Preferir WAMID para dedupe (mais estável que eventKey quando muda normalização/msgType)
            _dedupe_basis = _wm or _ek
            if _dedupe_basis:
                _dedup_doc = _sha1_id(f"task:{_dedupe_basis}")
                _ref = _db().collection("platform_tasks_dedup").document(_dedup_doc)
                _snap = _ref.get()
                if _snap.exists:
                    logger.info("[tasks] dedup: already_processed eventKey=%s wamid=%s", event_key, _wm)
                    return jsonify({"ok": True, "deduped": True}), 200
                _ref.set(
                    {
                        "eventKey": _ek,
                        "dedupeBasis": _dedupe_basis,
                        "wamid": _wm,
                        "createdAt": _fs_admin().SERVER_TIMESTAMP,
                    },
                    merge=True,
                )
        except Exception:
            pass




    except Exception:
        logger.exception("[tasks] worker_unhandled_exception (parse_json)")
        # Retornar 200 evita retry infinito do Cloud Tasks enquanto depuramos
        return jsonify({"ok": True, "error": "worker_exception"}), 200

    try:
        resp = _ycloud_inbound_worker_impl(event_key=event_key, payload=payload, data=data)
        if resp is None:
            logger.error("[tasks] BUG: impl returned None eventKey=%s", event_key)
            return jsonify({"ok": True, "guard": "impl_returned_none"}), 200
        return resp
    except Exception as e:
        logger.exception("[tasks] worker_unhandled_exception (impl) err=%s", f"{type(e).__name__}:{str(e)[:160]}")
        return jsonify({"ok": True, "error": "worker_exception"}), 200


def _ycloud_inbound_worker_impl(*, event_key: str, payload: dict, data: dict):
    """
    Implementação do worker. Conteúdo original (Render) foi movido para cá
    apenas para garantir return absoluto no Cloud Run.
    """
    # Defaults seguros (evita UnboundLocalError em trilhas que não passam pelo bloco de envio)
    send_text = None
    send_audio = None
    sent_ok = False


    # Estado base do turno (evita variáveis não inicializadas em early-returns)
    wa_out = None
    reply_text = ""
    spoken_text = ""
    audio_url = ""
    audio_debug = {}
    skip_wa_bot = False
    voice_config_ack_ready = False

    # Stub seguro: alguns caminhos (fallback / firebase_off) chamam _try_log_outbox_immediate
    # antes dela ser definida. Mantém o worker vivo.
    def _try_log_outbox_immediate(*args, **kwargs):
        return None


    # OUTBOX "rico enxuto": campos úteis, sem payload gigante (best-effort)
    def _trim(_s: object, _n: int) -> str:
        try:
            s = str(_s or "")
        except Exception:
            return ""
        s = s.strip()
        if not s:
            return ""
        return s[:_n]

    def _outbox_rich_enxuto(*, _sent_via: str, _reply_text: str) -> dict:
        out: dict = {}
        try:
            # route_hint vem do worker (ex.: sales_lead/sales/support etc.)
            try:
                out["route_hint"] = _trim(route_hint, 80)  # type: ignore[name-defined]
            except Exception:
                pass

            # reply/spoken (cortados)
            out["replyText"] = _trim(_reply_text, 600)
            try:
                out["spokenText"] = _trim(spoken_text, 600)  # type: ignore[name-defined]
            except Exception:
                out["spokenText"] = _trim(_reply_text, 600)

            out["sentVia"] = _trim(_sent_via, 80)

            # audioUrl (se existir) — enxuto e útil pra auditoria
            try:
                out["audioUrl"] = _trim(audio_url, 300)  # type: ignore[name-defined]
            except Exception:
                pass


            # understanding (curto)
            try:
                if isinstance(understanding, dict):  # type: ignore[name-defined]
                    out["understanding"] = {
                        "intent": _trim(understanding.get("intent"), 40),
                        "next_step": _trim(understanding.get("next_step"), 40),
                        "confidence": _trim(understanding.get("confidence"), 16),
                        "depth": _trim(understanding.get("depth"), 16),
                        "risk": _trim(understanding.get("risk"), 80),
                        "source": _trim(understanding.get("source"), 40),
                    }
            except Exception:
                pass

            # STT/TTS (a partir do audio_debug, se houver)
            try:
                if isinstance(audio_debug, dict):  # type: ignore[name-defined]
                    stt0 = audio_debug.get("stt")
                    if isinstance(stt0, dict):
                        out["stt"] = {
                            "ok": bool(stt0.get("ok")),
                            "confidence": stt0.get("confidence", 0),
                            "transcriptLen": stt0.get("transcriptLen", 0),
                            "preview": _trim(stt0.get("preview"), 240),
                            "error": _trim(stt0.get("error") or stt0.get("reason"), 240),
                        }
                    tts0 = audio_debug.get("tts") or audio_debug.get("ttsSales") or audio_debug.get("ttsAckSend")
                    if isinstance(tts0, dict):
                        out["tts"] = {
                            "ok": bool(tts0.get("ok")),
                            "mode": _trim(tts0.get("mode"), 40),
                            "ct": _trim(tts0.get("ct"), 40),
                            "bytes": int(tts0.get("bytes") or 0),
                            "reason": _trim(tts0.get("reason") or tts0.get("error"), 240),
                        }
            except Exception:
                pass

            # waOutMeta (enxuto)
            try:
                out["waOutMeta"] = {
                    "prefersText": bool(prefers_text),  # type: ignore[name-defined]
                    "planNextStep": _trim(plan_next_step, 40),  # type: ignore[name-defined]
                    "intentFinal": _trim(intent_final, 40),  # type: ignore[name-defined]
                    "hasAudioUrl": bool(str(audio_url or "").strip()),  # type: ignore[name-defined]
                }
            except Exception:
                pass

            # deliveryMode (como entregamos: áudio/texto)
            try:
                _has_audio = bool(str(audio_url or "").strip())  # type: ignore[name-defined]
                _send_link = False
                try:
                    _send_link = bool(force_send_link_text)  # type: ignore[name-defined]
                except Exception:
                    _send_link = (str(plan_next_step or "").strip().upper() == "SEND_LINK")  # type: ignore[name-defined]
                if _has_audio and _send_link:
                    out["deliveryMode"] = "audio_plus_text_link"
                elif _has_audio:
                    out["deliveryMode"] = "audio_only"
                else:
                    out["deliveryMode"] = "text_only"
            except Exception:
                pass

            # aiMeta (Firestore-first do sales_lead): copia metadados leves pro outbox
            try:
                _wo = wa_out if isinstance(wa_out, dict) else {}  # type: ignore[name-defined]
                # Suporta também quando vier agrupado (aiMeta)
                _am = _wo.get("aiMeta") if isinstance(_wo.get("aiMeta"), dict) else {}
                def _g(key: str, default: str = "") -> str:
                    v = _wo.get(key, _am.get(key) if isinstance(_am, dict) else default)
                    return _trim(v, 240)
                def _gb(key: str) -> bool:
                    v = _wo.get(key, _am.get(key) if isinstance(_am, dict) else None)
                    return bool(v)
                def _gl(key: str) -> list:
                    v = _wo.get(key, _am.get(key) if isinstance(_am, dict) else None)
                    return v if isinstance(v, list) else []
                out["aiMeta"] = {
                    "iaSource": _g("iaSource", ""),
                    "kbDocPath": _g("kbDocPath", ""),
                    "kbContractId": _g("kbContractId", ""),
                    "kbUsed": _gb("kbUsed"),
                    "kbRequiredOk": _gb("kbRequiredOk"),
                    "kbMissReason": _g("kbMissReason", ""),
                    "kbMissingFields": _gl("kbMissingFields"),
                    "kbExampleUsed": _g("kbExampleUsed", ""),
                    "spokenSource": _g("spokenSource", ""),
                    "replyTextRole": _g("replyTextRole", ""),
                    "spokenTextRole": _g("spokenTextRole", ""),
                    "funnelMoment": _g("funnelMoment", ""),
                }
            except Exception:
                pass
        except Exception:
            return {}
        return out

    # OUTBOX (determinístico): sempre grava 1 doc do envio (sem depender de _try_log_outbox_immediate)
    def _wa_log_outbox_deterministic(*, route: str, to_e164: str, reply_text: str, sent_ok: bool, extra: dict | None = None) -> None:
        try:
            _doc_out = _sha1_id(f"{event_key}:out:{to_e164}:{int(time.time())}")
            payload_out = {
                "createdAt": _fs_admin().SERVER_TIMESTAMP,
                "eventKey": event_key,
                "wamid": str(wamid or "")[:180],
                "to": str(to_e164 or "")[:40],
                "route": str(route or "")[:80],
                "cta_reason": "",
                "msgType": str(msg_type or "")[:40],
                "chars": int(len(reply_text or "")),
                "sent_ok": bool(sent_ok),
                "service": "ycloud_inbound_worker",
            }
            try:
                _r = str(route or "").strip()
                if _r == "send_text_site_cta":
                    payload_out["cta_reason"] = "next_step_send_link"
                elif _r == "cta_skipped":
                    payload_out["cta_reason"] = "cta_disabled_next_step_none"
            except Exception:
                pass
            try:
                payload_out.update(_outbox_rich_enxuto(_sent_via=str(route or ""), _reply_text=str(reply_text or "")))
            except Exception:
                pass


            try:
                if isinstance(extra, dict) and extra:
                    payload_out.update(extra)
            except Exception:
                pass
            _db().collection("platform_wa_outbox_logs").document(_doc_out).set(payload_out, merge=True)
            logger.info("[tasks] wa_log_outbox ok docId=%s to=%s sent_ok=%s", _doc_out, to_e164, bool(sent_ok))
        except Exception:
            logger.warning("[tasks] wa_log_outbox_failed eventKey=%s", str(event_key or "")[:160], exc_info=True)


    # Helper sempre disponível (evita NameError se fallback rodar antes do bloco "normal")
    def _clean_url_weirdness(s: str) -> str:
        t = (s or "").strip()
        if not t:
            return t
        # normaliza variações quebradas do domínio
        t = t.replace("meirobo. com. br", "meirobo.com.br")
        t = t.replace("meirobo .com.br", "meirobo.com.br")
        t = t.replace("meirobo . com . br", "meirobo.com.br")

        # remove duplicatas do domínio (às vezes o handler coloca 2x)
        try:
            first = t.find("meirobo.com.br")
            while t.count("meirobo.com.br") > 1:
                idx = t.rfind("meirobo.com.br")
                if idx == first:
                    break
                t = (t[:idx] + t[idx+len("meirobo.com.br"):]).strip()
        except Exception:
            pass

        # garante https clicável
        if ("http://" not in t.lower()) and ("https://" not in t.lower()) and ("meirobo.com.br" in t.lower()):
            t = t.replace("meirobo.com.br", "https://www.meirobo.com.br")
        return t


    # SENTINELA: prova que o handler entrou e leu payload
    try:
        _wamid = str((payload or {}).get("wamid") or "")
        _msg_type = str(
            (payload or {}).get("msgType")
            or (payload or {}).get("messageType")
            or (payload or {}).get("msg_type")
            or (payload or {}).get("msgType")
            or ""
        )
        logger.info("[tasks] start eventKey=%s wamid=%s msgType=%s", event_key, _wamid, _msg_type)
    except Exception:
        logger.info("[tasks] start eventKey=%s (no payload details)", event_key)


    # SMOKE (FireStore): prova determinística de escrita no projeto ativo
    # - Se isso falhar, o problema é credencial/projeto/alvo, não a lógica do bot.
    try:
        _db().collection("platform_tasks_smoke").document("last").set({
            "ts": _fs_admin().SERVER_TIMESTAMP,
            "eventKey": event_key,
        }, merge=True)
    except Exception:
        logger.exception("[tasks] firestore_smoke_write_failed eventKey=%s", str(event_key or "")[:160])


    # PROVA DE VIDA (coleções esperadas): grava SEMPRE um log inbound determinístico
    # Assim você enxerga no console do Firestore mesmo que o resto do fluxo caia em fallback.
    try:
        _wamid0 = str((payload or {}).get("wamid") or "")
        _msg_type0 = str((payload or {}).get("msgType") or (payload or {}).get("messageType") or "")
        _doc0 = _sha1_id(event_key or _wamid0 or str(time.time()))
        _db().collection("platform_wa_logs").document(_doc0).set({
            "createdAt": _fs_admin().SERVER_TIMESTAMP,
            "eventKey": event_key,
            "wamid": _wamid0[:180],
            "msgType": _msg_type0[:60],
            "service": "ycloud_inbound_worker",
        }, merge=True)
        logger.info("[tasks] wa_log_inbound ok docId=%s wamid=%s eventKey=%s", _doc0, _wamid0, event_key)
    except Exception:
        logger.warning("[tasks] wa_log_inbound_failed eventKey=%s", str(event_key or "")[:160], exc_info=True)

    if not event_key or not isinstance(payload, dict):
        logger.info("[tasks] early_return reason=%s eventKey=%s wamid=%s", "BAD_REQUEST_MISSING_EVENTKEY_OR_PAYLOAD", event_key, _wamid)
        return jsonify({"ok": False, "error": "bad_request"}), 400

    # ... resto do seu handler continua INTACTO ...
    # ==========================================================
    # FILTRO DE EVENTO (anti-eco / anti-loop)
    # Worker só processa inbound real do usuário.
    # ==========================================================
    # Compat: alguns envelopes colocam o tipo fora do payload
    ev_type = (
        (payload.get("eventType") or "")
        or (data.get("eventType") or "")
        or (payload.get("type") or "")
        or (data.get("type") or "")
    )
    ev_type = str(ev_type).strip()

    eventType_missing_fallback = False

    # ✅ Aceita variações reais do YCloud
    allowed_event_types = {"whatsapp.inbound_message.received", "message", "messages", "whatsapp.message", ""}

    if ev_type not in allowed_event_types:
        _mt = str((payload or {}).get("msgType") or (payload or {}).get("messageType") or "").strip().lower()
        logger.info(
            "[tasks] early_return reason=%s eventKey=%s wamid=%s eventType=%s msgType=%s",
            "IGNORED_EVENTTYPE", event_key, (_wamid or ""), ev_type, _mt
        )
        return jsonify({"ok": True, "ignored": True, "eventType": ev_type}), 200

    # Fallback saudável: eventType pode vir vazio em testes manuais/alguns provedores.
    # Se houver sinais fortes de inbound real, marcamos para auditoria (sem bloquear).
    _mt = str((payload or {}).get("msgType") or (payload or {}).get("messageType") or "").strip().lower()
    _from0 = str((payload or {}).get("from") or "").strip()
    _to0 = str((payload or {}).get("to") or "").strip()
    _w0 = str((payload or {}).get("wamid") or (payload or {}).get("messageId") or "").strip()

    _looks_inbound = bool(_w0 and _from0 and _to0 and (_mt in ("text", "chat", "audio", "voice", "ptt")))

    if (not ev_type) and _looks_inbound:
        eventType_missing_fallback = True
        logger.info(
            "[tasks] eventType_missing_fallback=true eventKey=%s wamid=%s msgType=%s",
            event_key, (_w0 or _wamid), _mt
        )


    dedup_ttl = int(os.environ.get("CLOUD_TASKS_DEDUP_TTL_SECONDS", "86400") or "86400")
    if not _idempotency_once(event_key, ttl_seconds=dedup_ttl):
        logger.info("[tasks] early_return reason=%s eventKey=%s wamid=%s", "DEDUP_ALREADY_PROCESSED", event_key, _wamid)
        return jsonify({"ok": True, "deduped": True}), 200

    try:
        # --- normalização mínima do evento ---
        msg_type = (payload.get("messageType") or payload.get("msgType") or "").strip().lower()
        from_raw = (payload.get("from") or "").strip()
        to_raw = (payload.get("to") or "").strip()
        wamid = (payload.get("wamid") or "").strip()
        _t = payload.get("text")
        if isinstance(_t, dict):
            text_in = str(_t.get("body") or _t.get("text") or _t.get("message") or "").strip()
        else:
            text_in = str(_t or "").strip()

        # Robustez: em testes/local alguns eventos chegam sem msgType;
        # se há texto, trate como "text" para evitar lastMsgType=""
        if (not msg_type) and text_in:
            msg_type = "text"

        media = payload.get("media") or {}

        from_e164 = _to_plus_e164(from_raw)
        to_e164 = _to_plus_e164(to_raw)
        
        try:
            inst_dbg = _to_plus_e164(os.environ.get("YCLOUD_WA_FROM_E164") or "")
        except Exception:
            inst_dbg = ""
        logger.info(
            "[tasks][route_probe] from_raw=%s to_raw=%s from_e164=%s to_e164=%s inst=%s",
            from_raw, to_raw, from_e164, to_e164, inst_dbg
        )
        
        # --- resolve UID (identidade) ---

        # ----------------------------------------------------------
        # GUARD: nunca tratar o número institucional como "sender"
        # (evita marcar customer_final / uid via sender_uid_links quando a msg for do nosso WABA)
        # ----------------------------------------------------------
        inst_from_e164 = ""
        try:
            inst_from_e164 = _to_plus_e164(os.environ.get("YCLOUD_WA_FROM_E164") or "")
        except Exception:
            inst_from_e164 = ""
        skip_sender_uid_lookup = bool(inst_from_e164 and from_e164 and from_e164 == inst_from_e164)

        # 1) Quem enviou (uid_sender) — usado no fluxo institucional (to == institucional)
        uid_sender = ""
        wa_key = ""
        try:
            from services.sender_uid_links import canonical_wa_key, get_uid_for_wa_key  # type: ignore
            if (not skip_sender_uid_lookup) and from_e164:
                wa_key = (canonical_wa_key(from_e164) or "").strip()
                uid_sender = (get_uid_for_wa_key(wa_key) or "").strip()
        except Exception:
            wa_key = ""
            uid_sender = ""

        # 2) Dono do WABA (cliente final): se o toE164 NÃO for o institucional,
        # resolve UID do profissional pelo DESTINO (to_e164) via waba_owner_links/profissionais.waba
        uid_owner = ""
        try:
            if to_e164 and (not inst_from_e164 or to_e164 != inst_from_e164):
                uid_owner = _resolve_owner_uid_by_to_e164(to_e164)
        except Exception:
            uid_owner = ""

        # UID efetivo:
        # - se existir owner → cliente final (o bot responde como o profissional dono do número)
        # - senão → sender (institucional/suporte/config)
        uid = (uid_owner or uid_sender or "").strip()
        
        # --- route decision log (institucional vs cliente_final) ---
        try:
            branch = "institutional"
            actor_type = "platform_institutional"
            if uid_owner:
                branch = "customer_final"
                actor_type = "customer_final"
            elif inst_from_e164 and to_e164 and to_e164 != inst_from_e164:
                branch = "unknown_waba"
                actor_type = "unknown"

            logger.info(
                "[tasks][route_pick] branch=%s uid=%s actor_type=%s to_e164=%s inst=%s",
                branch, uid, actor_type, (to_e164 or ""), (inst_from_e164 or "")
            )
            
        except Exception:
            pass

        
        # 2) voice_links (TTL): sinal do fluxo de VOZ via WhatsApp (invite/botão)
        # IMPORTANTÍSSIMO: consultar MESMO se já existe uid, porque "configuração de voz"
        # é um modo exclusivo disparado pelo botão/invite (não depende de uid vazio).
        uid_voice_link = ""
        try:
            from services.voice_wa_link import get_uid_for_sender  # type: ignore
            uid_voice_link = (get_uid_for_sender(from_e164) or "").strip()
        except Exception:
            uid_voice_link = ""

        # Se não resolveu uid pelo wa_key, usa o voice_link (TTL) como fallback
        if (not uid) and uid_voice_link:
            uid = uid_voice_link


        # wa_key_effective: chave canônica para memória por remetente (override etc.)
        wa_key_effective = (wa_key or _digits_only(from_e164)).strip()
        owner_name = _get_owner_name(uid) if uid else ""

        # --- 1) ÁUDIO: fluxo de VOZ (ingest) ---
        voice_waiting = False
        try:
            prof = _db().collection("profissionais").document(uid).get()
            prof_data = prof.to_dict() or {}

            # Novo canônico: profissionais/{uid}.vozClonada.*
            vc = prof_data.get("vozClonada") or {}
            vc_status = str(vc.get("status") or "").strip().lower()

            # Legado (algumas versões): profissionais/{uid}.voz.whatsapp.status
            voz = prof_data.get("voz") or {}
            wa = voz.get("whatsapp") or {}
            wa_status = str(wa.get("status") or "").strip().lower()

            # Considera "aguardando áudio" em qualquer um dos schemas
            voice_waiting = (
                vc_status in (
                    "waiting",
                    "waiting_audio",
                    "awaiting_audio",
                    "invited",
                    "pending_audio",
                    "invite_sent",
                    "inviting",
                    "awaiting",
                    "awaiting_voice",
                    "awaiting_upload",
                    "waiting_voice",
                )
                or wa_status in (
                    "waiting",
                    "waiting_audio",
                    "awaiting_audio",
                    "invited",
                    "invite_sent",
                    "inviting",
                    "awaiting",
                )
            )

            # Heurística: alguns invites antigos não carimbam status no Firestore.
            # Se ainda não existe voiceId e status vier vazio, tratamos o 1º áudio como parte do onboarding.
            try:
                if (not voice_waiting) and (os.environ.get("VOICE_AUTO_ACCEPT_FIRST_AUDIO", "1") != "0"):
                    vc_voice_id = str(vc.get("voiceId") or vc.get("providerVoiceId") or "").strip()
                    if (not vc_status) and (not wa_status) and (not vc_voice_id):
                        voice_waiting = True
                        logger.info("[tasks] voice_waiting_heuristic uid=%s from=%s", uid, from_e164)
            except Exception:
                pass
        except Exception:
            voice_waiting = False

        # Em produção, o status "waiting" pode falhar por drift de schema/endpoint de invite.
        # Para deixar o fluxo redondinho: se o MEI (uid resolvido) mandar áudio, aceitamos como VOZ.
        voice_accept_any = (os.environ.get("VOICE_ACCEPT_ANY_AUDIO", "1") == "1")

        # UID efetivo para fluxo de voz (prioriza o link TTL de voice_links quando existir)
        voice_uid_effective = ((uid_voice_link or uid) or "").strip()

        if voice_uid_effective and msg_type in ("audio", "voice", "ptt") and (not voice_waiting) and (not voice_accept_any):
            # Por enquanto: áudio do cliente só é processado no onboarding de VOZ.
            # Isso evita o "áudio nada a ver" (TTS) quando o usuário manda áudio fora do fluxo de voz.
            try:
                from providers.ycloud import send_text as _send_text  # type: ignore
                _send_text(
                    to_e164=from_e164,
                    text="📌 Recebi seu áudio 🙂\nNo momento eu só entendo áudio quando você está ativando a Voz do Atendimento.\nSe quiser falar comigo agora, me manda em texto aqui no WhatsApp."
                )
            except Exception:
                logger.exception("[tasks] customer_audio: falha ao enviar aviso texto wamid=%s eventKey=%s", wamid, event_key)
            logger.info("[tasks] early_return reason=%s eventKey=%s wamid=%s", "CUSTOMER_AUDIO_NOT_WAITING_TEXT_ONLY", event_key, wamid)
            return jsonify({"ok": True, "audio": "ignored_not_waiting"}), 200
        if voice_uid_effective and msg_type in ("audio", "voice", "ptt") and (voice_waiting or voice_accept_any):
            try:
                from services.voice_wa_download import download_media_bytes  # type: ignore
                from services.voice_wa_storage import upload_voice_bytes  # type: ignore
                from services.voice_wa_link import upsert_sender_link  # type: ignore
                from services.firebase_admin_init import ensure_firebase_admin  # type: ignore

                ensure_firebase_admin()

                provider = (payload.get("provider") or "ycloud")

                # Baixa bytes + mime do provedor (ycloud)
                b, mime = download_media_bytes(provider, media)

                ext_hint = "ogg"
                try:
                    from services.voice_wa_download import sniff_extension  # type: ignore
                    ext_hint = sniff_extension(mime or "", fallback="ogg")
                except Exception:
                    logger.exception("[tasks] outbox_final_write_fail wamid=%s eventKey=%s", wamid, event_key)

                # Caminho padrão já usado no projeto (não muda contrato)
                storage_path = f"profissionais/{uid}/voz/original/whatsapp_{int(time.time())}.{ext_hint}"

                # Assinatura correta: (storage_path, content_type, data)
                storage_path = upload_voice_bytes(storage_path, (mime or "audio/ogg"), b)
# status em doc do profissional (compat com o que já existe no webhook)
                try:
                    _db().collection("profissionais").document(uid).set(
                        {
                            "vozClonada": {
                                "status": "uploaded",
                                "object_key": storage_path,
                                "updatedAt": time.time(),
                                "lastError": "",
                            }
                        },
                        merge=True,
                    )
                except Exception:
                    pass


                # ✅ IMPORTANTÍSSIMO: encerra o modo "waiting" após receber 1 áudio válido.
                # Isso destrava SUPORTE imediatamente, sem precisar esperar TTL.
                try:
                    _db().collection("profissionais").document(uid).set(
                        {
                            "voz": {
                                "whatsapp": {
                                    "status": "received",
                                    "lastError": "",
                                    "lastAudioGcsPath": storage_path,
                                    "lastAudioMime": (mime or "audio/ogg"),
                                    "lastInboundAt": _fs_admin().SERVER_TIMESTAMP,
                                    "updatedAt": _fs_admin().SERVER_TIMESTAMP,
                                    "waFromE164": from_e164,
                                }
                            }
                        },
                        merge=True,
                    )
                except Exception:
                    pass

                # renova vínculo (from -> uid), tolerante ao 9 via store já existente
                try:
                    ttl_seconds = int(os.environ.get("VOICE_LINK_TTL_SECONDS", "86400") or "86400")
                    upsert_sender_link(from_e164, uid, ttl_seconds=ttl_seconds, method="audio_auto")
                except Exception:
                    pass

                # ACK opcional (mesmo comportamento do webhook antigo)
                # Default ON (1) para evitar silêncio quando o áudio foi aceito/armazenado.
                if os.environ.get("VOICE_WA_ACK", "1") != "0":
                    try:
                        # Idempotência do ACK (evita mandar 2x em retries/duplicatas)
                        _wm = str(wamid or "").strip()
                        _ek = str(event_key or "").strip()
                        _dedupe_basis = _wm or _ek
                        _ack_key = _sha1_id(f"voice_ack:{_dedupe_basis}")
                        _ack_ref = _db().collection("platform_tasks_dedup").document(_ack_key)
                        _ack_snap = _ack_ref.get()
                        if _ack_snap.exists:
                            logger.info("[tasks] voice_ack: already_sent eventKey=%s wamid=%s", event_key, wamid)
                        else:
                            _ack_ref.set(
                                {
                                    "eventKey": _ek,
                                    "wamid": _wm,
                                    "kind": "voice_ack",
                                    "createdAt": _fs_admin().SERVER_TIMESTAMP,
                                },
                                merge=True,
                            )
                        from providers.ycloud import send_text  # type: ignore
                        if not _ack_snap.exists:
                            send_text(
                                to_e164=from_e164,
                                text="✅ Áudio recebido! Vou preparar sua Voz do Atendimento.\nAgora volte para a tela de configuração e clique em Continuar."
                            )
                    except Exception:
                        logger.exception("[tasks] voice: falha ao enviar ACK via WhatsApp")

                try:
                    _db().collection("platform_wa_outbox_logs").add({
                        "createdAt": _fs_admin().SERVER_TIMESTAMP,
                        "from": from_e164,
                        "to": from_e164,
                        "wamid": wamid,
                        "msgType": msg_type,
                        "route": "voice_ingest",
                        "replyText": "ACK: voz recebida (configuração)",
                        "audioUrl": "",
                        "audioDebug": {},
                        "eventKey": event_key,
                        "sentOk": True,
                    })
                    logger.info("[tasks] outbox_final_write_ok wamid=%s eventKey=%s", wamid, event_key)

                except Exception:
                    pass
                logger.info("[tasks] early_return reason=%s eventKey=%s wamid=%s", "VOICE_INGEST_ACK_TEXT_ONLY", event_key, wamid)
                return jsonify({"ok": True, "voice": "stored"}), 200

            except Exception:
                logger.exception("[tasks] voice: falha ingest uid=%s", uid)
                logger.info("[tasks] early_return reason=%s eventKey=%s wamid=%s", "VOICE_INGEST_FAILED", event_key, wamid)
                return jsonify({"ok": True, "voice": "failed"}), 200

        # --- 2) LEAD / TEXTO: chama WA_BOT (vendas se uid vazio) ---
        reply_text = ""
        audio_url = ""
        audio_debug = {}
        tts_text_final_used = ""  # texto final que foi pro TTS
        wa_out = None

        speaker_state = {}  # cache local p/ gate de nome no TTS

        try:
            # Firebase Admin (Firestore) — harden Cloud Run
            try:
                from services.firebase_admin_init import ensure_firebase_admin as _ensure_firebase_admin  # type: ignore
                _ensure_firebase_admin()
            except Exception as e:
                # Em Cloud Run, preferimos NÃO matar o worker aqui.
                # Se Firebase admin falhar, ainda podemos responder fallback (texto)
                import traceback as _tb
                logger.error("[tasks] firebase_admin_init_failed (will fallback) err=%s", f"{type(e).__name__}:{str(e)[:200]}")
                logger.error("[tasks] firebase_admin_init_failed_traceback\n%s", _tb.format_exc())
                firebase_failed = True
            else:
                firebase_failed = False

            # Se Firebase falhou, evita chamar wa_bot (que depende de Firestore) e responde fallback curto
            if firebase_failed:
                reply_text = "Tive uma instabilidade aqui. Pode mandar sua mensagem de novo? 🙂"
                spoken_text = reply_text
                audio_url = ""
                try:
                    audio_debug = dict(audio_debug or {})
                    audio_debug["firebaseAdmin"] = {"ok": False, "reason": "init_failed"}
                except Exception:
                    pass
                prefers_text = True
                wa_kind = "fallback"
                kb_context = ""
                # cai adiante no bloco de envio (send_text), sem quebrar o worker
                wa_out = {
                    "ok": True,
                    "route": "voice_config_ack",
                    "route_hint": "voice_config_ack",
                    "replyText": reply_text,
                    "spokenText": spoken_text,
                    "audioUrl": "",
                    "audioDebug": audio_debug,
                    "prefersText": False,
                    "kind": wa_kind,
                    "kbContext": kb_context,
                    "understanding": {"source": "voice_config_ack", "intent": "VOICE_CONFIG", "confidence": "high", "next_step": "WAIT"},
                    "_debug": {"source": "voice_config_ack"},
                }
                skip_wa_bot = True
            else:
                from services import wa_bot as wa_bot_entry  # lazy import
                route_hint = "sales" if not uid else "customer"

            skip_wa_bot = False

            if msg_type in ("audio", "voice", "ptt") and not text_in:
                # Áudio de lead: baixar mídia e transcrever (STT) antes da IA
                transcript = ""
                stt_err = ""

                try:
                    url = ""
                    try:
                        url = (media.get("url") or "").strip()
                    except Exception:
                        url = ""

                    if not url:
                        stt_err = "no_media_url"
                    else:
                        # Preferir o downloader já usado no fluxo de voz (tende a lidar melhor com headers/auth)
                        audio_bytes = b""
                        ctype = ""

                        try:
                            from services.voice_wa_download import download_media_bytes  # type: ignore
                            provider = (payload.get("provider") or "ycloud")
                            audio_bytes, mime = download_media_bytes(provider, media)
                            ctype = (mime or "audio/ogg").split(";")[0].strip() or "audio/ogg"
                        except Exception:
                            # Fallback: download direto
                            r = requests.get(url, timeout=12)
                            r.raise_for_status()
                            audio_bytes = r.content
                            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()

                        if not audio_bytes or len(audio_bytes) < 200:
                            stt_err = "empty_audio_bytes"
                        else:
                            # Chama STT interno via HTTP (mesmo serviço)
                            try:
                                base = _backend_base(request)
                                stt_url = f"{base}/api/voz/stt"

                                headers = {"Content-Type": ctype or "audio/ogg"}
                                from subprocess import Popen, PIPE

                                def normalize_audio_for_stt(raw: bytes) -> bytes:
                                    p = Popen(
                                        [
                                            "ffmpeg",
                                            "-i", "pipe:0",
                                            "-ac", "1",
                                            "-ar", "16000",
                                            "-f", "wav",
                                            "pipe:1",
                                        ],
                                        stdin=PIPE,
                                        stdout=PIPE,
                                        stderr=PIPE,
                                    )
                                    out, _ = p.communicate(raw)
                                    return out if out else raw

                                audio_bytes = normalize_audio_for_stt(audio_bytes)
                                headers = {"Content-Type": "audio/wav"}

                                rr = requests.post(stt_url, data=audio_bytes, headers=headers, timeout=25)
                                stt_payload = {}
                                try:
                                    if rr.status_code == 200:
                                        # tenta JSON (sem explodir)
                                        try:
                                            stt_payload = rr.json() if rr.headers.get("content-type","").startswith("application/json") else {}
                                        except Exception:
                                            stt_payload = {}

                                        ok_flag = bool(stt_payload.get("ok"))
                                        transcript = (stt_payload.get("transcript") or "").strip() if ok_flag else ""
                                        if ok_flag and transcript:
                                            text_in = transcript
                                            audio_debug["stt"] = {
                                                "ok": True,
                                                "confidence": stt_payload.get("confidence"),
                                                "transcriptLen": len(transcript),
                                                "preview": transcript[:120],
                                            }
                                        else:
                                            # motivo real (ex.: empty_transcript / stt_failed)
                                            err_code = (stt_payload.get("error") or "").strip() or f"http_{rr.status_code}"
                                            detail = (stt_payload.get("detail") or "").strip()
                                            stt_err = f"stt_not_ok:{err_code}" + (f":{detail[:80]}" if detail else "")
                                            audio_debug["stt"] = {
                                                "ok": False,
                                                "error": err_code,
                                                "detail": detail[:160],
                                                "http": rr.status_code,
                                                "bodyHint": (rr.text or "")[:160],
                                            }
                                            logger.warning(
                                                "[tarefas] stt_not_ok from=%s wamid=%s err=%s detail=%s",
                                                from_e164, wamid, err_code, detail[:120]
                                            )
                                    else:
                                        stt_err = f"stt_http_{rr.status_code}"
                                        audio_debug["stt"] = {"ok": False, "http": rr.status_code, "bodyHint": (rr.text or "")[:160]}
                                except Exception as e:
                                    stt_err = f"stt_exc:{type(e).__name__}"
                                    audio_debug["stt"] = {"ok": False, "reason": stt_err}
                            except Exception as e:
                                stt_err = f"stt_exc:{e}"

                except Exception as e:
                    stt_err = f"stt_outer_exc:{e}"

                if transcript:
                    text_in = transcript
                    # mantém detalhes do STT (não sobrescreve)
                    audio_debug = dict(audio_debug or {})
                    audio_debug.setdefault("stt", {"ok": True})
                else:
                    # PATCH 1 (worker): se STT não trouxe transcript, NÃO chama IA.
                    logger.warning("[tasks] lead: stt_failed from=%s wamid=%s reason=%s", from_e164, wamid, stt_err)
                    reply_text = "Não consegui entender esse áudio. Pode mandar em texto ou repetir rapidinho?"
                    skip_wa_bot = True
                    audio_debug = dict(audio_debug or {})
                    audio_debug.setdefault("stt", {"ok": False, "reason": stt_err})


            # ==========================================================
            # IDENTIDADE PREMIUM (interlocutor ativo)
            # - Primeiro tenta override por regex (barato)
            # - Se não tiver, e houver gatilho, chama IA (curta) e persiste
            # ==========================================================
            try:
                nm = _detect_name_override(text_in)
                if nm and wa_key_effective:
                    _set_name_override(wa_key_effective, nm)
                    # também seta interlocutor ativo (garante 2ª mensagem)
                    if _IDENTITY_MODE != "off":
                        _set_active_speaker(wa_key_effective, nm, source="regex", confidence=0.70)
                    audio_debug = dict(audio_debug or {})
                    audio_debug["nameOverrideProbe_set"] = {"waKey": wa_key_effective, "name": nm}
            except Exception:
                pass

            # IA: só quando tem sinal de troca/apresentação e ainda não temos speaker bom
            try:
                if _IDENTITY_MODE != "off" and wa_key_effective and text_in:
                    active_now = _get_active_speaker(wa_key_effective)
                    # se já temos active speaker e não há sinal, não gasta IA
                    if _looks_like_identity_signal(text_in) and (not active_now):
                        name_ai, conf_ai, reason_ai = _openai_extract_speaker(
                            text_in,
                            owner_name=owner_name,
                            active_name=active_now,
                        )
                        audio_debug = dict(audio_debug or {})
                        audio_debug["speakerAI"] = {
                            "triggered": True,
                            "ownerName": owner_name,
                            "activeBefore": active_now,
                            "identifiedName": name_ai,
                            "confidence": conf_ai,
                            "reason": reason_ai,
                        }
                        # Persistir se confiança razoável
                        if name_ai and conf_ai >= 0.65:
                            _set_active_speaker(wa_key_effective, name_ai, source="ai", confidence=conf_ai)
                            # mantém override antigo também (compat)
                            _set_name_override(wa_key_effective, name_ai)
                            audio_debug["speakerAI"]["persisted"] = True
                        else:
                            audio_debug["speakerAI"]["persisted"] = False
                    else:
                        # debug leve (sem custo)
                        audio_debug = dict(audio_debug or {})
                        audio_debug["speakerAI"] = {
                            "triggered": False,
                            "activeBefore": active_now,
                            "hasSignal": bool(_looks_like_identity_signal(text_in)),
                        }
            except Exception:
                pass

            if hasattr(wa_bot_entry, "reply_to_text"):
                if skip_wa_bot:
                    wa_out = {"replyText": reply_text, "audioUrl": "", "audioDebug": audio_debug}
                else:
                    # ==========================================================
                    # Lead hints (segmento / nome) — lookup O(1)
                    # Não altera fluxo: só enriquece contexto se existir
                    # ==========================================================
                    segment_hint = ""
                    name_hint = ""
                    try:
                        leads_coll = os.getenv("INSTITUTIONAL_LEADS_COLL", "institutional_leads")
                        wa_key_digits = _digits_only(from_e164)
                        if wa_key_digits:
                            lead_doc = _db().collection(leads_coll).document(wa_key_digits).get()
                            if lead_doc.exists:
                                ld = lead_doc.to_dict() or {}
                                segment_hint = str(ld.get("segment") or "").strip()
                                name_hint = str(ld.get("name") or ld.get("displayName") or "").strip()
                    except Exception:
                        pass

                    ctx_for_bot = {
                        "from_e164": from_e164,   # cliente final
                        "to_e164": to_e164,       # número que recebeu (WABA)
                        # chave canônica (sempre digits-only, compatível com institutional_leads/{waKey})

                        "waKey": _digits_only(from_e164),
                        "msg_type": msg_type,
                        "wamid": wamid,
                        "route_hint": route_hint,
                        "event_key": event_key,
                        "uid_owner": uid_owner,
                        "uid_sender": uid_sender,
                    }

                    if segment_hint:
                        ctx_for_bot["segment_hint"] = segment_hint
                    if name_hint:
                        ctx_for_bot["name_hint"] = name_hint

                    # ----------------------------------------------------------
                    # CARIMBO DE ROTA (multi-WABA)
                    # ----------------------------------------------------------
                    if uid_owner:
                        ctx_for_bot["actor_type"] = "customer_final"
                        ctx_for_bot["uid_owner"] = uid_owner
                        ctx_for_bot["uid_sender"] = uid_sender
                        uid = uid_owner  # responde como o profissional dono do WABA
                    elif uid_sender:
                        ctx_for_bot["actor_type"] = "support"
                        ctx_for_bot["uid_sender"] = uid_sender
                    else:
                        ctx_for_bot["actor_type"] = "lead"

                    # ----------------------------------------------------------
                    # LOG CIRÚRGICO (observabilidade Cliente Zero)
                    # ----------------------------------------------------------
                    try:
                        logger.info(
                            "[TASKS][CTX] actor_type=%s uid_owner=%s from=%s to=%s waKey=%s",
                            ctx_for_bot.get("actor_type"),
                            (ctx_for_bot.get("uid_owner") or "")[:12],
                            (from_e164 or "")[:16],
                            (to_e164 or "")[:16],
                            (ctx_for_bot.get("waKey") or "")[:16],
                        )
                    except Exception:
                        pass

                    # PATCH A (obrigatório): garantir msg_type no ctx do wa_bot
                    ctx_for_bot["msg_type"] = msg_type  # "audio" | "voice" | "ptt" | "text"

                    wa_out = wa_bot_entry.reply_to_text(

                        uid=uid,
                        text=text_in,
                        ctx=ctx_for_bot,
                    )

                    # PATCH: preencher audio_debug["source"] ANTES de montar waOutMeta
                    # (evita source=null no waOutMeta)
                    try:
                        if isinstance(wa_out, dict) and isinstance(audio_debug, dict):
                            # preferência: _debug.source -> understanding.source -> inferido por route_hint
                            _u_src = ""
                            try:
                                _u = wa_out.get("understanding")
                                if isinstance(_u, dict):
                                    _u_src = str(_u.get("source") or "").strip()
                            except Exception:
                                _u_src = ""
                            dbg = wa_out.get("_debug")
                            if isinstance(dbg, dict):
                                _src = (dbg.get("source") or "").strip()
                                if not _src:
                                    _src = _u_src or ("sales_lead" if str(route_hint or "").strip().lower() == "sales" else "wa_bot")
                                audio_debug["source"] = _src
                                audio_debug["planner"] = {
                                    "intent": dbg.get("intent") or "",
                                    "next_step": dbg.get("next_step") or "",
                                    "composer_mode": dbg.get("composer_mode") or "",
                                }
                            else:
                                # nunca loga como "unknown"; se não veio _debug, inferimos pelo route_hint
                                audio_debug["source"] = (
                                    audio_debug.get("source")
                                    or _u_src
                                    or ("sales_lead" if str(route_hint or "").strip().lower() == "sales" else "wa_bot")
                                )
                    except Exception:
                        pass

                    # ==========================================================
                    # DEBUG (produto): prova do que veio do wa_bot
                    # - não altera comportamento
                    # - ajuda a confirmar se displayName/prefersText/ttsOwner estão chegando
                    # ==========================================================
                    try:
                        if isinstance(wa_out, dict):
                            audio_debug = dict(audio_debug or {})
                            audio_debug["waOutMeta"] = {
                                "route": str(wa_out.get("route") or "")[:80],
                                "hasAudioUrl": bool(str((wa_out.get("audioUrl") or wa_out.get("audio_url") or "")).strip()),
                                "prefersText": bool(wa_out.get("prefersText")),
                                "replySource": str(wa_out.get("replySource") or wa_out.get("reply_source") or "")[:40],
                                "kbSnapshotSizeChars": int(wa_out.get("kbSnapshotSizeChars") or 0) if isinstance(wa_out, dict) else 0,
                                "displayName": str(
                                    wa_out.get("displayName")
                                    or wa_out.get("leadName")
                                    or wa_out.get("nameToSay")
                                    or ""
                                ).strip()[:40],
                                "ttsOwner": str(wa_out.get("ttsOwner") or "").strip()[:40],
                                "source": (audio_debug.get("source") if isinstance(audio_debug, dict) else ""),
                            }
                    except Exception:
                        pass

        except Exception as e:
            # Best-effort: não derruba o worker se o wa_bot falhar/import quebrar
            # (Cloud Run às vezes trunca logger.exception; então imprimimos traceback explícito também)
            import traceback as _tb  # local import (mínimo)
            tb_txt = _tb.format_exc()
            logger.exception(
                "[tasks] wa_bot_failed route_hint=%s from=%s wamid=%s",
                ("sales" if not uid else "customer"), from_e164, wamid
            )
            logger.error(
                "[tasks] wa_bot_failed_traceback route_hint=%s from=%s wamid=%s\n%s",
                ("sales" if not uid else "customer"), from_e164, wamid, tb_txt
            )
            reply_text = ""
            audio_url = ""
            audio_debug = {"err": f"{type(e).__name__}:{str(e)[:200]}", "trace": "wa_bot_failed"}
            kb_context = ""
            wa_kind = ""

        # --- Extração canônica do retorno do wa_bot (texto/áudio/debug) ---
        prefers_text = False
        # Default seguro: se algum caminho não setar allow_audio, não quebra o worker
        allow_audio = True

        has_audio = False
        display_name = ""
        tts_text_from_bot = ""
        tts_text_from_bot_source = ""
        allow_sales_demo = False
        plan_next_step = ""
        intent_final = ""
        policies_applied = []
        # Observabilidade IA-first (não muda comportamento): entendimento/custo/risco
        understanding = {}
        name_use = ""
        if isinstance(wa_out, dict):
            reply_text = (
                wa_out.get("replyText")
                or wa_out.get("text")
                or wa_out.get("reply")
                or wa_out.get("message")
                or ""
            )
            prefers_text = bool(wa_out.get("prefersText"))
            plan_next_step = str(wa_out.get("planNextStep") or "").strip().upper()
            reply_text = _ensure_send_link_in_reply(reply_text, plan_next_step)
            tts_owner = str(wa_out.get("ttsOwner") or "").strip().lower()

            # Guard-rail: entrada é áudio e o áudio é do WORKER.
            # Não deixar prefersText=True matar TTS por engano.
            # Exceção: SEND_LINK deve continuar texto (link não vai no áudio).
            if msg_type in ("audio", "voice", "ptt") and tts_owner == "worker":
                if plan_next_step != "SEND_LINK" and prefers_text:
                    prefers_text = False
            # Blindagem: se o bot quer texto e o reply contém link, nunca "perder" o texto.
            # (evita casos onde a pipeline envia só áudio e o link some)
            try:
                if prefers_text and isinstance(reply_text, str) and ("http://" in reply_text or "https://" in reply_text):
                    allow_audio = True  # mantém áudio ACK se houver
            except Exception:
                pass
            audio_url = (wa_out.get("audioUrl") or wa_out.get("audio_url") or "").strip()
            if audio_url:
                has_audio = True
            wa_audio_debug = wa_out.get("audioDebug") or {}
            if isinstance(wa_audio_debug, dict):
                # merge: preserva o que o worker já tinha + adiciona o do wa_bot
                audio_debug = {**(audio_debug or {}), **wa_audio_debug}
            kb_context = (wa_out.get("kbContext") or wa_out.get("kb_context") or "")
            wa_kind = (wa_out.get("kind") or wa_out.get("type") or "")
            plan_next_step = str(wa_out.get("planNextStep") or wa_out.get("plan_next_step") or "").strip().upper()

            # 📐 NORMALIZA prefersText (SHOW institucional consistente)
            try:
                _mt = (msg_type or "").lower()
                _pns = (plan_next_step or "").strip().upper()

                # Se inbound é áudio → padrão é responder com áudio
                if _mt in ("audio", "voice", "ptt") and _pns != "SEND_LINK":
                    prefers_text = False

                # SEND_LINK sempre força texto (evita áudio lendo URL)
                if _pns == "SEND_LINK":
                    prefers_text = True

            except Exception as _e:
                logger.warning(f"[tasks][prefers_normalize] {_e}")

            intent_final = str(wa_out.get("intentFinal") or wa_out.get("intent_final") or "").strip().upper()
            policies_applied = wa_out.get("policiesApplied") or []
            if not isinstance(policies_applied, list):
                policies_applied = []
            # prefers_text já setado acima
            # display_name vem do handler (leadName/nameToSay) ou de displayName (compat)
            display_name = ((wa_out.get("displayName") or "") or (wa_out.get("leadName") or "") or (wa_out.get("nameToSay") or "")).strip()
            _spoken_from_bot = str(wa_out.get("spokenText") or "").strip()
            _tts_from_bot = str(wa_out.get("ttsText") or wa_out.get("tts_text") or "").strip()
            if _spoken_from_bot:
                tts_text_from_bot = _spoken_from_bot
                tts_text_from_bot_source = "spokenText"
            elif _tts_from_bot:
                tts_text_from_bot = _tts_from_bot
                tts_text_from_bot_source = "ttsText"
            else:
                tts_text_from_bot = ""
                tts_text_from_bot_source = ""
            allow_sales_demo = bool(wa_out.get("allowSalesDemo"))
            # Se o handler não manda "understanding", construímos a partir do que ele já manda:
            # planIntent/planNextStep/decisionDebug (sales_lead.py já devolve isso)
            try:
                _u = wa_out.get("understanding")
                if isinstance(_u, dict) and _u:
                    understanding = _u
                else:
                    _pi = str(wa_out.get("planIntent") or intent_final or "").strip()
                    _pn = str(wa_out.get("planNextStep") or plan_next_step or "").strip()
                    _dd = wa_out.get("decisionDebug") if isinstance(wa_out.get("decisionDebug"), dict) else {}
                    _conf = str((_dd or {}).get("confidence") or "").strip().lower()
                    if _conf not in ("high", "mid", "low"):
                        _conf = ""
                    understanding = {
                        "intent": (_pi or "").strip(),
                        "next_step": (_pn or "").strip(),
                        "confidence": _conf,
                        "risk": ("high" if _conf == "low" else ("mid" if _conf == "mid" else "low")) if _conf else "",
                        "depth": "economic" if str(_pn).strip().upper() in ("PRICE","SEND_LINK") or str(_pi).strip().upper() in ("PRICE","PLANS","DIFF","PROCESS","SLA","VOICE","ACTIVATE") else "deep",
                    }
            except Exception:
                pass

            
            # ----------------------------------------------------------
            # Rota (front vs legacy) — para telemetria e "IA first"
            # ----------------------------------------------------------
            _route = ""
            _is_front = False
            try:
                _route = str(wa_out.get("route") or "").strip().lower()
                if not _route:
                    # fallbacks possíveis
                    _route = str(((audio_debug.get("waOutMeta") or {}) if isinstance(audio_debug.get("waOutMeta"), dict) else {}).get("route") or "").strip().lower()
                _is_front = _route in ("front", "conversational_front", "conversationalfront")
            except Exception:
                _route = ""
                _is_front = False

            # ----------------------------------------------------------
            # REGRA DE PRODUTO (canônica):
            # entrou por ÁUDIO -> deve sair por ÁUDIO
            # EXCEÇÃO: SEND_LINK (precisa do link em texto)
            # Observação: o Conversational Front pode vir com prefersText=true por padrão;
            # aqui a gente neutraliza isso no worker quando a entrada foi áudio.
            # ----------------------------------------------------------
            try:
                if msg_type in ("audio", "voice", "ptt"):
                    _ns = str(plan_next_step or "").strip().upper()
                    if _is_front and _ns != "SEND_LINK":
                        prefers_text = False
            except Exception:
                pass

            # Se veio do FRONT, evita carimbo de fallback do worker/legacy
            try:
                if _is_front and isinstance(understanding, dict):
                    _src = str(understanding.get("source") or "").strip()
                    _src_l = _src.lower()
                    if (not _src) or _src_l.startswith("worker_fallback") or _src_l.startswith("fallback_") or _src_l.startswith("empty_reply"):
                        understanding["source"] = "front"
            except Exception:
                pass

# Normalização final (não muda comportamento): evita ia_first vazio
            try:
                if isinstance(understanding, dict):
                    _ii = str(understanding.get("intent") or "").strip().upper()
                    _nn = str(understanding.get("next_step") or "").strip().upper()
                    if not _ii:
                        _ii = str(intent_final or wa_out.get("planIntent") or "").strip().upper()
                    if not _nn:
                        _nn = str(plan_next_step or wa_out.get("planNextStep") or "").strip().upper()
                    # só seta se conseguimos algo; senão mantém como está
                    if _ii:
                        understanding["intent"] = _ii
                    if _nn:
                        understanding["next_step"] = _nn
            except Exception:
                pass
            try:
                if _is_front:
                    route_hint = "conversational_front"
            except Exception:
                pass
            # Observabilidade IA-first (fallback): garante campos básicos no understanding
            try:
                # Se o wa_bot retornou FRONT, o worker NÃO pode carimbar fallback no entendimento.
                _route_hint = ""
                try:
                    _route_hint = (wa_out.get("route") or wa_out.get("replySource") or wa_out.get("route_hint") or "").strip().lower()
                except Exception:
                    _route_hint = ""
                _is_front = _route_hint in ("front", "conversational_front", "conversationalfront")

                if not isinstance(understanding, dict):
                    understanding = {}

                # Só marque fallback quando NÃO for FRONT
                if not understanding.get("source") and (not _is_front):
                    understanding["source"] = "worker_fallback_from_wa_out"

                if not understanding.get("intent"):
                    understanding["intent"] = intent_final or ""
                if not understanding.get("next_step"):
                    understanding["next_step"] = plan_next_step or ""
                if eventType_missing_fallback:
                    understanding["eventType_missing_fallback"] = True

            except Exception:
                pass



            


            # name_use: preferir campo direto (novo) e cair para understanding.*



            try:



                name_use = str(



                    wa_out.get("nameUse")



                    or wa_out.get("name_use")



                    or (understanding.get("name_use") if isinstance(understanding, dict) else "")



                    or ""



                ).strip().lower()



            except Exception:



                name_use = ""

# A2: propaga _debug do handler para facilitar auditoria (planner/composer/fallback/worker)
            # ==========================================================
            # spokenText final (base para TTS)
            # - Prioridade: tts_text_from_bot (já "speechified") -> spokenText -> reply_text
            # ==========================================================
            spoken_text = ""
            try:
                _route_hint = (wa_out.get("route") or wa_out.get("replySource") or wa_out.get("route_hint") or "").strip().lower()
                _is_front = _route_hint in ("front", "conversational_front", "conversationalfront")

                _spoken_from_bot = (
                    (tts_text_from_bot or "").strip()
                    or str(wa_out.get("spokenText") or "").strip()
                )
                preserve_sales_surface = _keep_sales_surface_from_bot(
                    wa_out=wa_out if isinstance(wa_out, dict) else {},
                    uid=uid,
                )

                if _spoken_from_bot:
                    spoken_text = _spoken_from_bot
                elif preserve_sales_surface:
                    spoken_text = (reply_text or "").strip()
                else:
                    # Só compõe quando não veio spoken pronto
                    spoken_text = _make_tts_text((reply_text or "").strip(), display_name, add_acervo_cta=(not _is_front))
            except Exception:
                spoken_text = (reply_text or "").strip()

            # UX (produto): em VENDAS, o nome NÃO deve vir "colado" no spokenText do bot.
            # A IA só sinaliza via name_use; o worker decide (gate) se aplica no áudio.
            try:
                if (not bool(uid)) and spoken_text and display_name:
                    _st2, _removed = _strip_leading_name_prefix(spoken_text, str(display_name))
                    if _removed:
                        spoken_text = _st2
                        if isinstance(audio_debug, dict):
                            audio_debug["namePrefixStripped"] = True
            except Exception:
                pass

            # ==========================================================

            # UX: micro-empatia curta no ÁUDIO (sem script, sem textão)

            # - Só quando faz sentido comercial:

            #   a) fechamento (SEND_LINK) ou

            #   b) confidence=high em intents "quentes"

            # - Não duplica se já começou com validação/saudação.

            # ==========================================================

            try:

                conf = ""

                intent_u = ""

                if isinstance(understanding, dict):

                    conf = str(understanding.get("confidence") or "").strip().lower()

                    intent_u = str(understanding.get("intent") or "").strip().upper()

            

                hot_intents = {"PRICE", "AGENDA", "WHAT_IS", "OPERATIONAL"}

                should_spice = (

                    str(plan_next_step or "").strip().upper() == "SEND_LINK"

                    or (conf == "high" and intent_u in hot_intents)

                )

            

                preserve_sales_surface = _keep_sales_surface_from_bot(
                    wa_out=wa_out if isinstance(wa_out, dict) else {},
                    uid=uid,
                )

                if (not preserve_sales_surface) and should_spice and spoken_text:

                    low0 = spoken_text[:60].lower()

                    already_warm = any(

                        k in low0

                        for k in (

                            "perfeito", "fechado", "boa", "ótimo", "top", "show",

                            "entendi", "beleza", "claro", "massa", "tranquilo",

                            "bom dia", "boa tarde", "boa noite", "oi"

                        )

                    )

                    if not already_warm:

                        # 1 frase curta e humana (sem telemarketing)

                        prefix = "Fechado. " if str(plan_next_step or "").strip().upper() == "SEND_LINK" else "Perfeito — entendi. "

                        spoken_text = prefix + spoken_text.lstrip()

            except Exception:

                pass


            dbg = wa_out.get("_debug") if isinstance(wa_out, dict) else None

            # marca quem gerou (planner/composer/fallback/worker etc.)
            if isinstance(audio_debug, dict) and isinstance(dbg, dict):
                _dbg_src = str(dbg.get("source") or "").strip()
                _u_src2 = ""
                try:
                    _u2 = wa_out.get("understanding") if isinstance(wa_out, dict) else None
                    if isinstance(_u2, dict):
                        _u_src2 = str(_u2.get("source") or "").strip()
                except Exception:
                    _u_src2 = ""
                audio_debug["source"] = (
                    _dbg_src
                    or str(audio_debug.get("source") or "").strip()
                    or _u_src2
                    or ("sales_lead" if (route_hint == "sales") else "wa_bot")
                )
                audio_debug["planner"] = {
                    "intent": dbg.get("intent") or "",
                    "next_step": dbg.get("next_step") or "",
                    "composer_mode": dbg.get("composer_mode") or "",
                }
            elif isinstance(audio_debug, dict):
                audio_debug["source"] = audio_debug.get("source") or ("sales_lead" if (route_hint == "sales") else "wa_bot")
        elif wa_out:
            reply_text = str(wa_out)
        reply_text = reply_text or ""

        # ==========================================================
        # GUARD (produto): SEND_LINK => texto com link SEMPRE
        # - Se planNextStep=SEND_LINK, manda link por texto mesmo quando a trilha principal é áudio.
        # - Mantém rastreio/auditoria: outbox + deliveryMode=site_link.
        # ==========================================================
        force_send_link_text = False
        try:
            if str(plan_next_step or "").strip().upper() == "SEND_LINK":
                force_send_link_text = True
        except Exception:
            force_send_link_text = False


        # ==========================================================
        # CTA Guard (produto): NÃO mandar link automático
        # - Só permite CTA/link se:
        #   a) planNextStep == SEND_LINK  (force_send_link_text=True), ou
        #   b) o lead pediu link explicitamente ("me manda o link", "site", "onde assina", etc.)
        # ==========================================================
        explicit_link_request = False
        try:
            _trL = str(transcript or text_in or "").strip().lower()
            if _trL:
                link_words = (
                    "me manda o link", "manda o link", "me envia o link", "envia o link",
                    "o link", "qual o link", "tem o link",
                    "site", "site de vocês", "site oficial",
                    "onde assina", "como assino", "como assinar",
                    "onde contratar", "como contratar",
                    "procedimento pra assinar", "procedimento para assinar",
                    "assinar", "assinatura", "contratar",
                )
                explicit_link_request = any(w in _trL for w in link_words)
        except Exception:
            explicit_link_request = False


        # SENTINELA: prova que gerou (ou não) conteúdo
        logger.info("[tasks] computed reply chars=%d prefers_text=%s has_audio=%s",
                    len((reply_text or "").strip()), bool(prefers_text), bool(has_audio))


        # Sentinela curta IA-first (não quebra nada; ajuda diagnóstico sem Firestore)
        # Log rápido (Cloud Run) pra você ver sem Firestore
        try:
            if isinstance(understanding, dict) and understanding:
                logger.info(
                    "[tasks] ia_first intent=%s conf=%s risk=%s depth=%s next=%s source=%s front=%s route_hint=%s",
                    str(understanding.get("intent") or ""),
                    str(understanding.get("confidence") or ""),
                    str(understanding.get("risk") or ""),
                    str(understanding.get("depth") or ""),
                    str(understanding.get("next_step") or ""),
                    str(understanding.get("source") or ""),
                    str(_is_front),
                    str(_route_hint),
                )
        except Exception:
            pass



        
        # ==========================================================
        # Pacote 2 — Memória/CRM do Lead (afinidade + marketing)
        # Garante que as coleções apareçam e sejam atualizadas SEM depender do handler.
        # Impacto: só cria/atualiza 2 docs por lead (merge=True).
        # ==========================================================
        try:
            _wa_key = str(locals().get("wa_key") or locals().get("waKey") or "").strip()
            _from_e164 = str(locals().get("from_e164") or locals().get("fromE164") or "").strip()
            _disp = str(locals().get("display_name") or locals().get("displayName") or "").strip()
            _msg_type = str(

                locals().get("msg_type")

                or locals().get("msgType")

                or locals().get("messageType")

                or ""

            ).strip().lower()
            _route_hint = str(locals().get("route_hint") or locals().get("route") or "").strip().lower()


            

            # chave canônica do lead: SEMPRE digits-only (docId do institutional_leads)

            _wa_key_digits = _digits_only(_wa_key or _from_e164)

            if _wa_key_digits:

                _wa_key = _wa_key_digits

            

            # fallback de msg_type quando vier vazio (ex.: testes locais)

            if not _msg_type:

                _text_probe = str(locals().get("text_in") or locals().get("text") or locals().get("user_text") or "").strip()

                if _text_probe:

                    _msg_type = "text"
            # Só para VENDAS/LEAD (sem UID). Se você tiver um boolean explícito, use ele aqui.
            # Heurística segura: route_hint contém "sales" e tem wa_key.
            if _wa_key and ("sales" in _route_hint):
                leads_coll = os.getenv("INSTITUTIONAL_LEADS_COLL", "institutional_leads")
                prof_coll = os.getenv("PLATFORM_LEAD_PROFILES_COLL", "platform_lead_profiles")

                # ==========================================================
                # Lookup rápido do lead para hints (segmento / nome)
                # Não altera fluxo atual — apenas lê se existir
                # ==========================================================
                segment_hint = ""
                name_hint = ""
                try:
                    lead_doc = _db().collection(leads_coll).document(_wa_key).get()
                    if lead_doc.exists:
                        data = lead_doc.to_dict() or {}
                        segment_hint = str(data.get("segment") or "").strip()
                        name_hint = str(data.get("name") or data.get("displayName") or "").strip()
                except Exception:
                    pass


                base = {
                    "waKey": _wa_key,
                    "from": _from_e164,
                    "lastSeenAt": _fs_admin().SERVER_TIMESTAMP,
                    "lastMsgType": _msg_type,
                    "lastEventKey": str(event_key or "")[:500],
                }

                if segment_hint:
                    base["segment_hint"] = segment_hint

                if name_hint:
                    base["name_hint"] = name_hint

                if _disp:
                    base["displayName"] = _disp

                # lead canônico
                _db().collection(leads_coll).document(_wa_key).set(
                    {**base, "msgCount": _fs_admin().Increment(1)},
                    merge=True,
                )

                # perfil (afinidade/marketing)
                _db().collection(prof_coll).document(_wa_key).set(
                    {**base, "msgCount": _fs_admin().Increment(1)},
                    merge=True,
                )
        except Exception:
            logger.exception("[tasks] lead_profile_touch_failed waKey=%s", str(locals().get("wa_key") or "")[:40])


        # SENTINELA: daqui pra frente deveria entrar no outbound (ou cair em algum return/guard)
        try:
            logger.info(
                "[tasks] after_compute route_hint=%s uid=%s msg_type=%s reply_empty=%s",
                str(route_hint), ("yes" if uid else "no"), str(msg_type), (not (reply_text or "").strip())
            )
        except Exception:
            logger.info("[tasks] after_compute (no details)")

        # ==========================================================
        # TEXTO PRIMÁRIO DO FRONT
        # - Se a resposta já veio do conversational_front e a entrada é texto,
        #   envia aqui e sai, sem depender do fellthrough.
        # - Não mexe na trilha de áudio.
        # ==========================================================
        try:
            _route_hint_now = str(route_hint or "").strip().lower()
            _reply_now = (reply_text or "").strip()
            _is_text_in = msg_type in ("text", "chat", "")
            _came_from_front = _route_hint_now in ("conversational_front", "front")

            if (not sent_ok) and _is_text_in and _came_from_front and _reply_now:
                try:
                    _st = send_text
                    if not _st:
                        try:
                            from providers.ycloud import send_text as _send_text  # type: ignore
                            _st = _send_text
                            send_text = _st
                        except Exception:
                            logger.exception("[tasks] ycloud_provider_import_failed (front_text_primary)")
                            _st = None

                    if _st:
                        _rt_front = _clean_url_weirdness(_reply_now)
                        logger.info("[outbound] send_text (front_text_primary) to=%s chars=%d", from_e164, len(_rt_front))
                        _ok_front, _ = _st(from_e164, _rt_front)
                        try:
                            _wa_log_outbox_deterministic(
                                route="send_text_front_primary",
                                to_e164=from_e164,
                                reply_text=_rt_front,
                                sent_ok=bool(_ok_front),
                            )
                        except Exception:
                            pass
                        sent_ok = sent_ok or bool(_ok_front)
                        if _ok_front:
                            try:
                                _try_log_outbox_immediate(True, "send_text_front_primary")
                            except Exception:
                                pass
                            logger.info("[tasks] end eventKey=%s wamid=%s sent_ok=%s", event_key, _wamid, bool(sent_ok))
                            return jsonify({"ok": True, "sent": bool(sent_ok)}), 200
                except Exception:
                    logger.exception("[tasks] front_text_primary_failed")
        except Exception:
            pass

        # Se entrou por áudio: por padrão não preferir texto.
        # EXCEÇÃO: se o wa_bot pediu prefersText (ex.: para mandar link por escrito), respeitar.
        if msg_type in ("audio", "voice", "ptt") and (not prefers_text):
            prefers_text = False  # mantém o default; (na prática, não muda nada)

        # Não sobrescrever resposta do wa_bot com "texto pronto".
        # Fallback mínimo só quando for lead/VENDAS (uid ausente).
        reply_text = (reply_text or "").strip()[:1200]
        if not reply_text:
            if not uid:
                logger.warning(
                    '[tasks] route=tasks_empty_reply reason=empty_reply from=%s to=%s wamid=%s eventKey=%s',
                    from_e164, to_e164, wamid, event_key
                )
                reply_text = "Não consegui entender direitinho 🙂 Você quer: conhecer a plataforma, ver preços/planos, ou falar de um uso no seu negócio?"
            else:
                logger.warning(
                    "[tasks] customer_empty_reply from=%s wamid=%s",
                    from_e164, wamid
                )
                reply_text = "Não consegui responder agora 😕 Pode tentar de novo ou me explicar um pouco melhor?"

        # Se entrou por áudio, evitamos "paredão" como fallback de texto.
        # (O áudio é o canal principal; texto aqui é só fallback se o áudio falhar.)
        if msg_type in ("audio", "voice", "ptt"):
            try:
                if reply_text and len(reply_text) > _SUPPORT_WA_TEXT_MAX_CHARS:
                    before = reply_text
                    reply_text = _shorten_for_whatsapp(reply_text, _SUPPORT_WA_TEXT_MAX_CHARS)
                    audio_debug = dict(audio_debug or {})
                    audio_debug["waTextShorten"] = {
                        "applied": True,
                        "maxChars": _SUPPORT_WA_TEXT_MAX_CHARS,
                        "beforeLen": len(before),
                        "afterLen": len(reply_text),                     }
            except Exception:
                pass

            # ==========================================================
            # Guardrail (customer): suporte NÃO pede CNPJ.
            # Se algum caminho legado tentar validar identidade, trocamos
            # por um pedido humano de "como te chamo" (sem números).
            # ==========================================================
            def _looks_like_cnpj_request(s: str) -> bool:
                t = (s or "").strip().lower()
                if "cnpj" not in t:
                    return False
                # padrões comuns do texto problemático
                bad = (
                    "me informar seu cnpj",
                    "me informar o cnpj",
                    "poderia me informar seu cnpj",
                    "poderia me informar o cnpj",
                    "preciso confirmar",
                    "confirmar se você é",
                )
                return any(k in t for k in bad)

            if uid and _looks_like_cnpj_request(reply_text):
                # mantém humanização (nome do MEI é ok), mas sem pedir CNPJ
                reply_text = (
                    "Entendi 🙂 Eu não preciso do teu CNPJ pra te ajudar aqui. "
                    "Só pra eu te chamar certinho: você é o Edson mesmo ou é outra pessoa falando por este WhatsApp?"
                )
                audio_debug = dict(audio_debug or {})
                audio_debug["identity_guard"] = {"applied": True, "reason": "removed_cnpj_request_for_customer"}


            # Aplica override de nome (se existir) para manter consistência na conversa
            try:
                override = ""
                try:
                    # 1) Preferir interlocutor ativo (premium)
                    if _IDENTITY_MODE != "off" and wa_key_effective:
                        override = _get_active_speaker(wa_key_effective) or ""

                    # 2) Fallback: override legado (compat)
                    if wa_key_effective:
                        override = override or _get_name_override(wa_key_effective)

                    # Probe só para debug (não decide comportamento)
                    if wa_key_effective:
                        db_read = _db_admin() or _db()
                        snap = db_read.collection("platform_name_overrides").document(wa_key_effective).get()
                        data = snap.to_dict() or {}
                        name_probe = str(data.get("name") or "").strip()
                        exp = float(data.get("expiresAt") or 0.0)
                        audio_debug = dict(audio_debug or {})
                        audio_debug["nameOverrideProbe_get"] = {
                            "waKey": wa_key_effective,
                            "docExists": bool(snap.exists),
                            "name": name_probe,
                            "expiresAt": exp,
                            "now": time.time(),
                            "path": f"platform_name_overrides/{wa_key_effective}",
                        }

                        # speaker state probe
                        try:
                            sp = _speaker_db().collection(_SPEAKER_COLL).document(wa_key_effective).get()
                            spd = sp.to_dict() or {}
                            speaker_state = dict(spd or {})
                            # compat p/ gate local do nome
                            try:
                                speaker_state["last_name_used_at"] = float(speaker_state.get("lastNameUsedAtEpoch") or speaker_state.get("last_name_used_at") or 0.0)
                            except Exception:
                                pass
                            audio_debug["speakerStateProbe_get"] = {
                                "waKey": wa_key_effective,
                                "docExists": bool(sp.exists),
                                "displayName": str(spd.get("displayName") or "").strip(),
                                "expiresAt": float(spd.get("expiresAt") or 0.0),
                                "source": str(spd.get("source") or "").strip(),
                                "confidence": float(spd.get("confidence") or 0.0),
                                "now": time.time(),
                                "path": f"{_SPEAKER_COLL}/{wa_key_effective}",
                            }
                        except Exception:
                            pass
                        if exp and time.time() > exp:
                            override = ""
                except Exception as e:
                    audio_debug = dict(audio_debug or {})
                    audio_debug["nameOverrideProbe_get_err"] = str(e)[:120]
                    override = ""


                # ==========================================================
                # Name override (produto): APENAS para display_name / contexto
                # - NÃO modificar reply_text aqui.
                # - Uso do nome é decidido pela IA (name_use) + gate no áudio.
                # ==========================================================
                try:
                    if override:
                        nm = str(override).strip()
                        if nm:
                            display_name = nm
                except Exception:
                    pass


                # fallback final: se ainda não temos display_name, tenta speakerState diretamente
                try:
                    if not (display_name or "").strip() and wa_key_effective:
                        display_name = (_get_active_speaker(wa_key_effective) or "").strip()
                except Exception:
                    pass

                    # 🔥 CRÍTICO: se já tinha áudio pronto (ex.: vindo do wa_bot),
                    # mas o texto mudou por override, invalida áudio pra regenerar com o nome certo.
                    if audio_url and reply_text != reply_text_before_override:
                        audio_debug["ttsRegen"] = {"forced": True, "reason": "name_override_changed_text"}
                        audio_url = ""
            except Exception:
                pass

            # ==========================================================
            # Se o usuário pediu "somente texto", respeita.
            # Pacote 2: se o lead FECHOU por áudio ("assinar/procedimento"), também entra no modo
            # ACK em áudio + texto com link, mesmo quando prefersText=false.
            close_heur_global = False
            try:
                # IA-first: se o cérebro já sinalizou fechamento/CTA, não dependa de transcript.
                try:
                    _u = understanding if isinstance(understanding, dict) else {}
                    _u_int = str(_u.get("intent") or "").strip().upper()
                    _u_ns = str(_u.get("next_step") or "").strip().upper()
                    if (_u_int in ("CLOSE", "ACTIVATE")) or (_u_ns in ("SEND_LINK", "CTA", "EXIT")):
                        close_heur_global = True
                except Exception:
                    pass

                if msg_type in ("audio", "voice", "ptt"):
                    _trg = str(transcript or "").strip().lower()
                    if _trg:
                        close_words_g = (
                            "assinar", "assinatura", "contratar", "contrato",
                            "ativar", "ativação", "procedimento", "como assino",
                            "quero assinar", "quero contratar", "pode me enviar o procedimento",
                        )
                        close_heur_global = any(w in _trg for w in close_words_g)
            except Exception:
                close_heur_global = False

            if (prefers_text or close_heur_global) and msg_type in ("audio", "voice", "ptt", "text"):
                # PATCH: Se a entrada foi ÁUDIO e a resposta contém LINK/CTA,
                # não pode virar "text_only_requested".
                # Regra: manda 1 áudio curto (sem url) e depois manda o texto com o link.
                def _has_url_local(s: str) -> bool:
                    t = (s or "").lower()
                    return ("http://" in t) or ("https://" in t) or ("www." in t) or ("meirobo.com.br" in t)

                def _build_ack_audio(nm: str = "") -> str:
                    n = (nm or "").strip()
                    if n:
                        return (
                            f"Perfeito, {n}. Te mando o link por escrito agora e já fica tudo claro pra assinar. "
                            "Obrigado por chamar! — Ricardo, do MEI Robô."
                        )
                    return "Perfeito. Te mando o link por escrito agora e já fica tudo claro pra assinar. Obrigado por chamar! — Ricardo, do MEI Robô."

                audio_debug = dict(audio_debug or {})
                _rt = (reply_text or "").strip()

                # prefersText por link (não é "usuário pediu texto")
                # Só vira audio_plus_text_link quando o handler sinalizou FECHAMENTO/CTA (contrato).
                try:
                    _kind = str(wa_kind or "").strip().lower()
                    _ns = str(plan_next_step or "").strip().upper()
                    _intent = str(intent_final or "").strip().upper()
                    _pol = policies_applied if isinstance(policies_applied, list) else []
                    is_close_signal = (
                        (_kind == "sales_close")
                        or (_ns in ("SEND_LINK", "CTA", "EXIT"))
                        or (_intent == "ACTIVATE")
                        or ("hard_close:no_question" in _pol)
                        or ("policy:plan_send_link" in _pol)
                    )
                except Exception:
                    is_close_signal = False

                # Se fechou por áudio, força o close_signal (Pacote 2)
                is_close_signal = bool(is_close_signal or close_heur_global)


                # PILAR: entrou ÁUDIO -> sai ÁUDIO (exceto fechamento).
                # prefersText aqui é "tem link", não é "usuário pediu texto".
                # Então, se NÃO for fechamento, não pode bloquear o áudio.
                # EXCEÇÃO: SEND_LINK => texto com link é obrigatório (mesmo com áudio).
                if (msg_type in ("audio", "voice", "ptt")) and prefers_text and (not is_close_signal) and (not force_send_link_text):
                    prefers_text = False
                    try:
                        audio_debug = dict(audio_debug or {})
                        audio_debug["mode"] = "pillar_force_audio_non_close"
                    except Exception:
                        pass

                # Heurística mínima (Pacote 2): se o handler não marcou ACTIVATE,
                # mas o lead falou claramente "assinar/contratar/ativar/procedimento" em ÁUDIO,
                # tratamos como fechamento para manter: áudio (ACK) + texto (passos/link).
                close_heur = bool(close_heur_global)

                if close_heur:
                    is_close_signal = True

                # ==========================================================
                # Pacote 2 (regra explícita): "decisão de assinar" por ÁUDIO
                # => SEMPRE: 1 áudio curto de ACK + 1 texto com procedimento/link
                # Mesmo que prefersText=true. (prefersText aqui é "link por escrito", não "calar áudio")
                # ==========================================================
                if is_close_signal and (msg_type in ("audio", "voice", "ptt")):
                    try:
                        # garante que o texto tenha link copiável (sem "meirobo. com. br")
                        _rt_fix = _clean_url_weirdness(_rt)
                        if _rt_fix and ("meirobo.com.br" not in _rt_fix.lower()) and ("https://www.meirobo.com.br" not in _rt_fix.lower()):
                            _rt_fix = (_rt_fix.rstrip() + "\n\nhttps://www.meirobo.com.br").strip()
                            try:
                                audio_debug["policy"] = (audio_debug.get("policy") or []) + ["close_ack:forced_link_append"]
                            except Exception:
                                pass
                        reply_text = _rt_fix or reply_text
                        _rt = (reply_text or "").strip()
                    except Exception:
                        pass

                    # força modo "áudio + texto" no fechamento (mesmo que o reply não tenha url originalmente)
                    try:
                        audio_debug["mode"] = "audio_plus_text_link"
                        audio_debug["ack_source"] = "worker_ack"
                    except Exception:
                        pass

                    # Se não tem audio_url ainda, gera ACK institucional via /api/voz/tts e sobe Signed URL (padrão do worker)
                    if not audio_url:
                        try:
                            base = _backend_base(request)
                            tts_url = f"{base}/api/voz/tts"
                            voice_id = (os.environ.get("INSTITUTIONAL_VOICE_ID") or "").strip()
                            if voice_id:
                                nm = (display_name or "").strip()
                                ack = _build_ack_audio(nm)
                                tts_resp = requests.post(
                                    tts_url,
                                    headers={"Accept": "application/json"},
                                    json={"text": ack, "voice_id": voice_id, "format": "mp3"},
                                    timeout=35,
                                )
                                if not tts_resp.ok:
                                    audio_debug["ttsAck"] = {"ok": False, "reason": f"tts_http_{tts_resp.status_code}"}
                                    audio_url = ""
                                else:
                                    b = tts_resp.content or b""
                                    audio_url = _upload_audio_bytes_to_signed_url(b=b, audio_debug=audio_debug, tag="ttsAck", ext="mp3", content_type="audio/mpeg")
                            else:
                                try:
                                    audio_debug["ttsAck"] = {"ok": False, "reason": "missing_INSTITUTIONAL_VOICE_ID"}
                                except Exception:
                                    pass
                        except Exception as e:
                            try:
                                audio_debug["ttsAck"] = {"ok": False, "reason": f"{type(e).__name__}:{str(e)[:120]}"}
                            except Exception:
                                pass

                    # se gerou áudio, o outbound vai mandar áudio e depois texto (audio_plus_text_link)
                    # (não cair no "text_only_requested")
                if (msg_type in ("audio", "voice", "ptt", "text")) and _rt and _has_url_local(_rt) and is_close_signal and (os.environ.get("YCLOUD_CLOSE_ACK_FOR_TEXT", "1") not in ("0", "false", "False") or msg_type in ("audio", "voice", "ptt")):
                    audio_debug["mode"] = "audio_plus_text_link"

                    # A2: marca ACK do worker (fechamento)
                    # Não sobrescreve audio_debug["source"] (isso vem do handler).
                    if isinstance(audio_debug, dict):
                        audio_debug["ack_source"] = "worker_ack"

                    # gera áudio curto institucional (sem url) para manter "entra áudio -> sai áudio"
                    if not audio_url:
                        try:
                            base = _backend_base(request)
                            tts_url = f"{base}/api/voz/tts"
                            voice_id = (os.environ.get("INSTITUTIONAL_VOICE_ID") or "").strip()
                            if voice_id:
                                nm = (display_name or "").strip()
                                # tenta aproveitar override/premium speaker se existir
                                try:
                                    if not nm and wa_key_effective and _IDENTITY_MODE != "off":
                                        nm = _get_active_speaker(wa_key_effective) or ""
                                except Exception:
                                    nm = nm
                                ack = _build_ack_audio(nm)
                                tts_resp = requests.post(
                                    tts_url,
                                    headers={"Accept": "application/json"},
                                    json={"text": ack, "voice_id": voice_id, "format": "mp3"},
                                    timeout=35,
                                )

                                # (ACK) /api/voz/tts retorna MP3 bytes; sobe pro storage e gera Signed URL (mesmo padrão do worker)
                                try:
                                    if not tts_resp.ok:
                                        audio_debug["ttsAck"] = {"ok": False, "reason": f"tts_http_{tts_resp.status_code}"}
                                        audio_url = ""
                                    else:
                                        b = tts_resp.content or b""
                                        audio_url = _upload_audio_bytes_to_signed_url(b=b, audio_debug=audio_debug, tag="ttsAck", ext="mp3", content_type="audio/mpeg")
                                except Exception as e:
                                    audio_debug["ttsAck"] = {"ok": False, "reason": f"tts_exception:{type(e).__name__}:{str(e)[:120]}"}
                                    audio_url = ""
                            else:
                                audio_debug["ttsAck"] = {"ok": False, "reason": "missing_INSTITUTIONAL_VOICE_ID"}
                        except Exception as e:
                            audio_debug["ttsAck"] = {"ok": False, "reason": f"exc:{type(e).__name__}"}

                elif prefers_text:
                    # Caso geral: realmente só texto (ex.: usuário pediu explicitamente texto)
                    audio_debug["mode"] = "text_only_requested"
                    audio_url = ""  # garante que não envia áudio


            # Defaults (evita UnboundLocalError em logs)
            name_to_use = ""
            nome_a_usar = ""
    # ==========================================================
            # TTS automático (universal): se entrou por áudio, deve sair por áudio.
            # Se o wa_bot não devolveu audioUrl, geramos via /api/voz/tts.
            #
            # - customer (uid): usa vozClonada.voiceId se existir
            # - sales (uid vazio): usa INSTITUTIONAL_VOICE_ID (ENV) se existir
            # ==========================================================
            if msg_type in ("audio", "voice", "ptt") and (not audio_url) and reply_text and (not prefers_text):
                try:
                    base = _backend_base(request)
                    tts_url = f"{base}/api/voz/tts"

                    voice_id = ""
                    if uid:
                        # voz do próprio MEI (se existir)
                        try:
                            prof = _db().collection("profissionais").document(uid).get()
                            prof_data = prof.to_dict() or {}
                            vc = prof_data.get("vozClonada") or {}
                            voice_id = (vc.get("voiceId") or "").strip()
                        except Exception:
                            voice_id = ""

                    # Fallback universal: se entrou por áudio e não há voiceId do MEI, usa voz institucional
                    if not voice_id:
                        voice_id = (os.environ.get("INSTITUTIONAL_VOICE_ID") or "").strip()
                        if uid and voice_id:
                            audio_debug = dict(audio_debug or {})
                            audio_debug["ttsVoiceFallback"] = "institutional_for_customer_no_voiceId"

                    # se não há voice_id, não forçamos TTS (cai para texto, nunca mudo)
                    if voice_id:

                        # 🔥 TTS: separa SUPORTE vs VENDAS
                        # - SUPORTE: mantém teu pipeline atual (persona support + concept + rewrite)
                        # - VENDAS (uid vazio): fala curta com micro-exemplo + tom vendedor humano (IA)
                        tts_text = reply_text
                        tts_script_source = "replyText"
                        try:
                            is_sales = not bool(uid)
                            support_persona = {}

                            if is_sales and _SALES_TTS_MODE == "on":
                                # 🔒 Regra de ouro (VENDAS/uid vazio): o worker NÃO inventa texto.
                                preserve_sales_surface = _keep_sales_surface_from_bot(
                                    wa_out=wa_out if isinstance(wa_out, dict) else {},
                                    uid=uid,
                                )

                                if tts_text_from_bot:
                                    tts_text = tts_text_from_bot
                                    tts_script_source = (tts_text_from_bot_source or "from_bot")
                                    audio_debug = dict(audio_debug or {})
                                    audio_debug["ttsSales"] = {
                                        "ok": True,
                                        "mode": "from_bot",
                                        "waKind": str(wa_kind or "").strip().lower(),
                                    }
                                elif preserve_sales_surface:
                                    tts_text = (spoken_text or reply_text or "").strip()
                                    tts_script_source = "preserved_surface"
                                    audio_debug = dict(audio_debug or {})
                                    audio_debug["ttsSales"] = {
                                        "ok": True,
                                        "mode": "preserved_surface",
                                        "waKind": str(wa_kind or "").strip().lower(),
                                    }
                                else:
                                    tts_text = reply_text
                                    tts_script_source = "replyText"
                                    audio_debug = dict(audio_debug or {})
                                    audio_debug["ttsSales"] = {
                                        "ok": True,
                                        "mode": "reply_text",
                                        "waKind": str(wa_kind or "").strip().lower(),
                                    }

                                # corta antes do TTS pra não estourar
                                if tts_text and len(tts_text) > _SALES_TTS_MAX_CHARS:
                                    before = tts_text
                                    tts_text = _shorten_for_speech(tts_text, _SALES_TTS_MAX_CHARS)
                                    audio_debug = dict(audio_debug or {})
                                    audio_debug["ttsInputShortenSales"] = {
                                        "applied": True,
                                        "maxChars": _SALES_TTS_MAX_CHARS,
                                        "beforeLen": len(before),
                                        "afterLen": len(tts_text),
                                    }
                            else:
                                support_persona = _get_support_persona()

                                # Resolve nome UMA vez, cedo, e reutiliza no TTS
                                tts_name = ""
                                if wa_key_effective:
                                    try:
                                        if _IDENTITY_MODE != "off":
                                            tts_name = _get_active_speaker(wa_key_effective) or ""
                                        if not tts_name:
                                            tts_name = _get_name_override(wa_key_effective) or ""
                                    except Exception:
                                        tts_name = ""

                                # Fallback robusto (se por algum motivo helpers falharem):
                                # aproveita o que já sabemos do pipeline (speaker/override).
                                try:
                                    if not tts_name:
                                        spg = (audio_debug or {}).get("speakerStateProbe_get") or {}
                                        tts_name = str(spg.get("displayName") or "").strip() or tts_name
                                    if not tts_name:
                                        nog = (audio_debug or {}).get("nameOverrideProbe_get") or {}
                                        tts_name = str(nog.get("name") or "").strip() or tts_name
                                except Exception:
                                    pass

                            # Regra de produto: nome só de vez em quando.
                            name_to_use = ""
                            name_used = ""  # para telemetria (ttsTextProbe.nameUsed)

                            try:
                                # IA sugere via name_use; nunca escreva nome no texto do bot.
                                _name_use = ""
                                try:
                                    if isinstance(understanding, dict):
                                        _name_use = str(understanding.get("name_use") or understanding.get("nameUse") or "").strip().lower()
                                except Exception:
                                    _name_use = ""
                                if not _name_use:
                                    try:
                                        _name_use = str(wa_out.get("nameUse") or "").strip().lower()
                                    except Exception:
                                        _name_use = ""

                                if is_sales:
                                    # VENDAS (lead/uid vazio): só usa nome se IA pediu e respeita gap específico.
                                    if tts_name and wa_key_effective and _name_use and _name_use != "none":
                                        try:
                                            gap = int(os.getenv("SALES_NAME_SPOKEN_MIN_GAP_SECONDS", "360") or "360")
                                        except Exception:
                                            gap = 360
                                        now = time.time()
                                        last = float(_LAST_SALES_NAME_SPOKEN_AT.get(wa_key_effective) or 0.0)
                                        if (now - last) >= float(gap):
                                            name_to_use = tts_name
                                            name_used = tts_name
                                            _LAST_SALES_NAME_SPOKEN_AT[wa_key_effective] = now
                                else:
                                    # SUPORTE/CLIENTE (uid presente): usa gap padrão do suporte.
                                    if tts_name and wa_key_effective:
                                        last = float(_LAST_NAME_SPOKEN_AT.get(wa_key_effective) or 0.0)
                                        if (time.time() - last) >= float(_SUPPORT_NAME_MIN_GAP_SECONDS):
                                            name_to_use = tts_name
                                            name_used = tts_name
                                            _LAST_NAME_SPOKEN_AT[wa_key_effective] = time.time()
                            except Exception:
                                pass

                            # 1) Se for conceitual e houver kbContext: gera fala humana a partir do CONTEXTO (não lê artigo)
                            concept_generated = False
                            try:
                                if _SUPPORT_TTS_CONCEPT_MODE == "on" and (not is_sales) and str(wa_kind or "").strip().lower() == "conceptual" and (kb_context or "").strip():
                                    # conceitual: não usa nome, nem saudação do modelo (isso vem do Firestore)
                                    gen = _openai_generate_concept_speech(text_in, kb_context, display_name="")
                                    if gen:
                                        tts_text = gen
                                        concept_generated = True
                                        audio_debug = dict(audio_debug or {})
                                        audio_debug["ttsConcept"] = {"ok": True, "model": _SUPPORT_TTS_CONCEPT_MODEL}
                                    else:
                                        audio_debug = dict(audio_debug or {})
                                        audio_debug["ttsConcept"] = {"ok": False}
                            except Exception:
                                pass

                            # 2) Sempre expande unidades para TTS (antes de qualquer rewrite)
                            tts_text = _expand_units_for_speech(tts_text)

                            # 3) Saudação via Firestore (spice) com cadência (se permitido)
                            is_informal = True  # inbound áudio no WhatsApp: assume informal
                            greet = _pick_support_greeting(support_persona, wa_key_effective, tts_name, is_informal) if (not is_sales) else ""
                            used_spice = bool(greet)

                            if greet:
                                tts_text = f"{greet} {tts_text}".strip()
                                name_to_use_for_make = ""
                            else:
                                name_to_use_for_make = name_to_use

                            # 4) texto falável base (limpo + nome opcional, mas sem duplicar se teve spice)
                            if concept_generated:
                                tts_text = _clean_for_tts(tts_text)
                            else:
                                _route_hint = (wa_out.get("route") or wa_out.get("replySource") or wa_out.get("route_hint") or wa_out.get("replySource") or "").strip().lower()
                                _is_front = _route_hint in ("front", "conversational_front", "conversationalfront")
                                tts_text = _make_tts_text(tts_text, name_to_use_for_make, add_acervo_cta=(not _is_front))
                            # 5) IA reescreve para fala humana (agora com persona do Firestore)
                            if _SUPPORT_TTS_SUMMARY_MODE == "on" and (not is_sales):
                                rewritten = _openai_rewrite_for_speech(tts_text, name_to_use_for_make)
                                if rewritten:
                                    tts_text = rewritten
                                    # --- Dedup nome (evita "Edson, Fala, Edson!") ---
                                    try:
                                        # nome real do interlocutor (não o "permitido" pra make_tts_text)
                                        _nm = (tts_name or "").strip()
                                        if _nm:
                                            # se o texto começa com "Nome, ..." e também contém "..., Nome!" logo no começo,
                                            # remove o prefixo "Nome, " (mantém o greeting com nome).
                                            low = (tts_text or "").lower()
                                            nm_low = _nm.lower()
                                            if low.startswith(nm_low + ",") and (nm_low + "!") in low[:60]:
                                                tts_text = (tts_text or "")[len(_nm) + 1 :].lstrip()  # remove "Nome,"
                                    except Exception:
                                        pass
                                    audio_debug = dict(audio_debug or {})
                                    audio_debug["ttsRewrite"] = {"ok": True, "model": _SUPPORT_TTS_SUMMARY_MODEL}
                                else:
                                    audio_debug = dict(audio_debug or {})
                                    audio_debug["ttsRewrite"] = {"ok": False}

                            # 6) Expande unidades DE NOVO (rewrite pode reintroduzir MB/GB)
                            tts_text = _expand_units_for_speech(tts_text)

                            # Garantia final: se liberamos nome, ele não pode sumir no rewrite
                            # (mas se já teve greeting do Firestore, não re-injeta nome aqui)
                            try:
                                if name_to_use_for_make and (not used_spice):
                                    low = (tts_text or "").lstrip().lower()
                                    if not low.startswith((name_to_use_for_make.lower() + ",", name_to_use_for_make.lower() + " ")):
                                        tts_text = f"{name_to_use_for_make}, {tts_text}".strip()
                            except Exception:
                                pass

                        except Exception:
                            pass
    # Auditoria segura: prova do texto enviado ao TTS sem entupir logs
                            try:
                                sha = _sha1_id(tts_text)
                                head = (tts_text or "")[:80]
                                tail = (tts_text or "")[-80:] if tts_text else ""
                                audio_debug = dict(audio_debug or {})
                                audio_debug["ttsPayload"] = {"sha1": sha, "len": len(tts_text or ""), "head": head, "tail": tail}
                            except Exception:
                                pass

                            # Probe ANTES do corte (para debug)
                            # - Firestore-first: tenta wa_out top-level; fallback para wa_out.aiMeta; e por último understanding
                            _wo = wa_out if isinstance(wa_out, dict) else {}
                            _am = {}
                            try:
                                if isinstance(_wo.get("aiMeta"), dict):
                                    _am = _wo.get("aiMeta") or {}
                            except Exception:
                                _am = {}
                            def _meta_get(key: str, default=None):
                                try:
                                    v = _wo.get(key, None) if isinstance(_wo, dict) else None
                                    if (v is None or v == "" or v == []):
                                        v = _am.get(key, None) if isinstance(_am, dict) else None
                                    # fallback mínimo para iaSource via understanding (quando wa_out não trouxer)
                                    if (v is None or v == "") and key == "iaSource":
                                        try:
                                            if isinstance(understanding, dict):
                                                v = understanding.get("source") or understanding.get("iaSource")
                                        except Exception:
                                            pass
                                    return default if v is None else v
                                except Exception:
                                    return default
                            audio_debug = dict(audio_debug or {})
                            audio_debug["ttsTextProbe"] = {
                                "nameUsed": (locals().get("name_used") or locals().get("name_to_use") or ""),
                                "len": len(tts_text or ""),
                                "preview": (tts_text or "")[:140],
                                "ttsScriptSource": str(locals().get("tts_script_source") or ""),
                                # Como estamos entregando (ajuda a auditar "áudio vs texto")
                                "deliveryMode": ("audio_plus_text_link" if bool(locals().get("force_send_link_text")) else "audio_only"),
                                # Firestore-first: espelha metadados do wa_out (quando existir)
                                "aiMeta": {
                                    "kbUsed": bool(_meta_get("kbUsed", False)),
                                    "kbContractId": str(_meta_get("kbContractId", "") or "")[:80],
                                    "kbMissReason": str(_meta_get("kbMissReason", "") or "")[:80],
                                    "kbRequiredOk": bool(_meta_get("kbRequiredOk", False)),
                                    "kbDocPath": str(_meta_get("kbDocPath", "") or "")[:160],
                                    "kbSliceFields": (list(_meta_get("kbSliceFields", []) or [])[:20]),
                                    "kbSliceSizeChars": int(_meta_get("kbSliceSizeChars", 0) or 0),
                                    "kbMissingFields": (list(_meta_get("kbMissingFields", []) or [])[:20]),
                                    "iaSource": str(_meta_get("iaSource", "") or "")[:80],
                                    "replyTextRole": str(_meta_get("replyTextRole", "") or "")[:40],
                                    "spokenTextRole": str(_meta_get("spokenTextRole", "") or "")[:40],
                                    "kbExampleUsed": str(_meta_get("kbExampleUsed", "") or "")[:120],
                                    "spokenSource": str(_meta_get("spokenSource", "") or "")[:60],
                                    "funnelMoment": str(_meta_get("funnelMoment", "") or "")[:40],
                                },
                            }
                            # ==========================================================
                            # TTS cut policy (VENDAS): permitir áudio mais longo só em operacional
                            # - Mantém o resto igual
                            # - Evita cortar explicação no meio
                            # ==========================================================
                            _tts_max = _SUPPORT_TTS_MAX_CHARS
                            try:
                                _u = (understanding if isinstance(understanding, dict) else {}) or {}
                                _i = str(_u.get("intent") or "").strip().upper()
                                _d = str(_u.get("depth") or "").strip().lower()
                                # Só para VENDAS + intent operacional
                                if str(route_hint or "").strip().lower() in ("sales", "sales_lead") and _i in ("AGENDA", "OPERATIONAL", "PROCESS"):
                                    # Default operacional
                                    _tts_max = int(os.getenv("SALES_TTS_MAX_CHARS_OPERATIONAL", str(_SUPPORT_TTS_MAX_CHARS)) or str(_SUPPORT_TTS_MAX_CHARS))
                                    # Se IA marcou deep, libera um pouco mais
                                    if _d == "deep":
                                        _tts_max = int(os.getenv("SALES_TTS_MAX_CHARS_OPERATIONAL_DEEP", str(_tts_max)) or str(_tts_max))
                            except Exception:
                                _tts_max = _SUPPORT_TTS_MAX_CHARS

                            # Corte para evitar 413 (usa política acima)
                            if tts_text and len(tts_text) > _tts_max:
                                before = tts_text
                                tts_text = _shorten_for_speech(tts_text, _tts_max)
                                audio_debug = dict(audio_debug or {})
                                audio_debug["ttsInputShorten"] = {
                                    "applied": True,
                                    "maxChars": _tts_max,
                                    "beforeLen": len(before),
                                    "afterLen": len(tts_text),
                                }
                            # Probe FINAL (texto REAL falado)
                            audio_debug = dict(audio_debug or {})
                            audio_debug["ttsTextFinal"] = {
                                "len": len(tts_text or ""),
                                "preview": (tts_text or "")[:140],
                            }
                        except Exception:
                            pass

                        def _call_tts(payload_text: str):
                            return requests.post(
                                tts_url,
                                headers={"Accept": "application/json"},
                                json={"text": payload_text, "voice_id": voice_id},
                                timeout=35,
                            )

                        # ✅ Texto canônico falado (o que realmente vai pro TTS)

                        # 🔒 Blindagem final: nunca começar com "Fala!"
                        tts_text = re.sub(r"^(fala+[\s,!\.\-–—]*)", "", (tts_text or "").strip(), flags=re.IGNORECASE).strip() or "Oi 🙂"
                        
                        # ----------------------------------------------------------
                        # UX: nome no ÁUDIO deve ser aplicado APENAS pelo gate de VENDAS abaixo
                        # (evita prefixo duplo e mantém cadência consistente)

                        # UX (VENDAS): aplicar nome no ÁUDIO quando a IA sinaliza via wa_out.nameUse, com gate de cadência (mesmo sem uid)
                        try:
                            tts_text_base = str(tts_text or "")
                            _under = (understanding if isinstance(understanding, dict) else {})
                            _name_use_signal = str((wa_out or {}).get("nameUse") or _under.get("name_use") or "none").strip().lower()
                            _contact_name = (
                                str((wa_out or {}).get("leadName") or (wa_out or {}).get("displayName") or (display_name or "")).strip()
                                or str((speaker_state or {}).get("displayName") or "").strip()
                            ) or None

                            # Se a pessoa acabou de se identificar (triggered), usamos o nome 1x (empatia).
                            # Mantém IA soberana no geral; isso é só um “cumprimento humano” pós-identificação.
                            try:
                                speakerAI = (audio_debug or {}).get("speakerAI") if isinstance(audio_debug, dict) else {}
                                if (_name_use_signal in ("", "none")) and bool((speakerAI or {}).get("triggered")) and _contact_name:
                                    _name_use_signal = "greet"
                            except Exception:
                                pass
                            tts_text, name_used = _maybe_apply_name_to_tts(
                                text=tts_text_base,
                                name_use=_name_use_signal,
                                contact_name=_contact_name,
                                speaker_state=speaker_state,
                                now_ts=time.time(),
                                min_gap_seconds=int(_SALES_NAME_MIN_GAP_SECONDS or 120),
                            )
                            try:
                                if isinstance(ttsTextProbe, dict):
                                    ttsTextProbe["nameUsed"] = bool(name_used)
                                    ttsTextProbe["nameUse"] = str(_name_use_signal or "none")
                                    ttsTextProbe["leadName"] = str(_contact_name or "")
                            except Exception:
                                pass
                        except Exception:
                            pass

                        # ==========================================================
                        # LIMPEZA FINAL (OBRIGATÓRIA) DO QUE VAI SER FALADO
                        # - garante "humanizado", mesmo se vier do spokenText do bot
                        # - remove links/domínios
                        # - evita ler "89,00" como "oitenta e nove ... zero zero"
                        # ==========================================================
                        try:
                            tts_text = _strip_links_for_audio(tts_text or "")
                            # dinheiro comum: "R$ 89,00" -> "89 reais"
                            tts_text = re.sub(r"R\$\s*([0-9]{1,7})[.,]00\b", r"\1 reais", tts_text)
                            # número com ,00 no final: "89,00" -> "89"
                            tts_text = re.sub(r"([0-9]{1,7})[.,]00\b", r"\1", tts_text)
                            # limpeza geral já existente (URLs quebradas, espaços, etc)
                            tts_text = _clean_for_speech(tts_text)
                        except Exception:
                            pass

                        tts_text_final_used = tts_text

                        rr = _call_tts(tts_text_final_used)

                        # Retry automático se bater 413 (texto ainda grande pro endpoint)
                        if rr.status_code == 413:
                            try:
                                retry_text = _shorten_for_speech(tts_text, _SUPPORT_TTS_RETRY_MAX_CHARS)
                                # ✅ Se precisou retry, o falado é o retry_text
                                tts_text_final_used = retry_text
                                audio_debug = dict(audio_debug or {})
                                audio_debug["ttsRetry"] = {
                                    "applied": True,
                                    "http": 413,
                                    "maxChars": _SUPPORT_TTS_RETRY_MAX_CHARS,
                                    "retryLen": len(retry_text),
                                }
                                rr = _call_tts(retry_text)
                            except Exception as e_retry:
                                audio_debug = dict(audio_debug or {})
                                audio_debug["ttsRetry"] = {"applied": False, "reason": f"exc:{type(e_retry).__name__}"}

                        if rr.status_code == 200:
                            # 1) Tentativa normal: JSON com audioUrl
                            try:
                                j = rr.json()
                                if isinstance(j, dict) and j.get("ok") is True and (j.get("audioUrl") or ""):
                                    audio_url = (j.get("audioUrl") or "").strip()
                                    audio_debug = dict(audio_debug or {})
                                    _ct = (rr.headers.get("content-type") or "").lower()[:40]

                                    _blen = int(len(rr.content or b"") or 0)

                                    audio_debug["tts"] = {"ok": True, "mode": "json_audioUrl", "ct": _ct, "bytes": _blen}
                                else:
                                    raise ValueError("json_missing_audioUrl")
                            except Exception:
                                # 2) Fallback premium: MP3 bytes (ex.: começa com ID3)
                                try:
                                    b = rr.content or b""
                                    head = b[:3]
                                    ct = (rr.headers.get("content-type") or "").lower()

                                    is_mp3 = (head == b"ID3") or ("audio" in ct) or b.startswith(b"\xff\xfb")
                                    if not is_mp3 or len(b) < 256:
                                        raise ValueError("not_mp3_bytes")

                                    bucket_name = (os.environ.get("STORAGE_BUCKET") or "").strip()
                                    if not bucket_name:
                                        raise ValueError("missing_STORAGE_BUCKET")

                                    # upload em um caminho estável (não conflita)
                                    now = datetime.datetime.utcnow()
                                    obj = f"sandbox/institutional_tts/{now:%Y/%m/%d}/{uuid.uuid4().hex}.mp3"

                                    # IMPORTANT: usar client com credencial que tenha private_key
                                    # (evita "you need a private key to sign credentials" no Cloud Run)
                                    try:
                                        from services.gcp_creds import get_storage_client as _get_storage_client
                                        client = _get_storage_client()
                                    except Exception as e_client:
                                        raise RuntimeError(
                                            f"storage_client_unavailable:{type(e_client).__name__}:{str(e_client)[:120]}"
                                        )
                                    bucket = client.bucket(bucket_name)
                                    blob = bucket.blob(obj)
                                    blob.upload_from_string(b, content_type="audio/mpeg")

                                    exp_s = int(os.environ.get("SIGNED_URL_EXPIRES_SECONDS", "900") or "900")
                                    audio_url = blob.generate_signed_url(
                                        version="v4",
                                        expiration=datetime.timedelta(seconds=exp_s),
                                        method="GET",
                                    )

                                    audio_debug = dict(audio_debug or {})
                                    audio_debug["tts"] = {"ok": True, "mode": "bytes_upload_signed", "bytes": len(b), "ct": ct[:40]}
                                except Exception as e2:
                                    # erro real: não conseguimos obter uma URL pra mandar ao WhatsApp
                                    audio_debug = dict(audio_debug or {})
                                    audio_debug["tts"] = {"ok": False, "reason": f"tts_bytes_fail:{type(e2).__name__}:{str(e2)[:80]}"}
                        else:
                            audio_debug = dict(audio_debug or {})
                            audio_debug["tts"] = {"ok": False, "reason": f"tts_http_{rr.status_code}"}
                    else:
                        audio_debug = dict(audio_debug or {})
                        audio_debug["tts"] = {"ok": False, "reason": "missing_voice_id"}

                except Exception as e:
                    logger.exception("[tasks] tts_failed uid=%s wamid=%s", uid, wamid)
                    audio_debug = dict(audio_debug or {})
                    audio_debug["tts"] = {"ok": False, "reason": f"tts_exc:{e}"}

            # ✅ Guarda SEMPRE o texto final que foi pro TTS (hash + preview)
            try:
                audio_debug = dict(audio_debug or {})
                audio_debug["ttsTextFinal"] = {
                    "len": len(tts_text_final_used or ""),
                    "preview": (tts_text_final_used or "")[:120],
                    "sha1": _sha1(tts_text_final_used),
                }
            except Exception:
                pass

            # envia resposta: se lead mandou áudio, tentamos áudio (se veio audioUrl), senão texto
            sent_ok = False
            did_send_audio = False
            allow_audio = os.environ.get("YCLOUD_TEXT_REPLY_AUDIO", "1") not in ("0", "false", "False")

            try:
                from providers.ycloud import send_text, send_audio  # type: ignore
            except Exception:
                send_text = None  # type: ignore
                send_audio = None  # type: ignore

            # OUTBOX_IMMEDIATE_PATCH_V1
            # Pacote 1 (robustez): grava outbox imediatamente após envio bem-sucedido.
            # Evita depender do "bloco final" e facilita auditoria em produção.
            def _try_log_outbox_immediate(_sent_ok: bool, _channel: str, _extra: dict = None) -> None:
                # Por padrão, DESLIGADO para evitar duplicar com o OUTBOX determinístico.
                # Se quiser reativar em incidentes: OUTBOX_IMMEDIATE=1
                if (os.environ.get("OUTBOX_IMMEDIATE") or "").strip().lower() not in ("1","true","yes","on"):
                    return
                try:
                    # A3: Se cair no modo ACK+texto, não pode perder displayName no outbox
                    try:
                        # tenta preservar nome mesmo quando o fluxo é "send_audio_ack_then_text"
                        _dn = (display_name or "").strip()
                        if not _dn and isinstance(audio_debug, dict):
                            _no = audio_debug.get("nameOverride") if isinstance(audio_debug.get("nameOverride"), dict) else {}
                            _dn = str((_no or {}).get("name") or "").strip()
                        # fallback final: override em escopo (já aplicado no bloco de override)
                        if isinstance(audio_debug, dict):
                            wom = audio_debug.get("waOutMeta") if isinstance(audio_debug.get("waOutMeta"), dict) else {}
                            wom = dict(wom or {})
                            if not str(wom.get("displayName") or "").strip():
                                if _dn:
                                    wom["displayName"] = _dn
                                elif (override or "").strip():
                                    wom["displayName"] = str(override).strip()
                            audio_debug["waOutMeta"] = wom
                    except Exception:
                        pass

                                        # docId determinístico pra auditoria (e evita duplicar por retry)
                    _doc_id = _sha1_id(event_key or wamid or str(time.time()))
                    payload_out = {
                        "createdAt": _fs_admin().SERVER_TIMESTAMP,
                        "from": from_e164,
                        "to": from_e164,
                        "wamid": wamid,
                        "msgType": msg_type,
                        "route": "sales" if not uid else "customer",
                        "replyText": (reply_text or "")[:4000],
                        "audioUrl": (audio_url or ""),
                        "eventKey": event_key,
                        "sentOk": bool(_sent_ok),
                        "sentVia": str(_channel or ""),
                    }
                    if _extra:
                        payload_out.update(_extra)
                    _db().collection("platform_wa_outbox_logs").document(_doc_id).set(payload_out, merge=True)
                    logger.info("[tasks] outbox_immediate ok=%s via=%s docId=%s wamid=%s eventKey=%s",
                                bool(_sent_ok), str(_channel or ""), _doc_id, wamid, event_key)
                except Exception:
                    logger.warning("[tasks] outbox_immediate_failed via=%s wamid=%s", str(_channel or ""), wamid, exc_info=True)

            def _clean_url_weirdness(s: str) -> str:
                t = (s or "").strip()
                if not t:
                    return t
                # cola "meirobo. com. br" -> "meirobo.com.br"
                t = t.replace("meirobo. com. br", "meirobo.com.br")
                # remove duplicação óbvia se vier 2x
                if t.count("meirobo.com.br") > 1:
                    first = t.find("meirobo.com.br")
                    while t.count("meirobo.com.br") > 1:
                        idx = t.rfind("meirobo.com.br")
                        if idx == first:
                            break
                        t = (t[:idx] + t[idx+len("meirobo.com.br"):]).strip()
                # garante https clicável
                if ("http://" not in t.lower()) and ("https://" not in t.lower()) and ("meirobo.com.br" in t.lower()):
                    t = t.replace("meirobo.com.br", "https://www.meirobo.com.br")
                return t

                        # PATCH B: se prefersText veio do handler e é FECHAMENTO com link => áudio curto + texto com link.
            # (o worker NÃO decide; só executa o contrato do handler)
            has_link = ("http://" in (reply_text or "").lower()) or ("https://" in (reply_text or "").lower()) or ("www." in (reply_text or "").lower()) or ("meirobo.com.br" in (reply_text or "").lower())
            is_close_signal = (
                str(wa_kind or "").strip().lower() == "sales_close"
                or plan_next_step in ("SEND_LINK", "CTA", "EXIT")
                or intent_final == "ACTIVATE"
                or ("hard_close:no_question" in [str(x) for x in (policies_applied or [])])
            )
            # Se o bloco anterior (prefers_text) já decidiu "audio_plus_text_link" e até gerou ttsAck/audioUrl,
            # o outbound NÃO pode rebaixar para "send_text_prefersText".
            decided_audio_plus_text = False
            try:
                _mode = ""
                if isinstance(audio_debug, dict):
                    _mode = str(audio_debug.get("mode") or "").strip().lower()
                decided_audio_plus_text = (_mode == "audio_plus_text_link")
            except Exception:
                decided_audio_plus_text = False
 
            # REGRA: se é audio_plus_text_link, o TEXTO é obrigatório (é o link).
            # Não depende de prefersText vindo do handler.
            if decided_audio_plus_text:
                prefers_text = True

            # ==========================================================
            # REGRA CANÔNICA — ACK obrigatório em áudio
            # audio_plus_text_link IGNORA prefersText
            # ==========================================================
            force_ack_audio = bool(decided_audio_plus_text)
            
            audio_plus_text_link = bool(
                decided_audio_plus_text
                or (
                    prefers_text
                    and (has_link or decided_audio_plus_text)
                    and (is_close_signal or decided_audio_plus_text)
                    and (
                        msg_type in ("audio", "voice", "ptt")
                        or (
                            msg_type == "text"
                            and os.environ.get(
                                "YCLOUD_CLOSE_ACK_FOR_TEXT", "1"
                            ) not in ("0", "false", "False")
                        )
                    )
                )
            )
            # PATCH: quando é link e veio por áudio, manda 1 áudio curto e depois o texto com link.
            if audio_plus_text_link and allow_audio and audio_url and send_audio and (not did_send_audio):
                try:
                    _ok2, _resp2 = send_audio(from_e164, audio_url)
                    sent_ok = sent_ok or bool(_ok2)
                    did_send_audio = did_send_audio or bool(_ok2)
                    # Observabilidade: guardar resposta do provider (sem vazar gigante)
                    try:
                        if isinstance(audio_debug, dict):
                            audio_debug["ttsAckSend"] = {
                                "ok": bool(_ok2),
                                "resp": (str(_resp2)[:500] if _resp2 is not None else ""),
                                "audioUrl": (audio_url[:160] if isinstance(audio_url, str) else ""),
                            }
                    except Exception:
                        pass
                except Exception:
                    logger.exception("[tasks] lead: falha send_audio (audio_plus_text_link)")

                try:
                    _try_log_outbox_immediate(True, "send_audio_ack_then_text")
                except Exception:
                    pass

                # texto com link (reply completo)
                if send_text:
                    try:
                        # Regra de UX: quando houver áudio, o texto é só ação (CTA) — nunca eco do áudio
                        _rt = "https://www.meirobo.com.br"
                        _ok3, _ = send_text(from_e164, _rt)
                        try:
                            _wa_log_outbox_deterministic(route="send_text_audio_plus_text_link", to_e164=from_e164, reply_text=(_rt or ""), sent_ok=bool(_ok3))
                        except Exception:
                            pass
                        sent_ok = sent_ok or _ok3
                    except Exception:
                        logger.exception("[tasks] lead: falha send_text (audio_plus_text_link)")

            # Regra operacional (Cloud Run/Tasks):
            # - Se inbound é TEXTO e temos reply_text, envia TEXTO sempre.
            #   (não depender de prefers_text; senão fica mudo quando prefers_text=False e não há áudio)
            if (not audio_plus_text_link) and (msg_type in ("text", "chat", "")) and send_text:
                try:
                    _rt2 = _clean_url_weirdness(reply_text)
                    if (_rt2 or "").strip():
                        logger.info("[outbound] send_text (inbound_text_default) to=%s chars=%d", from_e164, len(_rt2))
                        _okT, _ = send_text(from_e164, _rt2)
                        try:
                            _wa_log_outbox_deterministic(route="send_text_inbound_text_default", to_e164=from_e164, reply_text=(_rt2 or ""), sent_ok=bool(_okT))
                        except Exception:
                            pass
                        sent_ok = sent_ok or bool(_okT)
                        if _okT:
                            _try_log_outbox_immediate(True, "send_text_inbound_text_default")
                except Exception:
                    logger.exception("[tasks] lead: falha send_text (inbound_text_default)")

            # PATCH B: se prefersText (caso geral), manda texto primeiro.
            if (not force_ack_audio) and (not audio_plus_text_link) and prefers_text and send_text:
                try:
                    _rt2 = _clean_url_weirdness(reply_text)
                    logger.info("[outbound] send_text (prefersText) to=%s chars=%d", from_e164, len(_rt2 or ""))
                    _okP, _ = send_text(from_e164, _rt2)
                    try:
                        _wa_log_outbox_deterministic(route="send_text_prefersText", to_e164=from_e164, reply_text=(_rt2 or ""), sent_ok=bool(_okP))
                    except Exception:
                        pass
                    sent_ok = sent_ok or bool(_okP)
                    if _okP:
                        _try_log_outbox_immediate(True, "send_text_prefersText")
                except Exception:
                    logger.exception("[tasks] lead: falha send_text (prefersText)")
        # Caso normal: entrou por áudio e NÃO pediu prefersText → manda só áudio
        _allow_audio = locals().get("allow_audio", True)
        if (_allow_audio and msg_type in ("audio", "voice", "ptt") and audio_url and send_audio
            and (not prefers_text or force_ack_audio) and (not did_send_audio)):
            try:
                sent_ack_audio = False
                _ok2 = False
                if audio_url and send_audio:
                    try:
                        _ok2, _ = send_audio(from_e164, audio_url)
                        sent_ack_audio = bool(_ok2)
                    except Exception as e:
                        if isinstance(audio_debug, dict):
                            audio_debug["ttsAckSend"] = {
                                "ok": False,
                                "err": f"{type(e).__name__}:{str(e)[:140]}",
                                "audioUrl": (audio_url[:120] if isinstance(audio_url, str) else ""),
                            }
                if isinstance(audio_debug, dict) and sent_ack_audio:
                    audio_debug["ttsAckSend"] = {"ok": True}
                if sent_ack_audio:
                    sent_ok = sent_ok or bool(_ok2)
                    did_send_audio = did_send_audio or bool(_ok2)

                # ==========================================================
                # GUARD (produto): se era SEND_LINK, manda TEXTO com o link também
                # mesmo quando a trilha principal foi áudio.
                # ==========================================================
                try:
                    if force_send_link_text and send_text:
                        # Regra de UX: quando houver áudio, o texto é só CTA fixo (clicável)
                        _rtL = "https://www.meirobo.com.br"
                        if _rtL:
                            _okL, _ = send_text(from_e164, _rtL)
                            try:
                                _wa_log_outbox_deterministic(route="send_text_force_link", to_e164=from_e164, reply_text=(_rtL or ""), sent_ok=bool(_okL), extra={"ctaReason": "next_step_send_link"})
                            except Exception:
                                pass
                            sent_ok = sent_ok or bool(_okL)
                            try:
                                _try_log_outbox_immediate(True, "send_audio_then_text_send_link")
                            except Exception:
                                pass
                except Exception:
                    logger.exception("[tasks] lead: falha send_text (send_link_after_audio)")


                # --- CTA GATING (IA soberana) ---
                cta_reason = locals().get("cta_reason") or ""

                try:
                    ia_next_step = str((understanding or {}).get("next_step") or "").strip().upper()
                except Exception:
                    ia_next_step = ""

                # UX (produto): quando houver ÁUDIO em VENDAS, sempre mandar 1 CTA simples por TEXTO
                # (clicável) — mas com cadência, pra não virar spam.
                try:
                    if (
                        (not force_send_link_text)
                        and (not bool(uid))
                        and send_text
                        and bool(explicit_link_request)
                    ):
                        try:
                            gap_cta = int(os.getenv("SALES_SITE_CTA_MIN_GAP_SECONDS", "600") or "600")
                        except Exception:
                            gap_cta = 600
                        now = time.time()
                        last_cta = float(_LAST_SALES_SITE_CTA_AT.get(wa_key_effective) or 0.0)
                        if (now - last_cta) >= float(gap_cta):
                            _rtC = "https://www.meirobo.com.br"
                            _okC, _ = send_text(from_e164, _rtC)
                            try:
                                _wa_log_outbox_deterministic(route="send_text_site_cta", to_e164=from_e164, reply_text=(_rtC or ""), sent_ok=bool(_okC), extra={"ctaReason": "explicit_user_request"})
                            except Exception:
                                pass
                            sent_ok = sent_ok or bool(_okC)
                            _LAST_SALES_SITE_CTA_AT[wa_key_effective] = now
                except Exception:
                    pass
                # Telemetria: CTA bloqueado quando a IA não pediu SEND_LINK
                # (não cria log extra; apenas carimba no outbox principal deste evento)
                try:
                    if (not force_send_link_text) and (not bool(uid)) and send_text and (not bool(explicit_link_request)) and ia_next_step != "SEND_LINK":
                        # keep stable string for auditoria
                        if not (locals().get("cta_reason") or ""):
                            cta_reason = "cta_disabled_next_step_none"
                except Exception:
                    pass



                # Pacote 2 (regra): se foi "decisão de assinar" por ÁUDIO, manda TEXTO com link também,
                # mesmo quando prefersText=False (porque o lead precisa copiar o procedimento).
                try:
                    # Anti-duplicidade: se já é o modo "audio_plus_text_link",
                    # o texto será enviado no bloco dedicado (send_audio_ack_then_text).
                    _already_audio_plus_text = False
                    try:
                        _already_audio_plus_text = bool(audio_plus_text_link) or (
                            isinstance(audio_debug, dict) and str(audio_debug.get("mode") or "").strip() == "audio_plus_text_link"
                        )
                    except Exception:
                        _already_audio_plus_text = bool(audio_plus_text_link)

                    close_heur2 = False
                    if not _already_audio_plus_text:
                        _tr2 = str(transcript or "").strip().lower()
                        if _tr2 and msg_type in ("audio", "voice", "ptt"):
                            close_words2 = (
                                "assinar", "assinatura", "contratar", "contrato",
                                "ativar", "ativação", "procedimento", "como assino",
                                "quero assinar", "quero contratar", "pode me enviar o procedimento",
                            )
                            close_heur2 = any(w in _tr2 for w in close_words2)
                        if close_heur2 and send_text:
                            _rt = (reply_text or "").strip()
                            if _rt:
                                if ("http://" not in _rt.lower()) and ("https://" not in _rt.lower()):
                                    _rt = (

                                        _rt.replace("www.https://", "https://")

                                           .replace("www.http://", "http://")

                                           .replace("www.meirobo.com.br", "https://www.meirobo.com.br")

                                           .replace("meirobo.com.br", "https://www.meirobo.com.br")

                                    )
                                _okT2, _ = send_text(from_e164, _rt)
                                try:
                                    _wa_log_outbox_deterministic(route="send_text_close_after_audio", to_e164=from_e164, reply_text=(_rt or ""), sent_ok=bool(_okT2))
                                except Exception:
                                    pass
                                sent_ok = sent_ok or bool(_okT2)
                                try:
                                    _try_log_outbox_immediate(True, "send_audio_then_text_close")
                                except Exception:
                                    pass
                except Exception:
                    logger.exception("[tasks] lead: falha send_text (close_after_audio)")
            except Exception:
                logger.exception("[tasks] lead: falha send_audio")

            # Fallback: se nada foi, tenta texto
            if (not sent_ok) and send_text:
                try:
                    sent_ok, _ = send_text(from_e164, _clean_url_weirdness(reply_text))
                except Exception:
                    logger.exception("[tasks] lead: falha send_text")

            # ==========================================================
            # Meta final (observabilidade): garante displayName/source/plan no audioDebug
            # - NÃO altera comportamento de envio (só log/meta)
            # ==========================================================
            try:
                if isinstance(audio_debug, dict):
                    # 1) displayName (prioridade: override -> display_name -> leadName/nameToSay/displayName)
                    _ov = ""
                    try:
                        _no = audio_debug.get("nameOverride") if isinstance(audio_debug.get("nameOverride"), dict) else {}
                        _ov = str((_no or {}).get("name") or "").strip()
                    except Exception:
                        _ov = ""

                    _dn = (str(_ov or "").strip() or str(display_name or "").strip())
                    if (not _dn) and isinstance(wa_out, dict):
                        _dn = str(wa_out.get("leadName") or wa_out.get("nameToSay") or wa_out.get("displayName") or "").strip()
                    if _dn:
                        display_name = _dn

                    # 2) source (prioridade: _debug.source -> inferido por route_hint)
                    _src = ""
                    if isinstance(wa_out, dict):
                        dbg = wa_out.get("_debug")
                        if isinstance(dbg, dict):
                            _src = str(dbg.get("source") or "").strip()
                        if not _src:
                            try:
                                _u = wa_out.get("understanding")
                                if isinstance(_u, dict):
                                    _src = str(_u.get("source") or "").strip()
                            except Exception:
                                _src = ""
                    if not _src:
                        _src = "sales_lead" if str(route_hint or "").strip().lower() == "sales" else "wa_bot"

                    if (audio_debug.get("source") in (None, "", "unknown")):
                        audio_debug["source"] = _src

                    # 3) waOutMeta: atualizar/garantir campos finais
                    wom = audio_debug.get("waOutMeta") if isinstance(audio_debug.get("waOutMeta"), dict) else {}
                    wom = dict(wom or {})
                    wom["displayName"] = str(display_name or _dn or "").strip()[:40]
                    wom["source"] = str(audio_debug.get("source") or _src).strip()[:80]

                    # hasAudioUrl/audioUrl: garantir coerência com o áudio final gerado/enviado
                    try:
                        wom["hasAudioUrl"] = bool(str(audio_url or "").strip())
                        if str(audio_url or "").strip():
                            wom["audioUrl"] = str(audio_url).strip()[:300]
                    except Exception:
                        pass

                    # (opcional) planner/meta para acabar com achismo
                    if plan_next_step:
                        wom["planNextStep"] = str(plan_next_step)[:40]
                    if intent_final:
                        wom["intentFinal"] = str(intent_final)[:40]
                    if policies_applied:
                        try:
                            wom["policiesApplied"] = list(policies_applied)[:10]
                        except Exception:
                            wom["policiesApplied"] = str(policies_applied)[:200]
                    if wa_kind:
                        wom["kind"] = str(wa_kind)[:40]

                    audio_debug["waOutMeta"] = wom
            except Exception:
                pass

            # ==========================================================
            # Auditoria: alinhado com o que realmente foi falado (principalmente em VENDAS, onde usamos spokenText do bot)
            _wo = wa_out if isinstance(wa_out, dict) else {}
            _am = _wo.get("aiMeta") if isinstance(_wo.get("aiMeta"), dict) else {}
            def _a(key: str, default: str = "") -> str:
                v = ""
                try:
                    v = str(_wo.get(key) or "").strip()
                    if not v and isinstance(_am, dict):
                        v = str(_am.get(key) or "").strip()
                except Exception:
                    v = ""
                return v or default
            audio_debug = dict(audio_debug or {})
            audio_debug["auditAlignment"] = {
                "note": (
                    "Áudio veio da superfície entregue pelo bot em vendas."
                    if (is_sales and _SALES_TTS_MODE == "on" and _keep_sales_surface_from_bot(wa_out=wa_out if isinstance(wa_out, dict) else {}, uid=uid))
                    else "Áudio é versão otimizada para fala do replyText (ou do kbContext quando conceptual)."
                ),
                "spokenSource": _a("spokenSource", "replyText_pipeline"),
                "replyTextRole": _a("replyTextRole", ""),
                "spokenTextRole": _a("spokenTextRole", ""),
                "replyTextSha1": _sha1(reply_text),
                "spokenTextSha1": _sha1(tts_text_final_used),
            }
            # log leve (auditoria). Precisa ocorrer antes do return.
            try:
                # IA soberana: separa "decisão" de "forma de entrega".
                # - SEND_LINK pode ser uma ação decidida (não é fallback).
                # - Fallback só quando a fonte é realmente fallback/erro.
                try:
                    _ia_src = str(((understanding or {}).get("source") if isinstance(understanding, dict) else "") or "").strip()
                except Exception:
                    _ia_src = ""
                _ia_src_l = (_ia_src or "").strip().lower()
                _ia_sov = bool(_ia_src) and (not _ia_src_l.startswith("fallback_")) and (_ia_src_l not in ("worker_fallback_from_wa_out", "sales_lead_exception_fallback", "no_sender"))
                try:
                    _ia_next = str(((understanding or {}).get("next_step") if isinstance(understanding, dict) else "") or "").strip().upper()
                except Exception:
                    _ia_next = ""
                _db().collection("platform_wa_outbox_logs").add({
                    "createdAt": _fs_admin().SERVER_TIMESTAMP,
                    "from": from_e164,
                    "to": from_e164,
                    "wamid": wamid,
                    "msgType": msg_type,
                    "route": "sales" if not uid else "customer",
                    "replyText": (reply_text or "")[:400],
                    "audioUrl": (audio_url or "")[:300],
                    "audioDebug": audio_debug,
                    "understanding": understanding if isinstance(understanding, dict) else {},
                    "iaSource": (_ia_src or "")[:40],
                    "iaSovereign": bool(_ia_sov),
                    "fallbackReason": ((_ia_src or "")[:40] if not _ia_sov else ""),
                    "cta_reason": str(locals().get("cta_reason") or "")[:80],
                    "action": (_ia_next or "")[:40],
                    "deliveryMode": ("site_link" if (_ia_next == "SEND_LINK") else ""),
                    "spokenText": (tts_text_final_used or "")[:600],
                    "eventKey": event_key,
                    "sentOk": bool(sent_ok),
                })
            except Exception:
                logger.warning("[tasks] outbox_log_failed from=%s to=%s wamid=%s eventKey=%s", from_e164, to_e164, wamid, event_key, exc_info=True)

            # SENTINELA: prova que chegou no fim (independente de enviar)
            try:
                logger.info("[tasks] end eventKey=%s wamid=%s sent_ok=%s", event_key, _wamid, bool(sent_ok))
            except Exception:
                logger.info("[tasks] end eventKey=%s sent_ok=%s", event_key, bool(sent_ok))

            return jsonify({"ok": True, "sent": bool(sent_ok)}), 200
        # Fallback de segurança: se chegamos até aqui com reply_text e inbound é TEXTO,
        # não podemos ficar mudos. Tenta enviar texto best-effort.
        try:
            _rt_final = (reply_text or "").strip()
        except Exception:
            _rt_final = ""

        # ✅ Regra canônica: se a decisão foi SEND_LINK (ex.: policy_link_request),
        # o fellthrough também precisa carregar o link (FRONTEND_BASE).
        try:
            _rt_final = _ensure_send_link_in_reply(_rt_final, ia_next_step)
        except Exception:
            pass

        # Anti-duplicidade: se já enviamos algo (ex.: send_text(prefersText) ou audio_plus_text_link),
        # NUNCA cair no fellthrough para mandar de novo.
        try:
            if bool(sent_ok):
                logger.info("[tasks] fellthrough_skipped (already_sent) eventKey=%s wamid=%s", event_key, _wamid)
                return jsonify({"ok": True, "sent": True, "dedup": "fellthrough_skipped"}), 200
        except Exception:
            pass

        if (msg_type in ("text", "chat", "", "audio", "voice", "ptt")) and _rt_final:
            try:
                _st = send_text
                # Import sob demanda: só tenta carregar provider aqui (não mexe no fluxo "normal")
                if not _st:
                    try:
                        from providers.ycloud import send_text as _send_text  # type: ignore
                        _st = _send_text
                        send_text = _st
                    except Exception:
                        logger.exception("[tasks] ycloud_provider_import_failed (fellthrough_fallback)")
                        _st = None

                if _st:
                    logger.info("[outbound] send_text (fellthrough_fallback) to=%s chars=%d", from_e164, len(_rt_final))
                    _okF, _ = _st(from_e164, _clean_url_weirdness(_rt_final))
                    try:
                        _wa_log_outbox_deterministic(route="send_text_fellthrough", to_e164=from_e164, reply_text=(_rt_final or ""), sent_ok=bool(_okF))
                    except Exception:
                        pass
                    sent_ok = sent_ok or bool(_okF)
                    if _okF:
                        _try_log_outbox_immediate(True, "send_text_fellthrough")
                    logger.info("[tasks] end eventKey=%s wamid=%s sent_ok=%s", event_key, _wamid, bool(sent_ok))
                    return jsonify({"ok": True, "sent": bool(sent_ok)}), 200
                else:
                    logger.warning("[tasks] fellthrough_fallback: send_text is None (no provider)")
            except Exception:
                logger.exception("[tasks] fellthrough_fallback: send_text failed")
        logger.info("[tasks] early_return reason=%s eventKey=%s wamid=%s", "FELLTHROUGH_NOOP", event_key, _wamid)
        return jsonify({"ok": True}), 200
    except Exception:
        logger.exception("[tasks] worker_unhandled_exception")
        try:
            logger.info("[tasks] early_return reason=%s eventKey=%s wamid=%s", "WORKER_EXCEPTION", event_key, _wamid)
        except Exception:
            logger.info("[tasks] early_return reason=%s", "WORKER_EXCEPTION")
        # IMPORTANTE: retornar 200 evita retry infinito do Cloud Tasks enquanto depuramos
        return jsonify({"ok": True, "error": "worker_exception"}), 200

     # Guard final: nunca pode "cair fora" sem return (evita 500 + retry infinito no Cloud Tasks)
    logger.error(
        "[tasks] final_return_guard eventKey=%s wamid=%s",
        (event_key if "event_key" in locals() else ""),
        (_wamid if "_wamid" in locals() else ""),
    )
    return jsonify({"ok": True, "guard": "final_return_guard"}), 200

    logger.error("[tasks] REACHED_END_OF_IMPL (guard) eventKey=%s", str(event_key or ""))
    return jsonify({"ok": True, "guard": "fell_off_impl", "eventKey": str(event_key or "")}), 200
