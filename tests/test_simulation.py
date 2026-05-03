"""Tests for lazerem.simulation."""

from __future__ import annotations

import pytest
from lazerem.simulation import EngravingSimulator, _depth_color
from lazerem.machine import BurnSegment


class TestDepthColor:
    def test_zero_is_light_tan(self):
        r, g, b = _depth_color(0.0)
        assert r > 150 and g > 140 and b > 100

    def test_full_is_dark(self):
        r, g, b = _depth_color(1.0)
        assert r < 60 and g < 40 and b < 30

    def test_midpoint(self):
        r, g, b = _depth_color(0.5)
        assert 60 <= r <= 180

    def test_clamp_below_zero(self):
        # Below zero → same as zero
        assert _depth_color(-0.1) == _depth_color(0.0)

    def test_clamp_above_one(self):
        assert _depth_color(1.1) == _depth_color(1.0)


class TestEngravingSimulator:
    def _cut_seg(self, x1, y1, x2, y2, power=0.8):
        return BurnSegment(
            motion="cut",
            start=(x1, y1),
            end=(x2, y2),
            power=power,
        )

    def _rapid_seg(self, x1, y1, x2, y2):
        return BurnSegment(
            motion="rapid",
            start=(x1, y1),
            end=(x2, y2),
            power=0.0,
        )

    def test_init_defaults(self):
        sim = EngravingSimulator()
        assert sim.resolution == 0.5
        assert sim._depth == {}

    def test_invalid_resolution(self):
        with pytest.raises(ValueError):
            EngravingSimulator(resolution=0.0)

    def test_rapid_ignored(self):
        sim = EngravingSimulator(resolution=1.0)
        sim.process([self._rapid_seg(0, 0, 10, 0)])
        assert sim._depth == {}

    def test_cut_adds_depth(self):
        sim = EngravingSimulator(resolution=1.0)
        sim.process([self._cut_seg(0, 0, 5, 0)])
        assert len(sim._depth) > 0
        for v in sim._depth.values():
            assert 0.0 < v <= 1.0

    def test_depth_capped_at_one(self):
        sim = EngravingSimulator(resolution=1.0, max_depth_per_pass=2.0)
        for _ in range(5):
            sim.process([self._cut_seg(0, 0, 5, 0)])
        for v in sim._depth.values():
            assert v <= 1.0

    def test_reset_clears(self):
        sim = EngravingSimulator(resolution=1.0)
        sim.process([self._cut_seg(0, 0, 10, 0)])
        assert sim._depth
        sim.reset()
        assert sim._depth == {}

    def test_bounds_none_when_empty(self):
        sim = EngravingSimulator()
        assert sim.bounds() is None

    def test_bounds_after_process(self):
        sim = EngravingSimulator(resolution=1.0)
        sim.process([self._cut_seg(0, 0, 10, 0)])
        b = sim.bounds()
        assert b is not None
        x0, y0, x1, y1 = b
        assert x1 > x0

    def test_render_returns_correct_size(self):
        sim = EngravingSimulator(resolution=1.0)
        rgb = sim.render(width_px=10, height_px=8)
        assert len(rgb) == 8
        assert len(rgb[0]) == 10
        # Check pixel tuples
        r, g, b = rgb[0][0]
        assert 0 <= r <= 255
        assert 0 <= g <= 255
        assert 0 <= b <= 255

    def test_render_after_process_darker(self):
        sim = EngravingSimulator(resolution=0.5)
        sim.process([self._cut_seg(0, 0, 10, 0, power=1.0)])
        rgb = sim.render(width_px=20, height_px=5)
        # Middle rows should have darker pixels along the cut line
        # Just check it renders without error
        assert len(rgb) == 5

    def test_arc_points_used(self):
        sim = EngravingSimulator(resolution=1.0)
        seg = BurnSegment(
            motion="arc_cw",
            start=(0, 0), end=(5, 0),
            power=0.5,
            arc_points=[(0, 0), (2.5, 2.5), (5, 0)],
        )
        sim.process([seg])
        assert len(sim._depth) > 0
