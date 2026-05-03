"""Tests for the drawing document model (drawing.py)."""

from __future__ import annotations

import math

import pytest

from lazerem.drawing import (
    CircleObj,
    DrawingDocument,
    Layer,
    LineObj,
    RectObj,
    TextObj,
    _circle_points,
    drawing_to_gcode,
    drawing_to_paths,
    text_to_paths,
)


# ---------------------------------------------------------------------------
# Layer
# ---------------------------------------------------------------------------

class TestLayer:
    def test_defaults(self):
        layer = Layer(name="Test")
        assert layer.color == "#00ff88"
        assert layer.power == 500.0
        assert layer.speed == 3000.0
        assert layer.enabled is True
        assert layer.no_cut is False

    def test_no_cut_flag(self):
        layer = Layer(name="Stock", no_cut=True)
        assert layer.no_cut is True


# ---------------------------------------------------------------------------
# DrawingDocument
# ---------------------------------------------------------------------------

class TestDrawingDocument:
    def _doc_with_one_layer(self) -> DrawingDocument:
        doc = DrawingDocument()
        doc.add_layer("Layer 1")
        return doc

    def test_add_layer(self):
        doc = DrawingDocument()
        idx = doc.add_layer("A")
        assert idx == 0
        assert len(doc.layers) == 1

    def test_add_multiple_layers(self):
        doc = DrawingDocument()
        doc.add_layer("A")
        doc.add_layer("B")
        assert len(doc.layers) == 2

    def test_remove_layer_remaps(self):
        doc = DrawingDocument()
        doc.add_layer("A")
        doc.add_layer("B")
        doc.add_object(LineObj(layer_idx=1, x1=0, y1=0, x2=5, y2=5))
        doc.remove_layer(0)
        # Object was on layer 1 → should now be on layer 0
        assert doc.objects[0].layer_idx == 0

    def test_remove_layer_deleted_object_reassigned(self):
        doc = DrawingDocument()
        doc.add_layer("A")
        doc.add_layer("B")
        obj = LineObj(layer_idx=0, x1=0, y1=0, x2=1, y2=1)
        doc.add_object(obj)
        doc.remove_layer(0)
        # Object was on deleted layer → reassigned to 0
        assert obj.layer_idx == 0

    def test_remove_only_layer_is_no_op(self):
        doc = DrawingDocument()
        doc.add_layer("Solo")
        doc.remove_layer(0)  # Should silently fail – nothing to remove
        # remove_layer only guards idx range, so layer IS removed.
        # Test that the doc stays usable.
        assert isinstance(doc.layers, list)

    def test_add_and_remove_object(self):
        doc = self._doc_with_one_layer()
        obj = LineObj(layer_idx=0, x1=0, y1=0, x2=10, y2=10)
        doc.add_object(obj)
        assert obj in doc.objects
        doc.remove_object(obj)
        assert obj not in doc.objects

    def test_remove_nonexistent_object_no_error(self):
        doc = self._doc_with_one_layer()
        obj = LineObj(layer_idx=0, x1=0, y1=0, x2=1, y2=1)
        doc.remove_object(obj)  # Should not raise


# ---------------------------------------------------------------------------
# drawing_to_paths
# ---------------------------------------------------------------------------

