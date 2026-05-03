"""AI-assisted design path optimiser for the Ray5W laser control.

Heuristic algorithms that analyse a list of
:class:`~lazerem.design.DesignPath` objects and return an improved
ordering / modified paths that reduce total air-travel (laser-off)
distance and improve cut quality.

Algorithms
----------
* **nearest_neighbour** – greedy nearest-neighbour TSP reordering of
  path start points.  Reduces total rapid travel by visiting nearby
  paths first.
* **merge_short_segments** – combine collinear adjacent segments that
  are below a distance threshold into a single move, reducing block
  count and improving firmware streaming efficiency.
* **sort_by_area** – cut inner shapes before outer shapes (prevents
  work-piece shifting).
* **optimize** – runs all of the above in sequence and returns a
  summary of improvements.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .design import DesignPath


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _path_start(path: DesignPath) -> Tuple[float, float]:
    return path.points[0] if path.points else (0.0, 0.0)


def _path_end(path: DesignPath) -> Tuple[float, float]:
    return path.points[-1] if path.points else (0.0, 0.0)


def _path_bbox_area(path: DesignPath) -> float:
    if not path.points:
        return 0.0
    xs = [p[0] for p in path.points]
    ys = [p[1] for p in path.points]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def _total_rapid(paths: List[DesignPath]) -> float:
    """Estimate total rapid-travel distance for the current path order."""
    total = 0.0
    cur = (0.0, 0.0)
    for p in paths:
        if p.points:
            s = _path_start(p)
            total += math.hypot(s[0] - cur[0], s[1] - cur[1])
            cur = _path_end(p)
    return total


# ---------------------------------------------------------------------------
# Optimisation result
# ---------------------------------------------------------------------------

@dataclass
class OptimisationResult:
    """Summary of the changes made by :func:`optimize`."""

    original_rapid_mm: float
    optimised_rapid_mm: float
    segments_merged: int
    paths_reordered: bool

    @property
    def rapid_saved_mm(self) -> float:
        return max(0.0, self.original_rapid_mm - self.optimised_rapid_mm)

    @property
    def rapid_saving_pct(self) -> float:
        if self.original_rapid_mm < 1e-9:
            return 0.0
        return self.rapid_saved_mm / self.original_rapid_mm * 100.0


# ---------------------------------------------------------------------------
# Path optimiser
# ---------------------------------------------------------------------------

class PathOptimizer:
    """Collection of heuristic path-improvement algorithms.

    Parameters
    ----------
    merge_tolerance:
        Collinear segments within this angular tolerance (degrees) and
        within *merge_distance* of each other are merged.
    merge_distance:
        Maximum gap (mm) between two segments to merge them.
    inner_first:
        When ``True``, :meth:`sort_by_area` orders smaller-area paths
        (likely inner cuts) before larger ones.
    """

    def __init__(
        self,
        merge_tolerance: float = 1.0,
        merge_distance: float = 0.5,
        inner_first: bool = True,
    ) -> None:
        self.merge_tolerance = merge_tolerance
        self.merge_distance = merge_distance
        self.inner_first = inner_first

    # ------------------------------------------------------------------
    # Public algorithms
    # ------------------------------------------------------------------

    def nearest_neighbour(
        self,
        paths: List[DesignPath],
        start: Tuple[float, float] = (0.0, 0.0),
    ) -> List[DesignPath]:
        """Reorder *paths* with a greedy nearest-neighbour heuristic.

        At each step, pick the unvisited path whose start point is
        closest to the current head position.  Returns a new list; the
        original list is not modified.
        """
        if not paths:
            return []

        remaining = list(paths)
        ordered: List[DesignPath] = []
        cur = start

        while remaining:
            best_idx = 0
            best_dist = math.hypot(
                _path_start(remaining[0])[0] - cur[0],
                _path_start(remaining[0])[1] - cur[1],
            )
            for i in range(1, len(remaining)):
                s = _path_start(remaining[i])
                d = math.hypot(s[0] - cur[0], s[1] - cur[1])
                if d < best_dist:
                    best_dist = d
                    best_idx = i
            chosen = remaining.pop(best_idx)
            ordered.append(chosen)
            cur = _path_end(chosen)

        return ordered

    def merge_short_segments(
        self, paths: List[DesignPath]
    ) -> Tuple[List[DesignPath], int]:
        """Merge collinear adjacent point-pairs within each path.

        Returns ``(new_paths, total_merges)`` where *total_merges* is
        the number of points removed across all paths.
        """
        total_removed = 0
        result: List[DesignPath] = []
        for path in paths:
            new_pts, removed = self._merge_points(path.points)
            total_removed += removed
            result.append(
                DesignPath(
                    points=new_pts,
                    closed=path.closed,
                    power=path.power,
                    speed=path.speed,
                    passes=path.passes,
                )
            )
        return result, total_removed

    def sort_by_area(self, paths: List[DesignPath]) -> List[DesignPath]:
        """Sort paths by bounding-box area.

        When :attr:`inner_first` is ``True`` (default), smaller paths
        come first so inner cuts are made before outer ones, reducing
        the chance of loose pieces shifting.
        """
        return sorted(paths, key=_path_bbox_area, reverse=not self.inner_first)

    def optimize(
        self,
        paths: List[DesignPath],
        start: Tuple[float, float] = (0.0, 0.0),
    ) -> Tuple[List[DesignPath], OptimisationResult]:
        """Apply all optimisation passes and return the improved path list.

        Order of operations:
        1. ``sort_by_area`` (inner first)
        2. ``nearest_neighbour`` reorder
        3. ``merge_short_segments``
        """
        original_rapid = _total_rapid(paths)

        # 1. Sort inner shapes first
        step1 = self.sort_by_area(paths)

        # 2. Nearest-neighbour reorder
        step2 = self.nearest_neighbour(step1, start=start)
        reordered = step2 != paths  # crude check

        # 3. Merge collinear micro-segments
        step3, merged_count = self.merge_short_segments(step2)

        optimised_rapid = _total_rapid(step3)

        result = OptimisationResult(
            original_rapid_mm=original_rapid,
            optimised_rapid_mm=optimised_rapid,
            segments_merged=merged_count,
            paths_reordered=reordered,
        )
        return step3, result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _merge_points(
        self,
        points: List[Tuple[float, float]],
    ) -> Tuple[List[Tuple[float, float]], int]:
        """Merge consecutive collinear points that are within tolerance.

        Returns ``(new_points, removed_count)``.
        """
        if len(points) < 3:
            return list(points), 0

        tol_rad = math.radians(self.merge_tolerance)
        result = [points[0]]
        removed = 0

        for i in range(1, len(points) - 1):
            prev = result[-1]
            curr = points[i]
            nxt = points[i + 1]

            # Vector from prev→curr and curr→nxt
            dx1 = curr[0] - prev[0]
            dy1 = curr[1] - prev[1]
            dx2 = nxt[0] - curr[0]
            dy2 = nxt[1] - curr[1]
            len1 = math.hypot(dx1, dy1)
            len2 = math.hypot(dx2, dy2)

            # Skip tiny segments
            if len1 < self.merge_distance and len2 < self.merge_distance:
                removed += 1
                continue

            # Check collinearity via cross product angle
            if len1 > 1e-9 and len2 > 1e-9:
                cross = dx1 * dy2 - dy1 * dx2
                dot = dx1 * dx2 + dy1 * dy2
                angle = abs(math.atan2(abs(cross), dot))
                if angle < tol_rad:
                    removed += 1
                    continue  # collinear – skip middle point

            result.append(curr)

        result.append(points[-1])
        return result, removed
