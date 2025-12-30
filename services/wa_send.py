# services/wa_send.py
import os
import json
import logging
import requests
import re
from typing import List, Tuple

GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v23.0")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID") or os.getenv("PHONE_NUMBER_ID")

# -----------------------------------------------------------------------------
# Helpers de telefone (usa services.phone_utils se existir; senão, fallback)
# -----------------------------------------------------------------------------
_DIGITS_RE = re.compile(r"\D+")

def _only_digits_local(s: str) -> str:
    return _DIGITS_RE.sub("", s or "")

def _ensure_cc_55(d: str) -> str:
    d = _only_digits_local(d)
    if d.startswith("00"):
        d = d[2:]
    if not d.startswith("55"):
        d = "55" + d
    return d

def _br_split(msisdn: str) -> Tuple[str, str, str]:
    d = _ensure_cc_55(msisdn)
    cc = d[:2]
    rest = d[2:]
    ddd = rest[:2] if len(rest) >= 10 else rest[:2]
    local = rest[2:]
    return cc, ddd, local

def _br_equivalence_key_local(msisdn: str) -> str:
    cc, ddd, local = _br_split(msisdn)
    local8 = _only_digits_local(local)[-8:]
    return f"{cc}{ddd}{local8}"

def _br_candidates_local(msisdn: str) -> List[str]:
    """
    Retorna candidatos E.164 sem '+' (ex.: '5511985648608'):
    - com 9 e sem 9 para celulares, quando aplicável
    - mantém apenas 55 + DDD(2) + local(8/9)
    """
    cc, ddd, local = _br_split(msisdn)
    local_digits = _only_digits_local(local)
    cands = set()
    if len(local_digits) >= 9 and local_digits[0] == "9":
        with9 = f"{cc}{ddd}{local_digits}"
        without9 = f"{cc}{ddd}{local_digits[1:]}"
        cands.add(with9)
        cands.add(without9)
    elif len(local_digits) == 8:
        without9 = f"{cc}{ddd}{local_digits}"
        with9 = f"{cc}{ddd}9{local_digits}"
        cands.add(without9)
        cands.add(with9)
    else:
        cands.add(f"{cc}{ddd}{local_digits}")
    return [c for c in cands if len(c) in (12, 13)]

def _normalize_br_msisdn_simple(wa_id: str) -> str:
    """
    Compat: insere 9 quando detectar 55 + DDD + local(8). Mantida por legado.
    """
    if not wa_id:
        return ""
    digits = _only_digits_local(wa_id)
    if digits.startswith("55") and len(digits) == 12:
        digits = digits[:4] + "9" + digits[4:]
    return digits

# Tenta importar versão centralizada (se existir)
try:
    from services.phone_utils import br_candidates as _br_candidates_ext, br_equivalence_key as _br_eq_key_ext, digits_only as _digits_only_ext  # type: ignore
    def br_candidates(msisdn: str) -> List[str]:
        return _br_candidates_ext(msisdn)
    def br_equivalence_key(msisdn: str) -> str:
        return _br_eq_key_ext(msisdn)
    def _only_digits(s: str) -> str:
        return _digits_only_ext(s)
    logging.info("[WA][PHONE] usando services.phone_utils")
except Exception:
    def br_candidates(msisdn: str) -> List[str]:
        return _br_candidates_local(msisdn)
    def br_equivalence_key(msisdn: str) -> str:
        return _br_equivalence_key_local(msisdn)
    def _only_digits(s: str) -> str:
        return _only_digits_local(s)
    logging.info("[WA][PHONE] usando helpers locais (fallback)")

# -----------------------------------------------------------------------------
# HTTP helpers
# -----------------------------------------------------------------------------
def _graph_url(path: str) -> str:
    return f"https://graph.facebook.com/{GRAPH_VERSION}/{path}"

def _headers_json() -> dict:
    return {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}

def _has_basic_config() -> bool:
    return bool(WHATSAPP_TOKEN and PHONE_NUMBER_ID)

