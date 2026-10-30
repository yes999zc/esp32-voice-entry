"""Minimal OTA endpoint for the device.

The firmware boots, joins Wi-Fi, POSTs to its configured OTA URL and reads the
`websocket.url` back from the JSON response. Without this endpoint the board
falls back to `api.tenclass.net` (the public XiaoZhi cloud), so this server has
to answer that request to get the device pointed at us.

Response shape the firmware parses (main/ota.cc):
  websocket:    flat map, every field is stored into the "websocket" settings
  server_time:  {timestamp: ms, timezone_offset: minutes}
  firmware:     optional OTA upgrade; omitted = stay on the flashed image

The same aiohttp app also hosts the camera sink and the /debug/* control plane
(see vision.py), so this module owns the Bearer gate that protects them.
"""
import hmac
import os
import re
import secrets
import time
from pathlib import Path

from aiohttp import web

DEFAULT_CONTROL_TOKEN_FILE = "~/.esp32-voice/control.token"

# The device cannot attach a header on these four calls: OTA happens before it
# has read any capability, the media URLs are handed to the firmware's audio and
# display players, and `self.screen.snapshot` POSTs its frame to /debug/upload
# before it can know our control token. Everything else requires the token.
#
# `/admin` is anonymous for a different reason: it is the console's own login
# screen. The page ships no secret and every byte of data it shows comes from a
# Bearer-protected /debug route, so gating the shell would only force a human to
# paste an Authorization header into a browser.
_ANONYMOUS_GET = (
    re.compile(r"/notify/[^/]+"),
    re.compile(r"/screen/[^/]+"),
    re.compile(r"/admin/?"),
)

ADMIN_PAGE = Path(__file__).with_name("admin.html")

# One static file with inline CSS/JS: 'unsafe-inline' is required for
# script/style, and everything else is locked down. There is no network origin
# in the page - all calls are same-origin relative paths.
_ADMIN_CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "connect-src 'self'; "
    "img-src 'self' blob:; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def _is_anonymous(request: web.Request) -> bool:
    if request.method == "POST" and request.path in ("/xiaozhi/ota/",
                                                     "/debug/upload"):
        return True
    if request.method == "GET":
        return any(p.fullmatch(request.path) for p in _ANONYMOUS_GET)
    return False


def resolve_control_token(cfg: dict) -> str:
    """Return the control-plane token, generating and persisting one if needed.

    Priority: ESP32_CONTROL_TOKEN > security.control_token_file > generate.
    The token is never logged, and the file lives outside the repository.
    """
    env = os.environ.get("ESP32_CONTROL_TOKEN", "").strip()
    if env:
        return env

    configured = (cfg.get("security") or {}).get("control_token_file",
                                                DEFAULT_CONTROL_TOKEN_FILE)
    path = Path(configured).expanduser()
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    if token:
        return token

    token = secrets.token_urlsafe(32)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token + "\n")
    os.chmod(path, 0o600)
    print(f"[auth] generated control token -> {path}", flush=True)
    return token


def effective_vision_token(cfg: dict, control_token: str) -> str:
    """What MCP initialize pushes as capabilities.vision.token.

    An explicit server.vision_token wins; empty means "reuse the control token"
    so the camera keeps working out of the box.
    """
    return (cfg["server"].get("vision_token") or "").strip() or control_token


def _bearer(request: web.Request) -> bytes:
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return b""
    return value.strip().encode()


def make_auth_middleware(control_token: str, vision_token: str):
    """Build the aiohttp middleware that gates every non-anonymous route."""

    @web.middleware
    async def auth_middleware(request: web.Request, handler):
        if _is_anonymous(request):
            return await handler(request)
        presented = _bearer(request)
        accepted = [control_token.encode()]
        if request.path == "/xiaozhi/vision":
            accepted.append(vision_token.encode())
        if not any(hmac.compare_digest(presented, want) for want in accepted):
            return web.json_response({"ok": False, "error": "unauthorized"},
                                     status=401)
        return await handler(request)

    return auth_middleware


def build_app(cfg: dict, extras=(), control_token: str | None = None) -> web.Application:
    ws_url = cfg["server"]["ws_url"]
    tz_minutes = int(cfg["server"].get("timezone_minutes", 480))
    if not control_token:
        control_token = resolve_control_token(cfg)
    vision_token = effective_vision_token(cfg, control_token)

    async def ota(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        app_name = body.get("application", {}).get("name", "?")
        version = body.get("application", {}).get("version", "?")
        print(f"[ota] {app_name} v{version} -> {ws_url}", flush=True)
        return web.json_response({
            "websocket": {"url": ws_url, "token": "", "version": 1},
            "server_time": {
                "timestamp": int(time.time() * 1000),
                "timezone_offset": tz_minutes,
            },
        })

    async def health(request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "ws": ws_url})

    async def admin(request: web.Request) -> web.Response:
        """Serve the single-page console (anonymous shell, protected data).

        No-store so a token typed into the page can never come back from a
        browser cache after sign-out; the CSP is the one for inline assets.
        """
        try:
            html = ADMIN_PAGE.read_text(encoding="utf-8")
        except OSError:
            raise web.HTTPNotFound()
        return web.Response(text=html, content_type="text/html",
                            headers={"Cache-Control": "no-store",
                                     "Content-Security-Policy": _ADMIN_CSP,
                                     "Referrer-Policy": "no-referrer",
                                     "X-Content-Type-Options": "nosniff"})

    app = web.Application(client_max_size=8 << 20,
                          middlewares=[make_auth_middleware(control_token,
                                                            vision_token)])
    app.router.add_post("/xiaozhi/ota/", ota)
    app.router.add_get("/xiaozhi/ota/", health)
    app.router.add_get("/admin", admin)
    app.router.add_get("/admin/", admin)
    for extra in extras or ():
        extra(app)
    return app


async def start(cfg: dict, host: str | None = None, extras=(), control_token: str | None = None):
    host = host or cfg["server"].get("host", "0.0.0.0")
    runner = web.AppRunner(build_app(cfg, extras, control_token=control_token))
    await runner.setup()
    site = web.TCPSite(runner, host, int(cfg["server"]["ota_port"]))
    await site.start()
    print(f"[ota] listening on http://{host}:{cfg['server']['ota_port']}/xiaozhi/ota/",
          flush=True)
    return runner
