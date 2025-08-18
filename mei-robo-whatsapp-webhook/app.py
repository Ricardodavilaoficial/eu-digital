from flask import Flask, request
import os, requests, json

app = Flask(__name__)

# Variáveis (defina no Render)
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "meirobo123")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")         # token temporário da Meta
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")       # ID do número de teste
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v22.0")

# ---------- Utilidades ----------

def normalize_br_msisdn(wa_id: str) -> str:
    """
    Ajusta MSISDN do Brasil: se vier sem o '9' (ex.: 55 51 8XXXXXXX),
    insere o '9' depois do DDD (55 + DD + 9 + 8 dígitos).
    Retorna somente dígitos (sem '+').
    """
    if not wa_id:
        return ""
    digits = "".join(ch for ch in wa_id if ch.isdigit())
    if digits.startswith("55"):
        # Ex.: 55 51 85648608 (12 dígitos) -> 55 51 9 85648608 (13 dígitos)
        if len(digits) == 12:
            digits = digits[:4] + "9" + digits[4:]
    return digits

def send_text(to: str, body: str):
    """Envia mensagem de texto pelo WhatsApp Cloud API."""
    to = "".join(ch for ch in (to or "") if ch.isdigit())  # só dígitos
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("CONFIG ERROR: Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID", flush=True)
        return
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        print("SEND STATUS:", r.status_code, r.text, flush=True)
    except Exception as e:
        print("SEND ERROR:", repr(e), flush=True)

# ---------- Rotas ----------

@app.route("/", methods=["GET"])
def root():
    return {"status": "ok", "service": "mei-robo-whatsapp-webhook", "webhook": "/webhook"}, 200

@app.route("/health", methods=["GET"])
def health():
    return {
        "ok": True,
        "has_whatsapp_token": bool(WHATSAPP_TOKEN),
        "has_phone_number_id": bool(PHONE_NUMBER_ID),
        "graph_version": GRAPH_VERSION
    }, 200

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("WEBHOOK VERIFIED", flush=True)
            return challenge, 200
        print("WEBHOOK VERIFY FAIL", mode, token, flush=True)
        return "ERROR", 403

    data = request.get_json(silent=True) or {}
    try:
        print("INCOMING:", json.dumps(data, ensure_ascii=False), flush=True)
    except Exception:
        print("INCOMING:", data, flush=True)

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    from_number = msg.get("from")
                    if not from_number:
                        contacts = value.get("contacts", [])
                        if contacts and isinstance(contacts, list):
                            from_number = contacts[0].get("wa_id")
                    msg_type = msg.get("type")
                    if from_number and msg_type in {"text", "audio", "image", "video", "document", "interactive"}:
                        to_msisdn = normalize_br_msisdn(from_number)
                        print(f"REPLY_TO: original={from_number} normalized={to_msisdn}", flush=True)
                        send_text(to_msisdn, "Olá! MEI Robô ativo ✅ — sua mensagem foi recebida.")
    except Exception as e:
        print("HANDLER ERROR:", repr(e), flush=True)

    return "EVENT_RECEIVED", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
