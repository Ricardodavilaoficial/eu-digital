# services/wa_bot.py
# Bot WhatsApp do MEI Robô
# - NLU leve "sempre on"
# - Preços: consolida de 3 fontes (doc.precos [map/lista], coleção /precos, coleção /produtosEServicos)
# - Profissão + até 2 especializações: sinônimos e matching por contexto
# - Cache de respostas de preço (quanto custa X?) via cache.kv (TTL)
# - FAQ fixos via profissionais/{uid}/faq/{endereco|horarios|telefone|pix}
# - Agendar/Reagendar com regras (sem fim de semana; +2 dias) e integração schedule se existir
# - Budget Guard: gate de custos (sem falar de economia ao usuário)
# - Microcopy humana + overrides opcionais por Firestore (l10n/persona)
# - Se o cliente falar por áudio, responder por áudio (se o app injetar send_audio_fn)
# - *** Harmonização MSISDN BR com/sem 9 (equivalence key + candidatos) ***
# - *** Humanização plugável via services.humanizer (sanitização e microcopy) ***

import os
import json
import logging

NLU_MODE = os.getenv("NLU_MODE", "legacy").strip().lower()
PRICING_MODE = os.getenv("PRICING_MODE", "legacy").strip().lower()  # legacy | domain
REPLY_AUDIO_WHEN_AUDIO = os.getenv("REPLY_AUDIO_WHEN_AUDIO", "true").strip().lower() in ("1", "true", "yes")
ACERVO_MODE = os.getenv("ACERVO_MODE", "off").strip().lower()  # off | on | only:uid1,uid2
CONTACT_MEMORY_MODE = os.getenv("CONTACT_MEMORY_MODE", "off").strip().lower()  # off | probe | on

# ---- Humanizer (feature-flag) ----
try:
    from services.humanizer import humanize as H, sanitize_text as H_sanitize, humanize_on
except Exception:
    def H(intent, payload, mode="text"): return (payload.get("raw","") or "").strip()
    def H_sanitize(s): return (s or "").strip()
    def humanize_on(): return False

try:
    from nlu.intent import detect_intent as detect_intent_v1
except Exception:
    detect_intent_v1 = None

try:
    # Legacy já existente no projeto
    from services.openai.nlu_intent import detect_intent as detect_intent_legacy
except Exception:
    detect_intent_legacy = None

# --- Contact Memory (histórico por contato) ---
try:
    from domain.contact_memory import build_contact_context, contact_memory_enabled_for
except Exception:
    build_contact_context = None

    def contact_memory_enabled_for(_uid: str) -> bool:
        return False


def parse_intent(text: str):
    """
    Fachada estável de intenção.
    Padrão: legacy. Quando NLU_MODE=v1 e houver módulo, usa nlu.intent.
    Em erro, faz fallback.
    """
    mode = NLU_MODE or "legacy"

    if mode == "v1" and detect_intent_v1:
        try:
            return detect_intent_v1(text)
        except Exception:
            pass

    if detect_intent_legacy:
        try:
            return detect_intent_legacy(text)
        except Exception:
            pass

    return {"intent": "desconhecida", "confidence": 0.0, "version": mode}


def _nlu_probe(uid: str, text: str):
    """
    Apenas LOGA a intenção quando NLU_MODE=v1.
    Não altera a resposta/fluxo. Serve pra validar v1 com usuário canário.
    """
    if (NLU_MODE == "v1") and detect_intent_v1:
        try:
            intent = detect_intent_v1(text or "")
            logging.info("[NLU_PROBE][uid=%s] %s", uid or "-", json.dumps(intent, ensure_ascii=False))
        except Exception as e:
            logging.warning("[NLU_PROBE][uid=%s][error]=%s", uid or "-", repr(e))


def _merge_intents_legacy_with_v1(nlu_legacy: dict, text: str) -> dict:
    """
    Se NLU_MODE=v1, consulta o v1 e (apenas) ajusta o campo intent para buckets
    simples do legacy, mantendo os demais campos (dateText, timeText etc.) do legacy.
    """
    if NLU_MODE != "v1" or not detect_intent_v1:
        return nlu_legacy
    try:
        v1 = detect_intent_v1(text or "") or {}
    except Exception:
        return nlu_legacy

    intent_v1 = (v1.get("intent") or "").lower()
    mapper = {
        "preco": "precos",
        "agendar": "agendar",
        "faq": "fallback",
        "saudacao": "fallback",
        "desconhecida": "fallback",
    }
    if intent_v1 in mapper:
        out = dict(nlu_legacy or {})
        out["intent"] = mapper[intent_v1]
        out["_v1"] = v1
        out["_src"] = "merged_v1"
        return out
    return nlu_legacy
# ============================================================================

import re
import requests
import unicodedata
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

# ========== Helpers de telefone (equivalence key + candidatos) ==========
# Preferimos services.phone_utils; se não houver, fallback local
try:
    from services.phone_utils import (
        br_equivalence_key as _br_equivalence_key_ext,
        br_candidates as _br_candidates_ext,
        digits_only as _digits_only_ext,
    )  # type: ignore

    def br_equivalence_key(msisdn: str) -> str:
        return _br_equivalence_key_ext(msisdn)

    def br_candidates(msisdn: str) -> List[str]:
        return _br_candidates_ext(msisdn)

    def _only_digits(s: str) -> str:
        return _digits_only_ext(s)

    logging.info("[wa_bot][phone] usando services.phone_utils")
except Exception:
    logging.info("[wa_bot][phone] services.phone_utils indisponível; usando fallback local")
    _DIGITS_RE = re.compile(r"\D+")

    def _only_digits(s: str) -> str:
        return _DIGITS_RE.sub("", s or "")

    def _ensure_cc_55(d: str) -> str:
        d = _only_digits(d)
        if d.startswith("00"):
            d = d[2:]
        if not d.startswith("55"):
            d = "55" + d
        return d

    def _br_split(msisdn: str) -> Tuple[str, str, str]:
        d = _ensure_cc_55(msisdn)
        cc = d[:2]
        rest = d[2:]
        ddd = rest[:2] if len(rest) >= 10 else rest[:2]
        local = rest[2:]
        return cc, ddd, local

    def br_equivalence_key(msisdn: str) -> str:
        cc, ddd, local = _br_split(msisdn)
        local8 = _only_digits(local)[-8:]
        return f"{cc}{ddd}{local8}"

    def br_candidates(msisdn: str) -> List[str]:
        cc, ddd, local = _br_split(msisdn)
        local_digits = _only_digits(local)
        cands = set()
        if len(local_digits) >= 9 and local_digits[0] == "9":
            with9 = f"{cc}{ddd}{local_digits}"
            without9 = f"{cc}{ddd}{local_digits[1:]}"
            cands.add(with9)
            cands.add(without9)
        elif len(local_digits) == 8:
            without9 = f"{cc}{ddd}{local_digits}"
            with9 = f"{cc}{ddd}9{local_digits}"
            cands.add(without9)
            cands.add(with9)
        else:
            cands.add(f"{cc}{ddd}{local_digits}")
        return [c for c in cands if len(c) in (12, 13)]


def _normalize_br_msisdn(wa_id: str) -> str:
    """Compatibilidade: insere 9 quando detectar 55 + DDD + local(8)."""
    if not wa_id:
        return ""
    digits = _only_digits(wa_id)
    if digits.startswith("55") and len(digits) == 12:
        digits = digits[:4] + "9" + digits[4:]
    return digits

# ========== DB helpers (imports tolerantes + helpers internos) ==========
_DB_LAST_ERR = None

# tentamos absolute...
try:
    from services import db as _dbsvc_abs
    _DB_CLIENT = getattr(_dbsvc_abs, "db", None)
    try:
        # get_doc pode não existir no módulo; tratamos abaixo
        from services.db import get_doc as _ext_get_doc_abs  # type: ignore
    except Exception:
        _ext_get_doc_abs = None  # type: ignore
except Exception as e_abs:
    _DB_LAST_ERR = f"abs:{e_abs}"
    _dbsvc_abs = None
    _DB_CLIENT = None
    _ext_get_doc_abs = None  # type: ignore

# ...ou relative
if _DB_CLIENT is None:
    try:
        from . import db as _dbsvc_rel  # type: ignore
        _DB_CLIENT = getattr(_dbsvc_rel, "db", None)
        try:
            from .db import get_doc as _ext_get_doc_rel  # type: ignore
        except Exception:
            _ext_get_doc_rel = None  # type: ignore
    except Exception as e_rel:
        _DB_LAST_ERR = (_DB_LAST_ERR or "") + f" | rel:{e_rel}"
        _dbsvc_rel = None
        _DB_CLIENT = None
        _ext_get_doc_rel = None  # type: ignore

# escolhemos qualquer get_doc que tenha vindo (corrigido)
try:
    _GET_DOC_FN = _ext_get_doc_abs or _ext_get_doc_rel  # type: ignore
except NameError:
    _GET_DOC_FN = None  # type: ignore


def _db_ready() -> bool:
    # Só usa Firestore se existir client E FIREBASE_PROJECT_ID
    return (_DB_CLIENT is not None) and bool(os.getenv("FIREBASE_PROJECT_ID"))


def _get_firestore_doc_ref(path: str):
    """Navega até um documento Firestore a partir de 'col/doc[/col/doc...]'."""
    if not _db_ready():
        return None
    parts = [p for p in (path or "").split("/") if p]
    if not parts or len(parts) % 2 != 0:
        return None  # precisa ser doc (número PAR de segmentos)
    ref = _DB_CLIENT
    for i, part in enumerate(parts):
        ref = ref.collection(part) if i % 2 == 0 else ref.document(part)
    return ref


def _get_firestore_col_ref(path: str):
    """Navega até uma coleção Firestore a partir de 'col[/doc/col...]' (número ÍMPAR de segmentos)."""
    if not _db_ready():
        return None
    parts = [p for p in (path or "").split("/") if p]
    if not parts or len(parts) % 2 != 1:
        return None
    ref = _DB_CLIENT
    for i, part in enumerate(parts):
        ref = ref.collection(part) if i % 2 == 0 else ref.document(part)
    return ref  # CollectionReference


def _get_doc_safe(path: str) -> Optional[Dict[str, Any]]:
    """Usa get_doc do services.db se existir; caso contrário, lê via client."""
    if not _db_ready():
        return None
    if callable(_GET_DOC_FN):
        try:
            return _GET_DOC_FN(path)  # type: ignore
        except Exception as e:
            logging.info("[wa_bot] _GET_DOC_FN falhou: %s", e)
    # fallback via client
    ref = _get_firestore_doc_ref(path)
    if ref is None:
        return None
    try:
        snap = ref.get()
        return snap.to_dict() if getattr(snap, "exists", False) else None
    except Exception as e:
        logging.info("[wa_bot] get via client falhou: %s", e)
        return None


def _list_collection_safe(path: str, limit: int = 500) -> List[Dict[str, Any]]:
    """Lista documentos de uma coleção por caminho textual (sem depender de list_collection externa)."""
    if not _db_ready():
        return []
    col_ref = _get_firestore_col_ref(path)
    out: List[Dict[str, Any]] = []
    if col_ref is None:
        return out
    try:
        docs = col_ref.limit(int(limit)).stream()  # type: ignore
        for d in docs:
            obj = d.to_dict() or {}
            obj["_id"] = d.id
            out.append(obj)
    except Exception as e:
        logging.info("[wa_bot] stream collection falhou: %s", e)
    return out


# Alias curto para o client (para writes/sessions)
DB = _DB_CLIENT

# ========== NLU leve (imports tolerantes) ==========
try:
    # ⚠️ Alias para evitar o erro "cannot import name 'extract_intent'":
    from services.openai.nlu_intent import detect_intent as extract_intent  # abs
