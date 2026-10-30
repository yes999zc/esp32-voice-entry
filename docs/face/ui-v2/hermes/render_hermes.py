#!/usr/bin/env python3
"""Render Hermes avatar + top-bar mockups (480x320).

Avatar source (official, used 1:1, never resized):
  <workspace>/04_Docs/human-bridge/assets/hermes-icon/
    hermes-face-64x72-a8.bin  (4608 B, 64x72, raw A8 alpha, row-major)
    hermes-face-56x64-a8.bin  (3584 B, 56x64, official export for the size comparison)

Recolor rule: RGB = #1F2B2D constant, A = raw byte. No outline, no box, no shadow,
no white background. Offline state: whole glyph alpha x0.4.

Placeholder UI fonts: Hiragino Sans GB W3 / SF Mono (final: MiSans + JetBrains Mono).
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 480, 320
PAPER = (0xF4, 0xF3, 0xEA)
INK = (0x20, 0x2B, 0x2D)
INK_GLYPH = (0x1F, 0x2B, 0x2D)
ACCENT = (0xE2, 0x70, 0x3A)
MUTED = (0x6B, 0x73, 0x72)
RULE = (0xD8, 0xD5, 0xC6)

ASSETS = Path("<workspace>/04_Docs/human-bridge/assets/hermes-icon")
OUT = Path(__file__).resolve().parent

CJK = "/System/Library/Fonts/Hiragino Sans GB.ttc"
MONO = "/System/Library/Fonts/SFNSMono.ttf"
_f = {}
def cjk(s):
    if ("c", s) not in _f: _f[("c", s)] = ImageFont.truetype(CJK, s, index=0)
    return _f[("c", s)]
def mono(s):
    if ("m", s) not in _f: _f[("m", s)] = ImageFont.truetype(MONO, s)
    return _f[("m", s)]
def t(d, xy, s, font, fill=INK, anchor="la"):
    d.text(xy, s, font=font, fill=fill, anchor=anchor)

def load_avatar(w, h, opacity=1.0):
    a = np.fromfile(ASSETS / f"hermes-face-{w}x{h}-a8.bin", dtype=np.uint8).reshape(h, w)
    if opacity != 1.0:
        a = (a.astype(np.float32) * opacity).round().astype(np.uint8)
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = INK_GLYPH
    rgba[..., 3] = a
    return Image.fromarray(rgba, "RGBA")

def paste_avatar(im, w, h, x, y, opacity=1.0):
    im.alpha_composite(load_avatar(w, h, opacity), (x, y))

def wifi(d, x, y):
    for r in (14, 9, 4):
        d.arc([x - r, y - r, x + r, y + r], start=225, end=315, fill=INK, width=2)
    d.rectangle([x - 1, y - 1, x + 1, y + 1], fill=INK)

def top_bar(d, state):
    d.line([0, 39, W, 39], fill=INK, width=1)
    if state == "offline":
        d.rectangle([16, 15, 23, 22], outline=INK, width=2)          # hollow dot
    else:
        d.rectangle([16, 15, 23, 22], fill=ACCENT)                   # link ok (only orange)
    t(d, (30, 20), "Hermes", cjk(14), anchor="lm")
    t(d, (30 + cjk(14).getlength("Hermes") + 6, 20), "在线" if state != "offline" else "断开",
      cjk(14), fill=MUTED, anchor="lm")

LOG_ONLINE = [
    ("18:58:55", "asr",   '"你好小智"',        False),
    ("18:58:56", "llm",   "hermes 1.2s",       False),
    ("18:58:57", "tts",   "first frame 420ms", False),
    ("18:58:58", "mute",  "off",               False),
    ("18:58:59", "wifi",  "-50dBm",            False),
    ("18:59:00", "sram",  "33KB",              False),
    ("18:59:01", "frames", "1024",             False),
]
LOG_OFFLINE = [
    ("18:58:55", "ws",    "link down",         False),   # ink: orange is reserved for the online dot
    ("18:58:56", "retry", "1/3 in 2s",         False),
    ("18:58:57", "wifi",  "-50dBm",            False),
    ("18:58:58", "sram",  "33KB",              False),
    ("18:58:59", "frames", "1024",             False),
    ("18:59:00", "ws",    "reconnecting",      False),
    ("18:59:01", "note",  "local only",        False),
]
LOG_SPEAKING = [
    ("18:58:55", "asr",   '"今天天气怎么样"',  False),
    ("18:58:56", "llm",   "hermes 1.6s",       False),
    ("18:58:57", "tts",   "first frame 380ms", False),
    ("18:58:58", "tts",   "chunk 2/6",         False),
    ("18:58:59", "wifi",  "-50dBm",            False),
    ("18:59:00", "sram",  "33KB",              False),
    ("18:59:01", "frames", "1024",             False),
]

def log_lines(d, rows_logs, x=72, y=54, width=328, lh=27, size=14, time_size=12):
    f, ft = mono(size), mono(time_size)
    tag_w, time_w = 68, 62
    for i, (ts, tag, msg, alert) in enumerate(rows_logs):
        yy = y + i * lh + lh // 2
        t(d, (x, yy), ts, ft, fill=MUTED, anchor="lm")
        t(d, (x + time_w, yy), tag, f, fill=(ACCENT if alert else INK), anchor="lm")
        fm = cjk(size) if any(ord(ch) > 127 for ch in msg) else f
        avail = width - time_w - tag_w
        s = msg
        while s and fm.getlength(s + "…") > avail:
            s = s[:-1]
        if s != msg:
            s += "…"
        t(d, (x + time_w + tag_w, yy), s, fm, fill=(ACCENT if alert else INK), anchor="lm")

def subtitle(d, text, top=262, bottom=314):
    d.rounded_rectangle([8, top, 472, bottom], radius=10, fill=INK)
    t(d, (W // 2, (top + bottom) // 2), text, cjk(20), fill=PAPER, anchor="mm")

def screen(state):
    im = Image.new("RGBA", (W, H), PAPER + (255,))
    d = ImageDraw.Draw(im)
    top_bar(d, state)

    # narrow status strip (64 px), same as variant A
    d.line([63, 40, 63, 260], fill=RULE, width=1)
    state_label = {"online": "在听", "offline": "断开", "speaking": "在说"}[state]
    for i, (lab, val) in enumerate([("状态", state_label), ("内存", "33KB"), ("帧", "1024")]):
        y = 56 + i * 66
        t(d, (12, y), lab, cjk(12), fill=MUTED)
        t(d, (12, y + 16), val, cjk(14) if not val.isascii() else mono(14))

    if state == "offline":
        log_lines(d, LOG_OFFLINE)
        subtitle(d, "链路断开，正在重连…")
        paste_avatar(im, 64, 72, 408, 168, opacity=0.4)
    elif state == "speaking":
        log_lines(d, LOG_SPEAKING)
        subtitle(d, "现在 23 度，湿度 48%。")
        paste_avatar(im, 64, 72, 408, 168)
    else:
        log_lines(d, LOG_ONLINE)
        subtitle(d, "我在，请说。")
        paste_avatar(im, 64, 72, 408, 168)

    return im.convert("RGB")

def compare_sheet():
    """64x72 vs 56x64, official exports, 1:1 (no scaling)."""
    im = Image.new("RGBA", (W, H), PAPER + (255,))
    d = ImageDraw.Draw(im)
    t(d, (16, 16), "头像占位对比 · 官方 A8 · 1:1 未缩放", cjk(20))
    t(d, (16, 46), "64×72（默认）", cjk(14), fill=MUTED)
    t(d, (280, 46), "56×64（冲突时降级）", cjk(14), fill=MUTED)

    paste_avatar(im, 64, 72, 64, 70)
    paste_avatar(im, 56, 64, 280, 78)

    t(d, (64, 150), "64×72 · 4,608 B", mono(12), fill=MUTED)
    t(d, (64, 168), "ink 65.5% · 日志右界 400", cjk(14))
    t(d, (280, 150), "56×64 · 3,584 B", mono(12), fill=MUTED)
    t(d, (280, 168), "ink 66.6% · 日志右界 408", cjk(14))

    d.line([16, 200, 464, 200], fill=RULE, width=1)
    t(d, (16, 208), "顶栏降级：① 头像 64→56（让出 8 px）", cjk(14))
    t(d, (16, 228), "② 文案退为「Hermes」+ 点　③ 只留点", cjk(14))
    t(d, (16, 256), "断开：alpha×0.4、空心点、文案「Hermes 断开」", cjk(14), fill=MUTED)
    t(d, (16, 282), "坐标：距右 8 · 底边 240（字幕条顶 262，留 22）", cjk(14), fill=MUTED)
    return im.convert("RGB")

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    screen("online").save(OUT / "hermes-online.png", optimize=True)
    screen("offline").save(OUT / "hermes-offline.png", optimize=True)
    screen("speaking").save(OUT / "hermes-speaking.png", optimize=True)
    compare_sheet().save(OUT / "avatar-size-compare.png", optimize=True)
    print("wrote 4 pngs to", OUT)
