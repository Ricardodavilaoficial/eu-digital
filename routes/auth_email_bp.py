from flask import Blueprint, request, jsonify, current_app, render_template
import json, os, uuid, time
from urllib import request as ulreq
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, quote
import urllib.parse as uparse
import redis

auth_email_bp = Blueprint("auth_email_bp", __name__)

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


# ==========================================================
# Email verification mode
# - sendgrid (default, atual)
# - firebase  (fallback Google)
# ==========================================================
def _email_verify_mode():
    return os.getenv("EMAIL_VERIFY_MODE", "sendgrid").strip().lower()
# === Redis setup for VT and verified flags ===
REDIS_URL = os.getenv("REDIS_URL", "").strip()
_r = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None

def _set_vt(uid: str, email: str, ttl: int = 24 * 3600) -> str:
    """Generate a verification token (VT) and store in Redis with TTL."""
    vt = uuid.uuid4().hex
    if _r:
        _r.setex(f"verif:{vt}", ttl, json.dumps({"uid": uid, "email": email, "ts": int(time.time())}))
    return vt

def _internal_base():
    # Usa o host atual (https://<render-domain>/)
    return (request.url_root or "").rstrip("/")

def _http_json_follow(method: str, url: str, headers: dict | None = None, body: dict | None = None, timeout: int = 15, max_redirects: int = 3):
    """
    Faz requisição JSON e segue redirects HTTP (301/302/303/307/308).
    - 303: troca para GET e remove body (comportamento padrão).
    - 301/302/307/308: mantém método e body.
    """
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)

    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    cur_method = method.upper()
    cur_url = url
    cur_data = data
    redirects = 0

    while True:
        req = ulreq.Request(cur_url, data=cur_data, headers=hdrs, method=cur_method)
        try:
            with ulreq.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                # Tenta JSON, senão retorna string bruta
                parsed = json.loads(raw) if raw.strip().startswith("{") else raw
                return resp.getcode(), parsed
        except HTTPError as e:
            # Se não for redirect, propaga
            if e.code not in (301, 302, 303, 307, 308):
                raise
            if redirects >= max_redirects:
                raise

            loc = e.headers.get("Location")
            if not loc:
                raise

            # Normaliza URL destino (pode ser relativo)
            next_url = urljoin(cur_url, loc)

            # Regra 303 → GET sem body
            if e.code == 303:
                cur_method = "GET"
                cur_data = None
            # Demais mantém método/body

            cur_url = next_url
            redirects += 1
            continue
        except URLError:
            raise

def _forward_auth_headers():
    # Mantida para compatibilidade, mas evitamos usá-la para garantir que o Bearer
    # validado seja exatamente o que vamos repassar (sem logs do token).
    auth = request.headers.get("Authorization", "")
    return {"Authorization": auth} if auth else {}

@auth_email_bp.route("/send-verification-email", methods=["GET", "POST", "OPTIONS"])
def send_verification_email_pretty():
    """
    Envia e-mail HTML (SendGrid) com link direto para verify-email.html com VT (verification token).
    Aceita GET/POST/OPTIONS (mesmo tratamento para GET e POST).
    """

    
    mode = _email_verify_mode()

    # ======================================================
    # MODO FIREBASE
    # - Não envia SendGrid
    # - Frontend usará sendEmailVerification() nativo
    # ======================================================
    if mode == "firebase":
        current_app.logger.warning(
            "[auth_email] EMAIL_VERIFY_MODE=firebase → skip SendGrid send"
        )
        return jsonify({"ok": True, "sent": False, "mode": "firebase"}), 200

