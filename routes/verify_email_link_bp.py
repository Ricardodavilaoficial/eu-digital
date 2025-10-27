# routes/verify_email_link_bp.py
from flask import Blueprint, jsonify, request
from services.firebase_admin_init import ensure_firebase_admin

verify_email_link_bp = Blueprint("verify_email_link_bp", __name__, url_prefix="/api/auth")

@verify_email_link_bp.route("/send-verification", methods=["POST"])
def send_verification():
    """
    Gera o link de verificação do Firebase Auth e retorna em JSON.
    NÂO envia email (isso será a Atividade 2).
    Requer Bearer idToken válido no Authorization.
    """
    import os
    from firebase_admin import auth as fb_auth
    ensure_firebase_admin()

    # 1) validar Bearer (idToken)
    hdr = request.headers.get("Authorization", "")
    if not hdr.startswith("Bearer "):
        return jsonify({"ok": False, "error": "missing_bearer"}), 401
    id_token = hdr.split(" ", 1)[1]

    try:
        decoded = fb_auth.verify_id_token(id_token)
        email = decoded.get("email") or ""
        if not email:
            return jsonify({"ok": False, "error": "no_email_in_token"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": "invalid_token", "detail": str(e)}), 401

    # 2) montar continueUrl (opcional no body)
    body = request.get_json(silent=True) or {}
    cont = body.get("continueUrl") or "/pages/configuracao.html"

    origin = request.headers.get("X-Forwarded-Proto", "https") + "://" + request.headers.get("Host", "").strip()
    # fallback seguro pro seu domínio público
    public_base = os.environ.get("PUBLIC_BASE", "https://www.meirobo.com.br")
    base = public_base if not origin or "onrender.com" in origin else origin

    verify_page = f"{base}/verify-email.html?cont={cont}"

    # 3) gerar link assinado
    try:
        link = fb_auth.generate_email_verification_link(
            email,
            action_code_settings=fb_auth.ActionCodeSettings(
                url=verify_page,
                handle_code_in_app=False,
            ),
        )
        return jsonify({"ok": True, "email": email, "verificationLink": link, "continueUrl": cont})
    except Exception as e:
        return jsonify({"ok": False, "error": "generate_link_failed", "detail": str(e)}), 500
