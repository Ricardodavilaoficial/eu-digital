# routes/auth_bp.py
from flask import Blueprint, jsonify, request
from firebase_admin import auth as fb_auth
from services.firebase_admin_init import ensure_firebase_admin

# Firestore (via Admin SDK)
try:
    from firebase_admin import firestore as fb_fs
except Exception:
    fb_fs = None

from datetime import datetime, timezone

auth_bp = Blueprint("auth_bp", __name__)

# ----------------- helpers -----------------

def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def _verify_bearer_token():
    """Extrai e valida o token Bearer do header Authorization; retorna o token decodificado ou None."""
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

def _has_pending_lead_by_uid(fs, uid: str) -> bool:
    """Checa se existe lead pendente para o uid."""
    try:
        snap = fs.collection("leads").document(uid).get()
        if not snap.exists:
            return False
        data = snap.to_dict() or {}
        status = (data.get("status") or "").lower()
        return status in ("pending", "awaiting_verification", "created", "new", "awaiting_email")
    except Exception:
        # Em caso de erro, não bloquear fluxo: considerar que pode haver pendência.
        return True

def _has_pending_lead_by_email(fs, email: str) -> bool:
    """Checa se existe lead pendente para o e-mail."""
    try:
        q = fs.collection("leads").where("email", "==", (email or "").strip().lower()).limit(1)
        docs = list(q.stream())
        if not docs:
            return False
        data = docs[0].to_dict() or {}
        status = (data.get("status") or "").lower()
        return status in ("pending", "awaiting_verification", "created", "new", "awaiting_email")
    except Exception:
        return True

# ----------------- rotas -----------------

@auth_bp.route("/whoami", methods=["GET"])
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


@auth_bp.route("/check-verification", methods=["GET"])
def check_verification():
    """
    Retorna se o e-mail está verificado e, se sim, garante/atualiza profissionais/{uid}
    e marca leads/{uid} como consumed. Método GET p/ facilitar uso no front.
    """
    try:
        ensure_firebase_admin()
        decoded = _verify_bearer_token()
        if not decoded:
            return jsonify({"ok": False, "error": "missing_or_invalid_token"}), 401

        uid = decoded.get("uid")
        email = decoded.get("email") or ""
        email_verified = bool(decoded.get("email_verified", False))

        if not email_verified:
            # Revalida direto no Admin (estado mais atual)
            try:
                user_record = fb_auth.get_user(uid)
                email_verified = bool(getattr(user_record, "email_verified", False))
                if not email and getattr(user_record, "email", None):
                    email = user_record.email
            except Exception:
                pass

        if not email_verified:
            return jsonify({"ok": True, "verified": False}), 200

        # Se verificado: upsert profissionais/{uid} e consumir lead, se existir
        try:
            fs = _get_fs()
            prof_ref = fs.collection("profissionais").document(uid)
            lead_ref = fs.collection("leads").document(uid)

            now_iso = _utc_now_iso()
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
                base_create = {"createdAt": now_iso, **base_update}
                # Tenta herdar campos do lead
                try:
                    lead_snap = lead_ref.get()
                    if lead_snap.exists:
                        lead_data = lead_snap.to_dict() or {}
                        for k in ("nome", "telefone", "cnpj", "segmento"):
                            if k in lead_data and lead_data[k]:
                                base_create[k] = lead_data[k]
                        # Marca lead como consumido
                        lead_ref.set({
                            **lead_data,
                            "status": "consumed",
                            "consumedAt": now_iso
                        }, merge=True)
                except Exception:
                    pass
                prof_ref.set(base_create, merge=False)
            else:
                prof_ref.set(base_update, merge=True)
        except Exception:
            # Não falhar a verificação por erro de persistência; reportar apenas verified=true
            pass

        return jsonify({"ok": True, "verified": True}), 200

    except Exception as e:
        # Expired token e outras falhas caem aqui; manter mensagem consistente
        return jsonify({"ok": False, "error": "check_verification_failed", "detail": str(e)}), 500


# aceita /reclaim-email e /reclaim-email/ (POST)
@auth_bp.route("/reclaim-email", methods=["POST"])
@auth_bp.route("/reclaim-email/", methods=["POST"])
def reclaim_email():
    """
    Apaga a conta não-verificada para permitir novo cadastro (lead pendente).
    Não exige Bearer; recebe {"email": "..."} no body.
    """
    try:
        ensure_firebase_admin()
        fs = _get_fs()

        data = request.get_json(force=True, silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        if not email:
            return jsonify({"ok": False, "error": "email-required"}), 400

        # Busca usuário pelo e-mail
        try:
            user_record = fb_auth.get_user_by_email(email)
        except fb_auth.UserNotFoundError:
            return jsonify({"ok": False, "reason": "not-found"}), 200
        except Exception as e:
            return jsonify({"ok": False, "error": "admin-get-user-failed", "detail": str(e)}), 200

        # Se já verificado, não faz sentido "reclamar"
        if getattr(user_record, "email_verified", False):
            return jsonify({"ok": False, "reason": "verified-account"}), 200

        # Só permite se houver lead pendente
        has_pending = _has_pending_lead_by_uid(fs, user_record.uid)
        if not has_pending:
            has_pending = _has_pending_lead_by_email(fs, email)

        if not has_pending:
            return jsonify({"ok": False, "reason": "no-pending-lead"}), 200

        # Deleta usuário para liberar novo fluxo
        try:
            fb_auth.delete_user(user_record.uid)
        except fb_auth.UserNotFoundError:
            pass
        except Exception as e:
            return jsonify({"ok": False, "error": "delete-failed", "detail": str(e)}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        return jsonify({"ok": False, "error": "internal", "detail": str(e)}), 200
