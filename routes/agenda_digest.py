# routes/agenda_digest.py
# GET /api/agenda/digest?dry_run=true|false&date=YYYY-MM-DD&tz=America/Sao_Paulo
# - Auth: Bearer padrão do projeto OU header X-Debug-UID quando ALLOW_DEBUG_UID=1
# - Dry-run: retorna JSON com itens reais do dia
# - Envio real: usa services.mailer.send_email (se disponível) + variáveis EMAIL_FROM/EMAIL_PROVIDER

import os
import logging
from datetime import datetime, timedelta

import pytz
from flask import Blueprint, request, jsonify

agenda_digest_bp = Blueprint("agenda_digest_bp", __name__, url_prefix="/api/agenda")

# ---------------- Auth guard (igual filosofia das demais rotas) ----------------
_uid_from_bearer = None
try:
    from services.auth import get_uid_from_bearer as _uid_from_bearer
except Exception:
    _uid_from_bearer = None


def _require_uid(req):
    # 1) Produção: Bearer normal
    if _uid_from_bearer:
        try:
            uid = _uid_from_bearer(req)
            if uid:
                return uid
        except Exception:
            pass
    # 2) DEV: X-Debug-UID quando ALLOW_DEBUG_UID=1
    if os.getenv("ALLOW_DEBUG_UID", "0") == "1":
        dbg = req.headers.get("X-Debug-UID")
        if dbg:
            return dbg
    return None


# ---------------- Repo & Mailer ----------------
_list_events_for = None
try:
    from services.agenda_repo import list_events_for as _list_events_for
except Exception:
    _list_events_for = None

_send_email = None
try:
    from services.mailer import send_email as _send_email
except Exception:
    _send_email = None


# ---------------- Helpers ----------------
def _parse_bool(val, default=False):
    if val is None:
        return default
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "on")

def _today_str_tz(tz: str) -> str:
    try:
        zone = pytz.timezone(tz)
        return datetime.now(zone).strftime("%Y-%m-%d")
    except Exception:
        # fallback: -3h (BR) aproximado
        return (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d")

def _fmt_item_line(it) -> str:
    nome = (it.get("cliente") or {}).get("nome") or "(Sem nome)"
    wa = (it.get("cliente") or {}).get("whatsapp") or ""
    hhmm = it.get("hhmm") or "??:??"
    svc = it.get("service_id") or "serviço"
    note_in = it.get("notes_internal") or ""
    tail = f" — obs: {note_in}" if note_in else ""
    wa_tail = f" [{wa}]" if wa else ""
    return f"{hhmm} – {svc} – {nome}{wa_tail}{tail}"


# ---------------- Route ----------------
@agenda_digest_bp.route("/digest", methods=["GET"])
def digest_get():
    uid = _require_uid(request)
    if not uid:
        return jsonify({"erro": "Auth obrigatório"}), 401

    # Query params
    dry_run = _parse_bool(request.args.get("dry_run"), default=True)
    tz = (request.args.get("tz") or request.args.get("timezone") or "America/Sao_Paulo").strip()
    date_str = (request.args.get("date") or "").strip() or _today_str_tz(tz)

    # Coleta eventos reais do dia (se repo disponível)
    items = []
    if _list_events_for:
        try:
            items = _list_events_for(uid, date_str, tz) or []
        except Exception:
            logging.exception("[agenda_digest] falha ao listar eventos")
            items = []
    else:
        logging.warning("[agenda_digest] agenda_repo.list_events_for indisponível")

    # Monta preview
    header = f"Agenda do dia — {date_str} ({tz})"
    if items:
        linhas = [_fmt_item_line(it) for it in items]
        summary = f"{len(items)} compromisso(s):\n" + "\n".join(linhas)
    else:
        summary = "Sem compromissos para hoje."

    preview = {
        "header": header,
        "summary": summary,
        "count": len(items),
        "items": items,  # inclui notes_internal
    }

    # Log útil no Render
    logging.info("[agenda_digest] uid=%s dry_run=%s date=%s tz=%s count=%s",
                 uid, dry_run, date_str, tz, len(items))

    # Envio real (se solicitado e possível)
    if not dry_run:
        if not _send_email:
            return jsonify({
                "ok": False,
                "dry_run": False,
                "date": date_str,
                "error": "mailer_not_available",
                "detail": "services.mailer.send_email não encontrado."
            }), 501

        email_from = os.environ.get("EMAIL_FROM") or ""
        email_provider = os.environ.get("EMAIL_PROVIDER") or ""
        if not email_from or not email_provider:
            return jsonify({
                "ok": False,
                "dry_run": False,
                "date": date_str,
                "error": "email_env_missing",
                "detail": "Configure EMAIL_FROM e EMAIL_PROVIDER para envio real."
            }), 400

        # destinatário obrigatório para envio real
        to_email = request.args.get("to") or request.headers.get("X-Digest-To")
        if not to_email:
            return jsonify({
                "ok": False,
                "dry_run": False,
                "date": date_str,
                "error": "recipient_missing",
                "detail": "Informe destinatário via ?to=email@dominio ou header X-Digest-To."
            }), 400

        subject = f"MEI Robô — Agenda do dia {date_str}"
        body_text = f"{header}\n\n{summary}\n\n— MEI Robô"
        try:
            _send_email(
                to=to_email,
                subject=subject,
                text=body_text,
                from_email=email_from
            )
            logging.info("[agenda_digest] sent to=%s", to_email)
            return jsonify({"ok": True, "dry_run": False, "date": date_str, "sent_to": to_email})
        except Exception as e:
            logging.exception("[agenda_digest] send failed: %s", e)
            return jsonify({"ok": False, "dry_run": False, "date": date_str, "error": "send_failed", "detail": str(e)}), 500

    # Dry-run
    return jsonify({
        "ok": True,
        "dry_run": True,
        "date": date_str,
        "tz": tz,
        "preview": preview,
    })
