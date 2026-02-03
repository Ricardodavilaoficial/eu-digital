# services/firebase_admin_init.py
# HOTFIX v2 — inicialização segura do Firebase Admin SDK com fallback e erro amigável.
#
# Se init falhar, levanta RuntimeError("firebase_admin_init_failed") para ser tratado.

from __future__ import annotations

import os, json, logging
import firebase_admin
from firebase_admin import credentials

logger = logging.getLogger(__name__)

def ensure_firebase_admin() -> None:
    try:
        firebase_admin.get_app()
        return
    except Exception:
        pass

    try:
        inline = (os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
        if inline:
            info = json.loads(inline)
            logger.info("[FIREBASE] Usando credencial inline (env JSON). project_id=%s client_email=%s",
                        info.get("project_id"), info.get("client_email"))
            cred = credentials.Certificate(info)
            firebase_admin.initialize_app(cred)
            return

        path = (os.environ.get("GOOGLE_APPLICATION_CREDENTIAL") or
                os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
        if path:
            cred = credentials.Certificate(path)
            firebase_admin.initialize_app(cred)
            return

        firebase_admin.initialize_app()
        return
    except Exception as e:
        raise RuntimeError("firebase_admin_init_failed") from e
