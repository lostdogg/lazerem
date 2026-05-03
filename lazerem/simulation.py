"""3-D engraving depth-map simulation for the Ray5W laser control.

The :class:`EngravingSimulator` consumes a list of
:class:`~lazerem.machine.BurnSegment` objects and builds a 2-D
floating-point depth map where each cell's value represents how much
material has been removed (in arbitrary depth units 0–1).

Model
-----
* Each cut segment removes depth proportional to its *power* fraction
  and the number of times that cell is visited.
* Each cell is a square *resolution*×*resolution* mm region.
* The depth grid is then shaded with a simple diffuse normal-map pass to
  give a convincing 3-D appearance when converted to an RGB pixel grid.

Usage::

    sim = EngravingSimulator(resolution=0.5)
    sim.process(machine.burn_path)
    rgb_grid = sim.render(width_px=400, height_px=300)
    # rgb_grid[row][col] = (R, G, B) ints 0-255
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from .machine import BurnSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def _depth_color(depth: float) -> Tuple[int, int, int]:
    """Map depth 0-1 to a wood-burn RGB colour.

    0   → light tan (raw wood)
    0.5 → medium brown (lightly charred)
    1   → very dark brown / near-black (deep engrave)
    """
    if depth <= 0.0:
        return (210, 180, 140)          # light tan
    elif depth <= 0.5:
        t = depth / 0.5
        r = int(_lerp(210, 120, t))
        g = int(_lerp(180, 80, t))
        b = int(_lerp(140, 40, t))
        return (r, g, b)
    else:
        t = (depth - 0.5) / 0.5
        r = int(_lerp(120, 30, t))
        g = int(_lerp(80, 20, t))
        b = int(_lerp(40, 10, t))
        return (r, g, b)


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class EngravingSimulator:
    """Build a depth map from a burn-path and render it as an RGB pixel grid.

    Parameters
    ----------
    resolution:
        Cell size in mm.  Smaller values give higher fidelity at the cost
        of memory and render time.
    max_depth_per_pass:
        Fraction of full depth removed per unit of normalised laser power
        per pass.  The total depth for a cell is capped at 1.0.
    """

    def __init__(
        self,
        resolution: float = 0.5,
        max_depth_per_pass: float = 0.3,
    ) -> None:
        if resolution <= 0:
            raise ValueError("resolution must be positive")
        self.resolution = resolution
        self.max_depth_per_pass = max_depth_per_pass

        # Depth grid: dict (grid_x, grid_y) → depth 0–1.
        # Populated by process().
        self._depth: dict = {}
        self._bounds: Optional[Tuple[float, float, float, float]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear the depth map."""
        self._depth = {}
        self._bounds = None

    def process(self, segments: List[BurnSegment]) -> None:
        """Accumulate depth from *segments* into the depth map.

        Rapid moves (laser off) are ignored.  Rasterises each cut/arc
        segment into cells along the path.
        """
        for seg in segments:
            if seg.motion == "rapid" or seg.power <= 0.0:
                continue
            pts = seg.arc_points if seg.arc_points else [seg.start, seg.end]
            for i in range(len(pts) - 1):
                self._rasterise_segment(pts[i], pts[i + 1], seg.power)

    def render(
        self,
        width_px: int = 256,
        height_px: int = 256,
        normal_strength: float = 1.5,
    ) -> List[List[Tuple[int, int, int]]]:
        """Return an *height_px × width_px* RGB grid (list of rows).

        Each element is an ``(R, G, B)`` tuple with values 0–255.
        The image is shaded with a simple height-map normal-map pass so
        engraved channels appear three-dimensional.

        Parameters
        ----------
        normal_strength:
            Amplification factor for the normal-map lighting.  Higher
            values exaggerate the 3-D relief effect.
        """
        if not self._depth:
            # Blank canvas – return uniform raw-wood colour
            wood = _depth_color(0.0)
            return [[wood] * width_px for _ in range(height_px)]

        x0, y0, x1, y1 = self._get_bounds()
        span_x = max(x1 - x0, self.resolution)
        span_y = max(y1 - y0, self.resolution)
        res = self.resolution

        grid = [[0.0] * width_px for _ in range(height_px)]

        # Sample depth into pixel grid
        for row in range(height_px):
            for col in range(width_px):
                # Map pixel → mm
                mm_x = x0 + col / (width_px - 1) * span_x if width_px > 1 else x0
                mm_y = y0 + row / (height_px - 1) * span_y if height_px > 1 else y0
                gx = math.floor(mm_x / res)
                gy = math.floor(mm_y / res)
                grid[row][col] = self._depth.get((gx, gy), 0.0)

        # Normal-map shading pass (Sobel-like, 3×3 kernel)
        output: List[List[Tuple[int, int, int]]] = []
        for row in range(height_px):
            out_row: List[Tuple[int, int, int]] = []
            for col in range(width_px):
                depth = grid[row][col]
                # Compute gradient for 3-D shading
                dx = (
                    self._get_grid_pixel(grid, row, col + 1, width_px, height_px)
                    - self._get_grid_pixel(grid, row, col - 1, width_px, height_px)
                )
                dy = (
                    self._get_grid_pixel(grid, row + 1, col, width_px, height_px)
                    - self._get_grid_pixel(grid, row - 1, col, width_px, height_px)
                )
                # Diffuse lighting from upper-left
                light_x, light_y, light_z = -0.577, -0.577, 0.577
                nx = -dx * normal_strength
                ny = -dy * normal_strength
                nz = 1.0
                length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
                nx /= length
                ny /= length
                nz /= length
                diffuse = max(0.1, nx * light_x + ny * light_y + nz * light_z)

                base_r, base_g, base_b = _depth_color(depth)
                r = int(min(255, base_r * diffuse))
                g = int(min(255, base_g * diffuse))
                b = int(min(255, base_b * diffuse))
                out_row.append((r, g, b))
            output.append(out_row)

        return output

    def bounds(self) -> Optional[Tuple[float, float, float, float]]:
        """Return (min_x, min_y, max_x, max_y) of the engraved area, or None."""
        if not self._depth:
            return None
        return self._get_bounds()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rasterise_segment(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        power: float,
    ) -> None:
        """Walk from p1→p2 in resolution-sized steps, accumulating depth."""
        x1, y1 = p1
        x2, y2 = p2
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(math.ceil(length / self.resolution)))
        depth_inc = power * self.max_depth_per_pass / steps * steps  # per cell hit
        # Simpler: each hit adds power * max_depth_per_pass
        depth_inc = power * self.max_depth_per_pass

        visited: set = set()
        for i in range(steps + 1):
            t = i / steps if steps > 0 else 0.0
            mx = x1 + (x2 - x1) * t
            my = y1 + (y2 - y1) * t
            gx = math.floor(mx / self.resolution)
            gy = math.floor(my / self.resolution)
            cell = (gx, gy)
            if cell not in visited:
                visited.add(cell)
                old = self._depth.get(cell, 0.0)
                self._depth[cell] = min(1.0, old + depth_inc)

    def _get_bounds(self) -> Tuple[float, float, float, float]:
        res = self.resolution
        xs = [k[0] * res for k in self._depth]
        ys = [k[1] * res for k in self._depth]
        return min(xs), min(ys), max(xs) + res, max(ys) + res

    @staticmethod
    def _get_grid_pixel(
        grid: List[List[float]],
        row: int,
        col: int,
        width: int,
        height: int,
    ) -> float:
        row = max(0, min(height - 1, row))
        col = max(0, min(width - 1, col))
        return grid[row][col]
