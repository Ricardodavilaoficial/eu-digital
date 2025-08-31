# services/wa_send.py
import os
import json
import logging
import requests

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v23.0")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID") or os.getenv("PHONE_NUMBER_ID")

def _only_digits(s: str) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())

def _normalize_br_msisdn(wa_id: str) -> str:
    if not wa_id:
        return ""
    digits = _only_digits(wa_id)
    # normaliza celulares BR (insere o 9 se vier sem)
    if digits.startswith("55") and len(digits) == 12:
        digits = digits[:4] + "9" + digits[4:]
    return digits

def send_text(to: str, body: str):
    """Envia texto via WhatsApp Cloud API."""
    to_digits = _normalize_br_msisdn(to)
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logging.error("[WA][SEND_TEXT] Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID")
        return False, {"error": "missing_whatsapp_config"}

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_digits,
        "type": "text",
        "text": {"preview_url": False, "body": (body or "")[:4096]},
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        try:
            resp_json = r.json()
        except Exception:
            resp_json = {"raw": r.text[:400]}
        logging.info("[WA][OUT TEXT] to=%s status=%s resp=%s", to_digits, r.status_code, str(resp_json)[:600])
        return r.ok, resp_json
    except Exception as e:
        logging.exception("[WA][SEND_TEXT][ERROR] %s", e)
        return False, {"error": repr(e)}

def send_audio(to: str, audio_bytes: bytes, mime_type: str = "audio/ogg"):
    """
    Envia áudio pela Cloud API:
      1) upload binário -> media_id
      2) send message type=audio com audio.id
    """
    to_digits = _normalize_br_msisdn(to)
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logging.error("[WA][SEND_AUDIO] Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID")
        return False, {"error": "missing_whatsapp_config"}

    try:
        # upload
        url_upload = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/media"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        files = {"file": ("voice.ogg", audio_bytes, (mime_type or "audio/ogg"))}
        data = {"messaging_product": "whatsapp"}
        ru = requests.post(url_upload, headers=headers, files=files, data=data, timeout=30)
        try:
            media_js = ru.json()
        except Exception:
            media_js = {"status_code": ru.status_code, "text": ru.text[:200]}
        media_id = (media_js or {}).get("id")
        if not media_id:
            logging.warning("[WA][AUDIO][UPLOAD_FAIL] %s", media_js)
            return False, {"error": "upload_failed", "resp": media_js}

        # message
        url_msg = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to_digits,
            "type": "audio",
            "audio": {"id": media_id},
        }
        rm = requests.post(url_msg, headers=headers, json=payload, timeout=20)
        try:
            js = rm.json()
        except Exception:
            js = {"status_code": rm.status_code, "text": rm.text[:200]}
        logging.info("[WA][OUT AUDIO] to=%s status=%s resp=%s", to_digits, rm.status_code, str(js)[:600])
        return rm.ok, js
    except Exception as e:
        logging.exception("[WA][SEND_AUDIO][ERROR] %s", e)
        return False, {"error": repr(e)}

def send_audio_link(to: str, url_link: str):
    """
    Alternativa: envia áudio por link (sem upload). Útil se o TTS salvou no GCS/S3 com URL pública.
    """
    to_digits = _normalize_br_msisdn(to)
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logging.error("[WA][AUDIO_LINK] Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID")
        return False, {"error": "missing_whatsapp_config"}

    try:
        url_msg = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to_digits,
            "type": "audio",
            "audio": {"link": url_link},
        }
        r = requests.post(url_msg, headers=headers, json=payload, timeout=20)
        try:
            js = r.json()
        except Exception:
            js = {"status_code": r.status_code, "text": r.text[:200]}
        logging.info("[WA][AUDIO_LINK] to=%s status=%s resp=%s", to_digits, r.status_code, str(js)[:600])
        return r.ok, js
    except Exception as e:
        logging.exception("[WA][AUDIO_LINK][ERROR] %s", e)
        return False, {"error": repr(e)}

def fetch_media(media_id: str):
    """
    Baixa bytes de uma mídia (ex.: áudio recebido) usando o media_id.
    Retorna (bytes, mime_type) ou (None, None).
    """
    if not WHATSAPP_TOKEN:
        logging.error("[WA][FETCH_MEDIA] Missing WHATSAPP_TOKEN")
        return None, None
    try:
        # 1) metadados (URL privada)
        info = requests.get(
            f"https://graph.facebook.com/{GRAPH_VERSION}/{media_id}",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=15
        ).json()
        media_url = info.get("url")
        if not media_url:
            logging.warning("[WA][MEDIA_INFO_FAIL] %s", info)
            return None, None

        # 2) download binário autorizado
        r = requests.get(media_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=30)
        content_type = r.headers.get("Content-Type", "application/octet-stream")
        data = r.content or b""
        if not data:
            return None, None
        return data, content_type
    except Exception as e:
        logging.exception("[WA][FETCH_MEDIA][ERROR] %s", e)
        return None, None
