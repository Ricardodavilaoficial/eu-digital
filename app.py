# app.py — entrypoint para runtime Python do Render (produção)
# Mantém: health, debug, firestore-utils, /api/send-text, estáticos
# Webhook agora é servido via routes/stripe_webhook (blueprint)

import os
import json
import logging
import traceback
import re
import hashlib
import importlib, types
import time
from typing import List, Tuple
from urllib.parse import urlparse
from urllib import request as ulreq
from urllib import parse as ulparse
from flask import Flask, jsonify, request, send_from_directory, redirect
from routes.admin import admin_bp
app.register_blueprint(admin_bp)

# >>> Verificação de Autoridade (Fase 1)
from routes.verificacao_autoridade import verificacao_bp
from middleware.authority_gate import init_authority_gate

# --- INÍCIO: integração CNPJ.ws pública (blueprint) ---
# Depende do arquivo: routes/cnpj_publica.py
# Se ainda não existir o pacote "routes", crie um __init__.py vazio dentro de /routes
try:
    from routes.cnpj_publica import bp_cnpj_publica
except Exception as e:
    bp_cnpj_publica = None
    logging.exception("Falha ao importar bp_cnpj_publica (CNPJ.ws pública): %s", e)

# >>> Stripe Webhook
from routes.stripe_webhook import stripe_webhook_bp
from routes.stripe_checkout import stripe_checkout_bp
from routes.conta_status import bp_conta
# --- FIM: integração CNPJ.ws pública ---


print("[boot] app.py raiz carregado ✅", flush=True)
logging.basicConfig(level=logging.INFO)

# --------------------------------------------------------------------
# 1) Cria a app primeiro e configura CORS-base controlado por ENV
# --------------------------------------------------------------------
app = Flask(__name__, static_folder="public", static_url_path="/")
from flask_cors import CORS  # importa depois de criar app
CORS(app)  # se você já usa CORS custom, mantenha o seu

# Blueprints já existentes (registro direto onde necessário)
# - verificacao_bp e bp_cnpj_publica ficam aqui para garantir disponibilidade
app.register_blueprint(verificacao_bp)
if bp_cnpj_publica:
    app.register_blueprint(bp_cnpj_publica)

# ✅ Stripe Webhook (SEM auth/CSRF; precisa estar acessível publicamente)
app.register_blueprint(stripe_webhook_bp)
print("[boot] Stripe Webhook blueprint registrado ✅", flush=True)
# ✅ Stripe Checkout API
app.register_blueprint(stripe_checkout_bp)
print("[boot] Stripe Checkout blueprint registrado ✅", flush=True)
# ✅ Gate + Status (contratos do front)
app.register_blueprint(bp_conta)
# (se houver middlewares de auth/CSRF, mantenha-os DEPOIS — e isente /webhooks/stripe)

_ALLOWED = os.environ.get("ALLOWED_ORIGINS", "")
if _ALLOWED:
    origins = [o.strip() for o in _ALLOWED.split(",") if o.strip()]
else:
    # fallback seguro para dev/local se a ENV não estiver definida
    origins = ["http://127.0.0.1:5501", "http://localhost:5501"]

# CORS-base: libera origens definidas (todas as rotas)
CORS(app, resources={r"/*": {"origins": origins}})

app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

# --------------------------------------------------------------------
# 2) (Opcional) CORS adicional para /api/* como você já tinha
#    Mantido para compatibilidade, pode coexistir com o CORS-base.
# --------------------------------------------------------------------
try:
    from flask_cors import CORS as _CORS2
    _CORS2(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)
    print("[init] CORS habilitado para /api/*")
except Exception as e:
    print(f"[warn] flask-cors indisponível: {e}")

# --------------------------------------------------------------------
# 3) Agora que o app existe, importe e registre blueprints auxiliares
#    com helper (evita NameError e import circular)
# --------------------------------------------------------------------
def _register_bp(bp, name: str):
    try:
        app.register_blueprint(bp)
        print(f"[bp] Registrado: {name}")
    except Exception as e:
        print(f"[bp][erro] Falhou ao registrar {name}: {e}")
        traceback.print_exc()

# Blueprint de autenticação (novo)
try:
    from routes.auth_bp import auth_bp
    _register_bp(auth_bp, "auth_bp (/auth/whoami)")
except Exception as e:
    print(f"[bp][warn] auth_bp não registrado: {e}")
    traceback.print_exc()

