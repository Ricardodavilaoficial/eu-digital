# routes/ycloud_tasks_bp.py
from __future__ import annotations

import os
import time
import random
import re
import hashlib
import logging
import uuid
import datetime
from google.cloud import storage as gcs_storage  # type: ignore
from typing import Any, Dict, Optional, Tuple

import requests

from flask import Blueprint, request, jsonify

from services.phone_utils import digits_only as _digits_only_c, to_plus_e164 as _to_plus_e164_c
from google.cloud import firestore  # type: ignore

logger = logging.getLogger("mei_robo.ycloud_tasks")

# Limites para manter "entra áudio -> sai áudio" sem 413 no /api/voz/tts
_SUPPORT_TTS_MAX_CHARS = int(os.environ.get("SUPPORT_TTS_MAX_CHARS", "650") or "650")
_SUPPORT_TTS_RETRY_MAX_CHARS = int(os.environ.get("SUPPORT_TTS_RETRY_MAX_CHARS", "420") or "420")
_SUPPORT_WA_TEXT_MAX_CHARS = int(os.environ.get("SUPPORT_WA_TEXT_MAX_CHARS", "900") or "900")

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


# Memória em-processo para "spice" (saudação do Firestore) com cadência
_LAST_SPICE_AT = {}          # wa_key -> epoch seconds
_LAST_SPICE_TEXT = {}        # wa_key -> last greeting used
ycloud_tasks_bp = Blueprint("ycloud_tasks_bp", __name__)


_IDENTITY_MODE = (os.environ.get("IDENTITY_MODE") or "on").strip().lower()  # on|off


