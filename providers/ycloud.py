# providers/ycloud.py
# YCloud WhatsApp Sender (HTTP puro) — MEI Robô
# - send_text / send_audio / send_template via /v2/whatsapp/messages/sendDirectly
# - Não depende de SDK
# - Seguro: não loga segredos; erros saneados

from __future__ import annotations

import os
import json
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib import request as ulreq
from urllib.error import HTTPError, URLError


DEFAULT_BASE_URL = "https://api.ycloud.com"
DEFAULT_TIMEOUT_SECONDS = 12


class YCloudError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _base_url() -> str:
    # permite override (staging)
    return _env("YCLOUD_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    k = _env("YCLOUD_API_KEY", "")
    if not k:
        raise YCloudError("missing_YCLOUD_API_KEY")
    return k


def _from_number() -> str:
    """
    Para o endpoint sendDirectly, o campo "from" deve ser o NÚMERO E.164
    registrado/conectado na YCloud (ex.: +555181474122).

    NÃO usar YCLOUD_WHATSAPP_PHONE_NUMBER_ID aqui.
    O ID existe e é útil para outras APIs, mas não como "from" deste sender.
    """
    v = _env("YCLOUD_WA_FROM_E164", "")
    if v:
        return v

    # fallback voz (se você usa isso em outro lugar)
    v = _env("VOICE_WA_NUMBER_E164", "") or _env("VOICE_WA_TEMP_NUMBER_E164", "")
    if v:
        return v

    raise YCloudError("missing_from_number (set YCLOUD_WA_FROM_E164)")


def _timeout() -> int:
    try:
        return int(_env("YCLOUD_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)) or DEFAULT_TIMEOUT_SECONDS)
    except Exception:
        return DEFAULT_TIMEOUT_SECONDS


def _post_json(path: str, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    url = f"{_base_url()}{path}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": _api_key(),
        "User-Agent": "mei-robo/ycloud-sender",
    }

    req = ulreq.Request(url, data=body, headers=headers, method="POST")

    try:
        with ulreq.urlopen(req, timeout=_timeout()) as resp:
            raw = resp.read() or b"{}"
            data = json.loads(raw.decode("utf-8", errors="replace"))
            return True, data

    except HTTPError as e:
        # erro HTTP com body JSON (geralmente)
        try:
            raw = e.read() or b"{}"
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            data = {"error": {"message": str(e), "status": getattr(e, "code", 0)}}

        return False, {
            "httpStatus": getattr(e, "code", 0),
            "error": data.get("error") or data,
        }

    except (URLError, socket.timeout) as e:
        return False, {
            "httpStatus": 0,
            "error": {"message": f"network_error:{type(e).__name__}"},
        }

    except Exception as e:
        return False, {
            "httpStatus": 0,
            "error": {"message": f"unexpected_error:{type(e).__name__}"},
        }


def send_text(to_e164: str, text: str, from_e164: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
    payload = {
        "from": (from_e164 or _from_number()),
        "to": (to_e164 or "").strip(),
        "type": "text",
        "text": {"body": (text or "").strip()},
    }
    return _post_json("/v2/whatsapp/messages/sendDirectly", payload)


def send_audio(to_e164: str, audio_url: str, from_e164: Optional[str] = None) -> Tuple[bool, Dict[str, Any]]:
    payload = {
        "from": (from_e164 or _from_number()),
        "to": (to_e164 or "").strip(),
        "type": "audio",
        "audio": {"link": (audio_url or "").strip()},
    }
    return _post_json("/v2/whatsapp/messages/sendDirectly", payload)


def send_template(
    to_e164: str,
    template_name: str,
    params: List[str],
    language_code: str = "pt_BR",
    from_e164: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    parameters = [{"type": "text", "text": str(x)} for x in (params or [])]

    payload = {
        "from": (from_e164 or _from_number()),
        "to": (to_e164 or "").strip(),
        "type": "template",
        "template": {
            "name": (template_name or "").strip(),
            "language": {"code": (language_code or "pt_BR").strip(), "policy": "deterministic"},
            "components": [{"type": "body", "parameters": parameters}],
        },
    }
    return _post_json("/v2/whatsapp/messages/sendDirectly", payload)
