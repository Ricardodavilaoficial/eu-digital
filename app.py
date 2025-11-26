# app.py — MEI Robô (produção) — fachada enxuta com flags
# Mantém: CORS/health/env/version/wa_debug/send-text, Stripe webhooks/checkout,
# blueprints principais, cupons (rotas absolutas), webhook GET challenge (Meta).
# Modulações: CNPJ e Voz V2 atrás de flags; imports protegidos por try/except.

import os, io, struct, json, logging, traceback, re, hashlib, importlib, types, time
from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from urllib import request as ulreq, parse as ulparse
from flask import Flask, jsonify, request, Response, g
from flask_cors import CORS
from uuid import uuid4  # <-- usado no req_id do /api/cadastro

print("[boot] app.py fachada enxuta carregado ✓", flush=True)
logging.basicConfig(level=logging.INFO)

# =====================================
# App + CORS (whitelist apenas /api/*)
# =====================================
app = Flask(__name__, static_folder="public", static_url_path="/")
# REMOVIDO: CORS(app)  ← evitamos abrir tudo por engano

# =====================================
# CORS fino: /api/* e /admin/*
# =====================================
ALLOWED_ORIGINS = [
    "https://mei-robo-prod.web.app",
    "https://www.meirobo.com.br",
    "https://meirobo-com-br-apex.web.app",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
]

_cors_common = {
    "origins": ALLOWED_ORIGINS,
    "supports_credentials": True,
    "allow_headers": [
        "Authorization",
        "Content-Type",
        "X-Requested-With",
        "cf-turnstile-response",  # ✅ header usado pelo Turnstile no cadastro
        "X-Turnstile-Token",      # ✅ alias que você também aceita em _is_human_ok()
        "X-Submit-Nonce",         # ✅ nonce de submissão usado no cadastro.html
    ],
    "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
}

CORS(app, resources={
    r"/api/*": _cors_common,
    r"/admin/*": _cors_common,
    "/gerar-cupom": _cors_common,
    "/captcha/verify": _cors_common,
})

# -------------------------------------------------
# CORS hardening específico para /api/cadastro
# -------------------------------------------------
@app.after_request
def _ensure_cadastro_cors(resp):
    try:
        path = (request.path or "").strip()
        # Só mexe em /api/cadastro (OPTIONS e POST)
        if path != "/api/cadastro":
            return resp

        origin = request.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            resp.headers["Access-Control-Allow-Origin"] = origin
            # Garante que o browser saiba que varia por Origin
            vary = resp.headers.get("Vary", "")
            if "Origin" not in vary:
                resp.headers["Vary"] = (vary + ", Origin").lstrip(", ").strip()

        # Junta o que já veio do flask-cors com o que a gente precisa
        existing = resp.headers.get("Access-Control-Allow-Headers", "")
        items = {h.strip() for h in existing.split(",") if h.strip()}
        items.update({
            "Authorization",
            "Content-Type",
            "X-Requested-With",
            "cf-turnstile-response",
            "X-Turnstile-Token",
            "X-Submit-Nonce",
        })
        resp.headers["Access-Control-Allow-Headers"] = ", ".join(sorted(items))

        # Garante métodos básicos na preflight (e na resposta também, não atrapalha)
        if not resp.headers.get("Access-Control-Allow-Methods"):
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"

    except Exception:
        # Nunca quebra a resposta se der algo errado aqui
        pass

    return resp

# =====================================
# Admin ping (usado pelo frontend para saber se é admin)
# =====================================

ADMIN_UID_ALLOWLIST = set(
    x.strip()
    for x in os.environ.get("ADMIN_UID_ALLOWLIST", "").split(",")
    if x.strip()
)

try:
    # Helper canônico do projeto para extrair UID do Bearer (Firebase ID token)
    from services.auth import get_uid_from_bearer  # type: ignore
except Exception:
    get_uid_from_bearer = None  # type: ignore


@app.route("/admin/ping", methods=["GET"])
def admin_ping():
    """
    Retorna 200 se o Bearer token for de um admin.
    401 se não tiver token / token inválido.
    403 se não estiver na allowlist de admin.
    """
    if get_uid_from_bearer is None:
        return jsonify({"ok": False, "error": "auth_helper_not_available"}), 500

    try:
        uid = get_uid_from_bearer(request)
    except Exception:
        return jsonify({"ok": False, "error": "invalid_token"}), 401

    if not uid:
        return jsonify({"ok": False, "error": "missing_uid"}), 401

    # Segurança: só é admin se estiver na allowlist
    if ADMIN_UID_ALLOWLIST and uid not in ADMIN_UID_ALLOWLIST:
        return jsonify({"ok": False, "error": "not_admin", "uid": uid}), 403

    return jsonify({"ok": True, "uid": uid, "role": "admin"}), 200

# Limite de upload (25 MB) — importante para áudio
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

# ================================
# Webhook GET challenge (Meta)
# ================================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "meirobo123")

# === Authority flags (mantém OFF por padrão para não impactar produção) ===
AUTHORITY_LINKAGE_ENABLED = os.getenv("AUTHORITY_LINKAGE_ENABLED", "0") in ("1","true","TRUE")
BLOCK_PAYMENT_UNTIL_AUTHORITY_APPROVED = os.getenv("BLOCK_PAYMENT_UNTIL_AUTHORITY_APPROVED","0") in ("1","true","TRUE")

@app.before_request
def _handle_webhook_challenge():
    if request.method == "GET" and request.path == "/webhook":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
            return Response(challenge, status=200, mimetype="text/plain; charset=utf-8")
        return Response("Forbidden", status=403)
    return None

# =========================================================
# (B) Helper global de publicação SSE (opcional, seguro como no-op)
# =========================================================
# Pode ser movido para services/pubsub.py se preferir.
import redis  # depende de REDIS_URL; se não houver, fica no-op
REDIS_URL = os.getenv("REDIS_URL", "").strip()
SSE_ENABLED = os.getenv("SSE_ENABLED", "0") == "1"

