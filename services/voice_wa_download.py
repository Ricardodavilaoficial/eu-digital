# services/voice_wa_download.py
# NOVO — helpers para extrair evento e baixar mídia do provedor.
#
# Suporta:
# - Meta Cloud API inbound (entry/changes/value/messages)
# - Payload genérico: {"message":{"type":"audio","from":"+55...","id":"...","media":{"url":"...","mimeType":"audio/ogg"}}}
#
# Download:
# - Se tiver URL direta, baixa com requests.
# - Se for Meta com mediaId, resolve URL via Graph usando VOICE_WA_PROVIDER_TOKEN.
#
# ENVs:
# - VOICE_WA_PROVIDER_TOKEN=...      (Meta: obrigatório para resolver mediaId)
# - VOICE_WA_META_GRAPH_VERSION=v20.0 (opcional)
# - VOICE_WA_MEDIA_TIMEOUT_SECONDS=20
# - VOICE_WA_MIN_BYTES=20000

from __future__ import annotations

import os
import json
from typing import Any, Dict, Tuple, Optional

import requests

def _timeout() -> int:
    return int(os.environ.get("VOICE_WA_MEDIA_TIMEOUT_SECONDS", "20") or "20")

def _min_bytes() -> int:
    return int(os.environ.get("VOICE_WA_MIN_BYTES", "20000") or "20000")

def resolve_incoming_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Meta Cloud API style
    try:
        entry = (payload.get("entry") or [None])[0] or {}
        changes = (entry.get("changes") or [None])[0] or {}
        value = changes.get("value") or {}
        msgs = value.get("messages") or []
        if msgs:
            m = msgs[0]
            mtype = m.get("type")
            from_raw = m.get("from") or ""
            from_e164 = "+" + "".join([c for c in str(from_raw) if c.isdigit()])
            mid = m.get("id") or ""
            if mtype == "text":
                body = ((m.get("text") or {}).get("body") or "").strip()
                return {"provider":"meta","kind":"text","fromE164":from_e164,"messageId":mid,"text":body}
            if mtype in ("audio","voice"):
                audio = m.get("audio") or {}
                # Meta usually sends: {"id": "...", "mime_type":"audio/ogg; codecs=opus", "voice":true}
                media_id = audio.get("id") or ""
                mime = (audio.get("mime_type") or "").split(";")[0].strip()
                return {"provider":"meta","kind":"audio","fromE164":from_e164,"messageId":mid,
                        "mimeType": mime, "durationSec": audio.get("duration") or None,
                        "media":{"id":media_id, "mimeType": mime}}
    except Exception:
        pass

    # Generic fallback
    msg = payload.get("message") or {}
    mtype = msg.get("type") or ""
    from_e164 = (msg.get("from") or "").strip()
    mid = (msg.get("id") or "").strip()
    if mtype == "text":
        text = ((msg.get("text") or msg.get("body") or "")).strip()
        return {"provider": payload.get("provider") or "unknown", "kind":"text","fromE164":from_e164,"messageId":mid,"text":text}
    if mtype in ("audio","voice"):
        media = msg.get("media") or {}
        return {"provider": payload.get("provider") or "unknown", "kind":"audio","fromE164":from_e164,"messageId":mid,
                "mimeType": media.get("mimeType") or "", "durationSec": media.get("durationSec"),
                "media": media}
    return {"provider": payload.get("provider") or "unknown", "kind":"unknown"}

def _meta_media_url(media_id: str) -> Tuple[str, str]:
    token = (os.environ.get("VOICE_WA_PROVIDER_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("meta_missing_token")
    graph_ver = (os.environ.get("VOICE_WA_META_GRAPH_VERSION") or "v20.0").strip()
    info_url = f"https://graph.facebook.com/{graph_ver}/{media_id}"
    r = requests.get(info_url, headers={"Authorization": f"Bearer {token}"}, timeout=_timeout())
    r.raise_for_status()
    data = r.json() or {}
    url = data.get("url") or ""
    mime = (data.get("mime_type") or "").split(";")[0].strip()
    if not url:
        raise RuntimeError("meta_media_url_missing")
    return url, mime

def download_media_bytes(provider: str, media: Dict[str, Any]) -> Tuple[bytes, str]:
    provider = (provider or "unknown").lower()
    url = (media.get("url") or "").strip()
    mime = (media.get("mimeType") or media.get("mime_type") or "").split(";")[0].strip()

    token = (os.environ.get("VOICE_WA_PROVIDER_TOKEN") or "").strip()

    if provider == "meta" and not url:
        media_id = (media.get("id") or "").strip()
        if media_id:
            url, mime2 = _meta_media_url(media_id)
            if not mime and mime2:
                mime = mime2

    if not url:
        raise RuntimeError("missing_media_url")

    headers = {}
    # Meta requires Authorization to download the media URL
    if provider == "meta" and token:
        headers["Authorization"] = f"Bearer {token}"
    # Some providers also require auth
    if media.get("authBearer") and not headers.get("Authorization"):
        headers["Authorization"] = f"Bearer {media['authBearer']}"

    r = requests.get(url, headers=headers, timeout=_timeout())
    r.raise_for_status()
    data = r.content or b""
    ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
    if not mime and ctype:
        mime = ctype
    return data, (mime or "application/octet-stream")

def sniff_extension(mime_type: str, fallback: str = "ogg") -> str:
    mt = (mime_type or "").lower()
    if "ogg" in mt or "opus" in mt:
        return "ogg"
    if "mpeg" in mt or "mp3" in mt:
        return "mp3"
    if "wav" in mt:
        return "wav"
    if "mp4" in mt or "m4a" in mt:
        return "m4a"
    return fallback

def basic_audio_validate(data: bytes, mime_type: str = "") -> Tuple[bool, str]:
    if not data:
        return (False, "empty_audio")
    if len(data) < _min_bytes():
        return (False, "audio_too_short")
    mt = (mime_type or "").lower()
    if mt and not mt.startswith("audio/"):
        # não bloqueia se mime vier vazio; mas se vier e não for áudio, rejeita
        return (False, "unsupported_media_type")
    return (True, "")
