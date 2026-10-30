"""B1 server-side mute switch: persistence, 4410 gate, HTTP control plane.

`session.py` imports the Opus native library at module import time, which is not
available on the dev host (same reason as tests/test_proactive.py), so it is
loaded with `opuslib` stubbed. The mute module itself is pure standard library.
"""
import asyncio
import datetime
import json
import stat
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import mute  # noqa: E402
import ota  # noqa: E402
import proactive  # noqa: E402
import vision  # noqa: E402

CONTROL = "test-control-token"
NOW = datetime.datetime(2026, 10, 28, 14, 0, 0)


def state_at(tmp_path, *, clock=None, monotonic=None, log=None,
             log_interval_s=60.0, name="mute.json"):
    return mute.MuteState(tmp_path / name, log_interval_s=log_interval_s,
                          clock=clock or (lambda: NOW),
                          monotonic=monotonic,
                          log=log)


# ---------------- persistence ----------------

def test_missing_file_means_unmuted(tmp_path):
    state = state_at(tmp_path)
    assert state.load() is False
    assert state.muted is False
    assert state.since is None
    status = state.status()
    assert status["muted"] is False
    assert status["mode"] == "A"
    assert "设备仍在采集并上传" in status["mode_note"]
    assert status["counters"] == {"frames_in": 0, "frames_dropped": 0,
                                  "frames_accepted": 0, "turns": 0}


def test_switch_persists_atomically_with_0600(tmp_path):
    state = state_at(tmp_path)
    ok, error = state.set_muted(True, changed_by="test")
    assert (ok, error) == (True, None)
    path = tmp_path / "mute.json"
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # No partially written temp file is left behind.
    assert list(tmp_path.glob(".mute-*.tmp")) == []
    payload = json.loads(path.read_text())
    assert payload["muted"] is True
    assert payload["changed_by"] == "test"
    assert payload["since"] == "2026-10-28T14:00:00"
    assert payload["updated_at"] == "2026-10-28T14:00:00"

    # A new process (fresh object) reads the same truth back.
    reloaded = mute.MuteState(path, clock=lambda: NOW)
    assert reloaded.load() is True
    assert reloaded.muted is True
    assert reloaded.since == NOW

    assert state.set_muted(False)[0] is True
    assert json.loads(path.read_text())["since"] is None
    assert mute.MuteState(path).load() is True
    assert mute.MuteState(path).muted is False


def test_write_failure_keeps_memory_unchanged(tmp_path):
    # A directory at the target path makes os.replace fail; the switch must not
    # change in memory when the file could not be written.
    path = tmp_path / "mute.json"
    path.mkdir()
    state = mute.MuteState(path, clock=lambda: NOW, log=lambda line: None)
    ok, error = state.set_muted(True)
    assert ok is False and error == "persist failed"
    assert state.muted is False
    assert state.updated_at is None
    assert list(tmp_path.glob(".mute-*.tmp")) == []


def test_repeating_same_value_is_a_noop(tmp_path):
    logs: list[str] = []
    state = state_at(tmp_path, log=logs.append)
    assert state.set_muted(True)[0] is True
    first = state.status()
    logs.clear()
    assert state.set_muted(True)[0] is True
    second = state.status()
    assert second["updated_at"] == first["updated_at"]
    assert logs == []                       # no second switch line
    # Counter cycle only resets on a real transition.
    state.note_frame()
    assert state.status()["counters"]["frames_in"] == 1
    assert state.set_muted(True)[0] is True
    assert state.status()["counters"]["frames_in"] == 1


def test_counters_and_minute_summary(tmp_path):
    ticks = {"now": 0.0}
    logs: list[str] = []
    state = state_at(tmp_path, monotonic=lambda: ticks["now"],
                     log=logs.append, log_interval_s=60.0)
    state.set_muted(True)
    logs.clear()
    state.note_frame()
    state.note_frame()
    assert state.status()["counters"] == {"frames_in": 2, "frames_dropped": 2,
                                          "frames_accepted": 0, "turns": 0}
    assert state.last_frame_at == NOW
    assert logs == []                       # not yet 60 s
    ticks["now"] = 60.0
    state.note_frame()
    assert logs == ["[mute] frames_in=3 dropped=3 accepted=0 turns=0"]


def test_previous_cycle_snapshot(tmp_path):
    state = state_at(tmp_path)
    state.note_frame()
    state.note_frame()
    state.note_turn()
    state.set_muted(True)
    status = state.status()
    assert status["counters"]["frames_in"] == 0
    assert status["previous"]["frames_accepted"] == 2
    assert status["previous"]["turns"] == 1
    assert status["previous"]["ended_at"] == "2026-10-28T14:00:00"


