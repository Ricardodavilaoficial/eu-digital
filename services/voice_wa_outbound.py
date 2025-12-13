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

    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=_timeout(),
    )
    if 200 <= r.status_code < 300:
        return (True, "meta_sent")
    return (False, f"meta_http_{r.status_code}")

def _send_ycloud_text(to_e164: str) -> Tuple[bool, str]:
    send_url = (os.environ.get("VOICE_WA_YCLOUD_SEND_URL") or "").strip()
    if not send_url:
        return (False, "ycloud_missing_send_url")

    token = (os.environ.get("VOICE_WA_PROVIDER_TOKEN") or "").strip()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {"to": to_e164, "type": "text", "text": _invite_text()}

    r = requests.post(send_url, headers=headers, data=json.dumps(payload), timeout=_timeout())
    if 200 <= r.status_code < 300:
        return (True, "ycloud_sent")
    return (False, f"ycloud_http_{r.status_code}")