# -------------------------
# Helpers de telefone (com fallback)
# -------------------------
def _token_fingerprint(tok: str):
    if not tok:
        return {"present": False, "length": 0, "sha256_12": None}
    sha12 = hashlib.sha256(tok.encode("utf-8")).hexdigest()[:12]
    return {"present": True, "length": len(tok), "sha256_12": sha12}

def _only_digits(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())

_br_candidates = None
_br_equivalence_key = None
_digits_only_external = None

try:
    from services.phone_utils import br_candidates as _br_candidates, br_equivalence_key as _br_equivalence_key, digits_only as _digits_only_external  # type: ignore
    print("[phone] usando services.phone_utils (externo)")
except Exception:
    print("[phone] services.phone_utils não encontrado; usando fallback local")

    _DIGITS_RE = re.compile(r"\D+")

    def _digits_only_local(s: str) -> str:
        return _DIGITS_RE.sub("", s or "")

    def _ensure_cc_55(d: str) -> str:
        d = _digits_only_local(d)
        # Remove zeros internacionais tipo 0055
        if d.startswith("00"):
            d = d[2:]
        if not d.startswith("55"):
            d = "55" + d
        return d

    def _br_split(msisdn: str) -> Tuple[str, str, str]:
        d = _ensure_cc_55(msisdn)
        cc = d[:2]
        rest = d[2:]
        ddd = rest[:2] if len(rest) >= 10 else rest[:2]
        local = rest[2:]
        return cc, ddd, local

    def _br_equivalence_key_local(msisdn: str) -> str:
        cc, ddd, local = _br_split(msisdn)
        local8 = _digits_only_local(local)[-8:]  # últimos 8
        return f"{cc}{ddd}{local8}"

    def _br_candidates_local(msisdn: str) -> List[str]:
        cc, ddd, local = _br_split(msisdn)
        local_digits = _digits_only_local(local)
        cands = set()
        if len(local_digits) >= 9 and local_digits[0] == "9":
            # Já tem 9 -> gera com e sem 9
            with9 = f"{cc}{ddd}{local_digits}"
            without9 = f"{cc}{ddd}{local_digits[1:]}" if len(local_digits) >= 1 else f"{cc}{ddd}{local_digits}"
            cands.add(with9)
            cands.add(without9)
        elif len(local_digits) == 8:
            # 8 dígitos -> gera sem e com 9
            without9 = f"{cc}{ddd}{local_digits}"
            with9 = f"{cc}{ddd}9{local_digits}"
            cands.add(without9)
            cands.add(with9)
        else:
            cands.add(f"{cc}{ddd}{local_digits}")
        # Mantemos apenas 55 + DDD(2) + 8/9
        return [c for c in cands if len(c) in (12, 13)]

    _br_candidates = _br_candidates_local
    _br_equivalence_key = _br_equivalence_key_local
    _digits_only_external = _digits_only_local

def br_candidates(msisdn: str) -> List[str]:
    try:
        return _br_candidates(msisdn)  # type: ignore
    except Exception:
        d = _only_digits(msisdn)
        if d.startswith("55") and len(d) == 12:
            return [d[:4] + "9" + d[4:], d]
        return [d]

def br_equivalence_key(msisdn: str) -> str:
    try:
        return _br_equivalence_key(msisdn)  # type: ignore
    except Exception:
        d = _only_digits(msisdn)
        if d.startswith("55"):
            cc = d[:2]
            ddd = d[2:4] if len(d) >= 4 else ""
            local8 = d[-8:]
            return f"{cc}{ddd}{local8}"
        local8 = d[-8:]
        return local8

def _normalize_br_msisdn(wa_id: str) -> str:
    """
    Mantida por compatibilidade: retorna 55 + DDD(2) + local(9) quando detectar celular sem o '9'.
    """
    if not wa_id:
        return ""
    digits = _only_digits(wa_id)
    if digits.startswith("55") and len(digits) == 12:
        digits = digits[:4] + "9" + digits[4:]
    return digits

# -------------------------
# Config
# -------------------------
APP_TAG = os.getenv("APP_TAG", "2025-08-27")
UID_DEFAULT = os.getenv("UID_DEFAULT", "ricardo-prod-uid")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "meirobo123")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v23.0")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID") or os.getenv("PHONE_NUMBER_ID")
FRONTEND_BASE = os.getenv("FRONTEND_BASE", "")  # ex.: https://mei-robo-prod.web.app

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

