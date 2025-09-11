# -*- coding: utf-8 -*-
"""Compat Licenças/Cupom — v2
Aceita POST /licencas/ativar-cupom com body { "codigo": "...", "uid": "..."? }
Robusto: tenta localizar cupom por:
  1) ID do documento == codigo (original e upper())
  2) Campo 'codigo' == codigo (case-insensitive)
  3) Campo 'code'   == codigo (case-insensitive)
Idempotente: usa transação para fazer valid -> used exatamente uma vez.
Segurança: Authorization opcional, habilitável por ENV REQUIRE_AUTH_ATIVACAO=1
"""
from __future__ import annotations

import os
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app, abort, Response

try:
    from firebase_admin import firestore as fb_firestore  # via firebase_admin SDK
    _HAS_FIREBASE = True
except Exception:
    _HAS_FIREBASE = False

try:
    from google.cloud import firestore  # SERVER_TIMESTAMP (opcional)
    _HAS_GCLOUD = True
except Exception:
    _HAS_GCLOUD = False

bp = Blueprint("licencas", __name__)

def _json_error(message: str, status: int) -> tuple[dict, int]:
    return { "error": message, "ok": False }, status

def _get_db():
    if not _HAS_FIREBASE:
        raise RuntimeError("firebase_admin/firestore não está disponível no ambiente.")
    return fb_firestore.client()

def _server_ts():
    if _HAS_FIREBASE:
        return fb_firestore.SERVER_TIMESTAMP
    if _HAS_GCLOUD:
        return firestore.SERVER_TIMESTAMP
    return datetime.utcnow().isoformat() + "Z"

def _should_require_auth() -> bool:
    return os.getenv("REQUIRE_AUTH_ATIVACAO", "0").strip() in ("1", "true", "True")

def _resolve_coupon_ref(db, codigo: str):
    """Resolve a referência do documento de cupom:
       - Tenta ID exato e upper()
       - Depois, busca por campos 'codigo'/'code' (case-insensitive)
       Retorna (doc_ref, snapshot_dict) ou (None, None) se não achar.
    """
    codigo_clean = (codigo or "").strip()
    if not codigo_clean:
        return None, None

    # 1) Tenta pelo ID do documento (exato e upper)
    for cid in (codigo_clean, codigo_clean.upper()):
        doc_ref = db.collection("cuponsAtivacao").document(cid)
        snap = doc_ref.get()
        if snap.exists:
            return doc_ref, snap.to_dict() or {}

    # 2) Busca por campo 'codigo' (case-insensitive)
    #    OBS: Firestore não faz case-insensitive nativo; tentamos exact e upper.
    for field in ("codigo", "code"):
        # tentativa 1: valor do jeito que veio
        q1 = db.collection("cuponsAtivacao").where(field, "==", codigo_clean).limit(1).get()
        if q1:
            r = q1[0]
            return r.reference, r.to_dict() or {}
        # tentativa 2: upper()
        q2 = db.collection("cuponsAtivacao").where(field, "==", codigo_clean.upper()).limit(1).get()
        if q2:
            r = q2[0]
            return r.reference, r.to_dict() or {}

    return None, None

@bp.route("/licencas/ativar-cupom", methods=["POST", "OPTIONS"])
def ativar_cupom_compat_v2():
    # Preflight (fallback, caso o CORS global não cubra)
    if request.method == "OPTIONS":
        resp = Response(status=204)
        origin = request.headers.get("Origin", "*")
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        return resp

    # Auth opcional
    if _should_require_auth():
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return _json_error("Unauthorized (Bearer token ausente).", 401)
        # Validação do token pode ser implementada depois

    # Body
    data = request.get_json(silent=True) or {}
    codigo = (data.get("codigo") or data.get("code") or "").strip()
    uid = (data.get("uid") or "").strip() or None
    if not codigo:
        return _json_error("Campo 'codigo' é obrigatório.", 400)

    try:
        db = _get_db()
        doc_ref, doc_data = _resolve_coupon_ref(db, codigo)
        if not doc_ref:
            return _json_error("Cupom não encontrado.", 404)

        # Transação idempotente
        @fb_firestore.transactional
        def _consume(transaction, ref, _uid: str | None):
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                raise KeyError("Cupom não encontrado.")
            data = snap.to_dict() or {}
            status = str(data.get("status", "valid")).lower()
            if status != "valid":
                raise ValueError("Cupom já utilizado ou inválido.")
            update = {
                "status": "used",
                "usedAt": _server_ts(),
            }
            if _uid:
                update["usedBy"] = _uid
            transaction.update(ref, update)

        tx = db.transaction()
        _consume(tx, doc_ref, uid)

        try:
            current_app.logger.info({
                "route": "/licencas/ativar-cupom",
                "codigo": codigo,
                "uid": uid,
                "result": "used",
                "resolved_id": doc_ref.id,
            })
        except Exception:
            pass

        return jsonify({
            "ok": True,
            "message": "Cupom ativado com sucesso.",
            "codigo": codigo,
            "status": "used",
            "resolved_id": doc_ref.id,
        }), 200

    except KeyError as e:
        return _json_error(str(e), 404)
    except ValueError as e:
        return _json_error(str(e), 409)
    except Exception as e:
        try:
            current_app.logger.exception("Erro ao ativar cupom (compat v2): %s", e)
        except Exception:
            pass
        return _json_error("Erro interno ao ativar cupom.", 500)

