# app.py — entrypoint para runtime Python do Render (produção)
# Unifica CORS, healthcheck, blueprints antigos e novos + rotas de debug
# + Webhook da Meta (GET challenge + POST eventos) com log em stdout

import os
import json
import logging
import traceback
from flask import Flask, jsonify, request, send_from_directory

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
# Webhook da Meta (GET challenge + POST eventos)
# -------------------------
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "meirobo123")

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge or "OK", 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def receive_webhook():
    try:
        payload = request.get_json(force=True, silent=True) or {}
        # loga no stdout (Render mostra) e também no logger
        pretty = json.dumps(payload, ensure_ascii=False)
        print("[WEBHOOK][INCOMING]", pretty, flush=True)
        logging.getLogger().info("[WEBHOOK][INCOMING] %s", pretty)
        return jsonify({"ok": True}), 200
    except Exception as e:
        print("[WEBHOOK][ERROR]", str(e), flush=True)
        logging.getLogger().exception("[WEBHOOK][ERROR] %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500

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
