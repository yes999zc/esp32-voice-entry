"""Step 2 / C2/C3 state -> face: the server pushes all six conversation states.

Firmware sets neutral itself in Idle/Connecting/Listening and does NOT touch the
face in kDeviceStateSpeaking (application.cc:1138-1147). The server now pushes:
listening (ready / listen start), thinking (ASR done, before the LLM), speaking
(before tts_start: face first, then voice), tool-running (around a tool call),
confirm-pending (while a spoken yes is awaited) and idle (turn end / answer /
cancel / timeout). C1a maps the six states to six distinct emotion names
(idle / happy / confused / speaking / angry / shocked) for the firmware's six
EAFs; unknown states normalise to idle, and a barge-in startle (shocked) is an
event look.

Pure mapper tests + session wiring tests (fake ws / fake codec, no Opus, no
models, no device). `opuslib` is stubbed before importing `session`.
"""
import asyncio
import json
import sys
import types
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

sys.modules.setdefault("opuslib", types.ModuleType("opuslib"))

import persona  # noqa: E402
import session as voice_session  # noqa: E402

CFG = yaml.safe_load((ROOT / "config.yaml").read_text())
RATE = CFG["audio"]["sample_rate"]


# --- mapping (pure function) -------------------------------------------------

# C1a: six states -> six DISTINCT firmware-native names (six EAFs).
SIX_STATES = {
    "idle": "idle",
    "listening": "happy",
    "thinking": "confused",
    "speaking": "speaking",
    "tool-running": "angry",
    "confirm-pending": "shocked",
}


def test_six_states_have_an_expression():
    for state, emotion in SIX_STATES.items():
        assert persona.map_state_to_emotion(state) == emotion
        assert persona.is_emotion(emotion), f"{emotion} not in EMOTION_NAMES"


def test_six_states_are_six_distinct_emotions():
    """Acceptance: exactly {idle,happy,confused,speaking,angry,shocked}.

    C1a rev2: ``speaking`` must stay the persona name (C1 aliases it to
    winking.eaf); mapping it to native ``winking`` would collide with idle
    (native winking -> neutral.eaf).
    """
    names = {persona.map_state_to_emotion(state) for state in SIX_STATES}
    assert names == {"idle", "happy", "confused", "speaking", "angry", "shocked"}
    assert len(names) == 6
    assert persona.map_state_to_emotion("idle") == "idle"
    assert persona.map_state_to_emotion("idle") != "neutral"
    assert persona.map_state_to_emotion("speaking") != "idle"


def test_idle_is_accepted_by_the_emotion_validation():
    """/debug/emotion validates through `is_emotion`; idle must be known."""
    assert persona.EMOTIONS.IDLE == "idle"
    assert "idle" in persona.EMOTION_NAMES
    assert persona.is_emotion("idle")


def test_unknown_state_normalises_to_idle():
    """C3/C1a: an unknown state falls back to idle's own look (not neutral)."""
    for state in ("", "   ", "nonsense", "idle-ish", None):
        assert persona.normalize_state(state) == "idle"
        assert persona.map_state_to_emotion(state) == "idle"
    assert persona.DEFAULT_STATE == "idle"
    assert persona.DEFAULT_EMOTION == persona.EMOTIONS.IDLE


def test_barge_in_is_an_event_look():
    assert persona.map_state_to_emotion("barge-in") == "shocked"


def test_mapping_tolerates_case_and_space():
    assert persona.map_state_to_emotion("  SPEAKING ") == "speaking"
    assert persona.map_state_to_emotion("Confirm-Pending") == "shocked"


def test_mapping_is_the_single_definition():
    # Every state in the table resolves through the one dict, values are known.
    for state, emotion in persona.STATE_TO_EMOTION.items():
        assert persona.map_state_to_emotion(state) == emotion.value
        assert emotion.value in persona.EMOTION_NAMES


# --- session wiring ----------------------------------------------------------

class FakeWs:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


class FrameCodec:
    def frames(self, pcm):
        return [b"a1", b"a2"]


class EmptyCodec:
    def frames(self, pcm):
        return []


class Asr:
    def __init__(self, text="今天天气不错"):
        self.text = text

    def transcribe(self, samples, sample_rate):
        return self.text


