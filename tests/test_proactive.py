"""Proactive v0: whitelisted triggers, six gates, face-before-voice.

Two layers, both offline:
- `proactive.evaluate()` / `ProactiveController` with an injected clock, sleep
  and fake sessions: no aiohttp, no models, no wall clock.
- The `GET /debug/proactive/status` route through a real `ota.build_app` +
  `vision.make_router` TestServer (Bearer middleware included).

`src/session.py` cannot be imported here (it pulls the Opus dynamic library), so
its four hook call-sites are asserted from the AST instead.
"""
import ast
import asyncio
import re
import sys
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ota  # noqa: E402
import proactive  # noqa: E402
import vision  # noqa: E402
from proactive import (  # noqa: E402
    Env, Gate, ProactiveConfig, ProactiveController, ProactiveState, Trigger,
    TriggerKind, evaluate, is_dont_speak,
)

NOW = datetime(2026, 10, 27, 14, 0, 0)          # 14:00, outside the night window
CONTROL = "test-control-token"
SESSION_SRC = ROOT / "src" / "session.py"


def config(**overrides) -> ProactiveConfig:
    base = dict(enabled=True, dry_run=False, night_start=__import__("datetime").time(23, 0),
                night_end=__import__("datetime").time(8, 0), hourly_limit=2,
                topic_cooldown_min=30, mute_minutes=30, emotion_lead_ms=600,
                human_silence_seconds=10.0)
    base.update(overrides)
    return ProactiveConfig(**base)


def trigger(kind=TriggerKind.TASK_DONE, topic="task", text="办好了",
            emotion="happy") -> Trigger:
    return Trigger(kind=kind, topic=topic, text=text, emotion=emotion)


def env(**overrides) -> Env:
    base = dict(now=NOW, socket_alive=True, device_idle=True, playing=False)
    base.update(overrides)
    return Env(**base)


# ---------------- gate matrix: pass / reject for each of the six gates ----------------

@pytest.mark.parametrize("name,env_kwargs,state_kwargs,gate", [
    ("socket dead", {"socket_alive": False}, {}, Gate.NO_SESSION),
    ("device busy", {"device_idle": False}, {}, Gate.IDLE_QUIET),
    ("playing", {"playing": True}, {}, Gate.IDLE_QUIET),
    ("human 3s ago", {}, {"last_human_speech_at": NOW - timedelta(seconds=3)},
     Gate.HUMAN_SILENCE),
    ("night", {"now": NOW.replace(hour=23, minute=30)}, {}, Gate.NIGHT),
    ("topic 5min ago", {}, {"topic_last_at": {"task": NOW - timedelta(minutes=5)}},
     Gate.TOPIC_COOLDOWN),
    ("hourly used", {},
     {"spoke_at": [NOW - timedelta(minutes=10), NOW - timedelta(minutes=20)]},
     Gate.HOURLY_LIMIT),
    ("muted", {}, {"muted_until": NOW + timedelta(minutes=10)}, Gate.MANUAL_MUTE),
])
def test_each_gate_rejects(name, env_kwargs, state_kwargs, gate):
    result = evaluate(trigger(), env(**env_kwargs), ProactiveState(**state_kwargs),
                      config())
    assert result.allowed is False, name
    assert result.rejected_by is gate, name
    assert result.detail, name


@pytest.mark.parametrize("name,env_kwargs,state_kwargs", [
    ("quiet 11s", {}, {"last_human_speech_at": NOW - timedelta(seconds=11)}),
    ("just before night", {"now": NOW.replace(hour=22, minute=59, second=59)}, {}),
    ("topic 31min ago", {}, {"topic_last_at": {"task": NOW - timedelta(minutes=31)}}),
    ("hourly 1/2", {}, {"spoke_at": [NOW - timedelta(minutes=10)]}),
    ("stale hour entries", {},
     {"spoke_at": [NOW - timedelta(minutes=61), NOW - timedelta(minutes=90)]}),
    ("mute expired", {}, {"muted_until": NOW - timedelta(minutes=1)}),
    ("different topic", {}, {"topic_last_at": {"other": NOW}}),
])
def test_gates_pass(name, env_kwargs, state_kwargs):
    result = evaluate(trigger(), env(**env_kwargs), ProactiveState(**state_kwargs),
                      config())
    assert result.allowed is True, (name, result)
    assert result.rejected_by is None and result.detail == "ok"


def test_evaluate_is_pure():
    state = ProactiveState(last_human_speech_at=NOW - timedelta(seconds=2),
                           topic_last_at={"task": NOW - timedelta(minutes=1)},
                           spoke_at=[NOW - timedelta(minutes=5)],
                           rejected={"x": 1})
    before = (dict(state.topic_last_at), list(state.spoke_at),
              dict(state.rejected), state.last_human_speech_at)
    evaluate(trigger(), env(), state, config())
    assert (dict(state.topic_last_at), list(state.spoke_at),
            dict(state.rejected), state.last_human_speech_at) == before


# ---------------- priority order (Lead-approved sequence) ----------------

@pytest.mark.parametrize("env_kwargs,state_kwargs,expected", [
    ({"socket_alive": False, "now": NOW.replace(hour=2)},
     {"last_human_speech_at": NOW}, Gate.NO_SESSION),
    ({"device_idle": False, "now": NOW.replace(hour=2)},
     {"last_human_speech_at": NOW}, Gate.IDLE_QUIET),
    ({"now": NOW.replace(hour=2)}, {"last_human_speech_at": NOW}, Gate.HUMAN_SILENCE),
    ({"now": NOW.replace(hour=2)},
     {"topic_last_at": {"task": NOW - timedelta(minutes=1)},
      "spoke_at": [NOW - timedelta(minutes=5)]}, Gate.NIGHT),
    ({}, {"topic_last_at": {"task": NOW - timedelta(minutes=1)},
          "spoke_at": [NOW - timedelta(minutes=5)],
          "muted_until": NOW + timedelta(minutes=5)}, Gate.TOPIC_COOLDOWN),
    ({}, {"spoke_at": [NOW - timedelta(minutes=5)],
          "muted_until": NOW + timedelta(minutes=5)}, Gate.HOURLY_LIMIT),
])
def test_gate_priority_is_fixed(env_kwargs, state_kwargs, expected):
    if "spoke_at" in state_kwargs and expected is Gate.HOURLY_LIMIT:
        state_kwargs["spoke_at"] = [NOW - timedelta(minutes=5),
                                    NOW - timedelta(minutes=15)]
    result = evaluate(trigger(), env(**env_kwargs), ProactiveState(**state_kwargs),
                      config(hourly_limit=2))
    assert result.rejected_by is expected


def test_disabled_is_not_a_gate():
    result = evaluate(trigger(), env(), ProactiveState(), config(enabled=False))
    assert result.allowed is False
    assert result.rejected_by is None
    assert result.detail == "proactive disabled"


# ---------------- numeric details (loggable, stable) ----------------

def test_rejection_details_carry_numbers():
    silence = evaluate(trigger(), env(),
                       ProactiveState(last_human_speech_at=NOW - timedelta(seconds=4.2)),
                       config())
    assert "4.2s" in silence.detail and "10s" in silence.detail

    hourly = evaluate(trigger(), env(),
                      ProactiveState(spoke_at=[NOW, NOW]), config())
    assert hourly.detail == "hourly: 2/2"

    mute = evaluate(trigger(), env(),
                    ProactiveState(muted_until=NOW + timedelta(minutes=5)),
                    config())
    assert "muted_until: 14:05" in mute.detail


# ---------------- night window boundaries ----------------

@pytest.mark.parametrize("clock,night", [
    ((22, 59, 59), False),
    ((23, 0, 0), True),
    ((7, 59, 59), True),
    ((8, 0, 0), False),
])
def test_night_boundaries(clock, night):
    at = NOW.replace(hour=clock[0], minute=clock[1], second=clock[2])
    result = evaluate(trigger(), env(now=at), ProactiveState(), config())
    assert (result.rejected_by is Gate.NIGHT) is night, clock


def test_night_window_can_be_disabled():
    same = __import__("datetime").time(0, 0)
    result = evaluate(trigger(), env(now=NOW.replace(hour=3)), ProactiveState(),
                      config(night_start=same, night_end=same))
    assert result.allowed is True


# ---------------- hourly limit boundary ----------------

@pytest.mark.parametrize("used,allowed", [(0, True), (1, True), (2, False), (3, False)])
def test_hourly_limit_boundary(used, allowed):
    state = ProactiveState(spoke_at=[NOW - timedelta(minutes=5 * i + 1)
                                     for i in range(used)])
    result = evaluate(trigger(), env(), state, config(hourly_limit=2))
    assert result.allowed is allowed


# ---------------- controller: fakes ----------------

class FakeSleep:
    def __init__(self):
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class FakeSession:
    def __init__(self, events: list, fail_speech=False):
        self.events = events
        self.alive = True
        self.speaking = False
        self.turn = None
        self.fail_speech = fail_speech
        self.emotions: list[str] = []
        self.spoken: list[str] = []

    async def push_emotion(self, name: str) -> None:
        self.events.append("emotion")
        self.emotions.append(name)

    async def speak_announcement(self, text: str) -> bool:
        self.events.append("speak")
        if self.fail_speech:
            raise RuntimeError("socket gone")
        self.spoken.append(text)
        return True


def make_controller(sessions, cfg=None, now=NOW):
    clock_now = {"now": now}
    sleeps = FakeSleep()
    logs: list[str] = []
    controller = ProactiveController(
        lambda: list(sessions),
        cfg if isinstance(cfg, ProactiveConfig) else config(**(cfg or {})),
        clock=lambda: clock_now["now"],
        sleep=sleeps,
        log=logs.append,
    )
    return controller, clock_now, sleeps, logs


# ---------------- no session: record and drop, never raise ----------------

async def test_no_session_records_and_drops():
    controller, _, sleeps, logs = make_controller([])
    record = await controller.fire(trigger())
    assert record["outcome"] == "no_session"
    assert record["spoke"] is False
    assert "no live session" in record["detail"]
    assert sleeps.calls == []                     # no face, no lead, no speech
    assert controller.state.no_session_total == 1
    assert logs and logs[0].startswith("[proactive] ")


async def test_no_session_status_reports_socket_dead():
    controller, _, _, _ = make_controller([])
    assert controller.status()["socket_alive"] is False
    assert controller.status()["today"]["no_session"] == 0


# ---------------- dry run: face -> wait -> stop before speech ----------------

async def test_dry_run_stops_before_speech():
    session = FakeSession([])
    controller, _, sleeps, _ = make_controller([session], {"dry_run": True})
    record = await controller.fire(trigger())
    assert session.events == ["emotion"]          # no speech event at all
    assert record["outcome"] == "dry_run"
    assert record["allowed"] is True              # gates passed; speech gated by dry_run
    assert record["spoke"] is False
    assert record["emotion_sent"] is True
    assert sleeps.calls == [0.6]                  # 600 ms face->voice lead
    assert controller.state.dry_run_total == 1
    assert controller.state.spoke_total == 0


async def test_dry_run_still_consumes_rate_limit_and_topic_window():
    session = FakeSession([])
    controller, _, _, _ = make_controller([session], {"dry_run": True})
    await controller.fire(trigger(topic="weather"))
    assert len(controller.state.spoke_at) == 1
    assert controller.state.topic_last_at["weather"] == NOW
    assert controller.state.last_slot_at == NOW
    assert controller.state.last_spoke_at is None      # dry run never spoke
    second = await controller.fire(trigger(topic="weather"))
    assert second["rejected_by"] == Gate.TOPIC_COOLDOWN.value


async def test_status_exposes_dry_run_and_timestamps():
    session = FakeSession([])
    controller, _, _, _ = make_controller([session], {"dry_run": True})
    await controller.fire(trigger())
    status = controller.status()
    assert status["dry_run"] is True
    assert status["socket_alive"] is True
    assert status["today"]["dry_run"] == 1
    assert status["last_emotion_sent_at"] is not None
    assert status["last_spoke_at"] is None         # dry run never spoke
    assert status["last_slot_at"] is not None      # but it did reserve a slot


# ---------------- order: face -> sleep -> speech ----------------

