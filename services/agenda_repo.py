# services/agenda_repo.py
# Persistência + cálculo de slots e listagem de eventos do dia (Firestore real).
# Coleção padrão: profissionais/{uid}/agendamentos/{autoId}

import os
import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta, time
import pytz

import firebase_admin
from firebase_admin import firestore as fb_firestore

# Regras de agenda (com fallback seguro)
try:
    from services.agenda_rules import get_rules_for as _get_rules_for
except Exception:
    _get_rules_for = None

# -------------------------------------------------------------------
# Helpers gerais
# -------------------------------------------------------------------

def _hhmm_to_time(hhmm: str) -> time:
    hh, mm = hhmm.split(":")
    return time(hour=int(hh), minute=int(mm))

def _time_to_hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"

def _daterange_days(start_date: datetime, days: int) -> List[datetime]:
    return [start_date + timedelta(days=i) for i in range(days)]

def _overlaps(start1: datetime, end1: datetime, start2: datetime, end2: datetime) -> bool:
    return start1 < end2 and start2 < end1

def _tz(tz_str: str) -> pytz.BaseTzInfo:
    try:
        return pytz.timezone(tz_str)
    except Exception:
        logging.warning("[agenda_repo] TZ inválido %r, usando America/Sao_Paulo", tz_str)
        return pytz.timezone("America/Sao_Paulo")

def _get_db():
    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        return fb_firestore.client()
    except Exception as e:
        logging.exception("[agenda_repo] Firestore não inicializado")
        raise RuntimeError("Firestore não inicializado") from e

def _safe_rules_for(uid: str) -> Dict[str, Any]:
    """
    Fallback de regras caso o módulo/consulta falhe. Mantém compat.
    """
    defaults = {
        "step_minutes": 30,
        "buffer_minutes": 0,
        "min_lead_days": 0,
        "max_lead_days": 30,
        "allow_same_day": True,
        "allow_weekend": False,
        # ISO weekday: 1=segunda ... 7=domingo
        "working_days": [1, 2, 3, 4, 5],
        "working_hours": {"start": "08:00", "end": "18:30"},
    }
    if not _get_rules_for:
        return defaults
    try:
        r = _get_rules_for(uid) or {}
        # merge r sobre defaults
        out = dict(defaults)
        out.update(r)
        # normaliza campos críticos
        out["step_minutes"] = int(out.get("step_minutes", defaults["step_minutes"]))
        out["buffer_minutes"] = int(out.get("buffer_minutes", defaults["buffer_minutes"]))
        out["min_lead_days"] = int(out.get("min_lead_days", defaults["min_lead_days"]))
        out["max_lead_days"] = int(out.get("max_lead_days", defaults["max_lead_days"]))
        out["allow_same_day"] = bool(out.get("allow_same_day", defaults["allow_same_day"]))
        out["allow_weekend"] = bool(out.get("allow_weekend", defaults["allow_weekend"]))
        wh = out.get("working_hours") or defaults["working_hours"]
        out["working_hours"] = {
            "start": wh.get("start") or defaults["working_hours"]["start"],
            "end": wh.get("end") or defaults["working_hours"]["end"],
        }
        wd = out.get("working_days") or defaults["working_days"]
        out["working_days"] = [int(x) for x in wd]
        return out
    except Exception:
        logging.exception("[agenda_repo] falha ao obter regras; usando defaults")
        return defaults

def _get_duration_min_for_service(uid: str, service_id: str) -> int:
    try:
        db = _get_db()
        col = db.collection("profissionais").document(uid).collection("produtosEServicos")
        q = col.where("slug", "==", service_id).limit(1).stream()
        for doc in q:
            data = doc.to_dict() or {}
            dur = data.get("duracaoMin") or data.get("duration_min") or data.get("duracao") or 30
            return int(dur)
    except Exception:
        logging.exception("[agenda_repo] falha ao buscar duração do serviço; usando 30")
    return 30