# Pré-flight simples
    if request.method == "OPTIONS":
        # Deixe o middleware de CORS completar os headers; aqui só respondemos vazio.
        return ("", 204)

    # Requer Redis para VT
    if not _r:
        current_app.logger.error("[auth_email] missing REDIS_URL for VT generation")
        return jsonify({"ok": False, "error": "missing_redis"}), 500

    # 0) Segurança: requer Bearer (mesma política do /api/auth/*)
    auth_hdr = request.headers.get("Authorization", "").strip()
    if not auth_hdr.lower().startswith("bearer "):
        current_app.logger.warning("[auth_email] missing bearer on client request")
        return jsonify({"ok": False, "error": "missing_bearer"}), 401

    # 1) Entrada: GET/POST tratados igual
    payload = request.get_json(silent=True) or {}
    if request.method == "GET":
        # permitir /send-verification-email?cont=/pages/configuracao.html
        if "cont" not in payload:
            payload["cont"] = (request.args.get("cont") or "").strip()

    cont = (payload.get("cont") or "").strip()

    base = _internal_base()

    # 2) Obtém e-mail e uid do usuário via whoami (robusto e já existente)
    try:
        current_app.logger.info("[auth_email] fetching whoami (send_via=sendgrid_pretty_vt)")
        code, who = _http_json_follow(
            "GET",
            f"{base}/api/auth/whoami",
            headers={
                "Authorization": auth_hdr,  # repasse 1:1 do Bearer do cliente
                "Accept": "application/json",
            },
            body=None,
            timeout=7,
        )
        if code != 200 or not isinstance(who, dict) or not who.get("ok"):
            current_app.logger.error("[auth_email] whoami_bad_status code=%s", code)
            return jsonify({"ok": False, "error": "whoami_exception", "detail": f"status_{code}"}), 500
        to_email = (who.get("email") or "").strip().lower()
        uid = (who.get("uid") or "").strip()
        if not to_email or not uid:
            current_app.logger.error("[auth_email] missing email or uid from whoami")
            return jsonify({"ok": False, "error": "missing_email_or_uid_from_whoami"}), 500
    except Exception as e:
        current_app.logger.exception("[auth_email] whoami_exception")
        return jsonify({"ok": False, "error": "whoami_exception", "detail": str(e)}), 500

    # 3) Monta LINK com VT → verify-email.html?vt=...&email=...&cont=/pages/configuracao.html
    try:
        frontend = os.getenv("FRONTEND_BASE", "https://www.meirobo.com.br").rstrip("/")
        cont_final = cont or "/pages/configuracao.html"
        vt = _set_vt(uid, to_email)
        params = {
            "vt": vt,
            "email": to_email,
            "cont": cont_final,
        }
        verification_link = f"{frontend}/verify-email.html?{uparse.urlencode(params)}"
        current_app.logger.info("[auth_email] using VT verification link: %s", verification_link)
    except Exception as e:
        current_app.logger.exception("[auth_email] vt_link_build_error")
        return jsonify({"ok": False, "error": "vt_link_build_error", "detail": str(e)}), 500

    # 4) Renderiza HTML (template simples com {{ verificationLink }})
    try:
        html_body = render_template("email_verification.html", verificationLink=verification_link)
        text_body = (
            "Confirme seu e-mail para continuar sua ativação no MEI Robô.\n\n"
            f"Abrir link de confirmação: {verification_link}\n\n"
            "Se você não se cadastrou, ignore este e-mail."
        )
    except Exception as e:
        current_app.logger.exception("[auth_email] template_render_error")
        return jsonify({"ok": False, "error": "template_render_error", "detail": str(e)}), 500

    # 5) Envia via SendGrid
    sg_key = os.getenv("SENDGRID_API_KEY", "").strip()
    if not sg_key:
        current_app.logger.error("[auth_email] missing SENDGRID_API_KEY")
        return jsonify({"ok": False, "error": "missing_sendgrid_api_key"}), 500

    from_name = os.getenv("EMAIL_FROM_NAME", "MEI Robô")
    from_addr = os.getenv("EMAIL_FROM_ADDR", "mei-robo@fujicadobrasil.com.br")
    reply_to = os.getenv("EMAIL_REPLY_TO", "")

    subject = "MEI Robô — Confirme seu e-mail"

    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_addr, "name": from_name},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": text_body},
            {"type": "text/html", "value": html_body}
        ]
    }

    # IMPORTANTÍSSIMO: NÃO deixar o SendGrid embrulhar o link com click-tracking (ls/click),
    # porque alguns navegadores (Edge/Tracking Prevention) bloqueiam/redirecionam e fica tela branca.
    # Para e-mail de verificação, o correto é link direto.
    payload["tracking_settings"] = {
        "click_tracking": {"enable": False, "enable_text": False}
    }
    if reply_to:
        payload["reply_to"] = {"email": reply_to}

    # >>> DEBUG TEMP (REMOVER DEPOIS) <<<
    sg_key_raw = os.getenv("SENDGRID_API_KEY", "")
    from_env_dbg = os.getenv("EMAIL_SENDER") or os.getenv("EMAIL_FROM") or os.getenv("EMAIL_FROM_ADDR") or ""
    current_app.logger.warning("[auth_email][dbg] using SENDGRID_API_KEY(len)=%s EMAIL_FROM/SENDER=%s",
                               len(sg_key_raw), from_env_dbg)
    # <<< DEBUG TEMP <<<

    try:
        current_app.logger.info("[auth_email] sending via SendGrid (send_via=sendgrid_pretty_vt) to=%s", to_email)
        code, _ = _http_json_follow(
            "POST",
            SENDGRID_API_URL,
            headers={"Authorization": f"Bearer {sg_key}"},
            body=payload,
            timeout=20
        )
        if code not in (200, 202):
            current_app.logger.warning("[auth_email] sendgrid_not_accepted status=%s", code)
            return jsonify({"ok": False, "error": "sendgrid_not_accepted", "status": code}), 502
    except HTTPError as e:
        current_app.logger.exception("[auth_email] sendgrid_http_error")
        return jsonify({"ok": False, "error": "sendgrid_http_error", "status": getattr(e, 'code', None), "detail": str(e)}), 502
    except Exception as e:
        current_app.logger.exception("[auth_email] sendgrid_exception")
        return jsonify({"ok": False, "error": "sendgrid_exception", "detail": str(e)}), 502

    return jsonify({"ok": True, "sent": True}), 200


