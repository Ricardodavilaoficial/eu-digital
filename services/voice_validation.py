# services/voice_validation.py 
# Validações de áudio para upload de voz (V2)

import io, re, time, struct, logging
from werkzeug.utils import secure_filename

try:
    from mutagen import File as MutagenFile
except Exception:
    MutagenFile = None

# MIMEs base aceitos (sem parâmetros)
ALLOWED_MIMES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    # novos formatos comuns em celular/navegador
    "audio/ogg",
    "audio/opus",
    "application/ogg",
    "audio/webm",
    "audio/x-m4a",
    "audio/aac",
    "audio/mp4",
}

# Tamanho máximo (aumentei um pouco para dar folga, se quiser volta pra 25MB)
MAX_BYTES = 50 * 1024 * 1024  # 50 MB


def ensure_audio_present(fileobj):
    """Garante que veio um arquivo no campo 'voz'."""
    if not fileobj:
        raise ValueError("missing_audio")
    return fileobj


def validate_mime(m):
    """Valida o MIME permitido (tolerante a parâmetros tipo '; codecs=opus')."""
    mt_raw = (m or "").lower().strip()
    if not mt_raw:
        raise ValueError("unsupported_media_type")

    # remove parâmetros, ex.: 'audio/ogg; codecs=opus' -> 'audio/ogg'
    base = mt_raw.split(";", 1)[0].strip()

    # normaliza alguns aliases
    if base in ("audio/wav", "audio/x-wav"):
        base = "audio/wav"
    elif base in ("audio/mpeg", "audio/mp3"):
        base = "audio/mpeg"
    elif base in ("audio/ogg", "audio/opus", "application/ogg", "audio/webm"):
        base = "audio/ogg"
    elif base in ("audio/x-m4a", "audio/aac", "audio/mp4"):
        base = "audio/mp4"

    # se estiver na lista, beleza
    if base in ALLOWED_MIMES:
        return base

    # fallback tolerante: qualquer audio/* a gente aceita,
    # porque o backend ainda vai tentar processar e rejeitar se for bizarro.
    if base.startswith("audio/"):
        logging.info("[voice_validation] MIME genérico aceito: %s", base)
        return base

    # qualquer outra coisa → 415
    raise ValueError("unsupported_media_type")


def validate_size(n):
    """Valida tamanho em bytes."""
    if n == 0:
        raise ValueError("empty_audio")
    if n > MAX_BYTES:
        raise OverflowError("payload_too_large")


def sanitize_filename(name: str) -> str:
    """Gera um nome seguro e único para o arquivo (timestamp)."""
    name = secure_filename(name or "voz")
    if not name:
        name = "voz"
    if "." not in name:
        name += ".mp3"
    base, ext = name.rsplit(".", 1)
    base = re.sub(r"[^a-zA-Z0-9._-]", "_", base)[:64] or "voz"
    ext = re.sub(r"[^a-zA-Z0-9]", "", ext)[:8] or "mp3"
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"{base}-{ts}.{ext.lower()}"


def _probe_wav_duration(buf: bytes):
    """Leitura mínima de cabeçalho WAV para estimar duração (fallback)."""
    if len(buf) < 44:
        return -1
    try:
        data_sz = struct.unpack("<I", buf[40:44])[0]
        byte_rate = struct.unpack("<I", buf[28:32])[0]
        return float(data_sz) / float(byte_rate) if byte_rate > 0 else -1
    except Exception:
        return -1


def probe_duration(buf: bytes, mimetype: str) -> float:
    """Retorna duração em segundos ou -1 se não conseguir determinar."""
    # Preferência: Mutagen (MP3/WAV/OGG/WEBM/etc, quando suportar)
    if MutagenFile is not None:
        try:
            audio = MutagenFile(io.BytesIO(buf), easy=False)
            if audio and getattr(audio, "info", None):
                d = getattr(audio.info, "length", None)
                if d and d > 0:
                    return float(d)
        except Exception:
            pass

    # Fallback simples para WAV
    base = (mimetype or "").split(";", 1)[0].strip().lower()
    if base in {"audio/wav", "audio/x-wav"}:
        return _probe_wav_duration(buf)

    return -1