def test_process_singleton_is_injectable(tmp_path):
    previous = mute.get_state()
    try:
        installed = mute.configure(tmp_path / "mute.json", clock=lambda: NOW)
        assert mute.get_state() is installed
    finally:
        mute._STATE = previous


# ---------------- 4410 gate (Session._on_audio) ----------------

_SESSION = None


def load_session():
    global _SESSION
    if _SESSION is None:
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "opuslib", types.ModuleType("opuslib"))
            import session as module
        _SESSION = module
    return _SESSION


class FakeWs:
    def __init__(self):
        self.sent: list = []

    async def send(self, data):
        self.sent.append(data)


class CountingCodec:
    def __init__(self):
        self.decodes = 0

    def decode(self, frame):
        self.decodes += 1
        return np.zeros(960, dtype=np.int16)


class CountingVad:
    def __init__(self):
        self.frames = 0

    def accept_waveform(self, samples):
        self.frames += 1


class FakeTts:
    def __init__(self):
        self.synths = 0

    async def synth(self, text):
        self.synths += 1
        return np.zeros(8, dtype=np.int16), 16000


def real_session_cfg():
    return {
        "audio": {"sample_rate": 16000, "frame_ms": 60, "channels": 1},
        "llm": {"provider": "deepseek", "model": "fake",
                "routing": {"enabled": False}, "max_tool_rounds": 1,
                "device_tools": False, "stream_tts": False},
        "conversation": {"thinking_face": "", "cue_restore_face": "",
                         "filler_chime_ms": 0, "barge_in": True},
        "safety": {"confirm_tools": []},
    }


def make_session(mute_state, codec=None, tts=None):
    session_mod = load_session()
    session = session_mod.Session(FakeWs(), real_session_cfg(), codec or CountingCodec(),
                                  tts or FakeTts(), None, FakeLlm(), mute=mute_state)
    return session_mod, session


class FakeLlm:
    provider = "deepseek"
    model = "fake"


async def test_muted_gate_drops_before_decode(tmp_path):
    state = state_at(tmp_path)
    state.set_muted(True)
    session_mod, session = make_session(state)
    codec = session.codec
    vad = CountingVad()
    # pop_segments / ASR / turn must never be reached: any call would explode.
    import session as live_session_module
    original_pop = live_session_module.pop_segments
    live_session_module.pop_segments = lambda vad: pytest.fail("pop_segments reached")
    try:
        for _ in range(3):
            await session._on_audio(b"frame", vad)
    finally:
        live_session_module.pop_segments = original_pop
    assert codec.decodes == 0
    assert vad.frames == 0
    assert session.turn is None
    status = state.status()
    assert status["counters"] == {"frames_in": 3, "frames_dropped": 3,
                                  "frames_accepted": 0, "turns": 0}
    assert status["last_frame_at"] == "2026-10-28T14:00:00"


async def test_unmuted_frames_are_decoded_and_turn_counted(tmp_path):
    state = state_at(tmp_path)
    session_mod, session = make_session(state)
    vad = CountingVad()

    async def fake_turn(segment):
        return None

    session._handle_turn = fake_turn
    import session as live_session_module
    original_pop = live_session_module.pop_segments
    live_session_module.pop_segments = lambda vad: [np.zeros(8000, dtype=np.int16)]
    session.turn = None
    try:
        await session._on_audio(b"frame", vad)
    finally:
        live_session_module.pop_segments = original_pop
    await asyncio.sleep(0)
    assert session.codec.decodes == 1
    assert vad.frames == 1
    counters = state.status()["counters"]
    assert counters["frames_accepted"] == 1
    assert counters["frames_dropped"] == 0
    assert counters["turns"] == 1
    assert state.status()["last_frame_at"] == "2026-10-28T14:00:00"


async def test_muted_gate_drops_before_speaking_branch(tmp_path):
    """Regression: a gate moved *after* the speaking branch would decode + VAD.

    The muted board may still be in Speaking (a turn started just before the
    switch), so the gate must run before `codec.decode` regardless of the
    speaking flag.
    """
    state = state_at(tmp_path)
    state.set_muted(True)
    session_mod, session = make_session(state)
    session.speaking = True
    vad = CountingVad()

    async def fail_barge(pcm):
        pytest.fail("_barge_watch reached while muted")

    session._barge_watch = fail_barge
    await session._on_audio(b"frame", vad)

    assert session.codec.decodes == 0
    assert vad.frames == 0
    assert session.turn is None
    assert state.status()["counters"] == {"frames_in": 1, "frames_dropped": 1,
                                          "frames_accepted": 0, "turns": 0}


