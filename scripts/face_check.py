#!/usr/bin/env python3
"""One command for the M7 Step 1 face acceptance on real hardware.

Usage
-----
    .venv313/bin/python scripts/face_check.py
    .venv313/bin/python scripts/face_check.py --base http://127.0.0.1:4411 \\
        --lan-base http://<mac-lan-ip>:4411 --token-file ~/.esp32-voice/control.token
    .venv313/bin/python scripts/face_check.py --blink

Wake the board first ("你好小智"): the board closes its websocket when it goes
idle, so all of this has to happen inside one session window. If the probe finds
no live session the script prints the wake-word hint and exits 2.

`--blink` is a side mode for the last acceptance item ("会眨眼"): it keeps the
same probe, then takes 8 snapshots in ~3 s (`blink-01..08.jpg`) and prints a
heuristic verdict. The default run (expressions + preview + report) is
unchanged when `--blink` is absent.

The script is a pure HTTP client for the voice server. It uses exactly three
calls -- `/debug/emotion`, `self.screen.snapshot`, `self.screen.preview_image`
-- and never touches a destructive tool or the server process. Evidence lands
in `docs/face/`:

    step1-neutral.jpg  step1-happy.jpg  step1-thinking.jpg  step1-confused.jpg
    step1-after-preview.jpg
    step1-report.md
    blink-01.jpg ... blink-08.jpg  blink-report.md

Why the preview step uses a generated PNG
-----------------------------------------
`self.screen.snapshot` always uploads JPEG (firmware `SnapshotToJpeg`), but the
image only builds the LVGL PNG decoder (`CONFIG_LV_USE_LODEPNG=y`, no TJPGD).
Previewing a captured JPEG therefore fails with "Downloaded image is invalid"
and never arms the 5 s preview timer -- the exact path that used to un-hide the
stock emoji and that this step is meant to regression-check. Step 3 writes a
small checkerboard PNG into the server's `/screen` cache dir (the only
anonymous file route the board can fetch; `/debug/photo` needs a Bearer header
its downloader cannot send) and previews that. That is a cache file next to the
matrix frames, not config or state. The snapshots and the after-preview shot
are real board output.

Exit codes: 0 = evidence captured, 2 = no live session (wake the board),
1 = any HTTP or device-tool failure.
"""
import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "face"

DEFAULT_BASE = "http://127.0.0.1:4411"
# The address the *board* uses to reach this server (photo upload + preview URL).
DEFAULT_LAN_BASE = "http://<mac-lan-ip>:4411"
DEFAULT_TOKEN_FILE = "~/.esp32-voice/control.token"
DEFAULT_PHOTO_DIR = "~/.hermes/cache/scratch/esp32-voice/photos"
DEFAULT_SCREEN_DIR = "~/.hermes/cache/scratch/esp32-voice/screen"
PREVIEW_PNG = "face-check-preview.png"

EMOTIONS = ("neutral", "happy", "thinking", "confused")
NO_SESSION_HINT = "板子没有活会话：请先说『你好小智』，30 s 内重跑"

# --blink: the face blinks every 3000 ms for about 150 ms (animation_speed=30,
# blink_phase += 20 per tick), so sample often enough to land in that window.
BLINK_SHOTS = 8
BLINK_INTERVAL = 0.375          # start-to-start seconds; 8 shots span ~2.6 s
BLINK_VERDICT_HIT = "疑似捕捉到眨眼（需人工看图确认）"
BLINK_VERDICT_MISS = "3 秒内未捕捉到眨眼，建议重跑或把 blink_interval 调短"
BLINK_SIZE_GAP = 0.015          # >1.5% file-size gap between two shots


class CheckError(RuntimeError):
    """A failed step; `exit_code` lets the no-session case exit 2."""

    def __init__(self, message, exit_code=1):
        super().__init__(message)
        self.exit_code = exit_code


