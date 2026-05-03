"""SVG importer for the Ray5W laser control.

Converts SVG vector graphics to GRBL G-code.  Uses only the Python
standard library (``xml.etree.ElementTree``).

Supported elements
------------------
``<path>``
    Full SVG path data (M/L/H/V/C/Q/A/Z and lower-case relative forms).
    Cubic and quadratic Béziers are approximated as line segments.
    Elliptical arcs are converted to polyline approximations.

``<rect>``, ``<circle>``, ``<ellipse>``, ``<line>``,
``<polyline>``, ``<polygon>``
    Shapes are converted to equivalent paths.

``<g>``
    Group elements with ``transform`` attributes are traversed
    recursively; transforms are applied cumulatively.

Transforms
----------
``translate(tx[,ty])``, ``scale(sx[,sy])``, ``rotate(a[,cx,cy])``,
``skewX(a)``, ``skewY(a)``, and ``matrix(a,b,c,d,e,f)`` are all
handled.

Coordinate system
-----------------
SVG uses pixels at 96 DPI by default (1 px = 25.4/96 ≈ 0.265 mm).
The *scale_to_mm* parameter (default True) converts pixels to mm.
The SVG Y-axis points downward; the output G-code is *not* flipped so
that the burn canvas (which already flips Y) renders it correctly.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

from ..design import DesignPath, paths_to_gcode


# 1 SVG pixel at 96 dpi → mm
_PX_TO_MM = 25.4 / 96.0

# Namespace prefix stripping regex
_NS_RE = re.compile(r"\{[^}]*\}")

# ---------------------------------------------------------------------------
# Transform helpers
# ---------------------------------------------------------------------------

# A 2-D affine transform is a 3×3 matrix stored as a flat tuple of 6 floats:
# (a, b, c, d, e, f)  applied as:
#   x' = a*x + c*y + e
#   y' = b*x + d*y + f
# This matches the SVG matrix() convention.

_IDENTITY: Tuple[float, ...] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

def _mul_transform(
    t1: Tuple[float, ...],
    t2: Tuple[float, ...],
) -> Tuple[float, ...]:
    """Concatenate two 2-D affine transforms (t1 applied after t2)."""
    a1, b1, c1, d1, e1, f1 = t1
    a2, b2, c2, d2, e2, f2 = t2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _apply_transform(
    x: float,
    y: float,
    t: Tuple[float, ...],
) -> Tuple[float, float]:
    a, b, c, d, e, f = t
    return a * x + c * y + e, b * x + d * y + f


_NUM_LIST_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")

def _nums(s: str) -> List[float]:
    return [float(m) for m in _NUM_LIST_RE.findall(s)]


def _parse_transform(attr: str) -> Tuple[float, ...]:
    """Parse an SVG transform attribute string into a 6-tuple affine matrix."""
    result = _IDENTITY
    for m in re.finditer(
        r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)", attr
    ):
        cmd = m.group(1)
        vals = _nums(m.group(2))
        if cmd == "matrix" and len(vals) >= 6:
            t = tuple(vals[:6])
        elif cmd == "translate":
            tx = vals[0] if vals else 0.0
            ty = vals[1] if len(vals) >= 2 else 0.0
            t = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif cmd == "scale":
            sx = vals[0] if vals else 1.0
            sy = vals[1] if len(vals) >= 2 else sx
            t = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif cmd == "rotate":
            ang = math.radians(vals[0]) if vals else 0.0
            ca, sa = math.cos(ang), math.sin(ang)
            if len(vals) >= 3:
                cx, cy = vals[1], vals[2]
                t = (
                    ca, sa, -sa, ca,
                    cx - cx * ca + cy * sa,
                    cy - cx * sa - cy * ca,
                )
            else:
                t = (ca, sa, -sa, ca, 0.0, 0.0)
        elif cmd == "skewX":
            ang = math.radians(vals[0]) if vals else 0.0
            t = (1.0, 0.0, math.tan(ang), 1.0, 0.0, 0.0)
        elif cmd == "skewY":
            ang = math.radians(vals[0]) if vals else 0.0
            t = (1.0, math.tan(ang), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        result = _mul_transform(result, t)
    return result


# ---------------------------------------------------------------------------
# SVG path data parser
# ---------------------------------------------------------------------------

_PATH_CMD_RE = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])")
_PATH_NUM_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def _parse_path_d(d: str) -> List[List[Tuple[float, float]]]:
    """Parse SVG path ``d`` attribute into a list of sub-paths.

    Each sub-path is a list of (x, y) points; curves are approximated
    with line segments.
    """
    tokens = _PATH_CMD_RE.split(d)
    commands: List[Tuple[str, List[float]]] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i].strip()
        if not tok:
            i += 1
            continue
        if _PATH_CMD_RE.match(tok):
            nums: List[float] = []
            if i + 1 < len(tokens):
                nums = [float(m.group()) for m in _PATH_NUM_RE.finditer(tokens[i + 1])]
                i += 1
            commands.append((tok, nums))
        i += 1

    subpaths: List[List[Tuple[float, float]]] = []
    current: List[Tuple[float, float]] = []
    cx, cy = 0.0, 0.0   # current position
    start_x, start_y = 0.0, 0.0  # path start (for Z)
    last_ctrl: Optional[Tuple[float, float]] = None  # for S/T

    def _flush():
        nonlocal current
        if current:
            subpaths.append(current)
        current = []

    def _bezier_cubic(
        x0: float, y0: float,
        x1: float, y1: float,
        x2: float, y2: float,
        x3: float, y3: float,
        n: int = 12,
    ) -> List[Tuple[float, float]]:
        pts = []
        for k in range(1, n + 1):
            t = k / n
            u = 1 - t
            bx = u**3*x0 + 3*u**2*t*x1 + 3*u*t**2*x2 + t**3*x3
            by = u**3*y0 + 3*u**2*t*y1 + 3*u*t**2*y2 + t**3*y3
            pts.append((bx, by))
        return pts

    def _bezier_quadratic(
        x0: float, y0: float,
        x1: float, y1: float,
        x2: float, y2: float,
        n: int = 8,
    ) -> List[Tuple[float, float]]:
        pts = []
        for k in range(1, n + 1):
            t = k / n
            u = 1 - t
            bx = u**2*x0 + 2*u*t*x1 + t**2*x2
            by = u**2*y0 + 2*u*t*y1 + t**2*y2
            pts.append((bx, by))
        return pts

    def _arc_to_points(
        x0: float, y0: float,
        rx: float, ry: float,
        x_rot: float,
        large_arc: bool,
        sweep: bool,
        x1: float, y1: float,
        n: int = 16,
    ) -> List[Tuple[float, float]]:
        """Convert SVG arc to a list of (x,y) points."""
        if abs(x0 - x1) < 1e-9 and abs(y0 - y1) < 1e-9:
            return []
        if abs(rx) < 1e-9 or abs(ry) < 1e-9:
            return [(x1, y1)]
        phi = math.radians(x_rot)
        cos_phi, sin_phi = math.cos(phi), math.sin(phi)
        dx = (x0 - x1) / 2
        dy = (y0 - y1) / 2
        x1p = cos_phi * dx + sin_phi * dy
        y1p = -sin_phi * dx + cos_phi * dy
        rx, ry = abs(rx), abs(ry)
        lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
        if lam > 1:
            s = math.sqrt(lam)
            rx *= s
            ry *= s
        num = max(0.0, rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2)
        den = rx**2 * y1p**2 + ry**2 * x1p**2
        sq = math.sqrt(num / den) if den > 1e-12 else 0.0
        if large_arc == sweep:
            sq = -sq
        cxp = sq * rx * y1p / ry
        cyp = -sq * ry * x1p / rx
        mx = (x0 + x1) / 2
        my = (y0 + y1) / 2
        ccx = cos_phi * cxp - sin_phi * cyp + mx
        ccy = sin_phi * cxp + cos_phi * cyp + my

        def _angle(ux, uy, vx, vy):
            n1 = math.hypot(ux, uy)
            n2 = math.hypot(vx, vy)
            if n1 < 1e-12 or n2 < 1e-12:
                return 0.0
            dot = (ux * vx + uy * vy) / (n1 * n2)
            dot = max(-1.0, min(1.0, dot))
            ang = math.acos(dot)
            if ux * vy - uy * vx < 0:
                ang = -ang
            return ang

        theta1 = _angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
        d_theta = _angle(
            (x1p - cxp) / rx, (y1p - cyp) / ry,
            (-x1p - cxp) / rx, (-y1p - cyp) / ry,
        )
        if not sweep and d_theta > 0:
            d_theta -= 2 * math.pi
        elif sweep and d_theta < 0:
            d_theta += 2 * math.pi

        pts = []
        for k in range(1, n + 1):
            t = k / n
            ang = theta1 + t * d_theta
            xr = rx * math.cos(ang)
            yr = ry * math.sin(ang)
            pts.append((
                cos_phi * xr - sin_phi * yr + ccx,
                sin_phi * xr + cos_phi * yr + ccy,
            ))
        return pts

    for cmd, args in commands:
        rel = cmd.islower()
        c = cmd.upper()
        last_ctrl = None if c not in ("C", "S", "Q", "T") else last_ctrl

        if c == "M":
            _flush()
            pairs = [(args[k], args[k + 1]) for k in range(0, len(args) - 1, 2)]
            if pairs:
                if rel and current:
                    cx += pairs[0][0]; cy += pairs[0][1]
                elif rel:
                    cx += pairs[0][0]; cy += pairs[0][1]
                else:
                    cx, cy = pairs[0]
                start_x, start_y = cx, cy
                current = [(cx, cy)]
                for px, py in pairs[1:]:
                    if rel:
                        cx += px; cy += py
                    else:
                        cx, cy = px, py
                    current.append((cx, cy))
        elif c == "L":
            pairs = [(args[k], args[k + 1]) for k in range(0, len(args) - 1, 2)]
            for px, py in pairs:
                if rel:
                    cx += px; cy += py
                else:
                    cx, cy = px, py
                current.append((cx, cy))
        elif c == "H":
            for v in args:
                cx = cx + v if rel else v
                current.append((cx, cy))
        elif c == "V":
            for v in args:
                cy = cy + v if rel else v
                current.append((cx, cy))
        elif c == "Z":
            current.append((start_x, start_y))
            subpaths.append(current)
            current = [(start_x, start_y)]
            cx, cy = start_x, start_y
        elif c == "C":
            for k in range(0, len(args) - 5, 6):
                x1, y1, x2, y2, x3, y3 = args[k:k + 6]
                if rel:
                    x1 += cx; y1 += cy
                    x2 += cx; y2 += cy
                    x3 += cx; y3 += cy
                last_ctrl = (x2, y2)
                pts = _bezier_cubic(cx, cy, x1, y1, x2, y2, x3, y3)
                current.extend(pts)
                cx, cy = x3, y3
        elif c == "S":
            for k in range(0, len(args) - 3, 4):
                x2, y2, x3, y3 = args[k:k + 4]
                if rel:
                    x2 += cx; y2 += cy
                    x3 += cx; y3 += cy
                if last_ctrl is not None:
                    x1 = 2 * cx - last_ctrl[0]
                    y1 = 2 * cy - last_ctrl[1]
                else:
                    x1, y1 = cx, cy
                last_ctrl = (x2, y2)
                pts = _bezier_cubic(cx, cy, x1, y1, x2, y2, x3, y3)
                current.extend(pts)
                cx, cy = x3, y3
        elif c == "Q":
            for k in range(0, len(args) - 3, 4):
                x1, y1, x2, y2 = args[k:k + 4]
                if rel:
                    x1 += cx; y1 += cy
                    x2 += cx; y2 += cy
                last_ctrl = (x1, y1)
                pts = _bezier_quadratic(cx, cy, x1, y1, x2, y2)
                current.extend(pts)
                cx, cy = x2, y2
        elif c == "T":
            for k in range(0, len(args) - 1, 2):
                x2, y2 = args[k], args[k + 1]
                if rel:
                    x2 += cx; y2 += cy
                if last_ctrl is not None:
                    x1 = 2 * cx - last_ctrl[0]
                    y1 = 2 * cy - last_ctrl[1]
                else:
                    x1, y1 = cx, cy
                last_ctrl = (x1, y1)
                pts = _bezier_quadratic(cx, cy, x1, y1, x2, y2)
                current.extend(pts)
                cx, cy = x2, y2
        elif c == "A":
            for k in range(0, len(args) - 6, 7):
                rx, ry, x_rot, la, sw, x2, y2 = args[k:k + 7]
                if rel:
                    x2 += cx; y2 += cy
                pts = _arc_to_points(cx, cy, rx, ry, x_rot,
                                     bool(la), bool(sw), x2, y2)
                current.extend(pts)
                cx, cy = x2, y2

    _flush()
    return subpaths


# ---------------------------------------------------------------------------
# Shape element helpers
# ---------------------------------------------------------------------------

def _circle_points(
    cx: float, cy: float, r: float, n: int = 36,
) -> List[Tuple[float, float]]:
    return [
        (cx + r * math.cos(2 * math.pi * i / n),
         cy + r * math.sin(2 * math.pi * i / n))
        for i in range(n + 1)
    ]


def _ellipse_points(
    cx: float, cy: float, rx: float, ry: float, n: int = 36,
) -> List[Tuple[float, float]]:
    return [
        (cx + rx * math.cos(2 * math.pi * i / n),
         cy + ry * math.sin(2 * math.pi * i / n))
        for i in range(n + 1)
    ]


# ---------------------------------------------------------------------------
# Main importer
# ---------------------------------------------------------------------------

def _tag(elem: ET.Element) -> str:
    """Return local tag name (strip namespace)."""
    return _NS_RE.sub("", elem.tag)


def _collect_paths(
    elem: ET.Element,
    transform: Tuple[float, ...],
    scale: float,
    power: float,
    speed: float,
    passes: int,
) -> List[DesignPath]:
    """Recursively collect DesignPath objects from an SVG element tree."""
    tag = _tag(elem)
    attr = elem.attrib

    # Accumulate transform
    if "transform" in attr:
        t = _parse_transform(attr["transform"])
        transform = _mul_transform(transform, t)

    results: List[DesignPath] = []

    # Helper: apply current transform + scale to all points
    def _pts(subpath: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        out = []
        for x, y in subpath:
            tx, ty = _apply_transform(x, y, transform)
            out.append((tx * scale, ty * scale))
        return out

    if tag == "path":
        d = attr.get("d", "")
        for sub in _parse_path_d(d):
            if sub:
                results.append(DesignPath(_pts(sub), False, power, speed, passes))

    elif tag == "rect":
        x = float(attr.get("x", 0))
        y = float(attr.get("y", 0))
        w = float(attr.get("width", 0))
        h = float(attr.get("height", 0))
        rx = float(attr.get("rx", 0))
        ry_val = float(attr.get("ry", rx))
        if rx > 0 or ry_val > 0:
            # Rounded rect – approximate corners
            r = min(rx, ry_val, w / 2, h / 2)
            pts: List[Tuple[float, float]] = []
            pts.append((x + r, y))
            pts.append((x + w - r, y))
            _tr_ellipse = _ellipse_points(x + w - r, y + r, r, r, 8)
            n4 = len(_tr_ellipse) // 4
            pts.extend(_tr_ellipse[n4 : len(_tr_ellipse) // 2 + 1])
            pts.append((x + w, y + h - r))
            pts.extend([(x + w - r + r * math.cos(a), y + h - r + r * math.sin(a))
                        for a in [math.pi * k / 8 for k in range(0, 5)]])
            pts.append((x + r, y + h))
            pts.extend([(x + r + r * math.cos(a), y + h - r + r * math.sin(a))
                        for a in [math.pi * (4 + k) / 8 for k in range(0, 5)]])
            pts.append((x, y + r))
            pts.extend([(x + r + r * math.cos(a), y + r + r * math.sin(a))
                        for a in [math.pi * (8 + k) / 8 for k in range(0, 5)]])
            pts.append((x + r, y))
        else:
            pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
        results.append(DesignPath(_pts(pts), True, power, speed, passes))

    elif tag == "circle":
        cx = float(attr.get("cx", 0))
        cy_val = float(attr.get("cy", 0))
        r = float(attr.get("r", 0))
        pts = _circle_points(cx, cy_val, r)
        results.append(DesignPath(_pts(pts), True, power, speed, passes))

    elif tag == "ellipse":
        cx = float(attr.get("cx", 0))
        cy_val = float(attr.get("cy", 0))
        rx_e = float(attr.get("rx", 0))
        ry_e = float(attr.get("ry", 0))
        pts = _ellipse_points(cx, cy_val, rx_e, ry_e)
        results.append(DesignPath(_pts(pts), True, power, speed, passes))

    elif tag == "line":
        x1 = float(attr.get("x1", 0))
        y1 = float(attr.get("y1", 0))
        x2 = float(attr.get("x2", 0))
        y2 = float(attr.get("y2", 0))
        results.append(DesignPath(_pts([(x1, y1), (x2, y2)]),
                                  False, power, speed, passes))

    elif tag in ("polyline", "polygon"):
        raw = attr.get("points", "")
        nums = _nums(raw)
        pts = [(nums[k], nums[k + 1]) for k in range(0, len(nums) - 1, 2)]
        closed = (tag == "polygon")
        results.append(DesignPath(_pts(pts), closed, power, speed, passes))

    # Recurse into groups and SVG root
    if tag in ("g", "svg", "symbol", "defs"):
        for child in elem:
            results.extend(
                _collect_paths(child, transform, scale, power, speed, passes)
            )

    return results


def import_svg(
    source: str,
    power: float = 500.0,
    speed: float = 3000.0,
    passes: int = 1,
    scale_to_mm: bool = True,
) -> str:
    """Parse an SVG string and return GRBL G-code.

    Parameters
    ----------
    source:
        SVG file content as a string.
    power:
        Default laser power (S value, 0–1000).
    speed:
        Default feed rate (mm/min).
    passes:
        Number of passes per path.
    scale_to_mm:
        When ``True`` (default) convert SVG pixels (96 dpi) to mm.
    """
    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        raise ValueError(f"SVG parse error: {exc}") from exc

    scale = _PX_TO_MM if scale_to_mm else 1.0
    paths = _collect_paths(root, _IDENTITY, scale, power, speed, passes)
    return paths_to_gcode(paths, power, speed, passes)
