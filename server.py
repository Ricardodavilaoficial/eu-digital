# server.py — ponte explícita p/ app da raiz (evita conflitos) + rotas de diagnóstico/util
import os, importlib.util, json
from flask import request, jsonify

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(ROOT, "app.py")

# Carrega app.py por caminho (nome de módulo isolado)
spec = importlib.util.spec_from_file_location("root_app", APP_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader, "Erro ao montar spec do app.py"
spec.loader.exec_module(module)

# expõe o Flask app para o gunicorn
app = module.app

# log de fingerprint no startup
print(f"[server] loaded app from {APP_PATH}", flush=True)

# -------------------------------------------------------------------
# Helpers locais (fallback) — caso o app.py não exponha as funções
# -------------------------------------------------------------------
def _normalize_br_msisdn_local(wa_id: str) -> str:
    if not wa_id:
        return ""
    digits = "".join(ch for ch in wa_id if ch.isdigit())
    if digits.startswith("55") and len(digits) == 12:  # sem o 9 após DDD
        digits = digits[:4] + "9" + digits[4:]
    return digits

def _send_text_local(to: str, body: str):
    import requests
    to_digits = "".join(ch for ch in (to or "") if ch.isdigit())
    TOKEN = os.getenv("WHATSAPP_TOKEN")
    PNI = os.getenv("PHONE_NUMBER_ID")
    GV = os.getenv("GRAPH_VERSION", "v22.0")
    if not TOKEN or not PNI:
        print("[ERROR] CONFIG: Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID", flush=True)
        return False, {"error": "missing_whatsapp_config"}
    url = f"https://graph.facebook.com/{GV}/{PNI}/messages"
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
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

# Pega helpers do app.py se existirem; senão usa fallback local
_normalize = getattr(module, "_normalize_br_msisdn", _normalize_br_msisdn_local)
_send_text = getattr(module, "_send_text", _send_text_local)

# -------------------------------------------------------------------
# Rota de diagnóstico para ver se as rotas existem
# -------------------------------------------------------------------
@app.get("/__whoami")
def __whoami():
    routes = sorted([str(r.rule) for r in app.url_map.iter_rules()])
    return {
        "app_path": APP_PATH,
        "has_/health": "/health" in routes,
        "has_/api/send-text": "/api/send-text" in routes,
        "routes_sample": [r for r in routes if r in ("/health", "/api/send-text", "/webhook", "/healthz", "/__routes", "/")],
    }

# -------------------------------------------------------------------
# Adiciona /health (sempre)
# -------------------------------------------------------------------
@app.get("/health")
def health():
    return jsonify(
        ok=True,
        service="mei-robo-prod",
        has_whatsapp_token=bool(os.getenv("WHATSAPP_TOKEN")),
        has_phone_number_id=bool(os.getenv("PHONE_NUMBER_ID")),
        graph_version=os.getenv("GRAPH_VERSION", "v22.0"),
    )

# -------------------------------------------------------------------
# Adiciona /api/send-text (sempre)
# -------------------------------------------------------------------
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

    to_norm = _normalize(to)
    print(f"[API][SEND_TEXT] to={to} normalized={to_norm} body_preview={body[:80]}", flush=True)
    ok, resp = _send_text(to_norm, body)
    return ({"ok": True, "resp": resp}, 200) if ok else ({"ok": False, "resp": resp}, 500)
