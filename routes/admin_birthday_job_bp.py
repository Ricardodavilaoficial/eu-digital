# routes/admin_birthday_job_bp.py
# Admin job: envio diário de aniversários (MVP)
# Rota: POST /admin/jobs/birthday
#
# Regras:
# - Usa template aprovado (YCloud) fora da janela de 24h.
# - Dedup por: birthday.lastSentYear == ano atual OU log birthday_logs/YYYYMMDD_<contatoId>
# - Só envia se consentimento.status == "consentido" (ou consentimento.status)
#
from __future__ import annotations

import os
import base64
import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, request, jsonify

from services.db import db  # firestore client (projeto)
from services.wa_send import send_template

logger = logging.getLogger("mei_robo.birthday_job")

admin_birthday_job_bp = Blueprint("admin_birthday_job_bp", __name__)

_TZ = ZoneInfo("America/Sao_Paulo")


def _uid_from_bearer(req) -> str | None:
    auth = (req.headers.get("Authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        return None
    tok = auth.split(" ", 1)[1].strip()
    parts = tok.split(".")
    if len(parts) < 2:
        return None
    try:
        pad = "=" * ((4 - len(parts[1]) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode((parts[1] + pad).encode()).decode())
        return payload.get("user_id") or payload.get("uid") or payload.get("sub")
    except Exception:
        return None


def _is_admin(req) -> tuple[bool, str | None]:
    allow = [x.strip() for x in (os.environ.get("ADMIN_UID_ALLOWLIST") or "").split(",") if x.strip()]
    if not allow:
        return False, None
    uid = _uid_from_bearer(req)
    if not uid:
        return False, None
    if uid not in set(allow):
        return False, uid
    return True, uid


def _first_name(contact: dict) -> str:
    # preferência: comoChama, senão nome (primeira palavra)
    s = (contact.get("comoChama") or contact.get("nome") or "").strip()
    if not s:
        return "você"
    return s.split()[0][:40]


def _get_consent_status(contact: dict) -> str:
    # compat: contato pode ter "consent.status" OU "consentimento.status"
    c1 = ((contact.get("consent") or {}) if isinstance(contact.get("consent"), dict) else {})
    c2 = ((contact.get("consentimento") or {}) if isinstance(contact.get("consentimento"), dict) else {})
    st = (c1.get("status") or c2.get("status") or "").strip().lower()
    return st or "pendente"


def _get_phone(contact: dict) -> str:
    # preferir telefone_v2.msisdn (canônico)
    tv2 = contact.get("telefone_v2") or {}
    if isinstance(tv2, dict):
        msisdn = (tv2.get("msisdn") or "").strip()
        if msisdn:
            return msisdn
    # fallback: telefone raw
    return (contact.get("telefone") or "").strip()


@admin_birthday_job_bp.route("/admin/jobs/birthday", methods=["POST", "OPTIONS"])
def admin_jobs_birthday():
    if request.method == "OPTIONS":
        return ("", 204)

    ok, uid = _is_admin(request)
    if not ok:
        # 401 se sem token, 403 se token mas não admin (mantém padrão)
        return jsonify({"ok": False, "error": "forbidden", "uid": uid}), (401 if uid is None else 403)

    mode = (os.environ.get("BIRTHDAY_MODE") or "off").strip().lower()
    if mode not in ("on", "true", "1", "yes"):
        return jsonify({"ok": False, "error": "birthday_mode_off"}), 409

    template = (os.environ.get("BIRTHDAY_TEMPLATE") or "mei_robo_aniversario_v1").strip()
    dry_run = (os.environ.get("BIRTHDAY_DRY_RUN") or "0").strip().lower() in ("1", "true", "yes", "on")

    body = request.get_json(silent=True) or {}
    # override opcional (só admin)
    if isinstance(body, dict) and "dry_run" in body:
        dry_run = bool(body.get("dry_run"))

    now_sp = datetime.now(_TZ)
    day = int(now_sp.day)
    month = int(now_sp.month)
    year = int(now_sp.year)
    yyyymmdd = now_sp.strftime("%Y%m%d")

    # allowlist de UIDs (MVP seguro)
    allow_uids = [x.strip() for x in (os.environ.get("BIRTHDAY_UID_ALLOWLIST") or "").split(",") if x.strip()]
    if isinstance(body, dict) and body.get("uid_allowlist"):
        # opcional via body
        try:
            allow_uids = [x.strip() for x in list(body.get("uid_allowlist") or []) if str(x).strip()]
        except Exception:
            pass

    # lista de profissionais
    prof_col = db.collection("profissionais")

    uids: list[str] = []
    if allow_uids:
        uids = allow_uids
    else:
        # fallback: varrer tudo (não recomendado em escala, mas ok no MVP)
        for snap in prof_col.stream():
            if snap and snap.id:
                uids.append(snap.id)

    sent = 0
    skipped = 0
    errors = 0
    checked = 0

    for puid in uids:
        try:
            clientes_col = prof_col.document(puid).collection("clientes")

            # query pelos campos indexáveis do birthday (sem OR de consentimento)
            q = (
                clientes_col
                .where("birthday.month", "==", month)
                .where("birthday.day", "==", day)
                .where("birthday.enabled", "==", True)
            )

            for doc in q.stream():
                checked += 1
                cid = doc.id
                c = doc.to_dict() or {}

                # consentimento
                if _get_consent_status(c) != "consentido":
                    skipped += 1
                    continue

                bday = c.get("birthday") or {}
                last_year = None
                try:
                    last_year = int(bday.get("lastSentYear")) if (isinstance(bday, dict) and bday.get("lastSentYear") is not None) else None
                except Exception:
                    last_year = None
                if last_year == year:
                    skipped += 1
                    continue

                log_id = f"{yyyymmdd}_{cid}"
                log_ref = prof_col.document(puid).collection("birthday_logs").document(log_id)
                if log_ref.get().exists:
                    skipped += 1
                    continue

                phone = _get_phone(c)
                if not phone:
                    # sem telefone => não envia
                    log_ref.set({
                        "sentAt": datetime.now(timezone.utc),
                        "template": template,
                        "status": "skipped_no_phone",
                        "error": "missing_phone",
                        "contactId": cid,
                        "uid": puid,
                    }, merge=True)
                    skipped += 1
                    continue

                name = _first_name(c)
                params = [{"type": "text", "text": name}]

                if dry_run:
                    # só loga
                    log_ref.set({
                        "sentAt": datetime.now(timezone.utc),
                        "template": template,
                        "status": "dry_run",
                        "error": "",
                        "contactId": cid,
                        "uid": puid,
                        "to": phone,
                        "param1": name,
                    }, merge=True)
                    # marca lastSentYear mesmo no dry_run? melhor NÃO.
                    sent += 0
                    continue

                ok_send, resp = send_template(
                    to=phone,
                    template_name=template,
                    params=params,
                    language_code="pt_BR",
                )

                if ok_send:
                    sent += 1
                    log_ref.set({
                        "sentAt": datetime.now(timezone.utc),
                        "template": template,
                        "status": "sent",
                        "error": "",
                        "contactId": cid,
                        "uid": puid,
                        "to": phone,
                        "resp": resp,
                    }, merge=True)

                    # atualiza lastSentYear (merge)
                    clientes_col.document(cid).set({
                        "birthday": {
                            "lastSentYear": year
                        },
                        "updatedAt": datetime.now(timezone.utc),
                    }, merge=True)

                else:
                    errors += 1
                    log_ref.set({
                        "sentAt": datetime.now(timezone.utc),
                        "template": template,
                        "status": "error",
                        "error": "send_failed",
                        "contactId": cid,
                        "uid": puid,
                        "to": phone,
                        "resp": resp,
                    }, merge=True)

        except Exception as e:
            errors += 1
            logger.exception("[birthday_job] uid=%s failed: %s", puid, e)

    return jsonify({
        "ok": True,
        "day": day,
        "month": month,
        "year": year,
        "date": yyyymmdd,
        "template": template,
        "dry_run": dry_run,
        "uids": len(uids),
        "checked": checked,
        "sent": sent,
        "skipped": skipped,
        "errors": errors,
    }), 200