async def test_order_is_emotion_then_sleep_then_speech():
    events: list[str] = []
    sleeps = FakeSleep()
    session = FakeSession(events)

    async def sleep(seconds: float) -> None:
        events.append("sleep")
        await sleeps(seconds)

    controller = ProactiveController(
        lambda: [session], config(dry_run=False), clock=lambda: NOW,
        sleep=sleep, log=lambda line: None)
    record = await controller.fire(trigger())
    assert events == ["emotion", "sleep", "speak"]
    assert record["outcome"] == "spoke"
    assert record["spoke"] is True
    assert session.spoken == ["办好了"]
    assert sleeps.calls == [0.6]
    assert controller.state.topic_last_at["task"] == NOW


async def test_rejected_trigger_still_moves_the_face_and_counts():
    session = FakeSession([])
    controller, _, sleeps, _ = make_controller(
        [session], {"night_start": __import__("datetime").time(0, 0),
                    "night_end": __import__("datetime").time(23, 59)})
    record = await controller.fire(trigger())
    assert record["rejected_by"] == Gate.NIGHT.value
    assert record["allowed"] is False
    assert record["outcome"] == "face_only"
    assert session.emotions == ["happy"]
    assert sleeps.calls == []                      # no lead, no speech
    assert controller.state.rejected["night"] == 1
    assert controller.state.face_only_total == 1


async def test_speech_failure_is_face_only():
    session = FakeSession([], fail_speech=True)
    controller, _, _, _ = make_controller([session], {"dry_run": False})
    record = await controller.fire(trigger())
    assert record["outcome"] == "face_only"
    assert record["spoke"] is False
    assert controller.state.face_only_total == 1
    assert controller.state.topic_last_at == {}    # did not speak: no cooldown


# ---------------- 别说了 -> 30 min silence ----------------

@pytest.mark.parametrize("text", ["别说了", "别说了！", "你别说了，安静", "好吧 别说了。"])
def test_dont_speak_phrase_family(text):
    assert is_dont_speak(text)


@pytest.mark.parametrize("text", ["我说了", "别", "", "说了别动"])
def test_not_dont_speak(text):
    assert not is_dont_speak(text)


async def test_mute_for_thirty_minutes():
    session = FakeSession([])
    controller, clock_now, _, _ = make_controller([session])
    assert controller.note_user_text("别说了") is True
    assert controller.state.muted_until == NOW + timedelta(minutes=30)

    blocked = await controller.fire(trigger())
    assert blocked["rejected_by"] == Gate.MANUAL_MUTE.value
    assert blocked["outcome"] == "face_only"
    assert controller.status()["muted_until"] == (NOW + timedelta(minutes=30)
                                                  ).isoformat(timespec="seconds")

    clock_now["now"] = NOW + timedelta(minutes=30, seconds=1)
    allowed = await controller.fire(trigger())
    assert allowed["rejected_by"] is None


def test_plain_text_does_not_mute():
    controller, _, _, _ = make_controller([FakeSession([])])
    assert controller.note_user_text("确认") is False
    assert controller.state.muted_until is None


# ---------------- triggers: whitelist + scheduling + confirm timeout ----------------

def test_whitelist_has_exactly_four_kinds():
    assert [kind.value for kind in TriggerKind] == [
        "task_done", "scheduled", "answer_ready", "confirm_timeout"]


def test_unknown_trigger_kind_is_rejected():
    with pytest.raises(ValueError):
        Trigger(kind="freeform", topic="x", text="y")


def test_unknown_emotion_is_rejected():
    with pytest.raises(ValueError):
        Trigger(kind=TriggerKind.TASK_DONE, topic="x", text="y", emotion="smug")


async def test_scheduled_reminder_fires_once():
    session = FakeSession([])
    controller, clock_now, _, _ = make_controller([session])
    controller.schedule(trigger(TriggerKind.SCHEDULED, topic="timer",
                                text="时间到了"), NOW + timedelta(minutes=1))
    assert await controller.tick() == []            # not due yet
    clock_now["now"] = NOW + timedelta(minutes=1)
    fired = await controller.tick()
    assert [r["kind"] for r in fired] == ["scheduled"]
    clock_now["now"] = NOW + timedelta(minutes=2)
    assert await controller.tick() == []            # not repeated


async def test_confirm_timeout_fires_exactly_once():
    session = FakeSession([])
    controller, clock_now, _, _ = make_controller([session])
    controller.note_confirm_pending("self.reboot", 120)
    assert await controller.tick() == []
    clock_now["now"] = NOW + timedelta(seconds=121)
    fired = await controller.tick()
    assert [r["kind"] for r in fired] == ["confirm_timeout"]
    assert fired[0]["topic"] == "confirm:self.reboot"
    clock_now["now"] = NOW + timedelta(seconds=200)
    assert await controller.tick() == []


async def test_answered_confirm_leaves_no_reminder():
    controller, clock_now, _, _ = make_controller([FakeSession([])])
    controller.note_confirm_pending("self.reboot", 120)
    controller.clear_confirm()
    clock_now["now"] = NOW + timedelta(seconds=121)
    assert await controller.tick() == []


# ---------------- session.py hook call-sites (AST; module cannot import) ----------------

def test_session_hooks_are_wired():
    tree = ast.parse(SESSION_SRC.read_text(encoding="utf-8"))
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    for name in ("_note_human_speech", "_note_user_text",
                 "_note_confirm_pending", "_clear_confirm"):
        assert name in called, name
    methods = {node.name for node in ast.walk(tree)
               if isinstance(node, ast.AsyncFunctionDef)}
    assert "speak_announcement" in methods
    # The hooks must be no-ops when no controller was configured.
    source = SESSION_SRC.read_text(encoding="utf-8")
    assert "proactive.get_controller()" in source


# ---------------- /debug/proactive/status route ----------------

class RouteSession:
    def __init__(self):
        self.alive = True
        self.speaking = False
        self.turn = None

    async def push_emotion(self, name):
        pass

    async def speak_announcement(self, text):
        return True


def route_cfg(tmp_path, **proactive_cfg):
    block = {"enabled": True, "dry_run": True, "worker": False}
    block.update(proactive_cfg)
    return {
        "server": {"ws_url": "ws://127.0.0.1:4410",
                   "vision_url": "http://127.0.0.1:4411/xiaozhi/vision",
                   "vision_token": "", "timezone_minutes": 480, "ota_port": 4411},
        "security": {"control_token_file": str(tmp_path / "control.token")},
        "proactive": block,
    }


def build_app(cfg, sessions):
    return ota.build_app(
        cfg,
        extras=(vision.make_router(cfg, lambda: list(sessions)),),
        control_token=CONTROL,
    )


@asynccontextmanager
async def running(cfg, sessions):
    client = TestClient(TestServer(build_app(cfg, sessions)))
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


def auth(token=CONTROL):
    return {"Authorization": f"Bearer {token}"}


async def test_proactive_status_requires_bearer(tmp_path):
    async with running(route_cfg(tmp_path), [RouteSession()]) as client:
        resp = await client.get("/debug/proactive/status")
        assert resp.status == 401


async def test_proactive_status_returns_counters(tmp_path):
    async with running(route_cfg(tmp_path), [RouteSession()]) as client:
        resp = await client.get("/debug/proactive/status", headers=auth())
        assert resp.status == 200
        body = await resp.json()
    for key in ("enabled", "dry_run", "socket_alive", "night", "today",
                "hourly", "muted_until", "last_human_speech_at",
                "last_emotion_sent_at", "last_spoke_at", "recent"):
        assert key in body, key
    assert body["enabled"] is True and body["dry_run"] is True
    assert body["socket_alive"] is True
    assert body["today"] == {"attempts": 0, "spoke": 0, "face_only": 0,
                             "no_session": 0, "dry_run": 0, "rejected": {}}


async def test_status_after_a_dry_run_trigger(tmp_path):
    async with running(route_cfg(tmp_path), [RouteSession()]) as client:
        controller = proactive.get_controller()
        await controller.fire(trigger())
        resp = await client.get("/debug/proactive/status", headers=auth())
        body = await resp.json()
    assert body["today"]["attempts"] == 1
    assert body["today"]["dry_run"] == 1
    assert body["last_emotion_sent_at"] is not None


async def test_worker_not_started_when_disabled(tmp_path):
    async with running(route_cfg(tmp_path, enabled=False), [RouteSession()]) as client:
        controller = proactive.get_controller()
        assert controller is not None
        assert controller.cfg.enabled is False
        assert controller.worker_task is None
        resp = await client.get("/debug/proactive/status", headers=auth())
        assert resp.status == 200
        assert (await resp.json())["enabled"] is False


# ---------------- offline + shipped config ----------------

def test_proactive_module_imports_offline():
    """The decision core must not drag in aiohttp, numpy or any model."""
    import subprocess
    code = (
        "import sys; sys.path.insert(0, 'src'); import proactive; "
        "loaded = {'aiohttp', 'numpy', 'opuslib', 'sherpa_onnx'} & set(sys.modules); "
        "assert not loaded, loaded; print('offline ok')"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "offline ok" in proc.stdout


def test_shipped_config_parses():
    """config.yaml carries the approved defaults; a typo must not crash startup."""
    import yaml
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    parsed = ProactiveConfig.from_cfg(cfg)
    assert parsed.enabled is True
    assert parsed.dry_run is True
    assert parsed.emotion_lead_ms == 600
    assert parsed.hourly_limit == 2
    assert parsed.topic_cooldown_min == 30
    assert parsed.mute_minutes == 30
    assert parsed.human_silence_seconds == 10.0
    assert (parsed.night_start.hour, parsed.night_end.hour) == (23, 8)


def test_empty_config_falls_back_to_safe_defaults():
    parsed = ProactiveConfig.from_cfg({})
    assert parsed.enabled is True
    assert parsed.dry_run is True            # a missing block must not speak
    assert parsed.emotion_lead_ms == 600
    assert parsed.night_start.hour == 23 and parsed.night_end.hour == 8


# ---------------- worker lifecycle (mutation-proof) ----------------

async def test_worker_survives_a_failing_tick():
    """One bad tick must be logged, not kill the worker."""
    events: list[str] = []
    sleeps: list[float] = []
    logs: list[str] = []
    controller = ProactiveController(lambda: [FakeSession([])], config(),
                                     clock=lambda: NOW,
                                     sleep=lambda seconds: asyncio.sleep(0),
                                     log=logs.append)

    async def tick():
        events.append("tick")
        if len(events) == 1:
            raise RuntimeError("boom")
        return []

    async def sleep(seconds: float):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise asyncio.CancelledError

    controller.tick = tick
    controller._sleep = sleep
    with pytest.raises(asyncio.CancelledError):
        await controller.run_forever(interval=1.0)
    assert events == ["tick", "tick"]              # ran again after the failure
    assert any("tick error RuntimeError: boom" in line for line in logs)


async def test_worker_cancel_is_not_swallowed():
    controller = ProactiveController(lambda: [], config(), clock=lambda: NOW,
                                     sleep=lambda seconds: asyncio.sleep(0),
                                     log=lambda line: None)
    task = asyncio.create_task(controller.run_forever())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


def test_status_worker_alive_and_last_tick():
    # A yielding sleep: a non-yielding fake would spin the loop and starve the
    # test coroutine (caught by faulthandler while writing this test).
    controller = ProactiveController(
        lambda: [], config(), clock=lambda: NOW,
        sleep=lambda seconds: asyncio.sleep(0.001), log=lambda line: None)
    assert controller.status()["worker_alive"] is False
    assert controller.status()["last_tick_at"] is None

    async def run():
        task = asyncio.create_task(controller.run_forever())
        await asyncio.sleep(0.01)
        assert controller.status()["worker_alive"] is True
        assert controller.status()["last_tick_at"] is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())


async def test_app_starts_and_stops_the_worker(tmp_path):
    """Mutation guard: deleting the startup task or the cleanup cancel turns this red."""
    async with running(route_cfg(tmp_path, worker=True), [RouteSession()]) as client:
        controller = proactive.get_controller()
        assert controller.worker_task is not None
        assert not controller.worker_task.done()
        resp = await client.get("/debug/proactive/status", headers=auth())
        body = await resp.json()
        assert body["worker_alive"] is True
    assert controller.worker_task.done()           # cleanup cancelled and awaited
    assert controller.status()["worker_alive"] is False


