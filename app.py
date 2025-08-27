# app.py — entrypoint para runtime Python do Render (produção)
# Magro: Webhook Meta + delegação para services/wa_bot (texto+áudio)

import os
import json
import logging
import traceback
import requests
import re
import hashlib
from flask import Flask, jsonify, request, send_from_directory

print("[boot] app.py raiz carregado ✅", flush=True)
logging.basicConfig(level=logging.INFO)

# -------------------------
# Flask / Static / CORS
# -------------------------
app = Flask(__name__, static_folder="public", static_url_path="/")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

def _token_fingerprint(tok: str):
    if not tok:
        return {"present": False, "length": 0, "sha256_12": None}
    sha12 = hashlib.sha256(tok.encode("utf-8")).hexdigest()[:12]
    return {"present": True, "length": len(tok), "sha256_12": sha12}

@app.get("/__wa_debug")
def __wa_debug():
    fp = _token_fingerprint(os.getenv("WHATSAPP_TOKEN", ""))
    return jsonify({
        "graph_version": os.getenv("GRAPH_VERSION", "v22.0"),
        "phone_number_id": os.getenv("PHONE_NUMBER_ID"),
        "token_fingerprint": fp,
        "pid": os.getpid(),
    }), 200

try:
    from flask_cors import CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
    print("[init] CORS habilitado para /api/*")
except Exception as e:
    print(f"[warn] flask-cors indisponível: {e}")

# -------------------------
# Blueprints existentes
# -------------------------
def _register_bp(bp, name: str):
    try:
        app.register_blueprint(bp)
        print(f"[bp] Registrado: {name}")
    except Exception as e:
        print(f"[bp][erro] Falhou ao registrar {name}: {e}")
        traceback.print_exc()

try:
    from routes.routes import routes
    _register_bp(routes, "routes")
except Exception as e:
    print(f"[bp][erro] import routes: {e}")
    traceback.print_exc()

try:
    from routes.teste_eleven_route import teste_eleven_route
    _register_bp(teste_eleven_route, "teste_eleven_route")
except Exception as e:
    print(f"[bp][erro] import teste_eleven_route: {e}")
    traceback.print_exc()

try:
    from routes.cupons import cupons_bp
    _register_bp(cupons_bp, "cupons_bp")
except Exception as e:
    print(f"[bp][erro] import cupons_bp: {e}")
    traceback.print_exc()

try:
    from routes.core_api import core_api
    _register_bp(core_api, "core_api")
except Exception as e:
    print(f"[bp][erro] import core_api: {e}")
    traceback.print_exc()

try:
    from routes.configuracao import config_bp
    _register_bp(config_bp, "config_bp (/api/configuracao)")
except Exception as e:
    print(f"[bp][warn] config_bp não registrado: {e}")
    traceback.print_exc()

try:
    from routes.importar_precos import importar_bp
    _register_bp(importar_bp, "importar_bp (/api/importar-precos)")
except Exception as e:
    print(f"[bp][warn] importar_bp não registrado: {e}")
    traceback.print_exc()

try:
    from routes.seed import seed_bp
    _register_bp(seed_bp, "seed_bp (/_seed/profissional)")
except Exception as e:
    print(f"[bp][warn] seed_bp não registrado: {e}")
    traceback.print_exc()

# -------------------------
# Health / util
# -------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        ok=True,
        service="mei-robo-prod",
        has_whatsapp_token=bool(os.getenv("WHATSAPP_TOKEN")),
        has_phone_number_id=bool(os.getenv("PHONE_NUMBER_ID")),
        graph_version=os.getenv("GRAPH_VERSION", "v22.0"),
    )

@app.route("/__routes", methods=["GET"])
def list_routes():
    rules = []
    for r in app.url_map.iter_rules():
        methods = sorted(list(r.methods - {"HEAD", "OPTIONS"}))
        rules.append({"rule": str(r), "endpoint": r.endpoint, "methods": methods})
    return jsonify(routes=rules, count=len(rules))

# -------------------------
# WhatsApp helpers
# -------------------------
def _only_digits(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())

def _normalize_br_msisdn(wa_id: str) -> str:
    if not wa_id:
        return ""
    digits = _only_digits(wa_id)
    if digits.startswith("55") and len(digits) == 12:
        digits = digits[:4] + "9" + digits[4:]
    return digits

APP_TAG = os.getenv("APP_TAG", "2025-08-27")
UID_DEFAULT = os.getenv("UID_DEFAULT", "ricardo-prod-uid")

def fallback_text(context: str) -> str:
    return f"[FALLBACK] MEI Robo PROD :: {APP_TAG} :: {context}\nDigite 'precos' para ver a lista."

