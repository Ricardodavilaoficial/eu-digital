import os
import functools
from flask import request, g, jsonify
from firebase_admin import auth
from .db import get_doc, set_doc, now_ts

ADMIN_CLAIM_KEY = "role"
ADMIN_CLAIM_VALUE = "admin"

def _verify_token_from_header():
    """Lê o Bearer token do Firebase Auth e decodifica."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1]
    decoded = auth.verify_id_token(token)
    return {"uid": decoded.get("uid"), "email": decoded.get("email"), "claims": decoded}

def auth_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        # BYPASS DEV (opcional): set DEV_FAKE_UID para testar sem login real
        fake_uid = os.getenv("DEV_FAKE_UID")
        if fake_uid:
            g.user = type("User", (), {"uid": fake_uid, "email": "dev@local", "claims": {}})
            prof_path = f"profissionais/{g.user.uid}"
            if get_doc(prof_path) is None:
                set_doc(prof_path, {
                    "perfil": {"segmento": None, "especializacao": None},
                    "plano": {"status": "bloqueado", "origem": None, "expiraEm": None, "quotaMensal": 0},
                    "createdAt": now_ts()
                })
            return fn(*args, **kwargs)

        try:
            user = _verify_token_from_header()
        except Exception:
            return jsonify({"erro": "auth/invalid-token"}), 401
        if not user:
            return jsonify({"erro": "auth/missing-token"}), 401

        g.user = type("User", (), user)

        # Bootstrap do documento do profissional, se não existir
        prof_path = f"profissionais/{g.user.uid}"
        if get_doc(prof_path) is None:
            set_doc(prof_path, {
                "perfil": {"segmento": None, "especializacao": None},
                "plano": {"status": "bloqueado", "origem": None, "expiraEm": None, "quotaMensal": 0},
                "createdAt": now_ts()
            })
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        # Garante que está autenticado antes
        resp = auth_required(lambda *a, **k: None)()
        if resp is not None:
            return resp  # erro de auth
        claims = getattr(g.user, "claims", {})
        if claims.get(ADMIN_CLAIM_KEY) != ADMIN_CLAIM_VALUE:
            return jsonify({"erro": "auth/not-admin"}), 403
        return fn(*args, **kwargs)
    return wrapper