except Exception as e_abs:
    try:
        from .openai.nlu_intent import detect_intent as extract_intent  # rel
    except Exception as e_rel:
        logging.exception("[wa_bot] nlu_intent indisponível: abs=%s | rel=%s", e_abs, e_rel)

        def extract_intent(text: str) -> Dict[str, Optional[str]]:
            t = (text or "").lower()
            if re.search(r"\b(preço|preços|tabela|valor|valores|serviço|serviços)\b", t):
                return {"intent": "precos", "serviceName": None, "dateText": None, "timeText": None}
            if re.search(r"\b(agendar|agenda|marcar|agendamento|reservar)\b", t):
                mdate = re.search(r"(\d{1,2}/\d{1,2})", t)
                mtime = re.search(r"(\d{1,2}:\d{2})", t)
                return {
                    "intent": "agendar",
                    "serviceName": None,
                    "dateText": mdate.group(1) if mdate else None,
                    "timeText": mtime.group(1) if mtime else None,
                }
            if re.search(r"\b(reagendar|remarcar|mudar\s+hor[áó]rio|trocar\s+hor[áó]rio)\b", t):
                return {"intent": "reagendar", "serviceName": None, "dateText": None, "timeText": None}
            if re.search(r"\b(endereç|localiza|maps?)\b", t):
                return {"intent": "localizacao", "serviceName": None, "dateText": None, "timeText": None}
            if re.search(r"\b(hor[áa]rio|funciona)\b", t):
                return {"intent": "horarios", "serviceName": None, "dateText": None, "timeText": None}
            if re.search(r"\b(telefone|whats|contato)\b", t):
                return {"intent": "telefone", "serviceName": None, "dateText": None, "timeText": None}
            if re.search(r"\b(pix|pagamento|pagar)\b", t):
                return {"intent": "pagamento", "serviceName": None, "dateText": None, "timeText": None}
            return {"intent": "fallback", "serviceName": None, "dateText": None, "timeText": None}

# ========== Budget Guard (imports tolerantes) ==========
try:
    from services.budget_guard import budget_fingerprint, charge, can_use_audio, can_use_gpt4o  # abs
except Exception as e_abs:
    try:
        from .budget_guard import budget_fingerprint, charge, can_use_audio, can_use_gpt4o  # rel
    except Exception as e_rel:
        logging.exception("[wa_bot] budget_guard indisponível: abs=%s | rel=%s", e_abs, e_rel)

        def budget_fingerprint():
            return {"can_audio": True, "can_gpt4o": False}

        def charge(*args, **kwargs):
            pass

        def can_use_audio():
            return True

        def can_use_gpt4o():
            return False
            
# ==== ACERVO / MINI-RAG (helpers) ==========================================
def _acervo_mode() -> str:
    try:
        return os.getenv("ACERVO_MODE", "off").strip().lower()
    except Exception:
        return "off"


def _acervo_enabled_for_uid(uid_default: str) -> bool:
    """
    Controla quem pode usar o acervo, de acordo com ACERVO_MODE.

    - off    → sempre desliga
    - on     → todos os MEIs (qualquer uid_default)
    - canary → apenas o UID listado em ACERVO_CANARY_UID (se definido)
    """
    mode = _acervo_mode()
    if mode == "off":
        return False
    if mode == "on":
        return True
    if mode == "canary":
        canary_uid = os.getenv("ACERVO_CANARY_UID", "").strip()
        if canary_uid and canary_uid == uid_default:
            return True
        # se não tiver canary definido, trata como desligado
        return False
    return False


def _try_acervo_answer(uid_default: str, pergunta: str) -> Optional[str]:
    """
    Tenta responder usando o acervo do MEI.

    - Se der erro, retorna None e deixa o fluxo cair pro fallback normal.
    - Só usa mini-RAG; não altera nada de sessão/preço/agenda.
    """
    pergunta = (pergunta or "").strip()
    if not pergunta:
        return None

    # import lazy para não quebrar boot se domain/acervo não existir
    try:
        from domain.acervo import query_acervo_for_uid  # type: ignore
    except Exception:
        logging.warning("[ACERVO] domain.acervo.query_acervo_for_uid indisponível.")
        return None

    max_tokens_default = 120
    try:
        max_tokens = int(os.getenv("LLM_MAX_TOKENS_ACERVO", str(max_tokens_default)))
    except Exception:
        max_tokens = max_tokens_default

    try:
        result = query_acervo_for_uid(
            uid=uid_default,
            pergunta=pergunta,
            max_tokens=max_tokens,
        )
    except Exception:
        logging.exception("[ACERVO] falha ao consultar mini-RAG do acervo.")
        return None

    if not isinstance(result, dict):
        return None

    reason = (result.get("reason") or "").lower()
    answer = (result.get("answer") or "").strip()

    # Só considera sucesso quando o domínio sinalizar "ok" e houver resposta
    if reason != "ok" or not answer:
        logging.info("[ACERVO] sem resposta útil (reason=%s).", reason)
        return None

    # Opcional: log mínimo dos docs usados (sem conteúdo)
    try:
        used_docs = result.get("usedDocs") or []
        ids = [str(d.get("id")) for d in used_docs if isinstance(d, dict)]
        logging.info("[ACERVO] resposta vinda do acervo. usedDocs=%s", ids)
    except Exception:
        pass

    return answer
    
# ==== Memória por contato (modo) ============================================
def _contact_memory_mode() -> str:
    """
    Controla o modo de uso da memória por contato via CONTACT_MEMORY_MODE.

    Valores esperados:
      - off   → totalmente desligado
      - probe → só loga o que seria usado (sem mudar resposta ao cliente)
      - on    → ligado (iremos usar de verdade nas próximas atividades)
    """
    try:
        m = (CONTACT_MEMORY_MODE or "off").strip().lower()
    except Exception:
        m = "off"
    return m or "off"

def _contact_memory_probe_enabled(uid: str) -> bool:
    """
    Retorna True quando devemos ao menos LOGAR a resolução de cliente/contato.
    Nesta atividade, mesmo quando ativo, ele NÃO muda a resposta ao cliente.
    """
    mode = _contact_memory_mode()
    if mode == "off":
        return False
    if mode in ("probe", "on"):
        return True
    return False

# ========== Cache KV (novo) ==========
# - Usamos cache.kv quando disponível; caso contrário, fallback em memória local.
try:
    from cache.kv import make_key as kv_make_key, get as kv_get, put as kv_put  # type: ignore

    _KV_OK = True
except Exception as e_kv:
    logging.warning("[wa_bot] cache.kv indisponível: %s", e_kv)
    _KV_OK = False
    # Fallback simples em memória com TTL
    _kv_mem: Dict[str, Tuple[Any, float]] = {}

    def kv_make_key(uid: str, intent: str, slug: str) -> str:
        uid = (uid or "").strip().lower()
        intent = (intent or "").strip().lower()
        slug = re.sub(r"\s+", "-", (slug or "").strip().lower())
        return f"{uid}::{intent}::{slug}"[:512]

    def kv_put(uid: str, key: str, value: Any, ttl_sec: int = 1800) -> bool:
        exp = datetime.utcnow().timestamp() + max(1, int(ttl_sec))
        _kv_mem[key] = (value, exp)
        return True

    def kv_get(uid: str, key: str):
        row = _kv_mem.get(key)
        if not row:
            return None
        value, exp = row
        if exp <= datetime.utcnow().timestamp():
            _kv_mem.pop(key, None)
            return None
        return value


# Heurística de pergunta de preço (mantida local)
def is_price_question(text: str) -> bool:
    return bool(re.search(r"\b(quanto|preço|precos|valor|custa|tá|ta)\b", text or "", re.I))


# ========== Acervo (mini-RAG) ==========

try:
    # Tentativa 1: nome mais provável
    from domain.acervo import query_acervo_for_uid as _acervo_query_for_uid  # type: ignore
except Exception:
    try:
        # Compatibilidade se o domínio expor outro nome
        from domain.acervo import answer_question_for_uid as _acervo_query_for_uid  # type: ignore
    except Exception:
        _acervo_query_for_uid = None  # type: ignore


def _acervo_enabled_for(uid: str) -> bool:
    """
    Liga/desliga o uso do acervo por ambiente e, opcionalmente, por UID.
    ACERVO_MODE:
      - "off" (padrão): nunca usa acervo
      - "on"/"true"/"1": liga para todos
      - "only:uid1,uid2": liga só para esses profissionais
    """
    if not _acervo_query_for_uid:
        return False

    mode = ACERVO_MODE or "off"
    if mode in ("on", "1", "true", "all"):
        return True
    if mode.startswith("only:"):
        try:
            allowed_str = mode.split(":", 1)[1]
            allowed = [x.strip() for x in allowed_str.split(",") if x.strip()]
            return uid in allowed
        except Exception:
            return False
    return False


def _acervo_answer(uid: str, pergunta: str, *, max_tokens: int = 256) -> Optional[str]:
    """
    Consulta o domínio do acervo para tentar responder em nome do MEI.
    Ainda NÃO está plugado no fluxo principal (isso vem em outro passo).
    """
    if not _acervo_enabled_for(uid):
        return None

    pergunta = (pergunta or "").strip()
    if not pergunta or len(pergunta) < 8:
        # ignora perguntas muito curtinhas tipo "oi", "blz?"
        return None

    if not _acervo_query_for_uid:
        return None

    try:
        # Tentativa 1: assinatura (uid, pergunta, max_tokens=...)
        try:
            res = _acervo_query_for_uid(uid, pergunta, max_tokens=max_tokens)  # type: ignore[misc]
        except TypeError:
            # Tentativa 2: (uid, pergunta)
            res = _acervo_query_for_uid(uid, pergunta)  # type: ignore[misc]

        if isinstance(res, dict):
            txt = (
                res.get("answer")
                or res.get("resposta")
                or res.get("texto")
                or res.get("message")
            )
        else:
            txt = str(res or "")

        txt = (txt or "").strip()
        if not txt:
            return None

        # Sanitiza antes de mandar pro cliente
        try:
            txt = H_sanitize(txt)
        except Exception:
            pass

        return txt
    except Exception as e:
        logging.info("[ACERVO] falha ao consultar acervo: %s", e)
        return None


# ========== Domain pricing (opcional) ==========
try:
    from domain.pricing import get_price as domain_get_price  # type: ignore
except Exception:
    domain_get_price = None  # type: ignore

# ========== Schedule (imports tolerantes) ==========
try:
    from services.schedule import (
        can_book,
        save_booking,
        validar_agendamento_v1,
        salvar_agendamento,
        atualizar_estado_agendamento,
    )  # abs
except Exception as e_abs:
    try:
        from .schedule import (
            can_book,
            save_booking,
            validar_agendamento_v1,
            salvar_agendamento,
            atualizar_estado_agendamento,
        )  # rel
    except Exception as e_rel:
        logging.exception("[wa_bot] schedule indisponível: abs=%s | rel=%s", e_abs, e_rel)

        def can_book(date_str, time_str, tz="America/Sao_Paulo"):
            try:
                dd, mm = [int(x) for x in re.findall(r"\d{1,2}", date_str)[:2]]
                hh, mi = [int(x) for x in re.findall(r"\d{1,2}", time_str)[:2]]
                tzinfo = timezone(timedelta(hours=-3))
                now = datetime.now(tzinfo)
                year = now.year
                dt = datetime(year, mm, dd, hh, mi, tzinfo=tzinfo)
                if (dt.date() - now.date()).days < 2:
                    return (False, "Preciso de pelo menos 2 dias de antecedência.")
                if dt.weekday() >= 5:
                    return (False, "Não atendemos em fins de semana.")
                return (True, None)
            except Exception:
                return (False, "Data/hora inválida.")

        def save_booking(uid, serviceName, dateText, timeText):
            return {"servico": serviceName or "serviço", "data": dateText, "hora": timeText}

        def validar_agendamento_v1(uid, ag):
            return (True, None, None)

        def salvar_agendamento(uid, ag):
            return {"id": "fake"}

        def atualizar_estado_agendamento(uid, ag_id, body):
            return True


