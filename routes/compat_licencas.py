# -*- coding: utf-8 -*-
"""Compatibilidade de Licenças/Cupom — MEI Robô
Rota nova (compat) para aceitar POST do frontend atual sem alterar a arquitetura existente.
- Endpoint: POST /licencas/ativar-cupom
- Corpo esperado: { "codigo": "ABC-123", "uid": "<opcional>" }
- Comportamento: idempotente; marca cupom como usado se estiver válido.
- Segurança: por padrão NÃO exige Authorization para não quebrar o FE atual.
             É possível habilitar exigência via ENV REQUIRE_AUTH_ATIVACAO=1.
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
    from google.cloud import firestore  # for SERVER_TIMESTAMP constant (optional)
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
    # Preferir SERVER_TIMESTAMP do Firestore quando disponível
    if _HAS_FIREBASE:
        return fb_firestore.SERVER_TIMESTAMP
    if _HAS_GCLOUD:
        return firestore.SERVER_TIMESTAMP  # fallback
    return datetime.utcnow().isoformat() + "Z"

def _should_require_auth() -> bool:
    return os.getenv("REQUIRE_AUTH_ATIVACAO", "0").strip() in ("1", "true", "True")

@bp.route("/licencas/ativar-cupom", methods=["POST", "OPTIONS"])
def ativar_cupom_compat():
    # Preflight manual (caso o CORS global não capture)
    if request.method == "OPTIONS":
        resp = Response(status=204)
        # CORS headers (deixe o middleware global cuidar, isto é apenas fallback)
        origin = request.headers.get("Origin", "*")
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        return resp

    # (1) Autorização opcional (para não quebrar hoje)
    if _should_require_auth():
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return _json_error("Unauthorized (Bearer token ausente).", 401)
        # Validação do token pode ser adicionada aqui no futuro

    # (2) Parse do body
    data = request.get_json(silent=True) or {}
    codigo = (data.get("codigo") or data.get("code") or "").strip()
    uid = (data.get("uid") or "").strip() or None

    if not codigo:
        return _json_error("Campo 'codigo' é obrigatório.", 400)

    # (3) Transação idempotente no Firestore
    try:
        db = _get_db()
        doc_ref = db.collection("cuponsAtivacao").document(codigo)
        @fb_firestore.transactional
        def _consume(transaction, ref, _uid: str | None):
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                raise KeyError("Cupom não encontrado.")
            data = snapshot.to_dict() or {}
            status = str(data.get("status", "valid")).lower()
            if status != "valid":
                # Já usado ou inválido -> não altera
                raise ValueError("Cupom já utilizado ou inválido.")
            update = {
                "status": "used",
                "usedAt": _server_ts(),
            }
            if _uid:
                update["usedBy"] = _uid
            transaction.update(ref, update)

        transaction = db.transaction()
        _consume(transaction, doc_ref, uid)

        # Log leve
        try:
            current_app.logger.info({
                "route": "/licencas/ativar-cupom",
                "codigo": codigo,
                "uid": uid,
                "result": "used",
            })
        except Exception:
            pass

        return jsonify({
            "ok": True,
            "message": "Cupom ativado com sucesso.",
            "codigo": codigo,
            "status": "used"
        }), 200

    except KeyError as e:
        return _json_error(str(e), 404)
    except ValueError as e:
        # Conflito de idempotência/estado
        return _json_error(str(e), 409)
    except Exception as e:
        try:
            current_app.logger.exception("Erro ao ativar cupom (compat): %s", e)
        except Exception:
            pass
        return _json_error("Erro interno ao ativar cupom.", 500)

