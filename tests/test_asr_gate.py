"""Voice-quality gates: segment energy floor, VAD config, filler chime, streaming.

`audio.py` loads the Opus shared library at import time, which pytest cannot see
on this Mac (sherpa-onnx is importable). `opuslib` is stubbed before the import:
the functions under test (RMS gate, chime, routing decision) are pure
Python/numpy and never touch Opus, sherpa-onnx or a model.

Thresholds are locked against the numbers measured on this board on 2026-10-27
(see the comment block in src/audio.py).
"""
import ast
import asyncio
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Import-time only: audio.py constructs opuslib codecs inside methods, never at
# module level. Stub it so importing does not require the native library.
sys.modules.setdefault("opuslib", types.ModuleType("opuslib"))

import audio  # noqa: E402
import session as voice_session  # noqa: E402

RATE = 16000
CFG = yaml.safe_load((ROOT / "config.yaml").read_text())


def square(amplitude: float, seconds: float, dtype=np.float32) -> np.ndarray:
    """±amplitude square wave: its RMS is exactly `amplitude`."""
    n = int(RATE * seconds)
    wave = np.empty(n, dtype=np.float32)
    wave[0::2] = amplitude
    wave[1::2] = -amplitude
    if dtype is np.int16:
        return (wave * 32768.0).astype(np.int16)
    return wave


# --- energy gate -------------------------------------------------------------

def test_silence_dropped():
    assert audio.is_noise_segment(np.zeros(int(RATE * 1.5), dtype=np.float32))


def test_low_long_dropped():
    # Digital silence / channel noise (new floor 0.0025 after task-26 step 2).
    assert audio.is_noise_segment(square(0.0015, 5.55))


def test_low_1_2s_dropped():
    assert audio.is_noise_segment(square(0.0012, 1.2))


def test_normal_speech_kept():
    # Real speech segments measured 0.0162-0.0272 rms.
    assert not audio.is_noise_segment(square(0.0181, 1.81))
    assert not audio.is_noise_segment(square(0.0272, 0.62))


def test_quiet_short_wake_kept():
    # Wake word: 0.0102 rms / 0.88 s. It passes the gate and is then dropped by
    # the wake-only text filter, so the two layers stay independent.
    assert not audio.is_noise_segment(square(0.0102, 0.88))


def test_short_blip_dropped():
    assert audio.is_noise_segment(square(0.03, 0.15))


def test_floor_boundary():
    # Quietest measured human segment is 0.0053; the floor sits below it.
    assert not audio.is_noise_segment(square(0.0053, 1.5))
    assert not audio.is_noise_segment(square(0.003, 1.5))
    assert audio.is_noise_segment(square(0.002, 1.5))


def test_int16_samples_supported():
    assert audio.is_noise_segment(square(0.0015, 2.0, dtype=np.int16))


# --- filler chime ------------------------------------------------------------

def test_filler_chime_limit():
    assert voice_session.FILLER_CHIME_MS == 160
    assert voice_session.FILLER_CHIME_MAX_MS == 300
    assert voice_session.FILLER_CHIME_MS <= voice_session.FILLER_CHIME_MAX_MS


def test_filler_chime_pcm():
    pcm = voice_session._chime_pcm(RATE)
    assert pcm.dtype == np.int16
    assert len(pcm) == RATE * voice_session.FILLER_CHIME_MS // 1000   # 2560 = 160 ms
    assert np.any(pcm) and np.max(np.abs(pcm)) <= int(0.13 * 32767)
    assert pcm[0] == 0 and pcm[-1] == 0                                # click-free edges


def test_filler_chime_refuses_long_audio():
    with pytest.raises(ValueError):
        voice_session._chime_pcm(RATE, voice_session.FILLER_CHIME_MAX_MS + 1)


# --- sentence streaming (first-frame path) -----------------------------------

def test_stream_decision():
    # Fast route offers no tools, so DeepSeek is streamed too; the agent route
    # does not stream DeepSeek because tool_calls can arrive mid-text.
    assert voice_session.should_stream_sentences(True, "deepseek", "fast")
    assert not voice_session.should_stream_sentences(True, "deepseek", "agent")
    assert voice_session.should_stream_sentences(True, "hermes", "agent")
    assert not voice_session.should_stream_sentences(False, "hermes", "agent")


# --- wiring regressions (mutation-proof) -------------------------------------
# These exist because the pure-function tests stayed green when the call site or
# the history append was mutated by hand: the rule must actually be connected.

_SESSION_SRC = (ROOT / "src" / "session.py").read_text()


def _session_func(name: str):
    tree = ast.parse(_SESSION_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Session":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and item.name == name:
                    return item
    raise AssertionError(f"Session.{name} not found")


def _call_lines(node, func_name: str) -> list[int]:
    out = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        fn = n.func
        if (isinstance(fn, ast.Name) and fn.id == func_name) or \
                (isinstance(fn, ast.Attribute) and fn.attr == func_name):
            out.append(n.lineno)
    return out


def test_noise_gate_is_wired_before_asr():
    fn = _session_func("_handle_turn")
    gate = _call_lines(fn, "is_noise_segment")
    # run_in_executor takes `self.asr.transcribe` as a reference, not a call.
    asr = [n.lineno for n in ast.walk(fn)
           if isinstance(n, ast.Attribute) and n.attr == "transcribe"]
    assert gate, "is_noise_segment call removed from _handle_turn"
    assert asr, "asr.transcribe call missing"
    assert min(gate) < min(asr), "gate must run before ASR"

    # The gate now lands in `dropped = is_noise_segment(...)` and the return is
    # guarded by `if dropped:`; both must still sit before the ASR call.
    dropped_assign = any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "dropped" for t in node.targets)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "is_noise_segment"
        for node in ast.walk(fn))
    assert dropped_assign, "gate result is not bound to `dropped`"
    gate_return = any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Name) and node.test.id == "dropped"
        and any(isinstance(x, ast.Return) for x in ast.walk(node))
        for node in ast.walk(fn))
    assert gate_return, "noise gate must return before ASR runs"