# ========== Constantes / TZ ==========
SP_TZ = timezone(timedelta(hours=-3))  # America/Sao_Paulo (sem DST)
GRAPH_VERSION_DEFAULT = os.getenv("GRAPH_VERSION", "v23.0")
PRICE_CACHE_TTL = int(os.getenv("PRICE_CACHE_TTL", "1800"))  # 30 min

# ===== L10N / Microcopy humana (templates simples) ===========================
_L10N_DEFAULTS = {
    "help": "Posso te passar preços, endereço/horários ou já marcar um horário. Como posso te ajudar?",
    "price_table_header": "Alguns valores:",
    "faq_default": "Posso te ajudar com endereço, horários, telefone e Pix. O que você precisa?",
    "ask_service": "Qual serviço você quer? Exemplos: {exemplos}.",
    "ask_datetime": "Qual dia e horário ficam bons? Ex.: ‘terça 10h’ ou ‘01/09 14:00’.",
    "schedule_confirm": "Fechado: {servico} em {dia} às {hora}{preco}. Se precisar mudar, é só me falar.",
    "reschedule_ask": "Qual nova data e horário? Ex.: 02/09 10:00, ou 'quarta 15h'.",
    "session_cleared": "Pronto, zerei nossa conversa. Quer recomeçar com ‘preços’ ou ‘agendar’?",
    "audio_error": "Poxa, tive um probleminha aqui com seu áudio. Pode tentar de novo? Se preferir, me manda por texto também."
}

def _load_l10n_overrides(uid: str) -> dict:
    """Lê profissionais/{uid}/l10n (se existir) para sobrescrever textos."""
    try:
        doc = _get_doc_safe(f"profissionais/{uid}/l10n")
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}

def _apply_persona(uid: str, text: str) -> str:
    """Aplica detalhes leves de persona se existirem (não obrigatório)."""
    try:
        prof = _get_doc_safe(f"profissionais/{uid}") or {}
        persona = prof.get("persona") or {}
        assinatura = persona.get("assinatura")
        if assinatura:
            return f"{text}\n{assinatura}"
        return text
    except Exception:
        return text

def say(uid: str, key: str, **kwargs) -> str:
    """Busca texto em overrides -> defaults e formata com kwargs."""
    store = _load_l10n_overrides(uid)
    tmpl = (store.get(key) if isinstance(store, dict) else None) or _L10N_DEFAULTS.get(key) or ""
    try:
        msg = tmpl.format(**kwargs)
    except Exception:
        msg = tmpl
    return _apply_persona(uid, msg)
# ===========================================================================

# ========== Utils ==========
def _strip_accents_lower(s: str) -> str:
    s = s or ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()


def _format_brl(v: Any) -> str:
    if isinstance(v, (int, float)):
        s = f"R${v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return s
    if isinstance(v, str) and not v.strip().lower().startswith("r$"):
        return f"R$ {v}"
    return str(v)


def fallback_text(app_tag: str, context: str) -> str:
    # Microcopy humana (sem debug técnico para o cliente); usada principalmente em erros de áudio
    if humanize_on():
        return H("audio_error", {"raw": _L10N_DEFAULTS.get("audio_error","")}, mode="audio")
    return _L10N_DEFAULTS["audio_error"]


def _pick_phone(value: Dict) -> str:
    try:
        return (value.get("messages", [{}])[0] or {}).get("from") or (value.get("contacts", [{}])[0] or {}).get("wa_id") or ""
    except Exception:
        return ""


# ---- Helper para chave de cache de preço (usa cache.kv) ----
def _mk_price_cache_key(uid: str, user_text: str) -> str:
    try:
        norm = re.sub(r"\s+", " ", (user_text or "").strip().lower())[:120]
    except Exception:
        norm = ""
    return kv_make_key(uid, "price_q", norm)


# ========== Profissão & especializações ==========
def _load_prof_context(uid: str) -> Dict[str, Any]:
    """Lê profissionais/{uid} e retorna {profissao, especializacoes[], aliases(Optional map)}."""
    prof = _get_doc_safe(f"profissionais/{uid}") or {}
    prof_context = {
        "profissao": (prof.get("profissao") or "").strip().lower(),
        "especializacoes": [],
        "aliases": {},
    }
    if isinstance(prof.get("especializacoes"), list):
        prof_context["especializacoes"] = [str(x).strip().lower() for x in prof["especializacoes"] if x]
    else:
        for key in ("especializacao1", "especializacao2"):
            v = prof.get(key)
            if v:
                prof_context["especializacoes"].append(str(v).strip().lower())

    custom_aliases = {}
    doc_aliases = _get_doc_safe(f"profissionais/{uid}/aliases")
    if isinstance(doc_aliases, dict) and doc_aliases:
        custom_aliases = doc_aliases
    elif isinstance(prof.get("aliases"), dict):
        custom_aliases = prof["aliases"]
    prof_context["aliases"] = custom_aliases
    return prof_context


def _profession_synonyms(profissao: str, especializacoes: List[str]) -> Dict[str, List[str]]:
    p = (profissao or "").lower()
    espec = set((especializacoes or []))
    base: Dict[str, List[str]] = {}

    # Barbeiro / cabeleireiro
    if "barbeiro" in p or "cabele" in p:
        base.update(
            {
                "corte": ["corte masculino", "corte feminino", "corte"],
                "barba": ["barba"],
                "sombra": ["sobrancelha", "design de sobrancelha", "sobrancelha masculina"],
                "baixar a melena": ["corte masculino"],
                "pezinho": ["acabamento", "pezinho"],
                "tintura": ["coloração", "tintura"],
            }
        )

    # Dentista
    if "dent" in p:
        base.update(
            {
                "limpeza": ["profilaxia", "limpeza"],
                "clareamento": ["clareamento dental", "clareamento"],
                "canal": ["tratamento de canal", "endodontia"],
                "aparelho": ["ortodontia", "avaliação ortodôntica"],
                "restauração": ["restauração", "resina"],
            }
        )

    # Pet (banho e tosa)
    if "pet" in p or "tosa" in p or "banho" in p:
        base.update(
            {
                "banho": ["banho"],
                "tosa": ["tosa", "tosa higiênica", "tosa completa"],
                "unha": ["corte de unha", "unha"],
                "higiene": ["higienização", "limpeza"],
            }
        )

    # Advogado
    if "advog" in p or "direito" in p:
        base.update(
            {
                "consulta": ["consulta", "consulta jurídica"],
                "contrato": ["revisão de contrato", "elaboração de contrato"],
                "trabalhista": ["consulta trabalhista"],
                "civil": ["consulta cível"],
            }
        )

    # Artesão / designer
    if "artes" in p or "artesã" in p or "designer" in p:
        base.update(
            {
                "personalizado": ["produto personalizado", "sob medida"],
                "aula": ["aula", "mentoria criativa"],
                "reparo": ["conserto", "reparo"],
            }
        )

    if "barba" in espec:
        base.setdefault("barba", ["barba"])
    if "clareamento" in espec:
        base.setdefault("clareamento", ["clareamento"])
    return base

# ========== Preços (agregador 3 fontes) ==========
def _normalize_item(it: Dict[str, Any]) -> Dict[str, Any]:
    """Padroniza campos nome, preco, duracaoMin e mantém extras."""
    nome = it.get("nome") or it.get("nomeLower") or it.get("_id") or "serviço"
    preco = it.get("preco", it.get("valor"))
    dur = it.get("duracaoMin", it.get("duracaoPadraoMin", it.get("duracao")))
    ativo = it.get("ativo", True)
    out = {**it}
    out["nome"] = str(nome)
    out["preco"] = preco
    if dur is not None:
        out["duracaoMin"] = dur
    out["ativo"] = ativo
    out["nomeLower"] = _strip_accents_lower(out["nome"])
    # Mantém slug se vier de produtosEServicos
    if "slug" in it and isinstance(it["slug"], str):
        out["slug"] = it["slug"].strip().lower()
    return out