# -----------------------------------------------------------------------------
# Envio de TEXTO (com candidatos com/sem 9)
# -----------------------------------------------------------------------------
def send_text(to: str, body: str):
    """
    Envia texto via WhatsApp Cloud API.
    Tenta br_candidates(to) (com e sem 9) até um retornar sucesso.
    """
    if not _has_basic_config():
        logging.error("[WA][SEND_TEXT] Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID")
        return False, {"error": "missing_whatsapp_config"}

    # Gera candidatos robustos
    try:
        cands = br_candidates(to)
    except Exception:
        cands = []
    if not cands:
        cands = [_normalize_br_msisdn_simple(to)]

    # De-dup
    seen = set()
    cands = [c for c in cands if not (c in seen or seen.add(c))]

    eq_key = br_equivalence_key(to)
    url = _graph_url(f"{PHONE_NUMBER_ID}/messages")
    headers = _headers_json()

    last_resp = None
    logging.info("[WA][SEND_TEXT] to=%s eq_key=%s cands=%s", to, eq_key, cands)

    for cand in cands:
        payload = {
            "messaging_product": "whatsapp",
            "to": cand,
            "type": "text",
            "text": {"preview_url": False, "body": (body or "")[:4096]},
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=15)
            try:
                resp_json = r.json()
            except Exception:
                resp_json = {"raw": r.text[:400], "status_code": r.status_code}
            logging.info("[WA][OUT TEXT] cand=%s status=%s resp=%s", cand, r.status_code, str(resp_json)[:600])
            if r.ok:
                return True, {"used": cand, "eq_key": eq_key, "resp": resp_json}
            last_resp = {"used": cand, "eq_key": eq_key, "resp": resp_json, "status_code": r.status_code}
        except Exception as e:
            logging.exception("[WA][SEND_TEXT][ERROR] cand=%s err=%s", cand, e)
            last_resp = {"error": repr(e), "used": cand, "eq_key": eq_key}

    return False, {"tried": cands, "eq_key": eq_key, "last": last_resp}

# -----------------------------------------------------------------------------
# Envio de ÁUDIO (upload + send) com candidatos
# -----------------------------------------------------------------------------
def send_audio(to: str, audio_bytes: bytes, mime_type: str = "audio/ogg"):
    """
    Envia áudio pela Cloud API:
      1) upload binário -> media_id
      2) send message type=audio com audio.id
    Tenta candidatos com/sem 9.
    """
    if not _has_basic_config():
        logging.error("[WA][SEND_AUDIO] Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID")
        return False, {"error": "missing_whatsapp_config"}

    # Upload primeiro (independe do 'to')
    try:
        url_upload = _graph_url(f"{PHONE_NUMBER_ID}/media")
        headers_up = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
        files = {"file": ("voice.ogg", audio_bytes, (mime_type or "audio/ogg"))}
        data = {"messaging_product": "whatsapp"}
        ru = requests.post(url_upload, headers=headers_up, files=files, data=data, timeout=30)
        try:
            media_js = ru.json()
        except Exception:
            media_js = {"status_code": ru.status_code, "text": ru.text[:200]}
        media_id = (media_js or {}).get("id")
        if not media_id:
            logging.warning("[WA][AUDIO][UPLOAD_FAIL] %s", media_js)
            return False, {"error": "upload_failed", "resp": media_js}
    except Exception as e:
        logging.exception("[WA][AUDIO][UPLOAD_ERR] %s", e)
        return False, {"error": repr(e)}

    # Gera candidatos e envia a mensagem
    try:
        cands = br_candidates(to)
    except Exception:
        cands = []
    if not cands:
        cands = [_normalize_br_msisdn_simple(to)]

    seen = set()
    cands = [c for c in cands if not (c in seen or seen.add(c))]
    eq_key = br_equivalence_key(to)

    url_msg = _graph_url(f"{PHONE_NUMBER_ID}/messages")
    headers = _headers_json()

    last_resp = None
    logging.info("[WA][SEND_AUDIO] to=%s eq_key=%s cands=%s media_id=%s", to, eq_key, cands, media_id)

    for cand in cands:
        payload = {
            "messaging_product": "whatsapp",
            "to": cand,
            "type": "audio",
            "audio": {"id": media_id},
        }
        try:
            rm = requests.post(url_msg, headers=headers, json=payload, timeout=20)
            try:
                js = rm.json()
            except Exception:
                js = {"status_code": rm.status_code, "text": rm.text[:200]}
            logging.info("[WA][OUT AUDIO] cand=%s status=%s resp=%s", cand, rm.status_code, str(js)[:600])
            if rm.ok:
                return True, {"used": cand, "eq_key": eq_key, "resp": js}
            last_resp = {"used": cand, "eq_key": eq_key, "resp": js, "status_code": rm.status_code}
        except Exception as e:
            logging.exception("[WA][SEND_AUDIO][ERROR] cand=%s err=%s", cand, e)
            last_resp = {"error": repr(e), "used": cand, "eq_key": eq_key}

    return False, {"tried": cands, "eq_key": eq_key, "last": last_resp}

