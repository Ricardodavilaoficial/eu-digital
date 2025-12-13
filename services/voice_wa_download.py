# services/voice_wa_download.py
# NOVO — resolve payload de webhook (Meta/YCloud) e baixa mídia de áudio.
# v1.0: "best-effort" e tolerante a formatos diferentes.
#
# ENVs:
# - VOICE_WA_PROVIDER=meta|ycloud|auto (opcional, default auto)
# - VOICE_WA_PROVIDER_TOKEN (token para baixar mídia do provider, ex: Meta Cloud API)
# - VOICE_WA_MEDIA_TIMEOUT_SECONDS (default 20)
# - VOICE_WA_MIN_BYTES (default 20000 ~ 20KB)
#
# Obs: Sem conversão de formato.

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional, Tuple

import requests

def _provider_default() -> str:
    return (os.environ.get("VOICE_WA_PROVIDER", "auto") or "auto").strip().lower()

def _timeout() -> int:
    return int(os.environ.get("VOICE_WA_MEDIA_TIMEOUT_SECONDS", "20") or "20")

def _min_bytes() -> int:
    return int(os.environ.get("VOICE_WA_MIN_BYTES", "20000") or "20000")

def sniff_extension(mime_type: Optional[str], fallback: str = "ogg") -> str:
    mt = (mime_type or "").lower().strip()
    if "ogg" in mt:
        return "ogg"
    if "mpeg" in mt or "mp3" in mt:
        return "mp3"
    if "wav" in mt:
        return "wav"
    if "m4a" in mt or "mp4" in mt:
        return "m4a"
    if "aac" in mt:
        return "aac"
    return fallback

def basic_audio_validate(data: bytes, mime_type: Optional[str] = None) -> Tuple[bool, str]:
    if not data or len(data) == 0:
        return False, "empty_file"
    if len(data) < _min_bytes():
        return False, "audio_too_short"
    return True, ""

