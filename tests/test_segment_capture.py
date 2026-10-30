"""Opt-in VAD segment capture (task-26 step 1).

Disabled by default and free when off. When enabled, every handled segment is
written to docs/segments/<timestamp>/ as WAV, named kept/dropped + rms + seconds,
capped at 60 segments / 20 MB.

`audio.py` needs opuslib only when codecs are constructed; stub it before the
import (same pattern as the other session tests).
"""
import sys
import types
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

sys.modules.setdefault("opuslib", types.ModuleType("opuslib"))

# Another test file replaces sys.modules["audio"] with a stub, so load the real
# module by path instead of trusting the global import cache.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("audio_capture", ROOT / "src" / "audio.py")
audio = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audio)

import session as voice_session  # noqa: E402
import yaml  # noqa: E402

CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
RATE = CFG["audio"]["sample_rate"]


def square(amplitude: float, seconds: float) -> np.ndarray:
    n = int(RATE * seconds)
    wave_ = np.empty(n, dtype=np.float32)
    wave_[0::2] = amplitude
    wave_[1::2] = -amplitude
    return wave_


def read_wav(path: Path):
    with wave.open(str(path), "rb") as fh:
        return (fh.getnchannels(), fh.getsampwidth(), fh.getframerate(),
                fh.getnframes(), np.frombuffer(fh.readframes(fh.getnframes()),
                                               dtype=np.int16))


# --- disabled / zero overhead ------------------------------------------------

def test_disabled_by_default_and_no_disk_write(tmp_path):
    assert audio.build_segment_recorder({"capture_segments": False}) is None
    assert audio.build_segment_recorder({}) is None
    assert not (tmp_path / "segments").exists()


# --- naming + WAV contents ---------------------------------------------------

def test_filename_format_and_audio(tmp_path, capsys):
    rec = audio.SegmentRecorder(root=tmp_path / "segments")
    seg = square(0.02, 0.10)                    # 1600 samples = 0.10 s
    path = rec.record(seg, RATE, dropped=False, rms=0.0052)

    assert path is not None
    assert path.parent.parent == tmp_path / "segments"
    assert path.name == "kept-0.0052-0.10s.wav"
    ch, width, rate, frames, pcm = read_wav(path)
    assert (ch, width, rate) == (1, 2, RATE)
    assert frames == len(seg)
    assert np.array_equal(pcm, (seg * 32768).astype(np.int16))

    dropped = rec.record(square(0.005, 2.0), RATE, dropped=True, rms=0.0050)
    assert dropped.name == "dropped-0.0050-2.00s.wav"
    assert rec.count == 2


def test_int16_input_is_kept_verbatim(tmp_path):
    rec = audio.SegmentRecorder(root=tmp_path)
    pcm16 = np.array([1, -2, 3, -4], dtype=np.int16)
    path = rec.record(pcm16, RATE, dropped=False, rms=0.001)
    _, _, _, frames, pcm = read_wav(path)
    assert frames == 4
    assert np.array_equal(pcm, pcm16)


# --- directory creation / caps ----------------------------------------------

def test_missing_directory_is_created(tmp_path):
    root = tmp_path / "does" / "not" / "exist"
    rec = audio.SegmentRecorder(root=root)
    path = rec.record(square(0.02, 0.10), RATE, dropped=False)
    assert path is not None and path.is_file()
    assert path.parent.is_dir()


def test_segment_cap_stops_capture(tmp_path, capsys):
    rec = audio.SegmentRecorder(root=tmp_path, max_segments=2)
    assert rec.record(square(0.02, 0.10), RATE, dropped=False, rms=0.01)
    assert rec.record(square(0.02, 0.10), RATE, dropped=False, rms=0.01)
    assert rec.record(square(0.02, 0.10), RATE, dropped=False, rms=0.01) is None
    assert rec.stopped is True
    assert len(list(tmp_path.rglob("*.wav"))) == 2
    assert "WARN limit reached" in capsys.readouterr().out


def test_byte_cap_stops_capture(tmp_path, capsys):
    rec = audio.SegmentRecorder(root=tmp_path, max_bytes=100)
    assert rec.record(square(0.02, 0.10), RATE, dropped=False, rms=0.01) is None
    assert rec.stopped is True
    assert not list(tmp_path.rglob("*.wav"))
    assert "WARN limit reached" in capsys.readouterr().out


# --- session wiring ----------------------------------------------------------

class FakeWs:
    async def send(self, data):
        pass


class FakeAsr:
    def transcribe(self, samples, sample_rate):
        return "你好，小志。"                     # wake-only: no turn


def bare_session(recorder):
    s = voice_session.Session.__new__(voice_session.Session)
    s.ws = FakeWs()
    s.session_id = "test"
    s.log_prefix = "[test]"
    s.cfg = CFG
    s.codec = None
    s.asr = FakeAsr()
    s.alive = True
    s._reply_ready = False
    s._first_audio_at = None
    s._cue_pushed = False
    s._cue_tasks = set()
    s._spoke_answer = False
    s._state_tasks = set()
    s.thinking_face = ""
    s.cue_restore_face = "neutral"
    s._filler_pcm = None
    s.filler_cache = {}
    s.pending_confirm = None
    s.segment_recorder = recorder
    return s


async def test_session_records_kept_and_dropped(tmp_path, capsys):
    rec = audio.SegmentRecorder(root=tmp_path)
    s = bare_session(rec)
    await s._handle_turn(square(0.0015, 2.0))    # below the gate -> dropped
    await s._handle_turn(square(0.02, 0.8))      # quiet but short -> kept
    names = sorted(p.name for p in tmp_path.rglob("*.wav"))
    assert len(names) == 2
    assert names[0].startswith("dropped-") and names[1].startswith("kept-")
    out = capsys.readouterr().out
    assert "[capture]" in out and "noise gate: dropped" in out
    assert "IndexError" not in out
