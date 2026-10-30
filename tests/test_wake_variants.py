"""Wake-word variants must never become a command.

2026-10-30 log: SenseVoice turned one "你好小智" into 小智 / 小志 / 小石 / 小日.
Some segments were dropped as wake-only (looked like "no reaction"), the rest
reached the model ("你好，小石。" -> confused answer). The same segment also
contains the real question, so the gate has to look at the *whole* line and at
the segment length, not just at a prefix table.
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

# audio.py imports the Opus native library at module import time (same reason as
# tests/test_mute.py); neither the gate nor the turn path touches a live codec.
sys.modules.setdefault("opuslib", types.ModuleType("opuslib"))

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

VARIANTS = [
    ("你好，小智。", 1.4),      # exact wake, long segment (board keeps streaming)
    ("你好小志", 0.9),
    ("你好，小石。", 1.0),      # heard on the board, sent to the model before
    ("好小日。", 0.06),        # 0.06 s line from the log - fuzzy match
    ("你好小日", 0.7),
    ("好吗小智", 0.5),         # spacing/typo variant, high overlap
]

COMMANDS = [
    ("停", 0.5),
    ("别说了", 0.7),
    ("几点了", 0.6),
    ("你好，小智，今天天气怎么样", 2.2),   # wake word + real question
]


def test_normalize_folds_punctuation_and_width():
    assert voice_session.normalize_wake_text("你好，小智。") == "你好小智"
    assert voice_session.normalize_wake_text(" 你好　小智！") == "你好小智"
    assert voice_session.normalize_wake_text("Ｈｉ，小智") == "hi小智"


def test_match_wake_prefix_consumes_the_longest_variant():
    assert voice_session.match_wake_prefix("你好，小智，几点了") == "几点了"
    assert voice_session.match_wake_prefix("小智小智") == ""
    assert voice_session.match_wake_prefix("今天天气") is None


@pytest.mark.parametrize("text,duration", VARIANTS)
def test_variants_are_wake_only(text, duration):
    assert voice_session.is_wake_only(text, duration) is True


@pytest.mark.parametrize("text,duration", COMMANDS)
def test_short_commands_are_not_wake_only(text, duration):
    assert voice_session.is_wake_only(text, duration) is False


def test_fuzzy_match_is_bounded_by_duration():
    # An unlisted mishearing (好小田) is only wake-only while the segment is
    # short; the same words inside a 1.6 s line could carry a real question.
    assert voice_session.is_wake_only("好小田", 0.6) is True
    assert voice_session.is_wake_only("好小田", 1.6) is False


# ---------------- the turn path ----------------

class FakeWs:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


class FakeAsr:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def transcribe(self, seg, rate):
        self.calls += 1
        return self.text


class FakeTts:
    async def synth(self, text):
        return np.zeros(8, dtype=np.int16), RATE


class FakeLlm:
    provider = "deepseek"
    model = "fake"


def make_session(asr_text):
    session = voice_session.Session(FakeWs(), CFG, codec=None, tts=FakeTts(),
                                    asr=FakeAsr(asr_text), llm=FakeLlm())
    session.codec = types.SimpleNamespace(decode=lambda frame: np.zeros(960, dtype=np.int16))
    return session


def speech(seconds: float) -> np.ndarray:
    """Loud enough to clear the noise gate, so only the wake gate decides."""
    return np.full(int(RATE * seconds), 3000, dtype=np.int16)


def types_sent(ws) -> list[str]:
    out = []
    for raw in ws.sent:
        msg = json.loads(raw) if isinstance(raw, str) else raw
        out.append(msg.get("type"))
    return out


@pytest.mark.parametrize("text,duration", VARIANTS)
async def test_wake_variant_opens_no_turn(text, duration, monkeypatch):
    session = make_session(text)
    ran = []
    monkeypatch.setattr(session, "_run_turn",
                        lambda t0, t: ran.append(t) or asyncio.sleep(0))
    await session._handle_turn(speech(duration))
    assert "stt" not in types_sent(session.ws), "wake word must not reach the subtitle/model"
    assert ran == [], "wake word must not start a turn"
    assert session.turn is None


@pytest.mark.parametrize("text,duration", COMMANDS)
async def test_real_command_still_opens_a_turn(text, duration, monkeypatch):
    session = make_session(text)
    ran = []
    async def fake_run_turn(t0, t):
        ran.append(t)
    monkeypatch.setattr(session, "_run_turn", fake_run_turn)
    await session._handle_turn(speech(duration))
    assert "stt" in types_sent(session.ws)
    assert ran == [voice_session.strip_wake(text)]


async def test_one_char_stop_command_survives_the_noise_gate():
    assert voice_session._valid_text("停") is True
    # Existing noise-gate contract stays: silence fillers are still rejected.
    assert voice_session._valid_text("啊") is False
    assert voice_session._valid_text("好") is False
