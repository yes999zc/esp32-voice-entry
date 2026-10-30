"""Volc (豆包 2.0) TTS: JSON-lines parsing, error handling, key fallback.

A local `http.server` on an ephemeral port plays the vendor endpoint; the tests
never touch the network. No model is loaded: the matcha fallback is replaced by
a sentinel in `build_tts()` tests, and the network tests construct `VolcTts`
directly.
"""
import base64
import json
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tts  # noqa: E402


def b64(pcm: np.ndarray) -> str:
    return base64.b64encode(pcm.astype(np.int16).tobytes()).decode()


@contextmanager
def fake_volc(frames, status=200):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib naming
            n = int(self.headers.get("Content-Length", 0))
            seen["headers"] = dict(self.headers)
            seen["body"] = json.loads(self.rfile.read(n))
            if status != 200:
                self.send_response(status)
                self.end_headers()
                self.wfile.write(b"boom")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            for frame in frames:
                self.wfile.write((json.dumps(frame) + "\n").encode())

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/tts", seen
    finally:
        srv.shutdown()
        srv.server_close()


def cfg(url="http://127.0.0.1:1/tts", **overrides):
    volc = {
        "base_url": url,
        "voice": "zh_female_xiaohe_uranus_bigtts",
        "resource_id": "seed-tts-2.0",
        "sample_rate": 16000,
        "timeout": 5,
    }
    volc.update(overrides)
    return {
        "provider": "volc",
        "speed": 1.0,
        "volc": volc,
        "matcha": {"model_dir": "/none", "vocoder": "/none"},
    }


async def test_pcm_accumulation_and_request():
    first = np.arange(0, 5, dtype=np.int16)
    second = np.arange(5, 12, dtype=np.int16)
    frames = [
        {"code": 0, "data": b64(first)},
        {"code": 0, "data": ""},          # heartbeat: skipped
        {"code": 0, "data": b64(second)},
        {"code": 20000000},               # completion marker (no data)
    ]
    with fake_volc(frames) as (url, seen):
        client = tts.VolcTts(cfg(url), api_key="test-key")
        pcm, rate = await client.synth("你好，测试。")

    assert rate == 16000
    assert pcm.dtype == np.int16
    assert np.array_equal(pcm, np.concatenate([first, second]))
    assert len(pcm.tobytes()) == len(first.tobytes()) + len(second.tobytes())
    assert seen["headers"]["X-Api-Key"] == "test-key"
    assert seen["headers"]["X-Api-Resource-Id"] == "seed-tts-2.0"
    assert seen["body"]["req_params"]["text"] == "你好，测试。"
    assert seen["body"]["req_params"]["speaker"] == "zh_female_xiaohe_uranus_bigtts"
    assert seen["body"]["req_params"]["audio_params"] == {
        "format": "pcm", "sample_rate": 16000}


async def test_non_ok_code_raises():
    frames = [{"code": 40000000, "message": "bad key"}]
    with fake_volc(frames) as (url, _):
        client = tts.VolcTts(cfg(url), api_key="k")
        with pytest.raises(RuntimeError, match="code=40000000"):
            await client.synth("你好")


async def test_http_error_raises():
    with fake_volc([], status=500) as (url, _):
        client = tts.VolcTts(cfg(url), api_key="k")
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await client.synth("你好")


async def test_empty_data_only_raises():
    frames = [{"code": 0, "data": ""}, {"code": 20000000}]
    with fake_volc(frames) as (url, _):
        client = tts.VolcTts(cfg(url), api_key="k")
        with pytest.raises(RuntimeError, match="no audio"):
            await client.synth("你好")


async def test_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("VOLC_API_KEY", "env-key")
    frames = [{"code": 0, "data": b64(np.zeros(4, dtype=np.int16))},
              {"code": 20000000}]
    with fake_volc(frames) as (url, seen):
        client = tts.VolcTts(cfg(url))       # no explicit key
        await client.synth("你好")
    assert seen["headers"]["X-Api-Key"] == "env-key"


async def test_stream_without_end_marker_raises():
    # Vendor closed a 200 OK stream after one data frame: half a sentence.
    frames = [{"code": 0, "data": b64(np.zeros(4, dtype=np.int16))}]
    with fake_volc(frames) as (url, _):
        client = tts.VolcTts(cfg(url), api_key="k")
        with pytest.raises(RuntimeError, match="before completion"):
            await client.synth("你好")


