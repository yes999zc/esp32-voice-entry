#!/usr/bin/env python3
"""Render UI v2 log-first variants (480x320) for review.

Placeholder fonts only (target MiSans / JetBrains Mono are not installed):
  CJK  : Hiragino Sans GB W3   (/System/Library/Fonts/Hiragino Sans GB.ttc, index 0)
  Mono : SF Mono               (/System/Library/Fonts/SFNSMono.ttf)
See docs/fonts/font-spec.md for the final fonts.

Output: variant-a.png, variant-b.png, variant-c.png, variant-d.png in this dir.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 480, 320
PAPER = (0xF4, 0xF3, 0xEA)
INK = (0x20, 0x2B, 0x2D)
ACCENT = (0xE2, 0x70, 0x3A)
MUTED = (0x6B, 0x73, 0x72)
RULE = (0xD8, 0xD5, 0xC6)

CJK = "/System/Library/Fonts/Hiragino Sans GB.ttc"
MONO = "/System/Library/Fonts/SFNSMono.ttf"
OUT = Path(__file__).resolve().parent

_f = {}
def cjk(s):
    if ("c", s) not in _f:
        _f[("c", s)] = ImageFont.truetype(CJK, s, index=0)
    return _f[("c", s)]

def mono(s):
    if ("m", s) not in _f:
        _f[("m", s)] = ImageFont.truetype(MONO, s)
    return _f[("m", s)]

def t(d, xy, s, font, fill=INK, anchor="la"):
    d.text(xy, s, font=font, fill=fill, anchor=anchor)

def fit(s, font, width):
    """Truncate with an ellipsis so every log line fits its column."""
    if font.getlength(s) <= width:
        return s
    while s and font.getlength(s + "…") > width:
        s = s[:-1]
    return s + "…"

def wifi(d, x, y):
    for r in (14, 9, 4):
        d.arc([x - r, y - r, x + r, y + r], start=225, end=315, fill=INK, width=2)
    d.rectangle([x - 1, y - 1, x + 1, y + 1], fill=INK)

def status_dot(d, x=16, y=15):
    d.rectangle([x, y, x + 8, y + 8], fill=ACCENT)

def subtitle(d, text, top=262, bottom=314, font_size=20):
    d.rounded_rectangle([8, top, 472, bottom], radius=10, fill=INK)
    t(d, (W // 2, (top + bottom) // 2), text, cjk(font_size), fill=PAPER, anchor="mm")

LOG = [
    ("18:58:55", "asr",   '"你好小智"',        False),
    ("18:58:56", "llm",   "hermes 1.2s",       False),
    ("18:58:57", "tts",   "first frame 420ms", False),
    ("18:58:58", "mute",  "off",               False),
    ("18:58:59", "wifi",  "-50dBm",            False),
    ("18:59:00", "sram",  "33KB",              False),
    ("18:59:01", "frames", "1024",             False),
    ("18:59:02", "tool",  "get_weather 0.8s",  False),
    ("18:59:03", "turn",  "done 3.4s",         False),
    ("18:59:04", "ws",    "connected",         False),
    ("18:59:05", "vad",   "speech end",        False),
    ("18:59:06", "sram",  "33KB low",          True),   # orange alert
]

def log_lines(d, x, y, width, rows, lh, size=14, time_size=12, start=0):
    f, ft = mono(size), mono(time_size)
    tag_w, time_w = (68 if size >= 14 else 60), 62
    for i in range(rows):
        ts, tag, msg, alert = LOG[(start + i) % len(LOG)]
        yy = y + i * lh
        t(d, (x, yy + lh // 2), ts, ft, fill=MUTED, anchor="lm")
        t(d, (x + time_w, yy + lh // 2), tag, f, fill=(ACCENT if alert else INK), anchor="lm")
        avail = width - time_w - tag_w
        fm = cjk(size) if any(ord(ch) > 127 for ch in msg) else f   # ASR text is Chinese
        t(d, (x + time_w + tag_w, yy + lh // 2), fit(msg, fm, avail), fm,
          fill=(ACCENT if alert else INK), anchor="lm")

def card(d, x, y, w, h, label, value, vsize=16):
    d.rectangle([x, y, x + w, y + h], outline=RULE, width=1)
    t(d, (x + 8, y + 8), label, cjk(12), fill=MUTED)
    t(d, (x + 8, y + h - 10), value, cjk(vsize) if not value.isascii() else mono(vsize), anchor="ls")

def top_bar(d, h=40, vol=True):
    d.line([0, h - 1, W, h - 1], fill=INK, width=1)
    status_dot(d)
    t(d, (30, 20), "小智", cjk(14), anchor="lm")
    t(d, (64, 20), "在线", cjk(14), fill=MUTED, anchor="lm")
    t(d, (W // 2, 20), "18:59:06", mono(14), anchor="mm")
    wifi(d, 404, 21)
    if vol:
        t(d, (464, 20), "6/10", mono(12), anchor="rm")

def variant_a():
    im = Image.new("RGB", (W, H), PAPER); d = ImageDraw.Draw(im)
    top_bar(d, 40)
    # narrow left status strip (64 px)
    d.line([63, 40, 63, 260], fill=RULE, width=1)
    for i, (lab, val) in enumerate([("状态", "在听"), ("内存", "33KB"), ("帧", "1024")]):
        y = 56 + i * 66
        t(d, (12, y), lab, cjk(12), fill=MUTED)
        t(d, (12, y + 16), val, cjk(14) if not val.isascii() else mono(14))
    log_lines(d, 72, 54, 400, rows=7, lh=27, size=14, time_size=12)
    subtitle(d, "在听，请说。")
    return im

def variant_b():
    im = Image.new("RGB", (W, H), PAPER); d = ImageDraw.Draw(im)
    top_bar(d, 32, vol=False)
    cards = [("状态", "在听"), ("音量", "6/10"), ("网络", "-50dBm"),
             ("uptime", "2h14"), ("内存", "33KB"), ("frames", "1024")]
    for i, (lab, val) in enumerate(cards):
        x = 6 + (i % 2) * 82
        y = 40 + (i // 2) * 72
        card(d, x, y, 76, 64, lab, val, vsize=16)
    d.line([168, 32, 168, 260], fill=RULE, width=1)
    log_lines(d, 176, 40, 296, rows=7, lh=28, size=14, time_size=12, start=2)
    subtitle(d, "在听，请说。")
    return im

def variant_c():
    im = Image.new("RGB", (W, H), PAPER); d = ImageDraw.Draw(im)
    log_lines(d, 12, 6, 456, rows=11, lh=22, size=14, time_size=12, start=1)
    # top translucent status band
    band = Image.new("RGBA", (W, 30), PAPER + (250,))
    im.paste(Image.alpha_composite(im.crop((0, 0, W, 30)).convert("RGBA"), band).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(im)
    d.line([0, 29, W, 29], fill=INK, width=1)
    status_dot(d, 16, 10)
    t(d, (30, 15), "小智", cjk(14), anchor="lm")
    t(d, (64, 15), "在线", cjk(14), fill=MUTED, anchor="lm")
    t(d, (W // 2, 15), "18:59:06", mono(13), anchor="mm")
    wifi(d, 412, 16)
    t(d, (464, 15), "6/10", mono(12), anchor="rm")
    subtitle(d, "现在 23 度，湿度 48%。", top=266, bottom=316)
    return im

def variant_d():
    im = Image.new("RGB", (W, H), PAPER); d = ImageDraw.Draw(im)
    top_bar(d, 30, vol=False)
    cards = [("状态", "在听"), ("音量", "6/10"), ("网络", "-50dBm"),
             ("uptime", "2h14"), ("内存", "33KB"), ("frames", "1024")]
    for i, (lab, val) in enumerate(cards):
        x = 6 + (i % 3) * 158
        y = 38 + (i // 3) * 66
        card(d, x, y, 152, 60, lab, val, vsize=16)
    d.line([0, 170, W, 170], fill=RULE, width=1)
    log_lines(d, 12, 180, 456, rows=4, lh=20, size=13, time_size=11, start=8)
    subtitle(d, "在听，请说。")
    return im

if __name__ == "__main__":
    for name, fn in [("variant-a", variant_a), ("variant-b", variant_b),
                     ("variant-c", variant_c), ("variant-d", variant_d)]:
        fn().save(OUT / f"{name}.png", optimize=True)
        print("wrote", OUT / f"{name}.png")