def _load_conflicts_for_day(uid: str, date_str: str, tz_str: str) -> List[Dict[str, Any]]:
    db = _get_db()
    items: List[Dict[str, Any]] = []
    try:
        col = db.collection("profissionais").document(uid).collection("agendamentos")
        # Apenas agendados relevantes (igual filtragem em list_events_for)
        q = col.where("date", "==", date_str).stream()
        for doc in q:
            d = doc.to_dict() or {}
            if d.get("status", "agendado") not in ("agendado", "reagendar"):
                continue
            items.append(d)
    except Exception:
        logging.exception("[agenda_repo] falha ao ler agendamentos do dia (conflicts)")
    return items

def _day_iso(d: datetime) -> int:
    return int(d.isoweekday())

def _parse_date_str(date_str: str, tz: pytz.BaseTzInfo) -> datetime:
    try:
        y, m, d = [int(x) for x in date_str.split("-")]
        return tz.localize(datetime(y, m, d))
    except Exception:
        logging.warning("[agenda_repo] date_str inválido %r; usando hoje", date_str)
        now = datetime.now(tz)
        return tz.localize(datetime(now.year, now.month, now.day))

# -------------------------------------------------------------------
# API principais
# -------------------------------------------------------------------

def find_slots(req: Dict[str, Any]) -> List[Dict[str, str]]:
    uid = req.get("uid") or ""
    service_id = req.get("service_id") or ""
    window_start = req.get("window_start")
    window_days = int(req.get("window_days") or 7)
    tz_str = (req.get("tz") or "America/Sao_Paulo").strip() or "America/Sao_Paulo"

    if not uid or not service_id or not window_start:
        return []

    tz = _tz(tz_str)
    # parse window_start com robustez
    try:
        start_date = _parse_date_str(window_start, tz)
    except Exception:
        start_date = _parse_date_str(datetime.now(tz).strftime("%Y-%m-%d"), tz)

    now = datetime.now(tz)

    rules = _safe_rules_for(uid)
    dur_min = _get_duration_min_for_service(uid, service_id)
    step = timedelta(minutes=int(rules["step_minutes"]))
    buffer_min = int(rules["buffer_minutes"])
    min_lead_days = int(rules["min_lead_days"])
    max_lead_days = int(rules["max_lead_days"])
    allow_same_day = bool(rules["allow_same_day"])
    allow_weekend = bool(rules["allow_weekend"])
    working_days = rules["working_days"]
    wh_start = _hhmm_to_time(rules["working_hours"]["start"])
    wh_end = _hhmm_to_time(rules["working_hours"]["end"])

    # Corrigido: se NÃO permite mesmo-dia, força no mínimo D+1
    offset_days = min_lead_days
    if not allow_same_day:
        offset_days = max(1, min_lead_days)
    first_ok_day = (now + timedelta(days=offset_days)).date()
    last_ok_day = (now + timedelta(days=max_lead_days)).date()

    slots: List[Dict[str, str]] = []

    for day in _daterange_days(start_date, window_days):
        ddate = day.date()
        if ddate < first_ok_day or ddate > last_ok_day:
            continue
        iso = _day_iso(day)
        if (iso not in working_days) and (not allow_weekend):
            continue

        date_str = ddate.strftime("%Y-%m-%d")
        conflicts = _load_conflicts_for_day(uid, date_str, tz_str)

        cur_dt = tz.localize(datetime.combine(ddate, wh_start))
        end_dt = tz.localize(datetime.combine(ddate, wh_end))

        while cur_dt + timedelta(minutes=dur_min) <= end_dt:
            # Se é hoje, não permitir horários passados
            if ddate == now.date() and cur_dt <= now:
                cur_dt += step
                continue

            start = cur_dt
            end = cur_dt + timedelta(minutes=dur_min)
            has_conflict = False
            for c in conflicts:
                try:
                    c_start = tz.localize(datetime.strptime(f"{c['date']} {c['hhmm']}", "%Y-%m-%d %H:%M"))
                    c_end = c_start + timedelta(minutes=int(c.get("duration_min") or dur_min))
                    if buffer_min:
                        c_start = c_start - timedelta(minutes=buffer_min)
                        c_end = c_end + timedelta(minutes=buffer_min)
                    if _overlaps(start, end, c_start, c_end):
                        has_conflict = True
                        break
                except Exception:
                    continue

            if not has_conflict:
                slots.append({"date": date_str, "hhmm": _time_to_hhmm(start.timetz())})
            cur_dt += step

    return slots