# -----------------------------------------------------------------------------
# Envio de ÁUDIO por LINK com candidatos
# -----------------------------------------------------------------------------
def send_audio_link(to: str, url_link: str):
    """
    Alternativa: envia áudio por link (sem upload). Útil se o TTS salvou no GCS/S3 com URL pública.
    Tenta candidatos com/sem 9.
    """
    if not _has_basic_config():
        logging.error("[WA][AUDIO_LINK] Missing WHATSAPP_TOKEN or PHONE_NUMBER_ID")
        return False, {"error": "missing_whatsapp_config"}

    try:
        cands = br_candidates(to)
    except Exception:
        cands = []
    if not cands:
        cands = [_normalize_br_msisdn_simple(to)]

    seen = set()
    cands = [c for c in cands if not (c in seen or seen.add(c))]
    eq_key = br_equivalence_key(to)

    url_msg = _graph_url(f"{PHONE_NUMBER_ID}/messages")
    headers = _headers_json()

    last_resp = None
    logging.info("[WA][AUDIO_LINK] to=%s eq_key=%s cands=%s link=%s", to, eq_key, cands, url_link)

    for cand in cands:
        payload = {
            "messaging_product": "whatsapp",
            "to": cand,
            "type": "audio",
            "audio": {"link": url_link},
        }
        try:
            r = requests.post(url_msg, headers=headers, json=payload, timeout=20)
            try:
                js = r.json()
            except Exception:
                js = {"status_code": r.status_code, "text": r.text[:200]}
            logging.info("[WA][OUT AUDIO_LINK] cand=%s status=%s resp=%s", cand, r.status_code, str(js)[:600])
            if r.ok:
                return True, {"used": cand, "eq_key": eq_key, "resp": js}
            last_resp = {"used": cand, "eq_key": eq_key, "resp": js, "status_code": r.status_code}
        except Exception as e:
            logging.exception("[WA][AUDIO_LINK][ERROR] cand=%s err=%s", cand, e)
            last_resp = {"error": repr(e), "used": cand, "eq_key": eq_key}

    return False, {"tried": cands, "eq_key": eq_key, "last": last_resp}

# -----------------------------------------------------------------------------
# Download de mídia
# -----------------------------------------------------------------------------
def fetch_media(media_id: str):
    """
    Baixa bytes de uma mídia (ex.: áudio recebido) usando o media_id.
    Retorna (bytes, mime_type) ou (None, None).
    """
    if not WHATSAPP_TOKEN:
        logging.error("[WA][FETCH_MEDIA] Missing WHATSAPP_TOKEN")
        return None, None
    try:
        # 1) Metadados (URL privada)
        info = requests.get(
            _graph_url(f"{media_id}"),
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=15
        ).json()
        media_url = info.get("url")
        if not media_url:
            logging.warning("[WA][MEDIA_INFO_FAIL] %s", info)
            return None, None

        # 2) Download binário autorizado
        r = requests.get(media_url, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"}, timeout=30)
        content_type = r.headers.get("Content-Type", "application/octet-stream")
        data = r.content or b""
        if not data:
            return None, None
        return data, content_type
    except Exception as e:
        logging.exception("[WA][FETCH_MEDIA][ERROR] %s", e)
        return None, None
# -----------------------------------------------------------------------------
# Envio por TEMPLATE (YCloud) — obrigatório fora da janela de 24h
# -----------------------------------------------------------------------------
def send_template(
    to: str,
    template_name: str,
    params: list,
    language_code: str = "pt_BR",
):
    """
    Envia template aprovado via YCloud.
    Usar SEMPRE para mensagens outbound fora da janela de 24h.
    """
    try:
        from providers.ycloud import send_template as _ycloud_send_template
    except Exception as e:
        logging.error("[WA][TEMPLATE] YCloud indisponível: %s", e)
        return False, {"error": "ycloud_not_available"}

    # normaliza telefone (mesma regra do resto do arquivo)
    try:
        cands = br_candidates(to)
    except Exception:
        cands = []

    if not cands:
        cands = [_normalize_br_msisdn_simple(to)]

    seen = set()
    cands = [c for c in cands if not (c in seen or seen.add(c))]

    last = None
    for cand in cands:
        ok, resp = _ycloud_send_template(
            to_e164=f"+{cand}",
            template_name=template_name,
            params=params,
            language_code=language_code,
        )
        logging.info("[WA][OUT TEMPLATE] cand=%s ok=%s resp=%s", cand, ok, resp)
        if ok:
            return True, {"used": cand, "resp": resp}
        last = {"used": cand, "resp": resp}

    return False, {"tried": cands, "last": last}

