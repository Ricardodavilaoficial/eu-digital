# app.py — entrypoint para runtime Python do Render (produção)
# Webhook Meta + delegação para services/wa_bot (texto+áudio) + endpoints de debug seguros

import os
import json
import logging
import traceback
import requests
import re
import hashlib
import importlib, types  # <-- lazy import do handler
from flask import Flask, jsonify, request, send_from_directory

print("[boot] app.py raiz carregado ✅", flush=True)
logging.basicConfig(level=logging.INFO)

# -------------------------
# Flask / Static / CORS
# -------------------------
app = Flask(__name__, static_folder="public", static_url_path="/")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

try:
    from flask_cors import CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
    print("[init] CORS habilitado para /api/*")
except Exception as e:
    print(f"[warn] flask-cors indisponível: {e}")

# -------------------------
# Helpers comuns
# -------------------------
def _token_fingerprint(tok: str):
    if not tok:
        return {"present": False, "length": 0, "sha256_12": None}
    sha12 = hashlib.sha256(tok.encode("utf-8")).hexdigest()[:12]
    return {"present": True, "length": len(tok), "sha256_12": sha12}

def _only_digits(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())

def _normalize_br_msisdn(wa_id: str) -> str:
    if not wa_id:
        return ""
    digits = _only_digits(wa_id)
    # normaliza celulares BR (inserindo 9 quando vier sem)
    if digits.startswith("55") and len(digits) == 12:
        digits = digits[:4] + "9" + digits[4:]
    return digits

APP_TAG = os.getenv("APP_TAG", "2025-08-27")
UID_DEFAULT = os.getenv("UID_DEFAULT", "ricardo-prod-uid")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "meirobo123")

# -------------------------
# WhatsApp helpers
# -------------------------
def fallback_text(context: str) -> str:
    return f"[FALLBACK] MEI Robo PROD :: {APP_TAG} :: {context}\nDigite 'precos' para ver a lista."

def _send_text(to: str, body: str):
    to_digits = _only_digits(to)
    token = os.getenv("WHATSAPP_TOKEN")
    pnid = os.getenv("PHONE_NUMBER_ID")
    gv = os.getenv("GRAPH_VERSION", "v23.0")
    if not token or not pnid:
        print("[ERROR] CONFIG: Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID", flush=True)
        return False, {"error": "missing_whatsapp_config"}

    url = f"https://graph.facebook.com/{gv}/{pnid}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_digits,
        "type": "text",
        "text": {"body": (body or "")[:4096]},
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        try:
            resp_json = r.json()
        except Exception:
            resp_json = {"raw": r.text}
        print(f"[WHATSAPP][OUTBOUND] to={to_digits} status={r.status_code} resp={json.dumps(resp_json, ensure_ascii=False)[:800]}", flush=True)
        return r.ok, resp_json
    except Exception as e:
        print("[ERROR][SEND]", repr(e), flush=True)
        return False, {"error": repr(e)}

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
        graph_version=os.getenv("GRAPH_VERSION", "v23.0"),
        app_tag=APP_TAG,
        uid_default=UID_DEFAULT,
    )

@app.route("/__routes", methods=["GET"])
def list_routes():
    rules = []
    for r in app.url_map.iter_rules():
        methods = sorted(list(r.methods - {"HEAD", "OPTIONS"}))
        rules.append({"rule": str(r), "endpoint": r.endpoint, "methods": methods})
    return jsonify(routes=rules, count=len(rules))

# -------------------------
# Debug WA + Env Seguro
# -------------------------
@app.get("/__wa_debug")
def __wa_debug():
    fp = _token_fingerprint(os.getenv("WHATSAPP_TOKEN", ""))
    out = {
        "graph_version": os.getenv("GRAPH_VERSION", "v23.0"),
        "phone_number_id": os.getenv("PHONE_NUMBER_ID"),
        "token_fingerprint": fp,
        "pid": os.getpid(),
        "app_tag": APP_TAG,
        "openai_model": os.getenv("OPENAI_NLU_MODEL"),
        "use_llm_for_all": os.getenv("USE_LLM_FOR_ALL"),
    }
    try:
        from services.budget_guard import budget_fingerprint
        out["budget"] = budget_fingerprint()
    except Exception:
        out["budget"] = {"available": False}
    return jsonify(out), 200

def _mask_secret(value: str):
    if not value:
        return {"present": False}
    v = value.strip()
    sha12 = hashlib.sha256(v.encode()).hexdigest()[:12]
    return {"present": True, "length": len(v), "sha256_12": sha12}