def log(message):
    print(message, flush=True)


def _token(args) -> str:
    env = os.environ.get("ESP32_CONTROL_TOKEN", "").strip()
    if env:
        return env
    path = Path(args.token_file).expanduser()
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CheckError(f"读不到 control token（{path}）：{exc}；"
                         "先用 --token-file 指定，或启动一次服务端生成它")
    if not token:
        raise CheckError(f"control token 文件是空的：{path}")
    return token


def _request(url, token=None, payload=None, timeout=30.0):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()[:200].decode("utf-8", "replace")
        raise CheckError(f"{url} -> HTTP {exc.code}: {body}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CheckError(f"{url} 连不上：{type(exc).__name__}: {exc}")


def post_json(base, token, path, payload, timeout=30.0) -> dict:
    _, body = _request(base + path, token, payload, timeout)
    try:
        return json.loads(body)
    except ValueError:
        raise CheckError(f"{path} 返回的不是 JSON：{body[:200]!r}")


def get_bytes(base, token, path, timeout=30.0) -> bytes:
    _, body = _request(base + path, token, None, timeout)
    return body


def call_tool(base, token, name, arguments, timeout=30.0):
    """POST /debug/tool; returns (sent, result_text)."""
    resp = post_json(base, token, "/debug/tool",
                     {"name": name, "arguments": arguments}, timeout)
    sent = int(resp.get("sent") or 0)
    results = resp.get("results") or []
    result = str(results[0].get("result", "")) if results else ""
    if sent == 0:
        raise CheckError("会话中途消失：板子可能又睡了，请重新说『你好小智』后重跑")
    return sent, result


def _new_snapshot(photo_dir: Path, since: float, wait: float = 4.0):
    """Newest snapshot-*.jpg written after `since`, waiting briefly for upload."""
    deadline = time.time() + wait
    while True:
        fresh = [p for p in photo_dir.glob("snapshot-*.jpg")
                 if p.stat().st_mtime >= since]
        if fresh:
            return max(fresh, key=lambda p: p.stat().st_mtime)
        if time.time() >= deadline:
            return None
        time.sleep(0.15)


def take_snapshot(base, token, lan_base, photo_dir: Path, dest: Path,
                  timeout=30.0) -> int:
    """Ask the board for a screenshot, fetch it over HTTP, save to `dest`."""
    since = time.time()
    _, result = call_tool(
        base, token, "self.screen.snapshot",
        {"url": lan_base + "/debug/upload", "quality": 90}, timeout)
    uploaded = _new_snapshot(photo_dir, since)
    if uploaded is None:
        raise CheckError(
            f"设备没上传成功：{photo_dir} 里没有新的 snapshot-*.jpg"
            f"（tool 结果 {result[:200]!r}）；检查板子能否访问 "
            f"{lan_base}/debug/upload")
    data = get_bytes(base, token, "/debug/photo/" + urllib.parse.quote(uploaded.name))
    if not data.startswith(b"\xff\xd8\xff"):
        raise CheckError(
            f"上传的文件不是 JPEG（{uploaded.name}, {len(data)} bytes）"
            f"：前 8 字节 {data[:8]!r}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)


def _ppng_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_preview_png(path: Path) -> None:
    """Write a 480x320 checkerboard PNG (pure stdlib) for the preview trigger."""
    width, height, cell = 480, 320, 32
    rows = []
    for y in range(height):
        row = bytearray([0])                       # PNG filter: None
        for x in range(width):
            if x < 8 or y < 8 or x >= width - 8 or y >= height - 8:
                row += b"\xff\x00\x00"             # red border
            else:
                shade = 200 if ((x // cell) + (y // cell)) % 2 == 0 else 60
                row += bytes((shade, shade, shade))
        rows.append(bytes(row))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n"
           + _ppng_chunk(b"IHDR", ihdr)
           + _ppng_chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
           + _ppng_chunk(b"IEND", b""))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
    except OSError as exc:
        raise CheckError(
            f"写不了 {path}：{exc}；/screen 路由直接从该目录取文件，"
            "用 --screen-dir 指向服务端的 screen 缓存目录")


def _server_pid(base: str, override) -> str:
    """PID listening on the server port, for the report (best effort)."""
    if override:
        return str(override)
    try:
        port = urllib.parse.urlsplit(base).port or 80
        out = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5)
        pids = [p for p in out.stdout.split() if p.strip()]
        return ",".join(pids) if pids else "unknown"
    except Exception:                      # lsof missing / no permission
        return "unknown"


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def write_report(path: Path, meta: dict) -> None:
    images = "\n".join(
        f"| `{row['file']}` | {row['bytes']} | {row['emotion']} | {row['sent']} |"
        for row in meta["images"])
    text = f"""# M7 Step 1 真机验收证据（face_check.py）

- 时间：{meta['time']}
- 脚本 PID：{meta['script_pid']}；服务端 PID：{meta['server_pid']}
- 服务端：{meta['base']}；板子侧地址：{meta['lan_base']}
- token 来源：{meta['token_file']}
- 探活 `sent`：{meta['probe_sent']}

## 截图

| 文件 | 字节 | 推送 emotion | sent |
| --- | --- | --- | --- |
{images}

## 预览回显一击

- `preview_image` URL：{meta['preview_url']}
- 设备回执：{meta['preview_result']}
- 停止预览 6 s 后：`{meta['after_file']}`（{meta['after_bytes']} bytes）
- 为什么预览的是生成的 PNG：设备快照只出 JPEG，而固件只编译了 PNG 解码器
  （`CONFIG_LV_USE_LODEPNG=y`，无 TJPGD）；预览 JPEG 会报 invalid，5 s 定时器
  不会启动，也就测不到 emoji 回显。

## 请人工确认

请人工确认：四张表情各不相同；after-preview 的脸中央仍是 kawaii 脸而不是小智 emoji。

## 备注

- 设备完全 Idle 时 WS 会话不存在，`/debug/emotion` 和 `/debug/tool` 都到不了板子；
  本报告只有在会话窗口内跑完才有效。
- 只调用了 `/debug/emotion`、`self.screen.snapshot`、`self.screen.preview_image`，
  没有调用任何破坏性工具。
"""
    path.write_text(text, encoding="utf-8")


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def blink_stats(shots):
    """Heuristic 'did the eyes move?' without decoding the JPEG.

    Pillow is not installed in .venv313 (`import PIL` -> ModuleNotFoundError),
    so a real eye-region pixel ratio is not available. Two different MD5s mean
    the panel changed between shots; the >1.5% file-size gap filters out tiny
    status-bar/antialiasing jitter, because a blink repaints both eye canvases.
    Still needs human eyes: the verdict says 'suspected', never 'confirmed'.
    """
    digests = [_md5(shot["path"]) for shot in shots]
    sizes = [shot["bytes"] for shot in shots]
    size_gap = (max(sizes) - min(sizes)) / max(min(sizes), 1)
    caught = len(set(digests)) >= 2 and size_gap > BLINK_SIZE_GAP
    return {"digests": digests, "distinct": len(set(digests)),
            "size_gap": size_gap, "caught": caught}


def write_blink_report(path: Path, meta: dict) -> None:
    rows = "\n".join(
        f"| `{shot['file']}` | {shot['bytes']} | `{digest[:8]}` | {shot['at_ms']} |"
        for shot, digest in zip(meta["shots"], meta["digests"]))
    text = f"""# M7 Step 1 眨眼取证（face_check.py --blink）

- 时间：{meta['time']}
- 脚本 PID：{meta['script_pid']}；服务端 PID：{meta['server_pid']}
- 服务端：{meta['base']}；板子侧地址：{meta['lan_base']}
- 探活 `sent`：{meta['probe_sent']}
- 采样：{meta['shots_count']} 张，总跨度 {meta['span_ms']} ms
  （目标 {int(BLINK_INTERVAL * 1000)} ms/张）
- 判据：Pillow 不可用（`.venv313` 没有 PIL），退回 MD5 + 文件大小
  （≥2 组不同 MD5 且最大体积差 >1.5%）。只能说明画面变了，不能证明是眨眼。

## 连拍

| 文件 | 字节 | MD5 前 8 | 距首张 (ms) |
| --- | --- | --- | --- |
{rows}

## 自动判定

- 不同 MD5 组数：{meta['distinct']}
- 最大体积差：{meta['size_gap'] * 100:.2f}%
- 结论：{meta['verdict']}

## 请人工确认

请人工确认：8 张里有没有眼睛闭合或半闭的帧（一次眨眼约 150 ms，命中率本就不高）。
没抓到就重跑，或把固件的 `blink_interval` 调短后重新构建。

## 备注

- 眨眼来自组件 `auto_blink=true` / `blink_interval=3000`，动画每 30 ms 一步，
  约 150 ms 走完一闭一睁；采样间隔 {int(BLINK_INTERVAL * 1000)} ms 决定了命中率。
- 状态栏、字幕等其它画面变化也可能触发「疑似」，所以结论必须人工看图。
"""
    path.write_text(text, encoding="utf-8")


def run_blink(args, token, base, lan_base, photo_dir, out_dir, probe_sent) -> int:
    """--blink mode: 8 snapshots in ~3 s, then a heuristic blink verdict."""
    log(f"[2/3] 连拍 {BLINK_SHOTS} 张：目标间隔 {int(BLINK_INTERVAL * 1000)} ms"
        f"（约 3 s，眨眼只有 ~150 ms）")
    # The probe pushed `neutral`; the component needs ~300 ms (10 x 30 ms ticks)
    # to finish that transition. Sampling during it would fake a "changed" frame.
    log("      等 0.5 s 让探活的 neutral 过渡结束")
    time.sleep(0.5)
    shots = []
    started_all = time.monotonic()
    for index in range(1, BLINK_SHOTS + 1):
        dest = out_dir / f"blink-{index:02d}.jpg"
        started = time.monotonic()
        nbytes = take_snapshot(base, token, lan_base, photo_dir, dest)
        shots.append({"n": index, "path": dest, "file": _rel(dest),
                      "bytes": nbytes,
                      "at_ms": round((started - started_all) * 1000)})
        wait = BLINK_INTERVAL - (time.monotonic() - started)
        if index < BLINK_SHOTS and wait > 0:
            time.sleep(wait)
    span_ms = round((time.monotonic() - started_all) * 1000)
    log(f"      {BLINK_SHOTS} 张完成，总跨度 {span_ms} ms")
    if span_ms > 3000:
        log("      注意：快照往返较慢，跨度已超过 3 s（采样窗口被拉长）")

    log("[3/3] 判定（Pillow 不可用：MD5 + 文件大小）")
    stats = blink_stats(shots)
    for shot, digest in zip(shots, stats["digests"]):
        log(f"      {shot['file']}: {shot['bytes']} bytes "
            f"md5={digest[:8]} t={shot['at_ms']} ms")
    log(f"      不同 MD5：{stats['distinct']} 组；最大体积差："
        f"{stats['size_gap'] * 100:.2f}%")
    verdict = BLINK_VERDICT_HIT if stats["caught"] else BLINK_VERDICT_MISS
    log(verdict)

    report_path = out_dir / "blink-report.md"
    write_blink_report(report_path, {
        "time": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "script_pid": os.getpid(),
        "server_pid": _server_pid(base, args.server_pid),
        "base": base,
        "lan_base": lan_base,
        "probe_sent": probe_sent,
        "shots_count": BLINK_SHOTS,
        "span_ms": span_ms,
        "shots": shots,
        "digests": stats["digests"],
        "distinct": stats["distinct"],
        "size_gap": stats["size_gap"],
        "verdict": verdict,
    })
    log(f"      报告：{_rel(report_path)}")
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="M7 Step 1 face acceptance: push expressions, snapshot, "
                    "check the emoji does not come back after a preview.")
    parser.add_argument("--base", default=DEFAULT_BASE,
                        help=f"voice server URL from this Mac (default {DEFAULT_BASE})")
    parser.add_argument("--lan-base", default=DEFAULT_LAN_BASE,
                        help="server URL as the *board* sees it, used for the photo "
                             f"upload and preview_image (default {DEFAULT_LAN_BASE})")
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE,
                        help=f"control token file (default {DEFAULT_TOKEN_FILE}); "
                             "ESP32_CONTROL_TOKEN wins when set")
    parser.add_argument("--photo-dir", default=DEFAULT_PHOTO_DIR,
                        help="server-side /debug/upload sink (default "
                             f"{DEFAULT_PHOTO_DIR})")
    parser.add_argument("--screen-dir", default=DEFAULT_SCREEN_DIR,
                        help="server-side /screen cache dir, writable by this "
                             f"script (default {DEFAULT_SCREEN_DIR})")
    parser.add_argument("--server-pid", type=int, default=None,
                        help="fill the report's server PID instead of detecting it")
    parser.add_argument("--out-dir", default=str(OUT_DIR),
                        help=f"evidence directory (default {_rel(OUT_DIR)})")
    parser.add_argument("--turn", metavar="TEXT", default=None,
                        help="drive a real text turn through POST /debug/turn and "
                             "capture snapshots while it answers - this is the only "
                             "automatic way to see the speaking face and subtitles")
    parser.add_argument("--turn-seconds", type=float, default=14.0,
                        help="how long to keep sampling after --turn (default 14 s)")
    parser.add_argument("--soak", metavar="MINUTES", type=float, default=None,
                        help="keepalive soak: sample ESTABLISHED + /debug/emotion "
                             "once a minute for N minutes and write a report "
                             "(no wake-up needed once the board is connected)")
    parser.add_argument("--blink", action="store_true",
                        help="blink check only: 8 snapshots in ~3 s, then a "
                             "heuristic verdict (skips expressions/preview)")
    return parser.parse_args(argv)




