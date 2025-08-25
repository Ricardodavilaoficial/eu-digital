# app.py — entrypoint para runtime Python do Render (produção)
# Unifica CORS, healthcheck, blueprints antigos e novos + rotas de debug
# + Webhook da Meta (GET challenge + POST eventos) com auto-reply e logs

import os
import json
import logging
import traceback
import requests
from flask import Flask, jsonify, request, send_from_directory
print("[boot] app.py raiz carregado ✅", flush=True)

# -------- logging básico --------
logging.basicConfig(level=logging.INFO)

# Serve arquivos estáticos da pasta /public como raiz do site
app = Flask(__name__, static_folder="public", static_url_path="/")
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

# CORS apenas para /api/* (frontend local chamando backend no Render)
try:
    from flask_cors import CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
    print("[init] CORS habilitado para /api/*")
except Exception as e:
    print(f"[warn] flask-cors indisponível: {e}")

# -------------------------
# Registro de Blueprints
# -------------------------
def _register_bp(bp, name: str):
    try:
        app.register_blueprint(bp)
        print(f"[bp] Registrado: {name}")
    except Exception as e:
        print(f"[bp][erro] Falhou ao registrar {name}: {e}")
        traceback.print_exc()

# Blueprints já existentes no seu projeto
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

# Novos (onboarding + importação de preços)
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

# Seed (criação/atualização de profissionais sem exigir áudio)
try:
    from routes.seed import seed_bp
    _register_bp(seed_bp, "seed_bp (/_seed/profissional)")
except Exception as e:
    print(f"[bp][warn] seed_bp não registrado: {e}")
    traceback.print_exc()

# -------------------------
# Healthcheck e Debug
# -------------------------
@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(ok=True, scope="app")

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

@app.route("/__import_check", methods=["GET"])
def import_check():
    import importlib, traceback as tb
    results = {}

    def ensure_registered(bp_name: str, module_name: str, attr_name: str):
        try:
            mod = importlib.import_module(module_name)
            bp = getattr(mod, attr_name)
            if bp_name not in app.blueprints:
                app.register_blueprint(bp)
            return {"ok": True, "registered": True}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": tb.format_exc()}

    results["configuracao"] = ensure_registered("config", "routes.configuracao", "config_bp")
    results["importar_precos"] = ensure_registered("importar_precos", "routes.importar_precos", "importar_bp")
    return jsonify(results)

# --- Firestore debug (consulta direta) ---
from services import db as dbsvc

@app.route("/__doc", methods=["GET"])
def debug_doc():
    """
    Ex.: /__doc?path=profissionais/demo
    Mostra dados do doc e suas subcoleções.
    """
    path = (request.args.get("path") or "").strip()
    if not path:
        return jsonify(error="use ?path=colecao/doc[/subcolecao/doc]"), 400
    ref = dbsvc.db.document(path)
    snap = ref.get()
    subcols = []
    if snap.exists:
        try:
            subcols = [c.id for c in ref.collections()]
        except Exception:
            subcols = []
    return jsonify(
        path=path,
        exists=bool(snap.exists),
        data=(snap.to_dict() if snap.exists else None),
        subcollections=subcols
    )

@app.route("/__list", methods=["GET"])
def debug_list():
    """
    Ex.: /__list?col=profissionais/demo/precos&limit=5
    Lista documentos de uma coleção/subcoleção.
    """
    col = (request.args.get("col") or "").strip()
    try:
        limit = int(request.args.get("limit") or 5)
    except Exception:
        limit = 5
    if not col:
        return jsonify(error="use ?col=colecao[/subcolecao]"), 400
    q = dbsvc.db.collection(col).limit(max(1, min(50, limit)))
    try:
        docs = [{"id": d.id, **(d.to_dict() or {})} for d in q.stream()]
    except Exception as e:
        return jsonify(error=str(e)), 500
    return jsonify(col=col, count=len(docs), docs=docs)

# -------------------------
# WhatsApp / Webhook + Utilidades
# -------------------------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "meirobo123")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v22.0")

