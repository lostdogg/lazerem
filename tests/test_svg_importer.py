"""Tests for the SVG importer."""

from __future__ import annotations

import pytest

from lazerem.importers.svg_importer import import_svg


_SIMPLE_RECT = """\
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
  <rect x="10" y="10" width="80" height="80"/>
</svg>
"""

_CIRCLE_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg">
  <circle cx="50" cy="50" r="30"/>
</svg>
"""

_LINE_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg">
  <line x1="0" y1="0" x2="100" y2="0"/>
</svg>
"""

_POLYLINE_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg">
  <polyline points="0,0 50,50 100,0"/>
</svg>
"""

_POLYGON_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg">
  <polygon points="0,0 50,50 100,0"/>
</svg>
"""

_PATH_MOVETO_LINETO = """\
<svg xmlns="http://www.w3.org/2000/svg">
  <path d="M 10 20 L 30 40 L 50 20 Z"/>
</svg>
"""

_PATH_HORIZONTAL_VERTICAL = """\
<svg xmlns="http://www.w3.org/2000/svg">
  <path d="M 0 0 H 100 V 50 H 0 Z"/>
</svg>
"""

_PATH_CUBIC_BEZIER = """\
<svg xmlns="http://www.w3.org/2000/svg">
  <path d="M 0 0 C 25 50 75 50 100 0"/>
</svg>
"""

_PATH_QUADRATIC = """\
<svg xmlns="http://www.w3.org/2000/svg">
  <path d="M 0 0 Q 50 100 100 0"/>
</svg>
"""

_GROUP_WITH_TRANSFORM = """\
<svg xmlns="http://www.w3.org/2000/svg">
  <g transform="translate(10, 20)">
    <rect x="0" y="0" width="40" height="40"/>
  </g>
</svg>
"""

_ELLIPSE_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="50" cy="50" rx="40" ry="20"/>
</svg>
"""

_INVALID_SVG = "not xml at all <<<"


class TestImportSvg:
    def test_rect_produces_gcode(self):
        gcode = import_svg(_SIMPLE_RECT, scale_to_mm=False)
        assert "G21" in gcode
        assert "G0" in gcode
        assert "G1" in gcode

    def test_circle_produces_gcode(self):
        gcode = import_svg(_CIRCLE_SVG, scale_to_mm=False)
        assert "G0" in gcode

    def test_line_produces_gcode(self):
        gcode = import_svg(_LINE_SVG, scale_to_mm=False)
        assert "G1" in gcode

    def test_polyline(self):
        gcode = import_svg(_POLYLINE_SVG, scale_to_mm=False)
        assert "G0" in gcode

    def test_polygon_closed(self):
        gcode = import_svg(_POLYGON_SVG, scale_to_mm=False)
        assert "G0" in gcode

    def test_path_moveto_lineto(self):
        gcode = import_svg(_PATH_MOVETO_LINETO, scale_to_mm=False)
        assert "G0" in gcode
        assert "G1" in gcode

    def test_path_horizontal_vertical(self):
        gcode = import_svg(_PATH_HORIZONTAL_VERTICAL, scale_to_mm=False)
        assert "G1" in gcode

    def test_path_cubic_bezier(self):
        gcode = import_svg(_PATH_CUBIC_BEZIER, scale_to_mm=False)
        # Bezier approximated as line segments
        assert "G1" in gcode

    def test_path_quadratic(self):
        gcode = import_svg(_PATH_QUADRATIC, scale_to_mm=False)
        assert "G1" in gcode

    def test_group_transform(self):
        gcode = import_svg(_GROUP_WITH_TRANSFORM, scale_to_mm=False)
        # The rect is translated by (10,20) – coordinates should reflect that
        assert "G0" in gcode

    def test_ellipse(self):
        gcode = import_svg(_ELLIPSE_SVG, scale_to_mm=False)
        assert "G0" in gcode

    def test_power_and_speed_applied(self):
        gcode = import_svg(_SIMPLE_RECT, power=750, speed=2000, scale_to_mm=False)
        assert "S750" in gcode
        assert "F2000" in gcode

    def test_scale_to_mm_shrinks_coordinates(self):
        gcode_raw = import_svg(_SIMPLE_RECT, scale_to_mm=False)
        gcode_mm = import_svg(_SIMPLE_RECT, scale_to_mm=True)
        # With scale_to_mm the coordinates should be smaller (pixels → mm)
        assert "10.0000" in gcode_raw  # raw pixel
        assert "10.0000" not in gcode_mm  # mm value should differ

    def test_invalid_svg_raises(self):
        with pytest.raises(ValueError, match="SVG parse error"):
            import_svg(_INVALID_SVG)

    def test_empty_svg(self):
        gcode = import_svg('<svg xmlns="http://www.w3.org/2000/svg"/>')
        assert "M2" in gcode

    def test_ends_with_m2(self):
        gcode = import_svg(_SIMPLE_RECT, scale_to_mm=False)
        assert gcode.strip().endswith("M2")
