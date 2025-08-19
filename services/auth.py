import os
import functools
from flask import request, g, jsonify
from firebase_admin import auth
from .db import get_doc, set_doc, now_ts

ADMIN_CLAIM_KEY = "role"
ADMIN_CLAIM_VALUE = "admin"

def _verify_token_from_header():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1]
    decoded = auth.verify_id_token(token)
    return {
        "uid": decoded.get("uid"),
        "email": decoded.get("email"),
        "claims": decoded,
    }

def _dev_user():
    dev_uid = os.getenv("DEV_FAKE_UID", "").strip()
    if not dev_uid:
        return None
    return {
        "uid": dev_uid,
        "email": "dev@local",
        # para poder chamar /admin/cupons nos testes:
        "claims": {ADMIN_CLAIM_KEY: os.getenv("DEV_FAKE_ROLE", ADMIN_CLAIM_VALUE)}
    }

def auth_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = None
        try:
            user = _verify_token_from_header()
        except Exception:
            user = None
        if not user:
            # fallback DEV
            user = _dev_user()
        if not user:
            return jsonify({"erro":"auth/missing-or-invalid-token"}), 401

        g.user = type("User", (), user)

        # bootstrap do documento do profissional, se não existir
        prof_path = f"profissionais/{g.user.uid}"
        if get_doc(prof_path) is None:
            set_doc(prof_path, {
                "perfil": {"segmento": None, "especializacao": None},
                "plano": {"status":"bloqueado", "origem": None, "expiraEm": None, "quotaMensal": 0},
                "createdAt": now_ts()
            })
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        resp = auth_required(lambda: None)()
        if resp is not None:
            return resp
        claims = getattr(g.user, "claims", {}) or {}
        if claims.get(ADMIN_CLAIM_KEY) != ADMIN_CLAIM_VALUE:
            return jsonify({"erro":"auth/not-admin"}), 403
        return fn(*args, **kwargs)
    return wrapper
