# routes/auth_bp.py
from flask import Blueprint, jsonify, request
from firebase_admin import auth as fb_auth
from services.firebase_admin_init import ensure_firebase_admin

auth_bp = Blueprint("auth_bp", __name__)

def _verify_bearer_token():
    hdr = request.headers.get("Authorization", "")
    if not hdr.startswith("Bearer "):
        return None
    token = hdr.split(" ", 1)[1]
    return fb_auth.verify_id_token(token)

@auth_bp.route("/auth/whoami", methods=["GET"])
def whoami():
    try:
        ensure_firebase_admin()
        decoded = _verify_bearer_token()
        if not decoded:
            return jsonify({"ok": False, "error": "missing_or_invalid_token"}), 401
        return jsonify({
            "ok": True,
            "uid": decoded.get("uid"),
            "email": decoded.get("email"),
            "provider": decoded.get("firebase", {}).get("sign_in_provider")
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 401
