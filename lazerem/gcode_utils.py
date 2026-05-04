"""Utility functions for transforming G-code text.

Intentionally free of tkinter / UI imports so it can be used in tests and
non-GUI contexts.
"""

from __future__ import annotations

import re

_GCODE_COORD_RE = re.compile(r'([XY])([+-]?\d+(?:\.\d+)?)', re.IGNORECASE)


def apply_gcode_translate(gcode: str, dx: float, dy: float) -> str:
    """Return *gcode* with every X and Y coordinate shifted by *dx* / *dy*.

    Comment sections (starting with ``;``) are preserved unchanged.
    Only X and Y axis words are modified; S, F, I, J and other words are
    left untouched.

    Parameters
    ----------
    gcode:
        Multi-line G-code string.
    dx:
        Translation to add to every X coordinate (mm).
    dy:
        Translation to add to every Y coordinate (mm).

    Returns
    -------
    str
        Translated G-code.
    """
    if dx == 0.0 and dy == 0.0:
        return gcode

    def _repl(m: re.Match) -> str:
        axis = m.group(1).upper()
        val = float(m.group(2))
        if axis == "X":
            return f"X{val + dx:.4f}".rstrip("0").rstrip(".")
        return f"Y{val + dy:.4f}".rstrip("0").rstrip(".")

    lines = []
    for line in gcode.splitlines():
        comment_idx = line.find(";")
        if comment_idx >= 0:
            code_part = line[:comment_idx]
            comment_part = line[comment_idx:]
        else:
            code_part = line
            comment_part = ""
        lines.append(_GCODE_COORD_RE.sub(_repl, code_part) + comment_part)
    return "\n".join(lines)
