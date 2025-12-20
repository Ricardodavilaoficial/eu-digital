# services/voice_wa_outbound.py
# NOVO — envio opcional de mensagem "convite" pro WhatsApp do MEI.
#
# ⚠️ Só roda se VOICE_WA_OUTBOUND_MODE=on.
#
# Suporta:
# - Meta Cloud API (VOICE_WA_PROVIDER=meta)
# - YCloud genérico (VOICE_WA_PROVIDER=ycloud) — você ajusta o payload quando tiver o spec.
#
# ENVs (Meta):
# - VOICE_WA_PROVIDER=meta
# - VOICE_WA_PROVIDER_TOKEN=...
# - VOICE_WA_META_PHONE_NUMBER_ID=...   (obrigatório)
# - VOICE_WA_META_GRAPH_VERSION=v20.0   (opcional)
#
# ENVs (YCloud genérico):
# - VOICE_WA_PROVIDER=ycloud
# - VOICE_WA_YCLOUD_SEND_URL=...        (obrigatório)
# - VOICE_WA_PROVIDER_TOKEN=...         (opcional)
#
# Texto:
# - VOICE_WA_INVITE_TEXT=... (opcional)

from __future__ import annotations

import os
import json
from typing import Tuple

import requests

# sender oficial YCloud (já usado no webhook)
from providers.ycloud import send_text as ycloud_send_text  # type: ignore

def _safe_trunc(s: str, n: int = 220) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ").strip()
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."

def _meta_error_detail(status_code: int, body_text: str) -> str:
    """Return a compact, non-sensitive error string for logs/UI."""
    msg = ""
    code = ""
    fbtrace = ""
    try:
        data = json.loads(body_text or "{}")
        err = data.get("error") or {}
        msg = str(err.get("message") or "")
        code = str(err.get("code") or "")
        fbtrace = str(err.get("fbtrace_id") or "")
    except Exception:
        msg = body_text or ""
    parts = [f"meta_http_{status_code}"]
    if code:
        parts.append(f"code_{code}")
    if fbtrace:
        parts.append(f"fbtrace_{fbtrace}")
    if msg:
        parts.append(_safe_trunc(msg, 160))
    return "|".join(parts)


def _provider() -> str:
    return (os.environ.get("VOICE_WA_PROVIDER", "meta") or "meta").strip().lower()

def _timeout() -> int:
    return int(os.environ.get("VOICE_WA_SEND_TIMEOUT_SECONDS", "15") or "15")

def _invite_text() -> str:
    return (os.environ.get("VOICE_WA_INVITE_TEXT") or
            "Aqui é o MEI Robô 🤖\n\nResponda esta mensagem com um ÁUDIO de 1 a 3 minutos, falando naturalmente (como você fala com seus clientes).").strip()

def send_invite_message(to_e164: str) -> Tuple[bool, str]:
    prov = _provider()
    if prov == "meta":
        return _send_meta_text(to_e164)
    if prov == "ycloud":
        return _send_ycloud_text(to_e164)
    return (False, "provider_not_supported")

def _send_meta_text(to_e164: str) -> Tuple[bool, str]:
    token = (os.environ.get("VOICE_WA_PROVIDER_TOKEN") or "").strip()
    phone_number_id = (os.environ.get("VOICE_WA_META_PHONE_NUMBER_ID") or "").strip()
    if not token:
        return (False, "meta_missing_token")
    if not phone_number_id:
        return (False, "meta_missing_phone_number_id")

    graph_ver = (os.environ.get("VOICE_WA_META_GRAPH_VERSION") or "v20.0").strip()
    url = f"https://graph.facebook.com/{graph_ver}/{phone_number_id}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": to_e164.replace("+", ""),
        "type": "text",
        "text": {"preview_url": False, "body": _invite_text()},
    }

    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=_timeout(),
        )
    except requests.RequestException as e:
        print(f"[voice-wa][meta] request_error to={_safe_trunc(to_e164, 40)} err={_safe_trunc(str(e), 160)}")
        return (False, "meta_request_error")

    if 200 <= r.status_code < 300:
        return (True, "meta_sent")

    detail = _meta_error_detail(r.status_code, getattr(r, "text", "") or "")
    print(f"[voice-wa][meta] send_failed to={_safe_trunc(to_e164, 40)} detail={detail}")
    return (False, detail)

def _send_ycloud_text(to_e164: str) -> Tuple[bool, str]:
    """Envia o convite via YCloud usando o sender oficial (providers.ycloud.send_text).

    Reaproveita as ENVs já existentes do provider (ex.: YCLOUD_BASE_URL, WHATSAPP_TOKEN, etc.).
    """
    try:
        ycloud_send_text(to_e164, _invite_text())
        return (True, "ycloud_sent")
    except Exception as e:
        detail = f"ycloud_send_error|{_safe_trunc(str(e), 180)}"
        print(f"[voice-wa][ycloud] send_failed to={_safe_trunc(to_e164, 40)} detail={detail}")
        return (False, detail)


