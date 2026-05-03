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
import re
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


# ---------------------------------------------------------------------------
# Hatch fill
# ---------------------------------------------------------------------------

def _line_bbox_clip(
    px: float,
    py: float,
    dx: float,
    dy: float,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> Optional[Tuple[float, float, float, float]]:
    """Clip the infinite line (px + t*dx, py + t*dy) to a bounding box.

    Returns ``(sx, sy, ex, ey)`` or ``None`` if the line misses the box.
    """
    t_min = float("-inf")
    t_max = float("inf")
    for p, d, b0, b1 in ((px, dx, x0, x1), (py, dy, y0, y1)):
        if abs(d) < 1e-12:
            if p < b0 - 1e-9 or p > b1 + 1e-9:
                return None  # parallel and outside
        else:
            ta = (b0 - p) / d
            tb = (b1 - p) / d
            t_min = max(t_min, min(ta, tb))
            t_max = min(t_max, max(ta, tb))
    if t_min > t_max + 1e-9:
        return None
    return (px + t_min * dx, py + t_min * dy,
            px + t_max * dx, py + t_max * dy)


def hatch_fill(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    angle: float = 45.0,
    spacing: float = 0.2,
    power: float = 500.0,
    speed: float = 3000.0,
    crosshatch: bool = False,
) -> str:
    """Generate a hatch-fill raster over a bounding box.

    Lines are drawn at *angle* degrees from horizontal (0 = horizontal,
    90 = vertical, 45 = diagonal).  If *crosshatch* is ``True`` a second
    perpendicular pass is appended.

    Parameters
    ----------
    x0, y0 : float
        Bottom-left corner (mm).
    x1, y1 : float
        Top-right corner (mm).
    angle : float
        Hatch angle in degrees.
    spacing : float
        Distance between hatch lines (mm).
    power : float
        Laser S value (0–1000).
    speed : float
        Feed rate (mm/min).
    crosshatch : bool
        When ``True`` append a second pass at *angle* + 90°.
    """
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    if spacing <= 0:
        spacing = 0.2

    s = int(round(max(0.0, min(1000.0, power))))
    lines: List[str] = [
        f"; hatch_fill angle={angle:.0f} spacing={spacing}",
        "G21 G90",
        f"F{int(speed)}",
    ]

    def _pass(angle_deg: float) -> None:
        rad = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        # Normal to the line direction
        nx = -sin_a
        ny = cos_a
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        projs = [nx * cx + ny * cy for cx, cy in corners]
        n_min = min(projs)
        n_max = max(projs)
        n_lines = max(1, int(math.ceil((n_max - n_min) / spacing))) + 1
        for i in range(n_lines):
            n_pos = n_min + i * spacing
            if n_pos > n_max + 1e-9:
                break
            # Point on normal at distance n_pos from origin
            px = nx * n_pos
            py = ny * n_pos
            clip = _line_bbox_clip(px, py, cos_a, sin_a, x0, y0, x1, y1)
            if clip is None:
                continue
            sx, sy, ex, ey = clip
            if i % 2 == 0:
                lines.append(f"G0 X{sx:.4f} Y{sy:.4f}")
                lines.append(f"M3 S{s}")
                lines.append(f"G1 X{ex:.4f} Y{ey:.4f}")
            else:
                lines.append(f"G0 X{ex:.4f} Y{ey:.4f}")
                lines.append(f"M3 S{s}")
                lines.append(f"G1 X{sx:.4f} Y{sy:.4f}")
            lines.append("M5")

    _pass(angle)
    if crosshatch:
        _pass(angle + 90.0)

    lines.append(f"G0 X{x0:.4f} Y{y0:.4f}")
    lines.append("M2")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Spiral toolpath
# ---------------------------------------------------------------------------

def spiral_fill(
    cx: float,
    cy: float,
    r_start: float,
    r_end: float,
    spacing: float = 0.5,
    power: float = 500.0,
    speed: float = 3000.0,
    segments_per_turn: int = 36,
) -> str:
    """Generate an Archimedean spiral toolpath.

    The spiral starts at radius *r_start* from (*cx*, *cy*) and expands
    outward to *r_end*, stepping by *spacing* per full revolution.

    Parameters
    ----------
    cx, cy : float
        Centre of the spiral (mm).
    r_start : float
        Inner radius (mm).
    r_end : float
        Outer radius (mm, must be > *r_start*).
    spacing : float
        Radial gap between successive turns (mm).
    power : float
        Laser S value (0–1000).
    speed : float
        Feed rate (mm/min).
    segments_per_turn : int
        Number of linear segments per full revolution.
    """
    if r_start < 0:
        r_start = 0.0
    if r_end <= r_start:
        r_end = r_start + max(spacing, 0.1)
    if spacing <= 0:
        spacing = 0.5
    n_turns = (r_end - r_start) / spacing
    total_angle = n_turns * 2.0 * math.pi
    total_segments = max(12, int(round(n_turns * segments_per_turn)))

    s = int(round(max(0.0, min(1000.0, power))))
    lines: List[str] = [
        "; spiral_fill",
        "G21 G90",
        f"F{int(speed)}",
        f"G0 X{cx + r_start:.4f} Y{cy:.4f}",
        f"M3 S{s}",
    ]

    for i in range(1, total_segments + 1):
        theta = total_angle * i / total_segments
        r = r_start + (r_end - r_start) * theta / total_angle
        x = cx + r * math.cos(theta)
        y = cy + r * math.sin(theta)
        lines.append(f"G1 X{x:.4f} Y{y:.4f}")

    lines.append("M5")
    lines.append(f"G0 X{cx:.4f} Y{cy:.4f}")
    lines.append("M2")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Perforation (dashed cuts)
# ---------------------------------------------------------------------------

_GCODE_COORD_RE = re.compile(r"([XYFI])([+-]?[\d.]+)", re.IGNORECASE)


def _parse_gcode_coords(
    line: str,
    cur_x: float,
    cur_y: float,
    cur_f: float,
) -> Tuple[float, float, float]:
    """Extract X, Y, F values from a G-code line, defaulting to current."""
    x, y, f = cur_x, cur_y, cur_f
    for m in _GCODE_COORD_RE.finditer(line):
        key = m.group(1).upper()
        val = float(m.group(2))
        if key == "X":
            x = val
        elif key == "Y":
            y = val
        elif key == "F":
            f = val
    return x, y, f


def perforation_to_dashes(
    gcode: str,
    dash_mm: float = 2.0,
    gap_mm: float = 1.0,
) -> str:
    """Convert continuous G1 cut moves into alternating dash / gap segments.

    Processes *gcode* line by line.  Each G1 move while the laser is on
    is split into alternating fired segments of *dash_mm* mm and
    un-fired gaps of *gap_mm* mm.

    The dash/gap phase is preserved across consecutive G1 moves so that
    the perforation pattern is continuous along a path.

    Parameters
    ----------
    gcode : str
        Input G-code string.
    dash_mm : float
        Length of each fired segment (mm).
    gap_mm : float
        Length of each un-fired gap (mm).
    """
    if dash_mm <= 0:
        dash_mm = 2.0
    if gap_mm <= 0:
        gap_mm = 1.0

    output: List[str] = []
    cur_x = 0.0
    cur_y = 0.0
    cur_f = 1000.0
    laser_on = False
    in_dash = True            # True = currently in a fired dash
    remaining = dash_mm       # mm remaining in the current segment

    for raw in gcode.splitlines():
        stripped = raw.strip().upper()
        cmd = stripped.split(";")[0].strip()  # drop inline comments

        if not cmd:
            output.append(raw)
            continue

        # Laser on/off
        if cmd.startswith("M3"):
            laser_on = True
            in_dash = True
            remaining = dash_mm
            output.append(raw)
            continue
        if cmd.startswith("M5"):
            laser_on = False
            output.append(raw)
            continue

        # Only split G1 moves when laser is on
        if (cmd.startswith("G1") or cmd.startswith("G 1")) and laser_on:
            tgt_x, tgt_y, new_f = _parse_gcode_coords(raw, cur_x, cur_y, cur_f)
            if new_f != cur_f:
                cur_f = new_f
            dx = tgt_x - cur_x
            dy = tgt_y - cur_y
            seg_len = math.hypot(dx, dy)

            if seg_len < 1e-9:
                output.append(raw)
                cur_x, cur_y = tgt_x, tgt_y
                continue

            # Split into dash/gap pieces
            pos = 0.0
            while pos < seg_len - 1e-9:
                piece = min(remaining, seg_len - pos)
                end_pos = pos + piece
                t = end_pos / seg_len
                ex = cur_x + dx * t
                ey = cur_y + dy * t

                if in_dash:
                    output.append(f"G1 X{ex:.4f} Y{ey:.4f} F{int(cur_f)}")
                else:
                    output.append("M5")
                    output.append(f"G0 X{ex:.4f} Y{ey:.4f}")
                    output.append(f"M3 S500")

                remaining -= piece
                pos = end_pos
                if remaining < 1e-9:
                    in_dash = not in_dash
                    remaining = dash_mm if in_dash else gap_mm

            cur_x, cur_y = tgt_x, tgt_y
            continue

        # G0 – update position, pass through
        if cmd.startswith("G0") or cmd.startswith("G 0"):
            cur_x, cur_y, cur_f = _parse_gcode_coords(raw, cur_x, cur_y, cur_f)

        output.append(raw)

    return "\n".join(output)
