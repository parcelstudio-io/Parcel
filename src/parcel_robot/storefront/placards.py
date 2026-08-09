"""Generate readable storefront text placards as RGB arrays / PNG textures.

Pure numpy + stdlib zlib — no Pillow. Glyphs are a fixed 5×7 bitmap font
scaled up so optional PP-OCR (when installed) can read synthetic pixels.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

# 5×7 uppercase + space + digits (bit rows, MSB = leftmost).
_GLYPHS: dict[str, tuple[int, ...]] = {
    " ": (0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00),
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    "C": (0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E),
    "D": (0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    "F": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10),
    "G": (0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0E),
    "H": (0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "I": (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "J": (0x01, 0x01, 0x01, 0x01, 0x11, 0x11, 0x0E),
    "K": (0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11),
    "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    "N": (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "Q": (0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D),
    "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    "S": (0x0E, 0x11, 0x10, 0x0E, 0x01, 0x11, 0x0E),
    "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
    "W": (0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11),
    "X": (0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11),
    "Y": (0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04),
    "Z": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F),
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "2": (0x0E, 0x11, 0x01, 0x06, 0x08, 0x10, 0x1F),
    "3": (0x0E, 0x11, 0x01, 0x06, 0x01, 0x11, 0x0E),
    "4": (0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02),
    "5": (0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    "7": (0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    "9": (0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C),
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    ".": (0x00, 0x00, 0x00, 0x00, 0x00, 0x0C, 0x0C),
    "&": (0x0C, 0x12, 0x14, 0x08, 0x15, 0x12, 0x0D),
}


def normalize_sign_text(text: str) -> str:
    """Uppercase + collapse whitespace; drop unsupported glyphs to space."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    cleaned: list[str] = []
    for ch in text.upper():
        if ch in _GLYPHS:
            cleaned.append(ch)
        elif ch.isspace():
            cleaned.append(" ")
        else:
            cleaned.append(" ")
    return " ".join("".join(cleaned).split())


def render_placard_rgb(
    text: str,
    *,
    width: int,
    height: int,
    bg_rgb: tuple[int, int, int] = (20, 20, 20),
    fg_rgb: tuple[int, int, int] = (255, 255, 255),
    margin_px: int = 8,
    scale: int | None = None,
) -> np.ndarray:
    """Rasterize ``text`` into an RGB uint8 placard of shape (H, W, 3)."""

    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or isinstance(height, bool)
        or not isinstance(height, int)
        or width < 16
        or height < 16
    ):
        raise ValueError("width/height must be integers ≥ 16")
    for name, rgb in (("bg_rgb", bg_rgb), ("fg_rgb", fg_rgb)):
        if len(rgb) != 3 or any(
            isinstance(c, bool) or not isinstance(c, int) or not 0 <= c <= 255 for c in rgb
        ):
            raise ValueError(f"{name} must be three ints in [0, 255]")

    normalized = normalize_sign_text(text)
    if not normalized:
        raise ValueError("text must contain at least one renderable glyph")

    img = np.empty((height, width, 3), dtype=np.uint8)
    img[:] = np.asarray(bg_rgb, dtype=np.uint8)

    chars = list(normalized)
    glyph_w, glyph_h = 5, 7
    gap = 1
    usable_w = max(1, width - 2 * margin_px)
    usable_h = max(1, height - 2 * margin_px)
    text_cols = len(chars) * (glyph_w + gap) - gap
    if scale is None:
        scale = max(1, min(usable_w // text_cols, usable_h // glyph_h))
    if isinstance(scale, bool) or not isinstance(scale, int) or scale < 1:
        raise ValueError("scale must be a positive integer")

    total_w = text_cols * scale
    total_h = glyph_h * scale
    x0 = max(margin_px, (width - total_w) // 2)
    y0 = max(margin_px, (height - total_h) // 2)
    fg = np.asarray(fg_rgb, dtype=np.uint8)

    cursor = x0
    for ch in chars:
        bits = _GLYPHS.get(ch, _GLYPHS[" "])
        for row, row_bits in enumerate(bits):
            for col in range(glyph_w):
                if row_bits & (1 << (glyph_w - 1 - col)):
                    yy0 = y0 + row * scale
                    xx0 = cursor + col * scale
                    img[yy0 : yy0 + scale, xx0 : xx0 + scale] = fg
        cursor += (glyph_w + gap) * scale
    return img


def write_png_rgb(path: Path | str, rgb: np.ndarray) -> Path:
    """Write an RGB uint8 array as a minimal PNG (stdlib zlib only)."""

    if not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3:
        raise TypeError("rgb must be a uint8 HxWx3 ndarray")
    if rgb.shape[2] != 3:
        raise ValueError("rgb must have 3 channels")
    h, w, _ = rgb.shape
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit RGB
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    out.write_bytes(png)
    return out.resolve()


def ensure_placard_png(
    path: Path | str,
    text: str,
    *,
    width: int = 640,
    height: int = 160,
    bg_rgb: tuple[int, int, int] = (20, 20, 20),
    fg_rgb: tuple[int, int, int] = (255, 255, 255),
) -> Path:
    """Create placard PNG if missing; return resolved path."""

    target = Path(path)
    if target.is_file():
        return target.resolve()
    rgb = render_placard_rgb(
        text, width=width, height=height, bg_rgb=bg_rgb, fg_rgb=fg_rgb
    )
    return write_png_rgb(target, rgb)