def create_event(uid: str, event: Dict[str, Any]) -> Dict[str, Any]:
    try:
        db = _get_db()

        dur_min = _get_duration_min_for_service(uid, event.get("service_id") or "generico")
        payload = dict(event)
        payload["duration_min"] = int(dur_min)
        payload["status"] = payload.get("status") or "agendado"

        try:
            payload["created_at"] = fb_firestore.SERVER_TIMESTAMP
            payload["updated_at"] = fb_firestore.SERVER_TIMESTAMP
        except Exception:
            pass

        doc_ref = db.collection("profissionais").document(uid).collection("agendamentos").document()
        doc_ref.set(payload)

        snap = doc_ref.get()
        echo = snap.to_dict() if snap and snap.exists else {
            k: v for k, v in payload.items() if k not in ("created_at", "updated_at")
        }

        return {"ok": True, "id": doc_ref.id, "echo": echo}

    except Exception:
        logging.exception("[agenda_repo] falha ao criar agendamento")
        return {"ok": False, "error": "create_failed"}

def list_events_for(uid: str, date_str: str, tz_str: str) -> List[Dict[str, Any]]:
    """
    Lista eventos visíveis do dia. Respeita ZERO_UIDS_EMPTY (env)
    para forçar lista vazia em UIDs específicos (ex.: cliente zero).
    """
    # Se quiser zerar temporariamente um ou mais UIDs, defina:
    # ZERO_UIDS_EMPTY="uid1,uid2"
    empty_uids_env = (os.getenv("ZERO_UIDS_EMPTY") or "").strip()
    if empty_uids_env:
        empty_uids = [u.strip() for u in empty_uids_env.split(",") if u.strip()]
        if uid in empty_uids:
            return []

    db = _get_db()
    out: List[Dict[str, Any]] = []
    try:
        # valida data rapidamente (evita consulta com garbage)
        tz = _tz(tz_str or "America/Sao_Paulo")
        _ = _parse_date_str(date_str, tz)

        col = db.collection("profissionais").document(uid).collection("agendamentos")
        q = col.where("date", "==", date_str).stream()
        for doc in q:
            d = doc.to_dict() or {}
            # Filtra status não visíveis
            if d.get("status", "agendado") not in ("agendado", "reagendar"):
                continue
            out.append(d)
    except Exception:
        logging.exception("[agenda_repo] falha ao listar eventos do dia")
    return out

# ---------------------------------------------------------------------
# NOVAS FUNÇÕES: update_event e cancel_event
# ---------------------------------------------------------------------

def update_event(event_id: str, data: Dict[str, Any], uid: str) -> Dict[str, Any]:
    """Atualiza campos específicos de um agendamento existente"""
    try:
        db = _get_db()
        col = db.collection("profissionais").document(uid).collection("agendamentos")
        doc_ref = col.document(event_id)
        doc = doc_ref.get()
        if not doc.exists:
            return {"ok": False, "error": "not_found"}

        update_payload = dict(data)
        update_payload["updated_at"] = fb_firestore.SERVER_TIMESTAMP

        doc_ref.update(update_payload)
        snap = doc_ref.get()
        return {"ok": True, "event": snap.to_dict()}
    except Exception:
        logging.exception("[agenda_repo] falha ao atualizar evento %s", event_id)
        return {"ok": False, "error": "update_failed"}

def cancel_event(event_id: str, reason: str, uid: str) -> Dict[str, Any]:
    """Cancela um agendamento e registra motivo e timestamp"""
    try:
        db = _get_db()
        col = db.collection("profissionais").document(uid).collection("agendamentos")
        doc_ref = col.document(event_id)
        snap = doc_ref.get()
        if not snap.exists:
            return {"ok": False, "error": "not_found"}

        updates = {
            "status": "cancelado",
            "cancel_reason": reason,
            "cancelled_at": fb_firestore.SERVER_TIMESTAMP,
            "updated_at": fb_firestore.SERVER_TIMESTAMP,
        }

        doc_ref.update(updates)
        updated = doc_ref.get().to_dict()
        return {"ok": True, "event": updated}
    except Exception:
        logging.exception("[agenda_repo] falha ao cancelar evento %s", event_id)
        return {"ok": False, "error": "cancel_failed"}
