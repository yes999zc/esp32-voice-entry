"""Raw `/debug/mcp` must not bypass the spoken-confirmation gate.

`/debug/mcp` sends firmware tool calls straight to every live session, so a
destructive tool (`config.yaml safety.confirm_tools`) would run without ever
asking the user out loud. The handler refuses those names with 403.

The refusal list is read from the repo's real `config.yaml`, not copied into the
test: a typo there must fail here (see `test_config_confirm_tools.py` for the
name-shape guard). The app is `vision.make_router` alone (no auth middleware;
this task does not test auth) and `server.py` is never imported, so no model,
ASR or TTS is loaded and no request ever reaches the device.

Red line: none of these names is ever really sent to hardware — the fake
sessions only record `send_tool_call`.
"""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import yaml
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tools as devtools  # noqa: E402
import vision  # noqa: E402

CONFIG_PATH = ROOT / "config.yaml"
REJECTED_BODY_REASON = "requires spoken confirmation; use /debug/tool with a live session"

# Spellings from before the 2.5.3 firmware audit: they never existed in the
# firmware, so the gate could not fire. They must stay forwarded verbatim
# (no compatibility shim).
LEGACY_WRONG_NAMES = [
    "self.system.reboot",
    "self.system.upgrade_firmware",
    "self.system.set_download_url",
]


def load_cfg() -> dict:
    with open(CONFIG_PATH) as fh:
        return yaml.safe_load(fh)


CFG = load_cfg()
CONFIRM_TOOLS = list(CFG["safety"]["confirm_tools"])


class FakeSession:
    """Records `send_tool_call` instead of talking to a device."""

    def __init__(self, session_id="fake01"):
        self.session_id = session_id
        self.calls = []

    async def send_tool_call(self, name, arguments):
        self.calls.append((name, arguments))


def make_cfg(confirm_tools):
    return {
        "server": {"ws_url": "ws://127.0.0.1:4410", "ota_port": 4411},
        "safety": {"confirm_tools": list(confirm_tools)},
    }


def build_app(cfg, sessions):
    app = web.Application()
    vision.make_router(cfg, lambda: list(sessions))(app)
    return app


@asynccontextmanager
async def running(sessions, cfg=None):
    client = TestClient(TestServer(build_app(cfg or CFG, sessions)))
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


@pytest.mark.parametrize("name", CONFIRM_TOOLS)
async def test_raw_confirm_tool_403_without_dispatch(name):
    """Every shipped destructive name is refused and never reaches a session."""
    sessions = [FakeSession("s1"), FakeSession("s2")]
    async with running(sessions) as client:
        resp = await client.post("/debug/mcp",
                                 json={"name": name, "arguments": {}})
        assert resp.status == 403
        assert await resp.json() == {
            "ok": False,
            "blocked": name,
            "reason": REJECTED_BODY_REASON,
        }
    assert [s.calls for s in sessions] == [[], []]


async def test_raw_confirm_tool_403_with_no_live_session():
    """No session must not downgrade the refusal to 200 / 503."""
    async with running([]) as client:
        resp = await client.post("/debug/mcp", json={"name": CONFIRM_TOOLS[0]})
        assert resp.status == 403
        body = await resp.json()
        assert body["ok"] is False
        assert body["blocked"] == CONFIRM_TOOLS[0]


@pytest.mark.parametrize("name", LEGACY_WRONG_NAMES)
async def test_legacy_wrong_name_still_forwarded(name):
    """The pre-audit spellings are not firmware tools: keep bench semantics."""
    sessions = [FakeSession("s1")]
    async with running(sessions) as client:
        resp = await client.post("/debug/mcp", json={"name": name})
        assert resp.status == 200
        assert await resp.json() == {"sent": 1, "name": name}
    assert sessions[0].calls == [(name, {})]


async def test_alias_is_normalized_before_the_check():
    """An alias that maps to a confirm tool is refused under its request name.

    The shipped config has no speech alias pointing at a dangerous tool (see
    `test_shipped_aliases_map_to_no_confirm_tool`), so the mapping path is
    exercised with an injected confirm list.
    """
    sessions = [FakeSession("s1")]
    cfg = make_cfg(["self.audio_speaker.set_volume"])
    async with running(sessions, cfg) as client:
        resp = await client.post("/debug/mcp",
                                 json={"name": "set_volume", "arguments": {"volume": 90}})
        assert resp.status == 403
        assert await resp.json() == {
            "ok": False,
            "blocked": "set_volume",
            "reason": REJECTED_BODY_REASON,
        }
    assert sessions[0].calls == []


def test_shipped_aliases_map_to_no_confirm_tool():
    """Documents why the alias case above needs an injected list."""
    for alias, device_name in devtools.DEVICE_NAME.items():
        assert device_name not in CONFIRM_TOOLS, alias


async def test_non_confirm_tool_is_sent_to_every_session():
    sessions = [FakeSession("s1"), FakeSession("s2"), FakeSession("s3")]
    args = {"volume": 60}
    async with running(sessions) as client:
        resp = await client.post("/debug/mcp",
                                 json={"name": "self.audio_speaker.set_volume",
                                       "arguments": args})
        assert resp.status == 200
        assert await resp.json() == {"sent": 3, "name": "self.audio_speaker.set_volume"}
    for sess in sessions:
        assert sess.calls == [("self.audio_speaker.set_volume", args)]


async def test_unknown_name_keeps_bench_behaviour():
    """Unknown names are still forwarded verbatim (M3 bench relies on this)."""
    sessions = [FakeSession("s1")]
    async with running(sessions) as client:
        resp = await client.post("/debug/mcp", json={"name": "foo.bar"})
        assert resp.status == 200
        assert await resp.json() == {"sent": 1, "name": "foo.bar"}
    assert sessions[0].calls == [("foo.bar", {})]


async def test_missing_name_is_still_400():
    async with running([FakeSession("s1")]) as client:
        resp = await client.post("/debug/mcp", json={})
        assert resp.status == 400
