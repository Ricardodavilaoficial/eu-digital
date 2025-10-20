# app.py — MEI Robô (produção) — fachada enxuta com flags
# Mantém: CORS/health/env/version/wa_debug/send-text, Stripe webhooks/checkout,
# blueprints principais, cupons (rotas absolutas), webhook GET challenge (Meta).
# Modulações: CNPJ e Voz V2 atrás de flags; imports protegidos por try/except.

import os, io, struct, json, logging, traceback, re, hashlib, importlib, types, time
from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from urllib import request as ulreq, parse as ulparse
from flask import Flask, jsonify, request, Response
from flask_cors import CORS

print("[boot] app.py fachada enxuta carregado ✓", flush=True)
logging.basicConfig(level=logging.INFO)

# =====================================
# App + CORS (whitelist apenas /api/*)
# =====================================
app = Flask(__name__, static_folder="public", static_url_path="/")
CORS(app)  

# ou CORS(app, resources={r"/api/*": {"origins": "*"}})

# Limite de upload (25 MB) — importante para áudio
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

_allowed = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
cors_resources = {
    r"/api/*": {
        "origins": _allowed or [],
        "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["Authorization","Content-Type","X-Requested-With","cf-turnstile-response","x-turnstile-token"],
        "supports_credentials": False,
    }
} if _allowed else {}
CORS(app, resources=cors_resources, always_send=False)

@app.after_request
def _strip_cors_when_no_origin(resp):
    try:
        if request.path.startswith("/api/") and "Origin" not in request.headers:
            for h in ("Access-Control-Allow-Origin","Access-Control-Allow-Credentials","Vary"):
                resp.headers.pop(h, None)
    except Exception:
        pass
    return resp

# ================================
# Webhook GET challenge (Meta)
# ================================
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "meirobo123")

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
# BYPASS PÚBLICO ANTECIPADO (signup/CNPJ/health/captcha)
# =========================================================
from flask import jsonify as _jsonify  # já importado acima, mas evita shadowing
_PUBLIC_ALLOW_EXACT = {
    "/health",
    "/captcha/verify",
    "/api/cadastro",   # cadastro deve ser público (protegido por captcha no handler)
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

# =====================================
# Error handlers padrão (úteis p/ voz)
# =====================================
@app.errorhandler(ValueError)
def _handle_value_error(e):
    msg = str(e) or "invalid_request"
    mapping = {
        "missing_audio": (400, "Áudio de voz é obrigatório."),
        "unsupported_media_type": (415, "Formato não suportado. Envie MP3 ou WAV."),
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
    app.register_blueprint(auth_bp, url_prefix="/api")
    print("[bp] Registrado: auth_bp (/api/auth/*)")
except Exception as e:
    print("[bp][warn] auth_bp:", e)
# <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

# Verificação de Autoridade (gate)
try:
    from middleware.authority_gate import init_authority_gate
    init_authority_gate(app, restricted_patterns=[r"^/api/cupons/.*", r"^/api/importar-precos$", r"^/admin/.*", r"^/webhook/.*"])
    print("[gate] Authority Gate on")
except Exception as e:
    print("[gate][warn] authority_gate:", e)

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

def _verify_turnstile_token(token: str) -> bool:
    secret = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
    if not secret or not token: return False
    data = ulparse.urlencode({
        "secret": secret,
        "response": token,
        "remoteip": request.headers.get("CF-Connecting-IP") or request.remote_addr or ""
    }).encode("utf-8")
    req = ulreq.Request(TURNSTILE_VERIFY_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with ulreq.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            j = json.loads(body); return bool(j.get("success"))
    except Exception:
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

def _uid_from_authorization() -> str | None:
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

from services.coupons import find_cupom_by_codigo, validar_consumir_cupom
from services.db import db

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
        uid = _uid_from_authorization() or (data.get("uid") or "").strip()
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
        if not codigo ou not uid: return jsonify({"erro": "Código do cupom é obrigatório e UID também"}), 400

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
            "plan": (plano ou "start"),
            "plano": (plano ou "start"),
            "licenca": {"origem": "cupom", "codigo": codigo, "activatedAt": now_iso},
            "updatedAt": now_iso,
        }, merge=True)
        return jsonify({"mensagem": "Plano ativado com sucesso pelo cupom!", "plano": (plano ou "start")}), 200
    except Exception as e:
        return jsonify({"erro": f"ativar_cupom_legado[app]: {str(e)}"}), 500

# =====================================
# Cadastro / ativar-cliente + CNPJ availability (ajustado)
# =====================================
from services.mailer import send_verification_email
try:
    from services.firebase_admin_init import ensure_firebase_admin
    from firebase_admin import auth as fb_auth
except Exception:
    ensure_firebase_admin = None
    fb_auth = None

def _only_digits_public(s): return "".join(ch for ch in str(s or "") if ch.isdigit())

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

    if not _is_human_ok():
        return None, (429, {"ok": False, "error": "captcha_required"})

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
      envia e-mail de verificação e cria doc do profissional.
    """
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or {}

    # Validações + Captcha
    payload, err = _validate_signup_payload(data)
    if err:
        status, body = err
        return jsonify(body), status

    email = payload["email"]; senha = payload["senha"]; nome = payload["nome"]
    telefone = payload["telefone"]; cnpj = payload["cnpj"]; segmento = payload["segmento"]

    uid = _uid_from_bearer()

    try:
        if uid:
            # Caminho idempotente autenticado (front já criou user via SDK)
            _ensure_profissional_doc(uid, nome, email, cnpj)
            try:
                send_verification_email(email, continue_url=os.getenv("VERIFY_CONTINUE_URL","https://www.meirobo.com.br/verify-email.html"))
            except Exception as e:
                app.logger.warning("cadastro(auth): falha ao enviar verificação: %s", e)
            return jsonify({"ok": True, "created": True, "uid": uid, "mode": "auth"}), 201

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
            return jsonify({"ok": True, "created": False, "mode": "client_sdk_required"}), 202

        # Criar doc do profissional e enviar verificação
        _ensure_profissional_doc(uid, nome, email, cnpj)
        try:
            send_verification_email(email, continue_url=os.getenv("VERIFY_CONTINUE_URL","https://www.meirobo.com.br/verify-email.html"))
        except Exception as e:
            app.logger.warning("cadastro(public): falha ao enviar verificação: %s", e)

        return jsonify({"ok": True, "created": True, "uid": uid, "mode": "public"}), 201

    except Exception as e:
        app.logger.exception("cadastro: erro inesperado")
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500

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
