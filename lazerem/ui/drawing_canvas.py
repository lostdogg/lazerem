"""Interactive drawing canvas for the Ray5W laser control.

Provides :class:`DrawingCanvas` – a ``tk.Canvas`` that supports:

* An XY grid with zoom / pan (scroll-wheel zoom, middle-mouse or Ctrl+drag pan).
* Five drawing tools selectable via the ``tool`` property:

  ``"select"``  – click an object to highlight it; drag to pan.
  ``"line"``    – click-drag to place a 2-point straight line.
  ``"rect"``    – click-drag to place an axis-aligned rectangle.
  ``"circle"``  – click to set centre, drag to set radius.
  ``"text"``    – click to place a text label (prompts in a small dialog).

* Real-time preview ghost while dragging.
* Snap to existing object endpoints, midpoints, and centres (yellow
  indicator; toggle via the ``snap_enabled`` property).
* Undo (Ctrl+Z) for the last-added object.
* Renders all objects in their layer colour; *no_cut* layers are shown with a
  dashed outline and reduced opacity to distinguish them from cutting layers.
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import simpledialog
from typing import List, Optional, Tuple

from ..drawing import (
    CircleObj,
    DrawingDocument,
    Layer,
    LineObj,
    RectObj,
    TextObj,
)

_BG = "#0d1a0d"
_GRID = "#1e2a1e"
_AXIS = "#3a5a3a"
_CURSOR = "#00ff88"
_GHOST = "#446644"
_HANDLE = "#00cc66"
_SNAP = "#ffff00"          # yellow snap indicator
_MONO_SM = ("Monospace", 9)

_SNAP_TOL_MM = 3.0         # snap trigger distance in mm

_TOOL_CURSORS = {
    "select": "arrow",
    "line": "crosshair",
    "rect": "crosshair",
    "circle": "crosshair",
    "text": "xterm",
}


class DrawingCanvas(tk.Canvas):
    """Zoomable / pannable canvas for interactive 2-D drawing."""

    def __init__(self, parent: tk.Widget, doc: DrawingDocument, **kwargs) -> None:
        kwargs.setdefault("bg", _BG)
        kwargs.setdefault("highlightthickness", 0)
        super().__init__(parent, **kwargs)

        self._doc: DrawingDocument = doc
        self._tool: str = "select"
        self._active_layer: int = 0

        # View transform
        self._scale: float = 5.0        # pixels per mm
        self._offset_x: float = 0.0
        self._offset_y: float = 0.0

        # Interaction state
        self._drag_start: Optional[Tuple[float, float]] = None  # world mm
        self._ghost_id: Optional[int] = None
        self._selected: Optional[object] = None
        self._snap_pos: Optional[Tuple[float, float]] = None    # active snap pt

        # Pan state (middle-mouse or Ctrl+drag)
        self._pan_pixel_start: Optional[Tuple[int, int]] = None
        self._panning: bool = False

        # Undo stack – stores objects added through canvas interaction
        self._undo_stack: List = []

        # Snap feature
        self._snap_enabled: bool = True

        self.bind("<Configure>", lambda _: self.redraw())
        self.bind("<MouseWheel>", self._on_scroll)
        self.bind("<Button-4>", self._on_scroll)
        self.bind("<Button-5>", self._on_scroll)
        self.bind("<ButtonPress-2>", self._pan_start)
        self.bind("<B2-Motion>", self._pan_move)
        self.bind("<ButtonRelease-2>", self._pan_end)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Control-ButtonPress-1>", self._pan_start)
        self.bind("<Control-B1-Motion>", self._pan_move)
        self.bind("<Control-ButtonRelease-1>", self._pan_end)
        self.bind("<Control-z>", lambda _: self._undo())
        self.bind("<Control-Z>", lambda _: self._undo())

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def tool(self) -> str:
        return self._tool

    @tool.setter
    def tool(self, value: str) -> None:
        self._tool = value
        cursor = _TOOL_CURSORS.get(value, "arrow")
        self.config(cursor=cursor)

    @property
    def active_layer(self) -> int:
        return self._active_layer

    @active_layer.setter
    def active_layer(self, idx: int) -> None:
        self._active_layer = max(0, idx)

    @property
    def snap_enabled(self) -> bool:
        """Whether snap-to-point is active for drawing tools."""
        return self._snap_enabled

    @snap_enabled.setter
    def snap_enabled(self, value: bool) -> None:
        self._snap_enabled = bool(value)

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def _to_canvas(self, x: float, y: float) -> Tuple[float, float]:
        """Convert machine coordinates (mm) → canvas pixels."""
        w = self.winfo_width() or 600
        h = self.winfo_height() or 400
        cx = w / 2 + self._offset_x + x * self._scale
        cy = h / 2 + self._offset_y - y * self._scale
        return cx, cy

    def _to_world(self, cx: float, cy: float) -> Tuple[float, float]:
        """Convert canvas pixels → machine coordinates (mm)."""
        w = self.winfo_width() or 600
        h = self.winfo_height() or 400
        x = (cx - w / 2 - self._offset_x) / self._scale
        y = -(cy - h / 2 - self._offset_y) / self._scale
        return x, y

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_document(self, doc: DrawingDocument) -> None:
        self._doc = doc
        self._selected = None
        self._undo_stack.clear()
        self.redraw()

    def clear_selection(self) -> None:
        """Deselect the currently selected drawing object."""
        self._selected = None
        self.redraw()

    def clear_undo(self) -> None:
        """Discard the entire undo history."""
        self._undo_stack.clear()

    @property
    def selected_object(self):
        """Return the currently selected drawing object (or None)."""
        return self._selected

    def fit_all(self) -> None:
        """Zoom and pan so all objects are visible."""
        xs: List[float] = [0.0]
        ys: List[float] = [0.0]
        for obj in self._doc.objects:
            if isinstance(obj, LineObj):
                xs += [obj.x1, obj.x2]
                ys += [obj.y1, obj.y2]
            elif isinstance(obj, RectObj):
                xs += [obj.x1, obj.x2]
                ys += [obj.y1, obj.y2]
            elif isinstance(obj, CircleObj):
                xs += [obj.cx - obj.r, obj.cx + obj.r]
                ys += [obj.cy - obj.r, obj.cy + obj.r]
            elif isinstance(obj, TextObj):
                xs.append(obj.x)
                ys.append(obj.y)
        if len(xs) < 2:
            return
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        w = self.winfo_width() or 600
        h = self.winfo_height() or 400
        margin = 40
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        scale_x = (w - 2 * margin) / span_x
        scale_y = (h - 2 * margin) / span_y
        self._scale = min(scale_x, scale_y)
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2
        self._offset_x = -cx * self._scale
        self._offset_y = cy * self._scale
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        self._draw_grid()
        self._draw_axes()
        self._draw_objects()
        self._draw_cursor_crosshair()
        self._draw_snap_indicator()

    # ------------------------------------------------------------------
    # Grid / axes
    # ------------------------------------------------------------------

    def _draw_grid(self) -> None:
        w = self.winfo_width() or 600
        h = self.winfo_height() or 400
        if self._scale <= 0:
            return
        raw_spacing = 10.0 / self._scale
        magnitude = 10 ** math.floor(math.log10(max(raw_spacing, 0.001)))
        grid_mm = magnitude * 10
        for factor in (1, 2, 5, 10):
            if magnitude * factor * self._scale >= 8:
                grid_mm = magnitude * factor
                break
        min_x = (0 - w / 2 - self._offset_x) / self._scale
        max_x = (w - w / 2 - self._offset_x) / self._scale
        min_y = -(h / 2 + self._offset_y) / self._scale
        max_y = -(-h / 2 + self._offset_y) / self._scale
        x = math.floor(min_x / grid_mm) * grid_mm
        while x <= max_x:
            cx, _ = self._to_canvas(x, 0)
            self.create_line(cx, 0, cx, h, fill=_GRID, width=1)
            x += grid_mm
        y = math.floor(min_y / grid_mm) * grid_mm
        while y <= max_y:
            _, cy = self._to_canvas(0, y)
            self.create_line(0, cy, w, cy, fill=_GRID, width=1)
            y += grid_mm

    def _draw_axes(self) -> None:
        w = self.winfo_width() or 600
        h = self.winfo_height() or 400
        ox, oy = self._to_canvas(0, 0)
        self.create_line(0, oy, w, oy, fill=_AXIS, width=1)
        self.create_line(ox, 0, ox, h, fill=_AXIS, width=1)
        self.create_text(w - 20, oy - 10, text="X", fill=_AXIS, font=_MONO_SM)
        self.create_text(ox + 10, 15, text="Y", fill=_AXIS, font=_MONO_SM)
        self.create_text(ox + 4, oy + 10, text="0", fill=_AXIS,
                         font=("Monospace", 8))

    def _draw_cursor_crosshair(self) -> None:
        ox, oy = self._to_canvas(0, 0)
        r = 7
        self.create_line(ox - r, oy, ox + r, oy, fill=_CURSOR, width=2)
        self.create_line(ox, oy - r, ox, oy + r, fill=_CURSOR, width=2)
        self.create_oval(ox - 3, oy - 3, ox + 3, oy + 3,
                         outline=_CURSOR, width=1)

    def _draw_snap_indicator(self) -> None:
        """Draw a yellow diamond at the active snap point (if any)."""
        if self._snap_pos is None:
            return
        cx, cy = self._to_canvas(*self._snap_pos)
        r = 6
        self.create_polygon(
            cx, cy - r,
            cx + r, cy,
            cx, cy + r,
            cx - r, cy,
            outline=_SNAP, fill="", width=2,
        )

    # ------------------------------------------------------------------
    # Snap helpers
    # ------------------------------------------------------------------

    def _get_snap_points(self) -> List[Tuple[float, float]]:
        """Collect all snap candidates (endpoints, midpoints, centres)."""
        pts: List[Tuple[float, float]] = []
        for obj in self._doc.objects:
            if isinstance(obj, LineObj):
                pts.append((obj.x1, obj.y1))
                pts.append((obj.x2, obj.y2))
                pts.append(((obj.x1 + obj.x2) / 2, (obj.y1 + obj.y2) / 2))
            elif isinstance(obj, RectObj):
                pts.append((obj.x1, obj.y1))
                pts.append((obj.x2, obj.y1))
                pts.append((obj.x2, obj.y2))
                pts.append((obj.x1, obj.y2))
                pts.append(((obj.x1 + obj.x2) / 2, (obj.y1 + obj.y2) / 2))
            elif isinstance(obj, CircleObj):
                pts.append((obj.cx, obj.cy))
            elif isinstance(obj, TextObj):
                pts.append((obj.x, obj.y))
        return pts

    def _snap_to(self, wx: float, wy: float) -> Tuple[float, float]:
        """Return the nearest snap point within tolerance, else (wx, wy)."""
        if not self._snap_enabled:
            self._snap_pos = None
            return wx, wy
        best_d = _SNAP_TOL_MM
        best: Optional[Tuple[float, float]] = None
        for sx, sy in self._get_snap_points():
            d = math.hypot(wx - sx, wy - sy)
            if d < best_d:
                best_d = d
                best = (sx, sy)
        self._snap_pos = best
        return best if best is not None else (wx, wy)

    # ------------------------------------------------------------------
    # Undo
    # ------------------------------------------------------------------

    def _undo(self) -> None:
        """Remove the most recently added object (Ctrl+Z)."""
        if not self._undo_stack:
            return
        obj = self._undo_stack.pop()
        self._doc.remove_object(obj)
        if self._selected is obj:
            self._selected = None
        self.redraw()

    # ------------------------------------------------------------------
    # Object rendering
    # ------------------------------------------------------------------

    def _layer_style(self, layer_idx: int) -> Tuple[str, str, tuple]:
        """Return (fill/outline color, dash pattern, width) for a layer."""
        if 0 <= layer_idx < len(self._doc.layers):
            layer = self._doc.layers[layer_idx]
            color = layer.color if layer.enabled else "#444444"
            dash = (4, 4) if layer.no_cut else ()
            width = 1 if layer.no_cut else 2
        else:
            color = "#888888"
            dash = ()
            width = 1
        return color, dash, width

    def _draw_objects(self) -> None:
        for obj in self._doc.objects:
            selected = (obj is self._selected)
            self._draw_one_object(obj, selected=selected)

    def _draw_one_object(self, obj, *, selected: bool = False,
                         ghost: bool = False) -> None:
        color, dash, width = self._layer_style(obj.layer_idx)
        if ghost:
            color = _GHOST
            dash = (3, 3)
            width = 1
        elif selected:
            color = "#ffffff"
            width += 1

        if isinstance(obj, LineObj):
            x1, y1 = self._to_canvas(obj.x1, obj.y1)
            x2, y2 = self._to_canvas(obj.x2, obj.y2)
            self.create_line(x1, y1, x2, y2, fill=color, width=width,
                             dash=dash)
            if selected:
                self._draw_handle(obj.x1, obj.y1)
                self._draw_handle(obj.x2, obj.y2)

        elif isinstance(obj, RectObj):
            x0, y0 = self._to_canvas(min(obj.x1, obj.x2),
                                      max(obj.y1, obj.y2))
            x1, y1 = self._to_canvas(max(obj.x1, obj.x2),
                                      min(obj.y1, obj.y2))
            self.create_rectangle(x0, y0, x1, y1, outline=color,
                                  fill="", width=width, dash=dash)
            if selected:
                for wx, wy in [(obj.x1, obj.y1), (obj.x2, obj.y1),
                               (obj.x2, obj.y2), (obj.x1, obj.y2)]:
                    self._draw_handle(wx, wy)

        elif isinstance(obj, CircleObj):
            if obj.r > 0:
                pts: List[float] = []
                n = max(12, min(obj.segments, 72))
                for i in range(n + 1):
                    theta = 2 * math.pi * i / n
                    px = obj.cx + obj.r * math.cos(theta)
                    py = obj.cy + obj.r * math.sin(theta)
                    cpx, cpy = self._to_canvas(px, py)
                    pts += [cpx, cpy]
                if len(pts) >= 4:
                    self.create_line(*pts, fill=color, width=width, dash=dash)
            if selected:
                self._draw_handle(obj.cx, obj.cy)
                self._draw_handle(obj.cx + obj.r, obj.cy)

        elif isinstance(obj, TextObj):
            cx, cy = self._to_canvas(obj.x, obj.y)
            font_size = max(6, int(obj.height * self._scale))
            self.create_text(cx, cy, text=obj.text, fill=color,
                             font=("Monospace", font_size),
                             anchor="sw")

    def _draw_handle(self, wx: float, wy: float) -> None:
        cx, cy = self._to_canvas(wx, wy)
        r = 4
        self.create_rectangle(cx - r, cy - r, cx + r, cy + r,
                               outline=_HANDLE, fill="", width=1)

    # ------------------------------------------------------------------
    # Mouse: pan (middle-mouse or Ctrl+click)
    # ------------------------------------------------------------------

    def _pan_start(self, event: tk.Event) -> None:
        self._pan_pixel_start = (event.x, event.y)
        self._panning = True

    def _pan_move(self, event: tk.Event) -> None:
        if not self._panning or self._pan_pixel_start is None:
            return
        dx = event.x - self._pan_pixel_start[0]
        dy = event.y - self._pan_pixel_start[1]
        self._offset_x += dx
        self._offset_y += dy
        self._pan_pixel_start = (event.x, event.y)
        self.redraw()

    def _pan_end(self, event: tk.Event) -> None:
        self._panning = False
        self._pan_pixel_start = None

    def _on_scroll(self, event: tk.Event) -> None:
        if event.num == 4 or getattr(event, "delta", 0) > 0:
            factor = 1.15
        else:
            factor = 1 / 1.15
        self._scale *= factor
        self.redraw()

    # ------------------------------------------------------------------
    # Mouse: drawing tools
    # ------------------------------------------------------------------

    def _on_press(self, event: tk.Event) -> None:
        if self._panning:
            return
        wx, wy = self._to_world(event.x, event.y)
        if self._tool == "select":
            self._selected = self._hit_test(wx, wy)
            self.redraw()
            return
        if self._tool == "text":
            wx, wy = self._snap_to(wx, wy)
            self._place_text(wx, wy)
            return
        wx, wy = self._snap_to(wx, wy)
        self._drag_start = (wx, wy)

    def _on_drag(self, event: tk.Event) -> None:
        if self._panning or self._drag_start is None:
            return
        wx, wy = self._to_world(event.x, event.y)
        wx, wy = self._snap_to(wx, wy)
        self._update_ghost(self._drag_start, (wx, wy))

    def _on_release(self, event: tk.Event) -> None:
        if self._panning or self._drag_start is None:
            return
        wx, wy = self._to_world(event.x, event.y)
        wx, wy = self._snap_to(wx, wy)
        self._snap_pos = None
        start = self._drag_start
        self._drag_start = None
        # Remove ghost
        if self._ghost_id is not None:
            self.delete(self._ghost_id)
            self._ghost_id = None
        self._commit_shape(start, (wx, wy))

    def _update_ghost(
        self, start: Tuple[float, float], end: Tuple[float, float]
    ) -> None:
        """Redraw the preview ghost object while dragging."""
        self.redraw()  # clears previous ghost too
        sx, sy = self._to_canvas(*start)
        ex, ey = self._to_canvas(*end)
        if self._tool == "line":
            self.create_line(sx, sy, ex, ey, fill=_GHOST, width=1, dash=(3, 3))
        elif self._tool == "rect":
            self.create_rectangle(sx, sy, ex, ey, outline=_GHOST, fill="",
                                  width=1, dash=(3, 3))
        elif self._tool == "circle":
            r_px = math.hypot(ex - sx, ey - sy)
            self.create_oval(sx - r_px, sy - r_px, sx + r_px, sy + r_px,
                             outline=_GHOST, fill="", width=1, dash=(3, 3))

    def _commit_shape(
        self, start: Tuple[float, float], end: Tuple[float, float]
    ) -> None:
        """Finalise the drawn shape and add it to the document."""
        # Clamp active layer
        if not self._doc.layers:
            return
        idx = min(self._active_layer, len(self._doc.layers) - 1)
        x1, y1 = start
        x2, y2 = end
        obj = None
        if self._tool == "line":
            if math.hypot(x2 - x1, y2 - y1) > 0.01:
                obj = LineObj(idx, x1, y1, x2, y2)
        elif self._tool == "rect":
            if abs(x2 - x1) > 0.01 and abs(y2 - y1) > 0.01:
                obj = RectObj(idx, x1, y1, x2, y2)
        elif self._tool == "circle":
            r = math.hypot(x2 - x1, y2 - y1)
            if r > 0.01:
                obj = CircleObj(idx, x1, y1, r)
        if obj is not None:
            self._doc.add_object(obj)
            self._undo_stack.append(obj)
        self.redraw()

    def _place_text(self, wx: float, wy: float) -> None:
        """Prompt for text and place a TextObj at the given world position."""
        if not self._doc.layers:
            return
        idx = min(self._active_layer, len(self._doc.layers) - 1)
        text = simpledialog.askstring(
            "Text", "Enter text to engrave:", parent=self
        )
        if text:
            obj = TextObj(idx, wx, wy, text)
            self._doc.add_object(obj)
            self._undo_stack.append(obj)
        self.redraw()

    # ------------------------------------------------------------------
    # Hit test (select tool)
    # ------------------------------------------------------------------

    def _hit_test(self, wx: float, wy: float, tol_mm: float = 2.0):
        """Return the topmost object near (wx, wy) or None."""
        for obj in reversed(self._doc.objects):
            if isinstance(obj, LineObj):
                d = _point_to_segment_dist(
                    wx, wy, obj.x1, obj.y1, obj.x2, obj.y2)
                if d <= tol_mm:
                    return obj
            elif isinstance(obj, RectObj):
                x0, x1 = sorted((obj.x1, obj.x2))
                y0, y1 = sorted((obj.y1, obj.y2))
                on_edge = (
                    abs(wx - x0) <= tol_mm and y0 <= wy <= y1 or
                    abs(wx - x1) <= tol_mm and y0 <= wy <= y1 or
                    abs(wy - y0) <= tol_mm and x0 <= wx <= x1 or
                    abs(wy - y1) <= tol_mm and x0 <= wx <= x1
                )
                if on_edge:
                    return obj
            elif isinstance(obj, CircleObj):
                d = abs(math.hypot(wx - obj.cx, wy - obj.cy) - obj.r)
                if d <= tol_mm:
                    return obj
            elif isinstance(obj, TextObj):
                if math.hypot(wx - obj.x, wy - obj.y) <= tol_mm * 2:
                    return obj
        return None


# ---------------------------------------------------------------------------
# Geometry helper
# ---------------------------------------------------------------------------

def _point_to_segment_dist(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float,
) -> float:
    """Minimum distance from point (px, py) to segment (ax,ay)–(bx,by)."""
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    nx = ax + t * dx
    ny = ay + t * dy
    return math.hypot(px - nx, py - ny)