def fallback_text(context: str) -> str:
    return f"[FALLBACK] MEI Robo PROD :: {APP_TAG} :: {context}\nDigite 'precos' para ver a lista."

# -------------------------
# Blueprints existentes (mantidos + novos)
# (OBS: verificacao_bp e bp_cnpj_publica já foram registrados acima)
# -------------------------
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

# >>> Compat de licenças/cupom (aceita POST /licencas/ativar-cupom)
try:
    from routes.compat_licencas import bp as licencas_bp
    _register_bp(licencas_bp, "licencas_bp (/licencas/ativar-cupom compat)")
except Exception as e:
    print(f"[bp][warn] licencas_bp não registrado: {e}")
    traceback.print_exc()

# >>> Novo: CAPTCHA (Turnstile) — valida token e seta cookie curto
try:
    from routes.captcha_bp import captcha_bp
    _register_bp(captcha_bp, "captcha_bp (/captcha/verify)")
except Exception as e:
    print(f"[bp][warn] captcha_bp não registrado: {e}")
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

# >>> Webhook legado (se existir)
try:
    from routes.webhook import bp_webhook
    _register_bp(bp_webhook, "bp_webhook (/webhook)")
except Exception as e:
    print(f"[bp][erro] import bp_webhook: {e}")
    traceback.print_exc()

# >>> Verificação de Autoridade — (REMOVIDO registro duplicado via helper)
# já registramos verificacao_bp no topo. Mantemos apenas o init do gate.
try:
    init_authority_gate(app, restricted_patterns=[
        r"^/api/cupons/.*",
        r"^/api/importar-precos$",
        r"^/admin/.*",
        r"^/webhook/.*"
    ])
    print("[gate] Authority Gate registrado (condicional por VERIFICACAO_AUTORIDADE)")
except Exception as e:
    print(f"[gate][warn] authority_gate não inicializado: {e}")
    traceback.print_exc()

# -------------------------
# Health / routes list
# -------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        ok=True,
        service="mei-robo-prod",
        has_whatsapp_token=bool(os.getenv("WHATSAPP_TOKEN")),
        has_phone_number_id=bool(PHONE_NUMBER_ID),
        graph_version=GRAPH_VERSION,
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
        "graph_version": GRAPH_VERSION,
        "phone_number_id": PHONE_NUMBER_ID,
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
        "GRAPH_VERSION": GRAPH_VERSION,
        "PHONE_NUMBER_ID": PHONE_NUMBER_ID,
        "OPENAI_NLU_MODEL": os.getenv("OPENAI_NLU_MODEL"),
        "USE_LLM_FOR_ALL": os.getenv("USE_LLM_FOR_ALL"),
        "BUDGET_MONTHLY_USD": os.getenv("BUDGET_MONTHLY_USD"),
        "BUDGET_RESERVE_PCT": os.getenv("BUDGET_RESERVE_PCT"),
        "TZ": os.getenv("TZ"),
        "STT_SECONDS_AVG": os.getenv("STT_SECONDS_AVG"),
        "UID_DEFAULT": os.getenv("UID_DEFAULT"),
        "APP_TAG": os.getenv("APP_TAG"),
        "FRONTEND_BASE": os.getenv("FRONTEND_BASE"),
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
        # >>> Incluímos as chaves do Turnstile no relatório seguro (mascarado)
        "TURNSTILE_SECRET_KEY": _mask_secret(os.getenv("TURNSTILE_SECRET_KEY", "")),
        "HUMAN_COOKIE_SIGNING_KEY": _mask_secret(os.getenv("HUMAN_COOKIE_SIGNING_KEY", "")),
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
# Lazy import do wa_bot + status
# -------------------------
_WA_BOT_MOD = None
_WA_BOT_LAST_ERR = None

def _load_wa_bot():
    global _WA_BOT_MOD, _WA_BOT_LAST_ERR
    if _WA_BOT_MOD and isinstance(_WA_BOT_MOD, types.ModuleType):
        return _WA_BOT_MOD
    try:
        _WA_BOT_MOD = importlib.import_module("services.wa_bot")
        _WA_BOT_LAST_ERR = None
        print("[init] services.wa_bot importado", flush=True)
        return _WA_BOT_MOD
    except Exception as e:
        _WA_BOT_MOD = None
        _WA_BOT_LAST_ERR = f"{type(e).__name__}: {e}\n" + (traceback.format_exc(limit=3) or "")
        print(f"[init][erro] não consegui importar services.wa_bot: {e}", flush=True)
        return None

