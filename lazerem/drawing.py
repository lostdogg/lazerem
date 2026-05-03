"""Drawing document model for the Ray5W laser control.

Provides an interactive drawing layer system:

* :class:`Layer` – named layer with colour, power, speed, and a *no_cut* flag.
  No-cut layers are rendered on the canvas as reference geometry (stock /
  material outline) but are **excluded** from the G-code output.
* :class:`LineObj`, :class:`RectObj`, :class:`CircleObj`, :class:`TextObj` –
  the four drawing primitive types.
* :class:`DrawingDocument` – container holding layers and objects.
* :func:`drawing_to_paths` – convert enabled, cutting layers to
  :class:`~lazerem.design.DesignPath` objects.
* :func:`drawing_to_gcode` – shortcut to full G-code string.
* :func:`text_to_paths` – render a string with the built-in stroke font.

Stroke font
-----------
A minimal vector font covering A–Z, a–z, 0–9, space, and the most common
punctuation marks.  Each glyph is a list of *strokes*, where each stroke is a
list of ``(x, y)`` normalised coordinates in the range ``[0, 1] × [0, 1]``.
The font is a single-stroke (Hershey-style) design; curves are approximated
with short line segments so the output is pure G0/G1 G-code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

from .design import DesignPath, paths_to_gcode


# ---------------------------------------------------------------------------
# Layer
# ---------------------------------------------------------------------------

@dataclass
class Layer:
    """A single drawing layer."""

    name: str
    color: str = "#00ff88"
    power: float = 500.0
    speed: float = 3000.0
    enabled: bool = True
    no_cut: bool = False       # True → shown but not cut (stock / material)


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------

@dataclass
class LineObj:
    """A straight line from (x1, y1) to (x2, y2) in mm."""

    layer_idx: int
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class RectObj:
    """An axis-aligned rectangle defined by two corner points in mm."""

    layer_idx: int
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class CircleObj:
    """A circle defined by centre (cx, cy) and radius r in mm."""

    layer_idx: int
    cx: float
    cy: float
    r: float
    segments: int = 72          # polyline approximation segment count


@dataclass
class TextObj:
    """A text label placed at (x, y) in mm."""

    layer_idx: int
    x: float
    y: float
    text: str
    height: float = 5.0         # glyph height in mm
    spacing: float = 1.2        # inter-character spacing multiplier


DrawObj = Union[LineObj, RectObj, CircleObj, TextObj]


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

@dataclass
class DrawingDocument:
    """Container for all layers and drawing objects."""

    layers: List[Layer] = field(default_factory=list)
    objects: List[DrawObj] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def add_layer(self, name: str = "Layer", **kwargs) -> int:
        """Append a new layer and return its index."""
        self.layers.append(Layer(name=name, **kwargs))
        return len(self.layers) - 1

    def remove_layer(self, idx: int) -> None:
        """Delete layer *idx* and remap object layer indices."""
        if not (0 <= idx < len(self.layers)):
            return
        self.layers.pop(idx)
        # Remap remaining objects; objects on deleted layer go to 0
        for obj in self.objects:
            if obj.layer_idx == idx:
                obj.layer_idx = 0
            elif obj.layer_idx > idx:
                obj.layer_idx -= 1

    def add_object(self, obj: DrawObj) -> None:
        self.objects.append(obj)

    def remove_object(self, obj: DrawObj) -> None:
        try:
            self.objects.remove(obj)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _circle_points(
    cx: float, cy: float, r: float, segments: int
) -> List[Tuple[float, float]]:
    """Return polyline approximation of a full circle."""
    pts: List[Tuple[float, float]] = []
    for i in range(segments + 1):
        theta = 2 * math.pi * i / segments
        pts.append((cx + r * math.cos(theta), cy + r * math.sin(theta)))
    return pts


# ---------------------------------------------------------------------------
# Stroke font
# ---------------------------------------------------------------------------

# Each glyph: list of strokes; each stroke: list of (x, y) in [0,1]×[0,1].
# Coordinates: (0,0) = bottom-left; (1,1) = top-right.
# The _FONT dict maps characters to stroke lists.  A glyph width of 0.6 units
# is the standard; the advance width is 0.7 (glyph + side-bearing).

_GLYPH_W = 0.6     # nominal glyph width in the unit box
_ADV_W = 0.75      # advance (glyph width + inter-char gap) multiplier

# Define every glyph as List[List[Tuple[float,float]]]
_FONT: dict = {
    " ": [],
    "A": [[(0.0, 0.0), (0.3, 1.0), (0.6, 0.0)],
          [(0.12, 0.4), (0.48, 0.4)]],
    "B": [[(0.0, 0.0), (0.0, 1.0), (0.45, 1.0), (0.6, 0.85), (0.6, 0.65),
           (0.45, 0.5), (0.0, 0.5)],
          [(0.45, 0.5), (0.6, 0.35), (0.6, 0.15), (0.45, 0.0), (0.0, 0.0)]],
    "C": [[(0.6, 0.85), (0.45, 1.0), (0.15, 1.0), (0.0, 0.85),
           (0.0, 0.15), (0.15, 0.0), (0.45, 0.0), (0.6, 0.15)]],
    "D": [[(0.0, 0.0), (0.0, 1.0), (0.4, 1.0), (0.6, 0.8),
           (0.6, 0.2), (0.4, 0.0), (0.0, 0.0)]],
    "E": [[(0.6, 1.0), (0.0, 1.0), (0.0, 0.0), (0.6, 0.0)],
          [(0.0, 0.5), (0.45, 0.5)]],
    "F": [[(0.6, 1.0), (0.0, 1.0), (0.0, 0.0)],
          [(0.0, 0.5), (0.45, 0.5)]],
    "G": [[(0.6, 0.85), (0.45, 1.0), (0.15, 1.0), (0.0, 0.85),
           (0.0, 0.15), (0.15, 0.0), (0.5, 0.0), (0.6, 0.1),
           (0.6, 0.45), (0.35, 0.45)]],
    "H": [[(0.0, 0.0), (0.0, 1.0)],
          [(0.0, 0.5), (0.6, 0.5)],
          [(0.6, 0.0), (0.6, 1.0)]],
    "I": [[(0.15, 0.0), (0.45, 0.0)],
          [(0.3, 0.0), (0.3, 1.0)],
          [(0.15, 1.0), (0.45, 1.0)]],
    "J": [[(0.45, 1.0), (0.45, 0.15), (0.3, 0.0), (0.15, 0.0),
           (0.0, 0.15)]],
    "K": [[(0.0, 0.0), (0.0, 1.0)],
          [(0.0, 0.5), (0.6, 1.0)],
          [(0.2, 0.65), (0.6, 0.0)]],
    "L": [[(0.0, 1.0), (0.0, 0.0), (0.6, 0.0)]],
    "M": [[(0.0, 0.0), (0.0, 1.0), (0.3, 0.4), (0.6, 1.0), (0.6, 0.0)]],
    "N": [[(0.0, 0.0), (0.0, 1.0), (0.6, 0.0), (0.6, 1.0)]],
    "O": [[(0.15, 0.0), (0.45, 0.0), (0.6, 0.15), (0.6, 0.85),
           (0.45, 1.0), (0.15, 1.0), (0.0, 0.85), (0.0, 0.15),
           (0.15, 0.0)]],
    "P": [[(0.0, 0.0), (0.0, 1.0), (0.45, 1.0), (0.6, 0.85),
           (0.6, 0.65), (0.45, 0.5), (0.0, 0.5)]],
    "Q": [[(0.15, 0.0), (0.45, 0.0), (0.6, 0.15), (0.6, 0.85),
           (0.45, 1.0), (0.15, 1.0), (0.0, 0.85), (0.0, 0.15),
           (0.15, 0.0)],
          [(0.35, 0.2), (0.6, -0.05)]],
    "R": [[(0.0, 0.0), (0.0, 1.0), (0.45, 1.0), (0.6, 0.85),
           (0.6, 0.65), (0.45, 0.5), (0.0, 0.5)],
          [(0.25, 0.5), (0.6, 0.0)]],
    "S": [[(0.6, 0.85), (0.45, 1.0), (0.15, 1.0), (0.0, 0.85),
           (0.0, 0.6), (0.15, 0.5), (0.45, 0.5), (0.6, 0.4),
           (0.6, 0.15), (0.45, 0.0), (0.15, 0.0), (0.0, 0.15)]],
    "T": [[(0.0, 1.0), (0.6, 1.0)],
          [(0.3, 1.0), (0.3, 0.0)]],
    "U": [[(0.0, 1.0), (0.0, 0.15), (0.15, 0.0), (0.45, 0.0),
           (0.6, 0.15), (0.6, 1.0)]],
    "V": [[(0.0, 1.0), (0.3, 0.0), (0.6, 1.0)]],
    "W": [[(0.0, 1.0), (0.15, 0.0), (0.3, 0.5), (0.45, 0.0), (0.6, 1.0)]],
    "X": [[(0.0, 1.0), (0.6, 0.0)],
          [(0.6, 1.0), (0.0, 0.0)]],
    "Y": [[(0.0, 1.0), (0.3, 0.5), (0.6, 1.0)],
          [(0.3, 0.5), (0.3, 0.0)]],
    "Z": [[(0.0, 1.0), (0.6, 1.0), (0.0, 0.0), (0.6, 0.0)]],
    # Lowercase (mostly same as uppercase scaled to 0.7 height, based from 0)
    "a": [[(0.5, 0.7), (0.5, 0.0)],
          [(0.5, 0.55), (0.3, 0.7), (0.1, 0.7), (0.0, 0.55),
           (0.0, 0.15), (0.1, 0.0), (0.3, 0.0), (0.5, 0.15)]],
    "b": [[(0.0, 0.0), (0.0, 1.0)],
          [(0.0, 0.5), (0.35, 0.5), (0.5, 0.65), (0.5, 0.85),
           (0.35, 1.0), (0.0, 1.0)]],
    "c": [[(0.5, 0.6), (0.35, 0.7), (0.15, 0.7), (0.0, 0.55),
           (0.0, 0.15), (0.15, 0.0), (0.35, 0.0), (0.5, 0.1)]],
    "d": [[(0.5, 0.0), (0.5, 1.0)],
          [(0.5, 0.55), (0.3, 0.7), (0.1, 0.7), (0.0, 0.55),
           (0.0, 0.15), (0.1, 0.0), (0.3, 0.0), (0.5, 0.15)]],
    "e": [[(0.0, 0.35), (0.5, 0.35), (0.5, 0.55), (0.35, 0.7),
           (0.15, 0.7), (0.0, 0.55), (0.0, 0.15), (0.15, 0.0),
           (0.4, 0.0), (0.5, 0.1)]],
    "f": [[(0.45, 1.0), (0.2, 1.0), (0.1, 0.9), (0.1, 0.0)],
          [(0.0, 0.65), (0.4, 0.65)]],
    "g": [[(0.5, 0.7), (0.5, -0.15), (0.35, -0.25), (0.15, -0.25),
           (0.0, -0.15)],
          [(0.5, 0.55), (0.3, 0.7), (0.1, 0.7), (0.0, 0.55),
           (0.0, 0.15), (0.1, 0.0), (0.3, 0.0), (0.5, 0.15)]],
    "h": [[(0.0, 0.0), (0.0, 1.0)],
          [(0.0, 0.45), (0.2, 0.7), (0.4, 0.7), (0.5, 0.55),
           (0.5, 0.0)]],
    "i": [[(0.2, 0.7), (0.3, 0.7), (0.3, 0.0)],
          [(0.3, 0.9), (0.3, 0.85)]],
    "j": [[(0.3, 0.9), (0.3, 0.85)],
          [(0.35, 0.7), (0.35, -0.1), (0.2, -0.25), (0.0, -0.2)]],
    "k": [[(0.0, 0.0), (0.0, 1.0)],
          [(0.0, 0.45), (0.5, 0.7)],
          [(0.15, 0.52), (0.5, 0.0)]],
    "l": [[(0.15, 1.0), (0.2, 1.0), (0.2, 0.1), (0.3, 0.0),
           (0.4, 0.0)]],
    "m": [[(0.0, 0.7), (0.0, 0.0)],
          [(0.0, 0.5), (0.1, 0.65), (0.25, 0.7), (0.35, 0.65),
           (0.4, 0.5), (0.4, 0.0)],
          [(0.4, 0.5), (0.5, 0.65), (0.65, 0.7), (0.75, 0.65),
           (0.8, 0.5), (0.8, 0.0)]],
    "n": [[(0.0, 0.7), (0.0, 0.0)],
          [(0.0, 0.45), (0.15, 0.65), (0.35, 0.7), (0.5, 0.55),
           (0.5, 0.0)]],
    "o": [[(0.15, 0.0), (0.35, 0.0), (0.5, 0.15), (0.5, 0.55),
           (0.35, 0.7), (0.15, 0.7), (0.0, 0.55), (0.0, 0.15),
           (0.15, 0.0)]],
    "p": [[(0.0, 0.7), (0.0, -0.3)],
          [(0.0, 0.5), (0.3, 0.7), (0.5, 0.55), (0.5, 0.15),
           (0.3, 0.0), (0.0, 0.15)]],
    "q": [[(0.5, 0.7), (0.5, -0.3)],
          [(0.5, 0.5), (0.2, 0.7), (0.0, 0.55), (0.0, 0.15),
           (0.2, 0.0), (0.5, 0.15)]],
    "r": [[(0.0, 0.7), (0.0, 0.0)],
          [(0.0, 0.45), (0.15, 0.65), (0.35, 0.7), (0.5, 0.65)]],
    "s": [[(0.5, 0.6), (0.35, 0.7), (0.15, 0.7), (0.0, 0.6),
           (0.0, 0.4), (0.5, 0.3), (0.5, 0.1), (0.35, 0.0),
           (0.15, 0.0), (0.0, 0.1)]],
    "t": [[(0.2, 1.0), (0.2, 0.1), (0.3, 0.0), (0.45, 0.0)],
          [(0.0, 0.7), (0.45, 0.7)]],
    "u": [[(0.0, 0.7), (0.0, 0.15), (0.1, 0.0), (0.35, 0.0),
           (0.5, 0.15), (0.5, 0.7)]],
    "v": [[(0.0, 0.7), (0.25, 0.0), (0.5, 0.7)]],
    "w": [[(0.0, 0.7), (0.1, 0.0), (0.25, 0.4), (0.4, 0.0),
           (0.5, 0.7)]],
    "x": [[(0.0, 0.7), (0.5, 0.0)],
          [(0.5, 0.7), (0.0, 0.0)]],
    "y": [[(0.0, 0.7), (0.25, 0.35)],
          [(0.5, 0.7), (0.0, -0.25)]],
    "z": [[(0.0, 0.7), (0.5, 0.7), (0.0, 0.0), (0.5, 0.0)]],
    # Digits
    "0": [[(0.15, 0.0), (0.45, 0.0), (0.6, 0.15), (0.6, 0.85),
           (0.45, 1.0), (0.15, 1.0), (0.0, 0.85), (0.0, 0.15),
           (0.15, 0.0)],
          [(0.6, 0.85), (0.0, 0.15)]],
    "1": [[(0.1, 0.8), (0.3, 1.0), (0.3, 0.0)],
          [(0.1, 0.0), (0.5, 0.0)]],
    "2": [[(0.0, 0.85), (0.15, 1.0), (0.45, 1.0), (0.6, 0.85),
           (0.6, 0.6), (0.0, 0.0), (0.6, 0.0)]],
    "3": [[(0.0, 1.0), (0.6, 1.0), (0.35, 0.55), (0.55, 0.55),
           (0.6, 0.4), (0.6, 0.15), (0.45, 0.0), (0.15, 0.0),
           (0.0, 0.15)]],
    "4": [[(0.45, 0.0), (0.45, 1.0), (0.0, 0.4), (0.6, 0.4)]],
    "5": [[(0.6, 1.0), (0.0, 1.0), (0.0, 0.55), (0.45, 0.55),
           (0.6, 0.4), (0.6, 0.15), (0.45, 0.0), (0.15, 0.0),
           (0.0, 0.15)]],
    "6": [[(0.55, 1.0), (0.15, 1.0), (0.0, 0.85), (0.0, 0.15),
           (0.15, 0.0), (0.45, 0.0), (0.6, 0.15), (0.6, 0.45),
           (0.45, 0.55), (0.0, 0.55)]],
    "7": [[(0.0, 1.0), (0.6, 1.0), (0.2, 0.0)],
          [(0.1, 0.5), (0.45, 0.5)]],
    "8": [[(0.15, 0.5), (0.0, 0.65), (0.0, 0.85), (0.15, 1.0),
           (0.45, 1.0), (0.6, 0.85), (0.6, 0.65), (0.45, 0.5),
           (0.15, 0.5), (0.0, 0.35), (0.0, 0.15), (0.15, 0.0),
           (0.45, 0.0), (0.6, 0.15), (0.6, 0.35), (0.45, 0.5)]],
    "9": [[(0.6, 0.45), (0.45, 0.55), (0.15, 0.55), (0.0, 0.4),
           (0.0, 0.15), (0.15, 0.0), (0.45, 0.0), (0.6, 0.15),
           (0.6, 0.85), (0.45, 1.0), (0.15, 1.0), (0.0, 0.85)]],
    # Common punctuation
    ".": [[(0.2, 0.0), (0.25, 0.0)]],
    ",": [[(0.25, 0.05), (0.15, -0.1)]],
    "!": [[(0.3, 0.3), (0.3, 1.0)],
          [(0.3, 0.1), (0.3, 0.05)]],
    "?": [[(0.0, 0.85), (0.15, 1.0), (0.45, 1.0), (0.6, 0.85),
           (0.6, 0.65), (0.3, 0.45), (0.3, 0.3)],
          [(0.3, 0.1), (0.3, 0.05)]],
    ":": [[(0.25, 0.65), (0.25, 0.6)],
          [(0.25, 0.1), (0.25, 0.05)]],
    ";": [[(0.25, 0.65), (0.25, 0.6)],
          [(0.25, 0.1), (0.15, -0.05)]],
    "-": [[(0.05, 0.5), (0.55, 0.5)]],
    "_": [[(0.0, 0.0), (0.6, 0.0)]],
    "+": [[(0.3, 0.1), (0.3, 0.9)],
          [(0.05, 0.5), (0.55, 0.5)]],
    "=": [[(0.05, 0.6), (0.55, 0.6)],
          [(0.05, 0.35), (0.55, 0.35)]],
    "/": [[(0.55, 1.0), (0.05, 0.0)]],
    "\\": [[(0.05, 1.0), (0.55, 0.0)]],
    "(": [[(0.4, 1.0), (0.2, 0.75), (0.2, 0.25), (0.4, 0.0)]],
    ")": [[(0.2, 1.0), (0.4, 0.75), (0.4, 0.25), (0.2, 0.0)]],
    "[": [[(0.4, 1.0), (0.2, 1.0), (0.2, 0.0), (0.4, 0.0)]],
    "]": [[(0.2, 1.0), (0.4, 1.0), (0.4, 0.0), (0.2, 0.0)]],
    "#": [[(0.15, 1.0), (0.1, 0.0)],
          [(0.45, 1.0), (0.4, 0.0)],
          [(0.0, 0.65), (0.55, 0.65)],
          [(0.0, 0.35), (0.55, 0.35)]],
    "@": [[(0.6, 0.6), (0.4, 0.7), (0.2, 0.7), (0.1, 0.6),
           (0.1, 0.4), (0.2, 0.3), (0.4, 0.3), (0.5, 0.4),
           (0.5, 0.65)],
          [(0.5, 0.65), (0.6, 0.7), (0.7, 0.55), (0.7, 0.3),
           (0.6, 0.15), (0.4, 0.1), (0.2, 0.15), (0.05, 0.3),
           (0.05, 0.6), (0.2, 0.85), (0.45, 0.9), (0.7, 0.85)]],
    "*": [[(0.3, 0.4), (0.3, 0.9)],
          [(0.05, 0.55), (0.55, 0.75)],
          [(0.55, 0.55), (0.05, 0.75)]],
    "%": [[(0.0, 1.0), (0.6, 0.0)],
          [(0.1, 0.8), (0.1, 0.65), (0.25, 0.65), (0.25, 0.8),
           (0.1, 0.8)],
          [(0.35, 0.35), (0.35, 0.2), (0.5, 0.2), (0.5, 0.35),
           (0.35, 0.35)]],
    "<": [[(0.5, 0.85), (0.1, 0.5), (0.5, 0.15)]],
    ">": [[(0.1, 0.85), (0.5, 0.5), (0.1, 0.15)]],
    "'": [[(0.3, 1.0), (0.3, 0.8)]],
    '"': [[(0.2, 1.0), (0.2, 0.8)],
          [(0.4, 1.0), (0.4, 0.8)]],
    "`": [[(0.2, 1.0), (0.35, 0.8)]],
    "^": [[(0.1, 0.7), (0.3, 1.0), (0.5, 0.7)]],
    "~": [[(0.0, 0.55), (0.15, 0.65), (0.35, 0.45), (0.5, 0.55)]],
    "&": [[(0.6, 0.5), (0.3, 0.0), (0.1, 0.0), (0.0, 0.15),
           (0.0, 0.35), (0.45, 0.7), (0.45, 0.85), (0.35, 1.0),
           (0.15, 1.0), (0.05, 0.85), (0.05, 0.7), (0.6, 0.0)]],
    "|": [[(0.3, 0.0), (0.3, 1.0)]],
}

# Add missing lowercase by folding to uppercase
for _c in "abcdefghijklmnopqrstuvwxyz":
    if _c not in _FONT and _c.upper() in _FONT:
        _FONT[_c] = _FONT[_c.upper()]


def _glyph_advance(ch: str) -> float:
    """Return the advance width multiplier for character *ch*."""
    if ch == "m":
        return 0.9
    if ch in "ij":
        return 0.4
    if ch == " ":
        return 0.5
    return _ADV_W


def text_to_paths(
    text: str,
    x: float,
    y: float,
    height: float = 5.0,
    power: float = 500.0,
    speed: float = 3000.0,
) -> List[DesignPath]:
    """Convert *text* to a list of :class:`~lazerem.design.DesignPath` objects.

    Parameters
    ----------
    text:
        The string to render.
    x, y:
        Baseline origin (mm).
    height:
        Glyph height in mm (default 5 mm).
    power, speed:
        Laser settings forwarded to each :class:`DesignPath`.
    """
    paths: List[DesignPath] = []
    cx = x
    for ch in text:
        strokes = _FONT.get(ch)
        if strokes is None:
            # Unknown character – just advance
            cx += height * _glyph_advance(ch)
            continue
        for stroke in strokes:
            pts = [(cx + sx * height, y + sy * height) for sx, sy in stroke]
            if len(pts) >= 2:
                paths.append(DesignPath(pts, False, power, speed, 1))
        cx += height * _glyph_advance(ch)
    return paths


# ---------------------------------------------------------------------------
# Document → DesignPath
# ---------------------------------------------------------------------------

def drawing_to_paths(doc: DrawingDocument) -> List[DesignPath]:
    """Convert the drawing document to laser paths.

    Only objects on layers that are **enabled** and whose *no_cut* flag is
    ``False`` are included in the output.

    Returns a flat list of :class:`~lazerem.design.DesignPath` objects.
    """
    result: List[DesignPath] = []
    for obj in doc.objects:
        idx = obj.layer_idx
        if idx < 0 or idx >= len(doc.layers):
            continue
        layer = doc.layers[idx]
        if not layer.enabled or layer.no_cut:
            continue
        result.extend(_obj_to_paths(obj, layer))
    return result


def _obj_to_paths(obj: DrawObj, layer: Layer) -> List[DesignPath]:
    """Convert a single drawing object to one or more DesignPaths."""
    p = layer.power
    s = layer.speed

    if isinstance(obj, LineObj):
        return [DesignPath([(obj.x1, obj.y1), (obj.x2, obj.y2)],
                           False, p, s)]

    if isinstance(obj, RectObj):
        x0, y0 = min(obj.x1, obj.x2), min(obj.y1, obj.y2)
        x1, y1 = max(obj.x1, obj.x2), max(obj.y1, obj.y2)
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        return [DesignPath(pts, True, p, s)]

    if isinstance(obj, CircleObj):
        pts = _circle_points(obj.cx, obj.cy, obj.r, obj.segments)
        return [DesignPath(pts, True, p, s)]

    if isinstance(obj, TextObj):
        return text_to_paths(obj.text, obj.x, obj.y, obj.height, p, s)

    return []


def drawing_to_gcode(doc: DrawingDocument) -> str:
    """Convert the full drawing document to a G-code string.

    No-cut layers are excluded from the output.
    """
    paths = drawing_to_paths(doc)
    return paths_to_gcode(paths)