_pub_redis = None
def _get_pub_redis():
    global _pub_redis
    if _pub_redis is None and REDIS_URL:
        try:
            _pub_redis = redis.from_url(REDIS_URL, decode_responses=True)
        except Exception:
            _pub_redis = None
    return _pub_redis

def publish_email_verified(uid: str):
    """Publica no canal do usuário. Safe no-op se desativado."""
    if not (SSE_ENABLED and REDIS_URL and uid):
        return False
    r = _get_pub_redis()
    if not r:
        return False
    ch = f"user:{uid}:email_verified"
    payload = json.dumps({"verified": True})
    try:
        r.publish(ch, payload)
        return True
    except Exception:
        return False

# =========================================================
# BYPASS PÚBLICO ANTECIPADO (signup/CNPJ/health/captcha)
# =========================================================

# === Blueprint: authority (vinculação de CNPJ) — isolado e atrás de flag ===
try:
    from routes.authority_bp import authority_bp
    app.register_blueprint(authority_bp)
    print("[boot] authority_bp registrado ✓", flush=True)
except Exception as e:
    # Mantém produção viva mesmo se o arquivo ainda não existir
    print("[boot] authority_bp não registrado:", e, flush=True)

from flask import jsonify as _jsonify  # já importado acima, mas evita shadowing
_PUBLIC_ALLOW_EXACT = {
    "/health",
    "/captcha/verify",        # compat legado
    "/api/captcha/verify",    # novo endpoint opcional
    "/api/cadastro",          # cadastro deve ser público (protegido por captcha no handler)
}
_PUBLIC_ALLOW_PREFIX = (
    "/api/cnpj",       # cobre /api/cnpj/availability e /api/cnpj/<cnpj>
)

@app.before_request
def _public_allowlist_early_bypass():
    """
    Bypass antecipado: libera caminhos públicos ANTES de qualquer gate de Auth
    que possa ter sido registrado em blueprints. Não altera as demais rotas.
    """
    path = (request.path or "/").strip()
    if path in _PUBLIC_ALLOW_EXACT:
        return
    for pref in _PUBLIC_ALLOW_PREFIX:
        if path.startswith(pref):
            return
    # Outras rotas seguem o fluxo normal

# ------------------------------------------------------------------
# Hook global: injeta g.uid com base no Bearer para todas /api/**
# ------------------------------------------------------------------
@app.before_request
def _inject_uid_from_bearer():
    """
    Preenche g.uid com o UID extraído do Firebase ID token (Bearer),
    sem bloquear nada. Apenas ajuda rotas como /api/agenda/view que
    esperam g.uid já preenchido.
    """
    try:
        path = (request.path or "/").strip()
        # Só faz sentido em rotas de API; não mexe em estáticos/HTML
        if not path.startswith("/api/"):
            return

        uid = _uid_from_bearer()
        if uid:
            g.uid = uid
    except Exception:
        # Nunca quebra a request; no pior caso segue sem g.uid
        pass

# =====================================
# Error handlers padrão (úteis p/ voz)
# =====================================
@app.errorhandler(ValueError)
def _handle_value_error(e):
    msg = str(e) or "invalid_request"
    mapping = {
        "missing_audio": (400, "Áudio de voz é obrigatório."),
        "unsupported_media_type": (415, "Formato não suportado. Envie MP3 or WAV."),
        "empty_audio": (422, "Arquivo de áudio vazio."),
        "payload_too_large": (413, "Arquivo muito grande. Máx. 25 MB."),
    }
    status, human = mapping.get(msg, (400, msg))
    return jsonify({"ok": False, "error": msg, "message": human}), status

@app.errorhandler(OverflowError)
def _handle_overflow_error(e):
    return jsonify({"ok": False, "error": "payload_too_large", "message": "Arquivo muito grande. Máx. 25 MB."}), 413

# ================================
# Blueprints principais (sempre ON)
# ================================
def _register_bp(bp, name: str):
    try:
        app.register_blueprint(bp)
        print(f"[bp] Registrado: {name}")
    except Exception as e:
        print(f"[bp][erro] {name}: {e}")
        traceback.print_exc()

try:
    from routes.health import health_bp
    _register_bp(health_bp, "health_bp")
except Exception as e:
    print("[bp][warn] health_bp:", e)

try:
    from routes.agenda_api import agenda_api_bp
    _register_bp(agenda_api_bp, "agenda_api_bp")
except Exception as e:
    print("[bp][warn] agenda_api_bp:", e)

try:
    from routes.agenda_reminders import agenda_rem_bp
    _register_bp(agenda_rem_bp, "agenda_rem_bp")
except Exception as e:
    print("[bp][warn] agenda_rem_bp:", e)

try:
    from routes.agenda_digest import agenda_digest_bp
    _register_bp(agenda_digest_bp, "agenda_digest_bp")
except Exception as e:
    print("[bp][warn] agenda_digest_bp:", e)

try:
    from routes.media import media_bp
    _register_bp(media_bp, "media_bp")
except Exception as e:
    print("[bp][warn] media_bp:", e)

try:
    from routes.contacts import contacts_bp
    _register_bp(contacts_bp, "contacts_bp")
except Exception as e:
    print("[bp][warn] contacts_bp:", e)

try:
    from routes.configuracao import config_bp, ler_configuracao as _config_read
    _register_bp(config_bp, "config_bp (/api/configuracao GET)")
except Exception as e:
    print("[bp][warn] config_bp:", e)
    _config_read = None

try:
    from routes.orcamentos import orcamentos_bp
    _register_bp(orcamentos_bp, "orcamentos_bp (/api/orcamentos)")
except Exception as e:
    print("[bp][warn] orcamentos_bp:", e)

try:
    from routes.orcamentos_digest import orcamentos_digest_bp
    _register_bp(orcamentos_digest_bp, "orcamentos_digest_bp (/api/orcamentos/digest)")
except Exception as e:
    print("[bp][warn] orcamentos_digest_bp:", e)

