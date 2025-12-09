# routes/configuracao.py
# Rota de configuração inicial do MEI (onboarding)
# - POST /api/configuracao (multipart): salva dados + (opcional) upload de áudio (voz)
# - GET  /api/configuracao (somente leitura): retorna dados achatados p/ front
#
# Extras:
# - Blindagem de CNPJ: não permite alterar CNPJ salvo sem override admin.
# - Suporte a FIREBASE_ADMIN_CREDENTIALS ou GOOGLE_APPLICATION_CREDENTIALS_JSON (inline)
# - Devolve vozClonada no GET p/ player do front (se estiver em profissionais/{uid}).

from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

# Firestore (via Firebase Admin)
import os, json, re, firebase_admin
from firebase_admin import auth as fb_auth, firestore, credentials

# GCS helper oficial do projeto
from services.storage_gcs import upload_bytes_and_get_url

# DB service usado para salvar a config (mantém compat com teu serviço)
from services import db as dbsvc

config_bp = Blueprint('config', __name__)

def _get_db():
    """Inicializa o Firebase Admin se necessário e retorna o client do Firestore."""
    try:
        firebase_admin.get_app()
    except ValueError:
        # 1) Tenta credencial JSON inline por env (recomendado no Render)
        cred_json = (
            os.getenv("FIREBASE_ADMIN_CREDENTIALS")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIAL_JSON")  # fallback sem 'S'
        )
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

