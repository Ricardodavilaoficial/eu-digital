# services/agenda_rules.py
# Regras de agenda por MEI (lidas de Firestore e/ou ENV), com defaults seguros.
# Novos campos pedidos: allow_same_day, allow_weekend, reminder_hours_before.

import os
import logging
from datetime import datetime
from typing import Dict, Any

try:
    import firebase_admin  # noqa
    from firebase_admin import firestore  # noqa
except Exception:
    firebase_admin = None
    firestore = None

DEFAULT_RULES = {
    "min_lead_days": 1,
    "max_lead_days": 30,
    "working_days": [1, 2, 3, 4, 5],  # 1=Mon .. 7=Sun (ISO)
    "working_hours": {"start": "09:00", "end": "18:00"},
    "step_minutes": 30,
    "buffer_minutes": 0,
    "daily_capacity": 999,  # sem limite prático por padrão
    "allow_same_day": False,
    "allow_weekend": False,
    "reminder_hours_before": 2
}

def _merge_env_overrides(rules: Dict[str, Any]) -> Dict[str, Any]:
    # Permite ajustar rapidamente via ENV sem redeploy de doc.
    env_map = {
        "MIN_LEAD_DAYS": ("min_lead_days", int),
        "MAX_LEAD_DAYS": ("max_lead_days", int),
        "STEP_MINUTES": ("step_minutes", int),
        "BUFFER_MINUTES": ("buffer_minutes", int),
        "DAILY_CAPACITY": ("daily_capacity", int),
        "ALLOW_SAME_DAY": ("allow_same_day", lambda v: v.lower() in ("1","true","yes","on")),
        "ALLOW_WEEKEND": ("allow_weekend", lambda v: v.lower() in ("1","true","yes","on")),
        "REMINDER_HOURS_BEFORE": ("reminder_hours_before", int),
    }
    for env, (key, caster) in env_map.items():
        val = os.getenv(env)
        if val:
            try:
                rules[key] = caster(val)
            except Exception:
                logging.exception(f"[agenda_rules] ENV {env} inválida: {val}")
    return rules

def get_rules_for(uid: str) -> Dict[str, Any]:
    rules = dict(DEFAULT_RULES)

    # Tenta Firestore: profissionais/{uid}/schedule_rules
    try:
        if firestore is not None:
            db = firestore.client()
            doc = db.collection("profissionais").document(uid).collection("config").document("schedule_rules").get()
            if doc and doc.exists:
                data = doc.to_dict() or {}
                rules.update({k: v for k, v in data.items() if v is not None})
    except Exception:
        logging.exception("[agenda_rules] Falha ao ler schedule_rules do Firestore")

    rules = _merge_env_overrides(rules)

    # Normalizações simples:
    wh = rules.get("working_hours") or {}
    start = (wh.get("start") or "09:00")[:5]
    end = (wh.get("end") or "18:00")[:5]
    rules["working_hours"] = {"start": start, "end": end}

    wd = rules.get("working_days") or [1,2,3,4,5]
    # Garante 1..7
    rules["working_days"] = [d for d in wd if isinstance(d, int) and 1 <= d <= 7] or [1,2,3,4,5]
    return rules
