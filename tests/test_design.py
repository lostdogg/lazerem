"""Tests for design operations (offset, array, nesting, boolean, gcode)."""

from __future__ import annotations

import math

import pytest

from lazerem.design import (
    DesignPath,
    array_path,
    boolean_difference,
    boolean_union,
    nest_paths,
    offset_path,
    paths_to_gcode,
)


class TestDesignPath:
    def test_empty(self):
        p = DesignPath()
        assert p.points == []
        assert p.closed is False

    def test_with_points(self):
        pts = [(0, 0), (10, 0), (10, 10), (0, 10)]
        p = DesignPath(pts, closed=True, power=800, speed=1200, passes=2)
        assert len(p.points) == 4
        assert p.power == 800
        assert p.passes == 2


class TestOffsetPath:
    def _square(self, side: float = 10.0) -> DesignPath:
        return DesignPath(
            [(0, 0), (side, 0), (side, side), (0, side)],
            closed=True,
        )

    def test_expand_increases_area(self):
        sq = self._square(10.0)
        offset = offset_path(sq, 1.0)
        # After expanding by 1 mm the x coordinates should be larger
        xs = [p[0] for p in offset.points]
        assert max(xs) > 10.0

    def test_shrink_decreases_area(self):
        sq = self._square(10.0)
        offset = offset_path(sq, -1.0)
        xs = [p[0] for p in offset.points]
        assert max(xs) < 10.0

    def test_zero_offset_unchanged(self):
        sq = self._square(10.0)
        offset = offset_path(sq, 0.0)
        # With zero offset the set of coordinates should be unchanged
        # (order may rotate by one due to miter-join indexing)
        orig_xs = {round(p[0], 6) for p in sq.points}
        orig_ys = {round(p[1], 6) for p in sq.points}
        new_xs = {round(p[0], 6) for p in offset.points}
        new_ys = {round(p[1], 6) for p in offset.points}
        assert orig_xs == new_xs
        assert orig_ys == new_ys

    def test_single_point_no_crash(self):
        p = DesignPath([(5, 5)], closed=False)
        result = offset_path(p, 1.0)
        assert result.points == [(5, 5)]

    def test_open_path(self):
        p = DesignPath([(0, 0), (10, 0), (10, 10)], closed=False)
        result = offset_path(p, 1.0)
        assert len(result.points) >= 3


class TestArrayPath:
    def _unit_path(self) -> DesignPath:
        return DesignPath([(0, 0), (5, 0), (5, 5), (0, 5)], closed=True)

    def test_1x1_array(self):
        p = self._unit_path()
        result = array_path(p, cols=1, rows=1, x_spacing=10, y_spacing=10)
        assert len(result) == 1
        assert result[0].points == p.points

    def test_3x3_array_count(self):
        p = self._unit_path()
        result = array_path(p, cols=3, rows=3, x_spacing=10, y_spacing=10)
        assert len(result) == 9

    def test_spacing_applied(self):
        p = DesignPath([(0, 0), (1, 0)])
        result = array_path(p, cols=2, rows=2, x_spacing=20, y_spacing=30)
        # Second column should be shifted 20 in X
        col1 = result[1]  # row0, col1
        assert abs(col1.points[0][0] - 20) < 1e-9
        # Second row should be shifted 30 in Y
        row1 = result[2]  # row1, col0
        assert abs(row1.points[0][1] - 30) < 1e-9

    def test_preserves_power(self):
        p = DesignPath([(0, 0), (1, 0)], power=777)
        result = array_path(p, 2, 2, 10, 10)
        for r in result:
            assert r.power == 777


class TestNestPaths:
    def _box(self, w: float, h: float, ox: float = 0.0, oy: float = 0.0) -> DesignPath:
        return DesignPath(
            [(ox, oy), (ox + w, oy), (ox + w, oy + h), (ox, oy + h)],
            closed=True,
        )

    def test_single_fits(self):
        p = self._box(50, 50)
        result = nest_paths([p], sheet_width=200, sheet_height=200, gap=2)
        assert len(result) == 1
        bx = [pt[0] for pt in result[0].points]
        by = [pt[1] for pt in result[0].points]
        assert min(bx) >= 0
        assert min(by) >= 0
        assert max(bx) <= 200
        assert max(by) <= 200

    def test_multiple_fit(self):
        boxes = [self._box(50, 50) for _ in range(4)]
        result = nest_paths(boxes, sheet_width=250, sheet_height=250, gap=2)
        assert len(result) == 4

    def test_too_wide_placed_as_is(self):
        p = self._box(500, 50)
        result = nest_paths([p], sheet_width=200, sheet_height=200)
        assert len(result) == 1
        # Should be returned untranslated (original position)
        assert result[0].points == p.points

    def test_empty_list(self):
        assert nest_paths([], 200, 200) == []


class TestBooleanOps:
    def _square(self) -> DesignPath:
        return DesignPath([(0, 0), (10, 0), (10, 10), (0, 10)], closed=True)

    def test_union_combines(self):
        a = [self._square()]
        b = [DesignPath([(5, 5), (15, 5), (15, 15)], closed=True)]
        result = boolean_union(a, b)
        assert len(result) == 2

    def test_union_empty(self):
        assert boolean_union([], []) == []

    def test_difference_empty_subject(self):
        clip = self._square()
        result = boolean_difference(
            DesignPath([], closed=True), clip
        )
        # Degenerate – should not crash, return subject
        assert isinstance(result, list)

    def test_difference_returns_list(self):
        sq = self._square()
        clip = DesignPath([(2, 2), (8, 2), (8, 8), (2, 8)], closed=True)
        result = boolean_difference(sq, clip)
        assert isinstance(result, list)


class TestPathsToGcode:
    def test_empty_paths(self):
        gcode = paths_to_gcode([])
        assert "G21" in gcode
        assert "M2" in gcode

    def test_single_path(self):
        p = DesignPath([(0, 0), (10, 0), (10, 10)], power=500, speed=3000)
        gcode = paths_to_gcode([p])
        assert "G0" in gcode
        assert "G1" in gcode
        assert "M3 S500" in gcode
        assert "M5" in gcode

    def test_closed_path_closes(self):
        p = DesignPath([(0, 0), (10, 0), (10, 10)], closed=True, power=500, speed=3000)
        gcode = paths_to_gcode([p])
        # Should return to first point
        assert "0.0000" in gcode

    def test_global_override(self):
        p = DesignPath([(0, 0), (1, 0)], power=100, speed=100)
        gcode = paths_to_gcode([p], power=999, speed=4000)
        assert "S999" in gcode
        assert "F4000" in gcode

    def test_multiple_passes(self):
        p = DesignPath([(0, 0), (10, 0)], power=500, speed=3000, passes=3)
        gcode = paths_to_gcode([p])
        # M3 should appear 3 times (once per pass)
        assert gcode.count("M3 S500") == 3
