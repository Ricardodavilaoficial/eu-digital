# routes/acervo_tasks_bp.py
from __future__ import annotations

import os
import logging
from typing import Any, Dict

from flask import Blueprint, request, jsonify

from services.db import db  # LazyFirestore
from services.gcs_handler import download_bytes  # já existe no teu projeto :contentReference[oaicite:0]{index=0}
from services.storage_gcs import upload_acervo_bytes_and_get_url  # teu helper canônico
from services.text_extract import extract_text_from_bytes

logger = logging.getLogger("mei_robo.tasks.acervo")

acervo_tasks_bp = Blueprint("acervo_tasks_bp", __name__)

def _auth_ok() -> bool:
    secret = (os.environ.get("CLOUD_TASKS_SECRET") or "").strip()
    got = (
        (request.headers.get("X-MR-Tasks-Secret") or "").strip()
        or (request.headers.get("X-CloudTasks-Secret") or "").strip()
        or (request.headers.get("X-Cloudtasks-Secret") or "").strip()
    )
    return bool(secret and got and got == secret)

def _mk_tags(text: str) -> list:
    # tags baratas (fallback): palavras frequentes sem stopwords básicas
    import re
    stop = set(["a","o","os","as","de","do","da","dos","das","e","em","para","por","com","um","uma","que","na","no","nas","nos"])
    words = re.findall(r"[a-zA-ZÀ-ÿ]{3,}", (text or "").lower())
    freq: Dict[str,int] = {}
    for w in words:
        if w in stop:
            continue
        freq[w] = freq.get(w, 0) + 1
    return [w for w,_ in sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:10]]

@acervo_tasks_bp.route("/tasks/acervo-index", methods=["GET","POST"])
def task_acervo_index():
    if request.method == "GET":
        return jsonify({"ok": True, "route": "/tasks/acervo-index", "methods": ["GET","POST"]}), 200

    if not _auth_ok():
        logger.warning("[tasks] unauthorized acervo-index")
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    uid = (data.get("uid") or "").strip()
    acervo_id = (data.get("acervoId") or "").strip()

    if not uid or not acervo_id:
        return jsonify({"ok": False, "error": "missing_uid_or_id"}), 400

    doc_path = f"profissionais/{uid}/acervo/{acervo_id}"
    ref = db.document(doc_path)
    snap = ref.get()
    if not snap.exists:
        return jsonify({"ok": False, "error": "not_found"}), 404

    item = snap.to_dict() or {}
    orig_path = (item.get("storageOriginalPath") or "").strip()
    filename = (item.get("titulo") or f"{acervo_id}.bin")
    tipo = (item.get("tipo") or "").lower().strip()

    # marca running
    try:
        ref.set({"indexStatus": "running", "indexError": None}, merge=True)
    except Exception:
        pass

    try:
        raw = download_bytes(orig_path) if orig_path else b""
        text, kind = extract_text_from_bytes(raw, filename if "." in filename else f"{filename}.{tipo}")

        if not text or len(text) < 80:
            raise RuntimeError("texto_extraido_vazio_ou_curto")

        # magrinho: até 20k chars, com cabeçalho
        body = text.strip()
        if len(body) > 20000:
            body = body[:20000]

        magrinho_md = f"# {item.get('titulo') or 'Acervo'}\n\n{body}\n"

        # salva consulta/<id>.md no acervo do uid
        consulta_rel = f"consulta/{acervo_id}.md"
        consulta_url, _, consulta_gcs_path, _ = upload_acervo_bytes_and_get_url(
            uid,
            consulta_rel,
            magrinho_md.encode("utf-8"),
            "text/markdown; charset=utf-8",
        )

        # resumo + tags + embedding
        resumo_curto = ""
        tags = item.get("tags") or []
        try:
            from services.llm import gpt_mini_complete  # novo
            prompt = (
                "Resuma em 2-4 bullets curtas (máx 400 caracteres) o conteúdo abaixo. "
                "Sem floreio, direto. Conteúdo:\n\n"
                + body[:6000]
            )
            resumo_curto = gpt_mini_complete(prompt, max_tokens=180)
        except Exception:
            # fallback: primeiro pedaço limpo
            resumo_curto = (body[:420] + ("…" if len(body) > 420 else "")).strip()

        if not tags:
            tags = _mk_tags(body)

        embedding = None
        try:
            from services.embeddings import get_mini_embedding  # novo
            embedding = get_mini_embedding(body[:12000])
        except Exception:
            embedding = None

        from google.cloud import firestore  # type: ignore
        now = firestore.SERVER_TIMESTAMP

        ref.set({
            "storageConsultaPath": consulta_gcs_path,
            "storageConsultaUrl": consulta_url,
            "resumoCurto": resumo_curto,
            "tags": tags,
            "embedding": embedding,
            "ultimaIndexacao": now,
            "indexStatus": "ready",
            "indexError": None,
            "atualizadoEm": now,
        }, merge=True)

        return jsonify({"ok": True, "uid": uid, "acervoId": acervo_id, "status": "ready"}), 200

    except Exception as e:
        logger.exception("acervo-index failed")
        try:
            ref.set({"indexStatus": "failed", "indexError": str(e)}, merge=True)
        except Exception:
            pass
        return jsonify({"ok": False, "error": "index_failed", "details": str(e)}), 500