async def test_unmuted_speaking_frames_still_take_the_barge_path(tmp_path):
    """The control case: with the switch off, the same speaking frame passes."""
    state = state_at(tmp_path)
    session_mod, session = make_session(state)
    session.speaking = True
    vad = CountingVad()
    barge_calls: list = []

    async def fake_barge(pcm):
        barge_calls.append(1)
        return False

    session._barge_watch = fake_barge
    await session._on_audio(b"frame", vad)

    assert session.codec.decodes == 1
    assert vad.frames == 1
    assert barge_calls == [1]
    assert session.turn is None
    counters = state.status()["counters"]
    assert counters["frames_accepted"] == 1
    assert counters["frames_dropped"] == 0


async def test_muted_speech_paths_refuse(tmp_path):
    state = state_at(tmp_path)
    state.set_muted(True)
    session_mod, session = make_session(state)

    assert await session.speak_announcement("你好") is False
    assert session.tts.synths == 0
    assert await session.send_notify("http://x/a.ogg", "通知") is False
    assert session.ws.sent == []


async def test_flush_notifications_does_not_take_while_muted(tmp_path, monkeypatch):
    state = state_at(tmp_path)
    state.set_muted(True)
    session_mod, session = make_session(state)
    calls = []
    logs: list[tuple] = []
    session.log = lambda *parts: logs.append(parts)
    monkeypatch.setattr(session_mod, "take_notifications",
                        lambda: calls.append(1) or [])
    await session._flush_notifications()
    assert calls == []
    assert any("queued notifications held" in " ".join(map(str, row))
               for row in logs)


# ---------------- HTTP control plane ----------------

def http_cfg(tmp_path):
    return {
        "server": {"ws_url": "ws://127.0.0.1:4410",
                   "vision_url": "http://127.0.0.1:4411/xiaozhi/vision",
                   "vision_token": "", "timezone_minutes": 480,
                   "ota_port": 4411},
        "security": {"control_token_file": str(tmp_path / "control.token")},
        "mute": {"path": str(tmp_path / "mute.json")},
        "proactive": {"enabled": False, "dry_run": True},
    }


@asynccontextmanager
async def running_app(tmp_path, state):
    cfg = http_cfg(tmp_path)
    app = ota.build_app(
        cfg,
        extras=(vision.make_router(cfg, lambda: [], mute_state=state),),
        control_token=CONTROL)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


def auth(token=CONTROL):
    return {"Authorization": f"Bearer {token}"}


async def test_mute_routes_require_bearer(tmp_path):
    state = state_at(tmp_path)
    async with running_app(tmp_path, state) as client:
        assert (await client.get("/debug/mute")).status == 401
        assert (await client.post("/debug/mute",
                                  json={"muted": True})).status == 401
        assert (await client.get("/debug/mute",
                                 headers=auth("wrong"))).status == 401


async def test_mute_get_and_post_flow(tmp_path):
    state = state_at(tmp_path)
    async with running_app(tmp_path, state) as client:
        resp = await client.get("/debug/mute", headers=auth())
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert data["muted"] is False
        assert data["mode"] == "A"
        assert "设备仍在采集并上传" in data["mode_note"]
        assert set(data["counters"]) == {"frames_in", "frames_dropped",
                                         "frames_accepted", "turns"}
        assert set(data["catchup"]) >= {"pending", "missed"}
        assert data["persisted_path"] == str(tmp_path / "mute.json")

        resp = await client.post("/debug/mute", json={"muted": True},
                                 headers=auth())
        assert resp.status == 200
        data = await resp.json()
        assert data["changed"] is True and data["muted"] is True
        assert json.loads((tmp_path / "mute.json").read_text())["muted"] is True

        # Repeating the same value is accepted but reports no change.
        data = await (await client.post("/debug/mute", json={"muted": True},
                                        headers=auth())).json()
        assert data["changed"] is False and data["muted"] is True

        data = await (await client.post("/debug/mute", json={"muted": False},
                                        headers=auth())).json()
        assert data["changed"] is True and data["muted"] is False
        assert "catchup" in data


async def test_mute_post_rejects_bad_bodies(tmp_path):
    state = state_at(tmp_path)
    async with running_app(tmp_path, state) as client:
        for body in ({}, {"muted": "yes"}, {"muted": 1}, [True]):
            resp = await client.post("/debug/mute", json=body, headers=auth())
            assert resp.status == 400, body
        resp = await client.post("/debug/mute", data=b"not json",
                                 headers={**auth(),
                                          "Content-Type": "application/json"})
        assert resp.status == 400


