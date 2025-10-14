# Placeholder seguro da Voz V2 (desligado por flag por padrão)
from flask import Blueprint, jsonify

voz_upload_bp = Blueprint("voz_upload_v2", __name__, url_prefix="/api")

@voz_upload_bp.route("/configuracao", methods=["POST"])
def upload_voz_config():
    # Ainda não ativado: quando VOZ_V2_ENABLED=true, ideal é apontar para a nova lógica
    # Mantido placeholder para não surpreender; por padrão, flag fica OFF.
    return jsonify({"ok": False, "error": "voz_v2_disabled"}), 501