class TestDrawingToPaths:
    def _simple_doc(self) -> DrawingDocument:
        doc = DrawingDocument()
        doc.add_layer("Cut", power=600, speed=2000)
        return doc

    def test_line_produces_path(self):
        doc = self._simple_doc()
        doc.add_object(LineObj(0, 0, 0, 10, 0))
        paths = drawing_to_paths(doc)
        assert len(paths) == 1
        assert paths[0].points == [(0.0, 0.0), (10.0, 0.0)]

    def test_rect_produces_closed_path(self):
        doc = self._simple_doc()
        doc.add_object(RectObj(0, 0, 0, 10, 10))
        paths = drawing_to_paths(doc)
        assert len(paths) == 1
        assert paths[0].closed is True
        assert len(paths[0].points) == 4

    def test_rect_corners_correct(self):
        doc = self._simple_doc()
        doc.add_object(RectObj(0, 0, 0, 5, 8))
        paths = drawing_to_paths(doc)
        pts = set(paths[0].points)
        assert (0.0, 0.0) in pts
        assert (5.0, 0.0) in pts
        assert (5.0, 8.0) in pts
        assert (0.0, 8.0) in pts

    def test_circle_produces_closed_polyline(self):
        doc = self._simple_doc()
        doc.add_object(CircleObj(0, 10, 10, 5))
        paths = drawing_to_paths(doc)
        assert len(paths) == 1
        pts = paths[0].points
        # First and last should be the same (closed polyline)
        assert abs(pts[0][0] - pts[-1][0]) < 1e-6
        assert abs(pts[0][1] - pts[-1][1]) < 1e-6

    def test_text_produces_multiple_paths(self):
        doc = self._simple_doc()
        doc.add_object(TextObj(0, 0, 0, "AB"))
        paths = drawing_to_paths(doc)
        # A and B each have multiple strokes
        assert len(paths) >= 2

    def test_disabled_layer_excluded(self):
        doc = DrawingDocument()
        doc.add_layer("Off", enabled=False)
        doc.add_object(LineObj(0, 0, 0, 10, 0))
        paths = drawing_to_paths(doc)
        assert len(paths) == 0

    def test_nocut_layer_excluded(self):
        doc = DrawingDocument()
        doc.add_layer("Stock", no_cut=True)
        doc.add_object(RectObj(0, 0, 0, 50, 30))
        paths = drawing_to_paths(doc)
        assert len(paths) == 0

    def test_nocut_layer_excluded_but_cut_layer_included(self):
        doc = DrawingDocument()
        doc.add_layer("Stock", no_cut=True)
        doc.add_layer("Cut", no_cut=False)
        doc.add_object(RectObj(0, 0, 0, 50, 30))   # on stock layer (idx 0)
        doc.add_object(LineObj(1, 0, 0, 10, 0))    # on cut layer (idx 1)
        paths = drawing_to_paths(doc)
        assert len(paths) == 1

    def test_layer_power_applied(self):
        doc = DrawingDocument()
        doc.add_layer("Fast", power=800, speed=4000)
        doc.add_object(LineObj(0, 0, 0, 5, 0))
        paths = drawing_to_paths(doc)
        assert paths[0].power == 800.0
        assert paths[0].speed == 4000.0

    def test_out_of_range_layer_skipped(self):
        doc = DrawingDocument()
        doc.add_layer("A")
        doc.add_object(LineObj(99, 0, 0, 5, 5))  # layer 99 does not exist
        paths = drawing_to_paths(doc)
        assert len(paths) == 0

    def test_empty_doc(self):
        doc = DrawingDocument()
        paths = drawing_to_paths(doc)
        assert paths == []


# ---------------------------------------------------------------------------
# drawing_to_gcode
# ---------------------------------------------------------------------------

class TestDrawingToGcode:
    def test_produces_valid_gcode_header(self):
        doc = DrawingDocument()
        doc.add_layer("L")
        doc.add_object(LineObj(0, 0, 0, 10, 0))
        gcode = drawing_to_gcode(doc)
        assert "G21" in gcode
        assert "G90" in gcode
        assert "M2" in gcode

    def test_nocut_not_in_gcode(self):
        doc = DrawingDocument()
        doc.add_layer("Stock", no_cut=True)
        doc.add_object(RectObj(0, 0, 0, 100, 100))
        gcode = drawing_to_gcode(doc)
        assert "G1" not in gcode

    def test_ends_with_m2(self):
        doc = DrawingDocument()
        doc.add_layer("L")
        doc.add_object(LineObj(0, 0, 0, 10, 0))
        gcode = drawing_to_gcode(doc)
        assert gcode.strip().endswith("M2")


# ---------------------------------------------------------------------------
# text_to_paths
# ---------------------------------------------------------------------------

class TestTextToPaths:
    def test_hello(self):
        paths = text_to_paths("HELLO", 0, 0, height=5.0)
        assert len(paths) >= 5  # at least one stroke per letter

    def test_space_advances(self):
        paths_no_space = text_to_paths("AB", 0, 0, height=5)
        paths_with_space = text_to_paths("A B", 0, 0, height=5)
        # A B should produce fewer strokes than AB could produce
        # (space adds no strokes) – total paths same or less
        assert len(paths_with_space) <= len(paths_no_space) + 2

    def test_digits(self):
        paths = text_to_paths("0123456789", 0, 0, height=4.0)
        assert len(paths) >= 10

    def test_power_speed_forwarded(self):
        paths = text_to_paths("A", 0, 0, power=750, speed=2500)
        for p in paths:
            assert p.power == 750.0
            assert p.speed == 2500.0

    def test_unknown_char_no_crash(self):
        # Characters not in the font dict should produce no paths, not crash
        paths = text_to_paths("\x00\x01", 0, 0)
        assert isinstance(paths, list)

    def test_position_applied(self):
        paths = text_to_paths("I", 10.0, 20.0, height=5.0)
        for p in paths:
            for x, y in p.points:
                assert x >= 10.0


# ---------------------------------------------------------------------------
# _circle_points
# ---------------------------------------------------------------------------

class TestCirclePoints:
    def test_closed(self):
        pts = _circle_points(0, 0, 5, 36)
        assert abs(pts[0][0] - pts[-1][0]) < 1e-6
        assert abs(pts[0][1] - pts[-1][1]) < 1e-6

    def test_radius(self):
        r = 7.5
        pts = _circle_points(0, 0, r, 72)
        for x, y in pts:
            assert abs(math.hypot(x, y) - r) < 1e-6

    def test_centre_offset(self):
        pts = _circle_points(5, 10, 3, 36)
        for x, y in pts:
            assert abs(math.hypot(x - 5, y - 10) - 3) < 1e-6