def resolve_incoming_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza vários formatos de webhook.
    Retorna dict:
      kind: "text"|"audio"|"unknown"
      provider: "meta"|"ycloud"|"unknown"
      fromE164: "+55..."
      messageId: "..."
      text: "..." (quando kind=text)
      mimeType, durationSec (quando disponível)
      media: { id, url, filename, mimeType }
    """
    # 1) Meta WhatsApp Cloud API (entry -> changes -> value -> messages)
    try:
        entry = (payload.get("entry") or [])
        if isinstance(entry, list) and entry:
            changes = entry[0].get("changes") or []
            if changes:
                value = changes[0].get("value") or {}
                messages = value.get("messages") or []
                if messages:
                    msg = messages[0]
                    mtype = (msg.get("type") or "").lower()
                    sender = msg.get("from")  # wa_id (sem +)
                    # converte pra E.164 BR best-effort
                    from_e164 = "+" + re.sub(r"\D+", "", str(sender or ""))
                    if from_e164.startswith("+55") is False and len(from_e164) >= 11:
                        # deixa como está; pode ser não-BR
                        pass
                    if mtype == "text":
                        text = (msg.get("text") or {}).get("body") or ""
                        return {
                            "kind": "text",
                            "provider": "meta",
                            "fromE164": from_e164,
                            "messageId": msg.get("id") or "",
                            "text": text,
                        }
                    if mtype in ("audio", "voice"):
                        audio = msg.get("audio") or {}
                        return {
                            "kind": "audio",
                            "provider": "meta",
                            "fromE164": from_e164,
                            "messageId": msg.get("id") or "",
                            "mimeType": audio.get("mime_type") or "",
                            "durationSec": audio.get("duration") or None,
                            "media": {
                                "id": audio.get("id") or "",
                                "mimeType": audio.get("mime_type") or "",
                            },
                        }
    except Exception:
        pass

    # 2) YCloud / genérico: tente alguns formatos comuns
    # Ex.: { "type":"message", "message":{ "type":"audio", "from":"+55..", "id":"...", "media":{...}} }
    for root_key in ("message", "data", "payload"):
        try:
            node = payload.get(root_key) or payload
            mtype = (node.get("type") or node.get("message_type") or "").lower()
            if mtype in ("text", "chat"):
                text = node.get("text") or node.get("body") or ""
                return {
                    "kind": "text",
                    "provider": "ycloud" if _provider_default() in ("ycloud",) else "unknown",
                    "fromE164": node.get("from") or node.get("from_number") or "",
                    "messageId": node.get("id") or node.get("message_id") or "",
                    "text": text,
                }
            if mtype in ("audio", "voice"):
                media = node.get("media") or node.get("audio") or {}
                return {
                    "kind": "audio",
                    "provider": "ycloud" if _provider_default() in ("ycloud",) else "unknown",
                    "fromE164": node.get("from") or node.get("from_number") or "",
                    "messageId": node.get("id") or node.get("message_id") or "",
                    "mimeType": media.get("mimeType") or media.get("mime_type") or node.get("mimeType") or "",
                    "durationSec": media.get("durationSec") or media.get("duration") or None,
                    "media": {
                        "id": media.get("id") or media.get("mediaId") or "",
                        "url": media.get("url") or media.get("mediaUrl") or "",
                        "filename": media.get("filename") or "",
                        "mimeType": media.get("mimeType") or media.get("mime_type") or "",
                    }
                }
        except Exception:
            pass

    # 3) fallback: unknown
    return {"kind": "unknown", "provider": _provider_default(), "fromE164": "", "messageId": "", "media": {}}

def _meta_resolve_media_url(media_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Meta Cloud API: GET /{media-id} -> { url, mime_type }.
    Requer VOICE_WA_PROVIDER_TOKEN.
    """
    token = (os.environ.get("VOICE_WA_PROVIDER_TOKEN") or "").strip()
    if not token or not media_id:
        return None, None
    # versão do Graph: deixe parametrizável
    graph_ver = (os.environ.get("VOICE_WA_META_GRAPH_VERSION") or "v20.0").strip()
    url = f"https://graph.facebook.com/{graph_ver}/{media_id}"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=_timeout())
    if r.status_code != 200:
        return None, None
    j = r.json() or {}
    return j.get("url"), j.get("mime_type")

def download_media_bytes(provider: str, media: Dict[str, Any]) -> Tuple[bytes, str]:
    """Baixa bytes de mídia e retorna (data, mime_type)."""
    provider = (provider or _provider_default() or "unknown").lower()
    media_id = (media.get("id") or "").strip()
    media_url = (media.get("url") or "").strip()
    mime = (media.get("mimeType") or media.get("mime_type") or "").strip()

    if provider == "meta":
        # resolve url se necessário
        if not media_url and media_id:
            resolved_url, resolved_mime = _meta_resolve_media_url(media_id)
            media_url = resolved_url or media_url
            mime = resolved_mime or mime
        if not media_url:
            raise RuntimeError("meta_no_media_url")
        token = (os.environ.get("VOICE_WA_PROVIDER_TOKEN") or "").strip()
        if not token:
            raise RuntimeError("meta_missing_token")
        r = requests.get(media_url, headers={"Authorization": f"Bearer {token}"}, timeout=_timeout())
        r.raise_for_status()
        return (r.content or b""), (mime or (r.headers.get("Content-Type") or ""))

    # ycloud/unknown: tenta URL direta, com token opcional
    if not media_url:
        raise RuntimeError("no_media_url")
    hdrs = {}
    bearer = (os.environ.get("VOICE_WA_PROVIDER_TOKEN") or "").strip()
    if bearer:
        hdrs["Authorization"] = f"Bearer {bearer}"
    r = requests.get(media_url, headers=hdrs, timeout=_timeout())
    r.raise_for_status()
    return (r.content or b""), (mime or (r.headers.get("Content-Type") or ""))
