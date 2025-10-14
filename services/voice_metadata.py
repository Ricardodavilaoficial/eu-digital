# services/voice_metadata.py
# Persiste metadados da última voz enviada no Firestore (best-effort)

import logging

try:
    from google.cloud import firestore  # requer google-cloud-firestore no requirements
except Exception as e:
    firestore = None
    logging.warning("[voice_metadata] Firestore SDK indisponível: %s", e)

def _get_db():
    if firestore is None:
        return None
    try:
        return firestore.Client()
    except Exception as e:
        logging.warning("[voice_metadata] Firestore Client falhou: %s", e)
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
                "updatedAt": firestore.SERVER_TIMESTAMP,
            }
        }, merge=True)
        logging.info("[voice_metadata] Persistido vozClonada p/ uid=%s", uid)
    except Exception as e:
        logging.warning("[voice_metadata] Falha ao persistir vozClonada (uid=%s): %s", uid, e)

__all__ = ["record_last_voice_url"]
