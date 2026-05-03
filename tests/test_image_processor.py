"""Tests for the image processor (no display required)."""

from __future__ import annotations

import pytest

from lazerem.image_processor import (
    _dither_floyd_steinberg,
    _dither_jarvis,
    _dither_threshold,
    adjust_brightness,
    adjust_contrast,
    adjust_saturation,
    to_grayscale,
    trace_image,
)


def _white_grid(w: int = 4, h: int = 4):
    return [[(255, 255, 255)] * w for _ in range(h)]


def _black_grid(w: int = 4, h: int = 4):
    return [[(0, 0, 0)] * w for _ in range(h)]


def _checkerboard(w: int = 4, h: int = 4):
    return [
        [((255, 255, 255) if (x + y) % 2 == 0 else (0, 0, 0)) for x in range(w)]
        for y in range(h)
    ]


class TestToGrayscale:
    def test_white_is_1(self):
        grid = _white_grid(2, 2)
        gray = to_grayscale(grid)
        for row in gray:
            for v in row:
                assert abs(v - 255.0) < 1.0  # near 255

    def test_black_is_0(self):
        grid = _black_grid(2, 2)
        gray = to_grayscale(grid)
        for row in gray:
            for v in row:
                assert v < 1.0

    def test_shape_preserved(self):
        grid = _checkerboard(6, 5)
        gray = to_grayscale(grid)
        assert len(gray) == 5
        assert len(gray[0]) == 6


class TestAdjustBrightness:
    def test_double_brightness(self):
        grid = [[(100, 100, 100)]]
        result = adjust_brightness(grid, 2.0)
        r, g, b = result[0][0]
        assert r == 200 and g == 200 and b == 200

    def test_clamp_at_255(self):
        grid = [[(200, 200, 200)]]
        result = adjust_brightness(grid, 2.0)
        r, g, b = result[0][0]
        assert r == 255

    def test_zero_brightness(self):
        grid = [[(200, 100, 50)]]
        result = adjust_brightness(grid, 0.0)
        assert result[0][0] == (0, 0, 0)


class TestAdjustContrast:
    def test_neutral(self):
        grid = [[(128, 128, 128)]]
        result = adjust_contrast(grid, 1.0)
        # Mid-grey should remain near 128
        r, g, b = result[0][0]
        assert abs(r - 128) <= 1

    def test_high_contrast_brightens_light(self):
        grid = [[(200, 200, 200)]]
        result = adjust_contrast(grid, 2.0)
        r, g, b = result[0][0]
        assert r > 200  # increased

    def test_zero_contrast_all_gray(self):
        grid = [[(50, 150, 200)]]
        result = adjust_contrast(grid, 0.0)
        r, g, b = result[0][0]
        assert r == g == b == 128


class TestAdjustSaturation:
    def test_zero_saturation_is_gray(self):
        grid = [[(200, 100, 50)]]
        result = adjust_saturation(grid, 0.0)
        r, g, b = result[0][0]
        # All channels should be equal (greyscale)
        assert r == g == b

    def test_neutral_unchanged(self):
        grid = [[(255, 0, 0)]]
        result = adjust_saturation(grid, 1.0)
        r, g, b = result[0][0]
        assert r > g and r > b  # red stays dominant

    def test_grey_pixel_unchanged_by_saturation(self):
        grid = [[(128, 128, 128)]]
        result = adjust_saturation(grid, 2.0)
        r, g, b = result[0][0]
        assert r == g == b  # grey has no hue to boost


class TestDithering:
    def _gray(self, w: int = 4, h: int = 4, value: float = 0.5):
        return [[value] * w for _ in range(h)]

    def test_threshold_white_not_engraved(self):
        gray = self._gray(4, 4, value=0.9)
        bitmap = _dither_threshold(gray, threshold=0.5)
        for row in bitmap:
            assert all(not v for v in row)

    def test_threshold_black_engraved(self):
        gray = self._gray(4, 4, value=0.1)
        bitmap = _dither_threshold(gray, threshold=0.5)
        for row in bitmap:
            assert all(v for v in row)

    def test_floyd_steinberg_shape(self):
        gray = self._gray(8, 8, value=0.5)
        bitmap = _dither_floyd_steinberg(gray, threshold=0.5)
        assert len(bitmap) == 8 and len(bitmap[0]) == 8

    def test_jarvis_shape(self):
        gray = self._gray(8, 8, value=0.5)
        bitmap = _dither_jarvis(gray, threshold=0.5)
        assert len(bitmap) == 8 and len(bitmap[0]) == 8


class TestTraceImage:
    def test_white_image_no_cuts(self):
        grid = _white_grid(10, 10)
        gcode = trace_image(grid, mode="threshold", threshold=0.5)
        assert "G21" in gcode
        # No G1 cuts for white image
        assert "G1" not in gcode

    def test_black_image_has_cuts(self):
        grid = _black_grid(4, 4)
        gcode = trace_image(grid, mode="threshold", threshold=0.5)
        assert "G1" in gcode

    def test_power_in_gcode(self):
        grid = _black_grid(4, 4)
        gcode = trace_image(grid, power=800, speed=2000)
        assert "S800" in gcode

    def test_floyd_steinberg_mode(self):
        grid = _checkerboard(8, 8)
        gcode = trace_image(grid, mode="floyd-steinberg")
        assert "G21" in gcode

    def test_jarvis_mode(self):
        grid = _checkerboard(8, 8)
        gcode = trace_image(grid, mode="jarvis")
        assert "G21" in gcode

    def test_ends_with_m2(self):
        grid = _white_grid(4, 4)
        gcode = trace_image(grid)
        assert gcode.strip().endswith("M2")