def bare_session(codec=None, cue_restore="idle"):
    s = voice_session.Session.__new__(voice_session.Session)
    s.ws = FakeWs()
    s.session_id = "test"
    s.log_prefix = "[test]"
    s.cfg = CFG
    s.codec = codec or FrameCodec()
    s.asr = Asr()
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
    s.thinking_face = ""
    s.cue_restore_face = cue_restore
    s._cue_pushed = False
    s._cue_tasks = set()
    s._spoke_answer = False
    s._state_tasks = set()
    s._filler_pcm = None
    s.filler_cache = {}
    s.pending_confirm = None
    s._confirm_task = None
    s._face_state = None
    s._face_emotion = None
    s.turn = None
    s._mcp_id = 10
    s._pending = {}
    s.confirm_tools = set()
    s.segment_recorder = None
    return s


def emotions(sent):
    out = []
    for raw in sent:
        if isinstance(raw, bytes):
            continue
        msg = json.loads(raw)
        if msg.get("type") == "llm":
            out.append(msg.get("emotion"))
    return out


def square(amplitude: float, seconds: float) -> np.ndarray:
    n = int(RATE * seconds)
    wave = np.empty(n, dtype=np.float32)
    wave[0::2] = amplitude
    wave[1::2] = -amplitude
    return wave


async def test_speaking_face_pushed_before_tts_start(capsys):
    """C2/C3: face first, voice second - speaking precedes tts_start."""
    s = bare_session()
    await s._speak("真正的回答。", np.zeros(960, dtype=np.int16), 0.0,
                    answer=True)
    assert emotions(s.ws.sent) == ["speaking"]
    messages = [json.loads(raw) for raw in s.ws.sent
                if not isinstance(raw, bytes)]
    speaking_at = next(i for i, msg in enumerate(messages)
                       if msg.get("type") == "llm"
                       and msg.get("emotion") == "speaking")
    tts_start_at = next(i for i, msg in enumerate(messages)
                        if msg.get("type") == "tts" and msg.get("state") == "start")
    assert speaking_at < tts_start_at, messages
    assert s._spoke_answer is True
    assert "state speaking -> speaking" in capsys.readouterr().out


async def test_speaking_face_only_when_audio_played():
    s = bare_session(codec=EmptyCodec())        # no frames reach the device
    await s._speak("没有声音。", np.zeros(960, dtype=np.int16), 0.0,
                    answer=True)
    assert emotions(s.ws.sent) == []
    assert s._spoke_answer is False


async def test_cue_restores_before_speaking():
    s = bare_session()
    await s._push_thinking_face(0.0)            # cue on screen
    s.ws.sent.clear()
    await s._speak("真正的回答。", np.zeros(960, dtype=np.int16), 0.0,
                    answer=True)
    # cue first: restore idle, then the speaking look - never two speakers.
    assert emotions(s.ws.sent) == ["idle", "speaking"]
    assert s._cue_pushed is False


async def test_pending_cue_blocks_speaking_push():
    s = bare_session(cue_restore="")            # configured "never restore"
    s._cue_pushed = True
    await s._speak("真正的回答。", np.zeros(960, dtype=np.int16), 0.0,
                    answer=True)
    assert emotions(s.ws.sent) == []            # cue owns the face, do not grab it
    assert s._spoke_answer is True


async def test_streaming_pushes_speaking_once():
    """A streaming turn sends one _speak per sentence; the face changes once."""
    s = bare_session()
    for sentence in ("第一句。", "第二句。", "第三句。"):
        await s._speak(sentence, np.zeros(960, dtype=np.int16), 0.0, answer=True)
    assert emotions(s.ws.sent) == ["speaking"]
    assert s._spoke_answer is True


async def test_non_answer_audio_does_not_push_speaking():
    """Confirm read-backs / proactive lines use _speak but are not the answer."""
    s = bare_session()
    await s._speak("好的，已经执行。", np.zeros(960, dtype=np.int16), 0.0)
    assert emotions(s.ws.sent) == []
    assert s._spoke_answer is False