try:
    from routes.stripe_webhook import stripe_webhook_bp
    _register_bp(stripe_webhook_bp, "stripe_webhook_bp")
except Exception as e:
    print("[bp][warn] stripe_webhook_bp:", e)

try:
    from routes.stripe_checkout import stripe_checkout_bp
    _register_bp(stripe_checkout_bp, "stripe_checkout_bp")
except Exception as e:
    print("[bp][warn] stripe_checkout_bp:", e)

try:
    from routes.conta_status import bp_conta
    _register_bp(bp_conta, "bp_conta")
except Exception as e:
    print("[bp][warn] bp_conta:", e)

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# NOVO: Auth blueprint (whoami + check-verification) sob /api
try:
    from routes.auth_bp import auth_bp
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    print("[bp] Registrado: auth_bp (/api/auth/*)")
except Exception as e:
    print("[bp][warn] auth_bp:", e)

# 🔸 NOVO (1/2): import do blueprint de e-mail bonito
try:
    from routes.auth_email_bp import auth_email_bp
    app.register_blueprint(auth_email_bp, url_prefix="/api/auth")
    print("[bp] Registrado: auth_email_bp (/api/auth/send-verification-email)")
except Exception as e:
    print("[bp][warn] auth_email_bp:", e)
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

# 🔸 NOVO (2/2): geração de link via Admin SDK com o MESMO prefixo
_gen_link_bp_ok = False
try:
    from routes.verify_email_link_bp import verify_email_link_bp
    app.register_blueprint(verify_email_link_bp, url_prefix="/api/auth")
    print("[bp] Registrado: verify_email_link_bp (/api/auth/generate-verification-link)")
    _gen_link_bp_ok = True
except Exception as e:
    print("[bp][warn] verify_email_link_bp:", e)

# --- (A) Registrar blueprint SSE ---
try:
    from routes.sse_bp import sse_bp  # ADICIONADO
    _register_bp(sse_bp, "sse_bp")    # ADICIONADO
except Exception as e:
    print("[bp][warn] sse_bp:", e)
# --- FIM (A) ---

# --- SHIM: gerar link de verificação (Admin SDK) ---
# Só cria o SHIM se o blueprint NÃO entrou
if not _gen_link_bp_ok:
    from flask import request as _req

    @app.route("/api/auth/generate-verification-link", methods=["GET", "POST", "OPTIONS"])
    def _auth_generate_verification_link():
        if _req.method == "OPTIONS":
            return ("", 204)
        try:
            if ensure_firebase_admin is None or fb_auth is None:
                return jsonify({"ok": False, "error": "admin_sdk_unavailable"}), 500

            data = _req.get_json(silent=True) or {}
            email = (_req.args.get("email") or data.get("email") or "").strip().lower()
            continue_url = (
                _req.args.get("continueUrl")
                or data.get("continueUrl")
                or (os.getenv("FRONTEND_BASE", "https://www.meirobo.com.br").rstrip("/") + "/verify-email.html")
            ).strip()

            if not email:
                return jsonify({"ok": False, "error": "missing_email"}), 400

            ensure_firebase_admin()
            acs = fb_auth.ActionCodeSettings(url=continue_url, handle_code_in_app=False)
            link = fb_auth.generate_email_verification_link(email, acs)
            return jsonify({"ok": True, "verification_link": link, "continueUrl": continue_url}), 200

        except Exception as e:
            app.logger.exception("generate_verification_link: erro")
            return jsonify({"ok": False, "error": "link_generate_failed", "detail": str(e)}), 500
# --- FIM SHIM ---

# =========================================================
# (C) Hook pós-resposta para publicar evento quando check-verification confirmar
# =========================================================
@app.after_request
def _maybe_publish_email_verified(resp):
    try:
        if request.path == "/api/auth/check-verification" and resp.status_code == 200:
            # Tenta ler JSON e detectar "verified": true
            ct = (resp.headers.get("Content-Type") or "").lower()
            if "application/json" in ct:
                import json as _json
                data = _json.loads(resp.get_data(as_text=True) or "{}")
                verified = bool(data.get("verified")) or bool(data.get("isVerified")) or (data.get("ok") and data.get("status") == "verified")
                if verified:
                    # extrai uid do bearer e publica
                    uid = _uid_from_bearer() if 'Authorization' in request.headers else None
                    if uid:
                        try:
                            publish_email_verified(uid)
                        except Exception:
                            pass
    except Exception:
        pass
    return resp

# ================================
# Blueprints opcionais (flags)
# ================================
# CNPJ pública
if os.getenv("CNPJ_BP_ENABLED", "false").lower() in ("1","true","yes"):
    try:
        from routes.cnpj_publica import cnpj_bp
        _register_bp(cnpj_bp, "cnpj_bp (/api/cnpj/<cnpj>)")
    except Exception as e:
        print("[bp][warn] cnpj_bp:", e)

# Voz V2 — usa o blueprint unificado routes/voz_v2.py
if os.getenv("VOZ_V2_ENABLED", "false").lower() in ("1","true","yes"):
    try:
        from routes.voz_v2 import voz_upload_bp  # <- nome correto do blueprint
        _register_bp(voz_upload_bp, "voz_upload_v2 (/api/voz/*)")
    except Exception as e:
        print("[bp][warn] voz_upload_v2:", e)

# Voz TTS (ElevenLabs) — independente da VOZ_V2 (apenas TTS)
try:
    from routes.voz_tts import voz_tts_bp
    app.register_blueprint(voz_tts_bp, url_prefix="/api/voz")  # expõe /api/voz/tts
    print("[bp] Registrado: voz_tts_bp (/api/voz/tts)")
except Exception as e:
    print("[bp][warn] voz_tts_bp:", e)

# Voz PROCESS (/api/voz/process) — marca status ready + voiceId
try:
    from routes.voz_process_bp import voz_process_bp
    _register_bp(voz_process_bp, "voz_process_bp (/api/voz/process)")
except Exception as e:
    print("[bp][warn] voz_process_bp:", e)

