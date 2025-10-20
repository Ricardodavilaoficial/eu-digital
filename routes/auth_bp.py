# routes/auth_bp.py
from flask import Blueprint, jsonify, request, current_app
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
    token = hdr.split(" ", 1)[1].strip()
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
        * UPSERT idempotente em profissionais/{uid} (status/emailVerified/verifiedAt/updatedAt)
        * Mescla campos do lead (nome/telefone/cnpj/segmento) se existirem
        * Marca leads/{uid} como status:"consumed", consumedAt
        * Loga evento estruturado
        * Retorna 200 { ok: True, verified: True }
    - Se não verificado:
        * Retorna 200 { ok: True, verified: False }
    - Token inválido/expirado → 401
    """
    try:
        ensure_firebase_admin()

        decoded = _verify_bearer_token()
        if not decoded:
            return jsonify({"ok": False, "error": "missing_or_invalid_token"}), 401

        uid = decoded.get("uid")
        email = (decoded.get("email") or "").strip()
        email_verified = bool(decoded.get("email_verified", False))

        # Em casos raros de defasagem, revalida direto no Admin SDK
        if not email_verified:
            try:
                user_record = fb_auth.get_user(uid)
                email_verified = bool(getattr(user_record, "email_verified", False))
                if not email and getattr(user_record, "email", None):
                    email = user_record.email
            except Exception:
                pass  # segue o fluxo

        if not email_verified:
            # Não verificado ainda — front pode tentar de novo
            return jsonify({"ok": True, "verified": False}), 200

        # ----- Verificado: transação para promover/mesclar e consumir lead -----
        fs = _get_fs()
        prof_ref = fs.collection("profissionais").document(uid)
        lead_ref = fs.collection("leads").document(uid)

        now_iso = _utc_now_iso()
        merged_fields = []
        created_prof = False
        had_lead = False

        @fb_fs.transactional
        def _promote(tx: fb_fs.Transaction):
            nonlocal merged_fields, created_prof, had_lead

            # Snapshots dentro da transação
            prof_snap = prof_ref.get(transaction=tx)
            lead_snap = lead_ref.get(transaction=tx)

            # Dados base de verificação
            base_update = {
                "uid": uid,
                "email": email,
                "status": "verified",
                "emailVerified": True,
                "verifiedAt": now_iso,
                "updatedAt": now_iso,
            }

            # Campos passíveis de merge vindos do lead
            lead_merge = {}
            if lead_snap.exists:
                had_lead = True
                ld = lead_snap.to_dict() or {}
                for k in ("nome", "telefone", "cnpj", "segmento"):
                    v = ld.get(k)
                    if v:
                        lead_merge[k] = v

            if not prof_snap.exists:
                created_prof = True
                base_create = {
                    "createdAt": now_iso,
                    **base_update,
                    **lead_merge
                }
                tx.set(prof_ref, base_create, merge=False)
                merged_fields = sorted(list(lead_merge.keys()))
            else:
                # Atualiza verificação e mescla campos do lead (se existirem)
                to_set = {**base_update}
                if lead_merge:
                    to_set.update(lead_merge)
                    merged_fields = sorted(list(lead_merge.keys()))
                tx.set(prof_ref, to_set, merge=True)

            # Marca lead como consumido (idempotente)
            if had_lead:
                tx.set(lead_ref, {
                    "status": "consumed",
                    "consumedAt": now_iso,
                    "updatedAt": now_iso
                }, merge=True)

        # Executa a transação
        tx = fs.transaction()
        _promote(tx)

        # Log estruturado para observabilidade
        try:
            current_app.logger.info({
                "event": "auth.check_verification",
                "verified": True,
                "uid": uid,
                "hadLead": had_lead,
                "createdProfDoc": created_prof,
                "mergedFields": merged_fields
            })
        except Exception:
            pass

        return jsonify({"ok": True, "verified": True}), 200

    except fb_auth.ExpiredIdTokenError as e:
        return jsonify({"ok": False, "error": "expired_token", "detail": str(e)}), 401
    except Exception as e:
        return jsonify({"ok": False, "error": "check_verification_failed", "detail": str(e)}), 500
