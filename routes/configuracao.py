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
import os, json, re, firebase_admin
from firebase_admin import auth as fb_auth, firestore, credentials

config_bp = Blueprint('config', __name__)

def _get_db():
    """Inicializa o Firebase Admin se necessário e retorna o client do Firestore."""
    try:
        firebase_admin.get_app()
    except ValueError:
        # 1) Tenta credencial JSON inline por env (recomendado no Render)
        cred_json = os.getenv("FIREBASE_ADMIN_CREDENTIALS") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        if cred_json:
            try:
                info = json.loads(cred_json)
                cred = credentials.Certificate(info)
            except Exception:
                # Se a env vier como caminho por engano, cai em ADC
                cred = credentials.ApplicationDefault()
        else:
            # 2) Sem JSON inline → ADC padrão (usa GOOGLE_APPLICATION_CREDENTIALS=path)
            cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
    return firestore.client()

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

def _first_non_empty(*vals):
    """Retorna o primeiro valor não vazio/não None, já com strip() se for string."""
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str):
            vs = v.strip()
            if vs != "":
                return vs
        else:
            # números/boolean/etc.
            return v
    return None

def _normalize_cnpj(cnpj):
    """Mantém apenas dígitos; retorna None se entrada vazia."""
    if not cnpj:
        return None
    s = str(cnpj)
    digits = re.sub(r"\D", "", s)
    return digits or None

@config_bp.route('/api/configuracao', methods=['GET'], strict_slashes=False)
def ler_configuracao():
    """
    Leitura "somente leitura" dos dados básicos do profissional para a tela configuracao.html.
    NÃO exige áudio. NÃO altera nada.
    Retorna campos achatados esperados pelo front:
      - nome, email, cnpj (aceita flat raiz OU dadosBasicos.*)
      - segmento (aceita perfilProfissional.segmento OU flat.segmento)
      - legal_name, trade_name se existirem (raiz OU dadosBasicos.*)
    """
    uid = _resolve_uid_for_read()
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    # Lê doc profissionais/{uid}
    try:
        doc_ref = _get_db().collection("profissionais").document(uid)
        snap = doc_ref.get()
        if not snap.exists:
            return jsonify({"ok": False, "error": "not_found"}), 404

        data = snap.to_dict() or {}

        # Possíveis caminhos
        dados_basicos = (data.get("dadosBasicos") or {}) if isinstance(data.get("dadosBasicos"), dict) else {}
        perfil_prof   = (data.get("perfilProfissional") or {}) if isinstance(data.get("perfilProfissional"), dict) else {}

        # Consolidação tolerante a esquemas antigos/novos
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
            "segmento": segmento or "",  # se vazio, o front chamará /integracoes/cnpj/<cnpj>
            "legal_name": legal_nm or "",
            "trade_name": trade_nm or "",
        }

        return jsonify({"ok": True, "data": flat}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500

@config_bp.route('/api/configuracao', methods=['POST'], strict_slashes=False)
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
