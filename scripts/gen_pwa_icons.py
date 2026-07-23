"""Generate placeholder PWA icons with zero dependencies.

Writes a set of PNGs + an SVG into app/static/icons/ — a solid theme-colour tile
with a centred light disc. They're deliberately plain: swap them for your real
brand art (same filenames) whenever you like.

    python scripts/gen_pwa_icons.py                 # uses PWA_THEME_COLOR from .env
    python scripts/gen_pwa_icons.py --bg "#111827"  # override the tile colour
"""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

ICONS_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"

# (filename, pixel size) — the set browsers actually ask for.
PNG_SIZES = [
    ("icon-192.png", 192),
    ("icon-512.png", 512),
    ("icon-maskable-512.png", 512),
    ("apple-touch-icon.png", 180),
    ("favicon-32.png", 32),
]


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path: Path, size: int, bg: tuple[int, int, int], fg: tuple[int, int, int]) -> None:
    """Full-bleed bg tile with a centred fg disc (safe as a maskable icon)."""
    cx = cy = size / 2
    r = size * 0.30
    r2 = r * r
    bg_px, fg_px = bytes(bg), bytes(fg)
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # per-scanline filter: none
        for x in range(size):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            raw += fg_px if dx * dx + dy * dy <= r2 else bg_px
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def write_svg(path: Path, bg: str, fg: str) -> None:
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
        f'<rect width="512" height="512" rx="96" fill="{bg}"/>'
        f'<circle cx="256" cy="256" r="154" fill="{fg}"/>'
        "</svg>\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate placeholder PWA icons.")
    parser.add_argument("--bg", default=settings.PWA_THEME_COLOR, help="tile colour (hex)")
    parser.add_argument("--fg", default="#ffffff", help="disc colour (hex)")
    args = parser.parse_args()

    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    bg_rgb, fg_rgb = _hex_to_rgb(args.bg), _hex_to_rgb(args.fg)
    for name, size in PNG_SIZES:
        write_png(ICONS_DIR / name, size, bg_rgb, fg_rgb)
        print(f"wrote {name} ({size}x{size})")
    write_svg(ICONS_DIR / "icon.svg", args.bg, args.fg)
    print("wrote icon.svg")


if __name__ == "__main__":
    main()
