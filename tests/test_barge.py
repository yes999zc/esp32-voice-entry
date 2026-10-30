"""Barge-in decision: 240 ms of sustained loud 20 ms sub-frames, then stop.

`src/session.py` imports `audio`, which loads the Opus dynamic library at import
time (unavailable to pytest on this Mac). The test installs a stub `audio`
module before importing `session`, then drives the real `_barge_watch` on
constructed 60 ms PCM frames via `Session.__new__` — no websocket, no models.

The signal is a ±A square wave, so the 20 ms sub-frame RMS is exactly A; that is
the statistic `barge_rms` is compared against. The echo probe now logs both
statistics (`sub20` and `frame60`); `sub20` is the decision one.

Thresholds come from the repo's `config.yaml`. `ECHO_20MS_PEAK` (0.0017) and
`PERSON_20MS_PEAK` (0.0348) are measured constants; the assertions only lock the
allowed window (>= echo x 4 and <= person / 4), not a specific threshold value.
"""
import json
import re
import sys
import time
import types
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# `session` does `from audio import build_vad, pop_segments, resample`; stub it
# so the Opus library is never loaded. Must happen before importing session.
_audio = types.ModuleType("audio")
_audio.build_vad = lambda *args, **kwargs: None
_audio.build_segment_recorder = lambda *args, **kwargs: None
_audio.is_noise_segment = lambda *args, **kwargs: False
_audio.pop_segments = lambda *args, **kwargs: []
_audio.resample = lambda pcm, src, dst: pcm
sys.modules["audio"] = _audio

import session as voice_session  # noqa: E402

CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
RATE = CFG["audio"]["sample_rate"]
FRAME_SAMPLES = int(RATE * CFG["audio"]["frame_ms"] / 1000)     # 960 = 60 ms
CONV = CFG["conversation"]

# Measured 2026-10-27 (58 `[echo]` windows over two 18-19 s answers with nobody
# speaking): self-echo while TTS plays is 60 ms frame RMS p50 0.0006 / p90
# 0.0008 / max 0.0011, i.e. ~0.0017 as 20 ms sub-frame peaks (x1.5 crest).
# A person interrupting ("等一下") measured 0.0348 as a 20 ms peak and stopped
# playback in 0.192 s. The shipped threshold must sit between the two.
ECHO_20MS_PEAK = 0.0017
PERSON_20MS_PEAK = 0.0348


def frame(amplitude: float) -> np.ndarray:
    """60 ms of ±amplitude square wave; every 20 ms sub-frame RMS == amplitude."""
    value = int(round(amplitude * 32768))
    pcm = np.full(FRAME_SAMPLES, value, dtype=np.int16)
    pcm[1::2] = -value
    return pcm


class Harness:
    """A Session with only the state `_barge_watch` / `_probe_echo` touch."""

    def __init__(self, guard_ago: float = 1.0, cfg: dict | None = None):
        sess = voice_session.Session.__new__(voice_session.Session)
        sess.cfg = cfg or CFG
        sess.session_id = "barge-test"
        sess.speaking = True
        sess.turn = None
        sess._speak_started_at = time.perf_counter() - guard_ago
        sess._barge_ms = 0
        sess._barge_quiet_ms = 0
        sess._barge_onset_at = None
        sess._echo_sub = []
        sess._echo_frame = []
        sess._echo_recent = []
        sess._echo_last_log = 0.0
        sess.sent = []
        sess.logs = []
        sess.log = lambda *parts: sess.logs.append(parts)
        sess.faces = []
        sess._face_state = None
        sess._face_emotion = None

        async def safe_send(data):
            sess.sent.append(data)

        async def push_emotion(name):
            sess.faces.append(name)

        sess._safe_send = safe_send
        sess.push_emotion = push_emotion
        self.sess = sess

    async def feed(self, amplitude: float, seconds: float) -> bool:
        """Feed whole 60 ms frames; return True if a barge fires."""
        frames = int(round(seconds / (FRAME_SAMPLES / RATE)))
        for _ in range(frames):
            if await self.sess._barge_watch(frame(amplitude)):
                return True
        return False


# ---------------- the four required cases ----------------

async def test_echo_floor_never_barges():
    """2 s at the measured echo floor (0.002) must never interrupt us."""
    harness = Harness()
    assert await harness.feed(0.002, 2.0) is False
    assert harness.sess.speaking is True
    assert harness.sess.sent == []


async def test_person_speaking_300ms_barges():
    """A person at 0.03 for 300 ms must interrupt and send a tts stop."""
    harness = Harness()
    assert await harness.feed(0.03, 0.30) is True
    assert harness.sess.speaking is False
    assert len(harness.sess.sent) == 1
    payload = json.loads(harness.sess.sent[0])
    assert (payload["type"], payload["state"]) == ("tts", "stop")
    assert payload["session_id"] == "barge-test"


async def test_barge_in_off_never_interrupts():
    """barge_in is the only switch; off means never cut playback (no degradation)."""
    cfg = dict(CFG)
    cfg["conversation"] = dict(CONV, barge_in=False)
    harness = Harness(cfg=cfg)
    assert await harness.feed(0.05, 2.0) is False
    assert harness.sess.speaking is True
    assert harness.sess.sent == []


async def test_single_frame_spike_does_not_barge():
    """One 60 ms spike (a door, a plosive) is not sustained speech."""
    harness = Harness()
    assert await harness.sess._barge_watch(frame(0.05)) is False
    assert await harness.feed(0.0005, 1.0) is False
    assert harness.sess.speaking is True


