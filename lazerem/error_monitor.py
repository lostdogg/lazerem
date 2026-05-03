"""Real-time error detection and alerts for the Ray5W laser control.

:class:`ErrorMonitor` runs as a background watchdog that inspects
machine state during a laser run and fires alert callbacks when
anomalies are detected.

Built-in checks
---------------
* **overtravel** – machine moved outside a configurable work area.
* **thermal** – simulated temperature threshold exceeded (based on
  accumulated power × time).
* **stall** – position has not changed for a configurable duration
  while the program is supposedly running.
* **job_interruption** – program stopped unexpectedly (status = ALARM).
* **low_power** – laser power is zero while M3/M4 is active.

Usage::

    from lazerem.error_monitor import ErrorMonitor, Alert

    def handle_alert(alert: Alert):
        print(f"ALERT [{alert.severity}] {alert.code}: {alert.message}")

    monitor = ErrorMonitor(machine, on_alert=handle_alert)
    monitor.start()
    machine.run_program(gcode)  # monitoring runs concurrently
    monitor.stop()
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    """A single error/warning alert emitted by the monitor."""

    code: str                    # e.g. 'OVERTRAVEL', 'THERMAL', 'STALL'
    message: str
    severity: str = "warning"   # 'info', 'warning', 'error', 'critical'
    timestamp: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

class ErrorMonitor:
    """Watchdog that polls machine state and raises alerts.

    Parameters
    ----------
    machine:
        The :class:`~lazerem.machine.LaserMachine` to watch.
    on_alert:
        Callback invoked (from the monitor thread) when an alert fires.
        Signature: ``on_alert(alert: Alert) -> None``.
    poll_interval:
        Seconds between each check (default: 0.1 s).
    work_area:
        ``(max_x, max_y)`` in mm.  Movement outside triggers an
        OVERTRAVEL alert.  ``None`` disables the check.
    thermal_limit:
        Accumulated power-seconds before a THERMAL alert fires.
        Each check accumulates ``laser_power_fraction * poll_interval``.
    stall_timeout:
        Seconds without position change while the program is running
        before a STALL alert fires.  ``None`` disables the check.
    """

    def __init__(
        self,
        machine,
        on_alert: Optional[Callable[[Alert], None]] = None,
        poll_interval: float = 0.1,
        work_area: Optional[tuple] = (400.0, 400.0),
        thermal_limit: float = 60.0,
        stall_timeout: Optional[float] = 5.0,
    ) -> None:
        self._machine = machine
        self._on_alert = on_alert
        self._poll_interval = max(0.01, poll_interval)
        self._work_area = work_area
        self._thermal_limit = thermal_limit
        self._stall_timeout = stall_timeout

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()

        self._thermal_accum: float = 0.0
        self._last_position: Optional[tuple] = None
        self._stall_since: Optional[float] = None
        self._alerted_codes: set = set()

        self.alerts: List[Alert] = []

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background watchdog thread."""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._alerted_codes = set()
        self._thermal_accum = 0.0
        self._last_position = None
        self._stall_since = None
        self.alerts = []
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the watchdog thread."""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None

    def reset(self) -> None:
        """Clear accumulated state and alert history."""
        self._thermal_accum = 0.0
        self._last_position = None
        self._stall_since = None
        self._alerted_codes = set()
        self.alerts = []

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self._poll_interval):
            try:
                self._check_all()
            except Exception:
                pass  # never crash the monitor thread

    def _check_all(self) -> None:
        m = self._machine
        now = time.monotonic()

        # --- ALARM / job interruption ----------------------------------
        if m.status == "ALARM":
            self._emit_once(Alert(
                "JOB_INTERRUPTION",
                "Machine entered ALARM state – job interrupted.",
                severity="critical",
            ))

        if not m.program_running:
            return  # no other checks needed when idle

        # --- Overtravel ------------------------------------------------
        if self._work_area:
            max_x, max_y = self._work_area
            px, py = m.position.x, m.position.y
            if px < -1.0 or px > max_x or py < -1.0 or py > max_y:
                self._emit_once(Alert(
                    "OVERTRAVEL",
                    f"Position ({px:.1f}, {py:.1f}) mm is outside "
                    f"work area ({max_x} × {max_y} mm).",
                    severity="error",
                ))

        # --- Thermal ---------------------------------------------------
        if m.laser_on:
            self._thermal_accum += (
                m.laser_power / m.MAX_POWER * self._poll_interval
            )
        if self._thermal_accum >= self._thermal_limit:
            self._emit_once(Alert(
                "THERMAL",
                f"Thermal accumulation {self._thermal_accum:.1f} s "
                f"exceeded limit {self._thermal_limit:.1f} s – "
                "possible overheating.",
                severity="warning",
            ))

        # --- Stall (position not changing) ----------------------------
        if self._stall_timeout is not None:
            cur_pos = m.position.as_tuple()
            if self._last_position == cur_pos:
                if self._stall_since is None:
                    self._stall_since = now
                elif now - self._stall_since > self._stall_timeout:
                    self._emit_once(Alert(
                        "STALL",
                        f"No position change for {self._stall_timeout:.1f} s "
                        "while program is running.",
                        severity="warning",
                    ))
            else:
                self._stall_since = None
            self._last_position = cur_pos

        # --- Low power while laser claimed to be on -------------------
        if m.laser_on and m.laser_power == 0.0:
            self._emit_once(Alert(
                "LOW_POWER",
                "Laser is armed (M3/M4) but power (S) is 0.",
                severity="info",
            ))

    def _emit_once(self, alert: Alert) -> None:
        """Fire *alert* only once per monitor session (deduplicated by code)."""
        if alert.code in self._alerted_codes:
            return
        self._alerted_codes.add(alert.code)
        self.alerts.append(alert)
        if self._on_alert:
            try:
                self._on_alert(alert)
            except Exception:
                pass
