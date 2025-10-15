# routes/voz_stt_bp.py
# Blueprint: STT via Google Cloud Speech (POST /api/voz/stt)
# - Aceita audio/mpeg (MP3) e audio/wav (LINEAR16) via body binário
# - Sem dependência de Storage/Firestore
# - Falha elegante se biblioteca não estiver instalada

from flask import Blueprint, request, jsonify
import os

voz_stt_bp = Blueprint("voz_stt_bp", __name__)

def _env_true(v: str) -> bool:
    return str(v or "").strip().lower() in ("1","true","yes","y","on")

@voz_stt_bp.route("/api/voz/stt", methods=["POST", "OPTIONS"])
def stt_post():
    if request.method == "OPTIONS":
        # CORS preflight simples
        return ("", 204)

    # Feature flag opcional (reusa VOZ_V2_ENABLED)
    if not _env_true(os.environ.get("VOZ_V2_ENABLED", "true")):
        return jsonify({"ok": False, "error": "feature_disabled"}), 403

    # Conteúdo binário obrigatório
    raw = request.get_data(cache=False, as_text=False)
    if not raw or len(raw) < 100:
        return jsonify({"ok": False, "error": "empty_audio"}), 400

    ctype = (request.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    # Mapeia encoding para Google STT
    if ctype == "audio/mpeg" or ctype == "audio/mp3":
        encoding = "MP3"
        sample_rate_hz = None  # deixa o Google inferir
    elif ctype == "audio/wav" or ctype == "audio/x-wav":
        encoding = "LINEAR16"
        sample_rate_hz = None
    else:
        # aceita mesmo assim tentando MP3 como fallback
        encoding = "MP3"
        sample_rate_hz = None

    language_code = os.environ.get("STT_LANGUAGE_CODE", "pt-BR")

    # Importa a lib de STT dentro do handler para falhar de forma controlada
    try:
        from google.cloud import speech
    except Exception as e:
        return jsonify({"ok": False, "error": "speech_lib_missing", "detail": str(e)}), 501

    try:
        client = speech.SpeechClient()  # credenciais já vêm do gcp_creds/ADC/inline
        audio = speech.RecognitionAudio(content=raw)
        cfg_kwargs = dict(
            encoding=getattr(speech.RecognitionConfig.AudioEncoding, encoding, speech.RecognitionConfig.AudioEncoding.MP3),
            language_code=language_code,
            enable_automatic_punctuation=True,
        )
        if sample_rate_hz:
            cfg_kwargs["sample_rate_hertz"] = sample_rate_hz

        config = speech.RecognitionConfig(**cfg_kwargs)
        resp = client.recognize(config=config, audio=audio)

        # Consolida as alternativas
        transcript = ""
        confidence = None
        for result in resp.results:
            if result.alternatives:
                alt = result.alternatives[0]
                transcript += (alt.transcript or "")
                if confidence is None:
                    confidence = alt.confidence

        return jsonify({"ok": True, "transcript": transcript.strip(), "confidence": confidence})
    except Exception as e:
        return jsonify({"ok": False, "error": "stt_failed", "detail": str(e)}), 500

@voz_stt_bp.route("/api/voz/stt/ping", methods=["GET"])
def stt_ping():
    return jsonify({"ok": True, "service": "voz_stt"})
