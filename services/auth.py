# services/auth.py — auth + decorators (produção)
from __future__ import annotations

import os
import re
import json
import logging
from functools import wraps
from types import SimpleNamespace
from flask import request, jsonify, g

# Firebase Admin
import firebase_admin
from firebase_admin import auth as fb_auth, credentials

# -----------------------------------------------------------------------------
# Logging (discreto)
# -----------------------------------------------------------------------------
logger = logging.getLogger("auth")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] auth: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


# -----------------------------------------------------------------------------
# Ambiente / Produção
# -----------------------------------------------------------------------------
def _is_production() -> bool:
    """
    Detecta produção:
      - ENV in {"prod", "production"} OU
      - RENDER == "true" (padrão do Render.com)
    """
    env = (os.getenv("ENV") or os.getenv("FLASK_ENV") or "").lower()
    if env in {"prod", "production"}:
        return True
    if (os.getenv("RENDER") or "").lower() == "true":
        return True
    return False


# -----------------------------------------------------------------------------
# Inicialização do Firebase Admin
# -----------------------------------------------------------------------------
def _init_firebase_admin():
    if firebase_admin._apps:
        return
    cred_json = (
        os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    )
    try:
        if cred_json:
            cred = credentials.Certificate(json.loads(cred_json))
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin inicializado via JSON embutido.")
        else:
            # Usa credencial padrão do ambiente
            firebase_admin.initialize_app()
            logger.info("Firebase Admin inicializado via credenciais padrão.")
    except Exception as e:
        # Não explode a inicialização; verify_id_token falhará se não houver credencial válida
        logger.warning(f"Falha ao inicializar Firebase Admin (seguirá tentando no verify): {e}")
        try:
            firebase_admin.initialize_app()
            logger.info("Firebase Admin fallback: inicialização padrão.")
        except Exception as e2:
            logger.error(f"Falha também no fallback do Firebase Admin: {e2}")


_init_firebase_admin()


# -----------------------------------------------------------------------------
# Helpers internos
# -----------------------------------------------------------------------------
def _get_bearer() -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return None


def _allowlist() -> set[str]:
    """
    Lê allowlist de ADMIN_UID_ALLOWLIST (ou, por retrocompatibilidade, ADMIN_UID).
    Aceita vírgulas, espaços e quebras de linha como separadores.
    """
    allow_raw = os.getenv("ADMIN_UID_ALLOWLIST") or os.getenv("ADMIN_UID") or ""
    if not allow_raw.strip():
        return set()
    parts = [p.strip() for p in re.split(r"[,\s]+", allow_raw) if p.strip()]
    return set(parts)


# -----------------------------------------------------------------------------
# Verificação forte de ID Token
# -----------------------------------------------------------------------------
def verify_id_token_strict(token: str) -> dict:
    """
    Verifica o ID Token do Firebase *com revogação*.
    Lança exceções específicas do firebase_admin em falhas.
    """
    _init_firebase_admin()
    return fb_auth.verify_id_token(token, check_revoked=True)


def get_verified_user_from_request() -> SimpleNamespace | None:
    """
    Retorna SimpleNamespace(uid, email, claims) se o Authorization: Bearer for válido.
    Caso contrário, retorna None. Não levanta exceções.
    """
    token = _get_bearer()
    if not token:
        return None
    try:
        decoded = verify_id_token_strict(token)
        uid = decoded.get("uid")
        if not uid:
            return None
        return SimpleNamespace(uid=uid, email=decoded.get("email"), claims=decoded)
    except Exception:
        return None


def get_verified_uid_from_request() -> str | None:
    """
    Retorna UID verificado do Authorization: Bearer, ou None se inválido/ausente.
    """
    user = get_verified_user_from_request()
    return user.uid if user else None


def current_uid() -> str | None:
    """
    UID atual já determinado e preso no 'g' (via decorators). Pode ser None.
    """
    return getattr(getattr(g, "user", None), "uid", None)


def is_admin(uid: str | None) -> bool:
    if not uid:
        return False
    return uid in _allowlist()


# -----------------------------------------------------------------------------
# Decorators
# -----------------------------------------------------------------------------
def auth_required(fn):
    """
    Exige Authorization: Bearer <ID_TOKEN Firebase> válido.
    Bypass de DEV (apenas fora de produção):
      - DEV_FAKE_UID definido E DEV_FORCE_ADMIN == "1"
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _get_bearer()
        if not token:
            if (
                not _is_production()
                and os.getenv("DEV_FORCE_ADMIN", "0") == "1"
                and os.getenv("DEV_FAKE_UID")
            ):
                # Bypass DEV (fora de produção)
                g.user = SimpleNamespace(uid=os.getenv("DEV_FAKE_UID"), email="dev@local")
            else:
                return jsonify({"erro": "Não autenticado"}), 401
        else:
            try:
                decoded = verify_id_token_strict(token)
                uid = decoded.get("uid")
                if not uid:
                    return jsonify({"erro": "Token inválido (sem UID)"}), 401
                g.user = SimpleNamespace(uid=uid, email=decoded.get("email"), claims=decoded)
            except fb_auth.RevokedIdTokenError:
                return jsonify({"erro": "Token revogado"}), 401
            except fb_auth.ExpiredIdTokenError:
                return jsonify({"erro": "Token expirado"}), 401
            except Exception:
                # sem vazar detalhes
                return jsonify({"erro": "Token inválido"}), 401

        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    """
    Requisitos:
      - Header: Authorization: Bearer <ID_TOKEN Firebase>
      - UID presente em ADMIN_UID_ALLOWLIST

    Bypass de dev:
      - Permitido somente se DEV_FORCE_ADMIN == "1" E DEV_FAKE_UID definido
      - E NÃO estiver em produção
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _get_bearer()
        allow = _allowlist()

        # Se allowlist estiver vazia em produção, desabilita o admin por segurança
        if _is_production() and not allow:
            logger.warning("Tentativa de acesso admin com allowlist vazia (produção).")
            return jsonify({"erro": "Admin desabilitado (allowlist vazia)"}), 403

        # Sem token → considerar bypass de DEV (apenas fora de produção)
        if not token:
            if (
                os.getenv("DEV_FORCE_ADMIN", "0") == "1"
                and os.getenv("DEV_FAKE_UID")
                and not _is_production()
            ):
                g.user = SimpleNamespace(uid=os.getenv("DEV_FAKE_UID"), email="dev@local")
                logger.info("Bypass DEV aplicado (fora de produção).")
            else:
                return jsonify({"erro": "Auth obrigatório"}), 401
        else:
            try:
                decoded = verify_id_token_strict(token)
                uid = decoded.get("uid")
                email = decoded.get("email")
                if not uid:
                    return jsonify({"erro": "Token inválido (sem UID)"}), 401
                g.user = SimpleNamespace(uid=uid, email=email, claims=decoded)
            except fb_auth.RevokedIdTokenError:
                return jsonify({"erro": "Token revogado"}), 401
            except fb_auth.ExpiredIdTokenError:
                return jsonify({"erro": "Token expirado"}), 401
            except Exception as e:
                logger.warning(f"Falha verify_id_token (discreto): {type(e).__name__}")
                return jsonify({"erro": "Token inválido"}), 401

        # Checagem de allowlist
        uid = getattr(g.user, "uid", None)
        if allow and uid not in allow:
            logger.info("Acesso negado: UID não allowlisted.")
            return jsonify({"erro": "Acesso restrito a administradores"}), 403

        g.admin = True
        return fn(*args, **kwargs)

    return wrapper
