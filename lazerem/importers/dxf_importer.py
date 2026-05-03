"""DXF importer for the Ray5W laser control.

Converts DXF (ASCII) files to GRBL G-code.  Uses only the Python
standard library.

Supported entity types
-----------------------
``LINE``         – Single straight line segment.
``ARC``          – Arc (centre + radius + start/end angles).
``CIRCLE``       – Full circle (approximated as a polyline).
``LWPOLYLINE``   – Lightweight polyline (AutoCAD 2000+).
``POLYLINE`` / ``VERTEX`` – Old-style polyline.
``SPLINE``       – Control points only; approximated as straight lines
                   through the control points.

DXF group codes used
--------------------
``0``   Entity type / section marker
``1``   Primary text (not used here)
``2``   Name / block name
``5``   Handle
``8``   Layer name (ignored)
``10/20/30`` – X/Y/Z of first point
``11/21/31`` – X/Y/Z of second point
``40``  Radius / bulge
``50``  Start angle (degrees)
``51``  End angle (degrees)
``70``  Flags / vertex count
``90``  Vertex count (LWPOLYLINE)

Coordinate system
-----------------
DXF coordinates are used as-is (usually mm or inches depending on the
drawing.  The importer does **not** auto-scale; set *scale* manually if
needed (e.g. 25.4 to convert inches to mm).
"""

from __future__ import annotations

import math
from typing import Dict, Iterator, List, Optional, Tuple

from ..design import DesignPath, paths_to_gcode


# ---------------------------------------------------------------------------
# DXF group-code reader
# ---------------------------------------------------------------------------

def _read_pairs(source: str) -> Iterator[Tuple[int, str]]:
    """Yield (group_code, value) pairs from ASCII DXF content."""
    lines = [ln.strip() for ln in source.splitlines()]
    i = 0
    while i + 1 < len(lines):
        code_str = lines[i]
        value = lines[i + 1]
        i += 2
        try:
            yield int(code_str), value
        except ValueError:
            continue  # skip malformed lines


def _parse_entities(source: str) -> List[Dict]:
    """Return a list of entity dicts from the ENTITIES section."""
    in_entities = False
    entities: List[Dict] = []
    current: Optional[Dict] = None

    for code, value in _read_pairs(source):
        if code == 0:
            # Save previous entity
            if current is not None:
                entities.append(current)
                current = None
            name = value.upper()
            if name == "ENDSEC":
                in_entities = False
            elif name == "SECTION":
                pass  # wait for code 2
            elif in_entities:
                current = {"type": name}
        elif code == 2 and not in_entities:
            if value.upper() == "ENTITIES":
                in_entities = True
        elif current is not None:
            # Store numeric codes as floats where possible
            try:
                current[code] = float(value)
            except ValueError:
                current[code] = value

    if current is not None:
        entities.append(current)

    return entities


# ---------------------------------------------------------------------------
# Entity → DesignPath converters
# ---------------------------------------------------------------------------

