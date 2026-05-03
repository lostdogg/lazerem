"""Tests for lazerem.error_monitor."""

from __future__ import annotations

import time
import pytest
from lazerem.error_monitor import ErrorMonitor, Alert
from lazerem.machine import LaserMachine


class TestAlert:
    def test_defaults(self):
        a = Alert("TEST", "Something happened")
        assert a.severity == "warning"
        assert a.code == "TEST"
        assert a.message == "Something happened"
        assert a.timestamp > 0

    def test_custom_severity(self):
        a = Alert("ERR", "bad", severity="critical")
        assert a.severity == "critical"


class TestErrorMonitor:
    def test_start_stop(self):
        m = LaserMachine()
        monitor = ErrorMonitor(m)
        monitor.start()
        assert monitor._running
        monitor.stop()
        assert not monitor._running

    def test_double_start_noop(self):
        m = LaserMachine()
        monitor = ErrorMonitor(m)
        monitor.start()
        t1 = monitor._thread
        monitor.start()  # should not start second thread
        assert monitor._thread is t1
        monitor.stop()

    def test_alarm_detected(self):
        """ALARM status triggers JOB_INTERRUPTION alert."""
        m = LaserMachine()
        alerts = []
        monitor = ErrorMonitor(m, on_alert=lambda a: alerts.append(a),
                               poll_interval=0.01)
        m.status = "ALARM"
        monitor.start()
        time.sleep(0.15)
        monitor.stop()
        codes = [a.code for a in alerts]
        assert "JOB_INTERRUPTION" in codes

    def test_overtravel_detected(self):
        m = LaserMachine()
        m.program_running = True
        m.position.x = 500.0  # outside default 400mm work area
        m.position.y = 10.0
        alerts = []
        monitor = ErrorMonitor(m, on_alert=lambda a: alerts.append(a),
                               poll_interval=0.01, work_area=(400.0, 400.0))
        monitor.start()
        time.sleep(0.15)
        monitor.stop()
        codes = [a.code for a in alerts]
        assert "OVERTRAVEL" in codes

    def test_no_overtravel_within_bounds(self):
        m = LaserMachine()
        m.program_running = True
        m.position.x = 10.0
        m.position.y = 10.0
        alerts = []
        monitor = ErrorMonitor(m, on_alert=lambda a: alerts.append(a),
                               poll_interval=0.01, work_area=(400.0, 400.0))
        monitor.start()
        time.sleep(0.15)
        monitor.stop()
        overtravel = [a for a in alerts if a.code == "OVERTRAVEL"]
        assert overtravel == []

    def test_low_power_alert(self):
        m = LaserMachine()
        m.program_running = True
        m.laser_on = True
        m.laser_power = 0.0
        alerts = []
        monitor = ErrorMonitor(m, on_alert=lambda a: alerts.append(a),
                               poll_interval=0.01, work_area=None,
                               stall_timeout=None)
        monitor.start()
        time.sleep(0.15)
        monitor.stop()
        codes = [a.code for a in alerts]
        assert "LOW_POWER" in codes

    def test_alert_fires_only_once(self):
        m = LaserMachine()
        m.status = "ALARM"
        alerts = []
        monitor = ErrorMonitor(m, on_alert=lambda a: alerts.append(a),
                               poll_interval=0.01)
        monitor.start()
        time.sleep(0.3)
        monitor.stop()
        interruption_alerts = [a for a in alerts if a.code == "JOB_INTERRUPTION"]
        assert len(interruption_alerts) == 1  # deduplicated

    def test_reset_clears_state(self):
        m = LaserMachine()
        alerts = []
        monitor = ErrorMonitor(m, on_alert=lambda a: alerts.append(a))
        m.status = "ALARM"
        monitor.start()
        time.sleep(0.15)
        monitor.stop()
        monitor.reset()
        assert monitor.alerts == []
        assert monitor._alerted_codes == set()

    def test_work_area_none_disables_check(self):
        m = LaserMachine()
        m.program_running = True
        m.position.x = 9999.0
        alerts = []
        monitor = ErrorMonitor(m, on_alert=lambda a: alerts.append(a),
                               poll_interval=0.01, work_area=None,
                               stall_timeout=None)
        monitor.start()
        time.sleep(0.15)
        monitor.stop()
        overtravel = [a for a in alerts if a.code == "OVERTRAVEL"]
        assert overtravel == []
