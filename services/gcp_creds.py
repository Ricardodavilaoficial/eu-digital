# services/gcp_creds.py
import os, json
from typing import Optional, Tuple

from google.oauth2 import service_account

# Modos:
# - "workload_identity": usa ADC do runtime (Cloud Run SA / Workload Identity) — RECOMENDADO
# - "adc_or_inline": tenta runtime/arquivo; se não houver, usa FIREBASE_SERVICE_ACCOUNT_JSON (inline)
# - "inline_only": exige FIREBASE_SERVICE_ACCOUNT_JSON (sem ADC)
def _mode() -> str:
    return (os.getenv("GCP_CREDENTIALS_MODE") or "workload_identity").strip().lower()

def _gac_file() -> Optional[str]:
    """
    Retorna o caminho do GOOGLE_APPLICATION_CREDENTIALS apenas se existir de verdade.
    Evita o caso Cloud Run: GAC apontando para algo inválido.
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

def _runtime_creds() -> Tuple[object, Optional[str]]:
    """
    ADC do runtime (Workload Identity / Cloud Run service account).
    Não usa private_key local.
    """
    import google.auth
    creds, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return creds, project

def get_firestore_client(project: Optional[str] = None):
    # Firestore deve ser via firebase-admin.
    raise RuntimeError("firestore_via_adc_disabled_use_firebase_admin")

def get_storage_client():
    from google.cloud import storage

    mode = _mode()

    # 1) Cloud Run "certo": Workload Identity (ADC runtime)
    if mode in ("workload_identity", "adc_only", "adc_or_inline"):
        try:
            creds, project = _runtime_creds()
            return storage.Client(project=project, credentials=creds)
        except Exception:
            # se o modo for estrito, não cai adiante
            if mode in ("workload_identity", "adc_only"):
                raise

    # 2) Arquivo via GOOGLE_APPLICATION_CREDENTIALS (se existir de verdade)
    if mode in ("adc_only", "adc_or_inline"):
        if _gac_file():
            return storage.Client()

    # 3) Inline (JSON em env) — fallback controlado
    if mode in ("adc_or_inline", "inline_only"):
        creds, project = _inline_creds()
        if creds:
            return storage.Client(project=project, credentials=creds)

    raise RuntimeError(
        f"Storage credentials not configured. mode={mode}. "
        "Use workload_identity (Cloud Run SA), or set FIREBASE_SERVICE_ACCOUNT_JSON (inline), "
        "or provide GOOGLE_APPLICATION_CREDENTIALS pointing to an existing file."
    )