async def test_cleanup_survives_an_already_dead_worker(tmp_path):
    """If the worker crashed before shutdown, cleanup must not raise."""
    async with running(route_cfg(tmp_path, worker=True), [RouteSession()]):
        controller = proactive.get_controller()

        async def crash():
            raise RuntimeError("worker already dead")

        controller.worker_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await controller.worker_task
        controller.worker_task = asyncio.create_task(crash())
        with pytest.raises(RuntimeError):
            await asyncio.shield(controller.worker_task)
    # reaching here proves cleanup did not re-raise


# ---------------- hourly limit across topics (controller level) ----------------

async def test_third_trigger_in_an_hour_is_rejected_across_topics():
    session = FakeSession([])
    controller, _, _, _ = make_controller([session], {"dry_run": False})
    first = await controller.fire(trigger(topic="one"))
    second = await controller.fire(trigger(topic="two"))
    third = await controller.fire(trigger(topic="three"))
    assert first["outcome"] == "spoke"
    assert second["outcome"] == "spoke"
    assert third["rejected_by"] == Gate.HOURLY_LIMIT.value
    assert third["detail"] == "hourly: 2/2"
    assert third["allowed"] is False


# ---------------- daily counter rollover ----------------

async def test_daily_counters_reset_on_a_new_day():
    session = FakeSession([])
    controller, clock_now, _, _ = make_controller([session], {"dry_run": False})
    await controller.fire(trigger(topic="one"))
    await controller.fire(trigger(topic="two"))
    assert controller.status()["today"]["attempts"] == 2
    clock_now["now"] = NOW + timedelta(days=1)
    status = controller.status()
    assert status["today"]["attempts"] == 0
    assert status["today"]["spoke"] == 0
    assert status["today"]["rejected"] == {}


def test_slot_pruning_drops_entries_outside_the_hour():
    state = ProactiveState(spoke_at=[NOW - timedelta(minutes=59),
                                     NOW - timedelta(minutes=61),
                                     NOW - timedelta(hours=3)])
    controller, _, _, _ = make_controller([])
    controller.state = state
    controller._prune_slots(NOW)
    assert state.spoke_at == [NOW - timedelta(minutes=59)]
    assert controller.status()["hourly"]["used"] == 1


# ---------------- config fallback: a typo must not break startup ----------------

@pytest.mark.parametrize("bad", [
    {"night_start": "25:99", "night_end": "x"},
    {"hourly_limit": "two", "topic_cooldown_min": None,
     "mute_minutes": "many", "emotion_lead_ms": []},
    {"human_silence_seconds": "soon", "enabled": "maybe", "dry_run": 3},
])
def test_bad_proactive_config_falls_back(bad):
    parsed = ProactiveConfig.from_cfg({"proactive": bad})
    assert parsed.night_start.hour == 23 and parsed.night_end.hour == 8
    assert parsed.hourly_limit == 2
    assert parsed.topic_cooldown_min == 30
    assert parsed.mute_minutes == 30
    assert parsed.emotion_lead_ms == 600
    assert parsed.human_silence_seconds == 10.0
    assert parsed.enabled is True
    assert parsed.dry_run is True


def test_string_booleans_are_understood():
    parsed = ProactiveConfig.from_cfg(
        {"proactive": {"enabled": "false", "dry_run": "yes"}})
    assert parsed.enabled is False
    assert parsed.dry_run is True


# ---------------- session hooks: behaviour, not just AST ----------------

_SESSION = None


def load_session():
    """Import `session` with opuslib stubbed (missing native lib on this host)."""
    global _SESSION
    if _SESSION is None:
        import types
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(sys.modules, "opuslib", types.ModuleType("opuslib"))
            import session as module
        _SESSION = module
    return _SESSION


class FakeTts:
    async def synth(self, text):
        import numpy as np
        return np.zeros(8, dtype=np.int16), 16000


class HookSession:
    """Minimal Session for `speak_announcement`: only tts/cfg/log/_speak matter."""

    def __init__(self):
        self.alive = True
        self.tts = FakeTts()
        self.cfg = {"audio": {"sample_rate": 16000}}
        self.spoken: list[tuple] = []
        self.logs: list[tuple] = []

    def log(self, *parts):
        self.logs.append(parts)

    async def _speak(self, text, pcm16, t0, label="tts", announce=True):
        self.spoken.append((text, label))


async def test_speak_announcement_uses_proactive_label():
    session_mod = load_session()
    fake = HookSession()
    speak = session_mod.Session.speak_announcement.__get__(fake)
    assert await speak("该喝水了") is True
    assert fake.spoken[0][0] == "该喝水了"
    assert fake.spoken[0][1] == "proactive"

    fake.alive = False
    assert await speak("sock dead") is False
    assert len(fake.spoken) == 1


async def test_speak_announcement_returns_false_on_synth_failure():
    session_mod = load_session()

    class BrokenTts:
        async def synth(self, text):
            raise RuntimeError("tts down")

    fake = HookSession()
    fake.tts = BrokenTts()
    speak = session_mod.Session.speak_announcement.__get__(fake)
    assert await speak("x") is False
    assert fake.spoken == []


def test_session_hooks_drive_the_controller():
    session_mod = load_session()
    previous = proactive.get_controller()
    try:
        controller = proactive.configure(
            {"proactive": {"mute_minutes": 30}}, lambda: [])
        session_mod._note_human_speech()
        assert controller.state.last_human_speech_at is not None

        session_mod._note_user_text("确认")           # not the mute phrase
        assert controller.state.muted_until is None
        session_mod._note_user_text("别说了")
        assert controller.state.muted_until is not None

        session_mod._note_confirm_pending("self.reboot", 120)
        assert controller.state.confirm_deadline is not None
        session_mod._clear_confirm()
        assert controller.state.confirm_deadline is None
    finally:
        proactive._CONTROLLER = previous


def test_session_hooks_are_noops_without_a_controller():
    session_mod = load_session()
    previous = proactive.get_controller()
    try:
        proactive._CONTROLLER = None
        session_mod._note_human_speech()
        assert session_mod._note_user_text("别说了") is None
        session_mod._note_confirm_pending("self.reboot", 120)
        session_mod._clear_confirm()
    finally:
        proactive._CONTROLLER = previous


# ================= task-18: three trigger sources =================
#
# A: reminder parsed from user text -> /debug/reminder CRUD -> tick -> speech.
# B: barge/abort cancels a turn before any audio -> TASK_DONE queued.
# C: reply finishes after the socket died -> ANSWER_READY queued.
# B and C share one queue (turn-id dedupe, cap 5, 30 min TTL) that only speaks
# with a live session; each chain is asserted as emotion -> 600 ms -> speech.

REMINDER_NOW = datetime(2026, 10, 27, 14, 0, 0)


# ---------------- trigger A: parsing (four classes + non-reminders) ----------------

@pytest.mark.parametrize("text,minutes,content", [
    ("3分钟后提醒我喝水", 3, "喝水"),
    ("五分钟后叫我关火", 5, "关火"),
    ("半小时后提醒我关火", 30, "关火"),
    ("一个半小时后叫我开会", 90, "开会"),
])
def test_parse_reminder_relative(text, minutes, content):
    parsed = proactive.parse_reminder(text, REMINDER_NOW)
    assert parsed is not None
    when, said = parsed
    assert when == REMINDER_NOW + timedelta(minutes=minutes)
    assert said == content


@pytest.mark.parametrize("text,expected,said", [
    ("明天9点提醒我开会", datetime(2026, 10, 28, 9, 0), "开会"),
    ("明天 9 点半提醒我", datetime(2026, 10, 28, 9, 30), ""),
])
def test_parse_reminder_tomorrow(text, expected, said):
    parsed = proactive.parse_reminder(text, REMINDER_NOW)
    assert parsed is not None
    when, content = parsed
    assert when == expected
    assert content == said


def test_parse_reminder_clock_time_rolls_over_to_tomorrow():
    assert proactive.parse_reminder("9:30提醒我拿快递", REMINDER_NOW)[0] == \
        datetime(2026, 10, 28, 9, 30)
    morning = REMINDER_NOW.replace(hour=8)
    assert proactive.parse_reminder("9:30提醒我拿快递", morning)[0] == \
        morning.replace(hour=9, minute=30)


@pytest.mark.parametrize("text", [
    "", "今天天气不错", "帮我查一下明天天气", "说点什么吧", "提醒",
])
def test_parse_reminder_ignores_non_reminders(text):
    """Anything else must fall through to the normal conversation."""
    assert proactive.parse_reminder(text, REMINDER_NOW) is None


def test_schedule_from_text_stores_a_reminder():
    controller, _, _, _ = make_controller([])
    reminder = controller.schedule_from_text("3分钟后提醒我喝水", REMINDER_NOW)
    assert reminder["text"] == "喝水"
    assert reminder["at"] == (REMINDER_NOW + timedelta(minutes=3)) \
        .isoformat(timespec="seconds")
    assert controller.schedule_from_text("今天天气不错", REMINDER_NOW) is None


# ---------------- trigger A: CRUD + tick ----------------

def test_reminder_crud():
    controller, _, _, _ = make_controller([])
    item = controller.add_reminder("喝水", NOW + timedelta(minutes=2), NOW)
    assert set(item) == {"id", "text", "at", "created_at"}
    assert controller.list_reminders(NOW)[0]["in_seconds"] == 120
    assert controller.delete_reminder(item["id"]) is True
    assert controller.delete_reminder(item["id"]) is False
    assert controller.list_reminders(NOW) == []


async def test_reminder_fires_once_via_tick():
    session = FakeSession([])
    controller, clock_now, _, _ = make_controller([session])
    controller.add_reminder("喝水", NOW + timedelta(minutes=1), NOW)

    clock_now["now"] = NOW + timedelta(seconds=30)
    assert await controller.tick() == []
    assert len(controller.list_reminders()) == 1

    clock_now["now"] = NOW + timedelta(seconds=61)
    fired = await controller.tick()
    assert len(fired) == 1
    assert fired[0]["kind"] == "scheduled" and fired[0]["topic"].startswith("reminder:")
    assert fired[0]["outcome"] == "spoke"
    assert controller.list_reminders() == []

    clock_now["now"] = NOW + timedelta(seconds=122)
    assert await controller.tick() == []          # never re-fires


# ---------------- queue: dedupe / cap / TTL / retry / dry run / no session ----------------

def test_pending_dedupes_by_turn_id():
    controller, _, _, _ = make_controller([])
    assert controller.enqueue_pending(TriggerKind.TASK_DONE, "task:t1",
                                      "报告写完了。", "t1") is True
    assert controller.enqueue_pending(TriggerKind.ANSWER_READY, "answer:t1",
                                      "报告写完了。", "t1") is False
    assert controller.pending_status()["count"] == 1


def test_pending_cap_drops_the_oldest():
    controller, _, _, _ = make_controller([], {"pending_max": 2})
    for index in range(3):
        controller.enqueue_pending(TriggerKind.TASK_DONE, f"task:t{index}",
                                   f"第{index}件事办好了。", f"t{index}")
    status = controller.pending_status()
    assert status["count"] == 2 and status["dropped"] == 1
    assert [item["turn_id"] for item in controller.state.pending] == ["t1", "t2"]


def test_pending_expires_after_ttl():
    controller, _, _, _ = make_controller([], {"pending_ttl_min": 30})
    controller.enqueue_pending(TriggerKind.TASK_DONE, "task:t1", "报告写完了。", "t1")
    status = controller.pending_status(NOW + timedelta(minutes=31))
    assert status["count"] == 0 and status["expired"] == 1


async def test_rejected_announcement_is_kept_and_retried():
    session = FakeSession([])
    session.speaking = True                      # idle_quiet gate rejects
    controller, clock_now, _, _ = make_controller(
        [session], {"pending_retry_seconds": 30})
    controller.enqueue_pending(TriggerKind.TASK_DONE, "task:t1", "报告写完了。", "t1")

    first = await controller._flush_pending(NOW)
    assert first["rejected_by"] == Gate.IDLE_QUIET.value
    assert controller.pending_status(NOW)["count"] == 1

    clock_now["now"] = NOW + timedelta(seconds=1)
    assert await controller._flush_pending(clock_now["now"]) is None   # retry throttle
    assert controller.pending_status(clock_now["now"])["count"] == 1

    session.speaking = False
    clock_now["now"] = NOW + timedelta(seconds=31)
    second = await controller._flush_pending(clock_now["now"])
    assert second["outcome"] == "spoke"
    assert controller.pending_status(clock_now["now"])["count"] == 0