async def test_thinking_pushed_after_asr_before_llm(capsys):
    """A valid ASR result sets thinking before `_run_turn` is entered."""
    s = bare_session()
    seen = []

    async def fake_run_turn(t0, text):
        seen.append(emotions(s.ws.sent))        # face already on the wire
        s._spoke_answer = True                  # pretend the answer played

    s._run_turn = fake_run_turn
    await s._handle_turn(square(0.02, 0.6))
    assert seen == [["confused"]]
    await asyncio.sleep(0.02)                   # fire-and-forget turn-end clear
    assert emotions(s.ws.sent) == ["confused", "idle"]
    assert s._spoke_answer is False
    out = capsys.readouterr().out
    assert "state thinking -> confused" in out
    assert "state idle -> idle" in out


async def test_turn_end_returns_to_idle_without_audio():
    """A thinking face must not linger when the turn produced no answer audio."""
    s = bare_session()

    async def fake_run_turn(t0, text):
        pass

    s._run_turn = fake_run_turn
    await s._handle_turn(square(0.02, 0.6))
    await asyncio.sleep(0.02)
    assert emotions(s.ws.sent) == ["confused", "idle"]


async def test_face_push_failure_does_not_raise(capsys):
    s = bare_session()

    async def boom(_name):
        raise ConnectionError("socket gone")

    s.push_emotion = boom
    await s._speak("真正的回答。", np.zeros(960, dtype=np.int16), 0.0,
                    answer=True)
    assert "state failed speaking" in capsys.readouterr().out


def test_run_turn_marks_answer_playback():
    """Both answer paths must call _speak(..., answer=True).

    Without this, deleting the keyword silently stops the speaking face from ever
    being pushed - the suite stayed green when both call sites lost it.
    """
    import ast

    tree = ast.parse((ROOT / "src" / "session.py").read_text(encoding="utf-8"))
    marked = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "attr", getattr(func, "id", ""))
        if name != "_speak":
            continue
        for kw in node.keywords:
            if kw.arg == "answer":
                marked.append(getattr(kw.value, "value", None))
    assert marked, "no _speak(..., answer=...) call site found"
    assert all(v is True for v in marked), f"answer= must be True, saw {marked}"
    assert len(marked) >= 2, f"expected both streaming and non-streaming answer paths, saw {len(marked)}"


async def test_text_turn_refuses_while_a_turn_is_running():
    """A bench injection must not clobber the turn that is already answering.

    `start_text_turn` resets `_first_audio_at`, `_spoke_answer` and the cue flags for
    the turn it starts. Running a second one mid-conversation reset the running
    turn's state and interleaved two answers - which would also corrupt the
    `--turn` screenshots taken for acceptance.
    """
    s = bare_session()

    class Busy:
        def done(self):
            return False

    s.turn = Busy()
    assert s.start_text_turn("你好") is None

    s.turn = None
    task = s.start_text_turn("你好")
    assert task is not None
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


# --- the six-state pushes (C2/C3) --------------------------------------------

async def test_listening_face_pushed_on_listen_start(capsys):
    s = bare_session()
    await s._on_json(json.dumps({"type": "listen", "state": "start",
                                 "mode": "auto"}), None)
    assert emotions(s.ws.sent) == ["happy"]
    assert "state listening -> happy" in capsys.readouterr().out


async def test_confirm_pending_face_is_not_overridden_by_listen_start():
    """The confused face must survive the device returning to Listening."""
    s = bare_session()
    await s._push_state_face("confirm-pending")
    s.pending_confirm = {"name": "self.reboot", "arguments": {},
                         "expires": 1e18}
    s.ws.sent.clear()
    await s._on_json(json.dumps({"type": "listen", "state": "start",
                                 "mode": "auto"}), None)
    assert emotions(s.ws.sent) == []


async def test_barge_startle_is_not_overridden_by_listen_start():
    s = bare_session()
    await s._push_state_face("barge-in")
    s.ws.sent.clear()
    await s._on_json(json.dumps({"type": "listen", "state": "start",
                                 "mode": "auto"}), None)
    assert emotions(s.ws.sent) == []