def _load_prices(uid: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    # (A) Doc principal → campo 'precos'
    prof = _get_doc_safe(f"profissionais/{uid}") or {}
    precos = prof.get("precos")
    if isinstance(precos, dict):
        if "itens" in precos and isinstance(precos["itens"], list):
            for it in precos["itens"]:
                if not isinstance(it, dict):
                    continue
                if it.get("ativo", True):
                    items.append(_normalize_item(it))
        else:
            for nome, valor in precos.items():
                items.append(_normalize_item({"nome": nome, "preco": valor, "ativo": True}))

    # (B) Coleção /precos
    try:
        for it in _list_collection_safe(f"profissionais/{uid}/precos", limit=500):
            if it.get("ativo", True):
                items.append(_normalize_item(it))
    except Exception as e:
        logging.info("[PRICES] erro lendo /precos: %s", e)

    # (C) Coleção /produtosEServicos
    try:
        for it in _list_collection_safe(f"profissionais/{uid}/produtosEServicos", limit=500):
            if it.get("ativo", True):
                items.append(_normalize_item(it))
    except Exception as e:
        logging.info("[PRICES] erro lendo /produtosEServicos: %s", e)

    # Dedup por nomeLower (primeiro ganha)
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for it in items:
        key = it.get("nomeLower", "").strip()
        if not key or it.get("ativo") is False:
            continue
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    return uniq


def _render_price_table(items: List[Dict[str, Any]], uid: str, debug_counts: Dict[str, int]) -> str:
    if not items:
        return "Ainda não tenho uma tabela de preços publicada. 🙏"
    lines = [ say(uid, "price_table_header") ]
    for it in items[:20]:
        nome = it.get("nome", "serviço")
        dur = it.get("duracaoMin") or "?"
        val = it.get("preco") if it.get("preco") not in (None, "") else "?"
        lines.append(f"• {nome} — {dur}min — {_format_brl(val)}")
    return "\n".join(lines)


def _count_sources(uid: str) -> Dict[str, int]:
    c = {"map": 0, "precos": 0, "ps": 0}
    prof = _get_doc_safe(f"profissionais/{uid}") or {}
    precos = prof.get("precos")
    if isinstance(precos, dict):
        if "itens" in precos and isinstance(precos["itens"], list):
            c["map"] = len(precos["itens"])
        else:
            c["map"] = len(precos)
    try:
        c["precos"] = len(_list_collection_safe(f"profissionais/{uid}/precos", limit=500))
    except Exception:
        pass
    try:
        c["ps"] = len(_list_collection_safe(f"profissionais/{uid}/produtosEServicos", limit=500))
    except Exception:
        pass
    return c


def _match_by_synonyms(text: str, items: List[Dict[str, Any]], prof_ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    t = _strip_accents_lower(text)
    aliases_map: Dict[str, str] = prof_ctx.get("aliases") or {}
    for alias, target in aliases_map.items():
        if _strip_accents_lower(alias) in t:
            target_norm = _strip_accents_lower(str(target))
            for it in items:
                if target_norm and target_norm in it.get("nomeLower", ""):
                    return it

    syn = _profession_synonyms(prof_ctx.get("profissao", ""), prof_ctx.get("especializacoes") or [])
    for alias, candidates in syn.items():
        if _strip_accents_lower(alias) in t:
            for cand in candidates:
                cand_norm = _strip_accents_lower(cand)
                for it in items:
                    if cand_norm in it.get("nomeLower", ""):
                        return it
    return None


def _find_price_item(items: List[Dict[str, Any]], text: str, prof_ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    hit = _match_by_synonyms(text, items, prof_ctx)
    if hit:
        return hit

    t = _strip_accents_lower(text)
    for it in items:
        nome = it.get("nomeLower", "")
        if not nome:
            continue
        for tok in re.findall(r"[a-z0-9]{4,}", nome):
            if tok in t:
                return it

    for key in ("corte", "barba", "banho", "tosa", "limpeza", "clareamento", "consulta", "contrato"):
        if key in t:
            for it in items:
                if key in it.get("nomeLower", ""):
                    return it
    return None


# ========== FAQ ==========
def _load_faq(uid: str, key: str) -> Optional[str]:
    doc = _get_doc_safe(f"profissionais/{uid}/faq/{key}")
    if not doc:
        return None
    if isinstance(doc.get("variacoes"), list) and doc["variacoes"]:
        idx = (datetime.now(SP_TZ).timetuple().tm_yday) % len(doc["variacoes"])
        return str(doc["variacoes"][idx])
    return doc.get("texto")


# ========== STT ==========
def stt_transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg", language: str = "pt-BR") -> str:
    try:
        import inspect
        import services.audio_processing as ap

        for name in [
            "transcribe_audio_bytes",
            "transcribe_audio",
            "stt_transcribe",
            "speech_to_text",
            "stt_bytes",
            "transcrever_audio_bytes",
            "transcrever_audio",
        ]:
            f = getattr(ap, name, None)
            if not callable(f):
                continue
            try:
                try:
                    text = f(audio_bytes, mime_type=mime_type, language=language)
                except TypeError:
                    try:
                        text = f(audio_bytes, language=language)
                    except TypeError:
                        try:
                            text = f(audio_bytes)
                        except TypeError:
                            sig = inspect.signature(f)
                            kwargs = {}
                            if "mime_type" in sig.parameters:
                                kwargs["mime_type"] = mime_type
                            if "language" in sig.parameters:
                                kwargs["language"] = language
                            text = f(audio_bytes, **kwargs)
                text = (text or "").strip()
                if text:
                    print(f"[STT] services.audio_processing.{name}='{text[:120]}'", flush=True)
                    return text
            except Exception as e:
                print(f"[STT] {name} falhou: {e}", flush=True)
    except Exception as e:
        print(f"[STT] módulo services.audio_processing indisponível: {e}", flush=True)

    # Fallback opcional (desligado por padrão) para Whisper/OpenAI
    try:
        if os.getenv("ENABLE_STT_OPENAI", "false").lower() in ("1", "true", "yes"):
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key and audio_bytes:
                lang = "pt" if language.lower().startswith("pt") else language.split("-")[0]
                files = {"file": ("audio.ogg", audio_bytes, mime_type or "audio/ogg")}
                data = {"model": "whisper-1", "language": lang}
                headers = {"Authorization": f"Bearer {api_key}"}
                resp = requests.post(
                    "https://api.openai.com/v1/audio/transcriptions", headers=headers, files=files, data=data, timeout=60
                )
                js = {}
                try:
                    js = resp.json()
                except Exception:
                    pass
                text = (js.get("text") if isinstance(js, dict) else "") or ""
                text = text.strip()
                print(f"[STT] openai whisper status={resp.status_code} text='{text[:120]}'", flush=True)
                return text
    except Exception as e:
        print(f"[STT] openai whisper erro: {e}", flush=True)

    print("[STT] nenhum backend retornou transcrição", flush=True)
    return ""


## ========== TTS helper (responder em áudio quando fizer sentido) ==========
def tts_speak(uid: str, text: str, voice_hint: Optional[str] = None) -> Optional[Tuple[bytes, str]]:
    """
    Tenta sintetizar áudio a partir do texto.
    Retorna (audio_bytes, mime_type) ou None se indisponível.
    Preferência: providers.tts (ex.: ElevenLabs), depois services.text_to_speech (ex.: Google).
    """
    if not text:
        return None

    # 1) providers.tts (caminho usual p/ ElevenLabs clonado)
    try:
        import inspect
        import providers.tts as ptts  # type: ignore
        for name in ["speak_bytes", "synthesize_bytes", "tts_bytes", "tts", "speak"]:
            f = getattr(ptts, name, None)
            if not callable(f):
                continue
            try:
                try:
                    out = f(text=text, voice_id=voice_hint, mime_type="audio/ogg")
                except TypeError:
                    try:
                        out = f(text, voice_id=voice_hint)
                    except TypeError:
                        try:
                            out = f(text)
                        except TypeError:
                            sig = inspect.signature(f)
                            kwargs = {}
                            if "voice_id" in sig.parameters and voice_hint:
                                kwargs["voice_id"] = voice_hint
                            if "mime_type" in sig.parameters:
                                kwargs["mime_type"] = "audio/ogg"
                            out = f(text, **kwargs)
                if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], (bytes, bytearray)):
                    return (bytes(out[0]), str(out[1] or "audio/ogg"))
                if isinstance(out, (bytes, bytearray)):
                    return (bytes(out), "audio/ogg")
            except Exception as e:
                logging.info("[TTS/providers] %s falhou: %s", name, e)
    except Exception as e:
        logging.info("[TTS] providers.tts indisponível: %s", e)

    # 2) services.text_to_speech (ex.: Google TTS)
    try:
        import inspect
        import services.text_to_speech as tts  # type: ignore

        candidates = [
            "speak_bytes", "synthesize_bytes", "tts_bytes",
            "speak", "synthesize", "text_to_speech"
        ]
        for name in candidates:
            f = getattr(tts, name, None)
            if not callable(f):
                continue
            try:
                try:
                    out = f(text, uid=uid, voice=voice_hint, format="audio/ogg")
                except TypeError:
                    try:
                        out = f(text, voice=voice_hint)
                    except TypeError:
                        try:
                            out = f(text)
                        except TypeError:
                            sig = inspect.signature(f)
                            kwargs = {}
                            if "uid" in sig.parameters:
                                kwargs["uid"] = uid
                            if "voice" in sig.parameters and voice_hint:
                                kwargs["voice"] = voice_hint
                            if "format" in sig.parameters:
                                kwargs["format"] = "audio/ogg"
                            out = f(text, **kwargs)

                if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], (bytes, bytearray)):
                    return (bytes(out[0]), str(out[1] or "audio/ogg"))
                if isinstance(out, (bytes, bytearray)):
                    return (bytes(out), "audio/ogg")
            except Exception as e:
                logging.info("[TTS/services] %s falhou: %s", name, e)
    except Exception as e:
        logging.info("[TTS] services.text_to_speech indisponível: %s", e)

    return None



def _get_uid_voice_id(uid: str) -> Optional[str]:
    """
    Regra de produto (MEI Robô do usuário): só retorna voiceId se status == 'ready'.
    Fonte canônica: profissionais/{uid}.vozClonada. Retrocompat: configuracao/{uid}.vozClonada.
    """
    try:
        if not uid:
            return None
        from google.cloud import firestore as _fs  # type: ignore
        _db = _fs.Client()
        snap = _db.collection('profissionais').document(uid).get()
        d = snap.to_dict() or {}
        vc = d.get('vozClonada') or {}
        if isinstance(vc, dict) and vc.get('status') == 'ready' and vc.get('voiceId'):
            return str(vc.get('voiceId'))
        snap2 = _db.collection('configuracao').document(uid).get()
        d2 = snap2.to_dict() or {}
        vc2 = d2.get('vozClonada') or {}
        if isinstance(vc2, dict) and vc2.get('status') == 'ready' and vc2.get('voiceId'):
            return str(vc2.get('voiceId'))
        return None
    except Exception as e:
        logging.info('[voz] falha ao buscar voiceId do uid=%s: %s', uid, e)
        return None

def send_reply(uid: str, to: str, text: str, inbound_type: str, send_text_fn, send_audio_fn=None, voice_hint: Optional[str] = None):
    """
    Se o cliente mandou ÁUDIO e houver send_audio_fn + TTS ok -> responde em áudio.
    Caso contrário, texto.
    """
    # Sanitiza sempre ANTES de enviar (tira ids/hashes) usando humanizer
    try:
        text = H_sanitize(text or "")
    except Exception:
        text = (text or "").strip()

    # tenta usar a voz configurada do MEI (env) se não vier dica explícita
    # regra de produto: sem fallback para voz da plataforma; usa sempre a voz do próprio MEI
    if not voice_hint:
        voice_hint = _get_uid_voice_id(uid)
    prefer_audio = (inbound_type == "audio") and REPLY_AUDIO_WHEN_AUDIO and callable(send_audio_fn)
    if prefer_audio:
        if not voice_hint:
            msg = "Sua voz ainda não foi finalizada. Envie o áudio pelo WhatsApp e conclua o processamento da voz para ativar as respostas em áudio."
            return send_text_fn(to, msg)
        tts_out = tts_speak(uid, text, voice_hint=voice_hint)
        if tts_out:
            audio_bytes, mime_type = tts_out
            try:
                return send_audio_fn(to, audio_bytes, mime_type)
            except Exception as e:
                logging.info("[OUTBOUND][AUDIO] falhou, caindo para texto: %s", e)
    return send_text_fn(to, text)


# ========== Memória de contato (gancho) ==========

try:
    from domain.contact_memory import answer_from_contact as _cm_answer  # type: ignore
except Exception:
    _cm_answer = None  # type: ignore


def _contact_memory_answer(uid: str, wa_id_or_phone: str, text_in: str) -> Optional[str]:
    """
    Tenta responder usando a memória do contato (cliente individual).
    Se não houver domínio ou der erro, devolve None e deixa o fluxo seguir normal.
    """
    if not _cm_answer:
        return None

    pergunta = (text_in or "").strip()
    if not pergunta:
        return None

    try:
        # Tentativa 1: assinatura nomeada (mais amigável para o domínio)
        try:
            return _cm_answer(
                uid=uid,
                wa_id_or_phone=wa_id_or_phone,
                question=pergunta,
            )  # type: ignore[call-arg]
        except TypeError:
            # Tentativa 2: assinatura posicional (uid, wa_id, pergunta)
            try:
                return _cm_answer(uid, wa_id_or_phone, pergunta)  # type: ignore[misc]
            except TypeError:
                # Tentativa 3: assinatura reduzida (uid, pergunta)
                return _cm_answer(uid, pergunta)  # type: ignore[misc]
    except Exception as e:
        logging.info("[CONTACT_MEMORY] erro ao consultar memória de contato: %s", e)
        return None
        