@app.get("/__wa_bot_status")
def wa_bot_status():
    mod = _load_wa_bot()
    return jsonify({
        "ok": True,
        "service": "mei-robo-prod",
        "app_tag": APP_TAG,
        "uid_default": UID_DEFAULT,
        "loaded": bool(mod and hasattr(mod, "process_change")),
        "has_process_change": bool(getattr(mod, "process_change", None)) if mod else False,
        "last_error": _WA_BOT_LAST_ERR,
        "module": getattr(mod, "__file__", None) if mod else None,
    }), 200

# -------------------------
# API utilitária de envio (texto) — agora com candidatos com/sem 9
# -------------------------
from services.wa_send import send_text as wa_send_text

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

    # Gera candidatos robustos (com/sem 9) + fallback de normalização
    cands = []
    try:
        cands = br_candidates(to)
    except Exception:
        cands = []
    if not cands:
        cands = [_normalize_br_msisdn(to)]

    # De-dup
    seen = set()
    cands = [c for c in cands if not (c in seen or seen.add(c))]

    eq_key = br_equivalence_key(to)
    print(f"[API][SEND_TEXT] to={to} eq_key={eq_key} cands={cands} body_preview={body[:80]}", flush=True)

    last_resp = None
    for cand in cands:
        ok, resp = wa_send_text(cand, body)
        print(f"[API][SEND_TEXT][try] cand={cand} ok={ok}", flush=True)
        if ok:
            return {"ok": True, "used": cand, "eq_key": eq_key, "resp": resp}, 200
        last_resp = resp

    return {"ok": False, "eq_key": eq_key, "tried": cands, "resp": last_resp}, 500

# -------------------------
# MSISDN debug helper
# -------------------------
@app.route("/__msisdn_debug", methods=["GET"])
def msisdn_debug():
    num = request.args.get("num", "")
    if not num:
        return jsonify({"ok": False, "error": "missing ?num="}), 400

    digits = _only_digits(num)
    norm = _normalize_br_msisdn(num)
    try:
        cands = br_candidates(num)
    except Exception:
        cands = [norm]
    try:
        key = br_equivalence_key(num)
    except Exception:
        key = None

    out = {
        "ok": True,
        "input": num,
        "digits_only": digits,
        "normalized": norm,
        "candidates": cands,
        "equivalence_key": key,
    }
    return jsonify(out), 200

# =========================
# Cupom — rotas absolutas (Plano B à prova de falhas do blueprint)
# =========================
from flask import g
from datetime import datetime, timezone
from services.coupons import find_cupom_by_codigo, validar_consumir_cupom
from services.db import db
import base64 as _b64

def _uid_from_authorization() -> str | None:
    """
    Extrai UID do Authorization: Bearer <idToken> lendo o payload do JWT (sem validar assinatura).
    Temporário para manter produção enquanto o services.auth.auth_required não está disponível.
    """
    auth = request.headers.get("Authorization", "").strip()
    if not auth.lower().startswith("bearer "):
        return None
    tok = auth.split(" ", 1)[1].strip()
    parts = tok.split(".")
    if len(parts) < 2:
        return None
    try:
        pad = "=" * ((4 - len(parts[1]) % 4) % 4)
        payload = json.loads(_b64.urlsafe_b64decode((parts[1] + pad).encode()).decode())
        uid = payload.get("user_id") or payload.get("uid") or payload.get("sub")
        return uid or None
    except Exception:
        return None

# ---- Turnstile helpers (LEGADO)
def _sign_value(raw: str, key: str) -> str:
    mac = hashlib.sha256((raw).encode("utf-8")).hexdigest()
    return mac[:16]

def _human_cookie_ok() -> bool:
    raw = request.cookies.get("human_ok", "")
    if not raw:
        return False
    parts = raw.split(".")
    if len(parts) == 3:
        val, ts_str, sig = parts
        key = os.getenv("HUMAN_COOKIE_SIGNING_KEY", "").strip()
        if not key:
            return False
        base = f"{val}.{ts_str}"
        expect = _sign_value(base, key)
        if sig != expect:
            return False
        try:
            ts = int(ts_str)
        except Exception:
            return False
        if (time.time() - ts) > 5 * 60:
            return False
        return val == "1"
    # modo sem assinatura (não recomendado, mas tolerado se já existir)
    return raw == "1"

