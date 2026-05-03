"""Design operations for the Ray5W laser control.

Provides:
  - :class:`DesignPath` – an ordered list of (x, y) waypoints with laser
    settings attached.
  - :func:`offset_path` – expand / shrink a closed polygon by a distance
    (kerf compensation).
  - :func:`array_path` – tile a path in an N×M rectangular grid.
  - :func:`nest_paths` – simple shelf-based nesting to minimise material
    waste on a rectangular sheet.
  - :func:`boolean_union` – combine two path collections.
  - :func:`boolean_difference` – Sutherland-Hodgman clip (subtract one
    polygon from another).
  - :func:`paths_to_gcode` – serialise :class:`DesignPath` objects to
    GRBL G-code text.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DesignPath:
    """A single design path with attached laser settings."""

    points: List[Tuple[float, float]] = field(default_factory=list)
    closed: bool = False
    power: float = 500.0    # S value 0–1000
    speed: float = 3000.0   # F value mm/min
    passes: int = 1


def _bbox(path: DesignPath) -> Tuple[float, float, float, float]:
    """Return (min_x, min_y, max_x, max_y) bounding box of *path*."""
    if not path.points:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [p[0] for p in path.points]
    ys = [p[1] for p in path.points]
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# Offset (kerf compensation)
# ---------------------------------------------------------------------------

def _offset_segment(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    dist: float,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Return segment p1→p2 shifted perpendicularly by *dist*.

    The outward normal for a CCW polygon is (dy, -dx)/length.
    Positive *dist* expands a CCW polygon outward.
    """
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return p1, p2
    nx = dy / length * dist
    ny = -dx / length * dist
    return (p1[0] + nx, p1[1] + ny), (p2[0] + nx, p2[1] + ny)


def _line_intersect(
    a1: Tuple[float, float], a2: Tuple[float, float],
    b1: Tuple[float, float], b2: Tuple[float, float],
) -> Optional[Tuple[float, float]]:
    """Intersection of infinite lines a1-a2 and b1-b2; ``None`` if parallel."""
    d1x = a2[0] - a1[0]
    d1y = a2[1] - a1[1]
    d2x = b2[0] - b1[0]
    d2y = b2[1] - b1[1]
    denom = d1x * d2y - d1y * d2x
    if abs(denom) < 1e-9:
        return None
    t = ((b1[0] - a1[0]) * d2y - (b1[1] - a1[1]) * d2x) / denom
    return (a1[0] + t * d1x, a1[1] + t * d1y)


def offset_path(path: DesignPath, dist: float) -> DesignPath:
    """Return a new :class:`DesignPath` offset outward by *dist* mm.

    Positive *dist* expands; negative shrinks.  Only meaningful for
    closed polygonal paths.
    """
    pts = path.points
    n = len(pts)
    if n < 2:
        return DesignPath(list(pts), path.closed,
                          path.power, path.speed, path.passes)

    # Offset each edge
    segs = [_offset_segment(pts[i], pts[i + 1], dist) for i in range(n - 1)]
    if path.closed and n >= 3:
        segs.append(_offset_segment(pts[-1], pts[0], dist))

    # Miter join: intersect adjacent offset edges to find new vertices
    new_pts: List[Tuple[float, float]] = []
    m = len(segs)
    for i in range(m):
        s1 = segs[i]
        s2 = segs[(i + 1) % m]
        pt = _line_intersect(s1[0], s1[1], s2[0], s2[1])
        new_pts.append(pt if pt is not None else s1[1])

    if not path.closed:
        new_pts = [segs[0][0]] + new_pts + [segs[-1][1]]

    return DesignPath(new_pts, path.closed,
                      path.power, path.speed, path.passes)


# ---------------------------------------------------------------------------
# Array / grid
# ---------------------------------------------------------------------------

def array_path(
    path: DesignPath,
    cols: int,
    rows: int,
    x_spacing: float,
    y_spacing: float,
) -> List[DesignPath]:
    """Return a *cols* × *rows* grid of copies of *path*.

    *x_spacing* and *y_spacing* are centre-to-centre distances in mm.
    Pass ``x_spacing = bbox_width + gap`` to space by gap.
    """
    results: List[DesignPath] = []
    for row in range(rows):
        for col in range(cols):
            dx = col * x_spacing
            dy = row * y_spacing
            shifted = [(x + dx, y + dy) for x, y in path.points]
            results.append(
                DesignPath(shifted, path.closed,
                           path.power, path.speed, path.passes)
            )
    return results


# ---------------------------------------------------------------------------
# Nesting (simple shelf algorithm on bounding boxes)
# ---------------------------------------------------------------------------

