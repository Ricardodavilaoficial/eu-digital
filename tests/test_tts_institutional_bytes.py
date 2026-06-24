import os
import sys
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import services.tts_fallback as t


@contextmanager
def env_patch(values):
    old = {}
    keys = set(values.keys())
    for k in keys:
        old[k] = os.environ.get(k)
        v = values[k]
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextmanager
def func_patch(**funcs):
    old = {}
    for name, fn in funcs.items():
        old[name] = getattr(t, name)
        setattr(t, name, fn)
    try:
        yield
    finally:
        for name, fn in old.items():
            setattr(t, name, fn)


def test_mode_absent_uses_standard_google():
    telemetry = {}
    with env_patch({
        "INSTITUTIONAL_GOOGLE_TTS_MODE": None,
        "INSTITUTIONAL_GOOGLE_TTS_OWNER_CLONE_KEY": None,
    }):
        with func_patch(_tts_google=lambda **k: b"standard"):
            out = t.tts_institutional_bytes(text="oi", telemetry=telemetry)
    assert out == b"standard"
    assert telemetry["voiceMode"] == "standard"
    assert telemetry["providerEffective"] == "google"
    assert telemetry["fallbackReason"] == ""


def test_standard_uses_standard_google():
    telemetry = {}
    with env_patch({
        "INSTITUTIONAL_GOOGLE_TTS_MODE": "standard",
        "INSTITUTIONAL_GOOGLE_TTS_OWNER_CLONE_KEY": "secret",
    }):
        with func_patch(_tts_google=lambda **k: b"standard"):
            out = t.tts_institutional_bytes(text="oi", telemetry=telemetry)
    assert out == b"standard"
    assert telemetry["voiceMode"] == "standard"
    assert telemetry["providerEffective"] == "google"


def test_owner_clone_without_key_falls_back_to_standard():
    telemetry = {}
    with env_patch({
        "INSTITUTIONAL_GOOGLE_TTS_MODE": "owner_clone",
        "INSTITUTIONAL_GOOGLE_TTS_OWNER_CLONE_KEY": None,
    }):
        with func_patch(_tts_google=lambda **k: b"standard"):
            out = t.tts_institutional_bytes(text="oi", telemetry=telemetry)
    assert out == b"standard"
    assert telemetry["voiceMode"] == "owner_clone"
    assert telemetry["providerEffective"] == "google"
    assert telemetry["fallbackReason"] == "missing_owner_clone_key"


def test_owner_clone_success():
    telemetry = {}
    with env_patch({
        "INSTITUTIONAL_GOOGLE_TTS_MODE": "owner_clone",
        "INSTITUTIONAL_GOOGLE_TTS_OWNER_CLONE_KEY": "secret",
    }):
        with func_patch(
            _tts_google=lambda **k: b"standard",
            _tts_google_owner_clone=lambda **k: b"clone",
        ):
            out = t.tts_institutional_bytes(text="oi", telemetry=telemetry)
    assert out == b"clone"
    assert telemetry["voiceMode"] == "owner_clone"
    assert telemetry["providerEffective"] == "google_owner_clone"
    assert telemetry["fallbackReason"] == ""


def test_owner_clone_failure_falls_back_to_standard():
    telemetry = {}

    def fail_clone(**kwargs):
        raise RuntimeError("x")

    with env_patch({
        "INSTITUTIONAL_GOOGLE_TTS_MODE": "owner_clone",
        "INSTITUTIONAL_GOOGLE_TTS_OWNER_CLONE_KEY": "secret",
    }):
        with func_patch(
            _tts_google=lambda **k: b"standard",
            _tts_google_owner_clone=fail_clone,
        ):
            out = t.tts_institutional_bytes(text="oi", telemetry=telemetry)
    assert out == b"standard"
    assert telemetry["voiceMode"] == "owner_clone"
    assert telemetry["providerEffective"] == "google"
    assert telemetry["fallbackReason"] == "owner_clone_failed:RuntimeError"


def test_invalid_mode_falls_back_to_standard():
    telemetry = {}
    with env_patch({
        "INSTITUTIONAL_GOOGLE_TTS_MODE": "banana",
        "INSTITUTIONAL_GOOGLE_TTS_OWNER_CLONE_KEY": "secret",
    }):
        with func_patch(_tts_google=lambda **k: b"standard"):
            out = t.tts_institutional_bytes(text="oi", telemetry=telemetry)
    assert out == b"standard"
    assert telemetry["voiceMode"] == "standard"
    assert telemetry["providerEffective"] == "google"
    assert telemetry["fallbackReason"] == "invalid_mode"


def main():
    test_mode_absent_uses_standard_google()
    test_standard_uses_standard_google()
    test_owner_clone_without_key_falls_back_to_standard()
    test_owner_clone_success()
    test_owner_clone_failure_falls_back_to_standard()
    test_invalid_mode_falls_back_to_standard()
    print("test_tts_institutional_bytes ok")


if __name__ == "__main__":
    main()