def _verify_turnstile_token(token: str) -> bool:
    secret = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
    if not secret or not token:
        return False
    data = ulparse.urlencode({
        "secret": secret,
        "response": token,
        "remoteip": request.headers.get("CF-Connecting-IP") or request.remote_addr or ""
    }).encode("utf-8")
    req = ulreq.Request(TURNSTILE_VERIFY_URL, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded"
    })
    try:
        with ulreq.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            j = json.loads(body)
            return bool(j.get("success"))
    except Exception:
        return False

def _is_human_ok() -> bool:
    # 1) cookie assinado válido (preferido)
    if _human_cookie_ok():
        return True
    # 2) fallback: token passado no header ou body → verificação ao vivo
    tok = (
        request.headers.get("cf-turnstile-response")
        or (request.get_json(silent=True) or {}).get("cf_token")
        or (request.get_json(silent=True) or {}).get("cf_resp")
        or (request.get_json(silent=True) or {}).get("token")
        or request.headers.get("x-turnstile-token")
    )
    if tok and _verify_turnstile_token(tok):
        return True
    return False

# ---------- Validação Pública (sem login) ----------
@app.route("/api/cupons/validar-publico", methods=["OPTIONS"])
def _preflight_api_cupons_validar_publico():
    return ("", 204)

def _parse_iso_maybe_z(s: str):
    if not s:
        return None
    try:
        # Python 3.11 aceita offset, mas nem sempre 'Z'; normaliza Z->+00:00
        if isinstance(s, str) and s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

@app.route("/api/cupons/validar-publico", methods=["POST"])
def api_cupons_validar_publico():
    """
    Verifica se o cupom *pode* ser usado (não consome). Sem exigir autenticação.
    Entrada: { "codigo": "ABC-123" }
    Saída: 200 {"ok": true, "cupom": {...}}  |  400 {"ok": false, "reason": "..."}
    """
    try:
        data = request.get_json(silent=True) or {}
        codigo = (data.get("codigo") or "").strip()
        if not codigo:
            return jsonify({"ok": False, "reason": "codigo_obrigatorio"}), 400

        from services.coupons import find_cupom_by_codigo
        cupom = find_cupom_by_codigo(codigo)
        if not cupom:
            return jsonify({"ok": False, "reason": "nao_encontrado"}), 400

        # checks básicos
        status = (cupom.get("status") or "").lower()
        if status in {"used", "revogado", "invalido"}:
            return jsonify({"ok": False, "reason": status}), 400

        if cupom.get("ativo") is False:
            return jsonify({"ok": False, "reason": "inativo"}), 400

        usos = int(cupom.get("usos") or 0)
        usos_max = int(cupom.get("usosMax") or 1)
        if usos_max > 0 and usos >= usos_max:
            return jsonify({"ok": False, "reason": "sem_usos_restantes"}), 400

        exp = cupom.get("expiraEm")
        if exp:
            dt = _parse_iso_maybe_z(exp if isinstance(exp, str) else str(exp))
            now_utc = datetime.now(timezone.utc)
            if dt and dt < now_utc:
                return jsonify({"ok": False, "reason": "expirado"}), 400

        # sucesso
        public = {
            "codigo": cupom.get("codigo"),
            "tipo": cupom.get("tipo"),
            "escopo": cupom.get("escopo"),
            "expiraEm": cupom.get("expiraEm"),
            "usos": usos,
            "usosMax": usos_max,
        }
        return jsonify({"ok": True, "cupom": public}), 200
    except Exception as e:
        return jsonify({"ok": False, "reason": "erro_interno", "detail": str(e)}), 500

# ---------- Ativar (com token OU uid) ----------
@app.route("/api/cupons/ativar", methods=["OPTIONS"])
def _preflight_api_cupons_ativar():
    return ("", 204)

