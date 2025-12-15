# routes/admin_ycloud_test_bp.py
# Admin-only: envio de teste via YCloud (texto/template)
# POST /admin/ycloud/send-test

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from flask import Blueprint, request, jsonify
from google.cloud import firestore  # type: ignore

from services.firebase_admin_init import ensure_firebase_admin
from services.auth import get_uid_from_bearer  # type: ignore

from providers.ycloud import send_text, send_template  # usa o provider que você acabou de preencher


admin_ycloud_test_bp = Blueprint("admin_ycloud_test_bp", __name__)

def _db():
    ensure_firebase_admin()
    return firestore.Client()

def _now_ts():
    return firestore.SERVER_TIMESTAMP  # type: ignore

def _is_admin(uid: str) -> bool:
    allow = set(
        x.strip() for x in (os.environ.get("ADMIN_UID_ALLOWLIST", "") or "").split(",") if x.strip()
    )
    # Se allowlist estiver vazia, consideramos “sem admin” (mais seguro)
    return bool(uid) and bool(allow) and (uid in allow)

def _allow_to(to_e164: str) -> bool:
    # opcional: trava destino em allowlist de números pra teste
    # ex: YCLOUD_TEST_TO_ALLOWLIST=+5551..., +5551...
    raw = (os.environ.get("YCLOUD_TEST_TO_ALLOWLIST", "") or "").strip()
    if not raw:
        return True  # se não setar, não trava (mas é admin-only)
    allow = set(x.strip() for x in raw.split(",") if x.strip())
    return (to_e164 or "").strip() in allow

def _log(doc: Dict[str, Any]):
    try:
        db = _db()
        payload = dict(doc or {})
        payload["createdAt"] = _now_ts()
        db.collection("platform_wa_outbox_logs").add(payload)
    except Exception:
        pass

@admin_ycloud_test_bp.route("/admin/ycloud/send-test", methods=["POST"])
def admin_send_test():
    # Auth + admin gate
    try:
        uid = get_uid_from_bearer(request)
    except Exception:
        return jsonify({"ok": False, "error": "invalid_token"}), 401

    if not uid:
        return jsonify({"ok": False, "error": "missing_uid"}), 401
    if not _is_admin(uid):
        return jsonify({"ok": False, "error": "not_admin"}), 403

    data = request.get_json(silent=True) or {}
    to_e164 = (data.get("toE164") or data.get("to") or "").strip()
    mode = (data.get("mode") or "text").strip().lower()

    if not to_e164:
        return jsonify({"ok": False, "error": "missing_toE164"}), 400
    if not _allow_to(to_e164):
        return jsonify({"ok": False, "error": "to_not_allowed"}), 403

    # Envio
    ok = False
    resp: Dict[str, Any] = {}
    try:
        if mode == "template":
            template_name = (data.get("templateName") or "").strip()
            params = data.get("params") or []
            if not template_name:
                return jsonify({"ok": False, "error": "missing_templateName"}), 400
            ok, resp = send_template(to_e164, template_name, list(params or []))
        else:
            text = (data.get("text") or "Teste MEI Robô ✅").strip()
            ok, resp = send_text(to_e164, text)
    except Exception as e:
        ok, resp = False, {"error": {"message": f"sender_exception:{type(e).__name__}"}}

    # Log (sem segredos)
    _log({
        "adminUid": uid,
        "to": to_e164,
        "mode": mode,
        "ok": bool(ok),
        "resp": resp,
    })

    return jsonify({"ok": bool(ok), "toE164": to_e164, "mode": mode, "resp": resp}), (200 if ok else 502)