# (Opcional) Voz STT — se existir arquivo routes/voz_stt_bp.py
try:
    from routes.voz_stt_bp import voz_stt_bp
    _register_bp(voz_stt_bp, "voz_stt_bp (/api/voz/stt)")
except Exception as e:
    print("[bp][warn] voz_stt_bp:", e)

# =====================================
# Health simples adicional e versão
# =====================================
APP_TAG = os.getenv("APP_TAG", "2025-10-14-F1")

@app.route("/health", methods=["GET"])
def health_simple():
    return jsonify(ok=True, service="mei-robo-prod", app_tag=APP_TAG), 200

@app.route("/__version", methods=["GET"])
def __version():
    return jsonify({"ok": True, "boot": APP_TAG}), 200

# Pequeno diagnóstico das flags de voz
@app.get("/__voice_flags")
def __voice_flags():
    return jsonify({
        "VOZ_V2_ENABLED": os.getenv("VOZ_V2_ENABLED"),
        "ELEVEN_API_KEY": bool(os.getenv("ELEVEN_API_KEY")),
        "ELEVEN_VOICE_ID": os.getenv("ELEVEN_VOICE_ID") is not None,
    }), 200

# =====================================
# Env seguro (sem segredos em claro)
# =====================================
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
        "APP_TAG": APP_TAG,
        "FRONTEND_BASE": os.getenv("FRONTEND_BASE"),
        "WHATSAPP_TOKEN": _mask_secret(os.getenv("WHATSAPP_TOKEN", "")),
        "OPENAI_API_KEY": _mask_secret(os.getenv("OPENAI_API_KEY", "")),
        "FIREBASE_PROJECT_ID": os.getenv("FIREBASE_PROJECT_ID"),
        "STORAGE_BUCKET": os.getenv("STORAGE_BUCKET"),
        "SIGNED_URL_EXPIRES_SECONDS": os.getenv("SIGNED_URL_EXPIRES_SECONDS"),
    }
    return jsonify({"ok": True, "env": safe}), 200

# =====================================
# WA bot status + lazy import
# =====================================
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
        print(f"[init][erro] services.wa_bot: {e}", flush=True)
        return None

@app.get("/__wa_bot_status")
def wa_bot_status():
    mod = _load_wa_bot()
    return jsonify({
        "ok": True,
        "service": "mei-robo-prod",
        "app_tag": APP_TAG,
        "loaded": bool(mod and hasattr(mod, "process_change")),
        "has_process_change": bool(getattr(mod, "process_change", None)) if mod else False,
        "last_error": _WA_BOT_LAST_ERR,
        "module": getattr(mod, "__file__", None) if mod else None,
    }), 200

# =====================================
# Helpers telefone + send-text
# =====================================
def _only_digits(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())

def _normalize_br_msisdn(wa_id: str) -> str:
    if not wa_id:
        return ""
    digits = _only_digits(wa_id)
    if digits.startswith("55") and len(digits) == 12:
        digits = digits[:4] + "9" + digits[4:]
    return digits

def br_candidates(msisdn: str) -> List[str]:
    d = _only_digits(msisdn)
    if d.startswith("55") and len(d) == 12:
        return [d[:4] + "9" + d[4:], d]
    return [d]

def br_equivalence_key(msisdn: str) -> str:
    d = _only_digits(msisdn)
    if d.startswith("55"):
        cc = d[:2]
        ddd = d[2:4] if len(d) >= 4 else ""
        local8 = d[-8:]
        return f"{cc}{ddd}{local8}"
    return d[-8:]

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

    cands = br_candidates(to) or [_normalize_br_msisdn(to)]
    seen = set(); cands = [c for c in cands if not (c in seen or seen.add(c))]
    eq_key = br_equivalence_key(to)

    last_resp = None
    for cand in cands:
        ok, resp = wa_send_text(cand, body)
        if ok:
            return {"ok": True, "used": cand, "eq_key": eq_key, "resp": resp}, 200
        last_resp = resp
    return {"ok": False, "eq_key": eq_key, "tried": cands, "resp": last_resp}, 500

# =====================================
# Cupons — rotas absolutas (mantidas)
# =====================================
import base64 as _b64
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