async def test_dry_run_consumes_the_queue():
    session = FakeSession([])
    controller, _, _, _ = make_controller([session], {"dry_run": True})
    controller.enqueue_pending(TriggerKind.ANSWER_READY, "answer:t1",
                               "报表已经生成好了。", "t1")
    record = await controller._flush_pending(NOW)
    assert record["outcome"] == "dry_run"
    assert session.events == ["emotion"]
    assert controller.pending_status(NOW)["count"] == 0


async def test_no_live_session_keeps_queue_and_spends_no_hourly_slot():
    controller, _, _, _ = make_controller([])
    controller.enqueue_pending(TriggerKind.TASK_DONE, "task:t1", "报告写完了。", "t1")
    assert await controller.tick() == []
    assert controller.state.pending
    assert controller.state.spoke_at == []
    assert controller.state.attempts == 0


def test_status_exposes_the_pending_block():
    controller, _, _, _ = make_controller([])
    controller.enqueue_pending(TriggerKind.TASK_DONE, "task:t1", "报告写完了。", "t1")
    pending = controller.status(NOW)["pending"]
    assert pending["count"] == 1
    assert pending["by_kind"] == {"task_done": 1}
    assert pending["oldest_age_s"] == 0
    assert pending["expired"] == 0 and pending["dropped"] == 0


# ---------------- /debug/reminder (Bearer + CRUD) ----------------

@pytest.fixture
def restore_controller():
    previous = proactive.get_controller()
    try:
        yield
    finally:
        proactive._CONTROLLER = previous


async def test_debug_reminder_requires_bearer(tmp_path, restore_controller):
    async with running(route_cfg(tmp_path), [RouteSession()]) as client:
        assert (await client.get("/debug/reminder")).status == 401
        assert (await client.post("/debug/reminder",
                                  json={"text": "喝水"})).status == 401
        assert (await client.delete("/debug/reminder/r1")).status == 401


async def test_debug_reminder_relative_when_echoes_absolute_time(tmp_path,
                                                                 restore_controller):
    async with running(route_cfg(tmp_path), [RouteSession()]) as client:
        before = datetime.now()
        resp = await client.post("/debug/reminder", headers=auth(),
                                 json={"text": "喝水", "when": "+300s"})
        after = datetime.now()
        assert resp.status == 200, await resp.text()
        body = await resp.json()
        assert body["ok"] is True
        at = datetime.fromisoformat(body["reminder"]["at"])
        # Pinned by absolute time, not float equality: the server resolved
        # `+300s` against a `now` inside this request window and truncated to
        # the second, so `at` must land in [before+299 s, after+300 s].
        assert before + timedelta(seconds=299) <= at <= after + timedelta(seconds=300)
        assert abs((at - before).total_seconds() - 300) <= 1
        assert body["in_seconds"] in (299, 300)

        listed = await (await client.get("/debug/reminder", headers=auth())).json()
        assert listed["count"] == 1
        assert listed["reminders"][0]["at"] == body["reminder"]["at"]

        reminder_id = body["reminder"]["id"]
        deleted = await (await client.delete(f"/debug/reminder/{reminder_id}",
                                             headers=auth())).json()
        assert deleted == {"ok": True, "deleted": reminder_id}
        assert (await client.delete(f"/debug/reminder/{reminder_id}",
                                    headers=auth())).status == 404
        listed = await (await client.get("/debug/reminder", headers=auth())).json()
        assert listed["count"] == 0


async def test_debug_reminder_iso_when_and_natural_text(tmp_path, restore_controller):
    async with running(route_cfg(tmp_path), [RouteSession()]) as client:
        requested = datetime.now()
        target = (requested + timedelta(minutes=2)).replace(microsecond=0)
        resp = await client.post("/debug/reminder", headers=auth(),
                                 json={"text": "关火", "when": target.isoformat()})
        assert resp.status == 200
        body = await resp.json()
        # An ISO timestamp is echoed verbatim, so the absolute instant is exact.
        assert body["reminder"]["at"] == target.isoformat(timespec="seconds")
        at = datetime.fromisoformat(body["reminder"]["at"])
        assert abs((at - (requested + timedelta(minutes=2))).total_seconds()) < 1
        assert body["in_seconds"] in (119, 120)

        before = datetime.now()
        resp = await client.post("/debug/reminder", headers=auth(),
                                 json={"text": "3分钟后提醒我喝水"})
        after = datetime.now()
        assert resp.status == 200
        body = await resp.json()
        assert body["reminder"]["text"] == "喝水"
        at = datetime.fromisoformat(body["reminder"]["at"])
        assert before + timedelta(seconds=179) <= at <= after + timedelta(seconds=180)
        assert body["in_seconds"] in (179, 180)


@pytest.mark.parametrize("payload", [
    {"text": "喝水", "when": "tomorrow-ish"},
    {"text": "喝水", "when": "+0s"},
    {"text": "今天天气不错"},
    {"when": "+300s"},
])
async def test_debug_reminder_rejects_bad_payloads(tmp_path, restore_controller,
                                                   payload):
    async with running(route_cfg(tmp_path), [RouteSession()]) as client:
        resp = await client.post("/debug/reminder", headers=auth(), json=payload)
        assert resp.status == 400
        assert (await resp.json())["ok"] is False


async def test_debug_reminder_503_without_controller(tmp_path, restore_controller):
    async with running(route_cfg(tmp_path), [RouteSession()]) as client:
        proactive._CONTROLLER = None
        resp = await client.get("/debug/reminder", headers=auth())
        assert resp.status == 503
        assert (await resp.json())["ok"] is False


# ---------------- real-path chains: session.py -> queue -> announcement ----------------

class FakeWs:
    def __init__(self):
        self.sent: list = []

    async def send(self, data):
        self.sent.append(data)


class FakeCodec:
    def __init__(self, frame_count=3):
        self.frame_count = frame_count

    def frames(self, pcm16):
        for _ in range(self.frame_count):
            yield b"\x00\x00"


class FakeLlm:
    provider = "hermes"
    model = "fake-llm"

    def __init__(self, reply="日志看完了，三处报错都是超时。", on_chat=None):
        self.reply = reply
        self.on_chat = on_chat
        self.calls: list[dict] = []

    async def chat(self, messages, session_id, tools=None, on_sentence=None):
        self.calls.append({"messages": messages, "tools": tools})
        if on_sentence is not None:          # streaming path: one sentence ready
            await on_sentence(self.reply)
        if self.on_chat is not None:
            self.on_chat()
        import types as _types
        return _types.SimpleNamespace(content=self.reply, tool_calls=[], latency=0.01)


def real_session_cfg(**llm_overrides) -> dict:
    llm = {"provider": "hermes", "model": "fake", "system_prompt": "你是测试。",
           "history_rounds": 3, "max_tool_rounds": 2, "device_tools": False,
           "stream_tts": False, "routing": {"enabled": False}}
    llm.update(llm_overrides)
    return {
        "audio": {"sample_rate": 16000, "frame_ms": 60, "channels": 1},
        "llm": llm,
        "conversation": {"thinking_face": "", "max_reply_chars": 300},
        "safety": {"confirm_tools": []},
    }


def make_real_session(reply="日志看完了，三处报错都是超时。", on_chat=None,
                      **llm_overrides):
    session_mod = load_session()
    ws = FakeWs()
    session = session_mod.Session(ws, real_session_cfg(**llm_overrides),
                                  FakeCodec(), FakeTts(), None,
                                  FakeLlm(reply, on_chat=on_chat))
    return session, ws


@pytest.fixture
def clean_sessions():
    session_mod = load_session()
    before = set(session_mod._SESSIONS)
    try:
        yield
    finally:
        session_mod._SESSIONS.clear()
        session_mod._SESSIONS.update(before)


def controller_for(session, events, now=NOW, **cfg_overrides):
    """Controller whose `sleep` records into `events` so order is provable."""
    clock_now = {"now": now}
    base = {"dry_run": False}
    base.update(cfg_overrides)

    async def sleep(seconds: float) -> None:
        events.append(("sleep", seconds))

    controller = ProactiveController(
        lambda: [session], config(**base),
        clock=lambda: clock_now["now"], sleep=sleep,
        log=lambda line: None)
    return controller, clock_now


def install_order_probes(session, events):
    """Record the controller's calls while keeping the real Session methods."""
    original_emotion = session.push_emotion
    original_speak = session.speak_announcement

    async def push_emotion(name):
        events.append("emotion")
        return await original_emotion(name)

    async def speak_announcement(text):
        events.append("speak")
        return await original_speak(text)

    session.push_emotion = push_emotion
    session.speak_announcement = speak_announcement
    return original_emotion, original_speak


class use_controller:
    """Point the process-wide controller at a test instance, then restore."""

    def __init__(self, controller):
        self.controller = controller
        self.previous = None

    def __enter__(self):
        self.previous = proactive.get_controller()
        proactive._CONTROLLER = self.controller
        return self.controller

    def __exit__(self, *exc):
        proactive._CONTROLLER = self.previous
        return False


async def test_chain_a_text_turn_schedules_then_announces(clean_sessions):
    events: list = []
    session, ws = make_real_session(reply="")
    install_order_probes(session, events)
    controller, clock_now = controller_for(session, events)

    with use_controller(controller):
        await session.start_text_turn("3分钟后提醒我喝水")

        # The spoken read-back went out through the real _speak pipeline.
        assert any("提醒你喝水" in str(payload) for payload in ws.sent)
        reminders = controller.list_reminders(NOW)
        assert len(reminders) == 1
        assert reminders[0]["text"] == "喝水"
        assert reminders[0]["at"] == (NOW + timedelta(minutes=3)) \
            .isoformat(timespec="seconds")

        events.clear()
        clock_now["now"] = NOW + timedelta(minutes=3, seconds=5)
        fired = await controller.tick()

    assert fired and fired[-1]["kind"] == "scheduled"
    assert fired[-1]["outcome"] == "spoke"
    assert events == ["emotion", ("sleep", 0.6), "speak"]


async def test_chain_b_cancel_before_audio_queues_task_done(clean_sessions):
    events: list = []
    session, _ = make_real_session()
    install_order_probes(session, events)
    controller, clock_now = controller_for(session, events)
    real_speak = session._speak

    async def cancelled_speak(text, pcm16, t0, label="tts", announce=True,
                           answer=False):
        raise asyncio.CancelledError()

    session._speak = cancelled_speak
    try:
        with use_controller(controller):
            with pytest.raises(asyncio.CancelledError):
                await session._run_turn(0.0, "帮我看看日志")
    finally:
        session._speak = real_speak

    pending = controller.pending_status(NOW)
    assert pending["count"] == 1
    item = controller.state.pending[0]
    assert item["kind"] == "task_done"
    assert item["text"] == "日志看完了，三处报错都是超时。"
    assert events == []                     # nothing was played

    events.clear()
    clock_now["now"] = NOW + timedelta(seconds=5)
    session.alive = True
    flushed = await controller.tick()
    assert flushed and flushed[-1]["kind"] == "task_done"
    assert events == ["emotion", ("sleep", 0.6), "speak"]
    assert controller.pending_status(clock_now["now"])["count"] == 0


async def test_chain_b_fast_route_is_not_queued(clean_sessions):
    session, _ = make_real_session(reply="你好呀，我在。")
    session.fast_llm = FakeLlm(reply="你好呀，我在。")     # routing: fast
    controller, _ = controller_for(session, [])
    real_speak = session._speak

    async def cancelled_speak(text, pcm16, t0, label="tts", announce=True,
                           answer=False):
        raise asyncio.CancelledError()

    session._speak = cancelled_speak
    try:
        with use_controller(controller):
            with pytest.raises(asyncio.CancelledError):
                await session._run_turn(0.0, "你好")
    finally:
        session._speak = real_speak
    assert controller.pending_status(NOW)["count"] == 0


