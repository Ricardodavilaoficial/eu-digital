# routes/configuracao.py
# Rota de configuração inicial do MEI (onboarding)
# - POST /api/configuracao (multipart): salva dados + upload de áudio (voz)
# - GET  /api/configuracao (somente leitura): retorna dados achatados p/ front
#
# Regras:
# - Somente para usuário autenticado **e com e-mail verificado**.
# - Não cria profissionais/{uid} aqui: check-verification é a única etapa promotora.
# - Blindagem de CNPJ (não altera sem override admin).
# - Suporte a credencial Admin via env inline.
# - Devolve vozClonada no GET p/ player do front.

from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

import os, json, re
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import auth as fb_auth, firestore, credentials

from services.firebase_admin_init import ensure_firebase_admin
from services.storage_gcs import upload_bytes_and_get_url
from services import db as dbsvc

config_bp = Blueprint('config', __name__)

# ---------------------------
# Admin SDK / Firestore
# ---------------------------
def _get_db():
    """Garante Admin SDK inicializado e retorna client do Firestore."""
    try:
        firebase_admin.get_app()
    except ValueError:
        # Preferir credencial inline via env
        cred_json = (
            os.getenv("FIREBASE_ADMIN_CREDENTIALS")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIAL_JSON")
        )
        if cred_json:
            try:
                info = json.loads(cred_json)
                cred = credentials.Certificate(info)
            except Exception:
                cred = credentials.ApplicationDefault()
        else:
            cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
    ensure_firebase_admin()
    return firestore.client()

# ---------------------------
# Helpers gerais
# ---------------------------
ALLOWED_AUDIO_MIMES = {
    "audio/wav", "audio/x-wav",
    "audio/mpeg", "audio/mp3",
    "audio/ogg", "audio/webm", "audio/x-m4a", "audio/aac", "audio/flac"
}

def _first_non_empty(*vals):
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str):
            vs = v.strip()
            if vs != "":
                return vs
        else:
            return v
    return None

def _normalize_cnpj(cnpj):
    if not cnpj:
        return None
    s = str(cnpj)
    digits = re.sub(r"\D", "", s)
    return digits or None

def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()

# ---------------------------
# Segurança / Auth
# ---------------------------
def _get_bearer_token():
    authz = request.headers.get("Authorization", "")
    if authz.startswith("Bearer "):
        return (authz.split(" ", 1)[1] or "").strip()
    return None

def _require_verified_user():
    """
    Retorna (uid, decoded) se autenticado e verificado.
    Caso contrário, retorna (None, resposta Flask) para ser devolvida ao cliente.
    """
    token = _get_bearer_token()
    if not token:
        return None, (jsonify({"ok": False, "error": "unauthorized"}), 401)
    try:
        ensure_firebase_admin()
        decoded = fb_auth.verify_id_token(token)
        uid = decoded.get("uid")
        email_verified = bool(decoded.get("email_verified", False))

        # Em raras defasagens, confirma via Admin SDK
        if not email_verified and uid:
            try:
                rec = fb_auth.get_user(uid)
                email_verified = bool(getattr(rec, "email_verified", False))
            except Exception:
                pass

        if not uid:
            return None, (jsonify({"ok": False, "error": "unauthorized"}), 401)
        if not email_verified:
            return None, (jsonify({"ok": False, "error": "email_not_verified"}), 403)
        return uid, decoded
    except fb_auth.ExpiredIdTokenError:
        return None, (jsonify({"ok": False, "error": "expired_token"}), 401)
    except Exception as e:
        return None, (jsonify({"ok": False, "error": "invalid_token", "detail": str(e)}), 401)

# ---------------------------
# Blindagem CNPJ
# ---------------------------
def _admin_override_enabled() -> bool:
    # Desligado por padrão. Para ligar: ADMIN_CNPJ_OVERRIDE=1
    return os.getenv("ADMIN_CNPJ_OVERRIDE", "0").lower() in ("1", "true", "yes")

def _is_admin_override(req) -> bool:
    """
    Permite override via header X-Admin-Override com valor secreto.
    Para ativar:
      - ADMIN_CNPJ_OVERRIDE=1
      - ADMIN_CNPJ_SECRET=<token_secreto>
    """
    if not _admin_override_enabled():
        return False
    secret = (os.getenv("ADMIN_CNPJ_SECRET") or "").strip()
    provided = (req.headers.get("X-Admin-Override") or "").strip()
    return bool(secret) and provided == secret

def _read_current_cnpj(uid: str):
    """Lê profissionais/{uid} e retorna CNPJ normalizado (flat ou dadosBasicos.cnpj)."""
    db = _get_db()
    snap = db.collection("profissionais").document(uid).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    dados_basicos = data.get("dadosBasicos") or {}
    cnpj_raw = _first_non_empty(data.get("cnpj"), dados_basicos.get("cnpj"))
    return _normalize_cnpj(cnpj_raw)