def _sign_value(raw: str, key: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

def _human_cookie_ok() -> bool:
    raw = request.cookies.get("human_ok", "")
    if not raw: return False
    parts = raw.split(".")
    if len(parts) == 3:
        val, ts_str, sig = parts
        key = os.getenv("HUMAN_COOKIE_SIGNING_KEY", "").strip()
        if not key: return False
        base = f"{val}.{ts_str}"
        expect = _sign_value(base, key)
        if sig != expect: return False
        try: ts = int(ts_str)
        except Exception: return False
        if (time.time() - ts) > 5 * 60: return False
        return val == "1"
    return raw == "1"

# ✅ Helper legado (bool) — mantido para outros endpoints
def _verify_turnstile_token(token: str) -> bool:
    secret = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
    if not secret or not token:
        return False
    data = ulparse.urlencode({
        "secret": secret,
        "response": token,
        "remoteip": request.headers.get("CF-Connecting-IP") or request.remote_addr or ""
    }).encode("utf-8")
    req = ulreq.Request(
        TURNSTILE_VERIFY_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with ulreq.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            j = json.loads(body)
            ok = bool(j.get("success"))
            if not ok:
                reason = ",".join(j.get("error-codes", [])) or "unknown"
                print(f"[turnstile] verify: success=false reason={reason}")
            return ok
    except Exception as e:
        print(f"[turnstile] verify: exception={type(e).__name__} msg={e}")
        return False

def _is_human_ok() -> bool:
    if _human_cookie_ok(): return True
    tok = (
        request.headers.get("cf-turnstile-response")
        or (request.get_json(silent=True) or {}).get("cf_token")
        or (request.get_json(silent=True) or {}).get("cf_resp")
        or (request.get_json(silent=True) or {}).get("token")
        or request.headers.get("x-turnstile-token")
    )
    return _verify_turnstile_token(tok) if tok else False

# ✅ Helper canônico para /api/cadastro (retorna ok, errs, raw)
def verify_turnstile(token: str, client_ip: str) -> Tuple[bool, list, dict]:
    secret = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
    if not secret or not token:
        return False, ["missing_secret_or_token"], {}
    data = ulparse.urlencode({
        "secret": secret,
        "response": token,
        "remoteip": client_ip or ""
    }).encode("utf-8")
    req = ulreq.Request(
        TURNSTILE_VERIFY_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with ulreq.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            j = json.loads(body)
            ok = bool(j.get("success"))
            errs = j.get("error-codes", []) or []
            return ok, errs, j
    except Exception as e:
        return False, [f"exception:{type(e).__name__}"], {"error": str(e)}

from services.coupons import find_cupom_by_codigo, validar_consumir_cupom
from services.db import db

# =====================================
# Admin — geração de cupons
# =====================================
def _ensure_admin_uid():
    """
    Retorna o UID do token Bearer se estiver presente
    e dentro do ADMIN_UID_ALLOWLIST. Caso contrário, None.
    """
    try:
        uid = _uid_from_bearer()
    except Exception:
        uid = None
    if not uid:
        return None
    if uid not in ADMIN_UID_ALLOWLIST:
        return None
    return uid


def _generate_coupon_code(prefix: str = "", length: int = 6) -> str:
    """
    Gera um código de cupom "humano" (sem 0/O/1/I) com prefixo opcional.
    Ex.: MEI-AB29FQ
    """
    import secrets
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    core = "".join(secrets.choice(alphabet) for _ in range(length))
    prefix = (prefix or "").strip().upper()
    if prefix:
        return f"{prefix}-{core}"
    return core


def _create_admin_coupon(body: dict) -> dict:
    """
    Cria um cupom de ativação na coleção cuponsAtivacao.
    Retorna o dict salvo (já com código e datas).
    """
    from datetime import datetime, timedelta, timezone

    dias_raw = body.get("diasValidade") or body.get("dias") or 0
    try:
        dias = int(dias_raw)
    except Exception:
        dias = 0

    prefixo = (body.get("prefixo") or "").strip().upper()
    origem  = (body.get("origem") or "admin-cupons").strip()

    now = datetime.now(timezone.utc)
    col = db.collection("cuponsAtivacao")

    # Gera código único (tenta algumas vezes)
    codigo = None
    for _ in range(8):
        cand = _generate_coupon_code(prefixo or "MEI", length=6)
        if not col.document(cand).get().exists:
            codigo = cand
            break
    if not codigo:
        raise ValueError("nao_foi_possivel_gerar_codigo_unico")

    doc = {
        "codigo": codigo,
        "tipo": "ativacao",
        "escopo": "plano",
        "plano": "start",
        "status": "novo",
        "ativo": True,
        "usos": 0,
        "usosMax": 1,
        "origem": origem,
        "createdAt": now.isoformat(),
    }

    if dias > 0:
        doc["expiraEm"] = (now + timedelta(days=dias)).isoformat()

    col.document(codigo).set(doc, merge=True)
    return doc


@app.route("/admin/cupons", methods=["POST", "OPTIONS"])
def admin_cupons_create():
    """
    Endpoint oficial usado por /pages/admin-cupons.html para gerar cupons.
    - Requer Bearer válido e UID presente em ADMIN_UID_ALLOWLIST.
    - Cria documento em cuponsAtivacao.
    """
    if request.method == "OPTIONS":
        return ("", 204)

    if not ADMIN_UID_ALLOWLIST:
        return jsonify({"ok": False, "error": "admin_allowlist_empty"}), 403

    uid = _ensure_admin_uid()
    if not uid:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    body = request.get_json(silent=True) or {}
    try:
        cupom = _create_admin_coupon(body)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    except Exception as e:
        app.logger.exception("admin_cupons_create: erro")
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500

    public = {
        "codigo": cupom.get("codigo"),
        "status": cupom.get("status"),
        "expiraEm": cupom.get("expiraEm"),
        "usos": cupom.get("usos", 0),
        "usosMax": cupom.get("usosMax", 1),
        "tipo": cupom.get("tipo"),
        "escopo": cupom.get("escopo"),
        "plano": cupom.get("plano"),
        "origem": cupom.get("origem"),
        "createdAt": cupom.get("createdAt"),
    }
    return jsonify({"ok": True, "codigo": public["codigo"], "cupom": public}), 200


@app.route("/gerar-cupom", methods=["POST", "OPTIONS"])
def gerar_cupom_legacy():
    """
    Alias legado para compatibilidade com versões antigas do painel.
    Apenas delega para /admin/cupons, mantendo mesma regra de admin.
    """
    if request.method == "OPTIONS":
        return ("", 204)
    return admin_cupons_create()


@app.route("/api/admin/cupons", methods=["GET", "OPTIONS"])
def admin_cupons_list():
    """
    Lista cupons de ativação (uso interno do painel admin).
    - Requer Bearer válido com UID na ADMIN_UID_ALLOWLIST.
    - Retorna items[] já normalizados.
    """
    if request.method == "OPTIONS":
        return ("", 204)

    if not ADMIN_UID_ALLOWLIST:
        return jsonify({"ok": False, "error": "admin_allowlist_empty"}), 403

    uid = _ensure_admin_uid()
    if not uid:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    try:
        try:
            limit = int(request.args.get("limit", "50") or "50")
        except Exception:
            limit = 50

        col = db.collection("cuponsAtivacao")
        query = col.limit(limit)
        docs = query.stream()

        items = []
        for doc in docs:
            d = doc.to_dict() or {}
            codigo = d.get("codigo") or doc.id
            items.append({
                "codigo": codigo,
                "status": d.get("status"),
                "expiraEm": d.get("expiraEm"),
                "usos": d.get("usos", 0),
                "usosMax": d.get("usosMax", 1),
                "tipo": d.get("tipo"),
                "escopo": d.get("escopo"),
                "plano": d.get("plano"),
                "origem": d.get("origem"),
                "createdAt": d.get("createdAt"),
            })

        return jsonify({"ok": True, "items": items}), 200
    except Exception as e:
        app.logger.exception("admin_cupons_list: erro")
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500


def _parse_iso_maybe_z(s: str):
    if not s: return None
    try:
        if isinstance(s, str) and s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

@app.route("/api/cupons/validar-publico", methods=["OPTIONS"])
def _preflight_api_cupons_validar_publico(): return ("", 204)

@app.route("/api/cupons/validar-publico", methods=["POST"])
def api_cupons_validar_publico():
    try:
        data = request.get_json(silent=True) or {}
        codigo = (data.get("codigo") or "").strip()
        if not codigo: return jsonify({"ok": False, "reason": "codigo_obrigatorio"}), 400
        cupom = find_cupom_by_codigo(codigo)
        if not cupom: return jsonify({"ok": False, "reason": "nao_encontrado"}), 400

        status = (cupom.get("status") or "").lower()
        if status in {"used","revogado","invalido"}: return jsonify({"ok": False, "reason": "status"}), 400
        if cupom.get("ativo") is False: return jsonify({"ok": False, "reason": "inativo"}), 400

        usos = int(cupom.get("usos") or 0)
        usos_max = int(cupom.get("usosMax") or 1)
        if (usos_max > 0) and (usos >= usos_max): return jsonify({"ok": False, "reason": "sem_usos_restantes"}), 400

        exp = cupom.get("expiraEm")
        if exp:
            dt = _parse_iso_maybe_z(exp if isinstance(exp, str) else str(exp))
            now_utc = datetime.now(timezone.utc)
            if dt and dt < now_utc: return jsonify({"ok": False, "reason": "expirado"}), 400

        public = {k: cupom.get(k) for k in ("codigo","tipo","escopo","expiraEm")}
        public.update({"usos": usos, "usosMax": usos_max})
        return jsonify({"ok": True, "cupom": public}), 200
    except Exception as e:
        return jsonify({"ok": False, "reason": "erro_interno", "detail": str(e)}), 500

@app.route("/api/cupons/ativar", methods=["OPTIONS"])
def _preflight_api_cupons_ativar(): return ("", 204)

@app.route("/api/cupons/ativar", methods=["POST"])
def api_cupons_ativar():
    try:
        data = request.get_json(silent=True) or {}
        codigo = (data.get("codigo") or "").strip()
        if not codigo: return jsonify({"erro": "Código do cupom é obrigatório"}), 400
        uid = _uid_from_bearer() or (data.get("uid") or "").strip()  # ← TROCA aplicada
        if not uid: return jsonify({"erro": "Não autenticado"}), 401

        cupom = find_cupom_by_codigo(codigo)
        ctx = {
            "ip": request.headers.get("CF-Connecting-IP")
                  or (request.headers.get("X-Forwarded-For","").split(",")[0].strip() if request.headers.get("X-Forwarded-For") else "")
                  or request.remote_addr or "",
            "ua": request.headers.get("User-Agent") or "",
        }
        ok, msg, plano = validar_consumir_cupom(cupom, uid, ctx=ctx)
        if not ok: return jsonify({"erro": msg}), 400

        now_iso = datetime.now(timezone.utc).isoformat()
        db.collection("profissionais").document(uid).set({
            "plan": (plano or "start"),
            "plano": (plano or "start"),
            "licenca": {"origem": "cupom", "codigo": codigo, "activatedAt": now_iso},
            "updatedAt": now_iso,
        }, merge=True)
        return jsonify({"mensagem": "Plano ativado com sucesso pelo cupom!", "plano": (plano or "start")}), 200
    except Exception as e:
        return jsonify({"erro": f"ativar_cupom[app]: {str(e)}"}), 500

@app.route("/api/cupons/ativar-cupom", methods=["OPTIONS"])
def _preflight_api_cupons_ativar_legado(): return ("", 204)

@app.route("/api/cupons/ativar-cupom", methods=["POST"])
def api_cupons_ativar_legado():
    try:
        if not _is_human_ok(): return jsonify({"erro": "captcha_required"}), 403
        data = request.get_json(silent=True) or {}
        codigo = (data.get("codigo") or "").strip()
        uid = (data.get("uid") or "").strip()
        if not codigo or not uid: return jsonify({"erro": "Código do cupom é obrigatório e UID também"}), 400

        cupom = find_cupom_by_codigo(codigo)
        ctx = {
            "ip": request.headers.get("CF-Connecting-IP")
                  or (request.headers.get("X-Forwarded-For","").split(",")[0].strip() if request.headers.get("X-Forwarded-For") else "")
                  or request.remote_addr or "",
            "ua": request.headers.get("User-Agent") or "",
        }
        ok, msg, plano = validar_consumir_cupom(cupom, uid, ctx=ctx)
        if not ok: return jsonify({"erro": msg}), 400

        now_iso = datetime.now(timezone.utc).isoformat()
        db.collection("profissionais").document(uid).set({
            "plan": (plano or "start"),
            "plano": (plano or "start"),
            "licenca": {"origem": "cupom", "codigo": codigo, "activatedAt": now_iso},
            "updatedAt": now_iso,
        }, merge=True)
        return jsonify({"mensagem": "Plano ativado com sucesso pelo cupom!", "plano": (plano or "start")}), 200
    except Exception as e:
        return jsonify({"erro": f"ativar_cupom_legado[app]: {str(e)}"), 500

# =====================================
# Cadastro / ativar-cliente + CNPJ availability (ajustado)
# =====================================
# REMOVIDO: from services.mailer import send_verification_email  ← caminho B desligado
try:
    from services.firebase_admin_init import ensure_firebase_admin
    from firebase_admin import auth as fb_auth
except Exception:
    ensure_firebase_admin = None
    fb_auth = None

def _only_digits_public(s): return "".join(ch for ch in str(s or "") if s is not None and ch.isdigit())

@app.route("/api/cnpj/availability", methods=["GET", "OPTIONS"])
def api_cnpj_availability():
    if request.method == "OPTIONS": return ("", 204)
    cnpj_raw = (request.args.get("cnpj") or "").strip()
    cnpj = _only_digits_public(cnpj_raw)
    if not cnpj: return jsonify({"ok": False, "error": "missing_cnpj"}), 400
    if len(cnpj) != 14: return jsonify({"ok": False, "error": "invalid_cnpj_length", "cnpj": cnpj}), 400
    return jsonify({"ok": True, "cnpj": cnpj, "available": True, "source": "stub"}), 200

def _ensure_profissional_doc(uid: str, nome: str, email: str, cnpj: str):
    now_iso = datetime.now(timezone.utc).isoformat()
    db.collection("profissionais").document(uid).set({
        "nome": nome, "email": email, "cnpj": cnpj,
        "onboarding": {"status": "created", "createdAt": now_iso},
        "updatedAt": now_iso,
    }, merge=True)
    return True

def _uid_from_bearer() -> str | None:
    auth = request.headers.get("Authorization", "").strip()
    if not auth.lower().startswith("bearer "): return None
    tok = auth.split(" ", 1)[1].strip()
    parts = tok.split(".")
    if len(parts) < 2: return None
    try:
        pad = "=" * ((4 - len(parts[1]) % 4) % 4)
        payload = json.loads(_b64.urlsafe_b64decode((parts[1] + pad).encode()).decode())
        return payload.get("user_id") or payload.get("uid") or payload.get("sub")
    except Exception:
        return None

def _validate_signup_payload(data: dict):
    email = (data.get("email") or "").strip().lower()
    senha = (data.get("senha") or "").strip()
    nome = (data.get("nome") or "").strip()
    telefone = _only_digits_public(data.get("telefone") or "")
    cnpj = _only_digits_public(data.get("cnpj") or "")
    segmento = (data.get("segmento") or "").strip().lower()

    # >>> Removida a verificação de captcha daqui para evitar dupla checagem no /api/cadastro
    # if not _is_human_ok():
    #     return None, (429, {"ok": False, "error": "captcha_required"})

    if not email:   return None, (422, {"ok": False, "error": "invalid_field", "field": "email"})
    if "@" not in email or "." not in email.split("@")[-1]:
        return None, (422, {"ok": False, "error": "invalid_field", "field": "email"})

    if not senha or len(senha) < 8:
        return None, (422, {"ok": False, "error": "weak_password"})

    if not nome:    return None, (422, {"ok": False, "error": "invalid_field", "field": "nome"})
    if not telefone:return None, (422, {"ok": False, "error": "invalid_field", "field": "telefone"})
    if not cnpj or len(cnpj) != 14:
        return None, (422, {"ok": False, "error": "invalid_field", "field": "cnpj"})

    if segmento and segmento not in {"barbearia","beleza","manicure","estetica","padaria","restaurante","servicos","tecnologia"}:
        return None, (422, {"ok": False, "error": "invalid_field", "field": "segmento"})

    return {
        "email": email, "senha": senha, "nome": nome,
        "telefone": telefone, "cnpj": cnpj, "segmento": segmento or "servicos"
    }, None

@app.route("/api/ativar-cliente", methods=["POST", "OPTIONS"])
def api_ativar_cliente():
    if request.method == "OPTIONS": return ("", 204)
    uid = _uid_from_bearer()
    if not uid: return jsonify({"ok": False, "error": "unauthenticated"}), 401
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()
    email = (data.get("email") or "").strip()
    cnpj = _only_digits_public(data.get("cnpj") or "")
    if not nome or not email or not cnpj:
        return jsonify({"ok": False, "error": "missing_fields", "need": ["nome","email","cnpj"]}), 400
    if len(cnpj) != 14:
        return jsonify({"ok": False, "error": "invalid_cnpj_length", "cnpj": cnpj}), 400
    _ensure_profissional_doc(uid, nome, email, cnpj)
    return jsonify({"ok": True, "uid": uid, "created": True}), 201

@app.route("/api/cadastro", methods=["POST", "OPTIONS"])
def api_cadastro():
    """
    Signup público e robusto:
    - captcha obrigatório (Turnstile),
    - valida payload,
    - se houver Bearer: usa uid do token (idempotente),
    - se não houver Bearer: cria usuário no Firebase Auth (se disponível),
      cria doc do profissional.
    - 🚫 (Mudança) NÃO envia e-mail pelo mailer legado aqui. O envio deve ser feito
      via rota bonita /api/auth/send-verification-email pelo frontend (ou internamente
      por função equivalente), evitando caminho B.
    """
    if request.method == "OPTIONS":
        return ("", 204)

    body = request.get_json(silent=True) or {}

    # --- início: log de tentativa (nonce + UA) ---
    req_id = request.headers.get('X-Submit-Nonce') or str(uuid4())[:8]
    ua = request.headers.get('User-Agent','')[:80]
    print(f"[cadastro] ENTER req={req_id} ua={ua}")

    # Leitura do token em um único ponto
    token = (body.get("turnstile_token") or
             body.get("cf-turnstile-response") or
             body.get("cf_token") or
             request.headers.get("cf-turnstile-response") or
             request.headers.get("X-Turnstile-Token") or "").strip()

    # Verificação única do Turnstile
    client_ip = request.headers.get("CF-Connecting-IP") or request.remote_addr or ""
    print(f"[cadastro] VERIFY#1 req={req_id}")
    ok, errs, raw = verify_turnstile(token, client_ip)
    print(f"[cadastro] VERIFIED req={req_id} ok={ok} errs={errs}")

    if os.getenv("TURNSTILE_REQUIRED", "true").strip().lower() in ("1","true","yes","on"):
        if not ok:
            return jsonify({"ok": False, "error": "captcha_required", "detail": errs}), 429

    # Validações + demais campos (sem nova verificação de captcha)
    payload, err = _validate_signup_payload(body)
    if err:
        status, body_resp = err
        return jsonify(body_resp), status

    email = payload["email"]; senha = payload["senha"]; nome = payload["nome"]
    telefone = payload["telefone"]; cnpj = payload["cnpj"]; segmento = payload["segmento"]

    uid = _uid_from_bearer()

    try:
        if uid:
            # Caminho idempotente autenticado (front já criou user via SDK)
            _ensure_profissional_doc(uid, nome, email, cnpj)
            # 🚫 Não enviar por mailer legado (evitar caminho B)
            app.logger.info("[cadastro] skip legacy mailer; send_via=frontend_sendgrid_pretty; uid=%s", uid)
            return jsonify({"ok": True, "created": True, "uid": uid, "mode": "auth", "next": "frontend_should_call_send_verification_email"}), 201

        # Caminho público (sem token): criar usuário se Admin SDK disponível
        if ensure_firebase_admin and fb_auth:
            try:
                ensure_firebase_admin()
                user = fb_auth.create_user(email=email, password=senha)
                uid = user.uid
            except Exception as e:
                # Trata e-mails já existentes como idempotência
                msg = str(e).lower()
                if "already exists" in msg or "already-exists" in msg:
                    # Tentamos descobrir UID pelo e-mail (quando possível)
                    try:
                        user = fb_auth.get_user_by_email(email)
                        uid = user.uid
                    except Exception:
                        uid = None
                    if not uid:
                        return jsonify({"ok": False, "error": "email_already_exists"}), 409
                else:
                    return jsonify({"ok": False, "error": "auth_create_failed", "detail": str(e)}), 400

        if not uid:
            # Se não conseguimos criar/descobrir UID (p.ex. sem Admin SDK),
            # devolve 202 para o front completar via SDK e refazer chamada autenticada
            return jsonify({"ok": True, "created": False, "mode": "client_sdk_required", "next": "frontend_should_signin_and_call_send_verification_email"}), 202

        # Criar doc do profissional (sem enviar verificação aqui)
        _ensure_profissional_doc(uid, nome, email, cnpj)
        app.logger.info("[cadastro] created profissional; skip legacy mailer; send_via=frontend_sendgrid_pretty; uid=%s", uid)

        return jsonify({"ok": True, "created": True, "uid": uid, "mode": "public", "next": "frontend_should_call_send_verification_email"}), 201

    except Exception as e:
        app.logger.exception("cadastro: erro inesperado")
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500

# -------------------------------------
# (Opcional) Captcha diagnostics
# -------------------------------------
from flask import Blueprint
captcha_bp = Blueprint("captcha_bp", __name__, url_prefix="/api/captcha")

@captcha_bp.route("/verify", methods=["POST"])
def captcha_verify():
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or body.get("cf_resp") or request.form.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "missing token"}), 400
    return jsonify({"ok": _verify_turnstile_token(token)}), 200

# Registrar blueprint opcional
try:
    app.register_blueprint(captcha_bp)
    print("[bp] Registrado: captcha_bp (/api/captcha/verify)")
except Exception as e:
    print("[bp][warn] captcha_bp:", e)

# Shim legado: /captcha/verify (sem /api) usado pelo captcha_gate.js antigo
@app.route("/captcha/verify", methods=["POST", "OPTIONS"])
def captcha_verify_legacy():
    if request.method == "OPTIONS":
        return ("", 204)
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or body.get("cf_resp") or request.form.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "missing token"}), 400
    return jsonify({"ok": _verify_turnstile_token(token)}), 200