def _db():
    project_id = (os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip() or None
    return firestore.Client(project=project_id)


def _db_admin():
    try:
        from firebase_admin import firestore as admin_fs  # type: ignore
        return admin_fs.client()
    except Exception:
        return None


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


def _digits_only(s: str) -> str:
    return _digits_only_c(s)


def _to_plus_e164(raw: str) -> str:
    return _to_plus_e164_c(raw)


_NAME_OVERRIDE_TTL = int(os.environ.get("SUPPORT_NAME_OVERRIDE_TTL_SECONDS", "3600") or "3600")  # 1h



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
    - If the message indicates returning to the owner (e.g., \"voltei\", \"agora sou eu de novo\") and owner_name is known, return owner_name.
    - Avoid third-person mentions (e.g., \"o papo é com o José\") unless it\'s clearly the speaker.
    - Name can be nickname (e.g., \"Banana\", \"Zé\").
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
    t = (text or "").strip()
    if not t:
        return ""
    patterns = [
        r"\bmeu nome é\s+(?:o|a|os|as)?\s*([A-Za-zÀ-ÿ]{2,}(?:\s+[A-Za-zÀ-ÿ]{2,}){0,2})\b",
        r"\baqui é\s+(?:o|a|os|as)?\s*([A-Za-zÀ-ÿ]{2,}(?:\s+[A-Za-zÀ-ÿ]{2,}){0,2})\b",
        r"\baqui quem fala é\s+([A-Za-zÀ-ÿ]{2,})\b",
        r"\bnão é\s+[A-Za-zÀ-ÿ]{2,}\s*,?\s*é\s+([A-Za-zÀ-ÿ]{2,})\b",
        r"\bnão sou\s+[A-Za-zÀ-ÿ]{2,}\s*,?\s*sou\s+([A-Za-zÀ-ÿ]{2,})\b",
    ]
    for p in patterns:
        m = re.search(p, t, flags=re.IGNORECASE)
        if m:
            return (m.group(1) or "").strip()
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
    # colapsa espaços
    t = re.sub(r"\s+", " ", t).strip()
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
    "- NÃO comece com saudação (nada de \"oi\", \"olá\", \"fala\", \"Faaala\", \"Graaande\").\n"
    "- NÃO use o nome da pessoa.\n"
    "- Sem emojis, sem CAPS, sem múltiplas exclamações.\n"
    "- 2–4 frases curtas + 1 pergunta final.\n"
    "- Se citar limites, use \"megabytes/gigabytes\" por extenso (nunca \"MB/GB\").\n"
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


def _make_tts_text(reply_text: str, display_name: str) -> str:
    """
    Constrói o texto falado (TTS) com tom humano:
    - abre com nome quando disponível e quando não há saudação
    - limpa bullets/ícones
    - fecha com porta aberta curta
    """
    base = _clean_for_speech(reply_text)
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


@ycloud_tasks_bp.route("/tasks/ycloud-inbound", methods=["POST"])
def ycloud_inbound_worker():
    # Auth simples via secret (modo Render)
    secret = (os.environ.get("CLOUD_TASKS_SECRET") or "").strip()
    got = (request.headers.get("X-MR-Tasks-Secret") or "").strip()
    if not secret or got != secret:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    event_key = (data.get("eventKey") or "").strip()
    payload = data.get("payload") or {}

    if not event_key or not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "bad_request"}), 400
    # ==========================================================
    # FILTRO DE EVENTO (anti-eco / anti-loop)
    # Worker só processa inbound real do usuário.
    # ==========================================================
    ev_type = (payload.get("eventType") or "").strip()
    if ev_type != "whatsapp.inbound_message.received":
        return jsonify({"ok": True, "ignored": True, "eventType": ev_type}), 200


    dedup_ttl = int(os.environ.get("CLOUD_TASKS_DEDUP_TTL_SECONDS", "86400") or "86400")
    if not _idempotency_once(event_key, ttl_seconds=dedup_ttl):
        return jsonify({"ok": True, "deduped": True}), 200

    try:
        # --- normalização mínima do evento ---
        msg_type = (payload.get("messageType") or payload.get("msgType") or "").strip().lower()
        from_raw = (payload.get("from") or "").strip()
        to_raw = (payload.get("to") or "").strip()
        wamid = (payload.get("wamid") or "").strip()
        text_in = (payload.get("text") or "").strip()
        media = payload.get("media") or {}

        from_e164 = _to_plus_e164(from_raw)
        to_e164 = _to_plus_e164(to_raw)        # --- resolve UID (identidade) ---
        # 1) Índice permanente: sender_uid_links/{waKey} -> uid
        uid = ""
        wa_key = ""
        try:
            from services.sender_uid_links import canonical_wa_key, get_uid_for_wa_key  # type: ignore
            wa_key = (canonical_wa_key(from_e164) or "").strip()
            uid = (get_uid_for_wa_key(wa_key) or "").strip()
        except Exception:
            wa_key = ""
            uid = ""

        # 2) Fallback legado (TTL): voice_links (fluxo de voz)
        if not uid:
            try:
                from services.voice_wa_link import get_uid_for_sender  # type: ignore
                uid = (get_uid_for_sender(from_e164) or "").strip()
            except Exception:
                uid = ""

        
        # wa_key_effective: chave canônica para memória por remetente (override etc.)
        wa_key_effective = (wa_key or _digits_only(from_e164)).strip()
        owner_name = _get_owner_name(uid) if uid else ""

# --- 1) ÁUDIO: fluxo de VOZ (ingest) SOMENTE se onboarding estiver "waiting" ---
        voice_waiting = False
        try:
            prof = _db().collection("profissionais").document(uid).get()
            prof_data = prof.to_dict() or {}
            voz = prof_data.get("voz") or {}
            wa = voz.get("whatsapp") or {}
            # regra saudável: só é onboarding de voz se estiver explicitamente aguardando áudio
            voice_waiting = (str(wa.get("status") or "").strip().lower() == "waiting")
        except Exception:
            voice_waiting = False

        if uid and msg_type in ("audio", "voice", "ptt") and voice_waiting:
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
                    pass

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
                                    "lastInboundAt": firestore.SERVER_TIMESTAMP,
                                    "updatedAt": firestore.SERVER_TIMESTAMP,
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
                if os.environ.get("VOICE_WA_ACK", "0") == "1":
                    try:
                        from providers.ycloud import send_text  # type: ignore
                        send_text(
                            to_e164=from_e164,
                            text="✅ Áudio recebido com sucesso.\nAgora volte para a tela de configuração e clique em Continuar."
                        )
                    except Exception:
                        logger.exception("[tasks] voice: falha ao enviar ACK via WhatsApp")

                try:
                    _db().collection("platform_wa_outbox_logs").add({
                        "createdAt": firestore.SERVER_TIMESTAMP,
                        "from": from_e164,
                        "to": to_e164,
                        "wamid": wamid,
                        "msgType": msg_type,
                        "route": "voice_ingest",
                        "replyText": "ACK: voz recebida (configuração)",
                        "audioUrl": "",
                        "audioDebug": {},
                        "eventKey": event_key,
                        "sentOk": True,
                    })
                except Exception:
                    pass
                return jsonify({"ok": True, "voice": "stored"}), 200

            except Exception:
                logger.exception("[tasks] voice: falha ingest uid=%s", uid)
                return jsonify({"ok": True, "voice": "failed"}), 200

        # --- 2) LEAD / TEXTO: chama WA_BOT (vendas se uid vazio) ---
        reply_text = ""
        audio_url = ""
        audio_debug = {}
        tts_text_final_used = ""  # texto final que foi pro TTS
        wa_out = None

        try:
            from services.firebase_admin_init import ensure_firebase_admin  # type: ignore
            ensure_firebase_admin()

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
                                base = (os.environ.get("BACKEND_BASE") or "").strip().rstrip("/")
                                if not base:
                                    # tenta inferir pelo request atual
                                    base = (request.host_url or "").strip().rstrip("/")
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
                    ctx_for_bot = {
                        "channel": "whatsapp",
                        "from_e164": from_e164,
                        "waKey": wa_key_effective,
                        "to_e164": to_e164,
                        "msg_type": msg_type,
                        "wamid": wamid,
                        "route_hint": route_hint,
                        "event_key": event_key,
                    }
                    # PATCH A (obrigatório): garantir msg_type no ctx do wa_bot
                    ctx_for_bot["msg_type"] = msg_type  # "audio" | "voice" | "ptt" | "text"
    
                    wa_out = wa_bot_entry.reply_to_text(
                        uid=uid,
                        text=text_in,
                        ctx=ctx_for_bot,
                    )

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
                                "hasAudioUrl": bool((wa_out.get("audioUrl") or wa_out.get("audio_url") or "").strip()),
                                "prefersText": bool(wa_out.get("prefersText")),
                                "displayName": str(wa_out.get("displayName") or "").strip()[:40],
                                "ttsOwner": str(wa_out.get("ttsOwner") or "").strip()[:40],
                            }
                    except Exception:
                        pass

        except Exception as e:
            # Best-effort: não derruba o worker se o wa_bot falhar/import quebrar
            logger.exception("[tasks] wa_bot_failed route_hint=%s from=%s wamid=%s", ("sales" if not uid else "customer"), from_e164, wamid)
            reply_text = ""
            audio_url = ""
            audio_debug = {"err": str(e)}
            kb_context = ""
            wa_kind = ""

        if isinstance(wa_out, dict):
            reply_text = (
                wa_out.get("replyText")
                or wa_out.get("text")
                or wa_out.get("reply")
                or wa_out.get("message")
                or ""
                )
            audio_url = (wa_out.get("audioUrl") or wa_out.get("audio_url") or "").strip()
            wa_audio_debug = wa_out.get("audioDebug") or {}
            if isinstance(wa_audio_debug, dict):
                # merge: preserva o que o worker já tinha + adiciona o do wa_bot
                audio_debug = {**(audio_debug or {}), **wa_audio_debug}
            else:
                audio_debug = (audio_debug or {})
            kb_context = (wa_out.get("kbContext") or wa_out.get("kb_context") or "")
            wa_kind = (wa_out.get("kind") or wa_out.get("type") or "")

        elif wa_out:
            reply_text = str(wa_out)

        # PATCH B: respeitar prefersText / displayName vindo do wa_bot
        prefers_text = False
        display_name = ""
        if isinstance(wa_out, dict):
            prefers_text = bool(wa_out.get("prefersText"))
            display_name = (wa_out.get("displayName") or "").strip()
        # Se entrou por áudio, nunca preferir texto (mantém "entra áudio → sai áudio")
        if msg_type in ("audio", "voice", "ptt"):
            prefers_text = False


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
                        "afterLen": len(reply_text),
                    }
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
                    }

                    # speaker state probe
                    try:
                        sp = _speaker_db().collection(_SPEAKER_COLL).document(wa_key_effective).get()
                        spd = sp.to_dict() or {}
                        audio_debug["speakerStateProbe_get"] = {
                            "docExists": bool(sp.exists),
                            "displayName": str(spd.get("displayName") or "").strip(),
                            "expiresAt": float(spd.get("expiresAt") or 0.0),
                            "source": str(spd.get("source") or "").strip(),
                            "confidence": float(spd.get("confidence") or 0.0),
                            "now": time.time(),
                        }
                    except Exception:
                        pass
                    if exp and time.time() > exp:
                        override = ""
            except Exception as e:
                audio_debug = dict(audio_debug or {})
                audio_debug["nameOverrideProbe_get_err"] = str(e)[:120]
                override = ""

            if override:
                reply_text_before_override = reply_text
                reply_text = _apply_name_override(reply_text, override)
                audio_debug = dict(audio_debug or {})
                audio_debug["nameOverride"] = {"applied": True, "name": override}

                # 🔥 CRÍTICO: se já tinha áudio pronto (ex.: vindo do wa_bot),
                # mas o texto mudou por override, invalida áudio pra regenerar com o nome certo.
                if audio_url and reply_text != reply_text_before_override:
                    audio_debug["ttsRegen"] = {"forced": True, "reason": "name_override_changed_text"}
                    audio_url = ""
        except Exception:
            pass

        # ==========================================================
        # Se o usuário pediu "somente texto", respeita.
        if prefers_text and msg_type in ("audio", "voice", "ptt"):
            audio_debug = dict(audio_debug or {})
            audio_debug["mode"] = "text_only_requested"
            audio_url = ""  # garante que não envia áudio

        # ==========================================================
        # TTS automático (universal): se entrou por áudio, deve sair por áudio.
        # Se o wa_bot não devolveu audioUrl, geramos via /api/voz/tts.
        #
        # - customer (uid): usa vozClonada.voiceId se existir
        # - sales (uid vazio): usa INSTITUTIONAL_VOICE_ID (ENV) se existir
        # ==========================================================
        if msg_type in ("audio", "voice", "ptt") and (not audio_url) and reply_text and (not prefers_text):
            try:
                base = (os.environ.get("BACKEND_BASE") or "").strip().rstrip("/")
                if not base:
                    base = (request.host_url or "").strip().rstrip("/")
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
                                        
                                                        # 🔥 PATCH CRÍTICO: TTS recebe um texto curto e "falável".
                    # (não é o mesmo texto canônico; é versão para FALA)
                    tts_text = reply_text
                    try:
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
                        if tts_name and wa_key_effective:
                            last = float(_LAST_NAME_SPOKEN_AT.get(wa_key_effective) or 0.0)
                            if (time.time() - last) >= float(_SUPPORT_NAME_MIN_GAP_SECONDS):
                                name_to_use = tts_name
                                _LAST_NAME_SPOKEN_AT[wa_key_effective] = time.time()

                        # 1) Se for conceitual e houver kbContext: gera fala humana a partir do CONTEXTO (não lê artigo)
                        concept_generated = False
                        try:
                            if _SUPPORT_TTS_CONCEPT_MODE == "on" and str(wa_kind or "").strip().lower() == "conceptual" and (kb_context or "").strip():
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
                        greet = _pick_support_greeting(support_persona, wa_key_effective, tts_name, is_informal)
                        used_spice = bool(greet)

                        if greet:
                            tts_text = f"{greet} {tts_text}".strip()
                            name_to_use_for_make = ""
                        else:
                            name_to_use_for_make = name_to_use

                        # 4) texto falável base (limpo + nome opcional, mas sem duplicar se teve spice)
                        if concept_generated:
                            tts_text = _clean_for_speech(tts_text)
                        else:
                            tts_text = _make_tts_text(tts_text, name_to_use_for_make)

                        # 5) IA reescreve para fala humana (agora com persona do Firestore)
                        if _SUPPORT_TTS_SUMMARY_MODE == "on":
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
                        audio_debug = dict(audio_debug or {})
                        audio_debug["ttsTextProbe"] = {
                            "nameUsed": (name_to_use or ""),
                            "len": len(tts_text or ""),
                            "preview": (tts_text or "")[:140],
                        }
