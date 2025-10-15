# services/gcp_creds.py
import os, json
from typing import Optional, Tuple
from google.oauth2 import service_account

# Modo de credenciais:
# - "adc_only": exige GOOGLE_APPLICATION_CREDENTIALS (arquivo) — recomendado em produção
# - "adc_or_inline": tenta arquivo; se não houver, usa FIREBASE_SERVICE_ACCOUNT_JSON (inline)
_MODE = (os.getenv("GCP_CREDENTIALS_MODE") or "adc_only").strip().lower()

def _inline_creds() -> Tuple[Optional[service_account.Credentials], Optional[str]]:
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None, None
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info)
    project = info.get("project_id")
    return creds, project

def get_firestore_client():
    from google.cloud import firestore
    gac = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if gac:
        # ADC via arquivo (Secret File)
        return firestore.Client()
    if _MODE == "adc_or_inline":
        creds, project = _inline_creds()
        if creds:
            return firestore.Client(project=project, credentials=creds)
    raise RuntimeError("ADC not configured for Firestore (set GOOGLE_APPLICATION_CREDENTIALS or use adc_or_inline).")

def get_storage_client():
    from google.cloud import storage
    gac = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if gac:
        # ADC via arquivo (Secret File)
        return storage.Client()
    if _MODE == "adc_or_inline":
        creds, project = _inline_creds()
        if creds:
            return storage.Client(project=project, credentials=creds)
    raise RuntimeError("ADC not configured for Storage (set GOOGLE_APPLICATION_CREDENTIALS or use adc_or_inline).")
