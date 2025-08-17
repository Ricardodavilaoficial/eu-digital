from flask import Flask, request
import os, requests

app = Flask(__name__)

# Variáveis (defina no Render)
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "meirobo123")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")  # token temporário da Meta
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")  # ID do número de teste
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v22.0")

def send_text(to: str, body: str):
    """Envia mensagem de texto pelo WhatsApp Cloud API."""
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
    r = requests.post(url, headers=headers, json=payload, timeout=10)
    print("SEND STATUS:", r.status_code, r.text, flush=True)

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        # Verificação do webhook pela Meta
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "ERROR", 403

    # Recebimento de eventos (mensagens)
    data = request.get_json(silent=True) or {}
    print("INCOMING:", data, flush=True)

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    from_number = msg.get("from")
                    # Evita responder a mensagens de status, etc.
                    if from_number and msg.get("type") in {"text", "audio", "image", "video", "document", "interactive"}:
                        send_text(from_number, "Olá! MEI Robô ativo ✅ — sua mensagem foi recebida.")
    except Exception as e:
        print("ERROR:", e, flush=True)

    return "EVENT_RECEIVED", 200

# Render usa o Gunicorn para servir (ver Start Command). Esta execução local é só para dev.
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