# Corte para evitar 413
                        if tts_text and len(tts_text) > _SUPPORT_TTS_MAX_CHARS:
                            before = tts_text
                            tts_text = _shorten_for_speech(tts_text, _SUPPORT_TTS_MAX_CHARS)
                            audio_debug = dict(audio_debug or {})
                            audio_debug["ttsInputShorten"] = {
                                "applied": True,
                                "maxChars": _SUPPORT_TTS_MAX_CHARS,
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
                    tts_text_final_used = tts_text

                    rr = _call_tts(tts_text)

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
                                audio_debug["tts"] = {"ok": True, "mode": "json_audioUrl"}
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

                                client = gcs_storage.Client()
                                bucket = client.bucket(bucket_name)
                                blob = bucket.blob(obj)
                                blob.upload_from_string(b, content_type="audio/mpeg")

                                exp_s = int(os.environ.get("SIGNED_URL_EXPIRES_SECONDS", "900") or "900")
                                audio_url = blob.generate_signed_url(
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
        allow_audio = os.environ.get("YCLOUD_TEXT_REPLY_AUDIO", "1") not in ("0", "false", "False")

        try:
            from providers.ycloud import send_text, send_audio  # type: ignore
        except Exception:
            send_text = None  # type: ignore
            send_audio = None  # type: ignore

        # PATCH B: se prefersText, manda direto texto e não tenta áudio
        if prefers_text and send_text:
            try:
                sent_ok, _ = send_text(from_e164, reply_text)
            except Exception:
                logger.exception("[tasks] lead: falha send_text (prefersText)")
        
        if (not prefers_text) and allow_audio and msg_type in ("audio", "voice", "ptt") and audio_url and send_audio:
            try:
                sent_ok, _ = send_audio(from_e164, audio_url)
            except Exception:
                logger.exception("[tasks] lead: falha send_audio")

        if (not sent_ok) and send_text:
            try:
                sent_ok, _ = send_text(from_e164, reply_text)
            except Exception:
                logger.exception("[tasks] lead: falha send_text")

        
        # ==========================================================
        # Auditoria: alinhamento explícito entre replyText e spokenText (TTS)
        # ==========================================================
        spoken_source = "replyText_pipeline"
        if wa_kind == "conceptual" and kb_context:
            spoken_source = "kbContext_concept"

        audio_debug = dict(audio_debug or {})
        audio_debug.setdefault("auditAlignment", {})
        audio_debug["auditAlignment"].update({
            "replyTextRole": "canonical_base",
            "spokenTextRole": "spoken_source_of_truth",
            "spokenSource": spoken_source,
            "replyTextSha1": _sha1(reply_text),
            "spokenTextSha1": _sha1(tts_text_final_used),
            "note": "Áudio é versão otimizada para fala do replyText (ou do kbContext quando conceptual).",
        })

# log leve (auditoria). Precisa ocorrer antes do return.
        try:
            _db().collection("platform_wa_outbox_logs").add({
        "createdAt": firestore.SERVER_TIMESTAMP,
        "from": from_e164,
        "to": to_e164,
        "wamid": wamid,
        "msgType": msg_type,
        "route": "sales" if not uid else "customer",
        "replyText": (reply_text or "")[:400],
        "audioUrl": (audio_url or "")[:300],
        "audioDebug": audio_debug,
        "spokenText": (tts_text_final_used or "")[:600],
        "eventKey": event_key,
        "sentOk": bool(sent_ok),
            })
        except Exception:
            logger.warning("[tasks] outbox_log_failed from=%s to=%s wamid=%s eventKey=%s", from_e164, to_e164, wamid, event_key, exc_info=True)

        return jsonify({"ok": True, "sent": bool(sent_ok)}), 200

    except Exception:
        logger.exception("[tasks] fatal: erro inesperado")
        return jsonify({"ok": True}), 200
