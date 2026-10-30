"""Matrix data-stream renderer for the 480x320 device screen.

The board's own firmware can draw this (see xiaozhi-esp32/main/display/matrix_ui.cc),
but this pure-Python version lets us put the effect on screen from the server today,
on the stock firmware, by pushing PNG frames through the preview_image tool.
"""
import random

from pngwrite import write_png

# 5x7 ASCII glyphs, chars 32..126, classic Adafruit GFX table (public domain).
_FONT_HEX = (
"000000000000005f00000007000700147f147f14242a7f2a12231308646236495620500008070300001c2241000041221c002a1c7f1c2a08083e080800807030000808080808000060600020100804023e5149453e00427f400072494949462141494d331814127f1027454545393c4a49493141211109073649494936464949291e0000140000004034000000081422411414141414004122140802015909063e415d594e7c1211127c7f494949363e414141227f4141413e7f494949417f090909013e414151737f0808087f00417f41002040413f017f081422417f404040407f021c027f7f0408107f3e4141413e7f090909063e4151215e7f09192946264949493203017f01033f4040403f1f2040201f3f4038403f631408146303047804036159494d43007f4141410204081020004141417f04020102044040404040000307080020545478407f284444383844444428384444287f385454541800087e090218a4a49c787f0804047800447d40002040403d007f1028440000417f40007c047804787c080404783844444438fc1824241818242418fc7c08040408485454542404043f44243c4040207c1c2040201c3c4030403c44281028444c9090907c4464544c440008364100000077000000413608000201020402"
)
FONT = bytes.fromhex(_FONT_HEX)

CELL_W, CELL_H = 6, 8
GLYPH_W, GLYPH_H = 5, 7
DECAY = 0.88


def _glyph_columns(ch: str):
    idx = (ord(ch) - 32) * 5
    if idx < 0 or idx + 5 > len(FONT):
        idx = (ord("?") - 32) * 5
    return FONT[idx:idx + 5]


class MatrixRain:
    """A falling-glyph field with a status band, rendered straight to RGB bytes."""

    def __init__(self, width: int = 480, height: int = 320, seed: int | None = None):
        self.width, self.height = width, height
        self.cols = width // CELL_W
        self.rows = height // CELL_H
        self.rng = random.Random(seed)
        self.heat = bytearray(self.cols * self.rows)      # per-cell intensity
        self.char = [self.rng.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<>/*+-=:.") for _ in range(self.cols * self.rows)]
        self.head = [self.rng.uniform(-self.rows, 0) for _ in range(self.cols)]
        self.speed = [self.rng.uniform(0.25, 1.0) for _ in range(self.cols)]
        self.trail = [self.rng.randint(5, 16) for _ in range(self.cols)]
        self.status = "ONLINE"
        self.line = ""

    def set_status(self, text: str) -> None:
        self.status = text

    def set_line(self, text: str) -> None:
        """Last thing heard or said; non-ASCII collapses to '?'."""
        self.line = "".join(c if 32 <= ord(c) < 127 else "?" for c in text)[:76]

    def step(self) -> None:
        heat, char = self.heat, self.char
        for i in range(len(heat)):
            v = heat[i]
            heat[i] = int(v * DECAY) if v > 2 else 0
        for x in range(self.cols):
            h = self.head[x]
            row = int(h)
            if 0 <= row < self.rows:
                i = row * self.cols + x
                heat[i] = 255
                char[i] = self.rng.choice("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ<>/*+-=:.")
                if row > 0:
                    heat[i - self.cols] = max(heat[i - self.cols], 190)
            self.head[x] = h + self.speed[x]
            if h > self.rows + self.trail[x]:
                self.head[x] = -self.rng.uniform(1, 12)
                self.speed[x] = self.rng.uniform(0.25, 1.0)
                self.trail[x] = self.rng.randint(5, 16)

    def _draw_text(self, buf: bytearray, x0: int, y0: int, text: str, rgb) -> None:
        r, g, b = rgb
        for n, ch in enumerate(text):
            if ch == " ":
                continue
            for col, bits in enumerate(_glyph_columns(ch)):
                px = x0 + n * CELL_W + col
                if px >= self.width:
                    return
                for row in range(GLYPH_H):
                    if bits & (1 << row):
                        py = y0 + row
                        if 0 <= py < self.height:
                            o = (py * self.width + px) * 3
                            buf[o:o + 3] = bytes((r, g, b))

    def render(self) -> bytes:
        """Return PNG bytes for the current state."""
        w, h = self.width, self.height
        buf = bytearray(w * h * 3)
        heat, char = self.heat, self.char
        for y in range(self.rows):
            base = y * self.cols
            for x in range(self.cols):
                v = heat[base + x]
                if v < 6:
                    continue
                bits_list = _glyph_columns(char[base + x])
                # leading glyph is near-white, the trail fades to green
                if v > 220:
                    rgb = build_colour(min(255, v), 255)
                else:
                    rgb = build_colour(v, int(v * 0.85))
                x0, y0 = x * CELL_W, y * CELL_H
                for col, bits in enumerate(bits_list):
                    if not bits:
                        continue
                    px = x0 + col
                    for row in range(GLYPH_H):
                        if bits & (1 << row):
                            py = y0 + row
                            o = (py * w + px) * 3
                            buf[o:o + 3] = rgb

        band_y = h - CELL_H - 2
        buf[(band_y - 1) * w * 3:] = bytes(len(buf) - (band_y - 1) * w * 3)  # clear band
        self._draw_text(buf, 4, band_y, "> " + self.status, (120, 255, 150))
        if self.line:
            self._draw_text(buf, 4, band_y - 10, self.line, (60, 200, 90))

        rows = bytearray()
        stride = w * 3
        for y in range(h):
            rows.append(0)
            rows += buf[y * stride:(y + 1) * stride]
        return rows


def build_colour(v: int, head: int) -> bytes:
    """LED-green ramp: intensity v (0-255), head=255 marks the leading glyph."""
    g = min(255, int(v * 0.95) + (25 if head > 200 else 0))
    r = int(v * 0.10)
    b = int(v * 0.16)
    return bytes((r, g, b))


def render_png(path: str, rain: MatrixRain) -> int:
    rows = rain.render()
    return write_png(path, rain.width, rain.height, rows)
