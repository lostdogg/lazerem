"""GRBL-style G-code parser for the Ray5W laser control.

Supports the subset of GRBL G-code used by diode laser engravers:

Motion codes
  G00  Rapid positioning (laser off)
  G01  Linear cut / engrave
  G02  Circular interpolation CW
  G03  Circular interpolation CCW
  G04  Dwell  (P = ms)

Modal groups
  G17          XY plane (only plane supported)
  G20 / G21    Inch / Metric units
  G90 / G91    Absolute / Incremental positioning

Laser control
  M3   Laser ON – constant-power mode
  M4   Laser ON – dynamic-power mode (GRBL laser mode)
  M5   Laser OFF
  S    Laser power  (0–1000 in GRBL, mapped to 0–100 %)

Program control
  M2 / M30  End of program

Other
  F    Feed rate (mm/min)
  X Y  Target position words
  I J  Arc centre offsets (incremental from start)
  R    Arc radius
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Word:
    """A single G-code word (letter + number)."""
    letter: str
    value: float


@dataclass
class Block:
    """A single G-code block (line), pre-parsed into words."""
    line_number: int
    raw: str
    words: List[Word] = field(default_factory=list)
    comment: str = ""

    def get(self, letter: str, default: Optional[float] = None) -> Optional[float]:
        """Return the value of the first word with *letter*, or *default*."""
        letter = letter.upper()
        for w in self.words:
            if w.letter == letter:
                return w.value
        return default

    def has(self, letter: str) -> bool:
        return any(w.letter == letter.upper() for w in self.words)


@dataclass
class ParseError:
    line_number: int
    raw: str
    message: str


# ---------------------------------------------------------------------------
# Token / block parsing
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(
    r"([A-Za-z])\s*([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)"
)
_COMMENT_RE = re.compile(r"\(([^)]*)\)|;(.*)")
_LINE_NUM_RE = re.compile(r"^[Nn](\d+)")


def _strip_comments(raw: str) -> Tuple[str, str]:
    """Remove inline comments from *raw* and return (clean, comment)."""
    comments: List[str] = []

    def _repl(m: re.Match) -> str:
        text = m.group(1) if m.group(1) is not None else m.group(2)
        comments.append(text.strip())
        return " "

    clean = _COMMENT_RE.sub(_repl, raw)
    return clean.strip(), "; ".join(comments)


def parse_program(source: str) -> Tuple[List[Block], List[ParseError]]:
    """Parse a complete G-code program string.

    Returns ``(blocks, errors)``.  Blocks with parse errors are still
    included (with whatever words could be extracted) and a matching
    :class:`ParseError` is appended to *errors*.
    """
    blocks: List[Block] = []
    errors: List[ParseError] = []

    for lineno, raw in enumerate(source.splitlines(), start=1):
        raw_stripped = raw.strip()
        if not raw_stripped or raw_stripped.startswith("%"):
            continue

        clean, comment = _strip_comments(raw_stripped)

        words: List[Word] = []
        line_number: Optional[int] = None

        m = _LINE_NUM_RE.match(clean)
        if m:
            line_number = int(m.group(1))
            clean = clean[m.end():].strip()

        for m in _WORD_RE.finditer(clean):
            letter = m.group(1).upper()
            try:
                value = float(m.group(2))
            except ValueError:
                errors.append(ParseError(lineno, raw, f"Bad number: {m.group(2)}"))
                continue
            words.append(Word(letter=letter, value=value))

        block = Block(
            line_number=line_number if line_number is not None else lineno,
            raw=raw,
            words=words,
            comment=comment,
        )
        blocks.append(block)

    return blocks, errors


# ---------------------------------------------------------------------------
# Arc helpers
# ---------------------------------------------------------------------------

def arc_points(
    start: Tuple[float, float],
    end: Tuple[float, float],
    center: Tuple[float, float],
    clockwise: bool,
    segments: int = 36,
) -> List[Tuple[float, float]]:
    """Return a list of (x, y) points approximating the arc."""
    cx, cy = center
    sx, sy = start
    ex, ey = end

    start_angle = math.atan2(sy - cy, sx - cx)
    end_angle = math.atan2(ey - cy, ex - cx)
    radius = math.hypot(sx - cx, sy - cy)

    if clockwise:
        if end_angle >= start_angle:
            end_angle -= 2 * math.pi
    else:
        if end_angle <= start_angle:
            end_angle += 2 * math.pi

    pts: List[Tuple[float, float]] = []
    for i in range(segments + 1):
        t = i / segments
        angle = start_angle + t * (end_angle - start_angle)
        pts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return pts
