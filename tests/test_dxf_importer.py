"""Tests for the DXF importer."""

from __future__ import annotations

import pytest

from lazerem.importers.dxf_importer import import_dxf


def _dxf(entities_block: str) -> str:
    """Wrap an ENTITIES block in a minimal DXF structure."""
    return (
        "  0\nSECTION\n  2\nENTITIES\n"
        + entities_block
        + "  0\nENDSEC\n  0\nEOF\n"
    )


_LINE_DXF = _dxf(
    "  0\nLINE\n  8\n0\n 10\n0.0\n 20\n0.0\n 11\n100.0\n 21\n0.0\n"
)

_ARC_DXF = _dxf(
    "  0\nARC\n  8\n0\n 10\n50.0\n 20\n50.0\n 40\n30.0\n 50\n0.0\n 51\n90.0\n"
)

_CIRCLE_DXF = _dxf(
    "  0\nCIRCLE\n  8\n0\n 10\n25.0\n 20\n25.0\n 40\n10.0\n"
)

_LWPOLYLINE_DXF = (
    "  0\nSECTION\n  2\nENTITIES\n"
    "  0\nLWPOLYLINE\n  8\n0\n 90\n3\n 70\n0\n"
    " 10\n0.0\n 20\n0.0\n"
    " 10\n50.0\n 20\n0.0\n"
    " 10\n50.0\n 20\n50.0\n"
    "  0\nENDSEC\n  0\nEOF\n"
)

_EMPTY_DXF = _dxf("")

_NO_SECTION_DXF = "random content\n0\nEOF"


class TestImportDxf:
    def test_line_produces_gcode(self):
        gcode = import_dxf(_LINE_DXF)
        assert "G21" in gcode
        assert "G0" in gcode
        assert "G1" in gcode

    def test_arc_produces_gcode(self):
        gcode = import_dxf(_ARC_DXF)
        assert "G1" in gcode

    def test_circle_produces_gcode(self):
        gcode = import_dxf(_CIRCLE_DXF)
        assert "G1" in gcode

    def test_lwpolyline_produces_gcode(self):
        gcode = import_dxf(_LWPOLYLINE_DXF)
        assert "G0" in gcode or "G1" in gcode

    def test_empty_entities(self):
        gcode = import_dxf(_EMPTY_DXF)
        assert "M2" in gcode

    def test_no_entities_section(self):
        gcode = import_dxf(_NO_SECTION_DXF)
        assert "M2" in gcode

    def test_power_applied(self):
        gcode = import_dxf(_LINE_DXF, power=800)
        assert "S800" in gcode

    def test_scale_applied(self):
        gcode_no_scale = import_dxf(_LINE_DXF, scale=1.0)
        gcode_scaled = import_dxf(_LINE_DXF, scale=25.4)
        # With scale=25.4 the end point X=100 becomes X=2540
        assert "2540.0000" in gcode_scaled
        assert "2540.0000" not in gcode_no_scale

    def test_ends_with_m2(self):
        gcode = import_dxf(_LINE_DXF)
        assert gcode.strip().endswith("M2")

    def test_arc_creates_multiple_points(self):
        """Arc should be approximated with more than two points."""
        gcode = import_dxf(_ARC_DXF)
        g1_lines = [l for l in gcode.splitlines() if l.startswith("G1")]
        assert len(g1_lines) > 2