# ========== Normalizador PT-BR (datas/horas) ==========
_MONTHS = {
    "jan": 1, "janeiro": 1,
    "fev": 2, "fevereiro": 2,
    "mar": 3, "marco": 3, "março": 3,
    "abr": 4, "abril": 4,
    "mai": 5, "maio": 5,
    "jun": 6, "junho": 6,
    "jul": 7, "julho": 7,
    "ago": 8, "agosto": 8,
    "set": 9, "setembro": 9,
    "out": 10, "outubro": 10,
    "nov": 11, "novembro": 11,
    "dez": 12, "dezembro": 12,
}
_UNITS = {
    "zero": 0, "um": 1, "uma": 1, "primeiro": 1,
    "dois": 2, "duas": 2, "tres": 3, "três": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12,
    "treze": 13, "catorze": 14, "quatorze": 14, "quinze": 15, "dezesseis": 16, "desesseis": 16,
    "dezessete": 17, "desessete": 17, "dezoito": 18, "dezenove": 19,
}
_TENS = {"vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50}
_WEEKDAYS = {
    "segunda": 0, "segunda-feira": 0,
    "terca": 1, "terça": 1, "terça-feira": 1, "terca-feira": 1,
    "quarta": 2, "quarta-feira": 2,
    "quinta": 3, "quinta-feira": 3,
    "sexta": 4, "sexta-feira": 4,
    "sabado": 5, "sábado": 5,
    "domingo": 6,
}


def _words_to_int_pt(s: str):
    if not s:
        return None
    s = s.strip()
    if s in _UNITS:
        return _UNITS[s]
    if s in _TENS:
        return _TENS[s]
    m = re.match(r"(vinte|trinta|quarenta|cinquenta)\s+e\s+([a-z]+)$", s)
    if m:
        tens = _TENS.get(m.group(1), 0)
        unit = _UNITS.get(m.group(2), 0)
        return tens + (unit or 0)
    return None


def _extract_day_month_from_words(t: str):
    m = re.search(r"(?:\bdia\s+)?(?P<d>(\d{1,2}|[a-z]+))\s+de\s+(?P<m>[a-z]{3,12})", t)
    if not m:
        return None
    d_raw = m.group("d")
    month_raw = m.group("m")
    mm = _MONTHS.get(month_raw)
    if not mm:
        return None
    if d_raw.isdigit():
        dd = int(d_raw)
    else:
        dd = _words_to_int_pt(d_raw)
    if not dd:
        return None
    return dd, mm


def _extract_time_from_words(t: str):
    if re.search(r"\bmeio\s+dia\b", t):
        mi = 30 if re.search(r"\bmeio\s+dia\s+e\s+meia\b", t) else 0
        return 12, mi
    if re.search(r"\bmeia\s+noite\b", t):
        mi = 30 if re.search(r"\bmeia\s+noite\s+e\s+meia\b", t) else 0
        return 0, mi
    period = None
    if re.search(r"\bda\s+manha\b|\bde\s+manha\b|\bmanh[ãa]\b", t):
        period = "manha"
    elif re.search(r"\bda\s+tarde\b|\bde\s+tarde\b|\btarde\b", t):
        period = "tarde"
    elif re.search(r"\bda\s+noite\b|\bde\s+noite\b|\bnoite\b", t):
        period = "noite"
    m = re.search(r"\b(?:as|às)?\s*(?P<h>\d{1,2})(?:[:h](?P<m>\d{2}))?\s*(?:horas?)?", t)
    if m:
        hh = int(m.group("h"))
        mi = int(m.group("m")) if m.group("m") else 0
        if re.search(rf"\b{hh}\s+e\s+meia\b", t):
            mi = 30
        if period in ("tarde", "noite") and 1 <= hh <= 11:
            hh += 12
        return hh, mi
    m2 = re.search(r"\b(?:as|às)?\s*([a-z]+)(?:\s*e\s*meia)?\s*(?:horas?)?", t)
    if m2:
        word = m2.group(1)
        hh = _words_to_int_pt(word)
        if hh is not None:
            mi = 30 if re.search(r"\b" + re.escape(word) + r"\s*e\s*meia\b", t) else 0
            if period in ("tarde", "noite") and 1 <= hh <= 11:
                hh += 12
            return hh, mi
    return None


def _weekday_to_date(next_text: str, weekday_word: str):
    if weekday_word not in _WEEKDAYS:
        return None
    today = datetime.now(SP_TZ).date()
    wd_target = _WEEKDAYS[weekday_word]
    wd_today = today.weekday()
    delta = (wd_target - wd_today) % 7
    if delta == 0:
        delta = 7
    if re.search(r"\bproxim[aoa]|\bsemana\s+que\s+vem", next_text):
        delta += 7
    return today + timedelta(days=delta)


def _normalize_datetime_pt(t: str) -> str:
    if re.search(r"\b\d{1,2}[\/\.]\d{1,2}\b", t) and re.search(r"\b\d{1,2}[:h]\d{2}\b", t):
        return t
    base_now = datetime.now(SP_TZ)
    dd = mm = None
    if "depois de amanha" in t:
        base = base_now + timedelta(days=2)
        dd, mm = base.day, base.month
    elif "amanha" in t:
        base = base_now + timedelta(days=1)
        dd, mm = base.day, base.month
    if dd is None:
        for w in sorted(_WEEKDAYS.keys(), key=len, reverse=True):
            if re.search(rf"\b{re.escape(w)}\b", t):
                d = _weekday_to_date(t, w)
                if d:
                    dd, mm = d.day, d.month
                    break
    dm = _extract_day_month_from_words(t)
    if dd is None and dm:
        dd, mm = dm
    ht = _extract_time_from_words(t)
    if dd and mm and ht:
        hh, mi = ht
        return f"{t} {dd:02d}/{mm:02d} {hh:02d}:{mi:02d}"
    return t


def _parse_datetime_br(text_norm: str):
    d = re.search(r"(\b\d{1,2})[\/\.-](\d{1,2})(?:[\/\.-](\d{2,4}))?", text_norm)
    h = re.search(r"(\b\d{1,2})[:h](\d{2})", text_norm)
    if not d or not h:
        return None
    day = int(d.group(1))
    month = int(d.group(2))
    year_g = d.group(3)
    year = int(year_g) + (2000 if year_g and len(year_g) == 2 else 0) if year_g else datetime.now(SP_TZ).year
    hour = int(h.group(1))
    minute = int(h.group(2))
    try:
        return datetime(year, month, day, hour, minute, tzinfo=SP_TZ)
    except Exception:
        return None


# ========== Sessão (Firestore) ==========

def _sess_ref(uid: str, wa_id_or_phone: str):
    """Armazena sessão por CHAVE DE EQUIVALÊNCIA (robusto com/sem 9)."""
    key = br_equivalence_key(wa_id_or_phone or "")
    return DB.collection(f"profissionais/{uid}/sessions").document(key) if _db_ready() else None


def _get_session(uid: str, wa_id_or_phone: str) -> dict:
    if not _db_ready():
        return {}
    try:
        ref = _sess_ref(uid, wa_id_or_phone)
        if ref is None:
            return {}
        snap = ref.get()
        sess = snap.to_dict() if snap.exists else {}
    except Exception as e:
        print(f"[WA_BOT][SESS] get erro: {e}", flush=True)
        sess = {}
    try:
        ts_str = sess.get("updatedAt") or sess.get("createdAt")
        if ts_str:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if datetime.now(SP_TZ) - ts > timedelta(minutes=30):
                _clear_session(uid, wa_id_or_phone)
                return {}
    except Exception:
        pass
    return sess or {}


def _save_session(uid: str, wa_id_or_phone: str, sess: dict):
    if not _db_ready():
        return
    now = datetime.now(SP_TZ).isoformat()
    sess = {**(sess or {}), "updatedAt": now}
    if "createdAt" not in sess:
        sess["createdAt"] = now
    sess["waKey"] = br_equivalence_key(wa_id_or_phone or "")
    try:
        ref = _sess_ref(uid, wa_id_or_phone)
        if ref is not None:
            ref.set(sess)
    except Exception as e:
        print(f"[WA_BOT][SESS] save erro: {e}", flush=True)


def _clear_session(uid: str, wa_id_or_phone: str):
    if not _db_ready():
        return
    try:
        ref = _sess_ref(uid, wa_id_or_phone)
        if ref is not None:
            ref.delete()
    except Exception as e:
        print(f"[WA_BOT][SESS] clear erro: {e}", flush=True)


# ---- NOVO: lembrar o último serviço citado (para agendar depois só com data/hora)
def _remember_last_service(uid: str, wa_id_or_phone: str, it: dict):
    """Guarda na sessão o último serviço citado (ex.: após pergunta de preço)."""
    if not it or not wa_id_or_phone:
        return
    try:
        sess = _get_session(uid, wa_id_or_phone) or {}
        sess["lastServiceId"] = it.get("id")
        sess["lastServiceName"] = (it.get("nomeLower") or it.get("nome") or "").lower()
        _save_session(uid, wa_id_or_phone, sess)
    except Exception as e:
        print(f"[SESS][remember_last_service] erro: {e}", flush=True)


# ========== Agendamento ==========

def _resolve_cliente_id(uid_default: str, wa_id_raw: str, to_msisdn: str) -> str:
    """
    Resolve clienteId tentando em ordem:
      1) profissionais/{uid}/clientes where waKey == eq_key
      2) where waId == wa_id_raw
      3) where telefone == each candidate (com/sem 9)
    """
    eq_key = br_equivalence_key(wa_id_raw or to_msisdn or "")
    cands = []
    try:
        cands = br_candidates(to_msisdn or wa_id_raw or "")
    except Exception:
        pass
    if not cands:
        norm = _normalize_br_msisdn(to_msisdn or wa_id_raw or "")
        if norm:
            cands = [norm]

    try:
        if _db_ready():
            # 1) waKey
            q = (
                DB.collection(f"profissionais/{uid_default}/clientes")
                .where("waKey", "==", eq_key)
                .limit(1)
                .stream()
            )
            for d in q:
                return d.id
    except Exception as e:
        print(f"[WA_BOT][AGENDA] lookup cliente por waKey falhou: {e}", flush=True)

    try:
        if _db_ready() and wa_id_raw:
            # 2) waId exato
            q = (
                DB.collection(f"profissionais/{uid_default}/clientes")
                .where("waId", "==", wa_id_raw)
                .limit(1)
                .stream()
            )
            for d in q:
                return d.id
    except Exception as e:
        print(f"[WA_BOT][AGENDA] lookup cliente por waId falhou: {e}", flush=True)

    # 3) telefone (tentando cada candidato)
    try:
        if _db_ready():
            for cand in cands:
                q = (
                    DB.collection(f"profissionais/{uid_default}/clientes")
                    .where("telefone", "==", cand)
                    .limit(1)
                    .stream()
                )
                for d in q:
                    return d.id
    except Exception as e:
        print(f"[WA_BOT][AGENDA] lookup cliente por telefone falhou: {e}", flush=True)

    return wa_id_raw or to_msisdn or "anon"


def _find_target_agendamento(uid: str, cliente_id: str, wa_id_raw: str, telefone: str):
    """
    Procura agendamento ativo do cliente tentando:
      - clienteId
      - clienteWaKey (eq_key)
      - clienteWaId
      - telefone (para cada candidato)
    """
    if not _db_ready():
        return None
    estados = ["solicitado", "confirmado"]
    candidatos = []

    def _iso_or_none(s):
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    try:
        q = (
            DB.collection(f"profissionais/{uid}/agendamentos")
            .where("clienteId", "==", cliente_id)
            .where("estado", "in", estados)
            .limit(10)
            .stream()
        )
        for d in q:
            obj = d.to_dict() or {}
            obj["_id"] = d.id
            candidatos.append(obj)
    except Exception as e:
        print(f"[WA_BOT][AGENDA] query por clienteId falhou: {e}", flush=True)

    if not candidatos:
        try:
            eq_key = br_equivalence_key(wa_id_raw or telefone or "")
            q = (
                DB.collection(f"profissionais/{uid}/agendamentos")
                .where("clienteWaKey", "==", eq_key)
                .where("estado", "in", estados)
                .limit(10)
                .stream()
            )
            for d in q:
                obj = d.to_dict() or {}
                obj["_id"] = d.id
                candidatos.append(obj)
        except Exception as e:
            print(f"[WA_BOT][AGENDA] query por clienteWaKey falhou: {e}", flush=True)

    if not candidatos and wa_id_raw:
        try:
            q = (
                DB.collection(f"profissionais/{uid}/agendamentos")
                .where("clienteWaId", "==", wa_id_raw)
                .where("estado", "in", estados)
                .limit(10)
                .stream()
            )
            for d in q:
                obj = d.to_dict() or {}
                obj["_id"] = d.id
                candidatos.append(obj)
        except Exception as e:
            print(f"[WA_BOT][AGENDA] query por clienteWaId falhou: {e}", flush=True)

    if not candidatos and telefone:
        try:
            cands = []
            try:
                cands = br_candidates(telefone)
            except Exception:
                pass
            if not cands:
                cands = [_normalize_br_msisdn(telefone)]
            for cand in cands:
                q = (
                    DB.collection(f"profissionais/{uid}/agendamentos")
                    .where("telefone", "==", cand)
                    .where("estado", "in", estados)
                    .limit(10)
                    .stream()
                )
                for d in q:
                    obj = d.to_dict() or {}
                    obj["_id"] = d.id
                    candidatos.append(obj)
                if candidatos:
                    break
        except Exception as e:
            print(f"[WA_BOT][AGENDA] query por telefone falhou: {e}", flush=True)

    if not candidatos:
        return None

    candidatos.sort(
        key=lambda x: _iso_or_none(x.get("createdAt") or x.get("inicio")) or datetime.min.replace(tzinfo=SP_TZ),
        reverse=True,
    )
    return candidatos[0]


def _build_and_save_agendamento(uid_default: str, value: dict, to_msisdn: str, svc: dict, dt: datetime, body_text: str, channel_mode: str = "text"):
    wa_id = ""
    nome_contato = ""
    try:
        contacts = value.get("contacts") or []
        if contacts and isinstance(contacts, list):
            wa_id = contacts[0].get("wa_id") or ""
            prof = contacts[0].get("profile") or {}
            nome_contato = prof.get("name") or ""
    except Exception:
        pass

    dur = int(svc.get("duracaoMin") or 60)
    fim = dt + timedelta(minutes=dur)
    servico_id = svc.get("id") or f"map:{(svc.get('nomeLower') or svc.get('nome') or 'servico').strip().lower()}"
    cliente_id = _resolve_cliente_id(uid_default, wa_id, to_msisdn)

    ag = {
        "estado": "solicitado",
        "canal": "whatsapp",
        "clienteId": cliente_id,
        "clienteWaId": wa_id,
        "clienteNome": nome_contato,
        "telefone": to_msisdn,
        "servicoId": servico_id,
        "servicoNome": svc.get("nome") or svc.get("nomeLower"),
        "duracaoMin": dur,
        "preco": svc.get("preco"),
        "dataHora": dt.isoformat(),
        "inicio": dt.isoformat(),
        "fim": fim.isoformat(),
        "observacoes": (body_text or "")[:500],
        "createdAt": datetime.now(SP_TZ).isoformat(),
    }

    saved_id = None

    # 1) Valida e tenta salvar via scheduler externo (se existir)
    try:
        ok, motivo, _ = validar_agendamento_v1(uid_default, ag)
        if not ok:
            return False, f"Não foi possível agendar: {motivo}"
        saved_id = salvar_agendamento(uid_default, ag)
        if isinstance(saved_id, dict):
            saved_id = saved_id.get("id") or saved_id.get("ag_id")
    except Exception as e:
        print(f"[WA_BOT][AGENDA] salvar via schedule falhou: {e}", flush=True)
        saved_id = None  # força fallback de persistência

    # 2) Fallback/garantia de persistência no Firestore quando id vier faltando ou "fake"
    try:
        need_fallback = (not saved_id) or (str(saved_id).strip().lower() in ("fake", "dummy", "test"))
        if need_fallback:
            if not _db_ready():
                raise RuntimeError("DB indisponível")
            ref = DB.collection(f"profissionais/{uid_default}/agendamentos").document()
            ag["createdAt"] = datetime.now(SP_TZ).isoformat()
            ref.set(ag)
            saved_id = ref.id
    except Exception as e2:
        print(f"[WA_BOT][AGENDA][FALLBACK_SAVE] erro: {e2}", flush=True)
        return False, "Tive um problema ao salvar seu agendamento. Pode tentar novamente em instantes?"

    # 3) Mensagem de confirmação (humanizada; sem ID)
    dia = dt.strftime("%d/%m")
    hora = dt.strftime("%H:%M")

    if humanize_on():
        payload = {
            "servico": ag.get("servicoNome") or "serviço",
            "data": dt.strftime("%Y-%m-%d"),
            "data_str": dia,
            "hora": hora,
        }
        msg = H("confirm_agenda", payload, mode=("audio" if channel_mode == "audio" else "text"))
    else:
        preco = ag.get("preco")
        preco_txt = f" — {_format_brl(preco)}" if preco not in (None, "", "?") else ""
        msg = f"Prontinho! Agendei {ag['servicoNome']} para {dia} às {hora}{preco_txt}. Se precisar alterar, é só me chamar. 😉"

    return True, msg

# ========== Fluxos de alto nível ==========
def _reply_prices(uid: str, to: str, send_text, channel_mode: str = "text"):
    counts = _count_sources(uid)
    items = _load_prices(uid)
    if humanize_on():
        itens = [{"nome": it.get("nome","serviço"), "duracaoMin": it.get("duracaoMin"), "preco": it.get("preco")} for it in items]
        msg = H("prices", {"itens": itens, "raw": _render_price_table(items, uid, counts)}, mode=("audio" if channel_mode=="audio" else "text"))
    else:
        msg = _render_price_table(items, uid, counts)
    logging.info(
        f"[WHATSAPP][OUTBOUND] prices count={len(items)} map={counts.get('map')} precos={counts.get('precos')} ps={counts.get('ps')}"
    )
    return send_text(to, msg)


def _reply_price_from_cache_or_data(uid: str, to: str, user_text: str, send_text, channel_mode: str = "text"):
    key = _mk_price_cache_key(uid, user_text)
    if channel_mode != "audio":
        cached = kv_get(uid, key)
        if cached:
            logging.info("[CACHE] price hit")
            return send_text(to, cached)

    items = _load_prices(uid)
    prof_ctx = _load_prof_context(uid)
    it = _find_price_item(items, user_text or "", prof_ctx)

    if not it:
        return _reply_prices(uid, to, send_text, channel_mode=channel_mode)

    # >>> Memoriza o serviço identificado (para agendar depois)
    try:
        _remember_last_service(uid, to, it)
    except Exception:
        pass

    nome = it.get("nome") or "serviço"
    valor_legacy = it.get("preco")
    slug = (it.get("slug") or "").strip().lower()

    valor_final = valor_legacy
    origem_txt = None

    # Se habilitado, tenta calcular via domain.pricing.get_price(slug)
    if PRICING_MODE == "domain" and domain_get_price and slug:
        try:
            res = domain_get_price(slug)  # contrato: {valor, origem}
            if isinstance(res, dict) and ("valor" in res):
                valor_final = res.get("valor", valor_legacy)
                origem_txt = res.get("origem")
        except Exception as e:
            logging.info("[PRICING][domain] falhou (%s). Usando legacy.", e)

    if valor_final in (None, "", "?"):
        # fallback para tabela completa se não houver valor
        return _reply_prices(uid, to, send_text, channel_mode=channel_mode)

    extra = f" 『{origem_txt}』" if origem_txt else ""
    base_msg = f"{nome}: {_format_brl(valor_final)} 😉{extra}"
    # Se humanizer estiver ativo, ao menos sanitizamos a saída
    msg = H_sanitize(base_msg)

    # Cacheia apenas versão texto
    if channel_mode != "audio":
        kv_put(uid, key, msg, ttl_sec=PRICE_CACHE_TTL)

    return send_text(to, msg)


def _build_budget_message(uid: str, itens: List[Dict[str, Any]], *, observacao: str | None = None) -> str:
    """
    Monta um orçamento em texto puro (para WhatsApp) a partir de itens de preço.
    Cada item deve ter pelo menos: nome, preco, duracaoMin (opcional).
    """
    if not itens:
        return "Ainda não consegui montar um orçamento com base no que você pediu. Pode me dizer o serviço com um pouco mais de detalhe?"

    linhas = []
    total = 0.0

    linhas.append("Orçamento solicitado:\n")

    for idx, it in enumerate(itens, start=1):
        nome = it.get("nome") or "serviço"
        dur = it.get("duracaoMin")
        preco = it.get("preco")
        try:
            v = float(preco)
        except Exception:
            v = 0.0

        total += v
        dur_txt = f" — {int(dur)}min" if dur not in (None, "", "?") else ""
        linhas.append(f"{idx}. {nome}{dur_txt} — {_format_brl(preco)}")

    linhas.append("")
    linhas.append(f"Total: {_format_brl(total)}")

    if observacao:
        obs_clean = (observacao or "").strip()
        if obs_clean:
            linhas.append("")
            linhas.append(f"Obs.: {obs_clean[:240]}")

    linhas.append("")
    linhas.append("Esse é um orçamento, sujeito a confirmação de agenda e disponibilidade. Se quiser, já posso te ajudar a agendar. 😉")

    msg = "\n".join(linhas)
    # Sanitiza antes de enviar, para não vazar nada estranho
    try:
        return H_sanitize(msg)
    except Exception:
        return msg


def _register_budget_from_bot(
    uid_default: str,
    to_msisdn: str,
    value: dict,
    itens: List[Dict[str, Any]],
    *,
    observacao: str | None = None,
) -> None:
    """
    Registra o orçamento gerado pelo bot na mesma coleção/formato
    do blueprint oficial de orçamentos (routes/orcamentos.py):

      profissionais/{uid}/orcamentos/{orcId}

    Campos principais compatíveis:
      - numero, origem, createdAt, total, moeda
      - clienteNome, clienteTelefone, clienteTipo
      - itens[ {codigo, nome, preco, qtd, duracaoMin} ]
      - canalEnvio, status
    """
    if not _db_ready():
        logging.info("[ORCAMENTO][BOT] DB indisponível; orçamento não registrado.")
        return

    try:
        # 1) Dados mínimos do cliente (nome/telefone) a partir do payload Meta
        cliente_nome = ""
        try:
            contacts = value.get("contacts") or []
            if contacts and isinstance(contacts, list):
                prof = contacts[0].get("profile") or {}
                cliente_nome = (prof.get("name") or "").strip()
        except Exception:
            pass

        tel_norm = _normalize_br_msisdn(to_msisdn or "")
        obs_txt = (observacao or "").strip()

        # 2) Normaliza itens no formato esperado pelo blueprint
        norm_itens: List[Dict[str, Any]] = []
        total = 0.0

        for it in (itens or []):
            if not isinstance(it, dict):
                continue

            nome = (it.get("nome") or "serviço").strip()
            preco_raw = it.get("preco")

            try:
                preco_val = float(preco_raw)
            except Exception:
                preco_val = 0.0

            norm = {
                "codigo": (it.get("codigo") or "").strip(),
                "nome": nome,
                "preco": preco_val,
                "qtd": 1.0,  # por enquanto o bot sempre considera 1 unidade
                "duracaoMin": 0.0,
            }
            try:
                if it.get("duracaoMin") not in (None, "", "?"):
                    norm["duracaoMin"] = float(it.get("duracaoMin"))
            except Exception:
                pass

            norm_itens.append(norm)
            total += preco_val * norm["qtd"]

        # 3) Campos canônicos de orçamentos
        created_at = datetime.now(timezone.utc).isoformat()

        # Mesmo padrão do blueprint: ORC-YYYY-XXXXX
        ano = datetime.now().year
        seq = random.randint(10000, 99999)
        numero = f"ORC-{ano}-{seq:05d}"

        doc = {
            "numero": numero,
            "origem": "bot",
            "createdAt": created_at,
            "total": total,
            "moeda": "BRL",
            "clienteId": None,
            "clienteTipo": "",
            "clienteNome": cliente_nome,
            "clienteContato": "",
            "clienteTelefone": tel_norm,
            "clienteEmail": "",
            "clienteObs": obs_txt,
            "cliente": {
                "tipo": "",
                "nome": cliente_nome,
                "contato": "",
                "telefone": tel_norm,
                "email": "",
                "obs": obs_txt,
            },
            "itens": norm_itens,
            "mensagemEnvio": "",
            "infoAdicionais": "",
            "canalEnvio": "whatsapp",
            "status": "enviado",
        }

        col = DB.collection(f"profissionais/{uid_default}/orcamentos")
        ref = col.document()
        ref.set(doc, merge=False)

        logging.info(
            "[ORCAMENTO][BOT] registrado id=%s numero=%s total=%s",
            ref.id,
            numero,
            total,
        )
    except Exception as e:
        logging.exception("[ORCAMENTO][BOT] falhou ao registrar: %s", e)


def _reply_budget(
    uid: str,
    to: str,
    user_text: str,
    send_text,
    value: dict,
    *,
    channel_mode: str = "text",
) -> None:
    """
    Fluxo de orçamento:
      - Usa a mesma base de preços do robô
      - Tenta achar 1..N serviços mencionados
      - Monta texto de orçamento
      - Registra o orçamento para digest/e-mail do MEI
    """
    items = _load_prices(uid)
    if not items:
        msg = "Ainda não tenho uma tabela de preços cadastrada para montar um orçamento. Assim que você cadastrar seus serviços e valores, posso fazer isso por aqui."
        send_text(to, msg)
        return

    prof_ctx = _load_prof_context(uid)
    text_norm = _strip_accents_lower(user_text or "")

    # 1) Tenta achar um serviço principal, como já fazemos em _find_price_item
    principal = _find_price_item(items, user_text or "", prof_ctx)

    selected: List[Dict[str, Any]] = []
    if principal:
        selected.append(principal)

    # 2) Se o texto citar mais serviços (“corte e barba”, “banho e tosa”), tenta achar mais itens
    #    de forma simples, sem travar o fluxo.
    for it in items:
        if it in selected:
            continue
        nome = it.get("nomeLower") or ""
        if not nome:
            continue
        # Heurística leve: se pelo menos um token do nome aparece no texto, inclui
        for tok in re.findall(r"[a-z0-9]{4,}", nome):
            if tok in text_norm:
                selected.append(it)
                break

    # Se mesmo assim não tiver nada, cai para um orçamento “genérico” (primeiro item)
    if not selected and items:
        selected.append(items[0])

    observacao = user_text

    # Monta mensagem de orçamento
    msg = _build_budget_message(uid, selected, observacao=observacao)

    # Envia (respeitando TTS/áudio quando vier áudio)
    send_text(to, msg)

    # Registra no backend (coleção orçamentos ou módulo oficial, via stub)
    try:
        _register_budget_from_bot(uid, to, value, selected, observacao=observacao)
    except Exception as e:
        logging.info("[ORCAMENTO][BOT] falha não-crítica ao registrar: %s", e)


def _reply_faq(uid: str, to: str, faq_key: str, send_text, channel_mode: str = "text"):
    ans = _load_faq(uid, faq_key)
    msg = ans if ans else say(uid, "faq_default")
    if humanize_on() and faq_key in ("endereco","horarios","telefone","pix"):
        # por ora, só sanitiza; variações de FAQ podem vir depois
        msg = H("help", {"raw": msg}, mode=("audio" if channel_mode=="audio" else "text"))
    return send_text(to, msg)


def _reply_schedule(uid: str, to: str, serviceName: Optional[str], dateText: str, timeText: str, send_text, value: dict, body_text: str, channel_mode: str = "text"):
    ok, reason = can_book(dateText, timeText)
    if not ok:
        return send_text(to, f"Não consegui agendar: {reason}")
    items = _load_prices(uid)
    svc = None
    if serviceName:
        s_norm = _strip_accents_lower(serviceName)
        for it in items:
            if s_norm in it.get("nomeLower", ""):
                svc = it
                break
    if not svc and items:
        svc = items[0]
    dt = None
    try:
        dd, mm = [int(x) for x in re.findall(r"\d{1,2}", dateText)[:2]]
        hh, mi = [int(x) for x in re.findall(r"\d{1,2}", timeText)[:2]]
        dt = datetime(datetime.now(SP_TZ).year, mm, dd, hh, mi, tzinfo=SP_TZ)
    except Exception:
        pass
    if not dt:
        return send_text(to, "Não entendi a data/hora. Pode enviar no formato 01/09 14:00?")
    ok2, msg = _build_and_save_agendamento(uid, value, to, svc or {"nome": "serviço"}, dt, body_text, channel_mode=channel_mode)
    return send_text(to, msg if ok2 else f"Não consegui agendar: {msg}")


def _agendar_fluxo(value: dict, to_msisdn: str, uid_default: str, app_tag: str, body_text: str, text_norm: str, items, sess: dict, wa_id_raw: str, channel_mode: str = "text"):
    svc = None
    if sess.get("servicoId") or sess.get("servicoNome"):
        for it in items:
            if it.get("id") == sess.get("servicoId") or it.get("nomeLower") == (sess.get("servicoNome") or "").lower():
                svc = it
                break
    if not svc:
        prof_ctx = _load_prof_context(uid_default)
        hit = _find_price_item(items, text_norm, prof_ctx)
        if hit:
            name = _strip_accents_lower(hit.get("nome", ""))
            for it in items:
                if it.get("nomeLower") == name:
                    svc = it
                    break

    # >>> Tenta usar o último serviço lembrado na sessão
    if not svc and sess.get("lastServiceName"):
        last_name = (sess.get("lastServiceName") or "").lower()
        for it in items:
            if it.get("nomeLower") == last_name or (last_name and last_name in it.get("nomeLower", "")):
                svc = it
                break

    text_norm2 = _normalize_datetime_pt(text_norm)
    dt = _parse_datetime_br(text_norm2)
    if not dt and sess.get("dataHora"):
        try:
            dt = datetime.fromisoformat(sess["dataHora"])
        except Exception:
            dt = None

    have_svc = svc is not None
    have_dt = dt is not None

    # >>> Se já temos data/hora mas não serviço, aplica um default seguro
    if have_dt and not have_svc and items:
        svc = items[0]
        have_svc = True

    if have_svc and have_dt:
        # >>> Regras de agenda antes de salvar
        ok_book, reason = can_book(dt.strftime("%d/%m"), dt.strftime("%H:%M"))
        if not ok_book:
            return f"Não consegui agendar: {reason}"
        ok, msg = _build_and_save_agendamento(uid_default, value, to_msisdn, svc, dt, body_text, channel_mode=channel_mode)
        if ok:
            _clear_session(uid_default, wa_id_raw)
        return msg

    new_sess = {
        "intent": "agendar",
        "servicoId": svc.get("id") if svc else None,
        "servicoNome": (svc.get("nomeLower") or svc.get("nome")) if svc else None,
        "dataHora": dt.isoformat() if dt else None,
        "waKey": br_equivalence_key(wa_id_raw or to_msisdn or ""),
    }
    _save_session(uid_default, wa_id_raw, new_sess)

    if not have_svc and not have_dt:
        nomes = ", ".join([it.get("nome") for it in items[:5]]) or "o serviço"
        return f"Vamos agendar! Qual serviço você quer ({nomes}...) e para quando? Ex.: 01/09 14:00"
    if not have_svc:
        nomes = ", ".join([it.get("nome") for it in items[:5]]) or "o serviço"
        return f"Certo. Para qual serviço? Tenho: {nomes}."
    return "Perfeito. Qual data e horário? Ex.: 01/09 14:00, ou 'terça 10h', ou 'semana que vem sexta 9:30'."


def _reagendar_fluxo(value: dict, to_msisdn: str, uid_default: str, app_tag: str, body_text: str, text_norm: str, sess: dict, wa_id_raw: str, channel_mode: str = "text"):
    text_norm2 = _normalize_datetime_pt(text_norm)
    dt = _parse_datetime_br(text_norm2)
    if not dt and sess.get("dataHora"):
        try:
            dt = datetime.fromisoformat(sess["dataHora"])
        except Exception:
            dt = None
    if not dt:
        _save_session(
            uid_default,
            wa_id_raw,
            {
                "intent": "reagendar",
                "waKey": br_equivalence_key(wa_id_raw or to_msisdn or ""),
            },
        )
        return say(uid_default, "reschedule_ask")

    wa = ""
    try:
        contacts = value.get("contacts") or []
        if contacts and isinstance(contacts, list):
            wa = contacts[0].get("wa_id") or ""
    except Exception:
        pass
    cliente_id = _resolve_cliente_id(uid_default, wa, to_msisdn)
    alvo = _find_target_agendamento(uid_default, cliente_id, wa, to_msisdn)
    if not alvo:
        return (
            "Não encontrei um agendamento ativo seu.\n"
            "Você pode enviar: reagendar <ID> <dd/mm> <hh:mm> (ID aparece na confirmação)"
        )

    ag_id = alvo.get("_id")
    try:
        body = {"acao": "reagendar", "dataHora": dt.isoformat()}
        atualizar_estado_agendamento(uid_default, ag_id, body)
    except Exception as e:
        print(f"[WA_BOT][AGENDA][REAGENDAR] erro: {e}", flush=True)
        return "Não consegui reagendar agora. Pode tentar novamente em instantes?"

    _clear_session(uid_default, wa_id_raw)
    dia = dt.strftime("%d/%m")
    hora = dt.strftime("%H:%M")
    nome = alvo.get("servicoNome") or "serviço"

    if humanize_on():
        payload = {"servico": nome, "data": dt.strftime("%Y-%m-%d"), "data_str": dia, "hora": hora}
        return H("confirm_reagenda", payload, mode=("audio" if channel_mode == "audio" else "text"))

    return f"Tudo certo! Reagendei {nome} para {dia} às {hora}. Se precisar, eu mudo de novo. 😉"


# ========== Entrada principal ==========
def process_change(value: Dict[str, Any], send_text_fn, uid_default: str, app_tag: str, send_audio_fn=None):
    """
    value: payload 'change.value' da Meta
    send_text_fn: função injetada por app.py para enviar texto
    send_audio_fn: (opcional) função para enviar áudio (to, audio_bytes, mime_type)
    """

    # ✅ Opção B (Vendas com IA): se uid não foi resolvido, tratamos como LEAD (conteúdo público).
    # Mantém webhook burro: decisão vive aqui no bot.
    if not (uid_default or ""):
        try:
            from services.bot_handlers.sales_lead import handle_sales_lead  # type: ignore
            if handle_sales_lead(value, send_text_fn, app_tag=app_tag):
                return True
        except Exception:
            # fallback conservador: sem handler, não tenta responder
            return

    messages = value.get("messages", [])
    if not messages:
        return

    for m in messages:
        to_raw = m.get("from") or _pick_phone(value) or ""   # wa_id da Meta (pode vir sem 9)
        eq_key = br_equivalence_key(to_raw)
        print(f"[INBOUND] from_raw={to_raw} eq_key={eq_key}", flush=True)

        msg_type = m.get("type")
        channel_mode = "audio" if msg_type == "audio" else "text"
        text_in = ""

        # -------- ÁUDIO de entrada ----------
        if msg_type == "audio":
            try:
                charge("stt_per_15s", float(os.getenv("STT_SECONDS_AVG", "15")) / 15.0)
            except Exception:
                pass
            audio = m.get("audio") or {}
            media_id = audio.get("id")
            try:
                if not media_id:
                    send_reply(uid_default, to_raw, fallback_text(app_tag, "audio:sem-media_id"), msg_type, send_text_fn, send_audio_fn)
                    continue

                # Preferir fetch centralizado (services.wa_send.fetch_media). Fallback para Graph direto.
                audio_bytes, content_type = None, None
                try:
                    from services.wa_send import fetch_media  # lazy
                    audio_bytes, content_type = fetch_media(media_id)
                except Exception:
                    token = os.getenv("WHATSAPP_TOKEN")
                    gv = GRAPH_VERSION_DEFAULT
                    info = requests.get(
                        f"https://graph.facebook.com/{gv}/{media_id}",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=15,
                    ).json()
                    media_url = info.get("url")
                    if not media_url:
                        send_reply(uid_default, to_raw, fallback_text(app_tag, "audio:sem-url"), msg_type, send_text_fn, send_audio_fn)
                        continue
                    r = requests.get(media_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
                    audio_bytes = r.content or b""
                    content_type = r.headers.get("Content-Type")

                if not audio_bytes:
                    send_reply(uid_default, to_raw, fallback_text(app_tag, "audio:bytes=0"), msg_type, send_text_fn, send_audio_fn)
                continue

                mt = (audio.get("mime_type") or content_type or "audio/ogg").split(";")[0].strip()
                text_in = stt_transcribe(audio_bytes, mime_type=mt, language="pt-BR")
            except Exception as e:
                print("[WA_BOT][AUDIO][ERROR]", repr(e), flush=True)
                send_reply(uid_default, to_raw, fallback_text(app_tag, "audio:error"), msg_type, send_text_fn, send_audio_fn)
                continue

        elif msg_type == "text":
            text_in = (m.get("text") or {}).get("body", "")
        else:
            # Tipos não suportados: responde ajuda humanizada
            help_msg = H("help", {"raw": say(uid_default, "help")}, mode=("audio" if channel_mode=="audio" else "text"))
            send_reply(uid_default, to_raw, help_msg, msg_type, send_text_fn, send_audio_fn)
            continue

        # -------- Probe de memória por contato (apenas LOG nesta etapa) ----------
        if _contact_memory_probe_enabled(uid_default):
            try:
                # usamos apenas o wa_id bruto (to_raw) para resolver o cliente
                cliente_probe_id = _resolve_cliente_id(uid_default, wa_id_raw="", to_msisdn=to_raw)
                logging.info(
                    "[CONTACT_MEMORY][probe] uid=%s clienteId=%s waKey=%s text='%s'",
                    uid_default,
                    cliente_probe_id,
                    eq_key,
                    (text_in or "")[:200],
                )
            except Exception as e:
                logging.info("[CONTACT_MEMORY][probe] erro ao resolver cliente: %s", e)

        # -------- NLU probe ----------
        try:
            _nlu_probe(uid_default, text_in)
        except Exception:
            pass

        # -------- NLU leve ----------
        try:
            charge("nlp_mini", 1.0)
        except Exception:
            pass
        nlu = extract_intent(text_in or "")
        nlu = _merge_intents_legacy_with_v1(nlu, text_in)
        intent = (nlu.get("intent") or "fallback").lower()
        serviceName = nlu.get("serviceName")
        dateText = nlu.get("dateText")
        timeText = nlu.get("timeText")

        text_norm = _strip_accents_lower(text_in)
        # --- hard override para reagendamento por palavras-chave ---
        if re.search(r"\b(reagendar|remarcar|trocar\s+(?:o|de)?\s*horario|mudar\s+(?:o|de)?\s*horario)\b", text_norm):
            intent = "reagendar"
    
        # comandos rápidos de sessão
        if re.search(r"\b(cancelar|limpar|resetar|apagar\s+(conversa|sess[aã]o))\b", text_norm):
            try:
                _clear_session(uid_default, to_raw)
            except Exception:
                pass
            send_reply(uid_default, to_raw, say(uid_default, "session_cleared"), msg_type, send_text_fn, send_audio_fn)
            continue

        # -------- Orçamento (intent dedicada) ----------
        # A intenção "orcamento" deve vir da IA de NLU (GPT),
        # mas mantemos uma proteção extra por palavra "orcamento"/"orçamento"
        # para não deixar o usuário sem resposta caso o modelo não classifique direito.
        if intent == "orcamento" or "orcamento" in text_norm or "orçamento" in text_norm:
            send = lambda _to, _msg: send_reply(uid_default, _to, _msg, msg_type, send_text_fn, send_audio_fn)
            _reply_budget(uid_default, to_raw, text_in, send, value, channel_mode=channel_mode)
            continue

        # -------- Roteamento ----------
        if intent == "precos":
            send = lambda _to, _msg: send_reply(uid_default, _to, _msg, msg_type, send_text_fn, send_audio_fn)
            _reply_prices(uid_default, to_raw, send, channel_mode=channel_mode)
            continue

        if is_price_question(text_in):
            send = lambda _to, _msg: send_reply(uid_default, _to, _msg, msg_type, send_text_fn, send_audio_fn)
            _reply_price_from_cache_or_data(uid_default, to_raw, text_in, send, channel_mode=channel_mode)
            continue

        if intent in ("localizacao", "horarios", "telefone", "pagamento"):
            faq_map = {"localizacao": "endereco", "horarios": "horarios", "telefone": "telefone", "pagamento": "pix"}
            send = lambda _to, _msg: send_reply(uid_default, _to, _msg, msg_type, send_text_fn, send_audio_fn)
            _reply_faq(uid_default, to_raw, faq_map[intent], send, channel_mode=channel_mode)
            continue

        if intent == "agendar" and dateText and timeText:
            send = lambda _to, _msg: send_reply(uid_default, _to, _msg, msg_type, send_text_fn, send_audio_fn)
            _reply_schedule(uid_default, to_raw, serviceName, dateText, timeText, send, value, text_in, channel_mode=channel_mode)
            continue

        # Slot-filling quando v1 sinaliza "agendar" sem data/hora
        if NLU_MODE == "v1" and intent == "agendar" and not (dateText and timeText):
            sess = _get_session(uid_default, to_raw)
            items = _load_prices(uid_default)
            reply = _agendar_fluxo(value, to_raw, uid_default, app_tag, text_in, text_norm, items, sess, to_raw, channel_mode=channel_mode)
            send_reply(uid_default, to_raw, reply, msg_type, send_text_fn, send_audio_fn)
            continue

        # >>> NOVO: também faz slot-filling no modo legacy (sem v1)
        if intent == "agendar" and not (dateText and timeText):
            sess = _get_session(uid_default, to_raw)
            items = _load_prices(uid_default)
            reply = _agendar_fluxo(value, to_raw, uid_default, app_tag, text_in, text_norm, items, sess, to_raw, channel_mode=channel_mode)
            send_reply(uid_default, to_raw, reply, msg_type, send_text_fn, send_audio_fn)
            continue

        if intent == "reagendar":
            sess = _get_session(uid_default, to_raw)
            reply = _reagendar_fluxo(value, to_raw, uid_default, app_tag, text_in, text_norm, sess, to_raw, channel_mode=channel_mode)
            send_reply(uid_default, to_raw, reply, msg_type, send_text_fn, send_audio_fn)
            continue

        # Slot-filling de agendamento genérico
        sess = _get_session(uid_default, to_raw)
        if sess.get("intent") in ("agendar", "reagendar"):
            if sess["intent"] == "agendar":
                items = _load_prices(uid_default)
                reply = _agendar_fluxo(value, to_raw, uid_default, app_tag, text_in, text_norm, items, sess, to_raw, channel_mode=channel_mode)
                send_reply(uid_default, to_raw, reply, msg_type, send_text_fn, send_audio_fn)
                continue
            else:
                reply = _reagendar_fluxo(value, to_raw, uid_default, app_tag, text_in, text_norm, sess, to_raw, channel_mode=channel_mode)
                send_reply(uid_default, to_raw, reply, msg_type, send_text_fn, send_audio_fn)
                continue

        # -------- Acervo (mini-RAG) antes do fallback --------
        try:
            query_text = text_in or ""

            # Se a memória por contato estiver ativa, monta um contexto curto
            # a partir do cliente (histórico, tags, timeline, anexos, etc.)
            if (query_text or "").strip() and contact_memory_enabled_for(uid_default):
                cliente_id = None
                try:
                    # Reuso da mesma lógica de resolução de cliente usada na agenda
                    cliente_id = _resolve_cliente_id(uid_default, wa_id_raw="", to_msisdn=to_raw)
                except Exception as e_cm:
                    logging.info("[ACERVO][CONTACT_MEMORY] erro ao resolver clienteId: %s", e_cm)

                if cliente_id:
                    ctx = None
                    try:
                        # Usa o builder de contexto do domínio
                        ctx = build_contact_context(
                            uid_default,
                            cliente_id,
                        )
                    except Exception as e_ctx:
                        logging.info("[ACERVO][CONTACT_MEMORY] erro ao montar contexto do contato: %s", e_ctx)

                    if ctx:
                        partes = []

                        nome = (ctx.get("nome") or "").strip()
                        tel = (ctx.get("telefone") or "").strip()
                        tags = ctx.get("tags") or []
                        obs = (ctx.get("observacoes") or "").strip()

                        header = ""
                        if nome:
                            header = f"Nome: {nome}"
                        if tel:
                            header = (header + f" | Telefone: {tel}").strip(" |")
                        if header:
                            partes.append(header)

                        if tags:
                            partes.append("Tags: " + ", ".join(str(t) for t in tags[:8]))

                        if obs:
                            partes.append("Observações: " + obs[:240])

                        notas = ctx.get("notas") or []
                        if notas:
                            linhas_n = []
                            for n in notas[:5]:
                                data = (n.get("data") or "").strip()
                                txt = (n.get("texto") or "").strip()
                                if not txt:
                                    continue
                                prefix = f"[{data}] " if data else ""
                                linhas_n.append(prefix + txt)
                            if linhas_n:
                                partes.append("Notas recentes:\n" + "\n".join(linhas_n))

                        anexos = ctx.get("anexos") or []
                        if anexos:
                            linhas_a = []
                            for a in anexos[:5]:
                                data = (a.get("data") or "").strip()
                                nome_arq = (a.get("nomeArquivo") or "").strip()
                                if not nome_arq:
                                    continue
                                prefix = f"[{data}] " if data else ""
                                linhas_a.append(prefix + nome_arq)
                            if linhas_a:
                                partes.append("Anexos recentes:\n" + "\n".join(linhas_a))

                        cm_text = "\n".join(partes).strip()
                        if cm_text:
                            query_text = (
                                "Contexto do contato (histórico, notas e anexos relevantes):\n"
                                + cm_text
                                + "\n\nPergunta atual do contato:\n"
                                + (text_in or "")
                            )

            if _acervo_enabled_for_uid(uid_default) and (query_text or "").strip():
                acervo_reply = _try_acervo_answer(uid_default, query_text)
                if acervo_reply:
                    logging.info("[ACERVO] resposta enviada a partir do acervo (mini-RAG + memória por contato).")
                    send_reply(uid_default, to_raw, acervo_reply, msg_type, send_text_fn, send_audio_fn)
                    continue
        except Exception:
            # Nunca deixa o acervo derrubar o bot; loga e segue para fallback
            logging.exception("[ACERVO] erro inesperado ao tentar usar o acervo; seguindo para fallback.")
       
        # Fallback -> ajuda humanizada
        logging.info("[NLU] fallback -> help")
        help_msg = H("help", {"raw": say(uid_default, "help")}, mode=("audio" if channel_mode=="audio" else "text"))
        send_reply(uid_default, to_raw, help_msg, msg_type, send_text_fn, send_audio_fn)

    # statuses
    for st in value.get("statuses", []):
        print(
            f"[WA_BOT][STATUS] id={st.get('id')} status={st.get('status')} ts={st.get('timestamp')} recipient={st.get('recipient_id')} errors={st.get('errors')}",
            flush=True,
        )

