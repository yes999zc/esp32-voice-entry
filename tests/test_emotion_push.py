"""`POST /debug/emotion`: authenticated expression push to live sessions.

The app is built exactly like production — `ota.build_app` (real Bearer
middleware) + `vision.make_router` — and served by an aiohttp TestServer on an
ephemeral port. Sessions are fakes: no device is touched and `server.py` is
never imported, so no ASR/TTS/LLM/Opus library is loaded.

Two facts are checked from the outside, because `session.py` cannot be imported
here (`audio.py` loads the Opus dynamic library at import time, which pytest
does not have):
- the route calls `Session.push_emotion(name)` once per target session;
- `Session.push_emotion` sends `protocol.llm_emotion(...)`, i.e. the exact
  `{"type":"llm","emotion":...}` frame the firmware dispatches in any state.
"""
import ast
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ota  # noqa: E402
import persona  # noqa: E402
import protocol  # noqa: E402
import vision  # noqa: E402

CONTROL = "test-control-token"
SESSION_SRC = ROOT / "src" / "session.py"


class FakeSession:
    """Records `push_emotion` instead of talking to a device."""

    def __init__(self, session_id):
        self.session_id = session_id
        self.emotions = []

    async def push_emotion(self, name):
        self.emotions.append(name)


def make_cfg(tmp_path):
    return {
        "server": {
            "ws_url": "ws://127.0.0.1:4410",
            "vision_url": "http://127.0.0.1:4411/xiaozhi/vision",
            "vision_token": "",
            "timezone_minutes": 480,
            "ota_port": 4411,
        },
        "security": {"control_token_file": str(tmp_path / "control.token")},
    }


def build_app(cfg, sessions):
    return ota.build_app(
        cfg,
        extras=(vision.make_router(cfg, lambda: list(sessions)),),
        control_token=CONTROL,
    )


@asynccontextmanager
async def running(sessions, tmp_path):
    client = TestClient(TestServer(build_app(make_cfg(tmp_path), sessions)))
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


def auth(token=CONTROL):
    return {"Authorization": f"Bearer {token}"}


# ---------------- auth gate (the route must not be anonymous) ----------------

async def test_missing_token_is_401_and_sends_nothing(tmp_path):
    sessions = [FakeSession("abc123")]
    async with running(sessions, tmp_path) as client:
        resp = await client.post("/debug/emotion", json={"emotion": "happy"})
        assert resp.status == 401
        assert await resp.json() == {"ok": False, "error": "unauthorized"}
    assert sessions[0].emotions == []


async def test_wrong_token_is_401(tmp_path):
    sessions = [FakeSession("abc123")]
    async with running(sessions, tmp_path) as client:
        resp = await client.post("/debug/emotion", json={"emotion": "happy"},
                                 headers=auth("not-the-token"))
        assert resp.status == 401
    assert sessions[0].emotions == []


# ---------------- push behaviour ----------------

async def test_push_reaches_every_live_session(tmp_path):
    sessions = [FakeSession("abc123"), FakeSession("def456")]
    async with running(sessions, tmp_path) as client:
        resp = await client.post("/debug/emotion", json={"emotion": "happy"},
                                 headers=auth())
        assert resp.status == 200
        assert await resp.json() == {"sent": 2, "emotion": "happy"}
    assert [s.emotions for s in sessions] == [["happy"], ["happy"]]


async def test_push_idle_is_accepted(tmp_path):
    """C1a: `idle` is a real emotion name, so /debug/emotion accepts it."""
    sessions = [FakeSession("abc123")]
    async with running(sessions, tmp_path) as client:
        resp = await client.post("/debug/emotion", json={"emotion": "idle"},
                                 headers=auth())
        assert resp.status == 200
        assert await resp.json() == {"sent": 1, "emotion": "idle"}
    assert sessions[0].emotions == ["idle"]


async def test_session_prefix_filters_targets(tmp_path):
    sessions = [FakeSession("abc123"), FakeSession("def456")]
    async with running(sessions, tmp_path) as client:
        resp = await client.post("/debug/emotion",
                                 json={"emotion": "thinking", "session": "abc"},
                                 headers=auth())
        assert resp.status == 200
        assert await resp.json() == {"sent": 1, "emotion": "thinking"}
    assert sessions[0].emotions == ["thinking"]
    assert sessions[1].emotions == []


async def test_unknown_emotion_is_400_and_sends_nothing(tmp_path):
    sessions = [FakeSession("abc123")]
    async with running(sessions, tmp_path) as client:
        resp = await client.post("/debug/emotion", json={"emotion": "angry-happy"},
                                 headers=auth())
        assert resp.status == 400
        body = await resp.json()
        assert body["error"] == "unknown emotion: angry-happy"
        assert "happy" in body["known"]
    assert sessions[0].emotions == []


