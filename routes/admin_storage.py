# routes/admin_storage.py
# Admin Storage (read-only) — lista objetos por prefix e gera Signed URL (GET) com expiração curta.
# Segurança:
# - @admin_required (Bearer + ADMIN_UID_ALLOWLIST)
# - allowlist de path/prefix (default: "sandbox/")
# - bloqueia ".." e "\"

from __future__ import annotations

import os
from datetime import timedelta
from flask import Blueprint, jsonify, request, make_response

from services.auth import admin_required
from services.gcs_handler import get_storage_client

admin_storage_bp = Blueprint("admin_storage_bp", __name__)

EXPIRES_MIN = int(os.getenv("SIGNED_URL_EXPIRES_MIN", "15"))
DEFAULT_BUCKET = (os.getenv("STORAGE_BUCKET") or "").strip()

# allowlist de prefixos (CSV). Default seguro: só sandbox/
_ALLOWED_PREFIXES = [
    p.strip().lstrip("/")
    for p in (os.getenv("ADMIN_STORAGE_ALLOWED_PREFIXES", "sandbox/") or "sandbox/").split(",")
    if p.strip()
]

# limite de listagem
DEFAULT_LIMIT = int(os.getenv("ADMIN_STORAGE_LIST_LIMIT", "200"))
MAX_LIMIT = int(os.getenv("ADMIN_STORAGE_LIST_LIMIT_MAX", "1000"))

def _bad_path(s: str) -> bool:
    s = (s or "")
    return (".." in s) or ("\\" in s)

def _norm(s: str) -> str:
    return (s or "").strip().lstrip("/")

def _is_allowed_prefix(p: str) -> bool:
    p = _norm(p)
    return any(p.startswith(ap) for ap in _ALLOWED_PREFIXES)

def _bucket_name() -> str:
    b = DEFAULT_BUCKET
    if not b:
        raise RuntimeError("STORAGE_BUCKET_not_set")
    return b

@admin_storage_bp.route("/api/admin/storage/list", methods=["GET", "OPTIONS"])
@admin_required
def admin_storage_list():
    if request.method == "OPTIONS":
        return make_response("", 204)

    prefix = _norm(request.args.get("prefix", ""))
    if not prefix:
        return jsonify({"ok": False, "error": "missing_prefix"}), 400
    if _bad_path(prefix):
        return jsonify({"ok": False, "error": "invalid_prefix"}), 400
    if not _is_allowed_prefix(prefix):
        return jsonify({"ok": False, "error": "prefix_not_allowed", "allowed": _ALLOWED_PREFIXES}), 403

    try:
        limit_raw = request.args.get("limit", "") or ""
        limit = int(limit_raw) if limit_raw else DEFAULT_LIMIT
    except Exception:
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))

    client = get_storage_client()
    if client is None:
        return jsonify({"ok": False, "error": "storage_client_unavailable"}), 500

    bucket = client.bucket(_bucket_name())

    items = []
    try:
        # list_blobs é paginado; vamos cortando no limite
        for blob in bucket.list_blobs(prefix=prefix):
            items.append({
                "path": blob.name,
                "size": int(blob.size or 0),
                "updated": blob.updated.isoformat() if getattr(blob, "updated", None) else None,
                "contentType": getattr(blob, "content_type", None),
            })
            if len(items) >= limit:
                break
    except Exception as e:
        return jsonify({"ok": False, "error": "list_failed", "detail": str(e)}), 500

    return jsonify({
        "ok": True,
        "bucket": _bucket_name(),
        "prefix": prefix,
        "limit": limit,
        "count": len(items),
        "items": items
    }), 200

@admin_storage_bp.route("/api/admin/storage/signed-url", methods=["GET", "OPTIONS"])
@admin_required
def admin_storage_signed_url():
    if request.method == "OPTIONS":
        return make_response("", 204)

    path = _norm(request.args.get("path", ""))
    if not path:
        return jsonify({"ok": False, "error": "missing_path"}), 400
    if _bad_path(path):
        return jsonify({"ok": False, "error": "invalid_path"}), 400
    if not _is_allowed_prefix(path):
        return jsonify({"ok": False, "error": "path_not_allowed", "allowed": _ALLOWED_PREFIXES}), 403

    client = get_storage_client()
    if client is None:
        return jsonify({"ok": False, "error": "storage_client_unavailable"}), 500

    bucket = client.bucket(_bucket_name())
    blob = bucket.blob(path)

    try:
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=EXPIRES_MIN),
            method="GET",
        )
    except Exception as e:
        return jsonify({"ok": False, "error": "signed_url_failed", "detail": str(e)}), 500

    return jsonify({
        "ok": True,
        "bucket": _bucket_name(),
        "path": path,
        "url": url,
        "expiresInSeconds": EXPIRES_MIN * 60
    }), 200
