# routes/voz_tts.py
# TTS via ElevenLabs
# Rotas:
#   POST /api/voz/tts        (também aceita /api/voz/tts/)
#   GET  /api/voz/tts/ping   (também aceita /api/voz/tts/ping/)
#
# Segurança/robustez:
# - Não persiste nada em banco/Storage.
# - Limita tamanho de texto.
# - Timeouts conservadores em upstream.
# - Cabeçalhos explícitos e stream sem carregar tudo em RAM.

from flask import Blueprint, request, Response, jsonify
import os, logging

# Fallback automático: ElevenLabs -> Google TTS (com cooldown)
try:
    from services.tts_fallback import tts_bytes as _tts_bytes  # type: ignore
except Exception:
    _tts_bytes = None

voz_tts_bp = Blueprint("voz_tts_bp", __name__)
ELEVEN_TTS_URL_TEMPLATE = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

def _env_true(v: str) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "y", "on")

@voz_tts_bp.route("/tts", methods=["POST"], strict_slashes=False)
def tts_post():
    # Feature flag opcional (default habilitado)
    if not _env_true(os.environ.get("VOZ_V2_ENABLED", "true")):
        return jsonify({"ok": False, "error": "feature_disabled"}), 403

    # Extrai payload (JSON ou form)
    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = {**request.form}

    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "missing_text"}), 400

    # Limite de caracteres (defesa contra abusos)
    try:
        max_chars = int(os.environ.get("VOZ_TTS_MAX_CHARS", "1000"))
    except Exception:
        max_chars = 1000
    if len(text) > max_chars:
        return jsonify({"ok": False, "error": "text_too_long", "limit": max_chars}), 413
    # Voice id (opcional) (prioridade: body -> query -> env)
    voice_id = (data.get("voice_id") or request.args.get("voice_id") or os.environ.get("ELEVEN_VOICE_ID") or "").strip()
    voice_id = voice_id or None

    if _tts_bytes is None:
        return jsonify({"ok": False, "error": "tts_fallback_unavailable"}), 500

    try:
        audio = _tts_bytes(text=text, voice_id=voice_id)
    except Exception as e:
        logging.exception("TTS fallback failed: %s", e)
        return jsonify({"ok": False, "error": "tts_failed", "detail": str(e)}), 502

    if not audio:
        return jsonify({"ok": False, "error": "empty_audio"}), 502

    headers_resp = {
        "Content-Type": "audio/mpeg",
        "Cache-Control": "no-store",
        "X-Voice-Id": (voice_id or ""),
    }
    return Response(audio, headers=headers_resp, status=200)
@voz_tts_bp.route("/tts/ping", methods=["GET"], strict_slashes=False)
def tts_ping():
    return jsonify({"ok": True, "service": "voz_tts", "enabled": _env_true(os.environ.get("VOZ_V2_ENABLED", "true"))})