async def test_chain_b_partial_playback_is_not_queued(clean_sessions):
    session, _ = make_real_session()
    controller, _ = controller_for(session, [])
    real_speak = session._speak

    async def cancelled_speak(text, pcm16, t0, label="tts", announce=True,
                           answer=False):
        raise asyncio.CancelledError()

    session._speak = cancelled_speak
    session._first_audio_at = 0.42          # one frame already reached the board
    try:
        with use_controller(controller):
            with pytest.raises(asyncio.CancelledError):
                await session._run_turn(0.0, "帮我看看日志")
    finally:
        session._speak = real_speak
    assert controller.pending_status(NOW)["count"] == 0


async def test_chain_c_late_answer_queues_and_waits_for_a_session(clean_sessions):
    events: list = []
    session, _ = make_real_session()
    install_order_probes(session, events)
    controller, clock_now = controller_for(session, events)
    real_speak = session._speak
    spoke: list = []

    async def spy_speak(text, pcm16, t0, label="tts", announce=True,
                        answer=False):
        spoke.append(text)
        return await real_speak(text, pcm16, t0, label=label, announce=announce,
                               answer=answer)

    session._speak = spy_speak
    session.alive = False                   # the user already hung up
    try:
        with use_controller(controller):
            await session._run_turn(0.0, "帮我看看日志")
            assert spoke == []              # C returns before any playback
            assert controller.pending_status(NOW)["count"] == 1
            item = controller.state.pending[0]
            assert item["kind"] == "answer_ready"
            assert item["text"] == "日志看完了，三处报错都是超时。"

            # No live session yet: the item is kept and no hourly slot is spent.
            clock_now["now"] = NOW + timedelta(seconds=10)
            assert await controller.tick() == []
            assert controller.pending_status(clock_now["now"])["count"] == 1
            assert controller.state.spoke_at == []

            events.clear()
            session.alive = True            # the board reconnects
            clock_now["now"] = NOW + timedelta(seconds=20)
            flushed = await controller.tick()
    finally:
        session._speak = real_speak

    assert flushed and flushed[-1]["kind"] == "answer_ready"
    assert events == ["emotion", ("sleep", 0.6), "speak"]
    assert controller.pending_status(clock_now["now"])["count"] == 0


async def test_chain_c_short_reply_is_not_queued(clean_sessions):
    session, _ = make_real_session(reply="好。")
    session.alive = False
    controller, _ = controller_for(session, [])
    with use_controller(controller):
        await session._run_turn(0.0, "帮我看看日志")
    assert controller.pending_status(NOW)["count"] == 0


def test_add_reminder_normalizes_to_whole_seconds():
    """The echoed `at`, the stored instant and the tick comparison are one value.

    Parsers start from `datetime.now()`, so without truncation a reminder echoed
    as 15:05:00 could really fire at 15:05:00.6 (or 0.4 s early after rounding).
    """
    controller, _, _, _ = make_controller([])
    fractional = datetime(2026, 10, 27, 14, 0, 0, 600000)
    item = controller.add_reminder("喝水", fractional, NOW)
    assert item["at"] == "2026-10-27T14:00:00"
    assert controller.state.reminders[item["id"]]["_at"] == NOW
    # Due exactly on the second: never a tick early, never a tick late.
    assert controller._due_reminder_items(NOW - timedelta(seconds=1)) == []
    due = controller._due_reminder_items(NOW)
    assert [entry["id"] for entry in due] == [item["id"]]
    # The query is pure: only an actual `spoke`/`dry_run` consumes a reminder.
    assert item["id"] in controller.state.reminders


async def test_reminder_due_check_does_not_wait_for_the_next_second():
    session = FakeSession([])
    controller, clock_now, _, _ = make_controller([session])
    controller.add_reminder("喝水", NOW + timedelta(seconds=0.6), NOW)
    clock_now["now"] = NOW - timedelta(seconds=0.1)
    assert await controller.tick() == []
    clock_now["now"] = NOW                    # the truncated instant
    fired = await controller.tick()
    assert len(fired) == 1 and fired[0]["kind"] == "scheduled"


# ================= task-18 rev2 (reviewer CHANGES) =================
#
# §1 「我三分钟后出门」must not schedule; 「取消提醒」must delete and say so.
# §2 a due reminder survives no_session / gate rejection and retries.
# §3 a partially spoken streamed reply is not replayed in full.
# §4 enqueue during the fire window must not drop the in-flight item.
# Plus config clamping for values that would break the gates.

# ---------------- §1: intent word is mandatory ----------------

@pytest.mark.parametrize("text", [
    "我三分钟后出门",          # a plan, not a request
    "我9:30出门",
    "明天9点去公司",
    "半小时后开会",
])
def test_parse_reminder_needs_an_explicit_intent(text):
    assert proactive.has_reminder_intent(text) is False
    assert proactive.parse_reminder(text, REMINDER_NOW) is None


@pytest.mark.parametrize("text,intent", [
    ("3分钟后提醒我喝水", "提醒"),
    ("五分钟后叫我关火", "叫我"),
    ("别忘了半小时后开会", "别忘"),
    ("记得明天9点交报告", "记得"),
])
def test_parse_reminder_accepts_intent_variants(text, intent):
    assert intent in text
    assert proactive.parse_reminder(text, REMINDER_NOW) is not None


def test_cancel_latest_reminder_keeps_the_older_one():
    controller, _, _, _ = make_controller([])
    first = controller.add_reminder("喝水", NOW + timedelta(minutes=1), NOW)
    second = controller.add_reminder("关火", NOW + timedelta(minutes=2), NOW)
    assert controller.cancel_latest_reminder()["id"] == second["id"]
    assert [entry["id"] for entry in controller.list_reminders(NOW)] == [first["id"]]
    assert controller.cancel_latest_reminder()["id"] == first["id"]
    assert controller.cancel_latest_reminder() is None


@pytest.mark.parametrize("text,cancels", [
    ("取消提醒", True),
    ("不用提醒了", True),
    ("删掉提醒", True),
    ("删除提醒", True),
    ("提醒我三分钟后喝水", False),
    ("取消会议", False),
])
def test_is_reminder_cancel(text, cancels):
    assert proactive.is_reminder_cancel(text) is cancels


async def test_cancel_reminder_from_text_speaks_and_removes(clean_sessions):
    session, ws = make_real_session(reply="")
    controller, _ = controller_for(session, [])
    with use_controller(controller):
        await session.start_text_turn("3分钟后提醒我喝水")
        assert len(controller.state.reminders) == 1
        await session.start_text_turn("取消提醒")
    assert controller.state.reminders == {}
    assert any("取消了" in str(payload) for payload in ws.sent)


async def test_cancel_without_a_reminder_stays_silent(clean_sessions):
    session, ws = make_real_session(reply="")
    controller, _ = controller_for(session, [])
    with use_controller(controller):
        await session.start_text_turn("取消提醒")
    assert not any("取消了" in str(payload) for payload in ws.sent)
    assert controller.state.reminders == {}


def test_maybe_cancel_reminder_is_a_noop_without_a_controller():
    previous = proactive.get_controller()
    try:
        proactive._CONTROLLER = None
        assert proactive.maybe_cancel_reminder("取消提醒") is None
    finally:
        proactive._CONTROLLER = previous


# ---------------- §2: a due reminder is retried, not silently lost ----------------

def _controller_with_sessions(sessions, **cfg_overrides):
    clock_now = {"now": NOW}
    controller = ProactiveController(
        lambda: list(sessions), config(**cfg_overrides),
        clock=lambda: clock_now["now"], sleep=FakeSleep(), log=lambda line: None)
    return controller, clock_now


async def test_due_reminder_waits_for_a_session_without_spending_attempts():
    sessions: list = []
    controller, clock_now = _controller_with_sessions(sessions)
    item = controller.add_reminder("喝水", NOW + timedelta(minutes=1), NOW)

    clock_now["now"] = NOW + timedelta(minutes=2)
    assert await controller.tick() == []
    assert item["id"] in controller.state.reminders
    assert controller.state.attempts == 0
    assert controller.state.spoke_at == []

    sessions.append(FakeSession([]))               # the board connects
    clock_now["now"] = NOW + timedelta(minutes=2, seconds=1)
    fired = await controller.tick()
    assert fired and fired[-1]["outcome"] == "spoke"
    assert controller.state.reminders == {}


async def test_rejected_due_reminder_is_kept_and_retried():
    session = FakeSession([])
    session.speaking = True                        # idle_quiet rejects
    controller, clock_now = _controller_with_sessions(
        [session], pending_retry_seconds=30)
    item = controller.add_reminder("喝水", NOW + timedelta(minutes=1), NOW)

    clock_now["now"] = NOW + timedelta(minutes=2)
    fired = await controller.tick()
    assert fired and fired[-1]["rejected_by"] == Gate.IDLE_QUIET.value
    assert item["id"] in controller.state.reminders

    # Inside the retry window: no second attempt.
    clock_now["now"] += timedelta(seconds=1)
    assert await controller.tick() == []
    assert item["id"] in controller.state.reminders

    # Board is free again and the retry window elapsed -> spoken, then removed.
    session.speaking = False
    clock_now["now"] += timedelta(seconds=31)
    fired = await controller.tick()
    assert fired and fired[-1]["outcome"] == "spoke"
    assert controller.state.reminders == {}


async def test_due_reminder_expires_after_ttl():
    controller, clock_now = _controller_with_sessions([], pending_ttl_min=30)
    item = controller.add_reminder("喝水", NOW + timedelta(minutes=1), NOW)
    clock_now["now"] = NOW + timedelta(minutes=1, seconds=1)
    assert await controller.tick() == []           # still waiting for a session
    assert item["id"] in controller.state.reminders

    clock_now["now"] = NOW + timedelta(minutes=32)
    assert await controller.tick() == []
    assert controller.state.reminders == {}
    assert controller.state.reminder_expired == 1
    assert controller.status(clock_now["now"])["reminders"] == {
        "count": 0, "expired": 1}
    assert controller.state.attempts == 0


# ---------------- §3: partially spoken streamed reply is not replayed ----------------

async def test_chain_c_does_not_repeat_a_partially_spoken_answer(clean_sessions):
    session, _ = make_real_session(reply="日志看完了，三处报错都是超时。",
                                   stream_tts=True)
    # The socket dies after the first streamed sentence reached the board.
    session.llm.on_chat = lambda: setattr(session, "alive", False)
    controller, _ = controller_for(session, [])
    with use_controller(controller):
        await session._run_turn(0.0, "帮我看看日志")
    assert session.alive is False
    assert session._first_audio_at is not None     # one sentence already played
    assert controller.state.pending == []          # C must not replay the reply


# ---------------- §4: in-flight item survives a full queue ----------------

async def test_in_flight_announcement_is_never_dropped_by_a_full_queue():
    session = FakeSession([])
    entered = asyncio.Event()
    release = asyncio.Event()

    async def sleep(seconds):
        entered.set()
        await release.wait()

    controller = ProactiveController(
        lambda: [session], config(pending_max=2),
        clock=lambda: NOW, sleep=sleep, log=lambda line: None)
    controller.enqueue_pending(TriggerKind.TASK_DONE, "task:a", "第一件事办好了。", "a")
    controller.enqueue_pending(TriggerKind.TASK_DONE, "task:b", "第二件事办好了。", "b")

    flushing = asyncio.create_task(controller._flush_pending(NOW))
    await entered.wait()                           # A is inside the 600 ms window
    assert controller.state.pending[0]["turn_id"] == "a"
    assert controller.state.pending[0]["in_flight"] is True

    # Queue is full (2/2) while A is being spoken: drop B, never A, queue C.
    assert controller.enqueue_pending(TriggerKind.TASK_DONE, "task:c",
                                      "第三件事办好了。", "c") is True
    assert [item["turn_id"] for item in controller.state.pending] == ["a", "c"]
    assert controller.state.pending_dropped == 1

    release.set()
    record = await flushing
    assert record["outcome"] == "spoke"
    assert [item["turn_id"] for item in controller.state.pending] == ["c"]


