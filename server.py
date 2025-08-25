# server.py — ponte explícita p/ app da raiz + rotas utilitárias condicionais
import os, importlib.util, json
from flask import request, jsonify

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(ROOT, "app.py")

# Carrega o app.py da raiz por caminho (evita conflitos de módulo)
spec = importlib.util.spec_from_file_location("root_app", APP_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader, "Erro ao montar spec do app.py"
spec.loader.exec_module(module)

# expõe o Flask app para o gunicorn
app = module.app

print(f"[server] loaded app from {APP_PATH}", flush=True)

# -------------------------------------------------------------------
# Fallback helpers (usados só se o app.py não expor os oficiais)
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

# Usa helpers do app.py se existirem; senão, fallback local
_normalize = getattr(module, "_normalize_br_msisdn", _normalize_br_msisdn_local)
_send_text = getattr(module, "_send_text", _send_text_local)

# -------------------------------------------------------------------
# Diagnóstico (endpoint único para evitar conflito)
# -------------------------------------------------------------------
@app.get("/__whoami", endpoint="server_whoami")
def __whoami():
    routes = sorted([str(r.rule) for r in app.url_map.iter_rules()])
    return {
        "app_path": APP_PATH,
        "has_/health": "/health" in routes,
        "has_/api/send-text": "/api/send-text" in routes,
        "routes_sample": [r for r in routes if r in ("/health", "/api/send-text", "/webhook", "/healthz", "/__routes", "/")],
    }

# -------------------------------------------------------------------
# Adiciona rotas APENAS se estiverem faltando (evita AssertionError)
# -------------------------------------------------------------------
def _register_missing_routes():
    existing_rules = {str(r.rule) for r in app.url_map.iter_rules()}

    if "/health" not in existing_rules:
        def health_local():
            return jsonify(
                ok=True,
                service="mei-robo-prod",
                has_whatsapp_token=bool(os.getenv("WHATSAPP_TOKEN")),
                has_phone_number_id=bool(os.getenv("PHONE_NUMBER_ID")),
                graph_version=os.getenv("GRAPH_VERSION", "v22.0"),
            )
        app.add_url_rule("/health", endpoint="server_health", view_func=health_local, methods=["GET"])
        print("[server] /health (server_health) adicionado", flush=True)

    if "/api/send-text" not in existing_rules:
        def api_send_text_local():
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

        app.add_url_rule("/api/send-text", endpoint="server_api_send_text", view_func=api_send_text_local, methods=["GET", "POST"])
        print("[server] /api/send-text (server_api_send_text) adicionado", flush=True)

_register_missing_routes()
