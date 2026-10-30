"""Device camera endpoint.

The firmware's `self.camera.take_photo` tool captures a frame, encodes it to
JPEG and POSTs it here as multipart/form-data (`question` + `file`). The
explain URL itself arrives from the MCP `initialize` capabilities we send on
handshake, so this server owns where the photo goes.

We save every photo to disk (proof + replay) and describe it with the local
oMLX vision model, returning the description as the tool result.
"""
import asyncio
import base64
import datetime
import json
import os
import re
import time
from contextlib import suppress
from pathlib import Path

import aiohttp
from aiohttp import web

import persona
import proactive
import tools as devtools
import mute

PHOTO_DIR = Path.home() / ".hermes/cache/scratch/esp32-voice/photos"
# `latest` only ever answers an image: snapshot uploads are .jpg, the
# preview_image test path is .png, and raw bodies arrive as .bin.
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")
NOTIFY_DIR = PHOTO_DIR.parent / "notify"
SCREEN_DIR = PHOTO_DIR.parent / "screen"


async def describe(jpeg: bytes, question: str, cfg: dict) -> str:
    v = cfg["vision"]
    key = os.environ.get(v.get("api_key_env", ""), "") or v.get("api_key", "")
    if not key:
        key_file = Path(v.get("api_key_file", "~/.hermes/keys/omlx.key")).expanduser()
        if key_file.exists():
            key = key_file.read_text().strip()
    prompt = question or "描述这张照片里有什么。"
    prompt += "\n用中文口语回答，40 字以内，不要 markdown、不要列表、不要分点。"
    payload = {
        "model": v["model"],
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}},
            ],
        }],
        "max_tokens": 300,
        "temperature": 0.2,
    }
    timeout = aiohttp.ClientTimeout(total=float(v.get("timeout", 60)))
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        async with sess.post(v["base_url"].rstrip("/") + "/chat/completions",
                             json=payload,
                             headers={"Authorization": f"Bearer {key}"}) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"vision http {resp.status}: {body[:200]}")
            data = await resp.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


