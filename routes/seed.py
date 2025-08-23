# routes/seed.py
from flask import Blueprint, request, jsonify
from services import db as dbsvc
from services.db import now_ts

seed_bp = Blueprint("seed_bp", __name__)

@seed_bp.route("/_seed/profissional", methods=["POST"])
def seed_profissional():
    """
    Cria/atualiza 'profissionais/{uid}' sem exigir áudio.
    Aceita (JSON):
      uid (str) [obrigatório]
      nome (str) [opcional]
      email (str) [opcional]
      sistema (obj) {origem, escopo} [opcional]
      configInicial (obj) [opcional] -> mesclado no doc
    """
    data = request.get_json(silent=True) or {}

    uid = (data.get("uid") or "").strip()
    if not uid:
        return jsonify(ok=False, error="uid obrigatório"), 400

    nome = (data.get("nome") or "").strip() or None
    email = (data.get("email") or "").strip() or None

    sistema_in = data.get("sistema") or {}
    if not isinstance(sistema_in, dict):
        sistema_in = {}
    sistema = {
        "origem": (sistema_in.get("origem") or "seed").strip(),
        "escopo": (sistema_in.get("escopo") or "global").strip(),
    }

    # Monta doc base
    doc = {
        "dadosBasicos": {},
        "sistema": sistema,
        "updatedAt": now_ts(),
    }
    if nome:
        doc["dadosBasicos"]["nome"] = nome
    if email:
        doc["dadosBasicos"]["email"] = email

    # Merge opcional de configInicial
    config_inicial = data.get("configInicial") or {}
    if isinstance(config_inicial, dict) and config_inicial:
        # Se quiser marcar criação:
        config_inicial.setdefault("criadoEm", now_ts())
        doc["configInicial"] = config_inicial

    # Persistência (merge=True evita sobrescrever indevido)
    dbsvc.salvar_config_profissional(uid, doc)

    # Retorna doc final
    out = dbsvc.get_doc(f"profissionais/{uid}")
    return jsonify(ok=True, uid=uid, profissional=out)
