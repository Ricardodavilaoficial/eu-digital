# routes/authority_bp.py
# Esqueleto v1 — Vinculação de autoridade ao CNPJ
# Estados: UNVERIFIED → DOCS_REQUIRED → UNDER_REVIEW → APPROVED | REJECTED

import os, hashlib, time
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from firebase_admin import auth as fb_auth
from services.firebase_admin_init import ensure_firebase_admin

try:
    from firebase_admin import firestore as fb_fs
except Exception:
    fb_fs = None

authority_bp = Blueprint("authority_bp", __name__, url_prefix="/api")

# Flags (lidas do ambiente)
AUTHORITY_LINKAGE_ENABLED = os.getenv("AUTHORITY_LINKAGE_ENABLED", "0") in ("1","true","TRUE")

def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

def _require_auth():
    """Valida Authorization: Bearer ... e retorna uid."""
    hdr = request.headers.get("Authorization", "")
    if not hdr.startswith("Bearer "):
        return None
    token = hdr.split(" ", 1)[1]
    try:
        ensure_firebase_admin()
        decoded = fb_auth.verify_id_token(token)
        return decoded.get("uid")
    except Exception:
        return None

def _require_admin(uid):
    # Simplificado: se tiver custom-claim admin=true
    try:
        ensure_firebase_admin()
        user = fb_auth.get_user(uid)
        return bool(getattr(user, "custom_claims", {}) and user.custom_claims.get("admin") is True)
    except Exception:
        return False

def _authority_ref(db, uid):
    # guardamos em subcoleção 'meta', doc 'authority'
    return db.collection("profissionais").document(uid).collection("meta").document("authority")

def _doc_safe_get(doc):
    return doc.to_dict() if doc and doc.exists else None

def _init_if_missing(db, uid, cnpj=None, userNameClaimed=None, reason="manual_check"):
    ref = _authority_ref(db, uid)
    snap = ref.get()
    if not snap.exists:
        ref.set({
            "status": "UNVERIFIED",
            "cnpj": cnpj or "",
            "userNameClaimed": userNameClaimed or "",
            "nameOnCNPJ": "",
            "mismatchFlag": False,
            "reason": reason,
            "evidence": [],
            "requestedAt": _utc_now_iso(),
            "updatedAt": _utc_now_iso()
        })
    return ref

# ============ CLIENTE ============

@authority_bp.route("/authority/start", methods=["POST"])
def authority_start():
    if not AUTHORITY_LINKAGE_ENABLED:
        return jsonify({"error": "authority_linkage_disabled"}), 503

    uid = _require_auth()
    if not uid:
        return jsonify({"error": "unauthorized"}), 401

    ensure_firebase_admin()
    db = fb_fs.client()

    data = request.get_json(silent=True) or {}
    cnpj = (data.get("cnpj") or "").strip()
    userNameClaimed = (data.get("userNameClaimed") or "").strip()

    ref = _init_if_missing(db, uid, cnpj=cnpj, userNameClaimed=userNameClaimed)
    ref.set({
        "cnpj": cnpj,
        "userNameClaimed": userNameClaimed,
        "status": "DOCS_REQUIRED",
        "updatedAt": _utc_now_iso(),
        "reason": data.get("reason") or "cnpj_api_blank_or_mismatch"
    }, merge=True)

    return jsonify({"status": "DOCS_REQUIRED"})

@authority_bp.route("/authority/evidence-url", methods=["POST"])
def authority_evidence_url():
    if not AUTHORITY_LINKAGE_ENABLED:
        return jsonify({"error": "authority_linkage_disabled"}), 503

    uid = _require_auth()
    if not uid:
        return jsonify({"error": "unauthorized"}), 401

    ensure_firebase_admin()
    db = fb_fs.client()
    _init_if_missing(db, uid)

    data = request.get_json(silent=True) or {}
    filename = (data.get("filename") or "").strip()
    contentType = (data.get("contentType") or "").strip()

    evidence_id = hashlib.sha256(f"{uid}:{filename}:{time.time()}".encode("utf-8")).hexdigest()[:24]

    ref = _authority_ref(db, uid)
    snap = ref.get()
    payload = _doc_safe_get(snap) or {}
    evid = payload.get("evidence", [])
    evid.append({
        "id": evidence_id,
        "path": f"authority/{uid}/{evidence_id}",
        "filename": filename,
        "contentType": contentType,
        "uploadedAt": None,
        "size": 0,
        "sha256": ""
    })
    ref.set({"evidence": evid, "updatedAt": _utc_now_iso()}, merge=True)

    return jsonify({
        "evidenceId": evidence_id,
        "uploadUrl": None,      # Atividade 2: Signed URL real
        "expiresInSec": 0
    })