# === (B) Backend — endpoint público de confirmação via VT ===
@auth_email_bp.post("/confirm-email")
def confirm_email():
    try:
        body = request.get_json(silent=True) or {}
        vt = (body.get("vt") or "").strip()
        if not vt or not _r:
            return jsonify({"ok": False, "error": "missing_vt_or_redis"}), 400

        raw = _r.get(f"verif:{vt}")
        if not raw:
            return jsonify({"ok": False, "error": "invalid_or_expired"}), 400

        data = json.loads(raw)
        uid = data.get("uid")
        email = data.get("email")

        # >>> Fonte canônica de verificação (aqui: Redis). Troque para Firestore/DB se já tiver.
        _r.set(f"verified:{uid}", "1", ex=30 * 24 * 3600)

        _r.delete(f"verif:{vt}")
        current_app.logger.info("[auth_email] email confirmed via VT; uid=%s email=%s", uid, email)
        return jsonify({"ok": True, "verified": True})
    except Exception as e:
        current_app.logger.exception("[auth_email] confirm_email_exception")
        return jsonify({"ok": False, "error": "confirm_email_exception", "detail": str(e)}), 500


# === (C) Backend — check-verification lê a mesma fonte canônica ===
@auth_email_bp.get("/check-verification")
def check_verification():
    try:
        mode = _email_verify_mode()
        verified = False
        uid = None

        # Preferir derivar via Bearer (whoami); fallback: uid via query
        auth_hdr = request.headers.get("Authorization", "").strip()
        if auth_hdr.lower().startswith("bearer "):
            base = _internal_base()
            code, who = _http_json_follow(
                "GET",
                f"{base}/api/auth/whoami",
                headers={
                    "Authorization": auth_hdr,
                    "Accept": "application/json",
                },
                body=None,
                timeout=7,
            )
            if code == 200 and isinstance(who, dict) and who.get("ok"):
                uid = (who.get("uid") or "").strip()

        if not uid:
            uid = (request.args.get("uid") or "").strip()

        if mode == "sendgrid":
            if _r and uid:
                verified = _r.get(f"verified:{uid}") == "1"
        else:
            # firebase: confirmação é feita via Auth (frontend)
            verified = False

        return jsonify({"ok": True, "verified": bool(verified)})
    except Exception as e:
        current_app.logger.exception("[auth_email] check_verification_exception")
        return jsonify({"ok": False, "error": "check_verification_exception", "detail": str(e)}), 500