@pytest.mark.parametrize("body", [{}, {"emotion": ""}, {"emotion": 42}])
async def test_missing_emotion_is_400(tmp_path, body):
    sessions = [FakeSession("abc123")]
    async with running(sessions, tmp_path) as client:
        resp = await client.post("/debug/emotion", json=body, headers=auth())
        assert resp.status == 400
    assert sessions[0].emotions == []


async def test_no_live_session_is_200_sent_zero(tmp_path):
    async with running([], tmp_path) as client:
        resp = await client.post("/debug/emotion", json={"emotion": "happy"},
                                 headers=auth())
        assert resp.status == 200
        assert await resp.json() == {"sent": 0, "emotion": "happy"}


async def test_prefix_matching_nothing_is_200_sent_zero(tmp_path):
    sessions = [FakeSession("abc123")]
    async with running(sessions, tmp_path) as client:
        resp = await client.post("/debug/emotion",
                                 json={"emotion": "happy", "session": "zzz"},
                                 headers=auth())
        assert resp.status == 200
        assert await resp.json() == {"sent": 0, "emotion": "happy"}
    assert sessions[0].emotions == []


# ---------------- the wire frame ----------------

def test_protocol_payload_is_the_firmware_llm_frame():
    """`llm_emotion` is reused, not re-invented: same shape the firmware reads."""
    payload = json.loads(protocol.llm_emotion("happy", "abc123"))
    assert payload == {"session_id": "abc123", "type": "llm", "emotion": "happy"}


def test_session_push_emotion_sends_protocol_llm_emotion():
    """Static wiring check; see the module docstring for why session.py is not
    imported (Opus dynamic library)."""
    tree = ast.parse(SESSION_SRC.read_text())
    method = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "push_emotion"
    )
    calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)]
    assert any(isinstance(c.func, ast.Attribute) and c.func.attr == "_safe_send"
               for c in calls), "push_emotion must send through _safe_send"
    protocol_calls = [
        c for c in calls
        if isinstance(c.func, ast.Attribute)
        and isinstance(c.func.value, ast.Name)
        and c.func.value.id == "protocol"
    ]
    assert [c.func.attr for c in protocol_calls] == ["llm_emotion"]


# ---------------- persona vocabulary ----------------

def test_persona_states_match_rui_led_states():
    """Word list is rui's LED_STATES (MIT, schema.py:128), not a new dialect."""
    assert persona.STATES == (
        "off", "listening", "thinking", "speaking", "wake", "error",
        "music", "music_paused", "muted",
    )


def test_persona_imports_stdlib_only():
    """persona.py must stay importable offline (no aiohttp / models / Opus)."""
    tree = ast.parse((ROOT / "src" / "persona.py").read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    assert modules == {"enum"}


@pytest.mark.parametrize("state,emotion", [
    ("idle", "idle"),
    ("listening", "happy"),
    ("thinking", "confused"),
    ("speaking", "speaking"),
    ("tool-running", "angry"),
    ("confirm-pending", "shocked"),
])
def test_step1_states_map_to_their_own_expression(state, emotion):
    """C1a: six states -> six distinct names (the C1 firmware routes six EAFs)."""
    assert persona.map_state_to_emotion(state) == emotion


@pytest.mark.parametrize("state", ["off", "wake", "error", "music",
                                   "music_paused", "muted"])
def test_other_states_fall_back_to_neutral(state):
    """rui aliases stay on the neutral baseline."""
    assert persona.map_state_to_emotion(state) == "neutral"


@pytest.mark.parametrize("state", ["", "   ", "nonsense"])
def test_unknown_states_fall_back_to_idle(state):
    """C1a: unknown states normalise to idle, which has its own look."""
    assert persona.map_state_to_emotion(state) == "idle"


def test_state_mapping_tolerates_case_and_space():
    assert persona.map_state_to_emotion("  Thinking ") == "confused"


def test_known_emotions_cover_firmware_and_persona_names():
    assert "happy" in persona.EMOTION_NAMES
    assert "neutral" in persona.EMOTION_NAMES
    # C1a: idle is a native name the /debug/emotion validator must accept.
    assert "idle" in persona.EMOTION_NAMES
    # Persona looks kept for compatibility with the pre-C1a contract.
    assert {"listening", "speaking"} <= persona.EMOTION_NAMES
    assert not persona.is_emotion("happy-happy")
    assert not persona.is_emotion("")
    assert not persona.is_emotion(None)