def run_turn(args, token, base, lan_base, photo_dir, out_dir) -> int:
    """Drive a real answer and capture what the screen does while it speaks.

    The speaking face and the subtitle bar only exist during a live answer, and the
    board only answers when someone talks to it. POST /debug/turn lets the server
    produce that answer from text, so the one wake-up we get does not also have to
    include a spoken sentence.
    """
    text = args.turn.strip()
    if not text:
        raise CheckError("--turn 需要非空文本")
    total = max(3.0, float(args.turn_seconds))
    pushed = post_json(base, token, "/debug/turn", {"text": text}, timeout=15)
    sent = int(pushed.get("sent") or 0)
    if sent == 0:
        log(NO_SESSION_HINT)
        return 2
    log(f"text turn {text!r} -> {sent} session(s); sampling {total:g}s")

    out_dir.mkdir(parents=True, exist_ok=True)
    samples, start, index = [], time.time(), 0
    while time.time() - start < total:
        index += 1
        dest = out_dir / f"turn-{index:02d}.jpg"
        try:
            nbytes = take_snapshot(base, token, lan_base, photo_dir, dest)
            samples.append({"file": _rel(dest), "bytes": nbytes,
                            "at": round(time.time() - start, 2)})
            log(f"      t+{samples[-1]['at']:5.2f}s -> {_rel(dest)} ({nbytes} bytes)")
        except Exception as exc:
            log(f"      t+{time.time() - start:5.2f}s snapshot failed: {type(exc).__name__}")
        time.sleep(max(0.2, min(1.0, total - (time.time() - start))))

    report = out_dir / f"turn-report-{time.strftime('%H%M%S')}.md"
    lines = [f"# Text turn: {text}", "",
             "看什么：回答期间截图里应出现 (1) 说话脸 (2) 底部字幕条逐字增长；"
             "回答结束后脸回到静息、字幕 2 s 后淡出。", "",
             "| t+ (s) | 截图 | 字节 |", "|---|---|---|"]
    for s_ in samples:
        lines.append(f"| {s_['at']} | {s_['file']} | {s_['bytes']} |")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"报告：{_rel(report)}（共 {len(samples)} 张）")
    return 0