async def test_full_queue_of_in_flight_items_refuses_the_newcomer():
    session = FakeSession([])
    entered = asyncio.Event()
    never = asyncio.Event()

    async def sleep(seconds):
        entered.set()
        await never.wait()

    controller = ProactiveController(
        lambda: [session], config(pending_max=1),
        clock=lambda: NOW, sleep=sleep, log=lambda line: None)
    controller.enqueue_pending(TriggerKind.TASK_DONE, "task:a", "第一件事办好了。", "a")
    flushing = asyncio.create_task(controller._flush_pending(NOW))
    await entered.wait()
    assert controller.enqueue_pending(TriggerKind.TASK_DONE, "task:b",
                                      "第二件事办好了。", "b") is False
    assert [item["turn_id"] for item in controller.state.pending] == ["a"]
    assert controller.state.pending_dropped == 1
    flushing.cancel()
    with suppress(asyncio.CancelledError):
        await flushing


# ---------------- config clamping ----------------

@pytest.mark.parametrize("overrides,field,expected", [
    ({"pending_max": 0}, "pending_max", 1),
    ({"pending_max": -3}, "pending_max", 1),
    ({"pending_ttl_min": -5}, "pending_ttl_min", 1),
    ({"mute_minutes": -10}, "mute_minutes", 0),
    ({"emotion_lead_ms": 100}, "emotion_lead_ms", 600),
    ({"pending_retry_seconds": -1}, "pending_retry_seconds", 0),
])
def test_unsafe_config_values_are_clamped(overrides, field, expected, capsys):
    parsed = ProactiveConfig.from_cfg({"proactive": overrides})
    assert getattr(parsed, field) == expected
    assert "clamped" in capsys.readouterr().out


async def test_zero_pending_max_does_not_crash_enqueue():
    controller, _, _, _ = make_controller([], {"pending_max": 0})
    assert controller.cfg.pending_max == 1
    assert controller.enqueue_pending(TriggerKind.TASK_DONE, "task:t1",
                                      "报告写完了。", "t1") is True
    assert controller.pending_status()["count"] == 1


# ================= task-18 verifier FAILED: bare clock times + clean content =================

@pytest.mark.parametrize("text,expected", [
    # bare X点 / X点半 / X点YY分: today when still ahead, tomorrow once passed
    ("记得九点半提醒我", datetime(2026, 10, 28, 9, 30)),
    ("记得九点提醒我", datetime(2026, 10, 28, 9, 0)),
    ("提醒我二十一点半", datetime(2026, 10, 27, 21, 30)),
    ("九点三十分提醒我开会", datetime(2026, 10, 28, 9, 30)),
    # explicit day words are taken literally
    ("明天九点半提醒我", datetime(2026, 10, 28, 9, 30)),
    ("后天九点叫我", datetime(2026, 10, 29, 9, 0)),
    ("今天九点提醒我", datetime(2026, 10, 27, 9, 0)),
])
def test_bare_clock_time(text, expected):
    parsed = proactive.parse_reminder(text, REMINDER_NOW)
    assert parsed is not None, text
    assert parsed[0] == expected, text


def test_bare_clock_time_stays_today_when_still_ahead():
    morning = datetime(2026, 10, 27, 8, 0)
    assert proactive.parse_reminder("记得九点半提醒我", morning)[0] == \
        datetime(2026, 10, 27, 9, 30)


def test_clock_time_rolls_to_tomorrow_at_noon():
    noon = datetime(2026, 10, 27, 12, 0)
    assert proactive.parse_reminder("12:00 提醒我", noon)[0] == \
        datetime(2026, 10, 28, 12, 0)


@pytest.mark.parametrize("text,content", [
    ("提醒我三分钟后喝水", "喝水"),          # the time phrase is stripped
    ("叫我明天九点起床", "起床"),
    ("9:30 提醒我", ""),                  # nothing to remind about
    ("明天九点半提醒我", ""),
    ("提醒我二十一点半", ""),
    ("别忘了半小时后开会", "开会"),
])
def test_reminder_content_is_clean(text, content):
    parsed = proactive.parse_reminder(text, REMINDER_NOW)
    assert parsed is not None, text
    assert parsed[1] == content, text


async def test_empty_content_is_announced_without_the_connector(clean_sessions):
    session, ws = make_real_session(reply="")
    controller, clock_now = controller_for(session, [])
    with use_controller(controller):
        await session.start_text_turn("9:30 提醒我")
        assert any("好，09:30 提醒你。" in str(payload) for payload in ws.sent)
        reminder = controller.list_reminders(NOW)[0]
        assert reminder["text"] == ""

        events: list = []
        clock_now["now"] = datetime(2026, 10, 28, 9, 30, 1)
        fired = await controller.tick()
    assert fired and fired[-1]["outcome"] == "spoke"
    assert fired[-1]["topic"].startswith("reminder:")


@pytest.mark.parametrize("text,expected", [
    ("九点一刻提醒我", datetime(2026, 10, 28, 9, 15)),
    ("九点三刻提醒我", datetime(2026, 10, 28, 9, 45)),
    ("记得十点一刻开会", datetime(2026, 10, 28, 10, 15)),
    ("二十三点三刻提醒我", datetime(2026, 10, 27, 23, 45)),
])
def test_quarter_past_clock_time(text, expected):
    """「九点一刻」 must be 09:15, not 九点一 (09:01) with a stray 刻."""
    parsed = proactive.parse_reminder(text, REMINDER_NOW)
    assert parsed is not None, text
    assert parsed[0] == expected, text
    assert "刻" not in parsed[1], text


@pytest.mark.parametrize("text", [
    "二十四点提醒我",          # hour out of range
    "六十分提醒我",            # minute out of range
    "十五点六十分提醒我",
    "九点零五分提醒我",        # 零X分 is not a supported numeral form
])
def test_invalid_clock_times_fall_through(text):
    """Out-of-range or unsupported times must not schedule a wrong instant."""
    assert proactive.parse_reminder(text, REMINDER_NOW) is None


@pytest.mark.parametrize("text,expected", [
    ("两点提醒我", datetime(2026, 10, 28, 2, 0)),
    ("零点提醒我", datetime(2026, 10, 28, 0, 0)),
    ("十二点提醒我", datetime(2026, 10, 28, 12, 0)),
    ("二十三点提醒我", datetime(2026, 10, 27, 23, 0)),
    ("十九点提醒我", datetime(2026, 10, 27, 19, 0)),
])
def test_chinese_numeral_hour_range(text, expected):
    assert proactive.parse_reminder(text, REMINDER_NOW)[0] == expected


# ================= task-18 verifier FAILED round 2: half-day words =================

@pytest.mark.parametrize("text,expected", [
    ("下午三点提醒我", datetime(2026, 10, 27, 15, 0)),
    ("傍晚六点提醒我", datetime(2026, 10, 27, 18, 0)),
    ("晚上十点提醒我", datetime(2026, 10, 27, 22, 0)),
    ("夜里十一点提醒我", datetime(2026, 10, 27, 23, 0)),
    ("今晚十点提醒我", datetime(2026, 10, 27, 22, 0)),
    ("中午一点提醒我", datetime(2026, 10, 28, 13, 0)),
])
def test_half_day_word_normalization(text, expected):
    parsed = proactive.parse_reminder(text, REMINDER_NOW)
    assert parsed is not None, text
    assert parsed[0] == expected, text


@pytest.mark.parametrize("text,expected", [
    ("今晚十二点提醒我", datetime(2026, 10, 28, 0, 0)),   # midnight, next day
    ("晚上十二点提醒我", datetime(2026, 10, 28, 0, 0)),
    ("凌晨十二点提醒我", datetime(2026, 10, 28, 0, 0)),   # 12 AM today already passed
    ("下午十二点提醒我", datetime(2026, 10, 28, 12, 0)),  # noon already passed
    ("中午十二点提醒我", datetime(2026, 10, 28, 12, 0)),
    ("上午九点提醒我", datetime(2026, 10, 28, 9, 0)),
    ("明天下午三点提醒我", datetime(2026, 10, 28, 15, 0)),
])
def test_half_day_edges(text, expected):
    assert proactive.parse_reminder(text, REMINDER_NOW)[0] == expected, text


@pytest.mark.parametrize("text", [
    "凌晨十三点提醒我",
    "中午十四点提醒我",
    "上午十四点提醒我",
    "明天后天九点提醒我",      # two day words: ambiguous
    "下午晚上九点提醒我",      # two half-day words: ambiguous
])
def test_unmappable_time_words_return_none(text):
    assert proactive.parse_reminder(text, REMINDER_NOW) is None


@pytest.mark.parametrize("text,content", [
    ("下午三点提醒我", ""),
    ("提醒我今晚十点吃药", "吃药"),
    ("晚上十点叫我关火", "关火"),
    ("明天下午三点提醒我开会", "开会"),
])
def test_half_day_words_are_stripped_from_content(text, content):
    assert proactive.parse_reminder(text, REMINDER_NOW)[1] == content, text


@pytest.mark.parametrize("text", [
    "别提醒了",
    "别再提醒",
    "停止提醒",
    "不要再提醒",
    "不用再提醒",
])
def test_extra_cancel_phrases(text):
    assert proactive.is_reminder_cancel(text) is True, text


@pytest.mark.parametrize("text", [
    "特别提醒",                # 特别提醒 must not cancel anything
    "再提醒我一次",            # adding another reminder is not cancelling
    "提醒我三分钟后喝水",
])
def test_cancel_false_positives(text):
    assert proactive.is_reminder_cancel(text) is False, text


def test_cancel_phrase_removes_the_newest_reminder():
    controller, _, _, _ = make_controller([])
    first = controller.add_reminder("喝水", NOW + timedelta(minutes=1), NOW)
    second = controller.add_reminder("关火", NOW + timedelta(minutes=2), NOW)
    assert controller.cancel_latest_reminder()["id"] == second["id"]
    assert [entry["id"] for entry in controller.list_reminders(NOW)] == [first["id"]]


def test_human_silence_seconds_is_clamped(capsys):
    parsed = ProactiveConfig.from_cfg(
        {"proactive": {"human_silence_seconds": -2.5}})
    assert parsed.human_silence_seconds == 0.0
    assert "clamped" in capsys.readouterr().out


# ================= task-18 rev4: rule table + exhaustive enumeration =================
#
# The parser has now been patched four times for the same class of bug (wrong
# instant / deleted reminder), so this section stops pointing at examples:
# `expected_reminder()` re-implements the agreed rule table independently of
# `src/proactive.py`, and the table is walked exhaustively (960 combinations).

HALF_DAY_WORDS_ALL = ("凌晨", "早上", "上午", "中午", "下午", "傍晚",
                      "晚上", "夜里", "今晚", "今夜")
DAY_WORD_CHOICES = ("", "今天", "明天", "后天")


def expected_half_day(word: str, hour: int):
    """Rule table, written from the spec — not imported from the implementation."""
    if word == "凌晨":
        if hour == 12:
            return 0, 0
        if hour < 12:
            return hour, 0
        return None
    if word in ("早上", "上午"):
        return (hour, 0) if hour <= 12 else None
    if word == "中午":
        if hour in (11, 12):
            return hour, 0
        if hour in (1, 2):
            return hour + 12, 0
        return None
    if word in ("下午", "傍晚"):
        if hour < 12:
            return hour + 12, 0
        if hour == 12:
            return 12, 0
        return hour, 0
    if word in ("晚上", "夜里", "今晚", "今夜"):
        if hour <= 4:                   # 晚上零点/一点 = 00:00/01:00
            return hour, 0
        if hour <= 11:
            return hour + 12, 0
        if hour == 12:
            return 0, 1
        return None                     # 「晚上十三点」 is not a time
    raise AssertionError(f"unknown half-day word {word!r}")


def expected_reminder(text: str, now: datetime):
    """`(when, content)` the rule table promises for a generated sentence."""
    match = re.fullmatch(
        r"(今天|明天|后天)?"
        r"(凌晨|早上|上午|中午|下午|傍晚|晚上|夜里|今晚|今夜)?"
        r"(\d{1,3})点提醒我", text)
    assert match is not None, text
    day_word, half_word, raw_hour = match.groups()
    raw = int(raw_hour)
    hour, offset = raw, 0
    if half_word:
        normalized = expected_half_day(half_word, raw)
        if normalized is None:
            return None
        hour, offset = normalized
    if day_word and half_word in ("晚上", "夜里", "今晚", "今夜") and raw <= 4:
        offset += 1                     # the midnight that ends that named day
    if not 0 <= hour <= 23:
        return None
    day_offset = {"今天": 0, "明天": 1, "后天": 2}.get(day_word or "", 0)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0) \
        + timedelta(days=day_offset + offset)
    if day_word is None and target <= now:
        target += timedelta(days=1)
    return target, ""


