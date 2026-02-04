# services/voice_metadata.py
# Persiste metadados da última voz enviada no Firestore (best-effort)

import logging

from services.firebase_admin_init import ensure_firebase_admin  # type: ignore
from firebase_admin import firestore as fb_firestore  # type: ignore

def _get_db():
    try:
        ensure_firebase_admin()
        return fb_firestore.client()
    except Exception as e:
        logging.warning("[voice_metadata] Firestore indisponível: %s", e)
        return None

def record_last_voice_url(uid: str, url: str, mime: str, bytes_len: int, duration_sec: int) -> None:
    """
    Grava em profissionais/<uid> o bloco `vozClonada` com informações da última amostra.
    Best-effort: se Firestore não estiver configurado, apenas loga e retorna.
    """
    if not uid or uid == "sem_uid":
        logging.info("[voice_metadata] uid vazio/sem_uid — ignorando persistência.")
        return

    db = _get_db()
    if not db:
        logging.info("[voice_metadata] Firestore indisponível — skip persistência (uid=%s)", uid)
        return

    try:
        db.collection("profissionais").document(uid).set({
            "vozClonada": {
                "arquivoUrl": url,
                "mime": mime,
                "bytes": int(bytes_len or 0),
                "duration_sec": int(duration_sec or 0),
                "updatedAt": fb_firestore.SERVER_TIMESTAMP,
            }
        }, merge=True)
        logging.info("[voice_metadata] Persistido vozClonada p/ uid=%s", uid)
    except Exception as e:
        logging.warning("[voice_metadata] Falha ao persistir vozClonada (uid=%s): %s", uid, e)

__all__ = ["record_last_voice_url"]
