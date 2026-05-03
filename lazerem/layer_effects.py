"""Layer effects for the Ray5W laser control.

Provides G-code generators for advanced per-layer laser effects:

* :func:`gradient_fill` – horizontal scan lines with power ramping
  linearly from one side of a bounding box to the other.
* :func:`variable_power_curve` – follow a path while modulating the S
  value according to a user-supplied normalised curve.
* :func:`texture_fill` – fill a rectangular bounding box with a
  repeating dot/dash pattern at a specified pitch.

All functions return a G-code string ready to paste into the editor or
feed to :class:`~lazerem.machine.LaserMachine`.
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Gradient fill
# ---------------------------------------------------------------------------

def gradient_fill(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    power_start: float = 100.0,
    power_end: float = 1000.0,
    line_spacing: float = 0.1,
    speed: float = 3000.0,
    axis: str = "x",
) -> str:
    """Generate a boustrophedon gradient-fill raster.

    The power ramps linearly from *power_start* to *power_end* across
    the bounding box.  Scan lines run parallel to *axis* (``'x'`` or
    ``'y'``).

    Parameters
    ----------
    x0, y0 : float
        Bottom-left corner of the fill rectangle (mm).
    x1, y1 : float
        Top-right corner (mm).
    power_start : float
        S value at the start edge (0–1000).
    power_end : float
        S value at the far edge.
    line_spacing : float
        Distance between scan lines (mm).
    speed : float
        Feed rate (mm/min).
    axis : str
        Scan-line orientation: ``'x'`` for horizontal lines,
        ``'y'`` for vertical lines.

    Returns
    -------
    str
        GRBL-compatible G-code string.
    """
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0

    lines: List[str] = [
        "; gradient_fill",
        "G21 G90",
        f"F{int(speed)}",
    ]
    lines.append(f"G0 X{x0:.4f} Y{y0:.4f}")

    if axis == "x":
        span = y1 - y0
        n = max(1, int(math.ceil(span / line_spacing)))
        for i in range(n + 1):
            t = i / n if n > 0 else 0.0
            y = y0 + i * line_spacing
            y = min(y, y1)
            power = power_start + (power_end - power_start) * t
            s = int(round(max(0.0, min(1000.0, power))))
            if i % 2 == 0:
                lines.append(f"G0 X{x0:.4f} Y{y:.4f}")
                lines.append(f"M3 S{s}")
                lines.append(f"G1 X{x1:.4f} Y{y:.4f}")
            else:
                lines.append(f"G0 X{x1:.4f} Y{y:.4f}")
                lines.append(f"M3 S{s}")
                lines.append(f"G1 X{x0:.4f} Y{y:.4f}")
            lines.append("M5")
    else:
        span = x1 - x0
        n = max(1, int(math.ceil(span / line_spacing)))
        for i in range(n + 1):
            t = i / n if n > 0 else 0.0
            x = x0 + i * line_spacing
            x = min(x, x1)
            power = power_start + (power_end - power_start) * t
            s = int(round(max(0.0, min(1000.0, power))))
            if i % 2 == 0:
                lines.append(f"G0 X{x:.4f} Y{y0:.4f}")
                lines.append(f"M3 S{s}")
                lines.append(f"G1 X{x:.4f} Y{y1:.4f}")
            else:
                lines.append(f"G0 X{x:.4f} Y{y1:.4f}")
                lines.append(f"M3 S{s}")
                lines.append(f"G1 X{x:.4f} Y{y0:.4f}")
            lines.append("M5")

    lines.append(f"G0 X{x0:.4f} Y{y0:.4f}")
    lines.append("M2")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Variable power curve
# ---------------------------------------------------------------------------

def variable_power_curve(
    points: List[Tuple[float, float]],
    power_curve: Callable[[float], float],
    speed: float = 3000.0,
    samples: int = 100,
) -> str:
    """Follow a polyline while varying laser power according to a curve.

    *power_curve* is called with a normalised parameter ``t ∈ [0, 1]``
    representing progress along the *total arc length* of the polyline,
    and must return a power value in 0–1000.

    Parameters
    ----------
    points:
        List of ``(x, y)`` waypoints in mm.
    power_curve:
        Callable ``(t: float) -> float`` mapping path fraction to S value.
    speed:
        Feed rate mm/min.
    samples:
        Number of evenly-spaced power samples along the path.
    """
    if len(points) < 2:
        raise ValueError("Need at least 2 points")

    # Compute cumulative arc length at each waypoint
    lengths = [0.0]
    for i in range(1, len(points)):
        dx = points[i][0] - points[i - 1][0]
        dy = points[i][1] - points[i - 1][1]
        lengths.append(lengths[-1] + math.hypot(dx, dy))
    total = lengths[-1] or 1.0

    # Resample to *samples* equally-spaced points along the path
    def point_at(s: float) -> Tuple[float, float]:
        s = max(0.0, min(total, s))
        for i in range(1, len(lengths)):
            if lengths[i] >= s:
                seg_len = lengths[i] - lengths[i - 1]
                t_seg = (s - lengths[i - 1]) / seg_len if seg_len > 1e-9 else 0.0
                x = points[i - 1][0] + (points[i][0] - points[i - 1][0]) * t_seg
                y = points[i - 1][1] + (points[i][1] - points[i - 1][1]) * t_seg
                return x, y
        return points[-1]

    lines: List[str] = [
        "; variable_power_curve",
        "G21 G90",
        f"F{int(speed)}",
        f"G0 X{points[0][0]:.4f} Y{points[0][1]:.4f}",
        "M3",
    ]

    for i in range(samples + 1):
        t = i / samples
        s_val = t * total
        px, py = point_at(s_val)
        power = int(round(max(0.0, min(1000.0, power_curve(t)))))
        lines.append(f"G1 X{px:.4f} Y{py:.4f} S{power}")

    lines.append("M5")
    lines.append("M2")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Texture fill
# ---------------------------------------------------------------------------

def texture_fill(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    pattern: str = "dot",
    pitch: float = 1.0,
    power: float = 500.0,
    speed: float = 3000.0,
    dot_size: float = 0.2,
) -> str:
    """Fill a rectangle with a repeating texture pattern.

    Parameters
    ----------
    x0, y0 / x1, y1 : float
        Bounding rectangle (mm).
    pattern : str
        ``'dot'`` – square dot grid.
        ``'line'`` – horizontal dash lines.
        ``'cross'`` – plus-sign grid.
    pitch : float
        Spacing between pattern elements (mm).
    power : float
        Laser power S value (0–1000).
    speed : float
        Feed rate (mm/min).
    dot_size : float
        Size of each dot/cross element (mm).
    """
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0

    s = int(round(max(0, min(1000, power))))
    lines: List[str] = [
        f"; texture_fill pattern={pattern} pitch={pitch}",
        "G21 G90",
        f"F{int(speed)}",
        f"M3 S{s}",
    ]

    half = dot_size / 2.0

    if pattern == "dot":
        cy = y0
        while cy <= y1:
            cx = x0
            while cx <= x1:
                lines.append(f"G0 X{cx - half:.4f} Y{cy:.4f}")
                lines.append(f"G1 X{cx + half:.4f}")
                cx += pitch
            cy += pitch

    elif pattern == "line":
        cy = y0
        even = True
        while cy <= y1:
            if even:
                lines.append(f"G0 X{x0:.4f} Y{cy:.4f}")
                lines.append(f"G1 X{x1:.4f}")
            else:
                lines.append(f"G0 X{x1:.4f} Y{cy:.4f}")
                lines.append(f"G1 X{x0:.4f}")
            cy += pitch
            even = not even

    elif pattern == "cross":
        cy = y0
        while cy <= y1:
            cx = x0
            while cx <= x1:
                # Horizontal bar
                lines.append(f"G0 X{cx - half:.4f} Y{cy:.4f}")
                lines.append(f"G1 X{cx + half:.4f}")
                # Vertical bar
                lines.append(f"G0 X{cx:.4f} Y{cy - half:.4f}")
                lines.append(f"G1 Y{cy + half:.4f}")
                cx += pitch
            cy += pitch
    else:
        raise ValueError(f"Unknown texture pattern: {pattern!r}")

    lines.append("M5")
    lines.append(f"G0 X{x0:.4f} Y{y0:.4f}")
    lines.append("M2")
    return "\n".join(lines)