async def test_truncated_stream_falls_back_to_full_audio(capsys):
    frames = [{"code": 0, "data": b64(np.zeros(4, dtype=np.int16))}]
    full = np.arange(12, dtype=np.int16)

    class Local:
        async def synth(self, text):
            return full.copy(), 16000

    with fake_volc(frames) as (url, _):
        wrapped = tts.FallbackTts(tts.VolcTts(cfg(url), api_key="k"), Local())
        pcm, rate = await wrapped.synth("你好")
    assert rate == 16000
    assert np.array_equal(pcm, full)          # whole fallback reply, not 4 samples
    out = capsys.readouterr().out
    assert "before completion" in out and "falling back to matcha" in out


async def test_fallback_circuit_breaker(capsys):
    calls = {"primary": 0, "fallback": 0}

    class Broken:
        async def synth(self, text):
            calls["primary"] += 1
            raise TimeoutError("slow")

    class Local:
        async def synth(self, text):
            calls["fallback"] += 1
            return np.zeros(8, dtype=np.int16), 16000

    wrapped = tts.FallbackTts(Broken(), Local(), cooldown_s=60)
    for _ in range(4):                       # the 4 sentences of one streaming turn
        await wrapped.synth("你好")
    assert calls == {"primary": 1, "fallback": 4}
    assert capsys.readouterr().out.count("WARN volc failed") == 1


async def test_fallback_retries_after_cooldown():
    class Broken:
        def __init__(self):
            self.calls = 0

        async def synth(self, text):
            self.calls += 1
            raise TimeoutError("slow")

    class Local:
        async def synth(self, text):
            return np.zeros(1, dtype=np.int16), 16000

    broken = Broken()
    wrapped = tts.FallbackTts(broken, Local(), cooldown_s=0)
    await wrapped.synth("一")
    await wrapped.synth("二")
    assert broken.calls == 2                 # cooldown 0 -> retried next call


async def test_fallback_wrapper_on_failure(capsys):
    class Broken:
        async def synth(self, text):
            raise TimeoutError("slow")

    class Local:
        async def synth(self, text):
            return np.zeros(8, dtype=np.int16), 16000

    wrapped = tts.FallbackTts(Broken(), Local())
    pcm, rate = await wrapped.synth("你好")
    assert rate == 16000 and len(pcm) == 8
    out = capsys.readouterr().out
    assert "WARN volc failed" in out and "falling back to matcha" in out


def test_build_tts_without_key_falls_back(monkeypatch, capsys):
    monkeypatch.setattr(tts, "_env", lambda name: (_ for _ in ()).throw(
        RuntimeError(f"{name} not set")))
    sentinel = object()
    monkeypatch.setattr(tts, "_build_matcha", lambda cfg: sentinel)

    built = tts.build_tts(cfg())
    assert built is sentinel
    out = capsys.readouterr().out
    assert "WARN volc unavailable" in out and "falling back to matcha" in out


def test_env_empty_value_is_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("VOLC_API_KEY", raising=False)
    (tmp_path / ".hermes").mkdir()
    (tmp_path / ".hermes" / ".env").write_text("VOLC_API_KEY=\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with pytest.raises(RuntimeError, match="VOLC_API_KEY not set"):
        tts._env("VOLC_API_KEY")


def test_env_whitespace_value_is_missing(monkeypatch):
    monkeypatch.setenv("VOLC_API_KEY", "   ")
    monkeypatch.setattr(tts.Path, "home", lambda: Path("/nonexistent-home"))
    with pytest.raises(RuntimeError, match="VOLC_API_KEY not set"):
        tts._env("VOLC_API_KEY")


def test_build_tts_empty_key_falls_back(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("VOLC_API_KEY", raising=False)
    (tmp_path / ".hermes").mkdir()
    (tmp_path / ".hermes" / ".env").write_text("VOLC_API_KEY=\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    sentinel = object()
    monkeypatch.setattr(tts, "_build_matcha", lambda cfg: sentinel)

    built = tts.build_tts(cfg())
    assert built is sentinel
    assert "WARN volc unavailable" in capsys.readouterr().out


def test_build_tts_wraps_volc_with_fallback(monkeypatch):
    monkeypatch.setattr(tts, "_env", lambda name: "key-from-env-file")
    sentinel = object()
    monkeypatch.setattr(tts, "_build_matcha", lambda cfg: sentinel)

    built = tts.build_tts(cfg())
    assert isinstance(built, tts.FallbackTts)
    assert isinstance(built.primary, tts.VolcTts)
    assert built.fallback is sentinel
