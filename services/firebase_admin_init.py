# services/firebase_admin_init.py
import os
import json
import firebase_admin
from firebase_admin import credentials

def ensure_firebase_admin():
    """
    Inicializa o Firebase Admin uma única vez usando a ENV
    FIREBASE_SERVICE_ACCOUNT_JSON (conteúdo JSON da chave).
    """
    if firebase_admin._apps:
        return
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        # Erro controlado para não matar o worker
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON não configurado no ambiente.")
    data = json.loads(raw)
    cred = credentials.Certificate(data)
    firebase_admin.initialize_app(cred)