def nest_paths(
    paths: List[DesignPath],
    sheet_width: float,
    sheet_height: float,
    gap: float = 1.0,
) -> List[DesignPath]:
    """Arrange *paths* onto a sheet using a simple shelf-first-fit algorithm.

    Returns a new list of :class:`DesignPath` objects with coordinates
    translated so they fit on the sheet (width × height, mm).  Paths that
    do not fit are appended untranslated at the end.

    This is a bounding-box approximation; actual shape nesting requires
    a more sophisticated no-fit polygon algorithm.
    """
    result: List[DesignPath] = []
    shelf_x = gap
    shelf_y = gap
    shelf_h = 0.0

    for path in paths:
        bx0, by0, bx1, by1 = _bbox(path)
        w = bx1 - bx0 + gap
        h = by1 - by0 + gap

        if w > sheet_width:
            # Shape wider than sheet – place as-is
            result.append(path)
            continue

        # Try current shelf
        if shelf_x + w > sheet_width:
            # Move to next shelf
            shelf_x = gap
            shelf_y += shelf_h + gap
            shelf_h = 0.0

        if shelf_y + h > sheet_height:
            # Doesn't fit on sheet
            result.append(path)
            continue

        dx = shelf_x - bx0
        dy = shelf_y - by0
        shifted = [(x + dx, y + dy) for x, y in path.points]
        result.append(
            DesignPath(shifted, path.closed,
                       path.power, path.speed, path.passes)
        )
        shelf_x += w
        shelf_h = max(shelf_h, h)

    return result


# ---------------------------------------------------------------------------
# Boolean operations
# ---------------------------------------------------------------------------

def boolean_union(
    paths_a: List[DesignPath],
    paths_b: List[DesignPath],
) -> List[DesignPath]:
    """Return the union of two path collections (simple concatenation)."""
    return list(paths_a) + list(paths_b)


def _inside_edge(
    p: Tuple[float, float],
    edge_s: Tuple[float, float],
    edge_e: Tuple[float, float],
) -> bool:
    """Return True if *p* is on the left side of directed edge s→e."""
    return (
        (edge_e[0] - edge_s[0]) * (p[1] - edge_s[1])
        - (edge_e[1] - edge_s[1]) * (p[0] - edge_s[0])
    ) >= 0.0


def boolean_difference(
    subject: DesignPath,
    clip_polygon: DesignPath,
) -> List[DesignPath]:
    """Sutherland-Hodgman clip – keep the part of *subject* inside
    *clip_polygon*.

    Note: this returns the *intersection*, not the set-difference, because
    full polygon difference requires a more complex algorithm.  For a true
    difference (subject minus clip) use two separate clip passes or rely on
    the G-code layer ordering instead.
    """
    subj_pts = list(subject.points)
    clip_pts = list(clip_polygon.points)

    if len(subj_pts) < 3 or len(clip_pts) < 3:
        return [subject]

    output = subj_pts
    n = len(clip_pts)

    for i in range(n):
        if not output:
            break
        input_list = output
        output = []
        edge_s = clip_pts[i]
        edge_e = clip_pts[(i + 1) % n]

        for k in range(len(input_list)):
            current = input_list[k]
            prev = input_list[k - 1]
            if _inside_edge(current, edge_s, edge_e):
                if not _inside_edge(prev, edge_s, edge_e):
                    pt = _line_intersect(prev, current, edge_s, edge_e)
                    if pt:
                        output.append(pt)
                output.append(current)
            elif _inside_edge(prev, edge_s, edge_e):
                pt = _line_intersect(prev, current, edge_s, edge_e)
                if pt:
                    output.append(pt)

    if not output:
        return []
    return [DesignPath(output, True,
                       subject.power, subject.speed, subject.passes)]


# ---------------------------------------------------------------------------
# G-code generation from design paths
# ---------------------------------------------------------------------------

def paths_to_gcode(
    paths: List[DesignPath],
    power: Optional[float] = None,
    speed: Optional[float] = None,
    passes: Optional[int] = None,
) -> str:
    """Serialise *paths* to GRBL G-code.

    Global *power*, *speed*, and *passes* override per-path values when set.
    """
    lines = ["G21 G90  ; metric, absolute", "M5       ; laser off initially", ""]

    for path in paths:
        p_power = power if power is not None else path.power
        p_speed = speed if speed is not None else path.speed
        p_passes = passes if passes is not None else path.passes

        pts = path.points
        if not pts:
            continue

        for _pass in range(p_passes):
            sx, sy = pts[0]
            lines.append(f"G0 X{sx:.4f} Y{sy:.4f}")
            lines.append(f"M3 S{p_power:.0f}")
            for x, y in pts[1:]:
                lines.append(f"G1 X{x:.4f} Y{y:.4f} F{p_speed:.0f}")
            if path.closed and len(pts) > 1:
                lines.append(
                    f"G1 X{pts[0][0]:.4f} Y{pts[0][1]:.4f} F{p_speed:.0f}"
                    "  ; close"
                )
            lines.append("M5")

    lines.extend(["", "G0 X0 Y0", "M2"])
    return "\n".join(lines)