async def test_mute_post_500_when_persist_fails(tmp_path):
    path = tmp_path / "mute.json"
    path.mkdir()
    state = mute.MuteState(path)
    async with running_app(tmp_path, state) as client:
        resp = await client.post("/debug/mute", json={"muted": True},
                                 headers=auth())
        assert resp.status == 500
        assert (await resp.json())["muted"] is False
        assert state.muted is False


async def test_mute_off_runs_catchup_once(tmp_path):
    """HTTP off -> controller.start_catchup(); a second off does nothing."""
    state = state_at(tmp_path)
    state.set_muted(True)

    class CatchupController:
        def __init__(self):
            self.starts = 0
            self.worker_task = None

        def catchup_status(self):
            return {"pending": 0, "missed": 0, "spoken": 0, "last_at": None,
                    "running": False, "last_result": None}

        def start_catchup(self):
            self.starts += 1
            return True

    controller = CatchupController()
    previous = proactive.get_controller()
    proactive._CONTROLLER = controller
    try:
        async with running_app(tmp_path, state) as client:
            # Startup replaced the controller; install ours after startup.
            proactive._CONTROLLER = controller
            data = await (await client.post("/debug/mute", json={"muted": False},
                                            headers=auth())).json()
            assert data["changed"] is True
            assert data["catchup_started"] is True
            assert controller.starts == 1
            data = await (await client.post("/debug/mute", json={"muted": False},
                                            headers=auth())).json()
            assert data["changed"] is False
            assert data["catchup_started"] is False
            assert controller.starts == 1
    finally:
        proactive._CONTROLLER = previous


class SlowCatchupSession:
    """A live session whose announcement blocks until the test releases it."""

    def __init__(self):
        self.alive = True
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.spoken: list[str] = []

    async def speak_announcement(self, text):
        self.entered.set()
        await self.release.wait()
        self.spoken.append(text)
        return True


async def test_mute_off_returns_before_a_slow_catchup_finishes(tmp_path):
    """POST off must not await TTS: fast 200 + background task + GET progress."""
    state = state_at(tmp_path)
    state.set_muted(True)
    session = SlowCatchupSession()
    controller = proactive.ProactiveController(
        lambda: [session],
        {"proactive": {"enabled": False},
         "mute": {"catchup_window_min": 10, "catchup_max_items": 2}},
        mute=state, log=lambda line: None)
    now = datetime.datetime.now().replace(microsecond=0)
    controller.add_reminder("喝水", now - datetime.timedelta(minutes=1), now)

    previous = proactive.get_controller()
    proactive._CONTROLLER = controller
    try:
        async with running_app(tmp_path, state) as client:
            proactive._CONTROLLER = controller
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            resp = await client.post("/debug/mute", json={"muted": False},
                                     headers=auth())
            elapsed = loop.time() - t0
            data = await resp.json()
            assert resp.status == 200
            assert elapsed < 0.5, elapsed
            assert data["catchup_started"] is True

            await asyncio.wait_for(session.entered.wait(), 2)
            running = await (await client.get("/debug/mute",
                                              headers=auth())).json()
            assert running["catchup"]["running"] is True

            session.release.set()
            await asyncio.wait_for(controller._catchup_task, 2)
            done = await (await client.get("/debug/mute", headers=auth())).json()
            assert done["catchup"]["running"] is False
            assert done["catchup"]["last_result"]["spoken"] is True
            assert session.spoken == ["提醒你喝水"]
    finally:
        proactive._CONTROLLER = previous


async def test_concurrent_off_starts_only_one_catchup(tmp_path):
    """The changed decision + persist + start are inside one lock."""
    state = state_at(tmp_path)
    state.set_muted(True)

    class CountingController:
        def __init__(self):
            self.starts = 0
            self.worker_task = None

        def catchup_status(self):
            return {"pending": 0, "missed": 0, "spoken": 0, "last_at": None,
                    "running": False, "last_result": None}

        def start_catchup(self):
            self.starts += 1
            return True

    controller = CountingController()
    previous = proactive.get_controller()
    proactive._CONTROLLER = controller
    try:
        async with running_app(tmp_path, state) as client:
            proactive._CONTROLLER = controller
            responses = await asyncio.gather(
                client.post("/debug/mute", json={"muted": False}, headers=auth()),
                client.post("/debug/mute", json={"muted": False}, headers=auth()),
            )
            data = [await resp.json() for resp in responses]
            assert sum(1 for item in data if item["changed"]) == 1
            assert sum(1 for item in data if item["catchup_started"]) == 1
            assert controller.starts == 1
    finally:
        proactive._CONTROLLER = previous
