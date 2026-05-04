"""Tests for the G-code translate helper in gcode_utils.py."""

from __future__ import annotations

import pytest

from lazerem.gcode_utils import apply_gcode_translate


class TestApplyGcodeTranslate:
    def test_zero_offset_is_identity(self):
        gcode = "G0 X10 Y20\nG1 X5.5 Y3.2 F3000 S500"
        assert apply_gcode_translate(gcode, 0, 0) == gcode

    def test_x_offset(self):
        result = apply_gcode_translate("G1 X10 Y0", 5, 0)
        assert "X15" in result
        assert "Y0" in result

    def test_y_offset(self):
        result = apply_gcode_translate("G1 X0 Y10", 0, -3)
        assert "X0" in result
        assert "Y7" in result

    def test_both_axes(self):
        result = apply_gcode_translate("G0 X10 Y20", 1, 2)
        assert "X11" in result
        assert "Y22" in result

    def test_negative_coordinates(self):
        result = apply_gcode_translate("G1 X-5 Y-10", 10, 10)
        assert "X5" in result
        assert "Y0" in result

    def test_comments_preserved(self):
        gcode = "G1 X10 Y5 ; move to start"
        result = apply_gcode_translate(gcode, 1, 1)
        assert "; move to start" in result
        # X and Y in code section are translated
        assert "X11" in result
        assert "Y6" in result

    def test_multiline(self):
        gcode = "G0 X0 Y0\nG1 X10 Y0\nG1 X10 Y10"
        result = apply_gcode_translate(gcode, 5, 5)
        lines = result.splitlines()
        assert "X5" in lines[0]
        assert "Y5" in lines[0]
        assert "X15" in lines[1]
        assert "X15" in lines[2] and "Y15" in lines[2]

    def test_decimal_coordinates(self):
        result = apply_gcode_translate("G1 X1.5 Y2.5", 0.5, 0.5)
        # Should have X2 and Y3 (exact format may vary due to rstrip)
        assert "X2" in result
        assert "Y3" in result

    def test_s_value_untouched(self):
        """S (power) word must not be altered by the translate."""
        gcode = "G1 X10 Y10 S500 F3000"
        result = apply_gcode_translate(gcode, 0, 0)
        assert "S500" in result

    def test_f_value_untouched(self):
        """F (feed rate) word must not be altered."""
        gcode = "G1 X0 Y0 F3000"
        result = apply_gcode_translate(gcode, 0, 0)
        assert "F3000" in result
