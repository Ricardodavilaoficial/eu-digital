# -*- coding: utf-8 -*-
"""routes/captcha_bp.py — CAPTCHA robusto (Cloudflare Turnstile)
Endpoints:
  - POST /captcha/verify  -> valida token Turnstile e devolve cookie HttpOnly curto (5min)

ENV necessárias no Render:
  - TURNSTILE_SECRET_KEY   (obrigatória)
  - HUMAN_COOKIE_SIGNING_KEY  (recomendada, chave longa 32+ chars para assinar cookie)

Como usar no Frontend:
  - Renderize o widget Turnstile no login e envie o token para /captcha/verify.
  - Se ok, o backend define cookie 'human_ok' e retorna { ok: true }.
  - Habilite o botão de login após a verificação.
"""
from __future__ import annotations

import json
import os
import time
import hmac
import hashlib
import base64
from typing import Optional

from flask import Blueprint, request, jsonify, current_app, make_response

try:
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode
except Exception as e:
    raise

captcha_bp = Blueprint("captcha_bp", __name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

def _sign(value: str, key: Optional[str]) -> str:
    if not key:
        return ""
    mac = hmac.new(key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).digest()
    return _b64url(mac)

@captcha_bp.route("/captcha/verify", methods=["POST", "OPTIONS"])
def captcha_verify():
    # CORS preflight (fallback; CORS global já deve cobrir)
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        origin = request.headers.get("Origin", "*")
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return resp

    secret = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
    if not secret:
        return jsonify({"ok": False, "error": "TURNSTILE_SECRET_KEY missing"}), 500

    # aceita JSON { token } ou form token=...
    token = None
    if request.is_json:
        data = request.get_json(silent=True) or {}
        token = (data.get("token") or "").strip()
    if not token:
        token = (request.form.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "missing token"}), 400

    remoteip = request.headers.get("CF-Connecting-IP") or request.remote_addr or ""

    payload = urlencode({
        "secret": secret,
        "response": token,
        "remoteip": remoteip,
    }).encode("utf-8")
    req = Request(TURNSTILE_VERIFY_URL, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
            ver = json.loads(raw)
    except Exception as e:
        try:
            current_app.logger.exception("turnstile verify error: %s", e)
        except Exception:
            pass
        return jsonify({"ok": False, "error": "verification_failed"}), 502

    if not ver.get("success"):
        return jsonify({"ok": False, "error": "captcha_not_passed", "details": ver}), 400

    # se OK, define cookie HttpOnly curto (5min), assinado se chave existir
    now = int(time.time())
    exp = now + 5 * 60
    value = f"v1.{exp}"
    sig_key = os.getenv("HUMAN_COOKIE_SIGNING_KEY", "").strip()
    sig = _sign(value, sig_key)
    cookie_val = value if not sig else f"{value}.{sig}"

    resp = make_response(jsonify({"ok": True, "expiresAt": exp}))
    resp.set_cookie(
        "human_ok",
        cookie_val,
        max_age=5 * 60,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return resp, 200