# Limite básico de validação (o app.py já tem MAX_CONTENT_LENGTH = 25MB)
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
      2) Fallback: querystring ?uid= (para CMD/testes)
    """
    token = _get_bearer_token()
    if token:
        try:
            decoded = fb_auth.verify_id_token(token)
            uid = decoded.get("uid")
            if uid:
                return uid
        except Exception:
            pass  # cai no fallback
    qs_uid = (request.args.get("uid") or "").strip()
    return qs_uid or None

def _resolve_uid_for_write():
    """
    Resolve o uid para escrita:
      1) Firebase ID Token (Authorization: Bearer) — fluxo normal
      2) Fallback: form uid= — apenas para testes manuais
    """
    token = _get_bearer_token()
    if token:
        try:
            decoded = fb_auth.verify_id_token(token)
            uid = decoded.get("uid")
            if uid:
                return uid
        except Exception:
            pass
    uid_form = (request.form.get("uid") or "").strip()
    return uid_form or None

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
            return v
    return None

def _normalize_cnpj(cnpj):
    """Mantém apenas dígitos; retorna None se entrada vazia."""
    if not cnpj:
        return None
    s = str(cnpj)
    digits = re.sub(r"\D", "", s)
    return digits or None

# ---------------------------
# BLINDAGEM CNPJ (helpers)
# ---------------------------

def _admin_override_enabled() -> bool:
    # Desligado por padrão. Para ligar: ADMIN_CNPJ_OVERRIDE=1
    return os.getenv("ADMIN_CNPJ_OVERRIDE", "0") in ("1", "true", "True", "yes", "YES")

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
    """Lê o doc profissionais/{uid} e retorna o CNPJ normalizado (flat ou dadosBasicos.cnpj)."""
    db = _get_db()
    snap = db.collection("profissionais").document(uid).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    dados_basicos = data.get("dadosBasicos") or {}
    cnpj_raw = _first_non_empty(data.get("cnpj"), dados_basicos.get("cnpj"))
    return _normalize_cnpj(cnpj_raw)

def _compute_perfil_publico(data: dict) -> dict:
    """
    Calcula um "perfil público" a partir do que já temos salvo:
      - branding_choice + public_brand
      - legal_name / trade_name
      - segmento profissional
    Isso é usado pela tela ativar-config.html para mostrar:
      - Como você vai aparecer no MEI Robô
      - Segmento
    """
    dados_basicos = data.get("dadosBasicos") or {}
    perfil_prof = data.get("perfilProfissional") or {}
    branding = data.get("branding") or {}

    legal_nm = _first_non_empty(
        data.get("legal_name"),
        dados_basicos.get("legal_name"),
        dados_basicos.get("razaoSocial"),
        dados_basicos.get("razao_social"),
    )
    trade_nm = _first_non_empty(
        data.get("trade_name"),
        dados_basicos.get("trade_name"),
        dados_basicos.get("nomeFantasia"),
        dados_basicos.get("nome_fantasia"),
    )

    choice = (branding.get("branding_choice") or "").strip()
    public_brand = (branding.get("public_brand") or "").strip()

    # Regra de comoAparecer:
    # 1) custom + public_brand
    # 2) trade_name
    # 3) legal_name
    # 4) fallback para nome básico
    if choice == "custom" and public_brand:
        como = public_brand
    elif choice == "trade_name" and trade_nm:
        como = trade_nm
    elif choice == "legal_name" and legal_nm:
        como = legal_nm
    else:
        como = _first_non_empty(public_brand, trade_nm, legal_nm, dados_basicos.get("nome"))

    segmento_escolhido = _first_non_empty(
        perfil_prof.get("segmento"),
        data.get("segmento"),
    )

    return {
        "comoAparecer": como or "",
        "segmento": segmento_escolhido or "",
    }

# ---------------------------
# GET /api/configuracao
# ---------------------------

@config_bp.route('/api/configuracao', methods=['GET'], strict_slashes=False)
def ler_configuracao():
    """
    Leitura "somente leitura" dos dados básicos do profissional para a tela configuracao.html.
    NÃO altera nada.
    Retorna campos achatados esperados pelo front:
      - nome, email, telefone, cnpj
      - segmento
      - legal_name, trade_name
      - vozClonadaUrl (se existir em profissionais/{uid}.vozClonada.arquivoUrl)
    """
    uid = _resolve_uid_for_read()
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        doc_ref = _get_db().collection("profissionais").document(uid)
        snap = doc_ref.get()
        if not snap.exists:
            return jsonify({"ok": False, "error": "not_found"}), 404

        data = snap.to_dict() or {}

        # caminhos possíveis
        dados_basicos = (data.get("dadosBasicos") or {}) if isinstance(data.get("dadosBasicos"), dict) else {}
        perfil_prof   = (data.get("perfilProfissional") or {}) if isinstance(data.get("perfilProfissional"), dict) else {}
        voz_clonada   = data.get("vozClonada") or {}

        branding      = (data.get("branding") or {}) if isinstance(data.get("branding"), dict) else {}
        estilo        = (data.get("estiloComunicacao") or {}) if isinstance(data.get("estiloComunicacao"), dict) else {}

        # Campos de branding/estilo de comunicação
        public_brand  = _first_non_empty(
            branding.get("public_brand"),
            dados_basicos.get("public_brand"),
        )
        display_nm    = _first_non_empty(
            estilo.get("display_name"),
            dados_basicos.get("display_name"),
            data.get("nome"),
        )

        # Jeito de falar (podem estar dentro de estiloComunicacao)
        formalidade   = (estilo.get("formalidade") or "").strip() if isinstance(estilo, dict) else ""
        saudacao      = (estilo.get("saudacao") or "").strip() if isinstance(estilo, dict) else ""
        closing_text  = (estilo.get("closing_text") or "").strip() if isinstance(estilo, dict) else ""
        janela_resp   = (estilo.get("janela_resposta") or "").strip() if isinstance(estilo, dict) else ""
        janela_custom = (estilo.get("janela_resposta_custom") or "").strip() if isinstance(estilo, dict) else ""

        # Emojis:
        # - preferimos a string salva (estilo.emojis ou data.emojis)
        # - se não existir, inferimos a partir do bool usaEmojis (sim/não)
        emojis_flat = ""
        if isinstance(estilo, dict):
            emojis_flat = (estilo.get("emojis") or "").strip()
        if not emojis_flat:
            emojis_flat = (str(data.get("emojis") or "")).strip()
        if not emojis_flat and isinstance(estilo.get("usaEmojis"), bool):
            emojis_flat = "sim" if estilo.get("usaEmojis") else "nao"

        # consolidação tolerante
        nome      = _first_non_empty(data.get("nome"),      dados_basicos.get("nome"))
        email     = _first_non_empty(data.get("email"),     dados_basicos.get("email"))
        telefone  = _first_non_empty(data.get("telefone"),  dados_basicos.get("telefone"))
        cnpj_raw  = _first_non_empty(data.get("cnpj"),      dados_basicos.get("cnpj"))
        cnpj      = _normalize_cnpj(cnpj_raw)

        segmento  = _first_non_empty(perfil_prof.get("segmento"), data.get("segmento"))

        legal_nm  = _first_non_empty(data.get("legal_name"),  dados_basicos.get("legal_name"))
        trade_nm  = _first_non_empty(data.get("trade_name"),  dados_basicos.get("trade_name"))

        # Status de ativação (onboarding x já ativo)
        status_ativacao = (data.get("statusAtivacao") or "").strip()

        # Perfil público calculado (comoAparecer + segmento)
        perfil_publico = _compute_perfil_publico(data)

        # NOVO bloco flat + especializações (esp1/esp2)
        flat = {
            "uid": uid,
            "nome": nome or "",
            "email": email or "",
            "telefone": telefone or "",
            "cnpj": cnpj or "",
            "segmento": segmento or "",
            "legal_name": legal_nm or "",
            "trade_name": trade_nm or "",
            "public_brand": public_brand or "",
            "display_name": display_nm or "",
            # Jeito de falar
            "formalidade": formalidade or "",
            "emojis": emojis_flat or "",
            "saudacao": saudacao or "",
            "closing_text": closing_text or "",
            "janela_resposta": janela_resp or "",
            "janela_resposta_custom": janela_custom or "",
            # Status de ativação (onboarding x já ativo)
            "statusAtivacao": status_ativacao or "",
            # player no front:
            "vozClonadaUrl": (voz_clonada.get("arquivoUrl") or ""),
            "vozClonada": voz_clonada or None,
            # Infos de branding/MEI para o ativar-config
            "branding_choice": branding.get("branding_choice") or "",
        }

        # especializações (esp1/esp2) só pra enriquecer, se existirem
        especs = perfil_prof.get("especializacoes") or []
        if isinstance(especs, (list, tuple)):
            flat["esp1"] = especs[0] if len(especs) > 0 else ""
            flat["esp2"] = especs[1] if len(especs) > 1 else ""

        # IMPORTANTE: mantemos "data" igual, só acrescentamos "perfil" no topo
        return jsonify({"ok": True, "data": flat, "perfil": perfil_publico}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500

# ---------------------------
# POST /api/configuracao
# ---------------------------

@config_bp.route('/api/configuracao', methods=['POST'], strict_slashes=False)
def salvar_configuracao():
    # -------- Resolve UID --------
    uid = _resolve_uid_for_write()
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    # -------- Campos do form --------
    nome       = (request.form.get('nome') or "").strip()
    email      = (request.form.get('email') or "").strip()
    telefone   = (request.form.get('telefone') or "").strip()
    cnpj_in    = (request.form.get('cnpj') or "").strip()
    cnpj_new   = _normalize_cnpj(cnpj_in)

    segmento   = (request.form.get('segmento') or "").strip()
    esp1       = (request.form.get('esp1') or "").strip()
    esp2       = (request.form.get('esp2') or "").strip()

    # 👇 NOVO: nomes legais/fantasia achatados
    legal_name = (request.form.get('legal_name') or "").strip()
    trade_name = (request.form.get('trade_name') or "").strip()

    formalidade = (request.form.get('formalidade') or "media").strip()
    emojis      = (request.form.get('emojis') or "sim").strip()
    saudacao    = (request.form.get('saudacao') or "").strip()
    closing     = (request.form.get('closing_text') or "").strip()
    display_nm  = (request.form.get('display_name') or "").strip()

    janela_resp = (request.form.get('janela_resposta') or "").strip()
    janela_custom = (request.form.get('janela_resposta_custom') or "").strip()

    branding_choice = (request.form.get('branding_choice') or "").strip()
    public_brand    = (request.form.get('public_brand') or "").strip()

    # -------- BLINDAGEM CNPJ (antes de subir áudio) --------
    try:
        cnpj_current = _read_current_cnpj(uid)
        if cnpj_current:
            if cnpj_new and cnpj_new != cnpj_current and not _is_admin_override(request):
                return jsonify({
                    "ok": False,
                    "error": "CNPJ alteration not allowed",
                    "message": "Alteração de CNPJ não permitida sem aprovação administrativa.",
                    "uid": uid,
                    "current_cnpj": cnpj_current
                }), 409
            if not cnpj_new:
                cnpj_new = cnpj_current
    except Exception as e:
        return jsonify({"ok": False, "error": "internal_error", "detail": f"Falha ao validar CNPJ: {e}"}), 500

    # -------- Áudio (AGORA OPCIONAL NESTE ENDPOINT) --------
    voz_file = request.files.get('voz')
    voz_url = None

    if voz_file and voz_file.filename:
        content_type = (voz_file.content_type or "").lower()
        if not any(content_type.startswith(a.split('/')[0]) or content_type == a for a in ALLOWED_AUDIO_MIMES):
            if not content_type.startswith("audio/"):
                return (f"Tipo de áudio não suportado: {content_type}", 415)

        # Nome seguro
        filename = secure_filename(voz_file.filename or "voz.wav")

        # -------- Upload para GCS (usa helper do projeto) --------
        try:
            buf = voz_file.read()
            # usa content_type se vier; fallback para audio/wav
            ctype = content_type or "audio/wav"
            url, bucket, path, access = upload_bytes_and_get_url(uid, filename, buf, ctype)
            voz_url = url
        except Exception as e:
            return (f"Falha no upload da voz: {e}", 500)

    # -------- Status de ativação: preservar se já existir --------
    existing_status = ""
    try:
        db = _get_db()
        snap = db.collection("profissionais").document(uid).get()
        if snap.exists:
            existing_data = snap.to_dict() or {}
            existing_status = (existing_data.get("statusAtivacao") or "").strip()
    except Exception:
        existing_status = ""

    # Se não houver nada salvo ainda, usamos o default "aguardando-voz"
    status_ativacao = existing_status or "aguardando-voz"

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
            # Guardamos a string completa e o bool para compatibilidade
            "emojis": emojis,  # "sim" | "as_vezes" | "nao"
            "usaEmojis": (emojis == "sim"),
            "saudacao": saudacao,
            "closing_text": closing,
            "display_name": display_nm,
            "janela_resposta": janela_resp,
            "janela_resposta_custom": janela_custom,
        },
        "branding": {
            "branding_choice": branding_choice,
            "public_brand": public_brand,
        },
        # 👇 NOVO: campos achatados para facilitar outras rotas
        "cnpj": cnpj_new or "",
        "legal_name": legal_name,
        "trade_name": trade_name,
        "segmento": segmento,
        # Mantemos statusAtivacao, preservando o valor se já existia
        "statusAtivacao": status_ativacao,
    }

    # Só inclui vozClonada se um novo áudio foi enviado neste POST
    if voz_url:
        doc["vozClonada"] = {
            "arquivoUrl": voz_url,
            "status": "pendente",  # depois que processar na ElevenLabs -> 'ready'
        }

    # -------- Persistência --------
    try:
        # Implementação do dbsvc deve usar set(..., merge=True) ou equivalente
        dbsvc.salvar_config_profissional(uid, doc)
    except Exception as e:
        return (f"Erro ao salvar no Firestore: {e}", 500)

    resp = {"status": "ok", "uid": uid}
    if voz_url:
        resp["vozUrl"] = voz_url

    return jsonify(resp), 200