@pytest.mark.parametrize("day_word", DAY_WORD_CHOICES)
@pytest.mark.parametrize("half_word", HALF_DAY_WORDS_ALL)
def test_half_day_table_is_exhaustively_correct(half_word, day_word):
    for hour in range(24):
        text = f"{day_word}{half_word}{hour}点提醒我"
        expected = expected_reminder(text, REMINDER_NOW)
        actual = proactive.parse_reminder(text, REMINDER_NOW)
        assert actual == expected, text


def test_half_day_offset_adds_to_the_explicit_day_word():
    """「明天晚上十二点」 is the midnight after tomorrow (10-29), not 10-28."""
    assert proactive.parse_reminder("明天晚上十二点提醒我", REMINDER_NOW)[0] == \
        datetime(2026, 10, 29, 0, 0)
    assert proactive.parse_reminder("后天晚上十二点提醒我", REMINDER_NOW)[0] == \
        datetime(2026, 10, 30, 0, 0)
    assert proactive.parse_reminder("明天中午一点提醒我", REMINDER_NOW)[0] == \
        datetime(2026, 10, 28, 13, 0)


def test_noon_ten_is_not_a_time():
    """「中午十点」 used to become 22:00; the table says None."""
    assert proactive.parse_reminder("中午十点提醒我", REMINDER_NOW) is None
    assert proactive.parse_reminder("中午三点提醒我", REMINDER_NOW) is None
    assert proactive.parse_reminder("中午二十四点提醒我", REMINDER_NOW) is None


@pytest.mark.parametrize("text", [
    "取消提醒",
    "别提醒了",
    "停止提醒",
    "不要再提醒",
    "不再提醒",
    "不要提醒了",
])
def test_cancel_whitelist_hits(text):
    assert proactive.is_reminder_cancel(text) is True, text


@pytest.mark.parametrize("text", [
    "特别提醒我明天九点开会",
    "分别提醒我明天九点开会",
    "告别提醒我明天九点开会",
    "个别提醒我明天九点开会",
    "再提醒我一次",
])
def test_cancel_whitelist_never_deletes_on_lookalikes(text):
    assert proactive.is_reminder_cancel(text) is False, text


@pytest.mark.parametrize("text", [
    "特别提醒我明天九点开会",
    "分别提醒我明天九点开会",
    "告别提醒我明天九点开会",
    "个别提醒我明天九点开会",
])
def test_lookalike_phrases_still_schedule(text):
    assert proactive.parse_reminder(text, REMINDER_NOW) is not None, text


# ================= task-18 rev5: bounded demonstrator cancel phrases =================

@pytest.mark.parametrize("text", [
    "删除刚才那个提醒",
    "取消刚才的提醒",
    "删除上一个提醒",
])
def test_bounded_verb_phrase_cancels(text):
    assert proactive.is_reminder_cancel(text) is True, text


def test_deletion_mention_with_a_gap_is_not_a_cancel():
    """「删除文件后提醒我…」 must schedule, not delete: no arbitrary gap allowed."""
    text = "删除文件后提醒我九点开会"
    assert proactive.is_reminder_cancel(text) is False
    parsed = proactive.parse_reminder(text, REMINDER_NOW)
    assert parsed is not None
    assert parsed[0] == datetime(2026, 10, 28, 9, 0)


# ================= task-18 rev6: evening small hours + reversed prefixes =================

@pytest.mark.parametrize("text,expected", [
    ("晚上零点提醒我", datetime(2026, 10, 28, 0, 0)),
    ("今晚零点提醒我", datetime(2026, 10, 28, 0, 0)),
    ("夜里零点提醒我", datetime(2026, 10, 28, 0, 0)),
    ("晚上一点提醒我", datetime(2026, 10, 28, 1, 0)),
    ("今晚一点提醒我", datetime(2026, 10, 28, 1, 0)),
    ("晚上四点提醒我", datetime(2026, 10, 28, 4, 0)),
    ("晚上五点提醒我", datetime(2026, 10, 27, 17, 0)),   # 5 is the pivot
    ("晚上十一点提醒我", datetime(2026, 10, 27, 23, 0)),
])
def test_evening_small_hours_are_not_shifted(text, expected):
    """「晚上零点」 is 00:00, not 12:00; only 5–11 shift by twelve hours."""
    parsed = proactive.parse_reminder(text, REMINDER_NOW)
    assert parsed is not None, text
    assert parsed[0] == expected, text


@pytest.mark.parametrize("text,expected", [
    ("下午明天三点提醒我", datetime(2026, 10, 28, 15, 0)),
    ("晚上明天十点提醒我", datetime(2026, 10, 28, 22, 0)),
    ("上午后天九点提醒我", datetime(2026, 10, 29, 9, 0)),
    ("中午明天十二点提醒我", datetime(2026, 10, 28, 12, 0)),
])
def test_reversed_prefix_order_also_parses(text, expected):
    """The regex accepts half-day before day-word; the 960 grid only used one order."""
    parsed = proactive.parse_reminder(text, REMINDER_NOW)
    assert parsed is not None, text
    assert parsed[0] == expected, text


# ================= task-18 rev7: negated cancel verbs =================

@pytest.mark.parametrize("text", [
    "不要删除提醒",
    "别删掉提醒",
    "不用取消提醒",
    "不要取消提醒",
    "不删除提醒",
    "不要删除刚才那个提醒",
    "别删除提醒",
])
def test_negated_cancel_never_deletes(text):
    """The user said "don't delete": deleting here is the worst outcome."""
    assert proactive.is_reminder_cancel(text) is False, text


async def test_negated_cancel_leaves_the_reminder_in_place(clean_sessions):
    session, ws = make_real_session(reply="")
    controller, _ = controller_for(session, [])
    with use_controller(controller):
        await session.start_text_turn("3分钟后提醒我喝水")
        assert len(controller.state.reminders) == 1
        await session.start_text_turn("不要删除提醒")
    assert len(controller.state.reminders) == 1
    assert not any("取消了" in str(payload) for payload in ws.sent)


# ================= task-18 rev8: residue guard + spoken aliases =================

@pytest.mark.parametrize("text,expected", [
    ("明晚八点提醒我", datetime(2026, 10, 28, 20, 0)),
    ("后晚八点提醒我", datetime(2026, 10, 29, 20, 0)),
    ("明早七点提醒我", datetime(2026, 10, 28, 7, 0)),
    ("半夜十二点提醒我", datetime(2026, 10, 28, 0, 0)),
    ("午夜一点提醒我", datetime(2026, 10, 28, 1, 0)),
])
def test_spoken_aliases(text, expected):
    parsed = proactive.parse_reminder(text, REMINDER_NOW)
    assert parsed is not None, text
    assert parsed[0] == expected, text


@pytest.mark.parametrize("text", [
    "明儿晚上八点提醒我",
    "今早七点提醒我",
    "今儿八点提醒我",
    "前儿八点提醒我",
    "昨天八点提醒我",
    "前天八点提醒我",
    "明儿个八点提醒我",
    "大后天八点提醒我",
    "明晚",
    "半夜",
    "凌晨",
])
def test_unconsumed_time_prefix_never_rings(text):
    """A time word we did not parse must yield None, not a wrong hour."""
    assert proactive.parse_reminder(text, REMINDER_NOW) is None, text


def test_residue_guard_does_not_touch_normal_content():
    assert proactive.parse_reminder("提醒我三分钟后喝水", REMINDER_NOW)[1] == "喝水"
    parsed = proactive.parse_reminder("提醒我八点买点水果", REMINDER_NOW)
    assert parsed is not None
    assert parsed[0] == datetime(2026, 10, 28, 8, 0)
    assert parsed[1] == "买点水果"
    assert proactive.parse_reminder("提醒我买点水果", REMINDER_NOW) is None


def test_tonight_midnight_is_the_next_calendar_day():
    """「今天晚上零点」 is the midnight that ends today, not today 00:00."""
    assert proactive.parse_reminder("今天晚上零点提醒我", REMINDER_NOW)[0] == \
        datetime(2026, 10, 28, 0, 0)
    assert proactive.parse_reminder("今天晚上一点提醒我", REMINDER_NOW)[0] == \
        datetime(2026, 10, 28, 1, 0)


@pytest.mark.parametrize("text", [
    "晚上十三点提醒我",
    "夜里十五点提醒我",
    "今晚二十三点提醒我",
])
def test_evening_hour_past_twelve_is_none(text):
    """「晚上十三点」 is not something anyone says: None, unlike 下午十三点."""
    assert proactive.parse_reminder(text, REMINDER_NOW) is None
    assert proactive.parse_reminder("下午十三点提醒我", REMINDER_NOW)[0].hour == 13


# ================= task-18 rev9: unsupported date contexts never guess =================

@pytest.mark.parametrize("text", [
    "周末八点提醒我",
    "月底八点提醒我",
    "下个月八点提醒我",
    "十月八点提醒我",
    "周三八点提醒我",
    "10月8号八点提醒我",
    "这周三八点提醒我",
    "国庆八点提醒我",
])
def test_date_context_we_do_not_understand_returns_none(text):
    """「周末八点」 must not become 08:00 today/tomorrow: we did not parse 周末."""
    assert proactive.parse_reminder(text, REMINDER_NOW) is None, text


@pytest.mark.parametrize("text,expected,content", [
    ("提醒我明天九点开会", datetime(2026, 10, 28, 9, 0), "开会"),
    ("提醒我八点买点水果", datetime(2026, 10, 28, 8, 0), "买点水果"),
    ("晚上五点提醒我", datetime(2026, 10, 27, 17, 0), ""),
    ("提醒我三分钟后喝水", datetime(2026, 10, 27, 14, 3), "喝水"),
    ("删除文件后提醒我九点开会", datetime(2026, 10, 28, 9, 0), "删除文件后开会"),
    ("我有个会三分钟后提醒我", datetime(2026, 10, 27, 14, 3), "我有个会"),
    ("明晚八点提醒我", datetime(2026, 10, 28, 20, 0), ""),
])
def test_date_context_probe_does_not_break_supported_phrases(text, expected, content):
    parsed = proactive.parse_reminder(text, REMINDER_NOW)
    assert parsed is not None, text
    assert parsed == (expected, content), text


# ---- gate 2 must know about speech before the segment closes ------------------

def test_speech_in_progress_feeds_gate_two_before_segment_close():
    """A long sentence must not look like silence.

    `_note_human_speech` used to fire only when a segment closed, so a person
    talking for longer than human_silence_seconds would leave the gate open
    mid-sentence - exactly when proactive must stay quiet.
    """
    import session as voice_session

    class Vad:
        def __init__(self, speaking):
            self._speaking = speaking

        def is_speech_detected(self):
            return self._speaking

    seen = []
    real = voice_session._note_human_speech
    try:
        voice_session._note_human_speech = lambda: seen.append("note")
        voice_session._note_speech_in_progress(Vad(True))
        voice_session._note_speech_in_progress(Vad(False))
    finally:
        voice_session._note_human_speech = real
    assert seen == ["note"], seen


def test_speech_probe_absent_is_a_noop():
    """Fake VADs in tests (and any non-sherpa backend) must not raise."""
    import session as voice_session

    class Bare:
        pass

    voice_session._note_speech_in_progress(Bare())      # must not raise


def test_speech_probe_that_raises_is_swallowed():
    import session as voice_session

    class Angry:
        def is_speech_detected(self):
            raise RuntimeError("vad gone")

    voice_session._note_speech_in_progress(Angry())     # must not raise


def test_recent_keeps_a_full_acceptance_window():
    """Step 3 is judged over 30 minutes of use; five decisions cannot show that.

    `/debug/proactive/status` exposes `recent`, and the acceptance reads it to argue
    "zero false triggers". Keeping only five entries would have truncated the window
    long before anyone looked.
    """
    import proactive as P

    assert P.RECENT_KEEP >= 20

    c = P.ProactiveController(lambda: [], P.ProactiveConfig(enabled=True, dry_run=True),
                              clock=lambda: datetime(2026, 10, 27, 14, 0))
    c.status()      # first call rolls the day over, which clears `recent`
    for i in range(P.RECENT_KEEP + 7):
        c._finish({"i": i, "kind": "scheduled", "outcome": "dry_run"})

    recent = c.status()["recent"]
    assert len(recent) == P.RECENT_KEEP
    assert [r["i"] for r in recent] == list(range(7, P.RECENT_KEEP + 7))


