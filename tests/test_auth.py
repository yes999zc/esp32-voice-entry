"""Control-plane auth: anonymous whitelist, Bearer gate, token lifecycle.

The app is built without any model: the test client talks to the real routes
from `ota.build_app` + `vision.make_router`, but every request stops before a
handler that would load a model (the no-image path of /xiaozhi/vision).
"""
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ota  # noqa: E402
import vision  # noqa: E402

CONTROL = "test-control-token"
VISION = "test-vision-token"


def make_cfg(tmp_path, vision_token=""):
    return {
        "server": {
            "ws_url": "ws://127.0.0.1:4410",
            "vision_url": "http://127.0.0.1:4411/xiaozhi/vision",
            "vision_token": vision_token,
            "timezone_minutes": 480,
            "ota_port": 4411,
        },
        "security": {"control_token_file": str(tmp_path / "control.token")},
    }


def build_app(cfg, control_token=CONTROL, extra_routes=None):
    extras = [vision.make_router(cfg, lambda: [])]
    if extra_routes:
        extras.append(extra_routes)
    return ota.build_app(cfg, extras=tuple(extras), control_token=control_token)


@asynccontextmanager
async def running(app):
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# token lifecycle

def test_env_token_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("ESP32_CONTROL_TOKEN", "from-env-token")
    cfg = make_cfg(tmp_path)
    assert ota.resolve_control_token(cfg) == "from-env-token"
    assert not (tmp_path / "control.token").exists()


def test_token_generated_once(tmp_path, monkeypatch):
    monkeypatch.delenv("ESP32_CONTROL_TOKEN", raising=False)
    cfg = make_cfg(tmp_path)
    token = ota.resolve_control_token(cfg)
    path = tmp_path / "control.token"
    assert len(token) >= 32
    assert path.read_text().strip() == token
    assert (path.stat().st_mode & 0o777) == 0o600
    assert (tmp_path.stat().st_mode & 0o777) == 0o700
    # A second start reuses the file instead of generating a new secret.
    assert ota.resolve_control_token(cfg) == token


def test_token_read_from_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ESP32_CONTROL_TOKEN", raising=False)
    cfg = make_cfg(tmp_path)
    cfg["security"]["control_token_file"] = str(tmp_path / "custom.token")
    (tmp_path / "custom.token").write_text("stored-token\n")
    assert ota.resolve_control_token(cfg) == "stored-token"


def test_vision_token_choice(tmp_path):
    cfg = make_cfg(tmp_path)
    assert ota.effective_vision_token(cfg, CONTROL) == CONTROL
    cfg["server"]["vision_token"] = VISION
    assert ota.effective_vision_token(cfg, CONTROL) == VISION


# middleware gate

async def test_bad_token_401(tmp_path):
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        for headers in ({}, auth("wrong-token")):
            resp = await client.post("/debug/mcp", json={"name": "x"},
                                     headers=headers)
            assert resp.status == 401
            assert await resp.json() == {"ok": False, "error": "unauthorized"}


async def test_401_skips_handler(tmp_path):
    calls = []

    async def spy(request):
        calls.append(1)
        return web.json_response({"ok": True})

    def add_spy(app):
        app.router.add_post("/debug/spy", spy)

    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg, extra_routes=add_spy)) as client:
        resp = await client.post("/debug/spy")
        assert resp.status == 401
        assert calls == []
        resp = await client.post("/debug/spy", headers=auth(CONTROL))
        assert resp.status == 200
        assert calls == [1]


async def test_good_token_ok(tmp_path):
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        resp = await client.post("/debug/mcp", json={"name": "self.camera.take_photo"},
                                 headers=auth(CONTROL))
        assert resp.status == 200
        assert (await resp.json())["sent"] == 0


async def test_control_routes_401(tmp_path):
    cfg = make_cfg(tmp_path)
    protected = [
        ("GET", "/debug/photo/photo.jpg"),
        ("POST", "/debug/tool"),
        ("POST", "/debug/mcp"),
        ("POST", "/debug/turn"),
        ("POST", "/debug/notify"),
        ("GET", "/debug/mute"),
        ("POST", "/debug/mute"),
        ("GET", "/xiaozhi/ota/"),          # health is ours, not the firmware's
    ]
    async with running(build_app(cfg)) as client:
        for method, path in protected:
            resp = await client.request(method, path)
            assert resp.status == 401, f"{method} {path}"


# anonymous whitelist

async def test_ota_anonymous(tmp_path):
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        resp = await client.post("/xiaozhi/ota/", json={
            "application": {"name": "xiaozhi", "version": "2.0.0"}})
        assert resp.status == 200
        assert (await resp.json())["websocket"]["url"] == cfg["server"]["ws_url"]


async def test_media_anonymous(tmp_path):
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        # 404 from the handler (missing file) proves auth did not interpose.
        assert (await client.get("/notify/missing.ogg")).status == 404
        assert (await client.get("/screen/missing.png")).status == 404


async def test_upload_anonymous(tmp_path, monkeypatch):
    """self.screen.snapshot POSTs here and cannot carry our token."""
    photos = tmp_path / "photos"
    monkeypatch.setattr(vision, "PHOTO_DIR", photos)
    cfg = make_cfg(tmp_path)
    body = aiohttp.MultipartWriter("form-data")
    part = body.append(b"\xff\xd8\xff\xd9")
    part.set_content_disposition("form-data", name="file", filename="snap.jpg")
    async with running(build_app(cfg)) as client:
        resp = await client.post("/debug/upload", data=body)
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True and data["bytes"] == 4
        # The server names the file; the client only supplies bytes.
        assert Path(data["path"]).name.startswith("snapshot-")
        assert Path(data["path"]).parent == photos
        assert Path(data["path"]).read_bytes() == b"\xff\xd8\xff\xd9"


async def test_other_debug_still_401(tmp_path):
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        for method, path in (("POST", "/debug/mcp"),
                             ("GET", "/debug/photo/x.jpg"),
                             ("POST", "/debug/upload/"),      # exact match only
                             ("GET", "/debug/upload")):
            resp = await client.request(method, path)
            assert resp.status == 401, f"{method} {path}"


# camera path

async def _post_question(client, headers, question="what is this"):
    body = aiohttp.MultipartWriter("form-data")
    part = body.append(question)
    part.set_content_disposition("form-data", name="question")
    return await client.post("/xiaozhi/vision", data=body, headers=headers)


async def test_vision_control_default(tmp_path):
    cfg = make_cfg(tmp_path)                       # vision_token is ""
    async with running(build_app(cfg)) as client:
        assert (await _post_question(client, {})).status == 401
        # No file part -> the handler answers 400 before any vision model call.
        resp = await _post_question(client, auth(CONTROL))
        assert resp.status == 400
        assert (await resp.json())["error"] == "no image"


async def test_vision_configured_token(tmp_path):
    cfg = make_cfg(tmp_path, vision_token=VISION)
    async with running(build_app(cfg)) as client:
        assert (await _post_question(client, auth("wrong-token"))).status == 401
        assert (await _post_question(client, auth(VISION))).status == 400
        assert (await _post_question(client, auth(CONTROL))).status == 400
