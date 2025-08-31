# routes/webhook.py
import os, json, logging, types, importlib, inspect
from flask import Blueprint, request, jsonify
from services.wa_send import send_text as _send_text, send_audio as _send_audio

bp_webhook = Blueprint("bp_webhook", __name__)
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "meirobo123")

_WA_BOT_MOD = None
_WA_BOT_LAST_ERR = None

def _load_wa_bot():
    global _WA_BOT_MOD, _WA_BOT_LAST_ERR
    if _WA_BOT_MOD and isinstance(_WA_BOT_MOD, types.ModuleType):
        return _WA_BOT_MOD
    try:
        _WA_BOT_MOD = importlib.import_module("services.wa_bot")
        _WA_BOT_LAST_ERR = None
        logging.info("[init] services.wa_bot importado")
        return _WA_BOT_MOD
    except Exception as e:
        _WA_BOT_MOD = None
        _WA_BOT_LAST_ERR = f"{type(e).__name__}: {e}"
        logging.exception("[init] erro import services.wa_bot: %s", e)
        return None

@bp_webhook.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        logging.info("[WEBHOOK][VERIFY] ok")
        return str(challenge or "OK"), 200
    logging.warning("[WEBHOOK][VERIFY] fail mode=%s token=%s", mode, token)
    return "Forbidden", 403

@bp_webhook.route("/webhook", methods=["POST"])
def receive_webhook():
    # headers úteis
    try:
        ct = request.content_type or "<none>"
        clen = request.content_length
        sig = request.headers.get("X-Hub-Signature-256")
        logging.info("[WEBHOOK][CT] %s | len=%s | has_sig256=%s", ct, clen, bool(sig))
    except Exception:
        pass

    # payload
    raw = ""
    try:
        raw = request.get_data(cache=True, as_text=True) or ""
    except Exception:
        pass

    data = {}
    if raw:
        try:
            data = json.loads(raw.lstrip("\ufeff").strip())
        except Exception:
            data = {}
    if not data:
        data = request.get_json(force=True, silent=True) or {}

    try:
        logging.info("[WEBHOOK][INCOMING] %s", json.dumps(data, ensure_ascii=False)[:1200])
    except Exception:
        logging.info("[WEBHOOK][INCOMING] <non-json>")

    # delegar
    try:
        wa_mod = _load_wa_bot()
        uid_default = os.getenv("UID_DEFAULT", "ricardo-prod-uid")
        app_tag = os.getenv("APP_TAG", "2025-08-27")

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if not wa_mod or not hasattr(wa_mod, "process_change"):
                    try:
                        msgs = value.get("messages") or []
                        if msgs and isinstance(msgs, list):
                            to = (msgs[0] or {}).get("from") or ""
                            if to:
                                _send_text(to, f"[FALLBACK] handler-indisponivel :: {app_tag}")
                    except Exception:
                        pass
                    logging.error("[HANDLER] services.wa_bot indisponível; last_error=%s", _WA_BOT_LAST_ERR)
                    continue

                # chamada compatível (com/sem send_audio_fn)
                try:
                    sig = inspect.signature(wa_mod.process_change)
                    if "send_audio_fn" in sig.parameters:
                        wa_mod.process_change(
                            value=value,
                            send_text_fn=_send_text,
                            uid_default=uid_default,
                            app_tag=app_tag,
                            send_audio_fn=_send_audio,
                        )
                    else:
                        wa_mod.process_change(value, _send_text, uid_default, app_tag)
                except TypeError:
                    wa_mod.process_change(value, _send_text, uid_default, app_tag)

        return "EVENT_RECEIVED", 200
    except Exception as e:
        logging.exception("[WEBHOOK][ERROR] %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500
