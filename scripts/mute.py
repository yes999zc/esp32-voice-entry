#!/usr/bin/env python3
"""Flip the server-side mute switch from the command line (B1, mode A).

Usage
-----
    .venv313/bin/python scripts/mute.py status
    .venv313/bin/python scripts/mute.py on
    .venv313/bin/python scripts/mute.py off --json
    .venv313/bin/python scripts/mute.py status --base-url http://127.0.0.1:4411

This is a pure HTTP client for the 4411 control plane; the switch itself lives
in the server process, so the CLI and the 4410 audio gate always agree. The
Bearer token comes from `ESP32_CONTROL_TOKEN` or `~/.esp32-voice/control.token`
(the file the server generates on first start).

Exit codes: 0 = success, 1 = request/token failure, 2 = usage error.

Mode A means the server drops the uplink frames before Opus decode. The board
keeps capturing and uploading; only a firmware change (B2) can stop the
microphone, and the status output says so on every run.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "http://127.0.0.1:4411"
DEFAULT_TOKEN_FILE = "~/.esp32-voice/control.token"
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


class CliError(Exception):
    """A failed call; the top-level handler maps it to exit code 1."""


def read_token(path: str) -> str:
    env = os.environ.get("ESP32_CONTROL_TOKEN", "").strip()
    if env:
        return env
    token_file = Path(path).expanduser()
    try:
        token = token_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CliError(f"读不到 control token（{token_file}）：{exc}；"
                       "先用 --token-file 指定，或启动一次服务端生成它")
    if not token:
        raise CliError(f"control token 文件是空的：{token_file}")
    return token


def call(base_url: str, token: str, payload: dict | None = None) -> dict:
    url = base_url.rstrip("/") + "/debug/mute"
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data,
                                     method="GET" if data is None else "POST")
    request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read()[:300].decode("utf-8", "replace")
        raise CliError(f"{url} -> HTTP {exc.code}: {body}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CliError(f"{url} 连不上：{type(exc).__name__}: {exc}")
    except json.JSONDecodeError:
        raise CliError(f"{url} 返回的不是 JSON")


def render(status: dict) -> str:
    """Human-readable status. Mode A wording is an acceptance requirement."""
    muted = bool(status.get("muted"))
    lines = [f"静音开关：{'开（服务端丢帧）' if muted else '关（正常对话）'}"]
    if muted:
        lines.append(f"静音开始：{status.get('since') or '未知'}")
        lines.append(f"最近切换：{status.get('updated_at') or '未知'} "
                     f"by {status.get('changed_by') or '未知'}")
    mode = status.get("mode", "A")
    lines.append(f"模式：{mode}（mode {mode}；服务端丢帧；设备仍在采集/上传，"
                 f"B2 后才是设备停采）")
    counters = status.get("counters") or {}
    lines.append(
        "帧计数：frames_in={} dropped={} accepted={} turns={}".format(
            counters.get("frames_in", 0), counters.get("frames_dropped", 0),
            counters.get("frames_accepted", 0), counters.get("turns", 0)))
    lines.append(f"最近一帧：{status.get('last_frame_at') or '无'}")
    catchup = status.get("catchup") or {}
    lines.append(f"静音期积压：pending={catchup.get('pending', 0)} "
                 f"missed={catchup.get('missed', 0)} "
                 f"spoken={catchup.get('spoken', 0)}")
    lines.append(f"持久化：{status.get('persisted_path') or '未知'}")
    return "\n".join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Server-side mute switch (B1 mode A): on | off | status")
    parser.add_argument("command", choices=("on", "off", "status"),
                        help="on = drop all uplink audio; off = resume; status = show")
    parser.add_argument("--json", action="store_true",
                        help="print the raw JSON response instead of human text")
    parser.add_argument("--base-url", default=DEFAULT_BASE,
                        help=f"4411 control plane URL (default {DEFAULT_BASE})")
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE,
                        help=f"control token file (default {DEFAULT_TOKEN_FILE}); "
                             "ESP32_CONTROL_TOKEN wins when set")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        token = read_token(args.token_file)
        payload = None
        if args.command in ("on", "off"):
            payload = {"muted": args.command == "on"}
        status = call(args.base_url, token, payload)
    except CliError as exc:
        print(f"[mute] ERROR {exc}", file=sys.stderr)
        return EXIT_FAIL

    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        if args.command == "on":
            print("已切换：静音" if status.get("changed") else "已经是静音状态")
        elif args.command == "off":
            print("已切换：解除静音" if status.get("changed") else "已经是正常状态")
            if status.get("catchup_started"):
                print("补说：后台进行中（GET /debug/mute 可查进度与结果）")
            else:
                catchup = (status.get("catchup") or {}).get("last_result") or {}
                if catchup.get("spoken"):
                    print(f"补说：{catchup.get('text', '')}")
                elif catchup.get("missed"):
                    print(f"错过未补：{catchup.get('missed')} 条（超出补说窗口）")
        print(render(status))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