def _arc_polyline(
    cx: float, cy: float, r: float,
    start_deg: float, end_deg: float,
    n: int = 32,
) -> List[Tuple[float, float]]:
    """Return polygon approximation of an arc."""
    start_rad = math.radians(start_deg)
    end_rad = math.radians(end_deg)
    if end_rad <= start_rad:
        end_rad += 2 * math.pi
    pts: List[Tuple[float, float]] = []
    for i in range(n + 1):
        t = i / n
        ang = start_rad + t * (end_rad - start_rad)
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def _circle_polyline(
    cx: float, cy: float, r: float, n: int = 36,
) -> List[Tuple[float, float]]:
    pts = [
        (cx + r * math.cos(2 * math.pi * i / n),
         cy + r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]
    pts.append(pts[0])  # close
    return pts


def _entity_to_path(
    ent: Dict,
    power: float,
    speed: float,
    passes: int,
) -> Optional[DesignPath]:
    etype = ent.get("type", "")

    if etype == "LINE":
        x1 = ent.get(10, 0.0)
        y1 = ent.get(20, 0.0)
        x2 = ent.get(11, 0.0)
        y2 = ent.get(21, 0.0)
        return DesignPath([(x1, y1), (x2, y2)], False, power, speed, passes)

    elif etype == "ARC":
        cx = ent.get(10, 0.0)
        cy = ent.get(20, 0.0)
        r = ent.get(40, 0.0)
        s = ent.get(50, 0.0)
        e = ent.get(51, 360.0)
        pts = _arc_polyline(cx, cy, r, s, e)
        return DesignPath(pts, False, power, speed, passes)

    elif etype == "CIRCLE":
        cx = ent.get(10, 0.0)
        cy = ent.get(20, 0.0)
        r = ent.get(40, 0.0)
        pts = _circle_polyline(cx, cy, r)
        return DesignPath(pts, True, power, speed, passes)

    elif etype == "LWPOLYLINE":
        # Vertex coordinates come in as multiple 10/20 codes – collect them
        raw = ent  # we'll walk the raw pairs again below
        pts_x: List[float] = []
        pts_y: List[float] = []
        # The multi-valued codes were overwritten in the simple dict –
        # we need to re-parse.  Return None here; handled separately.
        return None

    elif etype == "SPLINE":
        # Use control points (10/20 codes) as-is
        return None  # handled in multi-value pass

    return None


# ---------------------------------------------------------------------------
# Multi-value entity collector (LWPOLYLINE, POLYLINE/VERTEX, SPLINE)
# ---------------------------------------------------------------------------

def _collect_multivalue(source: str, power: float, speed: float, passes: int) -> List[DesignPath]:
    """Collect entities that have repeated group codes (LWPOLYLINE etc.)."""
    paths: List[DesignPath] = []
    in_entities = False
    current_type: Optional[str] = None
    x_vals: List[float] = []
    y_vals: List[float] = []
    # For POLYLINE/VERTEX
    in_vertex_sequence = False
    polyline_pts: List[Tuple[float, float]] = []
    poly_closed = False
    # For SPLINE
    ctrl_x: List[float] = []
    ctrl_y: List[float] = []

    def _flush():
        nonlocal x_vals, y_vals, current_type, in_vertex_sequence
        nonlocal polyline_pts, poly_closed, ctrl_x, ctrl_y
        if current_type == "LWPOLYLINE" and x_vals:
            n = min(len(x_vals), len(y_vals))
            pts = list(zip(x_vals[:n], y_vals[:n]))
            paths.append(DesignPath(pts, poly_closed, power, speed, passes))
        elif current_type == "SPLINE" and ctrl_x:
            n = min(len(ctrl_x), len(ctrl_y))
            pts = list(zip(ctrl_x[:n], ctrl_y[:n]))
            paths.append(DesignPath(pts, False, power, speed, passes))
        x_vals = []; y_vals = []; ctrl_x = []; ctrl_y = []
        poly_closed = False
        current_type = None

    for code, value in _read_pairs(source):
        if code == 0:
            ename = value.upper()
            if ename == "ENDSEC":
                _flush()
                if in_vertex_sequence and polyline_pts:
                    paths.append(DesignPath(polyline_pts, poly_closed,
                                            power, speed, passes))
                    polyline_pts = []
                in_entities = False
                in_vertex_sequence = False
                continue
            if ename == "SECTION":
                continue
            # Finish previous LWPOLYLINE / SPLINE
            _flush()
            # Handle POLYLINE/VERTEX
            if ename == "POLYLINE":
                if in_vertex_sequence and polyline_pts:
                    paths.append(DesignPath(polyline_pts, poly_closed,
                                            power, speed, passes))
                    polyline_pts = []
                in_vertex_sequence = True
                poly_closed = False
                current_type = "POLYLINE"
            elif ename == "VERTEX" and in_vertex_sequence:
                pass  # vertex coords collected below
            elif ename == "SEQEND":
                if polyline_pts:
                    paths.append(DesignPath(polyline_pts, poly_closed,
                                            power, speed, passes))
                    polyline_pts = []
                in_vertex_sequence = False
            elif ename in ("LWPOLYLINE", "SPLINE") and in_entities:
                current_type = ename
            elif not in_entities:
                pass  # not in ENTITIES section yet
        elif code == 2 and not in_entities:
            if value.upper() == "ENTITIES":
                in_entities = True
        elif code == 10 and in_entities:
            try:
                v = float(value)
            except ValueError:
                continue
            if current_type == "LWPOLYLINE":
                x_vals.append(v)
            elif current_type == "SPLINE":
                ctrl_x.append(v)
            elif in_vertex_sequence:
                # stash for vertex
                x_vals.append(v)
        elif code == 20 and in_entities:
            try:
                v = float(value)
            except ValueError:
                continue
            if current_type == "LWPOLYLINE":
                y_vals.append(v)
            elif current_type == "SPLINE":
                ctrl_y.append(v)
            elif in_vertex_sequence:
                y_vals.append(v)
                # Pair up latest x/y into polyline
                if x_vals and len(x_vals) == len(y_vals):
                    polyline_pts.append((x_vals[-1], y_vals[-1]))
        elif code == 70 and in_entities:
            try:
                flags = int(float(value))
            except ValueError:
                flags = 0
            if current_type in ("LWPOLYLINE", "POLYLINE"):
                poly_closed = bool(flags & 1)

    _flush()
    return paths


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def import_dxf(
    source: str,
    power: float = 500.0,
    speed: float = 3000.0,
    passes: int = 1,
    scale: float = 1.0,
) -> str:
    """Parse ASCII DXF *source* string and return GRBL G-code.

    Parameters
    ----------
    source:
        DXF file content as a string.
    power:
        Default laser power (S value, 0–1000).
    speed:
        Default feed rate (mm/min).
    passes:
        Number of passes per path.
    scale:
        Coordinate multiplier (e.g. ``25.4`` to convert inch DXF to mm).
    """
    entities = _parse_entities(source)
    paths: List[DesignPath] = []

    for ent in entities:
        p = _entity_to_path(ent, power, speed, passes)
        if p is not None:
            if scale != 1.0:
                p.points = [(x * scale, y * scale) for x, y in p.points]
            paths.append(p)

    # Also collect multi-value entities
    mv_paths = _collect_multivalue(source, power, speed, passes)
    if scale != 1.0:
        for p in mv_paths:
            p.points = [(x * scale, y * scale) for x, y in p.points]
    paths.extend(mv_paths)

    return paths_to_gcode(paths, power, speed, passes)
