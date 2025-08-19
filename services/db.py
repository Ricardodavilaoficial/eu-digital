import os, json
import firebase_admin
from firebase_admin import credentials, firestore as fa_firestore
from datetime import datetime

def now_ts():
    return datetime.utcnow().isoformat() + "Z"

def _init_firebase():
    """
    Ordem de prioridade (para evitar variáveis antigas quebrando):
    1) FIREBASE_SERVICE_ACCOUNT_JSON (JSON colado na variável)
    2) GOOGLE_APPLICATION_CREDENTIALS (caminho de arquivo existente)
    3) Application Default Credentials
    """
    if firebase_admin._apps:
        return firebase_admin.get_app()

    sa_json = (os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
    sa_path = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()

    cred = None
    if sa_json:
        try:
            cred = credentials.Certificate(json.loads(sa_json))
            print("FIREBASE: using FIREBASE_SERVICE_ACCOUNT_JSON")
        except Exception as e:
            print("FIREBASE: invalid FIREBASE_SERVICE_ACCOUNT_JSON:", e)

    if cred is None and sa_path:
        if os.path.exists(sa_path):
            cred = credentials.Certificate(sa_path)
            print(f"FIREBASE: using GOOGLE_APPLICATION_CREDENTIALS file: {sa_path}")
        else:
            # Loga para sabermos se houver resto de caminho antigo
            print(f"FIREBASE: file not found at GOOGLE_APPLICATION_CREDENTIALS: {sa_path}")

    if cred:
        return firebase_admin.initialize_app(cred)
    else:
        print("FIREBASE: using Application Default Credentials")
        return firebase_admin.initialize_app()

# Inicializa e cria o client
_init_firebase()
db = fa_firestore.client()

def get_doc(path: str):
    snap = db.document(path).get()
    return snap.to_dict() if snap.exists else None

def set_doc(path: str, data: dict):
    db.document(path).set(data, merge=True)

def update_doc(path: str, data: dict):
    db.document(path).set(data, merge=True)
