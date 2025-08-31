# services/budget_guard.py
# Guardião de orçamento/custos para o MEI Robô
# - Contabiliza custos por operação (STT, NLU mini, GPT-4o etc.)
# - Gating de recursos caros (áudio, GPT-4o) com base no orçamento mensal
# - Persistência leve em cache.kv (TTL até fim do mês/dia); fallback em memória

from __future__ import annotations
import os, json, time, logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

# =========================
# Configurações via ENV
# =========================
SP_TZ = timezone(timedelta(hours=-3))

BUDGET_MONTHLY_USD = float(os.getenv("BUDGET_MONTHLY_USD", "15.0"))
BUDGET_RESERVE_PCT = float(os.getenv("BUDGET_RESERVE_PCT", "0.20"))

# ---- Gating de features (com aliases pra compatibilidade) ----
# ÁUDIO (STT/TTS)
# - ENABLE_STT=true/false (preferido)
# - BUDGET_DISABLE_AUDIO=true => força desligar
enable_stt_env = os.getenv("ENABLE_STT", "true").strip().lower() in ("1", "true", "yes")
if os.getenv("BUDGET_DISABLE_AUDIO", "").strip().lower() in ("1", "true", "yes"):
    ENABLE_STT = False
else:
    ENABLE_STT = enable_stt_env

# GPT-4o
# - ENABLE_GPT4O=true/false OU ALLOW_GPT4O=true/false (alias)
if "ALLOW_GPT4O" in os.environ:
    ENABLE_GPT4O = os.getenv("ALLOW_GPT4O", "false").strip().lower() in ("1", "true", "yes")
else:
    ENABLE_GPT4O = os.getenv("ENABLE_GPT4O", "false").strip().lower() in ("1", "true", "yes")

# Thresholds mínimos para continuar ligando features (evita zerar)
BUDGET_MIN_REMAIN_AUDIO = float(os.getenv("BUDGET_MIN_REMAIN_AUDIO", "1.00"))   # USD
BUDGET_MIN_REMAIN_GPT4O = float(os.getenv("BUDGET_MIN_REMAIN_GPT4O", "2.50"))   # USD

# Cap diário de chamadas GPT-4o (extra além do budget mensal)
GPT4O_DAILY_CAP = int(os.getenv("GPT4O_DAILY_CAP", "200"))

# Tabela de custos (USD) por unidade; pode ser sobrescrita por ENV JSON
_DEFAULT_COSTS = {
    "stt_per_15s": 0.003,   # custo por 15s de áudio processado (ajuste à realidade)
    "nlp_mini":    0.0002,  # regras/intent baratas
    "gpt4o_msg":   0.015,   # 1 mensagem GPT-4o (estimativa conservadora)
    "tts_msg":     0.002,   # 1 resposta TTS curta (estimativa)
}
try:
    _COSTS = json.loads(os.getenv("BUDGET_COSTS_JSON", "")) or {}
    if not isinstance(_COSTS, dict):
        _COSTS = {}
except Exception:
    _COSTS = {}
COSTS: Dict[str, float] = {**_DEFAULT_COSTS, **_COSTS}

# =========================
# Persistência (cache.kv)
# =========================
try:
    from cache.kv import make_key as kv_make_key, get as kv_get, put as kv_put  # type: ignore
    _KV_OK = True
except Exception as e:
    logging.info("[budget_guard] cache.kv indisponível: %s", e)
    _KV_OK = False
    _kv_mem: Dict[str, Tuple[float, float]] = {}  # key -> (value, exp_ts)

    def kv_make_key(uid: str, group: str, slug: str) -> str:
        return f"{uid}::{group}::{slug}"[:512]

    def kv_get(uid: str, key: str):
        row = _kv_mem.get(key)
        if not row:
            return None
        value, exp = row
        if exp <= time.time():
            _kv_mem.pop(key, None)
            return None
        return value

    def kv_put(uid: str, key: str, value, ttl_sec: int = 3600):
        _kv_mem[key] = (value, time.time() + max(1, int(ttl_sec)))
        return True

# =========================
# Helpers de tempo / keys
# =========================
def _now() -> datetime:
    return datetime.now(SP_TZ)

def _month_key(dt: Optional[datetime] = None) -> str:
    dt = dt or _now()
    return dt.strftime("%Y-%m")  # ex.: 2025-08

def _day_key(dt: Optional[datetime] = None) -> str:
    dt = dt or _now()
    return dt.strftime("%Y-%m-%d")

def _seconds_until_end_of_month(dt: Optional[datetime] = None) -> int:
    dt = dt or _now()
    if dt.month == 12:
        nxt = datetime(dt.year + 1, 1, 1, tzinfo=dt.tzinfo)
    else:
        nxt = datetime(dt.year, dt.month + 1, 1, tzinfo=dt.tzinfo)
    return max(1, int((nxt - dt).total_seconds()))

