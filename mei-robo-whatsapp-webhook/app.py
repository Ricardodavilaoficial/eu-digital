from flask import Flask, request, jsonify
import os, sys, json, requests

app = Flask(__name__)

# ------------------------------------------------------------
# Drop A: Core API (licenças + agenda) DENTRO do webhook app
# ------------------------------------------------------------
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# CORS (útil se o front chamar direto)
try:
    from flask_cors import CORS
    CORS(app, supports_credentials=True)
except Exception:
    pass

# Blueprint principal (se existir)
try:
    from routes.core_api import core_api
    app.register_blueprint(core_api)
except Exception as e:
    print("[WARN] core_api blueprint not loaded:", repr(e), flush=True)

# ------------------------------------------------------------
# Variáveis de ambiente
# ------------------------------------------------------------
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "meirobo123")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v22.0")

# ------------------------------------------------------------
# Utilidades
# ------------------------------------------------------------
def normalize_br_msisdn(wa_id: str) -> str:
    """
    Ajusta MSISDN do Brasil para apenas dígitos.
    Se vier sem o '9' após o DDD (12 dígitos no total), insere o '9'.
    Ex.: 55 51 8XXXXXXX -> 55 51 9 8XXXXXXX
    """
    if not wa_id:
        return ""
    digits = "".join(ch for ch in wa_id if ch.isdigit())
    if digits.startswith("55"):
        if len(digits) == 12:  # sem o '9'
            digits = digits[:4] + "9" + digits[4:]
    return digits

def send_text(to: str, body: str):
    """Envia mensagem de texto pelo WhatsApp Cloud API."""
    to_digits = "".join(ch for ch in (to or "") if ch.isdigit())
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("[ERROR] CONFIG: Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID", flush=True)
        return {"ok": False, "error": "missing_whatsapp_config"}

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_digits,
        "type": "text",
        "text": {"body": body},
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        try:
            resp_json = r.json()
        except Exception:
            resp_json = {"raw": r.text}
        print(f"[WHATSAPP][OUTBOUND] to={to_digits} status={r.status_code} resp={json.dumps(resp_json, ensure_ascii=False)[:800]}", flush=True)
        return {"ok": r.ok, "status_code": r.status_code, "resp": resp_json}
    except Exception as e:
        print("[ERROR] SEND:", repr(e), flush=True)
        return {"ok": False, "error": repr(e)}

# ------------------------------------------------------------
# Rotas de saúde/diagnóstico
# ------------------------------------------------------------
@app.get("/healthz")
def _healthz():
    return jsonify({"ok": True}), 200

@app.get("/health")
def health():
    return {
        "ok": True,
        "has_whatsapp_token": bool(WHATSAPP_TOKEN),
        "has_phone_number_id": bool(PHONE_NUMBER_ID),
        "graph_version": GRAPH_VERSION,
        "service": "mei-robo-whatsapp-webhook",
    }, 200

@app.get("/__routes")
def _routes_dump():
    lines = []
    for rule in app.url_map.iter_rules():
        methods = ",".join(sorted(rule.methods - {"HEAD", "OPTIONS"}))
        lines.append(f"{methods:6}  {rule.rule}")
    return "\n".join(sorted(lines)), 200, {"Content-Type": "text/plain; charset=utf-8"}

@app.get("/")
def root():
    return {"status": "ok", "service": "mei-robo-whatsapp-webhook", "webhook": "/webhook"}, 200

# ------------------------------------------------------------
# Rota utilitária de envio (Plano A)
# ------------------------------------------------------------
@app.route("/api/send-text", methods=["GET", "POST"])
def api_send_text():
    """
    GET: /api/send-text?to=+55XXXXXXXXXXX&body=Mensagem
    POST: JSON { "to": "+55XXXXXXXXXXX", "body": "Mensagem" }
    """
    if request.method == "GET":
        to = request.args.get("to", "")
        body = request.args.get("body", "")
    else:
        data = request.get_json(silent=True) or {}
        to = data.get("to", "")
        body = data.get("body", "")

    if not to or not body:
        return {"ok": False, "error": "missing_to_or_body"}, 400

    to_norm = normalize_br_msisdn(to)
    print(f"[API][SEND_TEXT] to={to} normalized={to_norm} body_preview={body[:80]}", flush=True)
    result = send_text(to_norm, body)
    return result, (200 if result.get("ok") else 500)

# ------------------------------------------------------------
# Webhook (Meta)
# ------------------------------------------------------------
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    # Verificação (GET)
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("[WEBHOOK][VERIFY] success", flush=True)
            return str(challenge), 200
        print(f"[WEBHOOK][VERIFY] fail mode={mode} token={token}", flush=True)
        return "ERROR", 403

    # Eventos (POST)
    data = request.get_json(silent=True) or {}
    try:
        print("[WEBHOOK][INCOMING]", json.dumps(data, ensure_ascii=False)[:1200], flush=True)
    except Exception:
        print("[WEBHOOK][INCOMING] (non-json-printable)", flush=True)

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # 1) Mensagens de usuário -> empresa
                for msg in value.get("messages", []):
                    from_number = msg.get("from")
                    if not from_number:
                        contacts = value.get("contacts", [])
                        if contacts and isinstance(contacts, list):
                            from_number = contacts[0].get("wa_id")
                    msg_type = msg.get("type")
                    msg_id = msg.get("id")

                    print(f"[WEBHOOK][MESSAGE] id={msg_id} type={msg_type} from={from_number}", flush=True)

                    # Resposta automática mínima (confirmação de recepção)
                    if from_number and msg_type in {"text", "audio", "image", "video", "document", "interactive", "sticker", "location"}:
                        to_msisdn = normalize_br_msisdn(from_number)
                        body_preview = "Olá! MEI Robô ativo ✅ — sua mensagem foi recebida."
                        send_text(to_msisdn, body_preview)

                # 2) Status de mensagens (delivered, read, sent, failed)
                for st in value.get("statuses", []):
                    status = st.get("status")
                    message_id = st.get("id")
                    ts = st.get("timestamp")
                    recipient_id = st.get("recipient_id")
                    errors = st.get("errors")
                    print(f"[WEBHOOK][STATUS] id={message_id} status={status} ts={ts} recipient={recipient_id} errors={errors}", flush=True)

    except Exception as e:
        print("[ERROR] HANDLER:", repr(e), flush=True)

    return "EVENT_RECEIVED", 200

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
