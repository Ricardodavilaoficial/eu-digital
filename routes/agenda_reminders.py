# routes/agenda_reminders.py
# GET /api/agenda/reminders/run?kind=whatsapp&hours_before=2
# Envia lembretes via WhatsApp para compromissos a T+hours_before
# Auth: Bearer padrão OU X-Debug-UID quando ALLOW_DEBUG_UID=1

import os
import logging
from datetime import datetime, timedelta

import pytz
from flask import Blueprint, request, jsonify

agenda_rem_bp = Blueprint("agenda_rem_bp", __name__, url_prefix="/api/agenda")

# -------- Auth guard (igual ao restante) --------
_uid_from_bearer = None
try:
    from services.auth import get_uid_from_bearer as _uid_from_bearer
except Exception:
    _uid_from_bearer = None

def _require_uid(req):
    if _uid_from_bearer:
        try:
            uid = _uid_from_bearer(req)
            if uid:
                return uid
        except Exception:
            pass
    if os.getenv("ALLOW_DEBUG_UID", "0") == "1":
        dbg = req.headers.get("X-Debug-UID")
        if dbg:
            return dbg
    return None


# -------- Repo & WhatsApp sender --------
_list_events_for = None
try:
    from services.agenda_repo import list_events_for as _list_events_for
except Exception:
    _list_events_for = None

_send_text = None
try:
    # reuse existing WhatsApp sender
    from services.wa_send import send_text as _send_text
except Exception:
    _send_text = None


def _parse_int(val, default: int) -> int:
    try:
        return int(val)
    except Exception:
        return default


@agenda_rem_bp.route("/reminders/run", methods=["GET"])
def reminders_run():
    uid = _require_uid(request)
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    kind = (request.args.get("kind") or "whatsapp").strip().lower()
    hours_before = _parse_int(request.args.get("hours_before"), 2)
    tz_str = (request.args.get("tz") or request.args.get("timezone") or "America/Sao_Paulo").strip()

    if kind != "whatsapp":
        return jsonify({"ok": False, "error": "kind_not_supported"}), 400
    if not _list_events_for:
        return jsonify({"ok": False, "error": "repo_unavailable"}), 500
    if not _send_text:
        return jsonify({"ok": False, "error": "wa_sender_unavailable"}), 501

    # Agora → busca compromissos que acontecerão em T+hours_before
    zone = pytz.timezone(tz_str)
    now = datetime.now(zone)
    target_dt = now + timedelta(hours=hours_before)
    target_date = target_dt.strftime("%Y-%m-%d")
    target_hhmm = target_dt.strftime("%H:%M")

    try:
        events = _list_events_for(uid, target_date, tz_str) or []
        to_remind = [e for e in events if e.get("hhmm") == target_hhmm and (e.get("status") or "agendado") == "agendado"]
    except Exception:
        logging.exception("[agenda_reminders] falha ao listar eventos")
        return jsonify({"ok": False, "error": "list_failed"}), 500

    sent = []
    errors = []
    for ev in to_remind:
        cli = ev.get("cliente") or {}
        to = cli.get("whatsapp")
        if not to:
            continue
        svc = ev.get("service_id") or "serviço"
        date = ev.get("date") or target_date
        hhmm = ev.get("hhmm") or target_hhmm
        body = f"⏰ Lembrete: {svc} hoje às {hhmm}. Qualquer imprevisto, me avise por aqui. Até já!"
        try:
            _send_text(to, body)
            sent.append({"to": to, "date": date, "hhmm": hhmm})
        except Exception as e:
            logging.exception("[agenda_reminders] send fail to=%s err=%s", to, e)
            errors.append({"to": to, "error": str(e)})

    return jsonify({"ok": True, "tz": tz_str, "hours_before": hours_before, "sent": sent, "errors": errors})
