"""Mute must not let the board's abort chatter disturb the listen window.

2026-10-30 log: every mute toggle was followed by a burst of `[abort] None`
(5, then 24, then 2 - 36 in total) mixed with `[listen] detect None` /
`[listen] start realtime`. With nothing running those aborts were no-ops that
still cancelled an in-flight turn when a segment was being transcribed, and the
frames dropped while muted left the barge/listen counters frozen.

Rule under test: an abort that arrives while muted AND idle is ignored; a real
abort (speaking, or a turn in flight) still stops it; the first frame after
unmuting starts a clean listen window.
"""
import asyncio
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

sys.modules.setdefault("opuslib", types.ModuleType("opuslib"))

import mute  # noqa: E402
import session as voice_session  # noqa: E402

RATE = 16000
CFG = {
    "audio": {"sample_rate": RATE, "frame_ms": 60, "channels": 1},
    "llm": {"provider": "deepseek", "model": "fake",
            "routing": {"enabled": False}, "max_tool_rounds": 1,
            "device_tools": False, "stream_tts": False},
    "conversation": {"thinking_face": "", "cue_restore_face": "",
                     "filler_chime_ms": 0, "barge_in": True,
                     "filler_phrases": []},
    "safety": {"confirm_tools": []},
}


class FakeWs:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


class FakeAsr:
    def __init__(self, text="几点了"):
        self.text = text

    def transcribe(self, seg, rate):
        return self.text


class FakeTts:
    async def synth(self, text):
        return np.zeros(8, dtype=np.int16), RATE


class FakeLlm:
    provider = "deepseek"
    model = "fake"


class CountingVad:
    def __init__(self):
        self.frames = 0

    def accept_waveform(self, samples):
        self.frames += 1

    def empty(self) -> bool:
        # No segment ever closes: these tests are about frames reaching VAD.
        return True


def make_session(tmp_path, *, muted=False, asr_text="几点了"):
    state = mute.MuteState(tmp_path / "mute.json")
    state.set_muted(muted)
    session = voice_session.Session(FakeWs(), CFG, codec=None, tts=FakeTts(),
                                    asr=FakeAsr(asr_text), llm=FakeLlm(),
                                    mute=state)
    session.codec = types.SimpleNamespace(
        decode=lambda frame: np.zeros(960, dtype=np.int16))
    return session, state


async def abort(session):
    await session._on_json(json.dumps({"type": "abort"}), CountingVad())


def messages(ws):
    out = []
    for raw in ws.sent:
        out.append(json.loads(raw) if isinstance(raw, str) else raw)
    return out


async def test_muted_and_idle_abort_is_ignored(tmp_path, capsys):
    session, state = make_session(tmp_path, muted=True)
    session.speaking = False
    session.turn = None

    async def explode():
        raise AssertionError("_interrupt must not run for an idle muted abort")

    session._interrupt = explode
    await abort(session)

    assert session.speaking is False and session.turn is None
    assert "[abort] ignored while muted and idle" in capsys.readouterr().out


async def test_muted_abort_still_stops_speech(tmp_path):
    session, state = make_session(tmp_path, muted=True)
    session.speaking = True
    await abort(session)
    assert session.speaking is False
    assert messages(session.ws)[-1]["state"] == "stop"


async def test_muted_abort_still_cancels_a_running_turn(tmp_path):
    session, state = make_session(tmp_path, muted=True)
    session.turn = asyncio.create_task(asyncio.sleep(5))
    await abort(session)
    await asyncio.sleep(0)
    assert session.turn.cancelled() is True


async def test_unmute_resets_the_listen_window(tmp_path, capsys):
    session, state = make_session(tmp_path, muted=True)
    vad = CountingVad()
    await session._on_audio(b"frame", vad)
    assert session._muted_seen is True
    assert vad.frames == 0, "muted frames must not reach VAD"

    state.set_muted(False)
    await session._on_audio(b"frame", vad)

    assert session._muted_seen is False
    assert vad.frames == 1
    assert "[listen] reset after mute" in capsys.readouterr().out
    assert session._first_audio_at is None


async def test_first_turn_after_unmute_completes(tmp_path, monkeypatch):
    session, state = make_session(tmp_path, muted=True)
    vad = CountingVad()
    await session._on_audio(b"frame", vad)
    state.set_muted(False)
    await session._on_audio(b"frame", vad)

    ran = []

    async def fake_run_turn(t0, text):
        ran.append(text)

    monkeypatch.setattr(session, "_run_turn", fake_run_turn)
    seg = np.full(int(RATE * 0.8), 3000, dtype=np.int16)
    await session._handle_turn(seg)

    assert ran == ["几点了"]
    assert any(m.get("type") == "stt" for m in messages(session.ws))