# -------------------------------------
# Diagnóstico: lista de rotas ativas
# -------------------------------------
@app.get("/__routes")
def __routes():
    out = []
    for rule in app.url_map.iter_rules():
        methods = sorted([m for m in rule.methods if m not in {"HEAD", "OPTIONS"}])
        out.append({
            "rule": str(rule),
            "endpoint": rule.endpoint,
            "methods": methods,
        })
        # fim for
    out.sort(key=lambda x: x["rule"])
    return jsonify({"count": len(out), "routes": out}), 200

# -------------------------------------
# Diagnóstico de blueprints/voz
# -------------------------------------
import importlib.util

@app.get("/__bp_debug")
def __bp_debug():
    info = {
        "VOZ_V2_ENABLED": os.getenv("VOZ_V2_ENABLED"),
        "blueprints": sorted(list(app.blueprints.keys())),
        "voz_v2": {
            "spec_found": False,
            "import_ok": False,
            "has_vox_bp_attr": False,
            "attr_name": "voz_upload_bp",
            "import_error": None,
            "module_file": None,
        },
        "routes_count": len(list(app.url_map.iter_rules())),
        "routes_sample": sorted([str(r) for r in app.url_map.iter_rules() if "/api/voz" in str(r)]),
    }

    try:
        spec = importlib.util.find_spec("routes.voz_v2")
        info["voz_v2"]["spec_found"] = bool(spec)
        if spec and spec.origin:
            info["voz_v2"]["module_file"] = spec.origin
        mod = importlib.import_module("routes.voz_v2")
        info["voz_v2"]["import_ok"] = True
        info["voz_v2"]["has_vox_bp_attr"] = hasattr(mod, "voz_upload_bp")
    except Exception as e:
        info["voz_v2"]["import_error"] = f"{type(e).__name__}: {e}"

    return jsonify(info), 200

# --- ADC quick check ---
@app.get("/__adc_debug")
def __adc_debug():
    import os, json
    p = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    info = {"GOOGLE_APPLICATION_CREDENTIALS": p, "exists": False, "size": None}
    try:
        if p and os.path.isfile(p):
            import os as _os
            info["exists"] = True
            info["size"] = _os.path.getsize(p)
        if info["exists"]:
            with open(p, "r", encoding="utf-8") as f:
                j = json.load(f)
            info["json_ok"] = isinstance(j, dict) and j.get("type") == "service_account"
            info["project_id"] = j.get("project_id")
    except Exception as e:
        info["error"] = str(e)
    return info, 200

# =====================================
# EOF
# =====================================
