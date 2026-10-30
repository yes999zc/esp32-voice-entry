"""Minimal PNG writer — no Pillow dependency.

The matrix renderer produces ~8 frames/second of 480x320 images, so this only
needs to be fast enough for a few frames per second, not general purpose.
"""
import struct
import zlib


def write_png(path: str, width: int, height: int, rows: bytes) -> int:
    """Write an 8-bit RGB PNG. `rows` is height * (1 + width*3) bytes: a filter
    byte (0) followed by the RGB triplets of one scanline."""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)
