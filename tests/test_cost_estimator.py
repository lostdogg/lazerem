"""Tests for lazerem.cost_estimator."""

from __future__ import annotations

import pytest
from lazerem.cost_estimator import CostEstimator, CostReport
from lazerem.machine import BurnSegment, LaserMachine


def _cut(x1, y1, x2, y2, power=0.5):
    return BurnSegment("cut", (x1, y1), (x2, y2), power=power)


def _rapid(x1, y1, x2, y2):
    return BurnSegment("rapid", (x1, y1), (x2, y2), power=0.0)


class TestCostReport:
    def test_total_cost(self):
        r = CostReport(
            time_seconds=60,
            cut_length_mm=100,
            rapid_length_mm=20,
            engraved_area_mm2=10,
            electricity_kwh=0.001,
            electricity_cost=0.0015,
            material_cost=0.05,
        )
        assert abs(r.total_cost - 0.0515) < 1e-9

    def test_time_minutes(self):
        r = CostReport(120, 0, 0, 0, 0, 0, 0)
        assert r.time_minutes == 2.0

    def test_engraved_area_cm2(self):
        r = CostReport(0, 0, 0, 200, 0, 0, 0)
        assert r.engraved_area_cm2 == 2.0

    def test_summary_contains_fields(self):
        r = CostReport(60, 100, 20, 10, 0.001, 0.002, 0.05)
        s = r.summary()
        assert "Time" in s
        assert "Cost" in s
        assert "Energy" in s


class TestCostEstimator:
    def setup_method(self):
        self.est = CostEstimator(
            machine_watts=40.0,
            cost_per_kwh=0.15,
            material_cost_per_cm2=0.05,
            rapid_speed=5000.0,
            beam_width_mm=0.1,
        )

    def test_empty_path(self):
        report = self.est.estimate([])
        assert report.time_seconds == 0.0
        assert report.cut_length_mm == 0.0
        assert report.rapid_length_mm == 0.0
        assert report.total_cost == 0.0

    def test_single_cut_segment(self):
        segs = [_cut(0, 0, 10, 0)]  # 10 mm cut
        report = self.est.estimate(segs, feed_rate=3000.0)
        assert abs(report.cut_length_mm - 10.0) < 1e-6
        assert report.rapid_length_mm == 0.0
        assert report.engraved_area_mm2 > 0.0

    def test_single_rapid_segment(self):
        segs = [_rapid(0, 0, 10, 0)]
        report = self.est.estimate(segs, feed_rate=3000.0)
        assert report.cut_length_mm == 0.0
        assert abs(report.rapid_length_mm - 10.0) < 1e-6

    def test_time_calculated_correctly(self):
        # 60 mm at 3000 mm/min = 60/3000 min = 1.2 s
        segs = [_cut(0, 0, 60, 0)]
        report = self.est.estimate(segs, feed_rate=3000.0)
        assert abs(report.time_seconds - 1.2) < 0.01

    def test_arc_segment_uses_arc_points(self):
        seg = BurnSegment(
            "arc_cw", (0, 0), (10, 0), power=0.5,
            arc_points=[(0, 0), (5, 5), (10, 0)],
        )
        report = self.est.estimate([seg], feed_rate=3000.0)
        # Arc length should be longer than straight 10mm
        assert report.cut_length_mm > 10.0

    def test_electricity_cost_positive(self):
        segs = [_cut(0, 0, 100, 0)]
        report = self.est.estimate(segs, feed_rate=1000.0)
        assert report.electricity_kwh > 0.0
        assert report.electricity_cost > 0.0

    def test_material_cost_positive(self):
        segs = [_cut(0, 0, 100, 0)]
        report = self.est.estimate(segs, feed_rate=3000.0)
        assert report.material_cost >= 0.0

    def test_from_gcode(self):
        gcode = "G21 G90\nG0 X0 Y0\nM3 S500\nG1 X40 F3000\nG1 Y40\nM5\nM2\n"
        report = self.est.estimate_from_gcode(gcode, feed_rate=3000.0)
        assert report.cut_length_mm > 0.0
        assert report.time_seconds > 0.0

    def test_currency_label(self):
        est = CostEstimator(currency="EUR")
        report = est.estimate([], 3000.0)
        assert report.currency == "EUR"
        assert "EUR" in report.summary()

    def test_zero_feed_does_not_crash(self):
        # feed_rate 0 should be clamped to 1 internally
        segs = [_cut(0, 0, 10, 0)]
        report = self.est.estimate(segs, feed_rate=0.0)
        assert report.time_seconds > 0.0
