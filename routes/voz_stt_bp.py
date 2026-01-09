# routes/voz_stt_bp.py
# Blueprint: STT via Google Cloud Speech (POST /api/voz/stt)
# - Aceita audio/mpeg (MP3) e audio/wav (LINEAR16) via body binário
# - Suporta audio/ogg (OGG/OPUS) do WhatsApp
# - Sem dependência de Storage/Firestore
# - Falha elegante se biblioteca não estiver instalada
#
# Robustez v1 (2026-01):
# - transcript vazio (mesmo com 200/ok) é tratado como falha real: empty_transcript
# - retry leve para OGG_OPUS (WhatsApp): 2 tentativas com configs ligeiramente diferentes
# - limiar mínimo de bytes configurável para evitar STT em áudio curto/silêncio
#
# Obs: Mantém compatibilidade com o worker. Se ok=false, worker faz fallback humano e (quando entrada é áudio) responde em áudio.

from flask import Blueprint, request, jsonify
import os

voz_stt_bp = Blueprint("voz_stt_bp", __name__)


def _env_true(v: str) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name, default)).strip())
    except Exception:
        return default


def _content_type_base() -> str:
    return (request.headers.get("Content-Type") or "").split(";")[0].strip().lower()


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
    if not raw:
        return jsonify({"ok": False, "error": "empty_audio"}), 400

    ctype = _content_type_base()

    # WhatsApp/YCloud às vezes não manda Content-Type confiável.
    # Se for OGG, o arquivo começa com "OggS".
    if not ctype and raw[:4] == b"OggS":
        ctype = "audio/ogg"

    # Limiar de bytes (ajuda muito em áudio curtinho/silêncio; evita "empty transcript" enganoso)
    # Defaults conservadores para não quebrar: WhatsApp OGG geralmente > ~4KB
    min_bytes_default = 100
    if ctype in ("audio/ogg", "application/ogg", "audio/opus"):
        min_bytes_default = _env_int("STT_MIN_BYTES_OGG", 800)  # ajuste fino via ENV se quiser
    elif ctype in ("audio/wav", "audio/x-wav"):
        min_bytes_default = _env_int("STT_MIN_BYTES_WAV", 200)
    else:
        min_bytes_default = _env_int("STT_MIN_BYTES_GENERIC", 100)

    if len(raw) < min_bytes_default:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "too_short_or_silence",
                    "bytes": len(raw),
                    "minBytes": min_bytes_default,
                }
            ),
            400,
        )

    # Mapeia encoding para Google STT
    if ctype in ("audio/mpeg", "audio/mp3"):
        encoding = "MP3"
        sample_rate_hz = None  # deixa o Google inferir

    elif ctype in ("audio/wav", "audio/x-wav"):
        encoding = "LINEAR16"
        sample_rate_hz = None
    elif ctype in ("audio/ogg", "application/ogg", "audio/opus"):
        # WhatsApp geralmente envia voice note como OGG/OPUS
        encoding = "OGG_OPUS"
        sample_rate_hz = 48000  # tentativa 1; tentativa 2 omite isso se vier vazio
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

    # Helpers internos
    def _make_config(*, enc: str, sr: int | None, model: str | None):
        cfg_kwargs = dict(
            encoding=getattr(
                speech.RecognitionConfig.AudioEncoding,
                enc,
                speech.RecognitionConfig.AudioEncoding.MP3,
            ),
            language_code=language_code,
            enable_automatic_punctuation=True,
        )

        # WhatsApp/Opus costuma ser mono. Declarar 1 canal ajuda consistência.
        if enc == "OGG_OPUS":
            cfg_kwargs["audio_channel_count"] = 1
            cfg_kwargs["model"] = model or os.environ.get("STT_MODEL", "latest_short")

        # Guard definitivo: nunca enviar sample_rate_hertz inválido (0/"0"/None)
        supported = {8000, 12000, 16000, 24000, 48000}
        try:
            sr_i = int(sr) if sr is not None else 0
        except Exception:
            sr_i = 0

        if sr_i in supported:
            cfg_kwargs["sample_rate_hertz"] = sr_i
        else:
            # Para OPUS/OGG é melhor omitir do que mandar 0/ruim.
            cfg_kwargs.pop("sample_rate_hertz", None)

        return speech.RecognitionConfig(**cfg_kwargs)

    def _run_once(config):
        client = speech.SpeechClient()  # credenciais já vêm do ADC/inline
        audio = speech.RecognitionAudio(content=raw)

        # Para OGG/OPUS: long_running_recognize costuma ser mais estável.
        if encoding == "OGG_OPUS":
            op = client.long_running_recognize(config=config, audio=audio)
            resp = op.result(timeout=_env_int("STT_OP_TIMEOUT", 25))
        else:
            resp = client.recognize(config=config, audio=audio)

        transcript = ""
        confidence = None
        for result in resp.results:
            if result.alternatives:
                alt = result.alternatives[0]
                transcript += (alt.transcript or "")
                if confidence is None:
                    confidence = getattr(alt, "confidence", None)
        return transcript.strip(), confidence

    # Execução com retry leve (apenas para OGG/OPUS)
    attempts_meta = []
    try:
        if encoding == "OGG_OPUS":
            # Tentativa 1: sample_rate=48000 (como estava), model latest_short
            cfg1 = _make_config(enc=encoding, sr=sample_rate_hz, model=os.environ.get("STT_MODEL", "latest_short"))
            t1, c1 = _run_once(cfg1)
            attempts_meta.append({"n": 1, "sr": sample_rate_hz, "model": os.environ.get("STT_MODEL", "latest_short"), "len": len(t1)})
            if t1:
                return jsonify({"ok": True, "transcript": t1, "confidence": c1})

            # Tentativa 2: omitir sample_rate_hertz (deixar o decoder inferir pelo header OGG)
            cfg2 = _make_config(enc=encoding, sr=None, model=os.environ.get("STT_MODEL", "latest_short"))
            t2, c2 = _run_once(cfg2)
            attempts_meta.append({"n": 2, "sr": None, "model": os.environ.get("STT_MODEL", "latest_short"), "len": len(t2)})
            if t2:
                return jsonify({"ok": True, "transcript": t2, "confidence": c2})

            # (Opcional) Tentativa 3: latest_long para áudios maiores (ativar via ENV)
            if _env_true(os.environ.get("STT_RETRY_LONG", "false")):
                cfg3 = _make_config(enc=encoding, sr=None, model="latest_long")
                t3, c3 = _run_once(cfg3)
                attempts_meta.append({"n": 3, "sr": None, "model": "latest_long", "len": len(t3)})
                if t3:
                    return jsonify({"ok": True, "transcript": t3, "confidence": c3})

            # Nada transcreveu: falha real
            payload = {"ok": False, "error": "empty_transcript", "detail": "no_speech_or_too_noisy"}
            if _env_true(os.environ.get("STT_DEBUG", "false")):
                payload["debug"] = {"ctype": ctype, "bytes": len(raw), "attempts": attempts_meta}
            return jsonify(payload), 200  # 200 pra não quebrar caller; worker trata ok=false
        else:
            # MP3/WAV e outros: comportamento original
            cfg = _make_config(enc=encoding, sr=sample_rate_hz, model=None)
            t, c = _run_once(cfg)
            if not t:
                payload = {"ok": False, "error": "empty_transcript", "detail": "no_speech_or_too_noisy"}
                if _env_true(os.environ.get("STT_DEBUG", "false")):
                    payload["debug"] = {"ctype": ctype, "bytes": len(raw), "attempts": [{"n": 1, "sr": sample_rate_hz, "len": 0}]}
                return jsonify(payload), 200
            return jsonify({"ok": True, "transcript": t, "confidence": c})
    except Exception as e:
        # Nunca devolver 500 aqui: mantém o pipeline resiliente.
        # O worker trata ok=false e segue com fallback humano (e em áudio quando a entrada é áudio).
        payload = {"ok": False, "error": "stt_failed", "detail": str(e)[:160]}
        if _env_true(os.environ.get("STT_DEBUG", "false")):
            payload["detail_full"] = str(e)
            payload["debug"] = {"ctype": ctype, "bytes": len(raw), "attempts": attempts_meta}
        return jsonify(payload), 200

@voz_stt_bp.route("/api/voz/stt/ping", methods=["GET"])
def stt_ping():
    return jsonify({
        "ok": True,
        "service": "voz_stt",
        "app_tag": (os.getenv("APP_TAG") or "").strip()
    })