async def test_working_face_pushed_around_tool_call(capsys):
    s = bare_session()
    original_send = s._safe_send

    async def resolving_send(data):
        await original_send(data)
        if isinstance(data, str):
            msg = json.loads(data)
            if msg.get("type") == "mcp":
                fut = s._pending.get(msg["payload"]["id"])
                if fut is not None and not fut.done():
                    fut.set_result('{"ok": true}')

    s._safe_send = resolving_send
    result = await s.call_device_tool("take_photo", {"question": "这是什么"})
    assert result == '{"ok": true}'
    # C1a: tool-running -> angry, the follow-up thinking -> confused; both are
    # distinct looks, so two frames are expected.
    assert emotions(s.ws.sent) == ["angry", "confused"]
    out = capsys.readouterr().out
    assert "state tool-running -> angry" in out
    assert "state thinking -> confused" in out


async def test_confirm_pending_face_pushed_when_pending_is_created(capsys):
    s = bare_session()
    s.confirm_tools = {"self.reboot"}
    spoken = []

    async def say_text(t0, sentence):
        spoken.append(sentence)

    s._say_text = say_text
    result = json.loads(await s.call_device_tool("self.reboot", {"delay": 0}))
    try:
        assert result["needs_confirmation"] is True
        assert emotions(s.ws.sent) == ["shocked"]
        assert spoken == ["我要重启这台设备（延迟秒数=0），确认吗？"]
        out = capsys.readouterr().out
        assert "state confirm-pending -> shocked" in out
    finally:
        s._drop_pending()


def test_unknown_state_pushes_idle_look():
    """`map_state_to_emotion("nonsense")` is idle's own look, not neutral."""
    assert persona.normalize_state("nonsense") == "idle"
    assert persona.map_state_to_emotion("nonsense") == "idle"
    assert persona.map_state_to_emotion("nonsense") != "neutral"


async def test_handshake_pushes_listening_face(monkeypatch):
    """Session ready is the other listening edge (besides listen start)."""
    s = bare_session()

    async def recv():
        return json.dumps({
            "type": "hello",
            "audio_params": {"sample_rate": RATE, "frame_duration": 60},
        })

    s.ws.recv = recv

    async def no_flush():
        return None

    monkeypatch.setattr(s, "_flush_notifications", no_flush)
    assert await s.handshake() is True
    assert emotions(s.ws.sent) == ["happy"]


async def test_turn_end_keeps_confirm_pending_face():
    """While a yes is awaited, turn end must not paint idle over confirm-pending."""
    s = bare_session()
    await s._push_state_face("confirm-pending")
    s.pending_confirm = {"name": "self.reboot", "arguments": {},
                         "expires": 1e18}
    s.ws.sent.clear()
    s._finish_turn_face()
    await asyncio.sleep(0)
    assert emotions(s.ws.sent) == []


async def test_answer_audio_does_not_override_confirm_pending():
    s = bare_session()
    await s._push_state_face("confirm-pending")
    s.pending_confirm = {"name": "self.reboot", "arguments": {},
                         "expires": 1e18}
    s.ws.sent.clear()
    await s._speak("请确认。", np.zeros(960, dtype=np.int16), 0.0, answer=True)
    assert emotions(s.ws.sent) == []
    assert s._spoke_answer is True


async def test_stale_cue_restore_does_not_override_newer_state(capsys):
    s = bare_session()
    await s._push_thinking_face(0.0)            # cue look, face_state=thinking
    s._cue_pushed = True
    await s._push_state_face("confirm-pending")
    s.ws.sent.clear()
    await s._restore_cue_face("first audio")
    assert emotions(s.ws.sent) == []
    assert "cue restore skipped" in capsys.readouterr().out


def test_working_alias_maps_to_the_tool_running_look():
    assert persona.map_state_to_emotion("working") == "angry"
    assert persona.map_state_to_emotion("tool-running") == "angry"


async def test_same_emotion_state_change_is_not_resent(capsys):
    s = bare_session()
    await s._push_state_face("barge-in")            # shocked
    s.ws.sent.clear()
    await s._push_state_face("confirm-pending")     # also shocked
    assert emotions(s.ws.sent) == []
    assert "state confirm-pending -> shocked (unchanged, not resent)" in \
        capsys.readouterr().out
