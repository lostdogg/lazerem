"""Tests for lazerem.layer_effects."""

from __future__ import annotations

import pytest
from lazerem.layer_effects import gradient_fill, texture_fill, variable_power_curve


class TestGradientFill:
    def test_returns_string(self):
        g = gradient_fill(0, 0, 10, 10)
        assert isinstance(g, str)

    def test_starts_with_preamble(self):
        g = gradient_fill(0, 0, 10, 10)
        assert "G21" in g
        assert "G90" in g

    def test_ends_with_m2(self):
        g = gradient_fill(0, 0, 10, 10)
        assert g.strip().endswith("M2")

    def test_m3_present(self):
        g = gradient_fill(0, 0, 10, 10)
        assert "M3" in g

    def test_m5_present(self):
        g = gradient_fill(0, 0, 10, 10)
        assert "M5" in g

    def test_power_range_applied(self):
        g = gradient_fill(0, 0, 20, 20,
                          power_start=200, power_end=800,
                          line_spacing=1.0)
        assert "S200" in g or "S201" in g or "S199" in g
        # At least one S value should be close to 800
        assert any(f"S{v}" in g for v in range(790, 810))

    def test_y_axis_orientation(self):
        g = gradient_fill(0, 0, 10, 10, axis="y", line_spacing=1.0)
        assert isinstance(g, str)
        assert "M2" in g

    def test_swapped_coords_normalised(self):
        # Should not crash when x0 > x1
        g = gradient_fill(10, 10, 0, 0)
        assert "M2" in g

    def test_single_line(self):
        g = gradient_fill(0, 0, 1, 1, line_spacing=10.0)
        assert "M2" in g


class TestTextureFill:
    def test_dot_pattern(self):
        g = texture_fill(0, 0, 10, 10, pattern="dot")
        assert "M2" in g
        assert "G1" in g

    def test_line_pattern(self):
        g = texture_fill(0, 0, 10, 10, pattern="line")
        assert "M2" in g

    def test_cross_pattern(self):
        g = texture_fill(0, 0, 10, 10, pattern="cross")
        assert "M2" in g

    def test_invalid_pattern(self):
        with pytest.raises(ValueError):
            texture_fill(0, 0, 10, 10, pattern="zigzag")

    def test_power_applied(self):
        g = texture_fill(0, 0, 5, 5, pattern="dot", power=750)
        assert "S750" in g

    def test_speed_applied(self):
        g = texture_fill(0, 0, 5, 5, pattern="line", speed=2500)
        assert "F2500" in g

    def test_swapped_coords(self):
        g = texture_fill(10, 10, 0, 0, pattern="dot")
        assert "M2" in g


class TestVariablePowerCurve:
    def test_basic(self):
        pts = [(0, 0), (10, 0), (10, 10)]
        g = variable_power_curve(pts, power_curve=lambda t: 500.0)
        assert "M2" in g
        assert "G1" in g

    def test_too_few_points(self):
        with pytest.raises(ValueError):
            variable_power_curve([(0, 0)], power_curve=lambda t: 500.0)

    def test_power_varies(self):
        pts = [(0, 0), (10, 0)]
        g = variable_power_curve(pts, power_curve=lambda t: t * 1000.0, samples=10)
        lines = g.splitlines()
        s_values = []
        for line in lines:
            if "S" in line:
                for tok in line.split():
                    if tok.startswith("S"):
                        try:
                            s_values.append(int(tok[1:]))
                        except ValueError:
                            pass
        # Should have a range of S values
        assert len(set(s_values)) > 1

    def test_speed_applied(self):
        pts = [(0, 0), (5, 5)]
        g = variable_power_curve(pts, power_curve=lambda t: 500.0, speed=2000)
        assert "F2000" in g

    def test_ends_with_m2(self):
        pts = [(0, 0), (10, 0)]
        g = variable_power_curve(pts, power_curve=lambda t: 500.0)
        assert g.strip().endswith("M2")