@app.route("/api/cupons/ativar", methods=["POST"])
def api_cupons_ativar():
    try:
        data = request.get_json(silent=True) or {}
        codigo = (data.get("codigo") or "").strip()
        if not codigo:
            return jsonify({"erro": "Código do cupom é obrigatório"}), 400

        uid = _uid_from_authorization() or (data.get("uid") or "").strip()
        if not uid:
            # comportamento alinhado com a UI ("sessão expirada")
            return jsonify({"erro": "Não autenticado"}), 401

        from services.coupons import find_cupom_by_codigo, validar_consumir_cupom
        cupom = find_cupom_by_codigo(codigo)

        # >>> envia ip/ua para auditoria (blindagem)
        ctx = {
            "ip": request.headers.get("CF-Connecting-IP")
                  or (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() if request.headers.get("X-Forwarded-For") else "")
                  or request.remote_addr
                  or "",
            "ua": request.headers.get("User-Agent") or "",
        }
        ok, msg, plano = validar_consumir_cupom(cupom, uid, ctx=ctx)
        if not ok:
            return jsonify({"erro": msg}), 400

        from services.db import db
        now_iso = datetime.now(timezone.utc).isoformat()
        prof_ref = db.collection("profissionais").document(uid)
        prof_ref.set(
            {
                "plan": plano or "start",
                "plano": plano or "start",
                "licenca": {
                    "origem": "cupom",
                    "codigo": codigo,
                    "activatedAt": now_iso,
                },
                "updatedAt": now_iso,
            },
            merge=True,
        )
        return jsonify({"mensagem": "Plano ativado com sucesso pelo cupom!", "plano": (plano or "start")}), 200
    except Exception as e:
        return jsonify({"erro": f"ativar_cupom[app]: {str(e)}"}), 500

# ---------- Legado absoluto (codigo+uid no body; sem token) ----------
@app.route("/api/cupons/ativar-cupom", methods=["OPTIONS"])
def _preflight_api_cupons_ativar_legado():
    return ("", 204)

@app.route("/api/cupons/ativar-cupom", methods=["POST"])
def api_cupons_ativar_legado():
    try:
        # >>> Blindagem: exige humano_ok OU token Turnstile válido no header/body
        if not _is_human_ok():
            return jsonify({"erro": "captcha_required"}), 403

        data = request.get_json(silent=True) or {}
        codigo = (data.get("codigo") or "").strip()
        uid = (data.get("uid") or "").strip()
        if not codigo or not uid:
            return jsonify({"erro": "Código do cupom e UID são obrigatórios"}), 400

        from services.coupons import find_cupom_by_codigo, validar_consumir_cupom
        cupom = find_cupom_by_codigo(codigo)

        # >>> envia ip/ua para auditoria (blindagem)
        ctx = {
            "ip": request.headers.get("CF-Connecting-IP")
                  or (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() if request.headers.get("X-Forwarded-For") else "")
                  or request.remote_addr
                  or "",
            "ua": request.headers.get("User-Agent") or "",
        }
        ok, msg, plano = validar_consumir_cupom(cupom, uid, ctx=ctx)
        if not ok:
            return jsonify({"erro": msg}), 400

        from services.db import db
        now_iso = datetime.now(timezone.utc).isoformat()
        prof_ref = db.collection("profissionais").document(uid)
        prof_ref.set(
            {
                "plan": plano or "start",
                "plano": plano or "start",
                "licenca": {
                    "origem": "cupom",
                    "codigo": codigo,
                    "activatedAt": now_iso,
                },
                "updatedAt": now_iso,
            },
            merge=True,
        )
        return jsonify({"mensagem": "Plano ativado com sucesso pelo cupom!", "plano": (plano or "start")}), 200
    except Exception as e:
        return jsonify({"erro": f"ativar_cupom_legado[app]: {str(e)}"}), 500

# -------------------------
# Rotas de conveniência — /ativar → página de ativação
# -------------------------
@app.get("/ativar")
def goto_ativar():
    """
    Redireciona para a tela de ativação do frontend (se FRONTEND_BASE estiver setado),
    ou tenta servir /pages/ativar.html localmente. Fallback para index.html.
    """
    try:
        if FRONTEND_BASE:
            dest = FRONTEND_BASE.rstrip("/") + "/pages/ativar.html"
            if urlparse(dest).scheme:
                return redirect(dest, code=302)
        # se não houver FRONTEND_BASE, tenta servir local
        return app.send_static_file("pages/ativar.html")
    except Exception:
        return app.send_static_file("index.html")

# -------------------------
# Static
# -------------------------
@app.route("/", methods=["GET"])
def index():
    return app.send_static_file("index.html")

@app.route("/<path:path>", methods=["GET"])
def static_proxy(path):
    return send_from_directory(app.static_folder, path)

# -------------------------
# Main
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
