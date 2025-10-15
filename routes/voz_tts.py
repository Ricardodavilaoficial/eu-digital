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
import os, logging, requests

voz_tts_bp = Blueprint("voz_tts_bp", __name__)
ELEVEN_TTS_URL_TEMPLATE = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

def _env_true(v: str) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "y", "on")

@voz_tts_bp.route("/tts", methods=["POST"], strict_slashes=False)
def tts_post():
    # Feature flag opcional (default habilitado)
    if not _env_true(os.environ.get("VOZ_V2_ENABLED", "true")):
        return jsonify({"ok": False, "error": "feature_disabled"}), 403

    api_key = os.environ.get("ELEVEN_API_KEY") or ""
    if not api_key:
        return jsonify({"ok": False, "error": "missing_env", "detail": "ELEVEN_API_KEY is required"}), 500

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

    # Voice id (prioridade: body -> query -> env)
    voice_id = (data.get("voice_id") or request.args.get("voice_id") or os.environ.get("ELEVEN_VOICE_ID") or "").strip()
    if not voice_id:
        return jsonify({"ok": False, "error": "missing_voice_id"}), 400

    # Parâmetros opcionais
    model_id = (data.get("model") or os.environ.get("ELEVEN_TTS_MODEL") or "eleven_multilingual_v2").strip()
    opt_latency = (data.get("optimize_streaming_latency") or os.environ.get("ELEVEN_TTS_OPT_LAT", "0")).strip()

    headers = {
        "xi-api-key": api_key,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": float(os.environ.get("ELEVEN_VOICE_STABILITY", "0.5")),
            "similarity_boost": float(os.environ.get("ELEVEN_VOICE_SIMILARITY", "0.75")),
            "style": float(os.environ.get("ELEVEN_VOICE_STYLE", "0.0")),
            "use_speaker_boost": _env_true(os.environ.get("ELEVEN_VOICE_SPK_BOOST", "true")),
        },
    }
    try:
        opt_int = int(opt_latency)
        if opt_int in (0, 1, 2, 3, 4):
            payload["optimize_streaming_latency"] = opt_int
    except Exception:
        pass

    url = ELEVEN_TTS_URL_TEMPLATE.format(voice_id=voice_id)

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=(5, 30), stream=True)
    except requests.RequestException as e:
        logging.exception("ElevenLabs request failed: %s", e)
        return jsonify({"ok": False, "error": "upstream_error", "detail": str(e)}), 502

    if r.status_code != 200:
        try:
            detail = r.json()
        except Exception:
            detail = r.text[:500]
        return jsonify({"ok": False, "error": "upstream_non_200", "status": r.status_code, "detail": detail}), 502

    def generate():
        try:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        finally:
            r.close()

    headers_resp = {
        "Content-Type": "audio/mpeg",
        "Cache-Control": "no-store",
        "X-Voice-Id": voice_id,
        "X-Model-Id": model_id,
    }
    return Response(generate(), headers=headers_resp, status=200)

@voz_tts_bp.route("/tts/ping", methods=["GET"], strict_slashes=False)
def tts_ping():
    return jsonify({"ok": True, "service": "voz_tts", "enabled": _env_true(os.environ.get("VOZ_V2_ENABLED", "true"))})
