# routes/agenda_api.py
# Rotas: /api/agenda/slots/search, /api/agenda/appointments, /api/agenda/events, /api/agenda/week
# Protegidas por bearer (admin/owner). Mantém padrão do projeto.

import os
import logging
from datetime import datetime, timedelta

import pytz
from flask import Blueprint, request, jsonify

# Auth helper (usa seu serviço existente)
uid_from_bearer = None
try:
    from services.auth import get_uid_from_bearer  # preferencial
    uid_from_bearer = get_uid_from_bearer
except Exception:
    pass

from services.agenda_repo import find_slots, create_event, list_events_for

agenda_api_bp = Blueprint("agenda_api_bp", __name__, url_prefix="/api/agenda")


# ---------------------------------------------------------------------
# Auth guard: Bearer em produção + fallback DEV via X-Debug-UID (ENV)
# ---------------------------------------------------------------------
def _require_uid(req):
    # 1) Produção: tenta extrair via bearer normal
    if uid_from_bearer:
        try:
            uid = uid_from_bearer(req)
            if uid:
                return uid
        except Exception:
            pass
    # 2) DEV: permite header X-Debug-UID quando habilitado por ENV
    if os.getenv("ALLOW_DEBUG_UID", "0") == "1":
        dbg = req.headers.get("X-Debug-UID")
        if dbg:
            return dbg
    return None


# ---------------------------------------------------------------------
# POST /api/agenda/slots/search
# body: { service_id, window_start(YYYY-MM-DD), window_days, tz }
# resp: { ok, slots: [{date, hhmm}, ...] }  -> 3–5 primeiras opções
# ---------------------------------------------------------------------
@agenda_api_bp.route("/slots/search", methods=["POST"])
def search_slots():
    uid = _require_uid(request)
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    data["uid"] = uid
    slots = find_slots(data) or []
    top = slots[:5]  # sugere 3–5 primeiras opções
    return jsonify({"ok": True, "slots": top})


# ---------------------------------------------------------------------
# POST /api/agenda/appointments
# body mínimo:
# {
#   "date":"YYYY-MM-DD","hhmm":"09:30","tz":"America/Sao_Paulo",
#   "service_id":"corte",
#   "cliente":{"nome":"...","whatsapp":"+55..."},
#   "notes_public":"...","notes_internal":"..."
# }
# resp: { ok, id?, echo?, error? }  (NUNCA 500)
# ---------------------------------------------------------------------
@agenda_api_bp.route("/appointments", methods=["POST"])
def create_appointment():
    uid = _require_uid(request)
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    try:
        # valida mínimo
        required = ("date", "hhmm", "service_id")
        missing = [k for k in required if not data.get(k)]
        if missing:
            return jsonify({"ok": False, "error": f"missing:{','.join(missing)}"}), 400

        # normaliza payload (garante campos esperados pelo repo)
        event = {
            "date": data.get("date"),
            "hhmm": data.get("hhmm"),
            "tz": data.get("tz") or "America/Sao_Paulo",
            "service_id": data.get("service_id"),
            "cliente": data.get("cliente") or {},
            "notes_public": data.get("notes_public") or "",
            "notes_internal": data.get("notes_internal") or "",
        }

        res = create_event(uid, event)
        # Nunca estoura 500: responde JSON com ok:false se o repo falhar
        if not res or not res.get("ok"):
            return jsonify(res or {"ok": False, "error": "create_failed"}), 200
        return jsonify(res), 200

    except Exception:
        logging.exception("[agenda_api] erro ao criar appointment")
        return jsonify({"ok": False, "error": "exception"}), 200


# ---------------------------------------------------------------------
# GET /api/agenda/events?date=YYYY-MM-DD&tz=America/Sao_Paulo
# resp: { ok, items: [...] }
# ---------------------------------------------------------------------
@agenda_api_bp.route("/events", methods=["GET"])
def get_events_day():
    uid = _require_uid(request)
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    tz_str = request.args.get("tz") or "America/Sao_Paulo"
    date_str = request.args.get("date")
    if not date_str:
        tz = pytz.timezone(tz_str)
        date_str = datetime.now(tz).strftime("%Y-%m-%d")

    items = list_events_for(uid, date_str, tz_str) or []
    return jsonify({"ok": True, "items": items})


# ---------------------------------------------------------------------
# GET /api/agenda/week?start=YYYY-MM-DD&tz=America/Sao_Paulo
# resp: { ok, days: [{date, items:[...]}, ...] }
# ---------------------------------------------------------------------
@agenda_api_bp.route("/week", methods=["GET"])
def get_events_week():
    uid = _require_uid(request)
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    tz_str = request.args.get("tz") or "America/Sao_Paulo"
    tz = pytz.timezone(tz_str)

    start = request.args.get("start")  # YYYY-MM-DD
    if not start:
        start_dt = datetime.now(tz)
    else:
        start_dt = tz.localize(datetime.strptime(start, "%Y-%m-%d"))

    out_days = []
    for i in range(7):
        d = start_dt + timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        out_days.append({"date": ds, "items": list_events_for(uid, ds, tz_str) or []})

    return jsonify({"ok": True, "days": out_days})
