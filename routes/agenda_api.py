# routes/agenda_api.py
# Rotas: /api/agenda/slots/search, /api/agenda/appointments, /api/agenda/events, /api/agenda/week
# Protegidas por bearer (admin/owner). Mantém padrão do projeto.

from flask import Blueprint, request, jsonify
import logging
from datetime import datetime, timedelta
import pytz

# Auth helper (usa seu serviço existente)
uid_from_bearer = None
try:
    from services.auth import get_uid_from_bearer  # preferencial
    uid_from_bearer = get_uid_from_bearer
except Exception:
    pass

from services.agenda_repo import find_slots, create_event, list_events_for

agenda_api_bp = Blueprint("agenda_api_bp", __name__, url_prefix="/api/agenda")

def _require_uid(req):
    # extrai uid do bearer para vincular ao MEI dono
    if uid_from_bearer:
        return uid_from_bearer(req)
    # fallback – se seu projeto usa outro helper, ajuste aqui:
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    # Se houver decodificador central, use-o. Aqui só sinalizamos ausência.
    return req.headers.get("X-Debug-UID")  # fallback DEV opcional

@agenda_api_bp.route("/slots/search", methods=["POST"])
def search_slots():
    uid = _require_uid(request)
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    data["uid"] = uid
    slots = find_slots(data)
    # Sugerir 3–5 primeiros para conversa
    top = slots[:5]
    return jsonify({"ok": True, "slots": top})

@agenda_api_bp.route("/appointments", methods=["POST"])
def create_appointment():
    uid = _require_uid(request)
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    # valida mínimo
    for k in ("date", "hhmm", "tz", "service_id", "cliente"):
        if not data.get(k):
            return jsonify({"ok": False, "error": f"missing_{k}"}), 400

    res = create_event(uid, data)
    status = 200 if res.get("ok") else 500
    return jsonify(res), status

@agenda_api_bp.route("/events", methods=["GET"])
def get_events_day():
    uid = _require_uid(request)
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    date_str = request.args.get("date")
    tz_str = request.args.get("tz") or "America/Sao_Paulo"
    if not date_str:
        tz = pytz.timezone(tz_str)
        date_str = datetime.now(tz).strftime("%Y-%m-%d")
    items = list_events_for(uid, date_str, tz_str)
    return jsonify({"ok": True, "items": items})

@agenda_api_bp.route("/week", methods=["GET"])
def get_events_week():
    uid = _require_uid(request)
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    start = request.args.get("start")  # YYYY-MM-DD
    tz_str = request.args.get("tz") or "America/Sao_Paulo"
    tz = pytz.timezone(tz_str)
    if not start:
        start_dt = datetime.now(tz)
    else:
        start_dt = tz.localize(datetime.strptime(start, "%Y-%m-%d"))

    out_days = []
    for i in range(7):
        d = start_dt + timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        out_days.append({"date": ds, "items": list_events_for(uid, ds, tz_str)})

    return jsonify({"ok": True, "days": out_days})