async def test_guard_window_ignores_loud_speech():
    """Playback start is ignored for `barge_guard_ms`; the same speech after it barges."""
    harness = Harness(guard_ago=0.0)
    assert await harness.feed(0.05, 0.5) is False       # inside the guard
    assert harness.sess._barge_ms == 0                  # nothing accumulated
    harness.sess._speak_started_at -= (CONV["barge_guard_ms"] + 50) / 1000
    assert await harness.feed(0.05, 0.30) is True


# ---------------- the 240 ms accounting (why the log says 0.181 s) ----------------

async def test_min_ms_accumulates_over_frames_not_one_frame():
    """3 x 60 ms is not enough; the 4th frame (240 ms of audio) fires.

    The printed `onset->stop` is wall clock, so on a real 60 ms stream four
    frames span ~180 ms even though 240 ms of loud audio accumulated — this is
    the 0.181 s seen in the logs, not a one-frame trigger.
    """
    harness = Harness()
    assert [await harness.sess._barge_watch(frame(0.03)) for _ in range(3)] == \
        [False, False, False]
    assert harness.sess._barge_ms == 180
    assert await harness.sess._barge_watch(frame(0.03)) is True
    # The log prints both clocks; sustained=240 ms is what the counter decided.
    assert any("sustained=240 ms" in str(entry) for entry in harness.sess.logs)


async def test_long_gap_resets_the_run():
    """A >200 ms silence between loud runs must reset the accumulation.

    Quiet frames also count in 20 ms audio ticks, so a tight loop (no sleeps)
    must reset — this used to be wall-clock based and silently kept the old
    count when frames arrived in a burst.
    """
    harness = Harness()
    for _ in range(3):
        assert await harness.sess._barge_watch(frame(0.03)) is False
    assert harness.sess._barge_ms == 180
    for _ in range(5):                       # 300 ms of quiet: counter resets
        assert await harness.sess._barge_watch(frame(0.0005)) is False
    assert harness.sess._barge_ms == 0
    assert harness.sess._barge_onset_at is None
    # Three loud frames again must still not fire (below 240 ms).
    for _ in range(3):
        assert await harness.sess._barge_watch(frame(0.03)) is False


# ---------------- thresholds from the 2026-10-27 measurement ----------------

def test_shipped_threshold_sits_between_echo_and_person():
    """0.008 is 4.7x above self-echo and 4.3x below a person (see config.yaml)."""
    threshold = CONV["barge_rms"]
    assert threshold >= ECHO_20MS_PEAK * 4
    assert threshold <= PERSON_20MS_PEAK / 4


async def test_measured_echo_peak_does_not_interrupt():
    """The measured self-echo ceiling (20 ms peak 0.0017) must never barge."""
    harness = Harness()
    assert await harness.feed(ECHO_20MS_PEAK, 1.0) is False
    assert harness.sess.speaking is True


# ---------------- calibration probe ----------------

def test_echo_probe_off_logs_nothing():
    """echo_probe is off in the shipped config: the probe must stay silent."""
    harness = Harness()                      # CFG has echo_probe: false
    for _ in range(3):
        harness.sess._probe_echo(frame(0.03))
    harness.sess._flush_echo("playback")
    assert harness.sess._echo_sub == []
    assert harness.sess.logs == []


def test_echo_probe_logs_sub20_distribution():
    """The probe must log the statistic barge_rms is compared with (20 ms)."""
    cfg = dict(CFG)
    cfg["conversation"] = dict(CONV, echo_probe=True)
    harness = Harness(cfg=cfg)
    for _ in range(3):
        harness.sess._probe_echo(frame(0.03))
    harness.sess._flush_echo("playback")
    assert harness.sess._echo_sub == []            # flushed
    line = " ".join(str(part) for part in harness.sess.logs[-1])
    assert "sub20 p50=0.0300" in line
    assert "max=0.0300" in line
    assert "hist" in line



# ---------------- barge -> face (C3) ----------------

def _face_log_ms(harness) -> float:
    line = " ".join(str(part) for part in harness.sess.logs)
    match = re.search(r"\[barge\] face=([\d.]+) ms since detect", line)
    assert match, line
    return float(match.group(1))


async def test_barge_pushes_shocked_within_300ms():
    """Detected barge -> shocked startle (C1a), with an auditable latency."""
    harness = Harness()
    assert await harness.feed(0.03, 0.30) is True
    assert harness.sess.faces == ["shocked"]
    elapsed = _face_log_ms(harness)
    assert 0 <= elapsed <= 300, elapsed
    # The startle is still pushed before playback is told to stop.
    assert json.loads(harness.sess.sent[-1])["state"] == "stop"


class FakeClock:
    """Monotonic 40 ms tick, so the latency assertion is not wall-clock based."""

    def __init__(self, start: float = 1000.0, step: float = 0.040):
        self.now = start
        self.step = step

    def perf_counter(self) -> float:
        self.now += self.step
        return self.now


async def test_barge_face_latency_uses_the_measured_clock(monkeypatch):
    harness = Harness()
    clock = FakeClock()
    monkeypatch.setattr(voice_session, "time", clock)
    harness.sess._speak_started_at = clock.perf_counter() - 1.0
    assert await harness.feed(0.03, 0.30) is True
    assert harness.sess.faces == ["shocked"]
    elapsed = _face_log_ms(harness)
    assert 0 < elapsed <= 300, elapsed
