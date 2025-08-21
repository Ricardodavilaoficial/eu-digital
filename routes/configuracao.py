# routes/configuracao.py
# Rota de configuração inicial do MEI (onboarding)
# - Recebe multipart/form-data com os campos do formulário e o arquivo de voz
# - Faz upload do áudio para o GCS
# - Salva/mescla os dados em Firestore: profissionais/{uid}

from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

from services import db as dbsvc
from services import gcs_handler

config_bp = Blueprint('config', __name__)

# Limite básico de validação (o main.py já tem MAX_CONTENT_LENGTH = 25MB)
ALLOWED_AUDIO_MIMES = {
    "audio/wav", "audio/x-wav",
    "audio/mpeg", "audio/mp3",
    "audio/ogg", "audio/webm", "audio/x-m4a", "audio/aac", "audio/flac"
}

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