def _seconds_until_end_of_day(dt: Optional[datetime] = None) -> int:
    dt = dt or _now()
    nxt = datetime(dt.year, dt.month, dt.day, 23, 59, 59, tzinfo=dt.tzinfo)
    return max(1, int((nxt - dt).total_seconds()))

# =========================
# Estado de orçamento
# =========================
_UID = os.getenv("UID_DEFAULT", "global")  # escopo do budget (pode ser por profissional)

def _spent_key_month(month_key: str) -> str:
    return kv_make_key(_UID, "budget_spent_usd", month_key)

def _gpt4o_day_counter_key(day_key: str) -> str:
    return kv_make_key(_UID, "gpt4o_count", day_key)

def _get_spent_usd(month_key: Optional[str] = None) -> float:
    mk = month_key or _month_key()
    val = kv_get(_UID, _spent_key_month(mk))
    try:
        return float(val or 0.0)
    except Exception:
        return 0.0

def _set_spent_usd(amount: float, month_key: Optional[str] = None):
    mk = month_key or _month_key()
    ttl = _seconds_until_end_of_month()
    kv_put(_UID, _spent_key_month(mk), float(amount), ttl_sec=ttl)

def _inc_spent_usd(amount: float, month_key: Optional[str] = None) -> float:
    mk = month_key or _month_key()
    cur = _get_spent_usd(mk)
    new = max(0.0, cur + float(amount))
    _set_spent_usd(new, mk)
    return new

def _inc_gpt4o_day_count(delta: int = 1) -> int:
    dk = _day_key()
    key = _gpt4o_day_counter_key(dk)
    cur = kv_get(_UID, key) or 0
    try:
        cur = int(cur)
    except Exception:
        cur = 0
    new = max(0, cur + int(delta))
    ttl = _seconds_until_end_of_day()
    kv_put(_UID, key, new, ttl_sec=ttl)
    return new

def _get_gpt4o_day_count() -> int:
    dk = _day_key()
    key = _gpt4o_day_counter_key(dk)
    val = kv_get(_UID, key) or 0
    try:
        return int(val)
    except Exception:
        return 0

# =========================
# API pública
# =========================
def budget_fingerprint() -> Dict:
    month = _month_key()
    spent = _get_spent_usd(month)
    limit = float(BUDGET_MONTHLY_USD or 0.0)
    reserve = limit * float(BUDGET_RESERVE_PCT or 0.0)
    soft_cap = max(0.0, limit - reserve)
    remaining = max(0.0, soft_cap - spent)

    return {
        "month": month,
        "usd": {
            "limit": round(limit, 4),
            "reserve": round(reserve, 4),
            "soft_cap": round(soft_cap, 4),
            "spent": round(spent, 4),
            "remaining": round(remaining, 4),
        },
        "features": {
            "stt_enabled": bool(ENABLE_STT),
            "gpt4o_enabled": bool(ENABLE_GPT4O),
        },
        "costs": COSTS,
        "gpt4o": {
            "today_count": _get_gpt4o_day_count(),
            "daily_cap": int(GPT4O_DAILY_CAP),
        },
    }

def charge(kind: str, units: float = 1.0) -> float:
    """
    Registra custo = COSTS[kind] * units no mês corrente.
    Retorna o acumulado (spent) depois do incremento.
    - Se kind == 'gpt4o_msg', incrementa também o contador diário.
    """
    try:
        cost = float(COSTS.get(kind, 0.0))
    except Exception:
        cost = 0.0
    delta = cost * float(units or 1.0)
    if kind == "gpt4o_msg":
        _inc_gpt4o_day_count(int(max(1, units)))
    if delta <= 0:
        return _get_spent_usd()
    return _inc_spent_usd(delta)

def _remaining_after_reserve() -> float:
    fp = budget_fingerprint()
    return float(fp["usd"]["remaining"])

def can_use_audio() -> bool:
    """
    Gate para STT/TTS (áudio):
      - precisa ENABLE_STT=true (e BUDGET_DISABLE_AUDIO != true)
      - precisa ter 'remaining' >= BUDGET_MIN_REMAIN_AUDIO
    """
    if not ENABLE_STT:
        return False
    remaining = _remaining_after_reserve()
    return remaining >= BUDGET_MIN_REMAIN_AUDIO

def can_use_gpt4o() -> bool:
    """
    Gate para GPT-4o:
      - precisa ENABLE_GPT4O=true (ou ALLOW_GPT4O=true)
      - precisa ter 'remaining' >= BUDGET_MIN_REMAIN_GPT4O
      - respeita cap diário GPT4O_DAILY_CAP
    """
    if not ENABLE_GPT4O:
        return False
    if _get_gpt4o_day_count() >= GPT4O_DAILY_CAP:
        return False
    remaining = _remaining_after_reserve()
    return remaining >= BUDGET_MIN_REMAIN_GPT4O

# Opcional: helper para registrar uso de GPT-4o explicitamente
def note_gpt4o_used(n: int = 1):
    _inc_gpt4o_day_count(max(1, int(n)))