@app.route("/__env_safe", methods=["GET"])
def env_safe():
    key = request.args.get("key", "")
    if key != VERIFY_TOKEN:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    safe = {
        "VERIFY_TOKEN": bool(os.getenv("VERIFY_TOKEN")),
        "GRAPH_VERSION": os.getenv("GRAPH_VERSION"),
        "PHONE_NUMBER_ID": os.getenv("PHONE_NUMBER_ID"),
        "OPENAI_NLU_MODEL": os.getenv("OPENAI_NLU_MODEL"),
        "USE_LLM_FOR_ALL": os.getenv("USE_LLM_FOR_ALL"),
        "BUDGET_MONTHLY_USD": os.getenv("BUDGET_MONTHLY_USD"),
        "BUDGET_RESERVE_PCT": os.getenv("BUDGET_RESERVE_PCT"),
        "TZ": os.getenv("TZ"),
        "STT_SECONDS_AVG": os.getenv("STT_SECONDS_AVG"),
        "UID_DEFAULT": os.getenv("UID_DEFAULT"),
        "APP_TAG": os.getenv("APP_TAG"),
        "WHATSAPP_TOKEN": _mask_secret(os.getenv("WHATSAPP_TOKEN")),
        "OPENAI_API_KEY": _mask_secret(os.getenv("OPENAI_API_KEY")),
        "FIREBASE_PROJECT_ID": os.getenv("FIREBASE_PROJECT_ID"),
        "FIREBASE_CREDENTIALS_JSON": {"present": bool(os.getenv("FIREBASE_CREDENTIALS_JSON"))},
        "FIREBASE_SERVICE_ACCOUNT_JSON": {"present": bool(os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON"))},
        "GOOGLE_APPLICATION_CREDENTIALS_JSON": {"present": bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"))},
        "ELEVEN_API_KEY": _mask_secret(os.getenv("ELEVEN_API_KEY")),
        "ELEVEN_VOICE_ID": os.getenv("ELEVEN_VOICE_ID"),
        "DEV_FORCE_ADMIN": os.getenv("DEV_FORCE_ADMIN"),
        "DEV_FAKE_UID": os.getenv("DEV_FAKE_UID"),
    }
    return jsonify({"ok": True, "env": safe})

# -------------------------
# Firestore utils (debug)
# -------------------------
try:
    from services.db import get_doc, list_collection, get_db
except Exception as e:
    get_doc = None
    list_collection = None
    get_db = None
    print(f"[warn] services.db indisponível: {e}")

@app.route("/__ping_firestore", methods=["GET"])
def ping_firestore():
    if get_db is None:
        return jsonify({"ok": False, "error": "services.db not available"}), 500
    try:
        client = get_db()
        _ = next(client.collections(), None)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/__doc", methods=["GET"])
def debug_doc():
    """
    Auto-detecta: se path tiver número PAR de segmentos => documento.
                 se path tiver número ÍMPAR de segmentos => coleção (lista).
    Suporta ?field=nomeCampo para retornar apenas um campo de um documento.
    """
    if get_doc is None:
        return jsonify({"ok": False, "error": "services.db not available"}), 500

    path = request.args.get("path", "").strip()
    field = request.args.get("field", "").strip()
    limit = int(request.args.get("limit", "10"))

    if not path:
        return jsonify({"ok": False, "error": "missing ?path="}), 400

    parts = [p for p in path.split("/") if p]
    try:
        if len(parts) % 2 == 0:
            doc = get_doc(path)
            if doc is None:
                return jsonify({"ok": True, "kind": "doc", "path": path, "data": None})
            if field:
                return jsonify({"ok": True, "kind": "doc", "path": path, "field": field, "data": doc.get(field)})
            return jsonify({"ok": True, "kind": "doc", "path": path, "data": doc})
        else:
            items = list_collection(path, limit=limit)
            return jsonify({"ok": True, "kind": "collection", "collection": path, "count": len(items), "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/__list", methods=["GET"])
def debug_list():
    if list_collection is None:
        return jsonify({"ok": False, "error": "services.db not available"}), 500
    col = request.args.get("col")
    limit = int(request.args.get("limit", "5"))
    if not col:
        return jsonify({"ok": False, "error": "missing ?col="}), 400
    try:
        items = list_collection(col, limit=limit)
        return jsonify({"ok": True, "collection": col, "count": len(items), "items": items})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

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

# --- Lazy import do handler do WhatsApp ---
_WA_BOT_MOD = None
def _load_wa_bot():
    """Tenta importar (ou reimportar) services.wa_bot de forma segura."""
    global _WA_BOT_MOD
    if _WA_BOT_MOD and isinstance(_WA_BOT_MOD, types.ModuleType):
        return _WA_BOT_MOD
    try:
        _WA_BOT_MOD = importlib.import_module("services.wa_bot")
        print("[init] services.wa_bot importado", flush=True)
        return _WA_BOT_MOD
    except Exception as e:
        print(f"[init][erro] não consegui importar services.wa_bot: {e}", flush=True)
        _WA_BOT_MOD = None
        return None

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

    # 7) Carregar handler
    wa_mod = _load_wa_bot()

    # 8) Delegar processamento do change.value (ou responder fallback se indisponível)
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                if not wa_mod or not hasattr(wa_mod, "process_change"):
                    # tenta avisar o usuário, sem deixar a conversa “muda”
                    try:
                        msgs = value.get("messages") or []
                        if msgs and isinstance(msgs, list):
                            to_msisdn = _normalize_br_msisdn(msgs[0].get("from") or "")
                            if to_msisdn:
                                _send_text(to_msisdn, fallback_text("handler-indisponivel"))
                    except Exception:
                        pass
                    print("[ERROR] HANDLER: services.wa_bot não disponível ou sem process_change", flush=True)
                    continue

                # handler ok
                wa_mod.process_change(value, _send_text, UID_DEFAULT, APP_TAG)
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
