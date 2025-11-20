# routes/agenda_api.py
# Rotas: /api/agenda/slots/search, /api/agenda/appointments, /api/agenda/events, /api/agenda/week
# + PATCH e CANCEL para agendamentos.
# Protegidas por bearer (admin/owner). Mantém padrão do projeto.

import os
import logging
from datetime import datetime, timedelta
import pytz
from flask import Blueprint, request, jsonify, g

# Auth helper (usa seu serviço existente)
uid_from_bearer = None
try:
    from services.auth import get_uid_from_bearer  # preferencial
    uid_from_bearer = get_uid_from_bearer
except Exception:
    pass

from services.agenda_repo import find_slots, create_event, list_events_for
from domain.scheduling import build_agenda_view_dashboard

agenda_api_bp = Blueprint("agenda_api_bp", __name__, url_prefix="/api/agenda")

log = logging.getLogger(__name__)


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
# GET /api/agenda/view
# Visão da agenda para o mini-dashboard (Cliente Zero)
# ---------------------------------------------------------------------
@agenda_api_bp.route("/view", methods=["GET"])
def api_agenda_view():
    """
    Visão da agenda para o mini-dashboard (Cliente Zero).

    Auth:
      - Preferencial: g.uid (decorator padrão do projeto)
      - Fallback: bearer/X-Debug-UID via _require_uid(request)

    Query:
      - days (opcional, padrão 9)
      - base (opcional, YYYY-MM-DD) → ponto de partida para "hoje"

    Retorna:
      {
        "tz": "America/Sao_Paulo",
        "today": "YYYY-MM-DD",
        "hoje":   [ {hhmm, cliente, assunto, dur, status, level}, ... ],
        "amanha": [...],
        "semana": [...]
      }
    """
    # 1) UID: tenta g.uid, cai para bearer/X-Debug-UID se não tiver
    uid = getattr(g, "uid", None) or _require_uid(request)
    if not uid:
        return jsonify({
            "error": "unauthenticated",
            "detail": "uid ausente; envie Authorization: Bearer <token> ou habilite X-Debug-UID em ambiente de DEV."
        }), 401

    # 2) Quantidade de dias (padrão 9 = hoje + amanhã + D+2..D+8)
    days_param = (request.args.get("days") or "").strip()
    if not days_param:
        days_param = "9"

    try:
        days = int(days_param)
    except Exception:
        days = 9

    # 3) Base opcional (YYYY-MM-DD). Se ausente, domínio usa "agora" no fuso SP.
    base_str = (request.args.get("base") or "").strip()
    base_dt = None
    if base_str:
        try:
            # Usa TZ de São Paulo; build_agenda_view_dashboard já espera datetime tz-aware
            tz = pytz.timezone("America/Sao_Paulo")
            naive = datetime.strptime(base_str, "%Y-%m-%d")
            base_dt = tz.localize(naive)
        except Exception:
            base_dt = None

    try:
        data = build_agenda_view_dashboard(uid=uid, base_date=base_dt, days=days)
        return jsonify(data)
    except Exception as e:
        log.exception("Erro ao montar agenda view para uid=%s", uid)
        return jsonify({"error": "internal_error", "detail": str(e)}), 500


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


# ---------------------------------------------------------------------
# PATCH /api/agenda/appointments/<event_id>
# Atualiza campos limitados (notes_internal, notes_public, hhmm, service_id)
# ---------------------------------------------------------------------
@agenda_api_bp.route("/appointments/<event_id>", methods=["PATCH"])
def patch_appointment(event_id):
    uid = _require_uid(request)
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    allowed = {"notes_internal", "notes_public", "hhmm", "service_id"}
    update_data = {k: v for k, v in data.items() if k in allowed}
    if not update_data:
        return jsonify({"ok": False, "error": "no_valid_fields"}), 400

    try:
        from services.agenda_repo import update_event
        res = update_event(event_id, update_data, uid)
        return jsonify(res or {"ok": False, "error": "update_failed"})
    except Exception:
        logging.exception("[agenda_api] erro em patch_appointment")
        return jsonify({"ok": False, "error": "exception"}), 200


# ---------------------------------------------------------------------
# POST /api/agenda/appointments/<event_id>/cancel
# Marca cancelamento e tenta notificar o cliente
# ---------------------------------------------------------------------
@agenda_api_bp.route("/appointments/<event_id>/cancel", methods=["POST"])
def cancel_appointment(event_id):
    uid = _require_uid(request)
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "").strip() or "Cancelado pelo profissional"
    try:
        from services.agenda_repo import cancel_event
        res = cancel_event(event_id, reason, uid)
        if not res or not res.get("ok"):
            return jsonify(res or {"ok": False, "error": "cancel_failed"}), 200

        # tenta notificar o cliente
        _try_notify_cancel(res.get("event", {}))
        return jsonify({"ok": True, "event": res.get("event")})
    except Exception:
        logging.exception("[agenda_api] erro em cancel_appointment")
        return jsonify({"ok": False, "error": "exception"}), 200


# ---------------------------------------------------------------------
# Helper: tenta notificar cliente (WhatsApp > E-mail)
# ---------------------------------------------------------------------
def _try_notify_cancel(event):
    try:
        cliente = event.get("cliente") or {}
        nome = cliente.get("nome") or "cliente"
        msg = f"Olá, {nome}! Seu agendamento foi cancelado pelo profissional. Caso queira remarcar, é só enviar uma mensagem."

        from services import wa_send, mailer

        # tenta WhatsApp primeiro
        wa = cliente.get("whatsapp")
        if wa:
            try:
                wa_send.send_whatsapp_text(wa, msg)
                logging.info(f"[agenda_cancel] notificado via WhatsApp: {wa}")
                return True
            except Exception:
                logging.warning(f"[agenda_cancel] falha WhatsApp para {wa}")

        # fallback: e-mail
        em = cliente.get("email")
        if em:
            try:
                mailer.send_email(to=em, subject="Agendamento cancelado", body=msg)
                logging.info(f"[agenda_cancel] notificado via e-mail: {em}")
                return True
            except Exception:
                logging.warning(f"[agenda_cancel] falha e-mail para {em}")

        logging.info("[agenda_cancel] nenhum canal disponível para notificar cliente")
        return False

    except Exception:
        logging.exception("[agenda_api] erro em _try_notify_cancel")
        return False
