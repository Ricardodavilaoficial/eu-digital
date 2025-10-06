# services/agenda_repo.py
# Persistência + cálculo de slots e listagem de eventos do dia (Firestore real).
# Coleção padrão: profissionais/{uid}/agendamentos/{autoId}

import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta, time
import pytz

import firebase_admin
from firebase_admin import firestore as fb_firestore
from services.agenda_rules import get_rules_for

# ---- Helpers gerais ----

def _hhmm_to_time(hhmm: str) -> time:
    hh, mm = hhmm.split(":")
    return time(hour=int(hh), minute=int(mm))

def _time_to_hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"

def _daterange_days(start_date: datetime, days: int) -> List[datetime]:
    return [start_date + timedelta(days=i) for i in range(days)]

def _overlaps(start1: datetime, end1: datetime, start2: datetime, end2: datetime) -> bool:
    return start1 < end2 and start2 < end1

def _get_db():
    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        return fb_firestore.client()
    except Exception as e:
        logging.exception("[agenda_repo] Firestore não inicializado")
        raise RuntimeError("Firestore não inicializado") from e

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
        q = col.where("date", "==", date_str).stream()
        for doc in q:
            d = doc.to_dict() or {}
            if d.get("status", "agendado") not in ("agendado", "reagendar"):
                continue
            items.append(d)
    except Exception:
        logging.exception("[agenda_repo] falha ao ler agendamentos do dia")
    return items

def _day_iso(d: datetime) -> int:
    return int(d.isoweekday())

# ---- API principais ----

def find_slots(req: Dict[str, Any]) -> List[Dict[str, str]]:
    uid = req.get("uid") or ""
    service_id = req.get("service_id") or ""
    window_start = req.get("window_start")
    window_days = int(req.get("window_days") or 7)
    tz_str = req.get("tz") or "America/Sao_Paulo"

    if not uid or not service_id or not window_start:
        return []

    tz = pytz.timezone(tz_str)
    start_date = tz.localize(datetime.strptime(window_start, "%Y-%m-%d"))
    now = datetime.now(tz)

    rules = get_rules_for(uid)
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

    first_ok_day = now.date()
    if not allow_same_day:
        first_ok_day = (now + timedelta(days=min_lead_days)).date()
    else:
        first_ok_day = (now + timedelta(days=min_lead_days)).date()

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
                slots.append({"date": date_str, "hhmm": _time_to_hhmm(start.timetz())[:5]})
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
        echo = snap.to_dict() if snap and snap.exists else {k: v for k, v in payload.items() if k not in ("created_at", "updated_at")}

        return {"ok": True, "id": doc_ref.id, "echo": echo}

    except Exception:
        logging.exception("[agenda_repo] falha ao criar agendamento")
        return {"ok": False, "error": "create_failed"}

def list_events_for(uid: str, date_str: str, tz_str: str) -> List[Dict[str, Any]]:
    db = _get_db()
    out: List[Dict[str, Any]] = []
    try:
        col = db.collection("profissionais").document(uid).collection("agendamentos")
        q = col.where("date", "==", date_str).stream()
        for doc in q:
            d = doc.to_dict() or {}
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
        logging.exception(f"[agenda_repo] falha ao atualizar evento {event_id}")
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

        event = snap.to_dict() or {}
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
        logging.exception(f"[agenda_repo] falha ao cancelar evento {event_id}")
        return {"ok": False, "error": "cancel_failed"}
