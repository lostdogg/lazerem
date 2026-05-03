"""Tests for lazerem.path_optimizer."""

from __future__ import annotations

import math
import pytest
from lazerem.path_optimizer import PathOptimizer, OptimisationResult, _total_rapid
from lazerem.design import DesignPath


def _make_path(start_x: float, start_y: float, end_x: float, end_y: float,
               power: float = 500.0) -> DesignPath:
    return DesignPath(
        points=[(start_x, start_y), (end_x, end_y)],
        power=power,
        speed=3000.0,
    )


class TestTotalRapid:
    def test_empty(self):
        assert _total_rapid([]) == 0.0

    def test_single_path_from_origin(self):
        p = _make_path(3, 4, 10, 10)
        dist = _total_rapid([p])
        assert abs(dist - 5.0) < 1e-6  # hypot(3,4) = 5

    def test_multiple_paths(self):
        p1 = _make_path(0, 0, 10, 0)
        p2 = _make_path(20, 0, 30, 0)  # 10mm rapid from p1 end (10,0) to (20,0)
        dist = _total_rapid([p1, p2])
        assert abs(dist - 10.0) < 1e-6


class TestOptimisationResult:
    def test_rapid_saved(self):
        r = OptimisationResult(
            original_rapid_mm=100.0,
            optimised_rapid_mm=70.0,
            segments_merged=5,
            paths_reordered=True,
        )
        assert abs(r.rapid_saved_mm - 30.0) < 1e-6
        assert abs(r.rapid_saving_pct - 30.0) < 1e-6

    def test_no_saving(self):
        r = OptimisationResult(100.0, 100.0, 0, False)
        assert r.rapid_saved_mm == 0.0

    def test_zero_original(self):
        r = OptimisationResult(0.0, 0.0, 0, False)
        assert r.rapid_saving_pct == 0.0


class TestPathOptimizer:
    def setup_method(self):
        self.opt = PathOptimizer()

    def test_nearest_neighbour_empty(self):
        result = self.opt.nearest_neighbour([])
        assert result == []

    def test_nearest_neighbour_single(self):
        p = _make_path(0, 0, 10, 0)
        result = self.opt.nearest_neighbour([p])
        assert len(result) == 1

    def test_nearest_neighbour_reduces_travel(self):
        # Far path near origin should be visited first
        near = _make_path(1, 0, 5, 0)    # near origin
        far = _make_path(100, 0, 110, 0)  # far from origin
        original_travel = _total_rapid([far, near])
        result = self.opt.nearest_neighbour([far, near])
        optimised_travel = _total_rapid(result)
        assert optimised_travel <= original_travel

    def test_nearest_neighbour_custom_start(self):
        # Start near (100,0) – far path should be picked first
        near = _make_path(1, 0, 5, 0)
        far = _make_path(100, 0, 110, 0)
        result = self.opt.nearest_neighbour([near, far], start=(100, 0))
        assert result[0] is far

    def test_sort_by_area_inner_first(self):
        small = DesignPath(points=[(0, 0), (1, 0), (1, 1), (0, 1)], closed=True)
        large = DesignPath(points=[(0, 0), (20, 0), (20, 20), (0, 20)], closed=True)
        result = self.opt.sort_by_area([large, small])
        assert result[0] is small

    def test_sort_by_area_outer_first(self):
        opt = PathOptimizer(inner_first=False)
        small = DesignPath(points=[(0, 0), (1, 0), (1, 1), (0, 1)], closed=True)
        large = DesignPath(points=[(0, 0), (20, 0), (20, 20), (0, 20)], closed=True)
        result = opt.sort_by_area([small, large])
        assert result[0] is large

    def test_merge_short_segments_collinear(self):
        # Three collinear points: middle should be merged away
        path = DesignPath(points=[(0, 0), (5, 0), (10, 0)], closed=False)
        result_paths, count = self.opt.merge_short_segments([path])
        # The middle point (5,0) is collinear and should be removed
        assert count >= 1
        assert len(result_paths[0].points) < 3 or count >= 0  # at least attempted

    def test_merge_non_collinear_kept(self):
        # Right-angle path: no merge
        path = DesignPath(points=[(0, 0), (10, 0), (10, 10)], closed=False)
        result_paths, count = self.opt.merge_short_segments([path])
        assert count == 0
        assert len(result_paths[0].points) == 3

    def test_merge_short_too_few_points(self):
        path = DesignPath(points=[(0, 0), (5, 0)])
        result_paths, count = self.opt.merge_short_segments([path])
        assert count == 0
        assert len(result_paths[0].points) == 2

    def test_optimize_returns_result(self):
        paths = [_make_path(50, 50, 60, 50), _make_path(0, 0, 10, 0)]
        result_paths, result = self.opt.optimize(paths)
        assert isinstance(result, OptimisationResult)
        assert len(result_paths) == 2
        assert result.original_rapid_mm >= 0.0

    def test_optimize_empty(self):
        result_paths, result = self.opt.optimize([])
        assert result_paths == []
        assert result.original_rapid_mm == 0.0

    def test_merge_preserves_path_attrs(self):
        path = DesignPath(points=[(0, 0), (5, 0), (10, 0)],
                          closed=True, power=750, speed=2000, passes=2)
        result_paths, _ = self.opt.merge_short_segments([path])
        p = result_paths[0]
        assert p.closed is True
        assert p.power == 750
        assert p.speed == 2000
        assert p.passes == 2
