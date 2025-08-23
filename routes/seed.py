# routes/seed.py
from flask import Blueprint, request, jsonify
from services import db as dbsvc

seed_bp = Blueprint("seed_bp", __name__)

@seed_bp.route("/_seed/profissional", methods=["POST"])
def seed_profissional():
    data = request.get_json(silent=True) or {}
    uid = (data.get("uid") or "").strip()
    if not uid:
        return jsonify(ok=False, error="uid obrigatório"), 400

    nome = (data.get("nome") or "").strip() or None
    email = (data.get("email") or "").strip() or None
    origem = (data.get("origem") or "seed").strip()
    escopo = (data.get("escopo") or "global").strip()

    doc = {
        "dadosBasicos": {
            **({"nome": nome} if nome else {}),
            **({"email": email} if email else {}),
        },
        "sistema": {
            "origem": origem,
            "escopo": escopo,
        },
    }

    # Merge no Firestore
    dbsvc.salvar_config_profissional(uid, doc)
    out = dbsvc.get_doc(f"profissionais/{uid}")
    return jsonify(ok=True, uid=uid, profissional=out)
