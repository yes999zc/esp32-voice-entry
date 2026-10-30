"""MCP server (stdio) that exposes the ESP32 board to Hermes.

Hermes ignores the OpenAI `tools` we pass to its chat endpoint — it runs its own
agent loop — so the only way to give it the board's camera and controls is to
speak MCP. This shim advertises the same tool list as `src/tools.py` and forwards
each call to the running voice server's bench endpoint, which owns the live
websocket session with the device.

Written against the low-level mcp.server.Server API (mcp 2.x): the high-level
decorator API from 1.x is gone, and add_tool() there derives schemas from Python
signatures, which is awkward for a generated tool table.

Run by Hermes (`hermes mcp add`), not by a human.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import tools as devtools  # noqa: E402

VOICE_URL = os.environ.get("ESP32_VOICE_URL", "http://127.0.0.1:4411")
CONTROL_TOKEN_FILE = os.environ.get("ESP32_CONTROL_TOKEN_FILE",
                                    "~/.esp32-voice/control.token")

server = Server("esp32-device")


def _control_token() -> str:
    """Same source as the voice server: env first, then the shared token file."""
    env = os.environ.get("ESP32_CONTROL_TOKEN", "").strip()
    if env:
        return env
    try:
        return Path(CONTROL_TOKEN_FILE).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _call_device(name: str, arguments: dict) -> dict:
    token = _control_token()
    if not token:
        return {"error": "no control token: set ESP32_CONTROL_TOKEN or start the "
                         "voice server once to generate " + CONTROL_TOKEN_FILE}
    payload = json.dumps({"name": name, "arguments": arguments}).encode()
    req = urllib.request.Request(
        VOICE_URL + "/debug/tool", data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=95) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return {"error": f"voice server HTTP {exc.code}: {body[:200]}"}
    except Exception as exc:  # refused, timeout, ...
        return {"error": f"voice server unreachable: {type(exc).__name__}: {exc}"}


async def handle_list_tools(ctx, params):
    tools = []
    for spec in devtools.DEVICE_TOOLS:
        fn = spec["function"]
        if fn["name"] in devtools.SESSION_ENDING:
            # AEC switching closes the audio channel before replying; an agent
            # must never be able to hang up the channel it is talking through.
            continue
        tools.append(types.Tool(
            name=fn["name"],
            description=fn.get("description", ""),
            input_schema=fn.get("parameters") or {"type": "object", "properties": {}},
        ))
    return types.ListToolsResult(tools=tools)


async def handle_call_tool(ctx, params):
    name = params.name
    arguments = params.arguments or {}
    data = await anyio.to_thread.run_sync(lambda: _call_device(name, arguments))
    if "error" in data:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(
                {"ok": False, "error": data["error"]}, ensure_ascii=False))],
            is_error=True)
    results = data.get("results") or []
    if not results:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(
                {"ok": False, "error": "no live device session (board asleep?)"},
                ensure_ascii=False))],
            is_error=True)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=str(results[0].get("result", "")))],
        is_error=False)


server.add_request_handler("tools/list", types.PaginatedRequestParams, handle_list_tools)
server.add_request_handler("tools/call", types.CallToolRequestParams, handle_call_tool)


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
