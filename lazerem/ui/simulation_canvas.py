"""3-D engraving simulation canvas widget.

Renders the :class:`~lazerem.simulation.EngravingSimulator` depth map as
a PhotoImage on a tkinter Canvas.  The user can trigger a re-render
after a program run to visualise how different power levels and passes
affect the material.
"""

from __future__ import annotations

import tkinter as tk
from typing import List, Optional, Tuple

from ..simulation import EngravingSimulator
from ..machine import BurnSegment

_BG = "#0d1a0d"


class SimulationCanvas(tk.Canvas):
    """Canvas that shows a depth-map simulation of the engraving result.

    Call :meth:`update_simulation` with the current burn path to refresh.
    """

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        kwargs.setdefault("bg", _BG)
        kwargs.setdefault("highlightthickness", 0)
        super().__init__(parent, **kwargs)

        self._simulator = EngravingSimulator(resolution=0.5)
        self._photo: Optional[tk.PhotoImage] = None

        self.bind("<Configure>", self._on_resize)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_simulation(
        self,
        segments: List[BurnSegment],
        resolution: float = 0.5,
    ) -> None:
        """Rebuild the depth map from *segments* and redraw."""
        self._simulator = EngravingSimulator(resolution=resolution)
        self._simulator.process(segments)
        self._render()

    def clear(self) -> None:
        self._simulator.reset()
        self._render()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_resize(self, event: tk.Event) -> None:
        self._render()

    def _render(self) -> None:
        self.delete("all")
        w = self.winfo_width() or 300
        h = self.winfo_height() or 200

        if w < 2 or h < 2:
            return

        rgb_grid = self._simulator.render(width_px=w, height_px=h)

        # Build a tkinter PhotoImage row by row
        img = tk.PhotoImage(width=w, height=h)

        # Batch row data for efficiency
        row_data: List[str] = []
        for row in rgb_grid:
            hex_pixels = " ".join(f"#{r:02x}{g:02x}{b:02x}" for r, g, b in row)
            row_data.append(f"{{{hex_pixels}}}")

        img.put(" ".join(row_data))
        self._photo = img
        self.create_image(0, 0, anchor="nw", image=img)

        # Overlay label
        bounds = self._simulator.bounds()
        if bounds:
            x0, y0, x1, y1 = bounds
            label = f"Depth map  {x1 - x0:.1f}×{y1 - y0:.1f} mm"
        else:
            label = "No simulation data"
        self.create_text(
            4, 4, anchor="nw", text=label,
            fill="#88ff88", font=("Monospace", 8),
        )