def test_history_appended_once():
    fn = _session_func("_run_turn")
    appends = [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Attribute)
        and n.target.attr == "history"
    ]
    assert len(appends) == 1, f"history must be appended once, found {appends}"
    spoken_ifs = [n for n in ast.walk(fn)
                  if isinstance(n, ast.If) and isinstance(n.test, ast.Name)
                  and n.test.id == "spoken"]
    assert spoken_ifs, "streaming branch not found"
    for node in spoken_ifs:
        start = node.lineno
        end = max(getattr(x, "lineno", start) for x in ast.walk(node))
        assert not start <= appends[0] <= end, \
            "history append must not live inside the `if spoken:` branch"


# --- chime must not reach the subtitle bar -----------------------------------

class _FakeWs:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


class _EmptyCodec:
    def frames(self, pcm):
        return []


def _bare_session():
    s = voice_session.Session.__new__(voice_session.Session)
    s.ws = _FakeWs()
    s.session_id = "test"
    s.log_prefix = "[test]"
    s.cfg = CFG
    s.codec = _EmptyCodec()
    s._speak_lock = asyncio.Lock()
    s.speaking = False
    s._first_audio_at = None
    s._reply_ready = False
    s.alive = True
    s._speak_started_at = 0.0
    s._barge_ms = 0
    s._barge_quiet_ms = 0
    s._barge_onset_at = None
    s._echo_sub = []
    s._echo_frame = []
    s._echo_recent = []
    s.thinking_face = ""          # these tests cover the legacy chime path
    s.segment_recorder = None
    return s


def _states(sent) -> list[str]:
    out = []
    for raw in sent:
        msg = json.loads(raw) if isinstance(raw, str) else raw
        out.append(msg.get("state") or msg.get("type"))
    return out


async def test_chime_has_no_subtitle_line():
    s = _bare_session()
    pcm = np.zeros(RATE // 10, dtype=np.int16)
    await s._speak("chime 160 ms", pcm, 0.0, label="filler", announce=False)
    assert _states(s.ws.sent) == ["start", "stop"]
    assert "chime" not in "".join(str(m) for m in s.ws.sent)


async def test_spoken_text_still_announced():
    s = _bare_session()
    pcm = np.zeros(RATE // 10, dtype=np.int16)
    await s._speak("你好。", pcm, 0.0)
    assert _states(s.ws.sent) == ["start", "sentence_start", "stop"]


def test_chime_ms_is_clamped(capsys):
    assert voice_session.filler_chime_ms_for({"filler_chime_ms": 1000}) == 300
    assert "clamped" in capsys.readouterr().out
    # 10 ms passed the upper-bound clamp but _chime_pcm() used to reject it and
    # crash Session.__init__ -> whole device silent. Must disable, not raise.
    assert voice_session.filler_chime_ms_for({"filler_chime_ms": 10}) == 0
    assert "disabled" in capsys.readouterr().out
    # A typo such as "160ms" must fall back to the default, not raise.
    assert voice_session.filler_chime_ms_for({"filler_chime_ms": "160ms"}) == 160
    assert "not a number" in capsys.readouterr().out
    assert voice_session.filler_chime_ms_for({"filler_chime_ms": 0}) == 0
    assert voice_session.filler_chime_ms_for({}) == 160
    assert voice_session.filler_chime_ms_for({"filler_chime_ms": -5}) == 0


async def test_filler_path_passes_announce_false(monkeypatch, capsys):
    """The real call site must keep the chime out of the subtitle bar.

    Directly testing `_speak(..., announce=False)` did not catch a mutation that
    removed `announce=False` from `_filler_after`; this drives the real path.
    """
    s = _bare_session()
    s._reply_ready = False
    s._first_audio_at = None
    s.alive = True
    s._filler_pcm = np.zeros(RATE * voice_session.FILLER_CHIME_MS // 1000,
                             dtype=np.int16)
    calls = []

    async def fake_speak(text, pcm, t0, label="tts", announce=True):
        calls.append({"text": text, "label": label, "announce": announce})

    monkeypatch.setattr(s, "_speak", fake_speak)
    await s._filler_after(0.0, 0.0)
    assert len(calls) == 1
    assert calls[0]["announce"] is False
    assert calls[0]["label"] == "filler"
    assert "chime" in calls[0]["text"]
    assert "chime" in capsys.readouterr().out        # server-side log kept


# --- shipped config ----------------------------------------------------------

def test_vad_config_tightened():
    assert CFG["vad"]["min_speech"] == 0.25
    assert CFG["vad"]["min_silence"] == 0.5     # already below rui's 600 ms


def test_filler_config_silent():
    # task-17: the default delay mask is the thinking face; the chime is opt-in.
    conv = CFG["conversation"]
    assert conv["filler_chime_ms"] == 0
    assert conv["thinking_face"] == "thinking"
    assert conv["filler_phrases"] == []          # no startup TTS for filler