def _established(url_host="127.0.0.1", port=4410) -> int:
    """Count ESTABLISHED sockets on the voice port (macOS/Linux via lsof)."""
    import subprocess
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}"],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return -1
    return sum(1 for line in out.splitlines() if "ESTABLISHED" in line)


def run_soak(args, token: str, base: str, out_dir: Path) -> int:
    """Sample keepalive + push reachability every minute; write a report.

    This answers the one question the expression push could not: does the socket
    survive idle time?  It needs no wake-up word - once the board is connected,
    every sample is passive except a harmless neutral emotion push.
    """
    minutes = float(args.soak)
    if minutes <= 0:
        raise CheckError("--soak 需要正数分钟")
    total = int(round(minutes * 60))
    step = 60
    samples = []
    log(f"soak: {minutes:g} 分钟，每分钟采样一次（ESTABLISHED + /debug/emotion）")
    start = time.time()
    while True:
        stamp = time.strftime("%H:%M:%S")
        est = _established()
        try:
            push = post_json(base, token, "/debug/emotion",
                             {"emotion": "neutral"}, timeout=10)
            sent = int(push.get("sent") or 0)
            err = ""
        except Exception as exc:              # keep soaking through transient errors
            sent, err = -1, type(exc).__name__
        samples.append({"at": stamp, "established": est, "sent": sent, "error": err})
        log(f"      {stamp} established={est} sent={sent}{(' err=' + err) if err else ''}")
        left = total - (time.time() - start)
        if left <= 0:
            break
        time.sleep(min(step, max(1.0, left)))   # never overshoot a short window

    connected = [s for s in samples if s["established"] > 0]
    reachable = [s for s in samples if s["sent"] == 1]
    verdict = ("PASS：静置期间 socket 一直在，且推送可达"
               if len(connected) == len(samples) and len(reachable) >= len(samples) - 1
               else "FAIL：见下表（中间断开或推送不可达）")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / f"soak-{time.strftime('%Y%m%d-%H%M%S')}.md"
    lines = [f"# Keepalive soak {time.strftime('%Y-%m-%d %H:%M')}",
             "",
             f"- 采样 {len(samples)} 次（每 60 s），窗口 {minutes:g} 分钟",
             f"- ESTABLISHED 出现 {len(connected)}/{len(samples)} 次",
             f"- 推送 sent=1 出现 {len(reachable)}/{len(samples)} 次",
             f"- 结论：**{verdict}**",
             "",
             "| 时刻 | ESTABLISHED | /debug/emotion sent | 错误 |",
             "|---|---|---|---|"]
    for s_ in samples:
        lines.append(f"| {s_['at']} | {s_['established']} | {s_['sent']} | {s_['error']} |")
    lines += ["", "判读提示：只要有一行 established=0 而下一行恢复，说明中间断过——"
                  "对照固件日志 `M7KEEPALIVE` 的 closed-by-peer / close-channel reason 定位。"]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"报告：{_rel(report)}")
    return 0 if verdict.startswith("PASS") else 1


