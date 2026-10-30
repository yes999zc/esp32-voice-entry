"""Delay mask: default is a visual "thinking" face, no sound.

History (2026-10-27): a spoken sentence ("我想想") -> a 160 ms chime -> now just
the face. 9哥's call: the screen already shows the state and subtitles, so a
"da" only steals attention. The chime remains as an opt-in
(`filler_chime_ms > 0`); its no-overlap guarantee is still tested here.

Timing: `proactive_chime_lead_ms` (300 ms) after segment close. Skipped with
`face cue skipped (answer ready)` when the reply is already queued. The cue
restores itself through `cue_restore_face` on first audio / rejected segment /
turn end; `kDeviceStateSpeaking` only calls SetStatus, not SetEmotion
(application.cc:1138-1147), so the state flow does not overwrite it.

No model, no Opus, no device: a fake websocket and a fake codec drive the real
`_start_filler` / `_filler_after` / `_speak`. `opuslib` is stubbed before the
`session` import because `audio.py` loads the shared library at import time.
"""
import asyncio
import json
import sys
import time
import types
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

sys.modules.setdefault("opuslib", types.ModuleType("opuslib"))

import session as voice_session  # noqa: E402

CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
RATE = CFG["audio"]["sample_rate"]


class FakeWs:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


class FrameCodec:
    """Three identifiable audio frames; enough to interleave two playbacks."""

    def frames(self, pcm):
        return [b"a1", b"a2", b"a3"]


def bare_session(chime: bool = False, thinking: str = "thinking"):
    s = voice_session.Session.__new__(voice_session.Session)
    s.ws = FakeWs()
    s.session_id = "test"
    s.log_prefix = "[test]"
    s.cfg = CFG
    s.codec = FrameCodec()
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
    s.thinking_face = thinking
    s.cue_restore_face = "idle"
    s._cue_pushed = False
    s._cue_tasks = set()
    s._spoke_answer = False
    s._state_tasks = set()
    s.segment_recorder = None
    s._filler_pcm = (np.zeros(RATE * voice_session.FILLER_CHIME_MS // 1000,
                              dtype=np.int16) if chime else None)
    s.filler_cache = {}
    return s


def messages(sent):
    out = []
    for raw in sent:
        if isinstance(raw, bytes):
            out.append({"type": "audio"})
        else:
            out.append(json.loads(raw))
    return out


def states(sent):
    return [m.get("state") or m.get("type") for m in messages(sent)]


# --- shipped defaults --------------------------------------------------------

def test_default_is_face_not_sound():
    conv = CFG["conversation"]
    assert conv["filler_chime_ms"] == 0                 # silent by default
    assert voice_session.filler_chime_ms_for(conv) == 0
    assert conv["thinking_face"] == "thinking"
    assert conv["cue_restore_face"] == "idle"
    assert conv["proactive_chime_lead_ms"] == 300
    assert conv["proactive_chime_lead_ms"] <= \
        voice_session.PROACTIVE_CHIME_LEAD_MAX_MS


# --- face cue ----------------------------------------------------------------

async def test_thinking_face_at_300ms(capsys):
    s = bare_session()
    t0 = time.perf_counter()
    task = s._start_filler(t0)
    assert task is not None
    await task
    elapsed = time.perf_counter() - t0

    msgs = messages(s.ws.sent)
    assert msgs == [{"session_id": "test", "type": "llm", "emotion": "thinking"}]
    assert not any(m.get("type") == "tts" for m in msgs)   # no audio at all
    assert 0.22 <= elapsed <= 0.55, f"face cue fired after {elapsed:.3f}s"
    assert s._cue_pushed is True
    out = capsys.readouterr().out
    assert "cue thinking at" in out
    # No restore: the state-driven face owns it after the cue.
    assert "neutral" not in out


async def test_face_skipped_when_answer_audio_ready(capsys):
    s = bare_session()
    s._first_audio_at = 0.2
    await s._filler_after(time.perf_counter(), 0.0)
    assert s.ws.sent == []
    assert "face cue skipped (answer ready)" in capsys.readouterr().out


async def test_face_skipped_when_reply_ready(capsys):
    s = bare_session()
    s._reply_ready = True
    await s._filler_after(time.perf_counter(), 0.0)
    assert s.ws.sent == []
    assert "face cue skipped (answer ready)" in capsys.readouterr().out


