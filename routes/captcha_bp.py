# routes/captcha_bp.py
# Blueprint para verificar Cloudflare Turnstile sem depender de "requests".
# Usa apenas bibliotecas padrão (urllib) para evitar falhas de deploy por dependência ausente.

import os
import json
import time
import hmac
import hashlib
from urllib import request as ulreq
from urllib import parse as ulparse
from flask import Blueprint, jsonify, request, make_response

captcha_bp = Blueprint("captcha_bp", __name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

def _json_post(url: str, data: dict, timeout: int = 10) -> dict:
    payload = ulparse.urlencode(data).encode("utf-8")
    req = ulreq.Request(url, data=payload, headers={
        "Content-Type": "application/x-www-form-urlencoded"
    })
    try:
        with ulreq.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"success": False, "error": "network_error", "details": str(e)}
    try:
        return json.loads(body)
    except Exception:
        return {"success": False, "error": "bad_json", "body": body}

def _sign_value(raw: str, key: str) -> str:
    # assinatura curta (16 hex) para valor+ts
    mac = hmac.new(key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return mac[:16]

@captcha_bp.route("/captcha/verify", methods=["POST", "OPTIONS"])
def verify_captcha():
    # CORS: o app.py já habilita globalmente; aqui só espelhamos o básico
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Vary"] = "Origin"
        return resp

    secret = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
    if not secret:
        return jsonify({"ok": False, "error": "server_misconfigured: missing TURNSTILE_SECRET_KEY"}), 500

    data = request.get_json(silent=True) or {}
    token = data.get("token") or data.get("cf_resp") or request.form.get("token") or ""
    if not token:
        return jsonify({"ok": False, "error": "missing token"}), 400

    remoteip = request.headers.get("CF-Connecting-IP") or request.remote_addr or ""

    res = _json_post(TURNSTILE_VERIFY_URL, {
        "secret": secret,
        "response": token,
        "remoteip": remoteip
    })

    if not bool(res.get("success")):
        return jsonify({"ok": False, "error": "verification_failed", "details": res}), 502

    # Cookie "human_ok" por 5 minutos
    max_age = 5 * 60
    ts = int(time.time())
    val = "1"
    cookie_val = val

    sign_key = os.getenv("HUMAN_COOKIE_SIGNING_KEY", "").strip()
    if sign_key:
        base = f"{val}.{ts}"
        sig = _sign_value(base, sign_key)
        cookie_val = f"{base}.{sig}"

    resp = jsonify({"ok": True})
    # Cookie HttpOnly/Lax, seguro. (sem Domain explícito para o navegador decidir)
    resp.set_cookie(
        "human_ok",
        cookie_val,
        max_age=max_age,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    # Espelha CORS básico
    resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
    resp.headers["Vary"] = "Origin"
    return resp, 200
