import os
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import firestore as fa_firestore

# Inicializa o Firebase Admin (usa GOOGLE_APPLICATION_CREDENTIALS/ADC)
if not firebase_admin._apps:
    firebase_admin.initialize_app()

# Client do Firestore para usar nos outros módulos
db = fa_firestore.client()

def now_ts():
    return datetime.now(timezone.utc).isoformat()

def get_doc(path: str):
    snap = db.document(path).get()
    return snap.to_dict() if snap.exists else None

def set_doc(path: str, data: dict):
    db.document(path).set(data, merge=True)

def update_doc(path: str, data: dict):
    db.document(path).set(data, merge=True)

def add_doc(path: str, data: dict):
    ref = db.collection(path).document()
    ref.set(data)
    return ref.id

def query_collection(path: str, **filters):
    ref = db.collection(path)
    for k, v in filters.items():
        ref = ref.where(k, "==", v)
    return [{"id": d.id, **d.to_dict()} for d in ref.stream()]
