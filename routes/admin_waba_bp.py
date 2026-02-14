# routes/admin_waba_bp.py
# Admin-only: anexar (manual) um número/WABA (YCloud) ao profissional (Cliente Zero e primeiros clientes).
# POST /admin/waba/attach
#
# Regras:
# - Admin-only via ADMIN_UID_ALLOWLIST
# - Guard: nunca anexar o número institucional (YCLOUD_WA_FROM_E164) em cliente
# - Escreve:
#   1) profissionais/{uid}.waba (merge=True)
#   2) waba_owner_links/{waKeyDigits(fromE164)} -> {uid, fromE164, provider, status, attachedAt, attachedBy} (merge=True)
#
# Objetivo: suportar múltiplos WABAs com separação total institucional vs cliente-final.

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Tuple

from flask import Blueprint, jsonify, request

logger = logging.getLogger("mei_robo.admin_waba")

admin_waba_bp = Blueprint("admin_waba_bp", __name__)


def _db():
    from firebase_admin import firestore  # type: ignore
    return firestore.client()


def _now_ts() -> float:
    return float(time.time())


def _to_plus_e164(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if not s.startswith("+"):
        s = "+" + s
    s = "".join(ch for ch in s if ch.isdigit() or ch == "+")
    return s


def _wa_key_digits(e164: str) -> str:
    s = (e164 or "").strip()
    if not s:
        return ""
    return "".join(ch for ch in s if ch.isdigit())


def _get_uid_from_bearer(req) -> str:
    """Extrai UID de um Firebase ID token.
    Preferido: firebase_admin.auth.verify_id_token.
    Fallback: decodifica payload (não-cripto) apenas para ambientes legados.
    """
    try:
        authz = (req.headers.get("Authorization") or "").strip()
        if not authz.lower().startswith("bearer "):
            return ""
        token = authz.split(" ", 1)[1].strip()
        if not token:
            return ""

        # Preferido (seguro)
        try:
            from firebase_admin import auth as fb_auth  # type: ignore
            decoded = fb_auth.verify_id_token(token)
            uid = str(decoded.get("uid") or decoded.get("user_id") or decoded.get("sub") or "").strip()
            return uid
        except Exception:
            pass

        # Fallback (best-effort)
        try:
            import base64
            import json

            parts = token.split(".")
            if len(parts) < 2:
                return ""
            pad = "=" * ((4 - len(parts[1]) % 4) % 4)
            payload = json.loads(base64.urlsafe_b64decode((parts[1] + pad).encode()).decode())
            return str(payload.get("user_id") or payload.get("sub") or "").strip()
        except Exception:
            return ""
    except Exception:
        return ""


def _is_admin(req) -> Tuple[bool, str]:
    allow = [x.strip() for x in (os.environ.get("ADMIN_UID_ALLOWLIST") or "").split(",") if x.strip()]
    uid = _get_uid_from_bearer(req)
    return (bool(uid) and (uid in allow), uid)


@admin_waba_bp.route("/admin/waba/attach", methods=["POST", "OPTIONS"])
def admin_waba_attach():
    if request.method == "OPTIONS":
        return ("", 204)

    ok, admin_uid = _is_admin(request)
    if not ok:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    uid = (body.get("uid") or "").strip()
    from_e164 = _to_plus_e164(body.get("fromE164") or body.get("wabaFromE164") or body.get("e164") or "")

    if not uid:
        return jsonify({"ok": False, "error": "missing_uid"}), 400
    if not from_e164:
        return jsonify({"ok": False, "error": "missing_fromE164"}), 400

    # Guard: nunca permitir anexar o número institucional da plataforma ao cliente
    inst = _to_plus_e164(os.environ.get("YCLOUD_WA_FROM_E164") or "")
    if inst and from_e164 == inst:
        return jsonify({"ok": False, "error": "cannot_attach_institutional"}), 400

    provider = (body.get("provider") or "ycloud").strip().lower()
    mode = (body.get("mode") or "manual_chip").strip().lower()  # manual_chip | api_provisioned
    status = (body.get("status") or "ativo").strip().lower()

    patch: Dict[str, Any] = {
        "waba": {
            "provider": provider,
            "fromE164": from_e164,
            "mode": mode,
            "status": status,
            "attachedAt": _now_ts(),
            "attachedBy": admin_uid,
        }
    }

    # Campos opcionais (mantém patch pequeno)
    for k_in, k_out in [
        ("phoneNumberId", "phoneNumberId"),
        ("phone_number_id", "phoneNumberId"),
        ("wabaId", "wabaId"),
        ("businessId", "businessId"),
        ("displayPhoneNumber", "displayPhoneNumber"),
    ]:
        v = (body.get(k_in) or "").strip()
        if v:
            patch["waba"][k_out] = v

    wa_key = _wa_key_digits(from_e164)
    if not wa_key:
        return jsonify({"ok": False, "error": "invalid_fromE164"}), 400

    try:
        # 1) grava no profissional
        _db().collection("profissionais").document(uid).set(patch, merge=True)

        # 2) índice rápido de dono do WABA (destino -> uid)
        _db().collection("waba_owner_links").document(wa_key).set(
            {
                "uid": uid,
                "fromE164": from_e164,
                "provider": provider,
                "status": status,
                "mode": mode,
                "attachedAt": patch["waba"]["attachedAt"],
                "attachedBy": admin_uid,
            },
            merge=True,
        )

        return (
            jsonify(
                {
                    "ok": True,
                    "uid": uid,
                    "fromE164": from_e164,
                    "waKey": wa_key,
                    "provider": provider,
                    "mode": mode,
                    "status": status,
                }
            ),
            200,
        )
    except Exception as e:
        logger.exception("[admin_waba_attach] failed uid=%s from=%s", uid, from_e164)
        return jsonify({"ok": False, "error": "firestore_write_failed", "detail": str(e)[:160]}), 500
