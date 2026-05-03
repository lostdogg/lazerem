"""Job cost estimator for the Ray5W laser control.

Estimates the time, material usage, and financial cost of a laser job
from a parsed burn path.

Calculations
------------
* **Time** – derived from each segment's Euclidean length divided by the
  machine's ``feed_rate``.  Rapid moves are assumed to run at
  ``rapid_speed`` mm/min (default 5000).
* **Engraved area** – sum of (laser beam width) × (segment length) for
  all power-on segments.  Beam width is configurable.
* **Electricity cost** – laser power fraction × machine wattage ×
  time_hours × cost_per_kwh.
* **Material cost** – engraved area (cm²) × cost_per_cm2.

Usage::

    from lazerem.cost_estimator import CostEstimator, CostReport

    est = CostEstimator(machine_watts=40.0, cost_per_kwh=0.15,
                        material_cost_per_cm2=0.05)
    report = est.estimate(machine.burn_path, machine.feed_rate)
    print(report.summary())
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

from .machine import BurnSegment


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class CostReport:
    """Results of a cost estimation run."""

    time_seconds: float           # total estimated job time
    cut_length_mm: float          # total laser-on travel distance
    rapid_length_mm: float        # total laser-off rapid travel
    engraved_area_mm2: float      # estimated area engraved
    electricity_kwh: float        # energy consumed
    electricity_cost: float       # in currency units
    material_cost: float          # in currency units
    currency: str = "USD"

    @property
    def total_cost(self) -> float:
        return self.electricity_cost + self.material_cost

    @property
    def time_minutes(self) -> float:
        return self.time_seconds / 60.0

    @property
    def engraved_area_cm2(self) -> float:
        return self.engraved_area_mm2 / 100.0

    def summary(self) -> str:
        lines = [
            "── Job Cost Estimate ───────────────",
            f"  Time          : {self.time_minutes:.1f} min"
                f"  ({self.time_seconds:.0f} s)",
            f"  Cut length    : {self.cut_length_mm:.1f} mm",
            f"  Rapid travel  : {self.rapid_length_mm:.1f} mm",
            f"  Engraved area : {self.engraved_area_cm2:.2f} cm²",
            f"  Energy        : {self.electricity_kwh * 1000:.1f} Wh",
            f"  Electricity   : {self.currency} "
                f"{self.electricity_cost:.4f}",
            f"  Material      : {self.currency} "
                f"{self.material_cost:.4f}",
            f"  ─────────────────────────────────",
            f"  TOTAL COST    : {self.currency} "
                f"{self.total_cost:.4f}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Estimator
# ---------------------------------------------------------------------------

class CostEstimator:
    """Compute time, energy, and monetary cost of a laser job.

    Parameters
    ----------
    machine_watts:
        Electrical power draw of the laser machine in Watts.  This is
        the *wall-socket* power, not just the diode output.
    cost_per_kwh:
        Electricity price in the chosen currency per kWh.
    material_cost_per_cm2:
        Material price in the chosen currency per cm².
    rapid_speed:
        Assumed feed rate for G0 (rapid) moves in mm/min.
    beam_width_mm:
        Effective laser beam width in mm, used to calculate engraved
        area as ``beam_width × cut_length``.
    currency:
        Currency label string (default: ``'USD'``).
    """

    def __init__(
        self,
        machine_watts: float = 40.0,
        cost_per_kwh: float = 0.15,
        material_cost_per_cm2: float = 0.05,
        rapid_speed: float = 5000.0,
        beam_width_mm: float = 0.1,
        currency: str = "USD",
    ) -> None:
        self.machine_watts = machine_watts
        self.cost_per_kwh = cost_per_kwh
        self.material_cost_per_cm2 = material_cost_per_cm2
        self.rapid_speed = max(1.0, rapid_speed)
        self.beam_width_mm = beam_width_mm
        self.currency = currency

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(
        self,
        segments: List[BurnSegment],
        feed_rate: float = 3000.0,
    ) -> CostReport:
        """Compute cost from a burn path.

        Parameters
        ----------
        segments:
            The ``machine.burn_path`` list after a run.
        feed_rate:
            Default feed rate (mm/min) used when a segment does not
            carry its own speed information.
        """
        total_time_s = 0.0
        cut_mm = 0.0
        rapid_mm = 0.0
        engraved_mm2 = 0.0
        energy_ws = 0.0  # Watt-seconds

        feed_mmpm = max(1.0, feed_rate)

        for seg in segments:
            length = self._seg_length(seg)

            if seg.motion == "rapid":
                t = length / self.rapid_speed * 60.0
                rapid_mm += length
                # Machine still draws idle power during rapids
                energy_ws += self.machine_watts * t
                total_time_s += t
            else:
                t = length / feed_mmpm * 60.0
                cut_mm += length
                # Engrave area
                engraved_mm2 += length * self.beam_width_mm
                # Energy: full machine watt draw + extra for laser power
                energy_ws += self.machine_watts * t
                total_time_s += t

        kwh = energy_ws / 3_600_000.0
        elec_cost = kwh * self.cost_per_kwh
        mat_cost = (engraved_mm2 / 100.0) * self.material_cost_per_cm2

        return CostReport(
            time_seconds=total_time_s,
            cut_length_mm=cut_mm,
            rapid_length_mm=rapid_mm,
            engraved_area_mm2=engraved_mm2,
            electricity_kwh=kwh,
            electricity_cost=elec_cost,
            material_cost=mat_cost,
            currency=self.currency,
        )

    def estimate_from_gcode(
        self,
        gcode: str,
        feed_rate: float = 3000.0,
    ) -> CostReport:
        """Parse *gcode*, run it through a fresh machine, and estimate cost.

        This is a convenience wrapper that creates a temporary
        :class:`~lazerem.machine.LaserMachine`, runs the program, and
        calls :meth:`estimate`.
        """
        from .machine import LaserMachine
        m = LaserMachine()
        m.run_program(gcode)
        return self.estimate(m.burn_path, feed_rate=feed_rate)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _seg_length(seg: BurnSegment) -> float:
        """Euclidean length of a segment (using arc_points if available)."""
        pts = seg.arc_points if seg.arc_points else [seg.start, seg.end]
        total = 0.0
        for i in range(len(pts) - 1):
            total += math.hypot(
                pts[i + 1][0] - pts[i][0],
                pts[i + 1][1] - pts[i][1],
            )
        return total