def main(argv=None) -> int:
    args = parse_args(argv)
    base = args.base.rstrip("/")
    lan_base = args.lan_base.rstrip("/")
    out_dir = Path(args.out_dir)
    photo_dir = Path(args.photo_dir).expanduser()

    try:
        token = _token(args)

        if args.turn is not None:
            return run_turn(args, token, base, lan_base, photo_dir, out_dir)

        if args.soak is not None:
            return run_soak(args, token, base, out_dir)

        log(f"[1/{3 if args.blink else 5}] 探活：POST {base}/debug/emotion neutral")
        probe = post_json(base, token, "/debug/emotion", {"emotion": "neutral"},
                          timeout=10)
        probe_sent = int(probe.get("sent") or 0)
        if probe_sent == 0:
            log(NO_SESSION_HINT)
            return 2
        log(f"      活会话 {probe_sent} 个")

        if args.blink:
            return run_blink(args, token, base, lan_base, photo_dir, out_dir,
                             probe_sent)

        log("[2/5] 推表情并截图：neutral / happy / thinking / confused")
        images = []
        for emotion in EMOTIONS:
            pushed = post_json(base, token, "/debug/emotion",
                               {"emotion": emotion}, timeout=10)
            sent = int(pushed.get("sent") or 0)
            if sent == 0:
                raise CheckError("会话中途消失：请重新唤醒板子后重跑")
            time.sleep(0.8)               # let the face animation settle
            dest = out_dir / f"step1-{emotion}.jpg"
            nbytes = take_snapshot(base, token, lan_base, photo_dir, dest)
            images.append({"emotion": emotion, "file": _rel(dest),
                           "bytes": nbytes, "sent": sent})
            log(f"      {emotion}: sent={sent} -> {_rel(dest)} ({nbytes} bytes)")

        log("[3/5] preview_image 回显一击")
        preview_png = Path(args.screen_dir).expanduser() / PREVIEW_PNG
        write_preview_png(preview_png)
        preview_url = f"{lan_base}/screen/{preview_png.name}"
        _, preview_result = call_tool(
            base, token, "self.screen.preview_image", {"url": preview_url})
        if preview_result.strip().lower() != "true":
            hint = ""
            if "invalid" in preview_result.lower():
                hint = "（设备解码失败：确认目标是 PNG）"
            elif "open url" in preview_result.lower():
                hint = f"（板子访问不到 {preview_url}：检查 --lan-base / 防火墙）"
            raise CheckError(f"preview_image 失败：{preview_result[:200]}{hint}")
        log(f"      preview on: {preview_url}；等 6 s 让 5 s 预览定时器走完")
        time.sleep(6.0)
        after = out_dir / "step1-after-preview.jpg"
        after_bytes = take_snapshot(base, token, lan_base, photo_dir, after)
        log(f"      after preview -> {_rel(after)} ({after_bytes} bytes)")

        log("[4/5] 证据汇总")
        for row in images:
            log(f"      {row['file']}: {row['bytes']} bytes (sent={row['sent']})")
        log(f"      {_rel(after)}: {after_bytes} bytes")

        log("[5/5] 写报告")
        started = datetime.now().astimezone()
        report = {
            "time": started.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "script_pid": os.getpid(),
            "server_pid": _server_pid(base, args.server_pid),
            "base": base,
            "lan_base": lan_base,
            "token_file": args.token_file,
            "probe_sent": probe_sent,
            "images": images,
            "preview_url": preview_url,
            "preview_result": preview_result,
            "after_file": _rel(after),
            "after_bytes": after_bytes,
        }
        report_path = out_dir / "step1-report.md"
        write_report(report_path, report)
        log(f"      报告：{_rel(report_path)}")
        log("DONE：截图 + 报告已就绪，请按报告里的「请人工确认」逐条看图。")
        return 0
    except CheckError as exc:
        print(f"FAIL: {exc}", file=sys.stderr, flush=True)
        return exc.exit_code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr, flush=True)
        return 130


if __name__ == "__main__":
    sys.exit(main())
