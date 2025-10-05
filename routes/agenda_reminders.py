# routes/agenda_reminders.py
# GET /api/agenda/reminders/run?kind=whatsapp&hours_before=2
# Envia lembretes via função existente em services/wa_send.py

from flask import Blueprint, request, jsonify
import logging
from datetime import datetime, timedelta
import pytz

try:
    from services.wa_send import send_text as wa_send_text  # sua função existente
except Exception:
    wa_send_text = None

from services.agenda_rules import get_rules_for
from services.agenda_repo import list_events_for

agenda_rem_bp = Blueprint("agenda_rem_bp", __name__, url_prefix="/api/agenda/reminders")

def _send_whatsapp(to: str, body: str) -> bool:
    if wa_send_text:
        try:
            wa_send_text(to, body)
            return True
        except Exception:
            logging.exception("[agenda_rem] falha ao enviar WhatsApp")
    return False

def _require_uid(req):
    # Mesmo esquema do agenda_api
    try:
        from services.auth import get_uid_from_bearer
        return get_uid_from_bearer(req)
    except Exception:
        auth = req.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
    return req.headers.get("X-Debug-UID")

@agenda_rem_bp.route("/run", methods=["GET"])
def run():
    uid = _require_uid(request)
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    kind = request.args.get("kind") or "whatsapp"
    hours_before = int(request.args.get("hours_before") or 0)
    tz_str = request.args.get("tz") or "America/Sao_Paulo"
    tz = pytz.timezone(tz_str)

    rules = get_rules_for(uid)
    if hours_before <= 0:
        hours_before = int(rules.get("reminder_hours_before") or 2)

    now = datetime.now(tz)
    target = now + timedelta(hours=hours_before)
    date_str = target.strftime("%Y-%m-%d")
    items = list_events_for(uid, date_str, tz_str)

    sent = []
    for it in items:
        try:
            hhmm = it.get("hhmm")
            start_dt = tz.localize(datetime.strptime(f"{it['date']} {hhmm}", "%Y-%m-%d %H:%M"))
            # janela de ±15 min do target
            if abs((start_dt - target).total_seconds()) <= 15 * 60:
                cli = (it.get("cliente") or {})
                to = cli.get("whatsapp")
                service = it.get("service_id")
                when = f"{it['date']} {hhmm}"
                if to and kind == "whatsapp":
                    body = f"Olá! Lembrete do seu agendamento: {service} em {when}. Se precisar reagendar, responda por aqui. 😉"
                    if _send_whatsapp(to, body):
                        sent.append({"to": to, "service": service, "when": when})
        except Exception:
            logging.exception("[agenda_rem] erro ao processar item")

    return jsonify({"ok": True, "sent": sent, "target": target.isoformat()})