async def test_no_session_does_not_raise(capsys):
    s = bare_session()
    s.alive = False
    await s._filler_after(time.perf_counter(), 0.0)
    assert s.ws.sent == []

    # A dead socket surfaces as an exception from push_emotion; the cue must
    # swallow it and never reach the TTS/turn path.
    s = bare_session()

    async def boom(_name):
        raise ConnectionError("socket gone")

    s.push_emotion = boom
    await s._filler_after(time.perf_counter(), 0.0)
    assert s.ws.sent == []
    assert "cue failed" in capsys.readouterr().out


async def test_empty_thinking_face_disables_cue(capsys):
    s = bare_session(thinking="")
    assert s._start_filler(time.perf_counter()) is None
    await s._filler_after(time.perf_counter(), 0.0)
    assert s.ws.sent == []
    # An empty face + no chime + empty phrases must be a clean no-op, not the
    # swallowed IndexError that used to hide behind "[filler] error".
    assert "IndexError" not in capsys.readouterr().out


# --- opt-in chime (kept for rollback) ---------------------------------------

async def test_chime_opt_in_still_plays():
    s = bare_session(chime=True, thinking="")
    t0 = time.perf_counter()
    task = s._start_filler(t0)
    assert task is not None
    await task
    seq = states(s.ws.sent)
    assert seq[0] == "start" and seq[-1] == "stop" and "audio" in seq
    assert "sentence_start" not in seq                     # chime, no subtitle
    await s._filler_after(time.perf_counter(), 0.0)          # second cue
    assert all(m.get("type") != "llm" for m in messages(s.ws.sent))


async def test_playback_does_not_overlap():
    s = bare_session(chime=True, thinking="")
    pcm = np.zeros(960, dtype=np.int16)
    await asyncio.gather(
        s._speak("chime 160 ms", s._filler_pcm, 0.0, label="filler", announce=False),
        s._speak("真正的回答。", pcm, 0.0),
    )
    seq = states(s.ws.sent)
    open_playback = False
    starts = stops = sentences = 0
    for state in seq:
        if state == "start":
            assert not open_playback, f"overlapping tts_start: {seq}"
            open_playback = True
            starts += 1
        elif state == "stop":
            assert open_playback, f"tts_stop without start: {seq}"
            open_playback = False
            stops += 1
        else:                                  # audio / sentence_start
            assert open_playback, f"{state} outside playback: {seq}"
            if state == "sentence_start":
                sentences += 1
    assert (starts, stops) == (2, 2)
    assert not open_playback
    assert sentences == 1                     # only the answer has a subtitle


async def test_chime_dropped_under_lock_when_answer_ready(capsys):
    s = bare_session(chime=True, thinking="")
    s._reply_ready = True
    await s._speak("chime 160 ms", s._filler_pcm, 0.0, label="filler",
                   announce=False)
    assert s.ws.sent == []
    assert "chime skipped (answer ready)" in capsys.readouterr().out


# --- cue lifecycle (it must clear itself) -----------------------------------

def square(amplitude: float, seconds: float) -> np.ndarray:
    n = int(RATE * seconds)
    wave = np.empty(n, dtype=np.float32)
    wave[0::2] = amplitude
    wave[1::2] = -amplitude
    return wave


class CueAsr:
    """Fake ASR: optionally marks the cue as pushed, returns text or raises."""

    def __init__(self, text: str = "你好，小志。", session=None, raises=None):
        self.text = text
        self.session = session
        self.raises = raises

    def transcribe(self, samples, sample_rate):
        if self.session is not None:
            self.session._cue_pushed = True      # cue landed before ASR returned
        if self.raises is not None:
            raise self.raises
        return self.text


async def test_cue_restored_on_first_audio(capsys):
    s = bare_session()
    await s._push_thinking_face(0.0)             # cue is on screen
    s.ws.sent.clear()
    await s._speak("真正的回答。", np.zeros(960, dtype=np.int16), 0.0)

    emotions = [m.get("emotion") for m in messages(s.ws.sent)
                if m.get("type") == "llm"]
    assert emotions == ["idle"]                  # thinking -> idle, once
    assert s._cue_pushed is False
    assert "cue restore (first audio)" in capsys.readouterr().out


