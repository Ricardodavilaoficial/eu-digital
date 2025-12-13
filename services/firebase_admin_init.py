# services/firebase_admin_init.py
# NOVO — inicialização segura do Firebase Admin SDK (para rotas que validam Bearer).
#
# Evita erro: "The default Firebase app does not exist. Make sure to initialize the SDK..."
#
# Suporta:
# - FIREBASE_SERVICE_ACCOUNT_JSON (string JSON completa)
# - GOOGLE_APPLICATION_CREDENTIAL (path, ex.: /etc/secrets/gcp_sa.json)
# - GOOGLE_APPLICATION_CREDENTIALS (fallback)
#
# Não altera rotas existentes.

from __future__ import annotations

import os, json
import firebase_admin
from firebase_admin import credentials

def ensure_firebase_admin() -> None:
    try:
        firebase_admin.get_app()
        return
    except Exception:
        pass

    inline = (os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
    if inline:
        cred = credentials.Certificate(json.loads(inline))
        firebase_admin.initialize_app(cred)
        return

    path = (os.environ.get("GOOGLE_APPLICATION_CREDENTIAL") or
            os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if path:
        cred = credentials.Certificate(path)
        firebase_admin.initialize_app(cred)
        return

    firebase_admin.initialize_app()
