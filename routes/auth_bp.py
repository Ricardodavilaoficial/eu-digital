# routes/auth_bp.py
from flask import Blueprint, jsonify, request
from firebase_admin import auth as fb_auth
from services.firebase_admin_init import ensure_firebase_admin

# Firestore (via Admin SDK)
try:
    from firebase_admin import firestore as fb_fs
except Exception:  # fallback defensivo (não deve ocorrer se ensure_firebase_admin for chamado)
    fb_fs = None

from datetime import datetime, timezone

auth_bp = Blueprint("auth_bp", __name__)

def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def _verify_bearer_token():
    """Extrai e valida o token Bearer do header Authorization"""
    hdr = request.headers.get("Authorization", "")
    if not hdr.startswith("Bearer "):
        return None
    token = hdr.split(" ", 1)[1]
    return fb_auth.verify_id_token(token)

def _get_fs():
    """Retorna o client do Firestore via Admin SDK."""
    if fb_fs is None:
        raise RuntimeError("Firestore Admin SDK indisponível.")
    return fb_fs.client()

@auth_bp.route("/auth/whoami", methods=["GET"])
def whoami():
    """
    Endpoint protegido para validar um ID Token Firebase.
    Retorna { ok, uid, email, provider } se o token for válido.
    """
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
        # Expired token, signature error etc. → 401 ajuda o front a renovar o token
        return jsonify({"ok": False, "error": str(e)}), 401


@auth_bp.route("/auth/check-verification", methods=["POST"])
def check_verification():
    """
    Conclui (ou confirma) a verificação de e-mail.

    Comportamento:
    - Valida o Bearer (ID token).
    - Checa se o e-mail está verificado (decoded token; fallback: Admin get_user).
    - Se verificado:
        * Faz UPSERT idempotente em profissionais/{uid}
          - cria se não existir (com mínimos) OU atualiza verifiedAt/status/email
          - opcionalmente consome 'lead' em leads/{uid}, se existir
        * Retorna 200 { ok: True, verified: True }
    - Se não verificado:
        * Retorna 200 { ok: True, verified: False }
    - Token inválido → 401
    """
    try:
        ensure_firebase_admin()

        decoded = _verify_bearer_token()
        if not decoded:
            return jsonify({"ok": False, "error": "missing_or_invalid_token"}), 401

        uid = decoded.get("uid")
        email = decoded.get("email") or ""
        email_verified = bool(decoded.get("email_verified", False))

        # Em casos raros de defasagem, revalida direto no Admin SDK
        if not email_verified:
            try:
                user_record = fb_auth.get_user(uid)
                email_verified = bool(getattr(user_record, "email_verified", False))
                if email == "" and getattr(user_record, "email", None):
                    email = user_record.email
            except Exception:
                # se falhar, tratamos abaixo como não verificado
                pass

        if not email_verified:
            # Não verificado ainda — front pode tentar de novo
            return jsonify({"ok": True, "verified": False}), 200

        # ----- Verificado: upsert idempotente do usuário (SEM transação) -----
        fs = _get_fs()
        prof_ref = fs.collection("profissionais").document(uid)
        lead_ref = fs.collection("leads").document(uid)  # opcional: onde /api/cadastro gravou dados temporários

        now_iso = _utc_now_iso()

        # snapshot atual do profissional
        prof_snap = prof_ref.get()

        base_update = {
            "uid": uid,
            "email": email,
            "status": "verified",
            "emailVerified": True,
            "verifiedAt": now_iso,
            "updatedAt": now_iso,
        }

        if not prof_snap.exists:
            # mínimos ao criar
            base_create = {
                "createdAt": now_iso,
                **base_update
            }

            # tenta consumir dados do lead, se existir
            try:
                lead_snap = lead_ref.get()
                if lead_snap.exists:
                    lead_data = lead_snap.to_dict() or {}
                    for k in ("nome", "telefone", "cnpj", "segmento"):
                        if k in lead_data and lead_data[k]:
                            base_create[k] = lead_data[k]
                    # marca o lead como consumido (opcional)
                    lead_ref.set({
                        **lead_data,
                        "status": "consumed",
                        "consumedAt": now_iso
                    }, merge=True)
            except Exception:
                # se falhar o lead, segue sem bloquear a verificação
                pass

            # cria o doc do profissional
            prof_ref.set(base_create, merge=False)

        else:
            # já existe → apenas atualiza campos de verificação
            prof_ref.set(base_update, merge=True)

        return jsonify({"ok": True, "verified": True}), 200

    except fb_auth.ExpiredIdTokenError as e:
        # Semântica melhor para token vencido
        return jsonify({"ok": False, "error": "expired_token", "detail": str(e)}), 401
    except Exception as e:
        # Qualquer exceção inesperada → reporta sem vazar stack
        return jsonify({"ok": False, "error": "check_verification_failed", "detail": str(e)}), 500