# ---------------------------
# GET /api/configuracao
# ---------------------------
@config_bp.route('/api/configuracao', methods=['GET'], strict_slashes=False)
def ler_configuracao():
    """
    Somente leitura dos dados para configuracao.html.
    Requer usuário autenticado **e verificado**.
    """
    uid, err = _require_verified_user()
    if uid is None:
        return err  # (Response, status)

    try:
        doc_ref = _get_db().collection("profissionais").document(uid)
        snap = doc_ref.get()
        if not snap.exists:
            # Após verificação, check-verification sempre cria o doc.
            return jsonify({"ok": False, "error": "not_found"}), 404

        data = snap.to_dict() or {}

        dados_basicos = (data.get("dadosBasicos") or {}) if isinstance(data.get("dadosBasicos"), dict) else {}
        perfil_prof   = (data.get("perfilProfissional") or {}) if isinstance(data.get("perfilProfissional"), dict) else {}
        voz_clonada   = data.get("vozClonada") or {}

        nome      = _first_non_empty(data.get("nome"),      dados_basicos.get("nome"))
        email     = _first_non_empty(data.get("email"),     dados_basicos.get("email"))
        telefone  = _first_non_empty(data.get("telefone"),  dados_basicos.get("telefone"))
        cnpj_raw  = _first_non_empty(data.get("cnpj"),      dados_basicos.get("cnpj"))
        cnpj      = _normalize_cnpj(cnpj_raw)
        segmento  = _first_non_empty(perfil_prof.get("segmento"), data.get("segmento"))
        legal_nm  = _first_non_empty(data.get("legal_name"),  dados_basicos.get("legal_name"))
        trade_nm  = _first_non_empty(data.get("trade_name"),  dados_basicos.get("trade_name"))

        flat = {
            "uid": uid,
            "nome": nome or "",
            "email": email or "",
            "telefone": telefone or "",
            "cnpj": cnpj or "",
            "segmento": segmento or "",
            "legal_name": legal_nm or "",
            "trade_name": trade_nm or "",
            "vozClonadaUrl": (voz_clonada.get("arquivoUrl") or ""),
            "vozClonada": voz_clonada or None,
        }
        return jsonify({"ok": True, "data": flat}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500

# ---------------------------
# POST /api/configuracao
# ---------------------------
@config_bp.route('/api/configuracao', methods=['POST'], strict_slashes=False)
def salvar_configuracao():
    """
    Salva dados e upload da voz.
    Requer usuário autenticado **e verificado**.
    Não altera CNPJ salvo sem override admin.
    """
    uid, err = _require_verified_user()
    if uid is None:
        return err

    # -------- Campos do form --------
    nome       = (request.form.get('nome') or "").strip()
    email      = (request.form.get('email') or "").strip()
    telefone   = (request.form.get('telefone') or "").strip()
    cnpj_in    = (request.form.get('cnpj') or "").strip()
    cnpj_new   = _normalize_cnpj(cnpj_in)

    segmento   = (request.form.get('segmento') or "").strip()
    esp1       = (request.form.get('esp1') or "").strip()
    esp2       = (request.form.get('esp2') or "").strip()

    formalidade = (request.form.get('formalidade') or "media").strip()
    emojis      = (request.form.get('emojis') or "sim").strip()
    saudacao    = (request.form.get('saudacao') or "").strip()

    # -------- BLINDAGEM CNPJ (antes de subir áudio) --------
    try:
        cnpj_current = _read_current_cnpj(uid)
        if cnpj_current:
            if cnpj_new and cnpj_new != cnpj_current and not _is_admin_override(request):
                return jsonify({
                    "ok": False,
                    "error": "cnpj_change_not_allowed",
                    "message": "Alteração de CNPJ não permitida sem aprovação administrativa.",
                    "uid": uid,
                    "current_cnpj": cnpj_current
                }), 409
            if not cnpj_new:
                cnpj_new = cnpj_current
    except Exception as e:
        return jsonify({"ok": False, "error": "internal_error", "detail": f"Falha ao validar CNPJ: {e}"}), 500

    # -------- Áudio obrigatório --------
    voz_file = request.files.get('voz')
    if not voz_file:
        return jsonify({"ok": False, "error": "missing_audio"}), 422

    content_type = (voz_file.content_type or "").lower()
    # Aceita se "audio/*" OU exato em ALLOWED_AUDIO_MIMES
    if not (content_type.startswith("audio/") or content_type in ALLOWED_AUDIO_MIMES):
        return jsonify({"ok": False, "error": "unsupported_media_type", "content_type": content_type}), 415

    filename = secure_filename(voz_file.filename or "voz.wav")

    # -------- Upload para GCS --------
    try:
        buf = voz_file.read()
        url, bucket, path, access = upload_bytes_and_get_url(uid, filename, buf, content_type or "audio/wav")
        voz_url = url
    except Exception as e:
        return jsonify({"ok": False, "error": "upload_failed", "detail": str(e)}), 500

    # -------- Documento para Firestore --------
    doc = {
        "dadosBasicos": {
            "nome": nome,
            "email": email,
            "telefone": telefone,
            "cnpj": cnpj_new or "",
        },
        "perfilProfissional": {
            "segmento": segmento,
            "especializacoes": [v for v in [esp1, esp2] if v],
        },
        "estiloComunicacao": {
            "formalidade": formalidade,
            "usaEmojis": (emojis == "sim"),
            "saudacao": saudacao,
        },
        "vozClonada": {
            "arquivoUrl": voz_url,
            "status": "pendente"  # depois que processar na ElevenLabs -> 'pronto'
        },
        "statusAtivacao": "aguardando-voz",
        "updatedAt": _utc_now_iso(),
    }

    # -------- Persistência --------
    try:
        dbsvc.salvar_config_profissional(uid, doc)
    except Exception as e:
        return jsonify({"ok": False, "error": "firestore_write_failed", "detail": str(e)}), 500

    return jsonify({"ok": True, "uid": uid, "vozUrl": voz_url}), 200