def _normalize_br_msisdn(wa_id: str) -> str:
    """
    Ajusta MSISDN do Brasil para apenas dígitos.
    Se vier sem o '9' após o DDD (12 dígitos no total), insere o '9'.
    Ex.: 55 51 8XXXXXXX -> 55 51 9 8XXXXXXX
    """
    if not wa_id:
        return ""
    digits = "".join(ch for ch in wa_id if ch.isdigit())
    if digits.startswith("55") and len(digits) == 12:  # sem o 9
        digits = digits[:4] + "9" + digits[4:]
    return digits

def _send_text(to: str, body: str):
    """Envia mensagem de texto pelo WhatsApp Cloud API."""
    to_digits = "".join(ch for ch in (to or "") if ch.isdigit())
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("[ERROR] CONFIG: Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID", flush=True)
        return False, {"error": "missing_whatsapp_config"}

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
        return r.ok, resp_json
    except Exception as e:
        print("[ERROR] SEND:", repr(e), flush=True)
        return False, {"error": repr(e)}

# GET /webhook (verificação da Meta)
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

# POST /webhook (eventos reais) — resiliente a JSON inválido (fallback RAW)
@app.post("/webhook")
def receive_webhook():
    # 1) Leia o corpo cru (para diagnosticar e fallback)
    try:
        raw = request.get_data(cache=True, as_text=True)  # cache=True permite reuso
        if raw:
            print(f"[WEBHOOK][RAW] {raw[:800]}", flush=True)
        else:
            print("[WEBHOOK][RAW] <vazio>", flush=True)
    except Exception as e:
        raw = ""
        print("[WEBHOOK][RAW][ERROR]", repr(e), flush=True)

    # 2) Tente parsear como JSON; se vier vazio, tente do RAW e, como fallback,
    #    tente extrair de form-encoded (quando proxies enviam como form)
    data = {}
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}

    if not data and raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = {}

    if not data and request.form:
        # alguns clientes mandam como form: entry=[...] (string JSON)
        entry = request.form.get("entry")
        if entry:
            try:
                data = {"entry": json.loads(entry)}
            except Exception:
                pass

    # 3) Log do payload interpretado
    try:
        print("[WEBHOOK][INCOMING]", json.dumps(data, ensure_ascii=False)[:1200], flush=True)
        logging.getLogger().info("[WEBHOOK][INCOMING] %s", json.dumps(data, ensure_ascii=False)[:1200])
    except Exception:
        print("[WEBHOOK][INCOMING] (non-json-printable)", flush=True)

    # 4) Processamento normal (auto-reply + status)
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                # 1) Mensagens do usuário -> empresa
                for msg in value.get("messages", []):
                    from_number = msg.get("from")
                    if not from_number:
                        contacts = value.get("contacts", [])
                        if contacts and isinstance(contacts, list):
                            from_number = contacts[0].get("wa_id")
                    msg_type = msg.get("type")
                    msg_id = msg.get("id")
                    print(f"[WEBHOOK][MESSAGE] id={msg_id} type={msg_type} from={from_number}", flush=True)

                    if from_number and msg_type in {"text", "audio", "image", "video", "document", "interactive", "sticker", "location"}:
                        to_msisdn = _normalize_br_msisdn(from_number)
                        body_preview = "Olá! MEI Robô ativo ✅ — sua mensagem foi recebida."
                        _send_text(to_msisdn, body_preview)

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

    # Resposta padrão esperada pela Meta
    return "EVENT_RECEIVED", 200

# -------------------------
# API utilitária de envio (Plano A)
# -------------------------
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

    to_norm = _normalize_br_msisdn(to)
    print(f"[API][SEND_TEXT] to={to} normalized={to_norm} body_preview={body[:80]}", flush=True)
    ok, resp = _send_text(to_norm, body)
    return ({"ok": True, "resp": resp}, 200) if ok else ({"ok": False, "resp": resp}, 500)

# -------------------------
# Página inicial (estática)
# -------------------------
@app.route("/", methods=["GET"])
def index():
    # Serve /public/index.html diretamente (sem Jinja)
    return app.send_static_file("index.html")

# (Opcional) Servir outros arquivos de /public/ (assets, pages, etc.)
@app.route("/<path:path>", methods=["GET"])
def static_proxy(path):
    return send_from_directory(app.static_folder, path)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