async def test_fired_reminder_says_what_it_is():
    """A reminder set hours ago must not open with a bare noun.

    「喝水」 alone at the due moment reads as a non sequitur; the announcement carries
    its own framing. A reminder with no content (「9:30 提醒我」) says that the time has
    come instead of synthesizing an empty sentence.
    """
    session = FakeSession([])
    controller, clock_now, _, _ = make_controller([session])
    controller.add_reminder("喝水", NOW + timedelta(minutes=1), NOW)
    controller.add_reminder("", NOW + timedelta(minutes=1), NOW)

    clock_now["now"] = NOW + timedelta(seconds=61)
    fired = await controller.tick()
    assert [r["outcome"] for r in fired] == ["spoke", "spoke"], fired
    said = list(session.spoken)
    assert "提醒你喝水" in said, said
    assert "提醒时间到了" in said, said
    assert "喝水" not in said, "a bare noun must not be spoken on its own"


async def test_queued_announcements_say_where_they_came_from():
    """Heard minutes later, a bare reply body is a non sequitur.

    A continuation of an interrupted answer and a reply that arrived while the socket
    was down both need their own framing; kinds without an entry speak verbatim so
    future triggers are not forced into somebody else's words.
    """
    session = FakeSession([])
    controller, clock_now, _, _ = make_controller([session])
    controller.enqueue_pending(
        proactive.TriggerKind.TASK_DONE, topic="task:t1",
        text="项目已经跑完了", turn_id="t1", emotion="happy")
    controller.enqueue_pending(
        proactive.TriggerKind.ANSWER_READY, topic="answer:t2",
        text="明天下午会下雨", turn_id="t2", emotion="neutral")

    clock_now["now"] = NOW + timedelta(seconds=5)
    await controller.tick()
    clock_now["now"] = NOW + timedelta(seconds=70)
    await controller.tick()

    said = list(session.spoken)
    assert said == ["接着刚才说：项目已经跑完了", "刚才你问的那件事：明天下午会下雨"], said


async def test_busy_rejection_does_not_change_the_face():
    """'Look but stay quiet' must not apply when the reason is that it is talking.

    Every rejection used to push the trigger's expression, so a trigger arriving
    mid-answer flipped the face away from `speaking` - the board visibly changed
    expression while it was still speaking. Other rejections (night, cooldown) keep
    the face push: there the face is the whole point.
    """
    speaking = FakeSession([])
    speaking.speaking = True
    controller, _, _, _ = make_controller([speaking])

    record = await controller.fire(
        proactive.Trigger(proactive.TriggerKind.SCHEDULED, topic="reminder:x",
                          text="提醒你喝水", emotion="happy"))

    assert record["rejected_by"] == "idle_quiet", record
    assert record["outcome"] == "rejected", record
    assert record["emotion_sent"] is False, record
    assert speaking.emotions == [], speaking.emotions


# ---------------- B1 mute switch: gates, suspended expiry, catch-up ----------------

class FakeMute:
    """Duck-typed stand-in for mute.MuteState (only `.muted` is read)."""

    def __init__(self, muted=False):
        self.muted = muted


def controller_with_mute(mute_state, sessions=None, **overrides):
    logs: list[str] = []
    controller = ProactiveController(
        lambda: list(sessions or []),
        config(**overrides),
        clock=lambda: NOW,
        sleep=FakeSleep(),
        log=logs.append,
        mute=mute_state,
    )
    return controller, logs


def pending_item(text, created_at, turn_id="t1", kind=TriggerKind.TASK_DONE):
    return {
        "kind": TriggerKind(kind).value,
        "topic": "task",
        "text": text,
        "emotion": "happy",
        "turn_id": turn_id,
        "created_at": created_at,
        "created_at_iso": created_at.isoformat(timespec="seconds"),
        "session_seen_at": created_at.isoformat(timespec="seconds"),
    }


def test_evaluate_reports_mute_first():
    result = evaluate(trigger(), env(muted=True), ProactiveState(), config())
    assert result.allowed is False
    assert result.rejected_by is Gate.MUTE
    assert "mute" in result.detail


async def test_muted_fire_returns_muted_and_spends_nothing():
    mute_state = FakeMute(True)
    session = FakeSession([])
    controller, logs = controller_with_mute(
        mute_state, [session], hourly_limit=2)
    record = await controller.fire(trigger())
    assert record["outcome"] == "muted", record
    assert record["emotion_sent"] is False
    # No quota, no face, no speech, no topic window.
    assert controller.state.attempts == 0
    assert controller.state.spoke_at == []
    assert controller.state.topic_last_at == {}
    assert controller.state.spoke_total == 0
    assert session.spoken == [] and session.emotions == []
    assert any('"outcome": "muted"' in line for line in logs)


async def test_muted_tick_skips_flush_and_suspends_expiry():
    mute_state = FakeMute(True)
    session = FakeSession([])
    controller, _ = controller_with_mute(
        mute_state, [session], pending_ttl_min=1, pending_retry_seconds=0)
    controller.add_reminder("喝水", NOW - timedelta(minutes=5), NOW - timedelta(minutes=30))
    controller.state.pending.append(
        pending_item("办好了", NOW - timedelta(minutes=5)))
    fired = await controller.tick(NOW)
    assert fired == []
    assert session.spoken == []
    # Both queues survive even though their TTL (1 min) has long passed.
    assert len(controller.state.reminders) == 1
    assert len(controller.state.pending) == 1
    assert controller.state.reminder_expired == 0
    assert controller.state.pending_expired == 0
    assert controller.state.attempts == 0


async def test_muted_flush_helpers_are_noops():
    mute_state = FakeMute(True)
    session = FakeSession([])
    controller, _ = controller_with_mute(mute_state, [session])
    controller.state.pending.append(pending_item("办好了", NOW))
    controller.add_reminder("喝水", NOW - timedelta(minutes=1), NOW - timedelta(minutes=2))
    assert await controller._flush_pending(NOW) is None
    assert await controller._flush_due_reminders(NOW) == []
    assert len(controller.state.pending) == 1
    assert len(controller.state.reminders) == 1
    assert session.spoken == []


async def test_catchup_speaks_recent_items_as_one_sentence():
    mute_state = FakeMute(False)
    session = FakeSession([])
    controller, logs = controller_with_mute(
        mute_state, [session], catchup_window_min=10, catchup_max_items=2)
    recent_reminder = controller.add_reminder(
        "喝水", NOW - timedelta(minutes=2), NOW - timedelta(minutes=30))
    controller.enqueue_pending(TriggerKind.TASK_DONE, "task", "办好了", "t1",
                               NOW - timedelta(minutes=1))
    old_reminder = controller.add_reminder(
        "交报告", NOW - timedelta(minutes=30), NOW - timedelta(minutes=40))

    result = await controller.resume_from_mute(NOW)

    assert result["spoken"] is True and result["items"] == 2, result
    assert result["missed"] == 1, result
    assert len(session.spoken) == 1
    line = session.spoken[0]
    assert "提醒你喝水" in line and "办好了" in line, line
    assert "交报告" not in line, line
    assert recent_reminder["id"] not in controller.state.reminders
    assert old_reminder["id"] not in controller.state.reminders
    assert controller.state.pending == []
    assert controller.state.catchup_missed == 1
    assert controller.state.catchup_spoken == 2
    assert controller.state.catchup_last_at == NOW
    assert any("catchup missed_muted" in line for line in logs)


async def test_catchup_keeps_only_two_and_marks_the_older_missed():
    mute_state = FakeMute(False)
    session = FakeSession([])
    controller, _ = controller_with_mute(
        mute_state, [session], catchup_window_min=10, catchup_max_items=2)
    controller.add_reminder("九", NOW - timedelta(minutes=9), NOW - timedelta(minutes=20))
    controller.add_reminder("八", NOW - timedelta(minutes=8), NOW - timedelta(minutes=20))
    controller.add_reminder("一", NOW - timedelta(minutes=1), NOW - timedelta(minutes=20))

    result = await controller.resume_from_mute(NOW)

    assert result["spoken"] is True and result["items"] == 2
    assert result["missed"] == 1
    line = session.spoken[0]
    assert "提醒你一" in line and "提醒你八" in line, line
    assert "提醒你九" not in line, line
    assert list(controller.state.reminders) == []
    assert controller.state.catchup_missed == 1


async def test_catchup_window_drops_older_items_as_missed():
    mute_state = FakeMute(False)
    session = FakeSession([])
    controller, _ = controller_with_mute(
        mute_state, [session], catchup_window_min=5, catchup_max_items=2)
    controller.add_reminder("太早", NOW - timedelta(minutes=6), NOW - timedelta(minutes=7))

    result = await controller.resume_from_mute(NOW)

    assert result["spoken"] is False and result["missed"] == 1
    assert result["reason"] == "nothing_recent"
    assert session.spoken == []
    assert controller.state.reminders == {}
    assert controller.state.catchup_missed == 1


async def test_catchup_without_session_keeps_items():
    mute_state = FakeMute(False)
    controller, _ = controller_with_mute(mute_state, [])
    controller.add_reminder("喝水", NOW - timedelta(minutes=1), NOW - timedelta(minutes=2))

    result = await controller.resume_from_mute(NOW)

    assert result["spoken"] is False and result["reason"] == "no_session"
    assert result["missed"] == 0
    assert len(controller.state.reminders) == 1


async def test_catchup_is_not_repeated_by_another_unmute():
    mute_state = FakeMute(False)
    session = FakeSession([])
    controller, _ = controller_with_mute(mute_state, [session])
    controller.state.pending.append(pending_item("办好了", NOW - timedelta(minutes=1)))

    first = await controller.resume_from_mute(NOW)
    second = await controller.resume_from_mute(NOW)

    assert first["spoken"] is True
    assert second["spoken"] is False and second["reason"] == "empty"
    assert session.spoken == ["接着刚才说：办好了"]
    assert controller.state.catchup_spoken == 1


def test_status_exposes_mute_and_catchup():
    mute_state = FakeMute(True)
    controller, _ = controller_with_mute(mute_state, [])
    controller.state.catchup_missed = 3
    status = controller.status(NOW)
    assert status["muted"] is True
    assert status["catchup"]["missed"] == 3
    assert status["catchup"]["pending"] == 0


async def test_catchup_never_speaks_future_items_early():
    """A future reminder is not "due": keep it queued, do not spend a slot."""
    mute_state = FakeMute(False)
    session = FakeSession([])
    controller, logs = controller_with_mute(
        mute_state, [session], catchup_window_min=10, catchup_max_items=2)
    past = controller.add_reminder(
        "三分钟前", NOW - timedelta(minutes=3), NOW - timedelta(minutes=5))
    future_one = controller.add_reminder(
        "未来一", NOW + timedelta(minutes=5), NOW)
    future_two = controller.add_reminder(
        "未来二", NOW + timedelta(minutes=10), NOW)

    result = await controller.resume_from_mute(NOW)

    assert result["spoken"] is True and result["items"] == 1, result
    assert result["missed"] == 0, result
    assert session.spoken == ["提醒你三分钟前"]
    assert past["id"] not in controller.state.reminders
    assert future_one["id"] in controller.state.reminders
    assert future_two["id"] in controller.state.reminders
    assert controller.state.catchup_missed == 0
    assert all("未来" not in line for line in session.spoken)

    # A second unmute must not speak them early either; they stay untouched.
    second = await controller.resume_from_mute(NOW)
    assert second["spoken"] is False and second["reason"] == "nothing_recent"
    assert second["missed"] == 0
    assert len(controller.state.reminders) == 2
    assert len(session.spoken) == 1


async def test_catchup_defaults_are_ten_minutes_and_two_items():
    fresh = ProactiveConfig()
    assert fresh.catchup_window_min == 10.0
    assert fresh.catchup_max_items == 2
    parsed = ProactiveConfig.from_cfg(
        {"mute": {"catchup_window_min": 4.5, "catchup_max_items": 1}})
    assert parsed.catchup_window_min == 4.5
    assert parsed.catchup_max_items == 1