def _send_text(to: str, body: str):
    to_digits = _only_digits(to)
    token = os.getenv("WHATSAPP_TOKEN")
    pnid = os.getenv("PHONE_NUMBER_ID")
    gv = os.getenv("GRAPH_VERSION", "v22.0")
    if not token or not pnid:
        print("[ERROR] CONFIG: Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID", flush=True)
        return False, {"error": "missing_whatsapp_config"}

    url = f"https://graph.facebook.com/{gv}/{pnid}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": to_digits, "type": "text", "text": {"body": body}}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        try:
            resp_json = r.json()
        except Exception:
            resp_json = {"raw": r.text}
        print(f"[WHATSAPP][OUTBOUND] to={to_digits} status={r.status_code} resp={json.dumps(resp_json, ensure_ascii=False)[:800]}", flush=True)
        return r.ok, resp_json
    except Exception as e:
        print("[ERROR] SEND]:", repr(e), flush=True)
        return False, {"error": repr(e)}

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "meirobo123")

# -------------------------
# Webhook
# -------------------------
@app.get("/webhook")
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("[WEBHOOK][VERIFY] success", flush=True)
        return str(challenge or "OK"), 200
    print(f"[WEBHOOK][VERIFY] fail mode={mode} token={token}", flush=True)
    return "Forbidden", 403

# delegação para o handler externo
from services import wa_bot  # <— NOVO

@app.post("/webhook")
def receive_webhook():
    # 0) Headers para debug
    try:
        ct = request.content_type or "<none>"
        clen = request.content_length
        sig = request.headers.get("X-Hub-Signature-256")
        print(f"[WEBHOOK][CT] {ct} | len={clen} | has_sig256={bool(sig)}", flush=True)
    except Exception:
        pass

    # 1) RAW
    try:
        raw = request.get_data(cache=True, as_text=True) or ""
        if raw:
            print(f"[WEBHOOK][RAW] {raw[:800]}", flush=True)
        raw_clean = raw.lstrip("\ufeff").strip()
    except Exception as e:
        raw, raw_clean = "", ""
        print("[WEBHOOK][RAW][ERROR]", repr(e), flush=True)

    data = {}

    # 2) Parse JSON
    if raw_clean:
        try:
            data = json.loads(raw_clean)
        except Exception as e:
            print("[WEBHOOK][PARSE][raw][ERROR]", repr(e), flush=True)

    if not data:
        try:
            data = request.get_json(force=True, silent=True) or {}
        except Exception as e:
            print("[WEBHOOK][PARSE][flask][ERROR]", repr(e), flush=True)

    if not data and request.form:
        entry = request.form.get("entry")
        if entry:
            try:
                data = {"entry": json.loads(entry)}
            except Exception as e:
                print("[WEBHOOK][PARSE][form][ERROR]", repr(e), flush=True)

    # 5) Fallback regex (self-test)
    if not data and raw_clean:
        m = re.search(r'"from"\s*:\s*"([^"]+)"', raw_clean)
        if m:
            from_number = m.group(1)
            to_msisdn = _normalize_br_msisdn(from_number)
            print(f"[WEBHOOK][FALLBACK][regex] from={from_number} -> {to_msisdn}", flush=True)
            _send_text(to_msisdn, fallback_text("path=app.py:regex"))
            return "EVENT_RECEIVED", 200

    # 6) Log do payload interpretado
    try:
        print("[WEBHOOK][INCOMING]", json.dumps(data, ensure_ascii=False)[:1200], flush=True)
        logging.getLogger().info("[WEBHOOK][INCOMING] %s", json.dumps(data, ensure_ascii=False)[:1200])
    except Exception:
        print("[WEBHOOK][INCOMING] (non-json-printable)", flush=True)

    # 7) Delegar processamento do change.value
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                wa_bot.process_change(value, _send_text, UID_DEFAULT, APP_TAG)
    except Exception as e:
        print("[ERROR] HANDLER:", repr(e), flush=True)

    return "EVENT_RECEIVED", 200

# -------------------------
# API utilitária de envio
# -------------------------
@app.route("/api/send-text", methods=["GET", "POST"])
def api_send_text():
    if request.method == "GET":
        to = request.args.get("to", "")
        body = request.args.get("body", "")
    else:
        data = request.get_json(silent=True) or {}
        to = data.get("to", "")
        body = data.get("body", "")

    if not to or not body:
        return {"ok": False, "error": "missing_to_or_body"}, 400

    to_norm = _normalize_br_msisdn(to)
    print(f"[API][SEND_TEXT] to={to} normalized={to_norm} body_preview={body[:80]}", flush=True)
    ok, resp = _send_text(to_norm, body)
    return ({"ok": True, "resp": resp}, 200) if ok else ({"ok": False, "resp": resp}, 500)

# -------------------------
# Static
# -------------------------
@app.route("/", methods=["GET"])
def index():
    return app.send_static_file("index.html")

@app.route("/<path:path>", methods=["GET"])
def static_proxy(path):
    return send_from_directory(app.static_folder, path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
