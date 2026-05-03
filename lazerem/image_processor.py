"""Image processing for the Ray5W laser control.

Provides image loading (PNG via tkinter, BMP via struct), brightness/
contrast/saturation adjustment, and raster-to-vector tracing.

All pixel operations work on ``PixelGrid`` objects – plain Python lists
of ``(r, g, b)`` tuples stored row-major.

Image tracing modes
-------------------
``threshold``       – Simple binary threshold; each dark run becomes a
                      single G1 move in a scanline raster engrave.
``floyd-steinberg`` – Error-diffusion dithering before threshold;
                      produces halftone-like engrave output.
``jarvis``          – Jarvis-Judice-Ninke error diffusion (slightly
                      higher quality).

Output
------
Every trace function returns a GRBL G-code string suitable for pasting
into the editor.  The G-code uses a raster (scanline) strategy:

  * Even rows scan left→right.
  * Odd rows scan right→left (bidirectional / boustrophedon).
  * Dark pixels → G1 with the configured power.
  * Light pixels → G0 (rapid, laser off).

The image origin is placed at (0, 0) in machine coordinates.
Each pixel maps to *pixel_size* mm (default 0.1 mm ≈ 254 DPI).
"""

from __future__ import annotations

import math
import struct
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Pixel grid
# ---------------------------------------------------------------------------

# PixelGrid: List of rows, each row a list of (r, g, b) tuples (0-255).
PixelGrid = List[List[Tuple[int, int, int]]]


def _make_grid(width: int, height: int,
               fill: Tuple[int, int, int] = (255, 255, 255)) -> PixelGrid:
    return [[fill] * width for _ in range(height)]


# ---------------------------------------------------------------------------
# Image loading
# ---------------------------------------------------------------------------

def load_png_tkinter(path: str) -> Tuple[PixelGrid, int, int]:
    """Load a PNG file using ``tkinter.PhotoImage``.

    Returns ``(grid, width, height)``.  Requires a Tk root to exist.
    """
    import tkinter as tk
    root = tk._default_root  # type: ignore[attr-defined]
    img = tk.PhotoImage(file=path)
    w, h = img.width(), img.height()
    grid = _make_grid(w, h)
    for y in range(h):
        for x in range(w):
            raw = img.get(x, y)
            if isinstance(raw, str):
                parts = raw.split()
                r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
            else:
                r, g, b = int(raw[0]), int(raw[1]), int(raw[2])
            grid[y][x] = (r, g, b)
    return grid, w, h


