# services/voice_kickoff.py
# -*- coding: utf-8 -*-
"""
Kickoff interno (server-side) do processamento de voz após ativação (cupom/Stripe).

Objetivo:
- Não depender de frontend, CMD, sync/force vindo do usuário.
- Determinístico: usa lastAudioGcsPath gravado pelo webhook em profissionais/{uid}/voz/whatsapp.
- Seguro: cria lock best-effort para evitar processar duas vezes em paralelo.
- Best-effort: nunca quebra o fluxo chamador.
"""

from __future__ import annotations

import time
from typing import Optional, Dict, Any

import requests

try:
    from google.cloud import firestore
except Exception:
    firestore = None  # type: ignore

# Importa helpers internas do processador (sem HTTP)
# Ajuste o import conforme seu layout (no seu repo parece "routes/...")
try:
    from routes import voz_process_bp as vp  # type: ignore
except Exception:
    # fallback caso o import seja direto
    import routes.voz_process_bp as vp  # type: ignore


def _db():
    if firestore is None:
        return None
    # Reusa o mesmo project/client do módulo voz_process_bp quando possível
    try:
        return vp.db  # type: ignore
    except Exception:
        return firestore.Client()  # type: ignore


def _get_prof_doc(uid: str) -> Optional[Dict[str, Any]]:
    db = _db()
    if not db or not uid:
        return None
    try:
        snap = db.collection("profissionais").document(uid).get()
        return snap.to_dict() if snap.exists else None
    except Exception:
        return None


def _already_ready(prof: Optional[Dict[str, Any]]) -> bool:
    try:
        vc = (prof or {}).get("vozClonada") or {}
        return (vc.get("status") == "ready") and bool(vc.get("voiceId"))
    except Exception:
        return False


def _try_lock(uid: str, ttl_seconds: int = 600) -> bool:
    """
    Lock best-effort: cria doc profissionais/{uid}/voz/process_lock
    Falha se já existe (concorrência). TTL lógico no payload.
    """
    db = _db()
    if not db or not uid:
        return False

    try:
        ref = (
            db.collection("profissionais")
            .document(uid)
            .collection("voz")
            .document("process_lock")
        )

        now = int(time.time())
        payload = {
            "createdAt": firestore.SERVER_TIMESTAMP,  # type: ignore
            "expiresAtEpoch": now + int(ttl_seconds),
        }

        # create() falha se já existir
        ref.create(payload)
        return True
    except Exception:
        # Se já existe, tenta ver se expirou; se expirou, sobrescreve
        try:
            snap = (
                db.collection("profissionais")
                .document(uid)
                .collection("voz")
                .document("process_lock")
                .get()
            )
            if not snap.exists:
                return False
            data = snap.to_dict() or {}
            exp = int(data.get("expiresAtEpoch") or 0)
            if exp and exp < int(time.time()):
                snap.reference.set(
                    {
                        "createdAt": firestore.SERVER_TIMESTAMP,  # type: ignore
                        "expiresAtEpoch": int(time.time()) + int(ttl_seconds),
                    },
                    merge=False,
                )
                return True
        except Exception:
            pass
        return False


def _release_lock(uid: str):
    db = _db()
    if not db or not uid:
        return
    try:
        (
            db.collection("profissionais")
            .document(uid)
            .collection("voz")
            .document("process_lock")
            .delete()
        )
    except Exception:
        pass


def kickoff_voice_process(uid: str, reason: str = "unknown") -> Dict[str, Any]:
    """
    Processa a voz do último áudio recebido (WhatsApp) para ElevenLabs, e marca ready.

    Retorna dict de diagnóstico (não é response HTTP).
    """
    out: Dict[str, Any] = {"ok": False, "uid": uid, "reason": reason}

    if not uid:
        out["error"] = "missing_uid"
        return out

    # 1) Evita reprocessar se já estiver pronto
    prof = _get_prof_doc(uid)
    if _already_ready(prof):
        out.update({"ok": True, "skipped": "already_ready"})
        return out

    # 2) Lock pra evitar duplicidade
    locked = _try_lock(uid, ttl_seconds=600)
    if not locked:
        out.update({"ok": True, "skipped": "locked"})
        return out

    try:
        # 3) Resolve último áudio (canônico)
        obj = None
        try:
            obj = vp._get_last_audio_from_firestore(uid)  # type: ignore
        except Exception:
            obj = None

        if not obj:
            # fallback (não deveria ser necessário, mas mantém robustez)
            try:
                obj = vp._find_latest_voice_object(uid)  # type: ignore
            except Exception:
                obj = None

        out["object_path"] = obj
        if not obj:
            out["skipped"] = "no_audio"
            out["ok"] = True
            return out

        # 4) Gera signed url e baixa bytes
        link = vp._signed_url(obj, "audio/ogg")  # type: ignore
        r = requests.get(link, timeout=300)
        if r.status_code != 200:
            out["error"] = f"download_failed:{r.status_code}"
            return out

        audio_bytes = r.content or b""
        if len(audio_bytes) < 1024:
            out["error"] = "audio_too_small"
            return out

        # 5) Cria voz no ElevenLabs
        name = f"cliente-{uid}-{int(time.time())}"
        voice_id = vp._eleven_add_voice(name, audio_bytes)  # type: ignore

        # 6) Marca ready
        vp._save_ready(uid, voice_id, link, object_path=obj)  # type: ignore

        out.update({"ok": True, "status": "ready", "voiceId": voice_id})
        return out

    except Exception as e:
        # Best-effort: marca pendente e não quebra chamador
        try:
            vp._save_pending(uid, None, object_path=out.get("object_path"))  # type: ignore
        except Exception:
            pass
        out["error"] = f"exception:{type(e).__name__}"
        return out

    finally:
        _release_lock(uid)