async def test_cue_restored_on_rejected_segment(capsys):
    s = bare_session()
    s.asr = CueAsr("你好，小志。", session=s)     # wake-only -> rejected turn
    await s._handle_turn(square(0.02, 0.6))
    emotions = [m.get("emotion") for m in messages(s.ws.sent)
                if m.get("type") == "llm"]
    assert emotions == ["idle"]
    assert s._cue_pushed is False
    assert "cue restore (rejected)" in capsys.readouterr().out


async def test_cue_restored_on_turn_end(capsys):
    s = bare_session()
    s.asr = CueAsr(session=s, raises=RuntimeError("asr blew up"))
    await s._handle_turn(square(0.02, 0.6))
    await asyncio.sleep(0.02)                    # let the fire-and-forget restore run
    emotions = [m.get("emotion") for m in messages(s.ws.sent)
                if m.get("type") == "llm"]
    assert emotions == ["idle"]
    assert s._cue_pushed is False
    assert "cue restore (turn end)" in capsys.readouterr().out


async def test_cue_restore_disabled():
    s = bare_session()
    s.cue_restore_face = ""
    await s._push_thinking_face(0.0)
    s.ws.sent.clear()
    await s._speak("真正的回答。", np.zeros(960, dtype=np.int16), 0.0)
    assert not any(m.get("type") == "llm" for m in messages(s.ws.sent))
    assert s._cue_pushed is True                 # no restore configured


async def test_no_restore_when_no_cue_was_pushed():
    s = bare_session()
    await s._speak("真正的回答。", np.zeros(960, dtype=np.int16), 0.0)
    assert not any(m.get("type") == "llm" for m in messages(s.ws.sent))


# --- restore failure / announce guard ---------------------------------------

async def test_cue_restore_failure_is_swallowed(capsys):
    s = bare_session()
    await s._push_thinking_face(0.0)
    assert s._cue_pushed is True

    async def boom(_name):
        raise ConnectionError("socket gone")

    s.push_emotion = boom
    await s._restore_cue_face("first audio")     # must not raise
    assert s._cue_pushed is False
    assert "cue restore failed" in capsys.readouterr().out


async def test_chime_does_not_restore_face():
    """announce=False (chime) must never trip the cue's first-audio restore."""
    s = bare_session(chime=True, thinking="")
    await s._push_thinking_face(0.0)
    assert s._cue_pushed is True
    s.ws.sent.clear()
    await s._speak("chime 160 ms", s._filler_pcm, 0.0, label="filler",
                   announce=False)
    assert s._cue_pushed is True                 # cue untouched by the chime
    assert not any(m.get("type") == "llm" for m in messages(s.ws.sent))


# --- timing config (shared sanitise style) ----------------------------------

def test_lead_config_sanitised(capsys):
    f = voice_session.proactive_chime_lead_ms_for
    assert f({}) == 300
    assert f({"proactive_chime_lead_ms": 400}) == 400
    assert f({"proactive_chime_lead_ms": 1000}) == 400
    assert "clamped" in capsys.readouterr().out
    assert f({"proactive_chime_lead_ms": "300ms"}) == 300
    assert "not a number" in capsys.readouterr().out
    assert f({"proactive_chime_lead_ms": -5}) == 0


async def test_barge_stops_a_proactive_announcement_mid_stream():
    """A proactive line has no turn to cancel, so the frame loop must check the flag.

    `_barge_watch` stops an answer by cancelling `self.turn`; an announcement is
    awaited by the proactive controller instead, so before this guard the server
    kept streaming audio after tts_stop - the person interrupts and it talks on.
    """
    s = bare_session()
    s.codec = ManyFrames()
    seen = []
    real_send = s._safe_send

    async def counting_send(data):
        # Only the audio frames matter here; tts start/sentence/stop are JSON.
        if isinstance(data, (bytes, bytearray)) and data.startswith(b"f"):
            seen.append(data)
            if len(seen) == 2:        # the person speaks over it here
                s.speaking = False
        await real_send(data)

    s._safe_send = counting_send
    await s._speak("提醒你喝水", np.zeros(960, dtype=np.int16), 0.0, label="proactive")

    assert len(seen) == 2, f"kept streaming after the interrupt: {len(seen)} frames"
    assert s.speaking is False


class ManyFrames:
    def frames(self, pcm):
        return [f"f{i}".encode() for i in range(10)]
