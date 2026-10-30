"""The /admin console shell: anonymous page, protected data.

The page is one static HTML file. What matters here is the *authorization
boundary*: the shell is anonymous (it is the login form), every /debug route it
calls stays Bearer-protected, and the page itself carries no secret and no
hard-coded network origin.
"""
import re
import sys
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from contextlib import asynccontextmanager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ota  # noqa: E402
import vision  # noqa: E402

CONTROL = "test-control-token"
PAGE = ROOT / "src" / "admin.html"


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


def build_app(cfg):
    extras = [vision.make_router(cfg, lambda: [])]
    return ota.build_app(cfg, extras=tuple(extras), control_token=CONTROL)


@asynccontextmanager
async def running(app):
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


def auth(token: str = CONTROL) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# the shell is anonymous
# ---------------------------------------------------------------------------

async def test_admin_page_is_anonymous(tmp_path):
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        for path in ("/admin", "/admin/"):
            resp = await client.get(path)
            assert resp.status == 200, path
            assert resp.content_type == "text/html"
            body = await resp.text()
            # The login card, the language toggle and the three sections.
            assert 'id="loginForm"' in body
            assert 'id="langBtn"' in body
            for view in ("overview", "control", "diag"):
                assert f'id="panel-{view}"' in body
            assert f'id="tab-{view}"' in body


async def test_admin_page_cache_and_csp(tmp_path):
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        resp = await client.get("/admin")
        assert resp.headers["Cache-Control"] == "no-store"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["Referrer-Policy"] == "no-referrer"
        csp = resp.headers["Content-Security-Policy"]
        # Same-origin data only, no remote script/style origin, no framing.
        assert "connect-src 'self'" in csp
        assert "img-src 'self' blob:" in csp
        assert "frame-ancestors 'none'" in csp
        assert "http://" not in csp and "https://" not in csp


async def test_admin_html_file_is_not_whitelisted(tmp_path):
    """Only the two page paths are anonymous; the source file is not a route."""
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        assert (await client.get("/admin.html")).status == 401
        assert (await client.get("/admin/extra")).status == 401


async def test_admin_page_has_no_secrets_or_origins(tmp_path):
    body = PAGE.read_text(encoding="utf-8")
    # No hard-coded network origin, host, SSID, personal path or token.
    assert "http://" not in body.replace("http://www.w3.org", "")
    assert "https://" not in body
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", body), "no literal IPv4"
    assert "/Users/" not in body
    assert CONTROL not in body
    # Relative API paths only: the console must work on any host/port.
    for path in ("/debug/mute", "/debug/emotion", "/debug/turn",
                 "/debug/proactive/status", "/debug/reminder",
                 "/debug/photo/latest", "/debug/upload"):
        assert path in body, path


# ---------------------------------------------------------------------------
# the data behind it stays protected
# ---------------------------------------------------------------------------

async def test_admin_does_not_open_debug_routes(tmp_path):
    cfg = make_cfg(tmp_path)
    protected = [
        ("GET", "/debug/mute"),
        ("POST", "/debug/mute"),
        ("GET", "/debug/proactive/status"),
        ("GET", "/debug/reminder"),
        ("POST", "/debug/tool"),
        ("POST", "/debug/emotion"),
        ("POST", "/debug/turn"),
        ("GET", "/debug/photo/latest"),
        ("GET", "/debug/photo/x.jpg"),
    ]
    async with running(build_app(cfg)) as client:
        for method, path in protected:
            resp = await client.request(method, path)
            assert resp.status == 401, f"{method} {path}"


async def test_admin_token_reaches_mute(tmp_path):
    """A valid token gets past the gate; no mute state wired means 503, not 401."""
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        resp = await client.get("/debug/mute", headers=auth())
        assert resp.status == 503
        assert (await resp.json())["ok"] is False


# ---------------------------------------------------------------------------
# /debug/photo/latest (the console's screenshot preview)
# ---------------------------------------------------------------------------

async def test_latest_photo_is_protected(tmp_path, monkeypatch):
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    monkeypatch.setattr(vision, "PHOTO_DIR", photos)
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        assert (await client.get("/debug/photo/latest")).status == 401
        resp = await client.get("/debug/photo/latest", headers=auth())
        assert resp.status == 200
        assert await resp.read() == b"\xff\xd8\xff\xd9"
        assert resp.headers["Cache-Control"] == "no-store"


async def test_latest_photo_prefers_newest(tmp_path, monkeypatch):
    photos = tmp_path / "photos"
    photos.mkdir()
    old = photos / "snapshot-old.jpg"
    new = photos / "snapshot-new.jpg"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    import os
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))
    monkeypatch.setattr(vision, "PHOTO_DIR", photos)
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        resp = await client.get("/debug/photo/latest", headers=auth())
        assert await resp.read() == b"new"


async def test_latest_photo_skips_non_images(tmp_path, monkeypatch):
    """A newer .bin (raw /debug/upload body) must not win: it would break <img>."""
    photos = tmp_path / "photos"
    photos.mkdir()
    image = photos / "snapshot-image.jpg"
    blob = photos / "raw-latest.bin"
    image.write_bytes(b"\xff\xd8\xff\xd9")
    blob.write_bytes(b"\x00\x01\x02")
    import os
    os.utime(image, (1_000_000, 1_000_000))
    os.utime(blob, (3_000_000, 3_000_000))    # newest, but not an image
    monkeypatch.setattr(vision, "PHOTO_DIR", photos)
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        resp = await client.get("/debug/photo/latest", headers=auth())
        assert resp.status == 200
        assert await resp.read() == b"\xff\xd8\xff\xd9"


async def test_latest_photo_404_when_only_non_images(tmp_path, monkeypatch):
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "raw.bin").write_bytes(b"\x00")
    monkeypatch.setattr(vision, "PHOTO_DIR", photos)
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        resp = await client.get("/debug/photo/latest", headers=auth())
        assert resp.status == 404


async def test_latest_photo_404_when_empty(tmp_path, monkeypatch):
    photos = tmp_path / "photos"
    photos.mkdir()
    monkeypatch.setattr(vision, "PHOTO_DIR", photos)
    cfg = make_cfg(tmp_path)
    async with running(build_app(cfg)) as client:
        resp = await client.get("/debug/photo/latest", headers=auth())
        assert resp.status == 404
