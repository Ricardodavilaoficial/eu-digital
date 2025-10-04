
# routes/agenda_digest.py
# Minimal, safe GET endpoint for the daily agenda digest
# - URL: /api/agenda/digest?dry_run=true|false&date=YYYY-MM-DD&timezone=America/Sao_Paulo
# - Auth/Gate: uses the SAME decorator that protects /admin/ping
# - Behavior: returns a JSON preview in dry_run; for real send it checks for a mailer (if present)

import os
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

# Use the same admin decorator used by /admin/ping
from routes.admin import admin_required as _admin_guard

agenda_digest_bp = Blueprint("agenda_digest_bp", __name__, url_prefix="/api/agenda")

# Simple adapter so we keep the same @ decorator usage below
def _admin_gate():
    return _admin_guard

# Optional mailer (only used when dry_run=false and available)
_send_email = None
try:
    # If you already have a mailer utility, this will be used automatically
    from services.mailer import send_email as _send_email
except Exception:
    _send_email = None

def _parse_bool(val, default=False):
    if val is None:
        return default
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "on")

def _today_br_str():
    # Best-effort "today" in America/Sao_Paulo without pytz dependency
    # (UTC-03 most of the year; if DST changes, this is still a safe approximation for preview)
    dt = datetime.utcnow() - timedelta(hours=3)
    return dt.strftime("%Y-%m-%d")

@agenda_digest_bp.route("/digest", methods=["GET"])
@_admin_gate()
def digest_get():
    # Query params
    dry_run = _parse_bool(request.args.get("dry_run"), default=True)
    date_str = (request.args.get("date") or "").strip() or _today_br_str()
    tz = (request.args.get("timezone") or "America/Sao_Paulo").strip()

    # Basic env checks
    email_from = os.environ.get("EMAIL_FROM") or ""
    email_provider = os.environ.get("EMAIL_PROVIDER") or ""
    storage_bucket = os.environ.get("STORAGE_BUCKET") or ""

    # Build a tiny preview payload (no Firestore access here; this endpoint just orchestrates)
    preview = {
        "header": f"Agenda do dia — {date_str} ({tz})",
        "summary": "Sem eventos conectados neste endpoint mínimo (preview).",
        "notes": [
            "Este é um dry-run de segurança. O envio real depende do provider de e-mail do projeto.",
            "Se já existir um mailer em services.mailer.send_email, o envio real será usado automaticamente."
        ],
    }

    # Log for Render visibility
    logging.info("[agenda_digest] dry_run=%s date=%s tz=%s provider=%s from=%s bucket=%s",
                 dry_run, date_str, tz, email_provider, email_from, storage_bucket)

    # If not dry-run, try to send (only if a mailer exists)
    if not dry_run:
        if not _send_email:
            return jsonify({
                "ok": False,
                "dry_run": False,
                "date": date_str,
                "error": "mailer_not_available",
                "detail": "services.mailer.send_email não encontrado; habilite o provider antes do envio real."
            }), 501

        if not email_from or not email_provider:
            return jsonify({
                "ok": False,
                "dry_run": False,
                "date": date_str,
                "error": "email_env_missing",
                "detail": "Faltam EMAIL_FROM/EMAIL_PROVIDER no ambiente para envio real."
            }), 400

        # Determine recipient: if your admin gate injects identity, use request context or header fallback
        to_email = request.args.get("to") or request.headers.get("X-Digest-To")
        if not to_email:
            # As fallback, block explicit send without recipient to avoid surprises
            return jsonify({
                "ok": False,
                "dry_run": False,
                "date": date_str,
                "error": "recipient_missing",
                "detail": "Informe o destinatário via query ?to=email@dominio ou header X-Digest-To."
            }), 400

        subject = f"MEI Robô — Agenda do dia {date_str}"
        body_text = f"{preview['header']}\n\n{preview['summary']}\n\n— MEI Robô"
        try:
            _send_email(
                to=to_email,
                subject=subject,
                text=body_text,
                from_email=email_from
            )
            logging.info("[agenda_digest] sent to=%s subject=%s", to_email, subject)
            return jsonify({"ok": True, "dry_run": False, "date": date_str, "sent_to": to_email})
        except Exception as e:
            logging.exception("[agenda_digest] send failed: %s", e)
            return jsonify({"ok": False, "dry_run": False, "date": date_str, "error": "send_failed", "detail": str(e)}), 500

    # Dry-run response
    return jsonify({
        "ok": True,
        "dry_run": True,
        "date": date_str,
        "timezone": tz,
        "preview": preview,
        "env": {
            "EMAIL_PROVIDER": email_provider or "(vazio)",
            "EMAIL_FROM": email_from or "(vazio)",
            "STORAGE_BUCKET": storage_bucket or "(vazio)"
        }
    })
