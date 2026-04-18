import os
import io
import uuid
import logging
import traceback
from typing import Optional

from flask import Blueprint, request, send_file, jsonify

# === Imports tolerantes (evitam quebrar o boot do app) =======================
try:
    import services.audio_processing as audio_processing  # expõe: transcrever_audio_google, transcribe_audio_bytes, ...
except Exception:
    audio_processing = None

# Preferimos a API unificada (speak_bytes); mantemos fallback p/ função antiga
try:
    import services.text_to_speech as tts  # expõe: speak_bytes(...) -> (bytes, mime) | None
except Exception:
    tts = None

try:
    # Página HTML simples (debug/local). Se não existir, devolvemos texto plain.
    from interfaces.web_interface import html_index
except Exception:
    html_index = None

# ============================================================================

routes = Blueprint("routes", __name__)
log = logging.getLogger(__name__)


_obter_resposta_openai = None
_obter_resposta_openai_loaded = False


def _get_obter_resposta_openai():
    global _obter_resposta_openai, _obter_resposta_openai_loaded
    if _obter_resposta_openai_loaded:
        return _obter_resposta_openai
    try:
        from services.openai.openai_handler import obter_resposta_openai as _handler
        _obter_resposta_openai = _handler
    except Exception:
        _obter_resposta_openai = None
    _obter_resposta_openai_loaded = True
    return _obter_resposta_openai


def _guess_mime(filename: str, fallback: str = "application/octet-stream") -> str:
    """Heurística simples de MIME por extensão + cabeçalho do Flask."""
    name = (filename or "").lower()
    if name.endswith(".webm"):
        return "audio/webm"
    if name.endswith(".ogg") or name.endswith(".oga"):
        return "audio/ogg"
    if name.endswith(".mp3"):
        return "audio/mpeg"
    if name.endswith(".wav"):
        return "audio/wav"
    return fallback


def _transcrever(audio_bytes: bytes, mime: str, idioma: str = "pt-BR") -> str:
    """Encapsula a transcrição com a camada de compatibilidade."""
    if not audio_processing or not audio_bytes:
        return ""
    # Preferimos a função por bytes (faz conversão p/ WAV 16k quando possível)
    for fname in ("transcribe_audio_bytes", "stt_transcribe", "speech_to_text"):
        f = getattr(audio_processing, fname, None)
        if callable(f):
            try:
                return (f(audio_bytes, mime_type=mime, language=idioma) or "").strip()
            except TypeError:
                # Assinatura diferente — tenta com menos args
                try:
                    return (f(audio_bytes) or "").strip()
                except Exception:
                    pass
            except Exception:
                log.info("[STT] %s falhou; tentando próximo", fname, exc_info=True)

    # Compatibilidade com a função esperada originalmente por alguns trechos
    f_compat = getattr(audio_processing, "transcrever_audio_google", None)
    if callable(f_compat):
        try:
            # Essa função aceita bytes OU caminho de arquivo. Aqui passamos bytes.
            return (f_compat(audio_bytes, idioma=idioma) or "").strip()
        except Exception:
            log.info("[STT] transcrever_audio_google falhou", exc_info=True)

    return ""


def _responder_texto(texto_do_cliente: str) -> str:
    """Gera resposta textual (padrão) a partir da entrada do usuário."""
    obter_resposta_openai = _get_obter_resposta_openai()
    if obter_resposta_openai:
        try:
            return (obter_resposta_openai(texto_do_cliente) or "").strip()
        except Exception:
            log.info("[NLU] obter_resposta_openai falhou; usando fallback", exc_info=True)
    # Fallback simples e barato
    texto = (texto_do_cliente or "").strip()
    if not texto:
        return "Oi! Recebi seu áudio. Como posso te ajudar hoje?"
    return f"Você disse: “{texto}”. Posso te passar preços, endereço/horários ou já marcar um horário."


