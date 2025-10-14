# services/voice_validation.py — validações de áudio (placeholder seguro)
def validate_audio(file_path, min_seconds=60, max_mb=50, min_khz=16, max_khz=48):
    \"\"\"Devolve dict com {ok, errors[]} sem levantar exceções.\"\"\"
    return {"ok": True, "errors": []}
