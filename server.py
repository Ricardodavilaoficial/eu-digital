# server.py — ponte explícita p/ app da raiz (evita conflitos de módulo "app")
import os, importlib.util, json

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(ROOT, "app.py")

spec = importlib.util.spec_from_file_location("root_app", APP_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader, "Erro ao montar spec do app.py"
spec.loader.exec_module(module)

# expõe o Flask app para o gunicorn
app = module.app

# log de fingerprint no startup
print(f"[server] loaded app from {APP_PATH}", flush=True)

# rota de diagnóstico: mostra se /health e /api/send-text existem de fato
@app.get("/__whoami")
def __whoami():
    routes = sorted([str(r.rule) for r in app.url_map.iter_rules()])
    return {
        "app_path": APP_PATH,
        "has_/health": "/health" in routes,
        "has_/api/send-text": "/api/send-text" in routes,
        "routes_sample": [r for r in routes if r in ("/health", "/api/send-text", "/webhook", "/healthz", "/__routes", "/")]
    }
