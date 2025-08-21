# app.py — entrypoint para runtime Python do Render (produção)
# Unifica CORS, healthcheck, blueprints antigos e novos + rota de debug /__routes

import os
import traceback
from flask import Flask, render_template, jsonify

app = Flask(__name__)
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
    """Registra um blueprint e loga sucesso/erro."""
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

# Novos blueprints (onboarding + importação de preços)
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

# -------------------------
# Healthcheck e Debug
# -------------------------
@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(ok=True, scope="app")

# Lista todas as rotas carregadas (debug)
# -------------------------
# Diagnóstico de imports (on-demand)
# -------------------------
@app.route("/__import_check", methods=["GET"])
def import_check():
    import importlib, traceback
    results = {}

    # helper para registrar só se ainda não estiver
    def ensure_registered(bp_name: str, module_name: str, attr_name: str):
        try:
            mod = importlib.import_module(module_name)
            bp = getattr(mod, attr_name)
            if bp_name not in app.blueprints:
                app.register_blueprint(bp)
            return {"ok": True, "registered": True}
        except Exception as e:
            return {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc()
            }

    # Tenta importar/registrar os dois blueprints novos
    results["configuracao"] = ensure_registered("config", "routes.configuracao", "config_bp")
    results["importar_precos"] = ensure_registered("importar_precos", "routes.importar_precos", "importar_bp")

    return jsonify(results)

@app.route("/__routes", methods=["GET"])
def list_routes():
    rules = []
    for r in app.url_map.iter_rules():
        methods = sorted(list(r.methods - {"HEAD", "OPTIONS"}))
        rules.append({"rule": str(r), "endpoint": r.endpoint, "methods": methods})
    return jsonify(routes=rules, count=len(rules))

# -------------------------
# Página inicial
# -------------------------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

# Execução local opcional (não usado no Render)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