def load_bmp(path: str) -> Tuple[PixelGrid, int, int]:
    """Load a 24-bit or 32-bit BMP file without PIL.

    Returns ``(grid, width, height)``.
    """
    with open(path, "rb") as fh:
        data = fh.read()

    sig = data[:2]
    if sig != b"BM":
        raise ValueError(f"Not a BMP file (signature: {sig!r})")

    # File header (14 bytes)
    data_offset = struct.unpack_from("<I", data, 10)[0]

    # DIB header
    dib_size = struct.unpack_from("<I", data, 14)[0]
    if dib_size < 40:
        raise ValueError(f"Unsupported DIB header size: {dib_size}")

    width, height = struct.unpack_from("<ii", data, 18)
    bit_count = struct.unpack_from("<H", data, 28)[0]
    compression = struct.unpack_from("<I", data, 30)[0]

    if compression not in (0, 3):  # BI_RGB or BI_BITFIELDS
        raise ValueError(f"Unsupported BMP compression: {compression}")
    if bit_count not in (24, 32):
        raise ValueError(f"Only 24/32-bit BMP supported (got {bit_count})")

    bottom_up = height > 0
    height = abs(height)
    row_size = ((width * bit_count // 8 + 3) // 4) * 4  # 4-byte aligned
    bytes_per_pixel = bit_count // 8

    grid = _make_grid(width, height)
    for row in range(height):
        src_row = (height - 1 - row) if bottom_up else row
        offset = data_offset + src_row * row_size
        for col in range(width):
            p = offset + col * bytes_per_pixel
            b_val = data[p]
            g_val = data[p + 1]
            r_val = data[p + 2]
            grid[row][col] = (r_val, g_val, b_val)

    return grid, width, height


# ---------------------------------------------------------------------------
# Colour operations
# ---------------------------------------------------------------------------

def to_grayscale(grid: PixelGrid) -> List[List[float]]:
    """Convert RGB grid to 0.0–1.0 grayscale (luminance)."""
    return [
        [0.299 * r + 0.587 * g + 0.114 * b
         for r, g, b in row]
        for row in grid
    ]


def _clamp_byte(v: float) -> int:
    return max(0, min(255, int(round(v))))


def adjust_brightness(
    grid: PixelGrid,
    factor: float,
) -> PixelGrid:
    """Multiply each channel by *factor* (1.0 = no change, 2.0 = double)."""
    return [
        [(_clamp_byte(r * factor),
          _clamp_byte(g * factor),
          _clamp_byte(b * factor))
         for r, g, b in row]
        for row in grid
    ]


def adjust_contrast(
    grid: PixelGrid,
    factor: float,
) -> PixelGrid:
    """Apply contrast adjustment: pixel = (pixel - 128) * factor + 128."""
    return [
        [(_clamp_byte((r - 128) * factor + 128),
          _clamp_byte((g - 128) * factor + 128),
          _clamp_byte((b - 128) * factor + 128))
         for r, g, b in row]
        for row in grid
    ]


def _rgb_to_hsl(
    r: int, g: int, b: int,
) -> Tuple[float, float, float]:
    r_, g_, b_ = r / 255, g / 255, b / 255
    cmax = max(r_, g_, b_)
    cmin = min(r_, g_, b_)
    delta = cmax - cmin
    l = (cmax + cmin) / 2
    if delta < 1e-9:
        return 0.0, 0.0, l
    s = delta / (1 - abs(2 * l - 1))
    if cmax == r_:
        h = 60 * ((g_ - b_) / delta % 6)
    elif cmax == g_:
        h = 60 * ((b_ - r_) / delta + 2)
    else:
        h = 60 * ((r_ - g_) / delta + 4)
    return h, s, l


def _hsl_to_rgb(h: float, s: float, l: float) -> Tuple[int, int, int]:
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if h < 60:
        r_, g_, b_ = c, x, 0.0
    elif h < 120:
        r_, g_, b_ = x, c, 0.0
    elif h < 180:
        r_, g_, b_ = 0.0, c, x
    elif h < 240:
        r_, g_, b_ = 0.0, x, c
    elif h < 300:
        r_, g_, b_ = x, 0.0, c
    else:
        r_, g_, b_ = c, 0.0, x
    return (
        _clamp_byte((r_ + m) * 255),
        _clamp_byte((g_ + m) * 255),
        _clamp_byte((b_ + m) * 255),
    )


def adjust_saturation(
    grid: PixelGrid,
    factor: float,
) -> PixelGrid:
    """Multiply the HSL saturation by *factor* (0.0 = greyscale, 1.0 = no
    change, 2.0 = double)."""
    result: PixelGrid = []
    for row in grid:
        new_row = []
        for r, g, b in row:
            h, s, l = _rgb_to_hsl(r, g, b)
            s = max(0.0, min(1.0, s * factor))
            new_row.append(_hsl_to_rgb(h, s, l))
        result.append(new_row)
    return result


# ---------------------------------------------------------------------------
# Dithering helpers
# ---------------------------------------------------------------------------

def _dither_threshold(
    gray: List[List[float]],
    threshold: float = 0.5,
) -> List[List[bool]]:
    """Simple threshold: True = engrave (dark)."""
    return [
        [pix < threshold for pix in row]
        for row in gray
    ]


def _dither_floyd_steinberg(
    gray: List[List[float]],
    threshold: float = 0.5,
) -> List[List[bool]]:
    """Floyd-Steinberg error-diffusion dithering."""
    h = len(gray)
    w = len(gray[0]) if h else 0
    buf = [list(row) for row in gray]
    out: List[List[bool]] = [[False] * w for _ in range(h)]

    for y in range(h):
        for x in range(w):
            old = buf[y][x]
            new = 0.0 if old < threshold else 1.0
            out[y][x] = (new == 0.0)
            err = old - new
            if x + 1 < w:
                buf[y][x + 1] += err * 7 / 16
            if y + 1 < h:
                if x > 0:
                    buf[y + 1][x - 1] += err * 3 / 16
                buf[y + 1][x] += err * 5 / 16
                if x + 1 < w:
                    buf[y + 1][x + 1] += err * 1 / 16
    return out


def _dither_jarvis(
    gray: List[List[float]],
    threshold: float = 0.5,
) -> List[List[bool]]:
    """Jarvis-Judice-Ninke dithering."""
    h = len(gray)
    w = len(gray[0]) if h else 0
    buf = [list(row) for row in gray]
    out: List[List[bool]] = [[False] * w for _ in range(h)]

    jjn = [
        [0, 0, 0, 7, 5],
        [3, 5, 7, 5, 3],
        [1, 3, 5, 3, 1],
    ]

    for y in range(h):
        for x in range(w):
            old = buf[y][x]
            new = 0.0 if old < threshold else 1.0
            out[y][x] = (new == 0.0)
            err = (old - new) / 48.0
            for dy, row_w in enumerate(jjn):
                for dx_i, w_val in enumerate(row_w):
                    if w_val == 0:
                        continue
                    nx = x + dx_i - 2
                    ny = y + dy
                    if 0 <= ny < h and 0 <= nx < w:
                        buf[ny][nx] += err * w_val
    return out


# ---------------------------------------------------------------------------
# Raster G-code generator
# ---------------------------------------------------------------------------

def _binary_to_gcode(
    bitmap: List[List[bool]],
    power: float,
    speed: float,
    pixel_size: float,
) -> str:
    """Convert a boolean bitmap to boustrophedon (bidirectional) raster
    G-code.

    *bitmap[y][x]* is ``True`` where the laser should fire.
    """
    h = len(bitmap)
    w = len(bitmap[0]) if h else 0
    lines = [
        "G21 G90  ; metric, absolute",
        "M5       ; ensure laser off",
        f"G0 X0.000 Y0.000",
        "",
    ]

    for y in range(h):
        row = bitmap[y]
        gy = y * pixel_size
        # Boustrophedon: alternate scan direction
        if y % 2 == 0:
            indices = range(w)
        else:
            indices = range(w - 1, -1, -1)

        laser_on = False
        for x in indices:
            gx = x * pixel_size
            if row[x] and not laser_on:
                # Start laser
                lines.append(f"G0 X{gx:.4f} Y{gy:.4f}")
                lines.append(f"M3 S{power:.0f}")
                laser_on = True
            elif not row[x] and laser_on:
                # Stop laser at previous position
                lines.append("M5")
                laser_on = False
            if row[x]:
                lines.append(f"G1 X{gx:.4f} Y{gy:.4f} F{speed:.0f}")
        if laser_on:
            lines.append("M5")

    lines.extend(["", "G0 X0.000 Y0.000", "M2"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def trace_image(
    grid: PixelGrid,
    mode: str = "threshold",
    threshold: float = 0.5,
    power: float = 500.0,
    speed: float = 3000.0,
    pixel_size: float = 0.1,
) -> str:
    """Convert an RGB *grid* to G-code using the specified *mode*.

    Parameters
    ----------
    grid:
        Pixel grid from :func:`load_png_tkinter` or :func:`load_bmp`.
    mode:
        One of ``'threshold'``, ``'floyd-steinberg'``, or ``'jarvis'``.
    threshold:
        0.0–1.0 grayscale threshold (pixels below = engrave).
    power:
        Laser power for engraved pixels (S value 0–1000).
    speed:
        Feed rate (mm/min).
    pixel_size:
        Side length of one pixel in mm (default 0.1 mm ≈ 254 DPI).
    """
    gray = to_grayscale(grid)

    mode_lower = mode.lower()
    if mode_lower in ("floyd-steinberg", "floyd_steinberg"):
        bitmap = _dither_floyd_steinberg(gray, threshold)
    elif mode_lower == "jarvis":
        bitmap = _dither_jarvis(gray, threshold)
    else:
        bitmap = _dither_threshold(gray, threshold)

    return _binary_to_gcode(bitmap, power, speed, pixel_size)
