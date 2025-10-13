# routes/configuracao.py
# Rota de configuração inicial do MEI (onboarding)
# - Recebe multipart/form-data com os campos do formulário e o arquivo de voz
# - Faz upload do áudio para o GCS
# - Salva/mescla os dados em Firestore: profissionais/{uid}
#
# Acrescentado com segurança:
# - GET /api/configuracao: leitura "somente leitura" dos dados do profissional
#   (usa Firebase ID Token; fallback de teste por ?uid=)

from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

from services import db as dbsvc
from services import gcs_handler

# Imports para leitura segura (GET) via Firebase Admin
from firebase_admin import auth as fb_auth, firestore

config_bp = Blueprint('config', __name__)

# Firestore client (Firebase Admin já deve estar inicializado no app)
_db = firestore.client()

# Limite básico de validação (o main.py já tem MAX_CONTENT_LENGTH = 25MB)
ALLOWED_AUDIO_MIMES = {
    "audio/wav", "audio/x-wav",
    "audio/mpeg", "audio/mp3",
    "audio/ogg", "audio/webm", "audio/x-m4a", "audio/aac", "audio/flac"
}

def _get_bearer_token():
    authz = request.headers.get("Authorization", "")
    if authz.startswith("Bearer "):
        return (authz.split(" ", 1)[1] or "").strip()
    return None

def _resolve_uid_for_read():
    """
    Resolve o uid para leitura:
    1) Preferir Firebase ID Token (Authorization: Bearer)
    2) Fallback: querystring ?uid= (apenas para testes/diagnóstico)
    """
    token = _get_bearer_token()
    if token:
        try:
            decoded = fb_auth.verify_id_token(token)
            uid = decoded.get("uid")
            if uid:
                return uid
        except Exception:
            # cai para fallback ?uid=
            pass
    # Fallback CONTROLADO para CMD/teste
    qs_uid = (request.args.get("uid") or "").strip()
    return qs_uid or None

@config_bp.route('/api/configuracao', methods=['GET'])
def ler_configuracao():
    """
    Leitura "somente leitura" dos dados básicos do profissional para a tela configuracao.html.
    NÃO exige áudio. NÃO altera nada.
    Retorna campos achatados esperados pelo front:
      - nome, email, cnpj (de dadosBasicos.*)
      - segmento (de perfilProfissional.segmento)
      - legal_name, trade_name se existirem em algum lugar
    """
    uid = _resolve_uid_for_read()
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    # Lê doc profissionais/{uid}
    try:
        doc_ref = _db.collection("profissionais").document(uid)
        snap = doc_ref.get()
        if not snap.exists:
            return jsonify({"ok": False, "error": "not_found"}), 404

        data = snap.to_dict() or {}

        # Extrai dados nos caminhos atuais (sem mudar seu esquema)
        dados_basicos = data.get("dadosBasicos", {}) or {}
        perfil_prof   = data.get("perfilProfissional", {}) or {}

        flat = {
            "uid": uid,
            "nome": dados_basicos.get("nome"),
            "email": dados_basicos.get("email"),
            "telefone": dados_basicos.get("telefone"),
            "cnpj": dados_basicos.get("cnpj"),
            "segmento": perfil_prof.get("segmento"),
            # Esses dois podem vir do preenchimento da consulta CNPJ (se você salvar)
            "legal_name": data.get("legal_name") or dados_basicos.get("legal_name"),
            "trade_name": data.get("trade_name") or dados_basicos.get("trade_name"),
        }

        return jsonify({"ok": True, "data": flat}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500

@config_bp.route('/api/configuracao', methods=['POST'])
def salvar_configuracao():
    # -------- Campos do form --------
    nome       = (request.form.get('nome') or "").strip()
    email      = (request.form.get('email') or "").strip()
    telefone   = (request.form.get('telefone') or "").strip()
    cnpj       = (request.form.get('cnpj') or "").strip()

    segmento   = (request.form.get('segmento') or "").strip()
    esp1       = (request.form.get('esp1') or "").strip()
    esp2       = (request.form.get('esp2') or "").strip()

    formalidade = (request.form.get('formalidade') or "media").strip()
    emojis      = (request.form.get('emojis') or "sim").strip()
    saudacao    = (request.form.get('saudacao') or "").strip()

    # UID provisório para testes (frontend guarda em localStorage)
    uid = (request.form.get('uid') or "demo").strip()

    # -------- Áudio obrigatório --------
    voz_file = request.files.get('voz')
    if not voz_file:
        return ("Áudio de voz é obrigatório.", 400)

    content_type = (voz_file.content_type or "").lower()
    if not any(content_type.startswith(a.split('/')[0]) or content_type == a for a in ALLOWED_AUDIO_MIMES):
        # Aceita "audio/*" genérico também:
        if not content_type.startswith("audio/"):
            return (f"Tipo de áudio não suportado: {content_type}", 415)

    # Nome seguro e caminho no bucket
    filename = secure_filename(voz_file.filename or "voz.wav")
    dest_path = f"profissionais/{uid}/voz/{filename}"

    # -------- Upload para GCS --------
    try:
        voz_url = gcs_handler.upload_fileobj(
            voz_file,
            dest_path,
            content_type=content_type or "audio/wav",
            public=True  # em produção, considere public=False (Signed URL)
        )
    except Exception as e:
        return (f"Falha no upload da voz: {e}", 500)

    # -------- Documento para Firestore --------
    doc = {
        "dadosBasicos": {
            "nome": nome,
            "email": email,
            "telefone": telefone,
            "cnpj": cnpj,
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
    }

    # -------- Persistência --------
    try:
        dbsvc.salvar_config_profissional(uid, doc)
    except Exception as e:
        return (f"Erro ao salvar no Firestore: {e}", 500)

    return jsonify({"status": "ok", "uid": uid, "vozUrl": voz_url})