def _parse_reminder_when(value: str, now: datetime.datetime) -> datetime.datetime | None:
    """`+300s` / `+5m` / `+1h` / ISO8601 -> naive local datetime, or None.

    The server (and proactive) work in naive local wall-clock time, so an aware
    timestamp is converted to local time and stripped; a bare time is taken as
    local. Returning None lets the route answer 400 instead of scheduling a
    reminder at a surprising instant.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.startswith("+"):
        match = re.fullmatch(r"\+(\d+(?:\.\d+)?)([smhSMH]?)", raw)
        if match is None:
            return None
        amount = float(match.group(1))
        unit = (match.group(2) or "s").lower()
        seconds = amount * {"s": 1, "m": 60, "h": 3600}[unit]
        if seconds <= 0:
            return None
        return now + datetime.timedelta(seconds=seconds)
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def make_router(cfg: dict, sessions, tts=None, resample=None, mute_state=None):
    """Return an `app -> None` registrar for the OTA aiohttp app."""

    def _catchup_status() -> dict:
        """Queue depth + catch-up counters, without creating a controller."""
        controller = proactive.get_controller()
        if controller is None:
            return {"pending": 0, "missed": 0, "spoken": 0, "last_at": None,
                    "running": False, "last_result": None}
        return controller.catchup_status()

    # B1: the changed decision + persist + catch-up start must be one critical
    # section, otherwise two concurrent `off` calls can both report changed=true.
    mute_switch_lock = asyncio.Lock()

    async def vision_post(request: web.Request) -> web.Response:
        question = ""
        jpeg = b""
        dev = request.headers.get("Device-Id", "?")
        reader = await request.multipart()
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "question":
                question = (await part.text()).strip()
            elif part.name == "file":
                jpeg = await part.read(decode=False)
        if not jpeg:
            print("[vision] empty upload", flush=True)
            return web.json_response({"success": False, "error": "no image"}, status=400)

        PHOTO_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = PHOTO_DIR / f"{stamp}.jpg"
        path.write_bytes(jpeg)
        print(f"[vision] {len(jpeg)} bytes from {dev} q={question!r} -> {path}",
              flush=True)
        try:
            text = await describe(jpeg, question, cfg)
        except Exception as exc:
            print(f"[vision] describe failed: {type(exc).__name__}: {exc}", flush=True)
            return web.json_response({"success": False, "error": str(exc)[:200]})
        print(f"[vision] -> {text[:200]}", flush=True)
        # The firmware hands this body back verbatim as the tool result, so keep
        # it JSON: both a human and the LLM can read it.
        return web.json_response({"success": True, "text": text, "path": str(path)})

    async def debug_mcp(request: web.Request) -> web.Response:
        body = await request.json()
        name = body.get("name")
        args = body.get("arguments") or {}
        if not name:
            return web.json_response({"error": "name required"}, status=400)
        # Raw tool calls bypass `Session.call_device_tool`, so the spoken-confirm
        # gate never runs here. Destructive tools must go through /debug/tool with
        # a live session instead; they are refused even with a valid token.
        # Normalize exactly like `call_device_tool`: aliases map to firmware names,
        # `self.*` is passed through, unknown names are left untouched (bench use).
        if name.startswith("self."):
            device_name = name
        else:
            device_name = devtools.DEVICE_NAME.get(name) or name
        confirm_tools = (cfg.get("safety") or {}).get("confirm_tools") or ()
        if device_name in confirm_tools:
            print(f"[debug] mcp BLOCKED {name} (-> {device_name}): needs spoken confirmation",
                  flush=True)
            return web.json_response({"ok": False, "blocked": name,
                                      "reason": "requires spoken confirmation; "
                                                "use /debug/tool with a live session"},
                                     status=403)
        sent = 0
        for sess in list(sessions()):
            await sess.send_tool_call(name, args)
            sent += 1
        print(f"[debug] mcp {name} {json.dumps(args, ensure_ascii=False)} -> {sent} session(s)",
              flush=True)
        return web.json_response({"sent": sent, "name": name})

    async def debug_tool(request: web.Request) -> web.Response:
        """Call a tool and wait for the device's result; for bench sweeps (M3)."""
        body = await request.json()
        name = body.get("name")
        args = body.get("arguments") or {}
        if not name:
            return web.json_response({"error": "name required"}, status=400)
        live = list(sessions())
        if not live:
            return web.json_response({"sent": 0, "error": "no live session"}, status=503)
        results = []
        for sess in live:
            t0 = time.perf_counter()
            result = await sess.call_device_tool(name, args)
            results.append({"session": sess.session_id[:6],
                            "ms": round((time.perf_counter() - t0) * 1000),
                            "result": result})
        return web.json_response({"sent": len(live), "name": name, "results": results})

    async def debug_upload(request: web.Request) -> web.Response:
        """Sink for self.screen.snapshot (multipart `file`) and raw uploads."""
        kind = "bin"
        body = b""
        if request.content_type.startswith("multipart/"):
            # Must not pre-read the body: aiohttp's reader needs the stream.
            reader = await request.multipart()
            while True:
                part = await reader.next()
                if part is None:
                    break
                if part.name == "file":
                    body = await part.read(decode=False)
                    kind = "jpg"
        else:
            body = await request.read()
        if not body:
            print("[debug] upload empty", flush=True)
            return web.json_response({"ok": False, "error": "empty body"}, status=400)
        PHOTO_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = PHOTO_DIR / f"snapshot-{stamp}.{kind}"
        path.write_bytes(body)
        print(f"[debug] upload {len(body)} bytes -> {path}", flush=True)
        return web.json_response({"ok": True, "path": str(path), "bytes": len(body)})

    async def debug_turn(request: web.Request) -> web.Response:
        """Run a full turn from text (no microphone): bench for filler/tool timing."""
        body = await request.json()
        text = (body.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "text required"}, status=400)
        live = list(sessions())
        if not live:
            return web.json_response({"sent": 0, "error": "no live session"}, status=503)
        started = [sess for sess in live if sess.start_text_turn(text) is not None]
        if not started:
            return web.json_response(
                {"sent": 0, "busy": len(live), "error": "turn in flight"}, status=409)
        print(f"[debug] text turn {text!r} -> {len(started)} session(s)", flush=True)
        return web.json_response({"sent": len(started), "busy": len(live) - len(started),
                                  "text": text})

    async def debug_emotion(request: web.Request) -> web.Response:
        """Push an expression to live sessions (`llm`/`emotion`, no turn).

        The firmware dispatches `llm` + `emotion` in every device state
        (`main/application.cc:683-689`), so this also works while the board is
        Listening or Speaking. A fully idle board has no WS session at all, so
        there is nobody to push to: that is `{"sent": 0}`, not an error.
        """
        body = await request.json()
        raw = body.get("emotion")
        name = raw.strip().lower() if isinstance(raw, str) else ""
        if not name:
            return web.json_response({"error": "emotion required"}, status=400)
        if not persona.is_emotion(name):
            return web.json_response(
                {"error": f"unknown emotion: {name}",
                 "known": sorted(persona.EMOTION_NAMES)}, status=400)
        raw_prefix = body.get("session")
        prefix = raw_prefix.strip() if isinstance(raw_prefix, str) else ""
        targets = [sess for sess in list(sessions())
                   if not prefix or sess.session_id.startswith(prefix)]
        for sess in targets:
            await sess.push_emotion(name)
        print(f"[debug] emotion {name} -> {len(targets)} session(s)"
              + (f" matching {prefix!r}" if prefix else ""), flush=True)
        return web.json_response({"sent": len(targets), "emotion": name})

    async def debug_file(request: web.Request) -> web.Response:
        """Serve a saved photo so we can test self.screen.preview_image.

        `latest` is the console's shortcut to the newest image: `snapshot`
        uploads through the anonymous POST /debug/upload, so the browser never
        learns the server-side filename. It resolves inside this same route and
        stays behind the Bearer gate - no directory listing is exposed.
        """
        name = request.match_info["name"]
        if name == "latest":
            newest = None
            if PHOTO_DIR.is_dir():
                # Raw /debug/upload bodies land here as .bin too; feeding one to
                # an <img> would just break the console preview.
                files = [p for p in PHOTO_DIR.iterdir()
                         if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES]
                if files:
                    newest = max(files, key=lambda p: p.stat().st_mtime)
            if newest is None:
                raise web.HTTPNotFound()
            return web.FileResponse(newest,
                                    headers={"Cache-Control": "no-store"})
        path = PHOTO_DIR / name
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def debug_notify(request: web.Request) -> web.Response:
        """Speak a line on the device right now (one-way `notify`, no mic)."""
        body = await request.json()
        text = (body.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "text required"}, status=400)
        if tts is None:
            return web.json_response({"error": "tts not wired"}, status=500)
        import subprocess
        import wave

        NOTIFY_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        wav_path = NOTIFY_DIR / f"{stamp}.wav"
        ogg_path = NOTIFY_DIR / f"{stamp}.ogg"
        pcm, rate = await tts.synth(text)
        with wave.open(str(wav_path), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(rate)
            fh.writeframes(pcm.tobytes())
        # The firmware only accepts single-stream mono Ogg Opus on http(s).
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(wav_path), "-c:a", "libopus", "-b:a", "32k",
            "-ac", "1", "-f", "ogg", str(ogg_path),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        if proc.returncode != 0 or not ogg_path.exists():
            return web.json_response({"error": f"ffmpeg failed: {err[:200].decode(errors='replace')}"},
                                     status=500)
        base = cfg["server"].get("ws_url", "").replace("ws://", "http://").rsplit(":", 1)[0]
        url = f"{base}:{cfg['server']['ota_port']}/notify/{ogg_path.name}"
        pushed = 0
        for sess in list(sessions()):
            if await sess.send_notify(url, text):
                pushed += 1
        queued = 0
        if pushed == 0:
            from session import queue_notification
            queued = queue_notification(text)
        print(f"[notify] {text[:40]!r} -> {pushed} session(s), queued={queued} {url}",
              flush=True)
        return web.json_response({"pushed": pushed, "queued": queued, "url": url,
                                  "bytes": ogg_path.stat().st_size})

    matrix_state = {"on": False, "task": None, "rain": None}

    def _screen_base() -> str:
        base = cfg["server"].get("ws_url", "").replace("ws://", "http://").rsplit(":", 1)[0]
        return f"{base}:{cfg['server']['ota_port']}"

    async def matrix_loop(fps: float) -> None:
        """Render the data stream and push each frame to the device.

        The stock firmware has no custom UI, so the only way in is preview_image:
        it takes a URL, downloads it and shows it (auto-hiding after 5 s, which is
        why we keep pushing).
        """
        from matrix import MatrixRain, render_png

        SCREEN_DIR.mkdir(parents=True, exist_ok=True)
        rain = MatrixRain()
        matrix_state["rain"] = rain
        frame = 0
        while matrix_state["on"]:
            rain.step()
            frame += 1
            name = f"frame-{frame % 2}.png"
            path = SCREEN_DIR / name
            try:
                render_png(str(path), rain)
            except Exception as exc:
                print(f"[matrix] render failed: {exc}", flush=True)
                await asyncio.sleep(1.0)
                continue
            url = f"{_screen_base()}/screen/{name}?f={frame}"
            for sess in list(sessions()):
                try:
                    await asyncio.wait_for(
                        sess.call_device_tool("self.screen.preview_image", {"url": url}),
                        timeout=2.5)
                except Exception:
                    pass                    # a dropped frame is not a failure
            await asyncio.sleep(max(0.05, 1.0 / fps))
        print("[matrix] stopped", flush=True)

    async def debug_matrix(request: web.Request) -> web.Response:
        body = await request.json()
        on = bool(body.get("on", True))
        fps = float(body.get("fps", 3))
        matrix_state["on"] = on
        if on and (matrix_state["task"] is None or matrix_state["task"].done()):
            matrix_state["task"] = asyncio.create_task(matrix_loop(fps))
        print(f"[matrix] {'on' if on else 'off'} at {fps} fps", flush=True)
        return web.json_response({"on": on, "fps": fps})

    async def screen_file(request: web.Request) -> web.Response:
        path = SCREEN_DIR / request.match_info["name"]
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Content-Type": "image/png",
                                              "Cache-Control": "no-store"})

    async def debug_reminder_list(request: web.Request) -> web.Response:
        """List pending reminders with their absolute local fire time.

        Absolute times are echoed on purpose: bench scenarios are built by hand,
        and a bare "+300s" cannot be checked against a wall clock afterwards.
        """
        controller = proactive.get_controller()
        if controller is None:
            return web.json_response({"ok": False,
                                      "error": "proactive not configured"},
                                     status=503)
        now = controller._now()
        return web.json_response({"ok": True,
                                  "now": now.isoformat(timespec="seconds"),
                                  "count": len(controller.state.reminders),
                                  "reminders": controller.list_reminders(now)})

    async def debug_reminder_create(request: web.Request) -> web.Response:
        """Create a reminder from `when` + `text`, or from natural-language text.

        `when` accepts an ISO8601 local timestamp (`2026-10-27T15:05:00`) or a
        relative offset (`+300s`, `+5m`, `+1h`). Without `when` the text is
        parsed like a spoken request (`3 分钟后提醒我喝水`).
        """
        controller = proactive.get_controller()
        if controller is None:
            return web.json_response({"ok": False,
                                      "error": "proactive not configured"},
                                     status=503)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"},
                                     status=400)
        text = str(body.get("text") or "").strip()
        if not text:
            return web.json_response({"ok": False, "error": "text required"},
                                     status=400)
        now = controller._now()
        raw_when = str(body.get("when") or "").strip()
        if raw_when:
            when = _parse_reminder_when(raw_when, now)
            if when is None:
                return web.json_response(
                    {"ok": False, "when": raw_when,
                     "error": "bad when: use ISO8601 local time or +300s / +5m / +1h"},
                    status=400)
            reminder = controller.add_reminder(text, when, now)
        else:
            reminder = controller.schedule_from_text(text, now)
            if reminder is None:
                return web.json_response(
                    {"ok": False, "text": text,
                     "error": "cannot parse a reminder time from text"}, status=400)
        at = datetime.datetime.fromisoformat(reminder["at"])
        return web.json_response({
            "ok": True,
            "now": now.isoformat(timespec="seconds"),
            "reminder": reminder,
            # Whole seconds: `at` is stored truncated to the second (see
            # `ProactiveController.add_reminder`), so echoing 299.7 here would
            # only leak the sub-second offset of the request itself.
            "in_seconds": round((at - now).total_seconds()),
        })

    async def debug_reminder_delete(request: web.Request) -> web.Response:
        controller = proactive.get_controller()
        if controller is None:
            return web.json_response({"ok": False,
                                      "error": "proactive not configured"},
                                     status=503)
        reminder_id = request.match_info["reminder_id"]
        if not controller.delete_reminder(reminder_id):
            return web.json_response({"ok": False, "id": reminder_id,
                                      "error": "unknown reminder"}, status=404)
        return web.json_response({"ok": True, "deleted": reminder_id})

    async def debug_proactive_status(request: web.Request) -> web.Response:
        """Proactive v0 counters: attempts, rejections, mute, socket state.

        Bearer-protected like every other /debug route; no side effects apart
        from the daily counter rollover inside `status()`.
        """
        controller = proactive.get_controller()
        if controller is None:
            return web.json_response({"enabled": False,
                                      "error": "proactive not configured"},
                                     status=503)
        return web.json_response(controller.status())

    async def debug_mute_get(request: web.Request) -> web.Response:
        """B1 mute status: the switch, mode A note, frame counters, catch-up."""
        state = mute_state if mute_state is not None else mute.get_state()
        if state is None:
            return web.json_response({"ok": False, "error": "mute not configured"},
                                     status=503)
        body = {"ok": True}
        body.update(state.status())
        body["catchup"] = _catchup_status()
        return web.json_response(body)

    async def debug_mute_set(request: web.Request) -> web.Response:
        """Flip the server-side mute switch and persist it (same truth as 4410).

        Body must be `{"muted": true|false}`. A failed persistence answers 500
        and leaves the in-memory state untouched (see mute.MuteState.set_muted).
        Turning it off starts the catch-up in a background task and answers
        immediately (`catchup_started`), so a slow TTS cannot time out the CLI;
        GET /debug/mute reports `catchup.running` / `catchup.last_result`.
        """
        state = mute_state if mute_state is not None else mute.get_state()
        if state is None:
            return web.json_response({"ok": False, "error": "mute not configured"},
                                     status=503)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"},
                                     status=400)
        value = body.get("muted") if isinstance(body, dict) else None
        if not isinstance(value, bool):
            return web.json_response(
                {"ok": False, "error": 'body must be {"muted": true|false}'},
                status=400)
        async with mute_switch_lock:
            changed = value != state.muted
            ok, error = state.set_muted(value, changed_by="http")
            if not ok:
                return web.json_response({"ok": False, "error": error,
                                          "muted": state.muted}, status=500)
            catchup_started = False
            if changed and not value:
                controller = proactive.get_controller()
                if controller is not None:
                    catchup_started = controller.start_catchup()
            result = {"ok": True, "changed": changed,
                      "catchup_started": catchup_started}
            result.update(state.status())
            result["catchup"] = _catchup_status()
        return web.json_response(result)

    async def notify_file(request: web.Request) -> web.Response:
        path = NOTIFY_DIR / request.match_info["name"]
        if not path.is_file():
            raise web.HTTPNotFound()
        print(f"[notify] device fetched {path.name} ({path.stat().st_size} bytes)",
              flush=True)
        return web.FileResponse(path, headers={"Content-Type": "audio/ogg"})

    async def _proactive_startup(app: web.Application) -> None:
        """Build the process-wide controller and start the reminder ticker.

        The worker only runs when proactive is enabled; a disabled deployment
        still gets `/debug/proactive/status` with counters at zero.
        """
        try:
            controller = proactive.configure(
                cfg, sessions,
                mute=mute_state if mute_state is not None else mute.get_state())
        except Exception as exc:
            # A proactive typo must not take the whole HTTP app down.
            print(f"[proactive] init failed {type(exc).__name__}: {exc}", flush=True)
            controller = proactive.configure({"proactive": {"enabled": False}},
                                             sessions,
                                             mute=mute_state if mute_state
                                             is not None else mute.get_state())
        if not controller.cfg.enabled:
            print("[proactive] disabled by config", flush=True)
            return
        if not bool((cfg.get("proactive") or {}).get("worker", True)):
            print("[proactive] worker disabled by config", flush=True)
            return
        controller.worker_task = asyncio.create_task(
            controller.run_forever(), name="proactive")
        print("[proactive] worker started", flush=True)

    async def _proactive_cleanup(app: web.Application) -> None:
        """Stop the ticker; a worker that already died must not fail shutdown."""
        controller = proactive.get_controller()
        task = controller.worker_task if controller is not None else None
        if task is not None:
            task.cancel()
            # CancelledError is the expected path; Exception covers a worker
            # that already crashed before shutdown (task.exception() consumed).
            with suppress(asyncio.CancelledError, Exception):
                await task
            print("[proactive] worker stopped", flush=True)

    def register(app: web.Application) -> None:
        app.on_startup.append(_proactive_startup)
        app.on_cleanup.append(_proactive_cleanup)
        app.router.add_post("/xiaozhi/vision", vision_post)
        app.router.add_post("/debug/mcp", debug_mcp)
        app.router.add_post("/debug/tool", debug_tool)
        app.router.add_post("/debug/turn", debug_turn)
        app.router.add_post("/debug/emotion", debug_emotion)
        app.router.add_post("/debug/upload", debug_upload)
        app.router.add_post("/debug/notify", debug_notify)
        app.router.add_get("/debug/photo/{name}", debug_file)
        app.router.add_get("/notify/{name}", notify_file)
        app.router.add_post("/debug/matrix", debug_matrix)
        app.router.add_get("/debug/proactive/status", debug_proactive_status)
        app.router.add_get("/debug/mute", debug_mute_get)
        app.router.add_post("/debug/mute", debug_mute_set)
        app.router.add_post("/debug/reminder", debug_reminder_create)
        app.router.add_get("/debug/reminder", debug_reminder_list)
        app.router.add_delete("/debug/reminder/{reminder_id}", debug_reminder_delete)
        app.router.add_get("/screen/{name}", screen_file)

    return register
