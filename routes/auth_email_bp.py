# routes/auth_email_bp.py
from flask import Blueprint, request, jsonify, current_app, render_template
import json, os
from urllib import request as ulreq
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin

auth_email_bp = Blueprint("auth_email_bp", __name__)

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"

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
    auth = request.headers.get("Authorization", "")
    return {"Authorization": auth} if auth else {}

@auth_email_bp.route("/send-verification-email", methods=["POST"])
def send_verification_email_pretty():
    """
    Gera o verificationLink via /api/auth/send-verification
    e envia e-mail HTML com logo + botão (SendGrid).
    """
    # 0) Segurança: requer Bearer (mesma política do /api/auth/*)
    auth_hdr = request.headers.get("Authorization", "").strip()
    if not auth_hdr.lower().startswith("bearer "):
        return jsonify({"ok": False, "error": "unauthenticated"}), 401

    # 1) Gera link assinado usando o endpoint já existente (fonte da verdade)
    base = _internal_base()
    try:
        code, resp = _http_json_follow(
            "POST",
            f"{base}/api/auth/send-verification",   # sem barra final; seguiremos 307/308 se houver
            headers=_forward_auth_headers(),
            body={}
        )
        if code != 200 or not isinstance(resp, dict) or not resp.get("ok"):
            return jsonify({"ok": False, "error": "send_verification_failed", "detail": resp, "status": code}), 500
        verification_link = resp.get("verificationLink") or resp.get("link")
        if not verification_link:
            return jsonify({"ok": False, "error": "missing_verification_link"}), 500
    except (HTTPError, URLError) as e:
        return jsonify({"ok": False, "error": "send_verification_http_error", "detail": str(e)}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": "send_verification_exception", "detail": str(e)}), 500

    # 2) Obtém e-mail do usuário via whoami (robusto e já existente)
    try:
        code, who = _http_json_follow(
            "GET",
            f"{base}/api/auth/whoami",
            headers=_forward_auth_headers(),
            body=None
        )
        if code != 200 or not isinstance(who, dict) or not who.get("ok"):
            return jsonify({"ok": False, "error": "whoami_failed", "detail": who, "status": code}), 500
        to_email = (who.get("email") or "").strip().lower()
        if not to_email:
            return jsonify({"ok": False, "error": "missing_email_from_whoami"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": "whoami_exception", "detail": str(e)}), 500

    # 3) Renderiza HTML (template simples com {{ verificationLink }})
    try:
        html_body = render_template("email_verification.html", verificationLink=verification_link)
        text_body = (
            "Confirme seu e-mail para continuar sua ativação no MEI Robô.\n\n"
            f"Abrir link de confirmação: {verification_link}\n\n"
            "Se você não se cadastrou, ignore este e-mail."
        )
    except Exception as e:
        return jsonify({"ok": False, "error": "template_render_error", "detail": str(e)}), 500

    # 4) Envia via SendGrid
    sg_key = os.getenv("SENDGRID_API_KEY", "").strip()
    if not sg_key:
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
    if reply_to:
        payload["reply_to"] = {"email": reply_to}

    try:
        code, _ = _http_json_follow(
            "POST",
            SENDGRID_API_URL,
            headers={"Authorization": f"Bearer {sg_key}"},
            body=payload,
            timeout=20
        )
        if code not in (200, 202):
            return jsonify({"ok": False, "error": "sendgrid_not_accepted", "status": code}), 502
    except HTTPError as e:
        return jsonify({"ok": False, "error": "sendgrid_http_error", "status": getattr(e, 'code', None), "detail": str(e)}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": "sendgrid_exception", "detail": str(e)}), 502

    return jsonify({"ok": True, "sent": True}), 200
