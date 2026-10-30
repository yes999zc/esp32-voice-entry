#!/usr/bin/env python3
"""Render static UI v2 mockups (480x320) for review.

Placeholder fonts (target fonts are NOT installed on this machine):
  - Chinese: Hiragino Sans GB W3  (/System/Library/Fonts/Hiragino Sans GB.ttc, index 0)
  - Latin/digits: SF Mono        (/System/Library/Fonts/SFNSMono.ttf)
Final firmware fonts are MiSans (CJK) + JetBrains Mono (Latin), generated with
lv_font_conv --bpp 4; see docs/fonts/font-spec.md.

This script only draws; it does not touch firmware.
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

W, H = 480, 320
PAPER = (0xF4, 0xF3, 0xEA)
INK = (0x20, 0x2B, 0x2D)
ACCENT = (0xE2, 0x70, 0x3A)

CJK = "/System/Library/Fonts/Hiragino Sans GB.ttc"
MONO = "/System/Library/Fonts/SFNSMono.ttf"
OUT = Path(__file__).resolve().parents[2] / "docs" / "face" / "ui-v2"

_fonts = {}
def cjk(size):
    key = ("cjk", size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(CJK, size, index=0)
    return _fonts[key]

def mono(size):
    key = ("mono", size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(MONO, size)
    return _fonts[key]

def text(d, xy, s, font, fill=INK, anchor="la"):
    d.text(xy, s, font=font, fill=fill, anchor=anchor)

def wifi(d, x, y):
    # 3 arcs + dot, 2 px ink, snapped to an 8 px grid
    for r in (18, 12, 6):
        d.arc([x - r, y - r, x + r, y + r], start=225, end=315, fill=INK, width=2)
    d.rectangle([x - 2, y - 2, x + 2, y + 2], fill=INK)

def robot_face(d, x, y):
    """Pixel-outline robot, 96x96 box, 2 px strokes, ink only (no images)."""
    # antenna
    d.rectangle([x + 45, y + 2, x + 51, y + 10], fill=INK)
    d.rectangle([x + 41, y - 6, x + 55, y + 4], outline=INK, width=2)
    # ears
    d.rectangle([x - 6, y + 30, x + 0, y + 54], fill=INK)
    d.rectangle([x + 96, y + 30, x + 102, y + 54], fill=INK)
    # head
    d.rectangle([x, y + 10, x + 96, y + 90], outline=INK, width=2, fill=PAPER)
    # eyes (12x12 with 4x4 paper glint)
    d.rectangle([x + 20, y + 34, x + 32, y + 46], fill=INK)
    d.rectangle([x + 64, y + 34, x + 76, y + 46], fill=INK)
    d.rectangle([x + 23, y + 37, x + 27, y + 41], fill=PAPER)
    d.rectangle([x + 67, y + 37, x + 71, y + 41], fill=PAPER)
    # mouth: speaker-like bar with 2 gaps
    for dx in (28, 40, 52):
        d.rectangle([x + dx, y + 62, x + dx + 8, y + 72], fill=INK)

def segmented_bar(d, x, y, w, filled, total=12, h=12, gap=3):
    seg = (w - gap * (total - 1)) / total
    for i in range(total):
        x0 = round(x + i * (seg + gap))
        x1 = round(x0 + seg)
        if i < filled:
            d.rectangle([x0, y, x1, y + h], fill=INK)
        else:
            d.rectangle([x0, y, x1, y + h], outline=INK, width=1)

def frame(state):
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)

    # ---- top bar (40) ----
    d.line([0, 39, W, 39], fill=INK, width=1)
    d.rectangle([16, 15, 24, 23], fill=INK)             # status dot (ink: accent is single-use)
    text(d, (32, 20), state["top_left"], cjk(14), anchor="lm")
    text(d, (W // 2, 20), state["top_center"], cjk(14), anchor="mm")
    wifi(d, 424, 30)
    text(d, (462, 20), "5G", mono(14), anchor="rm")

    # ---- main (40..260) ----
    # room name
    text(d, (16, 52), state["room"], cjk(32))
    # status chip: accent bar is the single accent use on this screen
    d.rectangle([16, 108, 19, 129], fill=ACCENT)
    text(d, (30, 119), state["status"], cjk(20), anchor="lm")
    # segmented bar
    segmented_bar(d, 16, 146, 248, state["filled"])
    text(d, (268, 152), f'{state["filled"]:02d} / 12', mono(14), anchor="lm")
    # 3 detail rows
    for i, (label, value) in enumerate(state["details"]):
        y = 184 + i * 24
        text(d, (16, y), label, cjk(14), fill=(0x6B, 0x73, 0x72))
        text(d, (96, y), value, cjk(14))
        d.line([16, y + 18, 304, y + 18], fill=(0xD8, 0xD5, 0xC6), width=1)

    # right panel: robot face (x 320..464)
    d.line([318, 48, 318, 252], fill=(0xD8, 0xD5, 0xC6), width=1)
    robot_face(d, 344, 96)

    # ---- bottom subtitle (60) ----
    d.rounded_rectangle([8, 262, 472, 314], radius=10, fill=INK)
    text(d, (W // 2, 288), state["subtitle"], cjk(20), fill=PAPER, anchor="mm")
    return im

SCREENS = {
    "idle": dict(
        top_left="在线", top_center="客厅 · 14:32", room="客厅", status="空闲",
        filled=3,
        details=[("唤醒词", "你好小智"), ("音量", "6 / 10"), ("网络", "5G 良好")],
        subtitle="你好，我在。",
    ),
    "listening": dict(
        top_left="在线", top_center="客厅 · 14:32", room="客厅", status="在听",
        filled=6,
        details=[("识别", "实时转写"), ("音量", "6 / 10"), ("网络", "5G 良好")],
        subtitle="我在，请说。",
    ),
    "speaking": dict(
        top_left="在线", top_center="客厅 · 14:32", room="客厅", status="在说",
        filled=9,
        details=[("播报", "剩余 2 句"), ("音量", "7 / 10"), ("网络", "5G 良好")],
        subtitle="客厅现在 23 度，湿度 48%。",
    ),
}

def font_sheet():
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    d.line([0, 39, W, 39], fill=INK, width=1)
    text(d, (16, 12), "FONT SHEET · 480×320 · bpp4", mono(14), fill=(0x6B, 0x73, 0x72))

    text(d, (16, 48), "32px", mono(14), fill=(0x6B, 0x73, 0x72))
    text(d, (16, 64), "客厅 在听 在想 在说", cjk(32))

    text(d, (16, 112), "20px", mono(14), fill=(0x6B, 0x73, 0x72))
    text(d, (16, 128), "你好，我在。今天天气不错。", cjk(20))

    text(d, (16, 160), "14px", mono(14), fill=(0x6B, 0x73, 0x72))
    text(d, (16, 176), "唤醒词  音量  网络  信号  待机  播报", cjk(14))

    text(d, (16, 202), "44px mono", mono(14), fill=(0x6B, 0x73, 0x72))
    text(d, (16, 216), "23°", mono(44))
    text(d, (150, 222), "主数值 / 分段条数字", cjk(14), fill=(0x6B, 0x73, 0x72))
    text(d, (150, 240), "6 / 12", mono(20))

    d.line([0, 276, W, 276], fill=(0xD8, 0xD5, 0xC6), width=1)
    text(d, (16, 286), "样张字体：Hiragino Sans GB W3 / SF Mono（占位）", cjk(14), fill=(0x6B, 0x73, 0x72))
    text(d, (16, 304), "最终：MiSans 子集 + JetBrains Mono 子集", cjk(14), fill=(0x6B, 0x73, 0x72))
    return im

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, st in SCREENS.items():
        frame(st).save(OUT / f"ui-{name}.png", optimize=True)
    font_sheet().save(OUT / "font-sample.png", optimize=True)
    print("wrote", *(str(p) for p in sorted(OUT.glob("*.png"))), sep="\n  ")
