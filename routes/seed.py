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

    nome = (data.get("nome") or "").strip()
    email = (data.get("email") or "").strip()

    sistema_in = data.get("sistema") or {}
    if not isinstance(sistema_in, dict):
        sistema_in = {}
    sistema = {
        "origem": (sistema_in.get("origem") or "seed").strip(),
        "escopo": (sistema_in.get("escopo") or "global").strip(),
    }

    # Doc base
    doc = {
        "sistema": sistema,
        "updatedAt": now_ts(),
    }

    # Só inclui dadosBasicos se houver algo a gravar (evita wipe com {}).
    dados_basicos = {}
    if nome:
        dados_basicos["nome"] = nome
    if email:
        dados_basicos["email"] = email
    if dados_basicos:
        doc["dadosBasicos"] = dados_basicos

    # Merge opcional de configInicial
    config_inicial = data.get("configInicial")
    if isinstance(config_inicial, dict) and config_inicial:
        ci = dict(config_inicial)
        ci.setdefault("criadoEm", now_ts())
        doc["configInicial"] = ci

    # Persistência (merge=True evita sobrescrever indevido)
    dbsvc.salvar_config_profissional(uid, doc)

    out = dbsvc.get_doc(f"profissionais/{uid}")
    return jsonify(ok=True, uid=uid, profissional=out)


@seed_bp.route("/_seed/precos", methods=["POST"])
def seed_precos():
    """
    Insere itens de preços em 'profissionais/{uid}/precos'.
    Aceita (JSON):
      uid (str) [obrigatório]
      itens (list) [obrigatório] - cada item com:
        - nome (str)       [obrigatório]
        - preco (float)    [opcional; default 0]
        - duracaoPadraoMin (int) [opcional; default 30]
    """
    data = request.get_json(silent=True) or {}
    uid = (data.get("uid") or "").strip()
    itens = data.get("itens") or []
    if not uid:
        return jsonify(ok=False, error="uid obrigatório"), 400
    if not isinstance(itens, list) or not itens:
        return jsonify(ok=False, error="itens[] é obrigatório"), 400

    norm = []
    for it in itens:
        if not isinstance(it, dict):
            continue
        nome = str(it.get("nome") or "").strip()
        if not nome:
            continue
        try:
            preco = float(it.get("preco") or 0)
        except Exception:
            preco = 0.0
        try:
            dur = int(it.get("duracaoPadraoMin") or 30)
        except Exception:
            dur = 30
        norm.append({"nome": nome, "preco": preco, "duracaoPadraoMin": dur})

    if not norm:
        return jsonify(ok=False, error="itens sem dados válidos"), 400

    inserted = dbsvc.salvar_tabela_precos(uid, norm)
    return jsonify(ok=True, uid=uid, inseridos=inserted)
