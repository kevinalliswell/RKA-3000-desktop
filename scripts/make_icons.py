"""Generate the application icons (PNG + ICO) with the standard library only.

A flat navy rounded square with a mint "R(t)" curve. Re-run to regenerate; the files are
committed so builds never depend on an image toolchain.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "src-tauri" / "icons"
NAVY = (0x12, 0x2B, 0x45, 255)
MINT = (0x5E, 0xD4, 0xB8, 255)
CLEAR = (0, 0, 0, 0)


def _inside_rounded(x: float, y: float, size: float, radius: float) -> bool:
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius**2


def _curve(t: float) -> float:
    # reduction-degree style saturation curve, normalised 0..1
    return 1.0 - 2.718281828 ** (-4.0 * t)


def render(size: int) -> bytes:
    pixels = bytearray()
    radius = size * 0.22
    stroke = max(1.5, size * 0.075)
    for row in range(size):
        pixels.append(0)  # filter type none
        for col in range(size):
            x, y = col + 0.5, row + 0.5
            if not _inside_rounded(x, y, size, radius):
                pixels.extend(CLEAR)
                continue
            color = NAVY
            # curve from (0.18, 0.80) to (0.86, 0.22)
            t = (x / size - 0.18) / 0.68
            if 0.0 <= t <= 1.0:
                curve_y = size * (0.80 - 0.58 * _curve(t))
                if abs(y - curve_y) <= stroke:
                    color = MINT
            if abs(y - size * 0.80) <= stroke * 0.45 and size * 0.14 <= x <= size * 0.88:
                color = MINT
            pixels.extend(color)
    return bytes(pixels)


def png(size: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(render(size), 9)) + chunk(b"IEND", b"")


def ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, data = b"", b""
    for size, blob in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset)
        data += blob
        offset += len(blob)
    return header + entries + data


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    rendered = {size: png(size) for size in (32, 128, 256)}
    for size, blob in rendered.items():
        (ICONS / f"{size}x{size}.png").write_bytes(blob)
    (ICONS / "icon.png").write_bytes(rendered[256])
    (ICONS / "icon.ico").write_bytes(ico([(256, rendered[256]), (32, rendered[32])]))
    (ROOT / "frontend" / "public").mkdir(parents=True, exist_ok=True)
    (ROOT / "frontend" / "public" / "icon.png").write_bytes(rendered[128])
    print(f"icons written to {ICONS}")


if __name__ == "__main__":
    main()