def _tts(texto: str, prefer_ogg: bool = True) -> Optional[tuple]:
    """
    TTS unificado: tenta services.text_to_speech.speak_bytes(); se não houver, tenta
    função legada gerar_audio_elevenlabs() quando presente.
    Retorna (bytes, mime) ou None.
    """
    if not texto:
        return None

    # 1) API unificada (preferida)
    if tts:
        speak = getattr(tts, "speak_bytes", None)
        if callable(speak):
            try:
                fmt = "audio/ogg" if prefer_ogg else "audio/mpeg"
                out = speak(texto, format=fmt)
                if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], (bytes, bytearray)):
                    return (bytes(out[0]), str(out[1]))
            except Exception:
                log.info("[TTS] speak_bytes falhou; tentando fallback", exc_info=True)

        # 2) Fallback Eleven labs legado (gera arquivo em disco)
        gerar = getattr(tts, "gerar_audio_elevenlabs", None)
        if callable(gerar):
            try:
                path = gerar(texto)
                if path and os.path.exists(path):
                    # vamos ler os bytes para devolver via streaming (e apagar o arquivo temporário)
                    with open(path, "rb") as f:
                        data = f.read()
                    try:
                        os.remove(path)
                    except Exception:
                        pass
                    return (data, "audio/mpeg")
            except Exception:
                log.info("[TTS] gerar_audio_elevenlabs falhou", exc_info=True)

    return None


# -----------------------------------------------------------------------------
# Rotas
# -----------------------------------------------------------------------------
@routes.route("/", methods=["GET"])
def index():
    if callable(html_index):
        return html_index()
    return "<h1>MEI Robô — API</h1><p>Use POST /audio para enviar um áudio (form-data: audio).</p>", 200


@routes.route("/audio", methods=["POST"])
def processar_audio():
    """
    Recebe um arquivo de áudio via form-data (campo 'audio'), transcreve (Google STT),
    gera uma resposta textual e (se possível) devolve TTS da resposta.
    """
    try:
        log.info("📥 POST /audio recebido | ct=%s | mimetype=%s", request.content_type, request.mimetype)

        if "audio" not in request.files:
            return jsonify({"ok": False, "error": "Campo 'audio' não encontrado (form-data)."}), 400

        fs = request.files["audio"]
        if not fs or not fs.filename:
            return jsonify({"ok": False, "error": "Arquivo de áudio inválido."}), 400

        # Lê bytes e determina MIME
        audio_bytes = fs.read() or b""
        if not audio_bytes:
            return jsonify({"ok": False, "error": "Arquivo de áudio vazio."}), 400

        mime = fs.mimetype or _guess_mime(fs.filename, "audio/ogg")
        log.info("🔎 arquivo=%s | size=%d | mime=%s", fs.filename, len(audio_bytes), mime)

        # STT (Google)
        texto = _transcrever(audio_bytes, mime)
        log.info("📝 Transcrição: %r", texto[:240] if texto else "")

        if not texto:
            return jsonify({"ok": False, "error": "Não foi possível transcrever o áudio."}), 400

        # Gera resposta textual
        resposta_txt = _responder_texto(texto)
        log.info("🤖 Resposta: %r", resposta_txt[:240] if resposta_txt else "")

        # Tenta TTS; se indisponível, devolvemos JSON com o texto
        tts_out = _tts(resposta_txt, prefer_ogg=True)
        if tts_out:
            audio_resp, mime_resp = tts_out
            # streama os bytes (sem salvar em disco)
            ext = ".ogg" if (mime_resp or "").lower().startswith("audio/ogg") else ".mp3"
            filename = f"resposta-{uuid.uuid4().hex}{ext}"
            return send_file(
                io.BytesIO(audio_resp),
                mimetype=mime_resp or "audio/mpeg",
                as_attachment=False,
                download_name=filename,
                max_age=0,
                conditional=False,
                etag=False,
                last_modified=None,
            )

        # Fallback: sem TTS disponível — devolve JSON
        return jsonify({"ok": True, "transcricao": texto, "resposta": resposta_txt, "audio": None}), 200

    except Exception as e:
        log.exception("[/audio] erro: %s", e)
        return jsonify({"ok": False, "error": f"Erro interno: {str(e)}"}), 500


@routes.route("/ping", methods=["GET"])
def ping():
    return jsonify(ok=True, service="routes", version="v1"), 200
