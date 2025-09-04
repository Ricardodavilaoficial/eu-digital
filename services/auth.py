# services/auth.py — auth + decorator admin_required (produção)
from __future__ import annotations

import os, json
from functools import wraps
from types import SimpleNamespace
from flask import request, jsonify, g

# Firebase Admin
import firebase_admin
from firebase_admin import auth as fb_auth, credentials

# --- Inicialização do Firebase Admin ---
if not firebase_admin._apps:
    cred_json = (
        os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    )
    try:
        if cred_json:
            cred = credentials.Certificate(json.loads(cred_json))
            firebase_admin.initialize_app(cred)
        else:
            # Tenta credencial padrão (por exemplo, variável GOOGLE_APPLICATION_CREDENTIALS apontando para arquivo)
            firebase_admin.initialize_app()
    except Exception:
        # Fallback silencioso, mas o verify_id_token vai falhar se não houver credencial válida
        firebase_admin.initialize_app()

def _get_bearer() -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None

def _allowlist() -> set[str]:
    allow = os.getenv("ADMIN_UID_ALLOWLIST") or os.getenv("ADMIN_UID") or ""
    return {x.strip() for x in allow.split(",") if x.strip()}

def _decode_token(token: str) -> dict:
    # check_revoked=True dá mais segurança (requer RTDB/Firestore rules para revogação, se em uso)
    return fb_auth.verify_id_token(token, check_revoked=True)

def admin_required(fn):
    """
    Exige:
      - Authorization: Bearer <ID_TOKEN Firebase>
      - UID presente em ADMIN_UID_ALLOWLIST

    Bypass de dev só é permitido se DEV_FORCE_ADMIN == "1" E DEV_FAKE_UID definido.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _get_bearer()
        allow = _allowlist()

        if not token:
            # Bypass só se explicitamente forçado (nunca em produção)
            if os.getenv("DEV_FORCE_ADMIN", "0") == "1" and os.getenv("DEV_FAKE_UID"):
                g.user = SimpleNamespace(uid=os.getenv("DEV_FAKE_UID"), email="dev@local")
            else:
                return jsonify({"erro": "Auth obrigatório"}), 401
        else:
            try:
                decoded = _decode_token(token)
                uid = decoded.get("uid")
                email = decoded.get("email")
                if not uid:
                    return jsonify({"erro": "Token inválido (sem UID)"}), 401
                g.user = SimpleNamespace(uid=uid, email=email)
            except Exception as e:
                return jsonify({"erro": f"Token inválido: {e}"}), 401

        # Checagem de allowlist
        if allow and getattr(g.user, "uid", None) not in allow:
            return jsonify({"erro": "Acesso restrito a administradores"}), 403

        return fn(*args, **kwargs)
    return wrapper
