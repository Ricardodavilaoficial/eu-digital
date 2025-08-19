import os
from flask import Flask, request

app = Flask(__name__)
# --- Drop A: Core API (licenças + agenda) ---
try:
    from flask_cors import CORS
    CORS(app, supports_credentials=True)
except Exception:
    pass

from routes.core_api import core_api
app.register_blueprint(core_api)
# --- fim Drop A ---

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "meirobo123")

@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification token mismatch", 403

@app.route("/webhook", methods=["POST"])
def receive():
    # Aqui você processa as mensagens/events (por enquanto só confirma)
    return "EVENT_RECEIVED", 200
# --- Healthcheck direto (fora do blueprint) ---
from flask import jsonify

@app.get("/healthz")
def _healthz():
    return jsonify({"ok": True}), 200

# --- Dump de rotas para diagnóstico ---
@app.get("/__routes")
def _routes_dump():
    # Mostra todas as rotas registradas, para conferirmos se o core_api entrou
    lines = []
    for rule in app.url_map.iter_rules():
        methods = ",".join(sorted(rule.methods - {"HEAD", "OPTIONS"}))
        lines.append(f"{methods:6}  {rule.rule}")
    return "\n".join(sorted(lines)), 200, {"Content-Type": "text/plain; charset=utf-8"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


