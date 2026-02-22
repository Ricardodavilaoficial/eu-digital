# services/gcp_creds.py
import os, json
from typing import Optional, Tuple
from google.oauth2 import service_account

# Modo de credenciais:
# - "adc_only": exige GOOGLE_APPLICATION_CREDENTIALS (arquivo) — recomendado em produção
# - "adc_or_inline": tenta arquivo; se não houver, usa FIREBASE_SERVICE_ACCOUNT_JSON (inline)
def _mode() -> str:
    return (os.getenv("GCP_CREDENTIALS_MODE") or "adc_only").strip().lower()

def _gac_file() -> Optional[str]:
    """
    Retorna o caminho do GOOGLE_APPLICATION_CREDENTIALS apenas se existir de verdade.
    Evita o caso Cloud Run: GAC apontando para algo inválido (ex.: JSON em env),
    que faz o SDK tentar abrir "um arquivo" com o conteúdo do JSON.
    """
    gac = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if not gac:
        return None
    return gac if os.path.exists(gac) else None

def _inline_creds() -> Tuple[Optional[service_account.Credentials], Optional[str]]:
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None, None
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info)
    project = info.get("project_id")
    return creds, project

def get_firestore_client(project: Optional[str] = None):
    # Firestore deve ser via firebase-admin (FIREBASE_SERVICE_ACCOUNT_JSON).
    # Este módulo existe para credenciais GCP (GCS/Tasks), não para Firestore.
    raise RuntimeError("firestore_via_adc_disabled_use_firebase_admin")

def get_storage_client():
    from google.cloud import storage

    # 1) Preferir credencial inline quando disponível (Cloud Run + Signed URL V4)
    creds, project = _inline_creds()
    if creds:
        return storage.Client(project=project, credentials=creds)

    # 2) Arquivo via GOOGLE_APPLICATION_CREDENTIALS (Secret File)
    if _gac_file():
        return storage.Client()

    # 3) Opcional: tentar ADC "padrão" (se tiver)
    try:
        return storage.Client()
    except Exception:
        pass

    raise RuntimeError("ADC not configured for Storage (set GOOGLE_APPLICATION_CREDENTIALS or use adc_or_inline).")
