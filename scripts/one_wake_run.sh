#!/usr/bin/env bash
# One-wake acceptance run for the M7 persona layer.
#
# The board only opens a session when it hears the wake word (or someone touches
# the screen), so every device check has to fit into a single window where 9哥 is
# present. This script runs them in order, keeps the raw output in one log, and
# stops early with a clear instruction if nobody has woken the board yet.
#
#   ./scripts/one_wake_run.sh            # full run, 15 minute soak
#   ./scripts/one_wake_run.sh --soak 3   # shorter soak for a quick pass
#
# Exit codes: 0 all green, 2 board not woken (nothing was tested), 3 a check failed.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
PY=".venv313/bin/python"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="docs/face/one-wake-$STAMP"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/run.log"
SOAK_MIN="${2:-15}"
# Something with a bit of length and common characters: long enough to show
# several subtitle updates, short enough to finish inside the sampling window.
TURN_TEXT="${TURN_TEXT:-今天天气怎么样？请用两三句话说一下。}"
if [ "${1:-}" = "--soak" ]; then shift 2 || true; fi

say() { printf '%s\n' "$*" | tee -a "$LOG"; }
run() { say "\$ $*"; "$@" 2>&1 | tee -a "$LOG"; return "${PIPESTATUS[0]}"; }

say "=== one-wake acceptance run $STAMP ==="
say "log: $LOG"

# 1) Is the board listening?  /debug/emotion answers sent:0 when there is no
#    session, which is the cheapest way to tell before running anything else.
say ""
say "--- [1/4] probe: is a session live? ---"
probe="$("$PY" - "$LOG" <<'PY'
import json, sys, urllib.request
from pathlib import Path
tok = Path.home() / ".esp32-voice" / "control.token"
token = tok.read_text().strip() if tok.exists() else ""
req = urllib.request.Request(
    "http://127.0.0.1:4411/debug/emotion",
    data=json.dumps({"emotion": "neutral"}).encode(),
    headers={"Content-Type": "application/json",
             "Authorization": f"Bearer {token}"},
    method="POST")
try:
    with urllib.request.urlopen(req, timeout=8) as r:
        print(json.loads(r.read()).get("sent", -1))
except Exception as exc:
    print(f"error:{type(exc).__name__}")
PY
)"
say "sent=$probe"
if [ "$probe" != "1" ]; then
  say ""
  say "!! 板子当前没有活会话（sent=${probe}）。"
  say "!! 按一下板子上的 BOOT 键（或说「你好小智」），然后再跑一次本脚本。"
  say "!! 唤醒方式：BOOT 键单击 = ToggleChatState()（固件 chd_esp32s3_box_board.cc:841-852）；触摸面板是否可用未确认。"
  say "!! 没有会话时：表情推不到、截图与 soak 都无意义——所以这里直接停，不浪费你的时间。"
  exit 2
fi

# 2) Faces, preview-vs-emoji regression, blink, subtitles (subtitles show up in
#    the snapshots because they are just another LVGL object on the same screen).
say ""
say "--- [2a/4] 四种表情 + preview 回显不盖脸 (face_check.py) ---"
run "$PY" scripts/face_check.py --out-dir "$LOG_DIR" \
  || { say "!! face_check（表情/预览）失败，见上面的原始输出"; exit 3; }

say ""
say "--- [2b/4] 眨眼连拍 (face_check.py --blink) ---"
# --blink is its own flow and does NOT push the four expressions, so it runs as a
# separate pass; chaining it here is what made an earlier run report "blink only".
run "$PY" scripts/face_check.py --blink --out-dir "$LOG_DIR" || say "!! 眨眼连拍失败"

# 2b) Drive a real text turn and sample the screen while it answers.  This is the
#     only way to see the speaking face and the subtitles without 9哥 having to
#     compose a sentence: the server produces the answer from text.
say ""
say "--- [2c/4] 真实回答期间的屏幕取样（说话脸 + 字幕）---"
run "$PY" scripts/face_check.py --turn "${TURN_TEXT}" --turn-seconds 14 \
  --out-dir "$LOG_DIR" || say "!! text turn 取样失败（见上面输出）"

# 3) Keepalive soak.  This is the only way to prove the socket survives idling,
#    which is what makes server-side pushes possible at all.
say ""
say "--- [3/4] keepalive soak ${SOAK_MIN} min (leave the board alone) ---"
run "$PY" scripts/face_check.py --soak "$SOAK_MIN" --out-dir "$LOG_DIR" \
  || say "!! soak 判 FAIL —— 对照固件日志 M7KEEPALIVE 的 closed-by-peer / close-channel"

# 4) Proactive counters: how many times it considered speaking, and what stopped
#    it.  dry_run is on by default, so nothing here should have made a sound.
say ""
say "--- [4/4] proactive status ---"
token="$(cat "$HOME/.esp32-voice/control.token" 2>/dev/null || true)"
status_json="$(curl -s -m 8 -H "Authorization: Bearer $token" \
     "http://127.0.0.1:4411/debug/proactive/status")"
say "$status_json" | tee -a "$LOG"
say ""
say "$status_json" | "$PY" -c 'import json,sys
d = json.load(sys.stdin)
for key in ("enabled", "dry_run", "socket_alive", "today", "hourly", "recent"):
    print(key, "=", json.dumps(d.get(key), ensure_ascii=False))' 2>&1 | tee -a "$LOG"
say ""
say "=== done. 原始输出：$LOG"
say "=== 截图与 soak 报告：$LOG_DIR"
say "=== 需要人看一眼的：step1-*.jpg（表情与字幕观感）、soak-*.md 的结论行"
