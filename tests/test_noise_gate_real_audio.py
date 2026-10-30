"""Noise gate re-derived from real WAVs (task-26 step 2).

Nine? No: six fixtures captured on the board (2026-10-28, docs/segments/
20261028-102709): the three quietest human segments the old 0.008 floor dropped
plus three kept ones. All six must pass the new 0.0025 floor; synthetic digital
silence must still be dropped. The hallucination filter runs after ASR.
"""
import importlib.util
import sys
import types
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

sys.modules.setdefault("opuslib", types.ModuleType("opuslib"))

# Other test files swap sys.modules["audio"] for a stub; load the real module by
# path and make session import that one.
_spec = importlib.util.spec_from_file_location("audio_real_gate", ROOT / "src" / "audio.py")
audio = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audio)
sys.modules["audio"] = audio

_spec = importlib.util.spec_from_file_location("session_real_gate", ROOT / "src" / "session.py")
session = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(session)

FIXTURES = ROOT / "tests" / "fixtures" / "segments"
HUMAN_WAVS = [
    "dropped-0.0053-1.41s.wav",
    "dropped-0.0059-1.93s.wav",
    "dropped-0.0064-1.45s.wav",
    "kept-0.0084-4.20s.wav",
    "kept-0.0086-1.96s.wav",
    "kept-0.0110-0.77s.wav",
]


def load_wav(name: str) -> tuple[np.ndarray, int]:
    with wave.open(str(FIXTURES / name), "rb") as fh:
        assert fh.getnchannels() == 1 and fh.getsampwidth() == 2
        rate = fh.getframerate()
        pcm = np.frombuffer(fh.readframes(fh.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0, rate


@pytest.mark.parametrize("name", HUMAN_WAVS)
def test_real_human_segments_are_kept(name):
    samples, rate = load_wav(name)
    assert rate == 16000
    rms = audio.segment_rms(samples)
    assert 0.004 <= rms <= 0.02, f"{name} rms={rms:.4f} outside captured range"
    assert audio.is_noise_segment(samples, rate) is False, name


def test_quietest_real_segment_is_kept():
    # The old 0.008 floor rejected exactly this one; 0.0053 is the measured floor
    # of real speech, so 0.0025 has a >2x margin.
    samples, rate = load_wav("dropped-0.0053-1.41s.wav")
    assert audio.segment_rms(samples) < 0.006
    assert audio.is_noise_segment(samples, rate) is False


def test_digital_silence_is_still_dropped():
    rng = np.random.default_rng(0)
    silence = rng.normal(0.0, 0.0005, 16000 * 2).astype(np.float32)
    assert audio.segment_rms(silence) < audio.SEGMENT_RMS_FLOOR
    assert audio.is_noise_segment(silence, 16000) is True


# --- post-ASR hallucination filter ------------------------------------------

@pytest.mark.parametrize("text", [
    "谢谢观看。",
    "字幕由 Amara.org 社区提供",
    "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目",
    "感谢观看，记得订阅",
    "明镜与点点",
])
def test_known_hallucinations_rejected(text):
    assert session._valid_text(text) is False


@pytest.mark.parametrize("text", [
    "今天周几？",
    "今天天气怎么样？",
    "打开台灯",
    "给我讲个笑话",
])
def test_real_questions_survive_filter(text):
    assert session._valid_text(text) is True


def test_too_short_still_rejected():
    assert session._valid_text("。") is False
    assert session._valid_text("啊") is False
    assert session._valid_text("好") is False
    assert session._valid_text("好的") is True
