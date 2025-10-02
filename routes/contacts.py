# routes/contacts.py
# Blueprint: opt-in (UI-only v1) — request/confirm
# Rotas:
#   POST /api/contacts/<contact_id>/request-optin
#   POST /api/contacts/<contact_id>/confirm-optin
from __future__ import annotations

from flask import Blueprint, request, jsonify
from services.auth import auth_required, current_uid
from services import db as dbsvc  # lazy wrapper

contacts_bp = Blueprint("contacts_bp", __name__)

def _col_prof(uid: str):
    return dbsvc.collection("profissionais").document(uid)

@contacts_bp.route("/api/contacts/<contact_id>/request-optin", methods=["POST"])
@auth_required
def request_optin(contact_id: str):
    """Cria um item em outbox (UI-only), marcando auditoria de pedido de opt-in"""
    uid = current_uid()
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    channel = (body.get("channel") or "whatsapp").lower()
    msg = (body.get("message") or "").strip()

    outbox_col = _col_prof(uid).collection("outbox")
    audits_col = _col_prof(uid).collection("audits")

    data = {
        "kind": "optin_request",
        "contactId": contact_id,
        "channel": channel,
        "message": msg,
        "status": "queued",
        "createdAt": dbsvc.now_ts(),
        "updatedAt": dbsvc.now_ts(),
    }
    ref = outbox_col.document()
    ref.set(data)

    audits_col.document().set({
        "action": "optin_request",
        "contactId": contact_id,
        "createdAt": dbsvc.now_ts(),
        "channel": channel
    })

    return jsonify({"ok": True, "id": ref.id}), 200

@contacts_bp.route("/api/contacts/<contact_id>/confirm-optin", methods=["POST"])
@auth_required
def confirm_optin(contact_id: str):
    """Marca consentimento no contato e adiciona log de auditoria (UI-only)"""
    uid = current_uid()
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    consent_status = (body.get("status") or "consentido").lower()

    contato_ref = _col_prof(uid).collection("clientes").document(contact_id)
    # merge — não sobrescreve outros campos do contato
    contato_ref.set({
        "consent": {
            "status": consent_status,
            "timestamp": dbsvc.now_ts(),
            "source": "ui_manual"
        },
        "updatedAt": dbsvc.now_ts(),
    }, merge=True)

    _col_prof(uid).collection("audits").document().set({
        "action": "optin_confirm",
        "contactId": contact_id,
        "status": consent_status,
        "createdAt": dbsvc.now_ts(),
    })

    return jsonify({"ok": True, "contactId": contact_id, "status": consent_status}), 200
