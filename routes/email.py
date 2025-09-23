# routes/email.py
from flask import Blueprint, request, jsonify, render_template
import datetime as dt

email_bp = Blueprint("email_bp", __name__, url_prefix="/api/email")

@email_bp.route("/preview/<etype>", methods=["GET"])
def preview_email(etype):
    # Exemplos de contexto
    if etype == "resumo":
        return render_template("emails/daily_summary.html",
            sender="mei-robo@fujicadobrasil.com.br",
            date_str=dt.datetime.now().strftime("%d/%m"),
            kpis={"servicos": 6, "valor": "R$ 540", "novos": 2},
            rows=[
                {"hora":"08:00","cliente":"Carlos Silva","servico":"Corte masculino","preco":"R$ 60","status":"agendado","obs":""},
                {"hora":"09:30","cliente":"Ana Souza","servico":"Coloração","preco":"R$ 180","status":"agendado","obs":"retocar raiz"},
            ],
            include_tomorrow=False
        )
    if etype == "confirmacao":
        return render_template("emails/confirmation.html",
            sender="mei-robo@fujicadobrasil.com.br",
            data="09/09", hora="14:00", nome="João",
            links={"confirmar":"#ok","reagendar":"#reag","cancelar":"#cancel"}
        )
    if etype == "lembrete":
        return render_template("emails/reminder.html",
            sender="mei-robo@fujicadobrasil.com.br",
            data="09/09", hora="14:00", nome="João", link="#reagendar"
        )
    return "Tipo inválido", 400

@email_bp.route("/test", methods=["POST"])
def test_email():
    payload = request.get_json(force=True, silent=True) or {}
    to_email = payload.get("to") or "seu-email@exemplo.com"
    etype = payload.get("type", "resumo")
    # Aqui você chamaria os send_* conforme o tipo.
    return jsonify({"ok": True, "sent_type": etype, "to": to_email})