@authority_bp.route("/authority/evidence-commit", methods=["POST"])
def authority_evidence_commit():
    if not AUTHORITY_LINKAGE_ENABLED:
        return jsonify({"error": "authority_linkage_disabled"}), 503

    uid = _require_auth()
    if not uid:
        return jsonify({"error": "unauthorized"}), 401

    ensure_firebase_admin()
    db = fb_fs.client()

    data = request.get_json(silent=True) or {}
    evidence_id = (data.get("evidenceId") or "").strip()
    sha256 = (data.get("sha256") or "").strip()
    size = int(data.get("size") or 0)
    ev_type = (data.get("type") or "outro").strip()

    ref = _authority_ref(db, uid)
    snap = ref.get()
    doc = _doc_safe_get(snap) or {}
    arr = doc.get("evidence", [])

    found = False
    for item in arr:
        if item.get("id") == evidence_id:
            item["uploadedAt"] = _utc_now_iso()
            item["size"] = size
            item["sha256"] = sha256
            item["type"] = ev_type
            found = True
            break

    if not found:
        arr.append({
            "id": evidence_id or hashlib.sha256(f"{uid}:{time.time()}".encode()).hexdigest()[:24],
            "path": f"authority/{uid}/{evidence_id or 'adhoc'}",
            "filename": "",
            "contentType": "",
            "uploadedAt": _utc_now_iso(),
            "size": size,
            "sha256": sha256,
            "type": ev_type
        })

    ref.set({
        "evidence": arr,
        "status": "UNDER_REVIEW",
        "updatedAt": _utc_now_iso()
    }, merge=True)

    return jsonify({"status": "UNDER_REVIEW"})

@authority_bp.route("/authority/status", methods=["GET"])
def authority_status():
    if not AUTHORITY_LINKAGE_ENABLED:
        return jsonify({"error": "authority_linkage_disabled"}), 503

    uid = _require_auth()
    if not uid:
        return jsonify({"error": "unauthorized"}), 401

    ensure_firebase_admin()
    db = fb_fs.client()
    ref = _authority_ref(db, uid)
    snap = ref.get()
    doc = _doc_safe_get(snap) or {"status": "UNVERIFIED", "evidence": []}

    missing = []
    if doc.get("status") == "DOCS_REQUIRED":
        missing = ["procuração ou print do e-CNPJ"]

    return jsonify({
        "status": doc.get("status", "UNVERIFIED"),
        "missing": missing,
        "updatedAt": doc.get("updatedAt"),
        "evidenceCount": len(doc.get("evidence", []))
    })

# ============ ADMIN ============

@authority_bp.route("/admin/authority/pending", methods=["GET"])
def admin_authority_pending():
    uid = _require_auth()
    if not uid:
        return jsonify({"error": "unauthorized"}), 401
    if not _require_admin(uid):
        return jsonify({"error": "forbidden"}), 403

    ensure_firebase_admin()
    db = fb_fs.client()

    # Buscar docs em subcoleção 'meta' com status pendente
    q1 = db.collection_group("meta").where("status", "in", ["UNDER_REVIEW", "DOCS_REQUIRED"]).stream()
    out = []
    for d in q1:
        data = d.to_dict() or {}
        parts = d.reference.path.split("/")
        try:
            prof_idx = parts.index("profissionais")
            uid_found = parts[prof_idx + 1]
        except Exception:
            uid_found = None
        if data.get("status") in ("UNDER_REVIEW", "DOCS_REQUIRED"):
            out.append({"uid": uid_found, "status": data.get("status"), "updatedAt": data.get("updatedAt")})

    return jsonify({"pending": out})

@authority_bp.route("/admin/authority/decision", methods=["POST"])
def admin_authority_decision():
    uid = _require_auth()
    if not uid:
        return jsonify({"error": "unauthorized"}), 401
    if not _require_admin(uid):
        return jsonify({"error": "forbidden"}), 403

    ensure_firebase_admin()
    db = fb_fs.client()

    data = request.get_json(silent=True) or {}
    target_uid = (data.get("uid") or "").strip()
    decision = (data.get("decision") or "").strip().upper()
    note = (data.get("note") or "").strip()

    if decision not in ("APPROVED", "REJECTED"):
        return jsonify({"error": "invalid_decision"}), 400

    ref = _authority_ref(db, target_uid)
    snap = ref.get()
    if not snap.exists:
        return jsonify({"error": "not_found"}), 404

    ref.set({
        "status": decision,
        "reviewedAt": _utc_now_iso(),
        "updatedAt": _utc_now_iso(),
        "reviewer": {"uid": uid},
        "decisionNote": note
    }, merge=True)

    return jsonify({"status": decision})
