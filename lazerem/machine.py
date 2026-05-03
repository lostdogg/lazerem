"""Ray5W laser machine simulation.

The :class:`LaserMachine` class interprets parsed G-code blocks and
maintains the machine state (position, laser power, modal groups, etc.).
It records the burn path so the UI canvas can display it.

Key differences from a CNC spindle machine:
  * Only X/Y axes – no Z axis.
  * Laser power is the S word (0–1000 in GRBL, exposed as 0–100 %).
  * M3 = laser on (constant power), M4 = laser on (dynamic power mode),
    M5 = laser off.
  * Rapid moves (G0) are drawn with the laser off regardless of M3/M4.
  * The power level is stored on each path segment for colour-coded display.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .parser import Block, arc_points, parse_program


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Position:
    x: float = 0.0
    y: float = 0.0

    def as_tuple(self) -> Tuple[float, float]:
        return (self.x, self.y)

    def copy(self) -> "Position":
        return Position(self.x, self.y)


@dataclass
class BurnSegment:
    """A single move recorded in the burn path."""
    motion: str          # 'rapid', 'cut', 'arc_cw', 'arc_ccw'
    start: Tuple[float, float]
    end: Tuple[float, float]
    # Laser power 0.0–1.0 (fraction of max S value)
    power: float = 0.0
    # For arcs: intermediate XY points
    arc_points: List[Tuple[float, float]] = field(default_factory=list)


class MachineError(Exception):
    """Raised when an invalid/unsupported G-code is encountered."""


# ---------------------------------------------------------------------------
# Machine
# ---------------------------------------------------------------------------

class LaserMachine:
    """Virtual Ray5W 2-axis diode laser engraver (GRBL firmware model)."""

    # Maximum S value (GRBL default $30 = 1000)
    MAX_POWER: float = 1000.0

    # Modal defaults
    _DEFAULT_MOTION = 0    # G0
    _DEFAULT_UNIT = 21     # metric (mm)
    _DEFAULT_DISTANCE = 90 # absolute

    def __init__(self) -> None:
        self.reset()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset to power-on state."""
        self.position = Position()

        # Modal groups
        self.motion_mode: int = self._DEFAULT_MOTION
        self.units: int = self._DEFAULT_UNIT       # 20 = inch, 21 = mm
        self.distance_mode: int = self._DEFAULT_DISTANCE  # 90 / 91

        # Laser state
        self.laser_on: bool = False
        self.laser_dynamic: bool = False  # True when M4 (dynamic) mode
        self.laser_power: float = 0.0    # 0–MAX_POWER (raw S value)

        # Feed
        self.feed_rate: float = 1000.0   # mm/min

        # Execution
        self.program_running: bool = False
        self.program_stopped: bool = False

        # Burn-path recording
        self.burn_path: List[BurnSegment] = []

        # Status
        self.status: str = "IDLE"

    def load_program(self, source: str):
        """Parse *source* and return ``(blocks, errors)``."""
        return parse_program(source)

    def run_program(
        self,
        source: str,
        on_block: Optional[Callable[[int, Block], None]] = None,
    ) -> List[str]:
        """Execute a G-code program string.

        *on_block* is called before each block: ``on_block(index, block)``.
        Returns a list of warning/info messages.
        """
        blocks, parse_errors = parse_program(source)
        messages: List[str] = [
            f"N{e.line_number}: parse error – {e.message}"
            for e in parse_errors
        ]

        self.program_running = True
        self.program_stopped = False
        self.burn_path = []
        self.status = "RUNNING"

        try:
            for idx, block in enumerate(blocks):
                if self.program_stopped:
                    break
                if on_block:
                    on_block(idx, block)
                msg = self._execute_block(block)
                if msg:
                    messages.append(msg)
        except MachineError as exc:
            messages.append(f"MACHINE ERROR: {exc}")
            self.status = "ALARM"
            return messages

        self.program_running = False
        if self.status not in ("ALARM",):
            self.status = "DONE"
        return messages

    def execute_mdi(self, line: str) -> str:
        """Execute a single MDI line.  Returns a status / error string."""
        blocks, errors = parse_program(line)
        if errors:
            return f"Parse error: {errors[0].message}"
        if not blocks:
            return "OK"
        try:
            for block in blocks:
                msg = self._execute_block(block)
                if msg:
                    return msg
        except MachineError as exc:
            self.status = "ALARM"
            return f"ALARM: {exc}"
        return "OK"

    # ------------------------------------------------------------------
    # Internal execution
    # ------------------------------------------------------------------

    def _execute_block(self, block: Block) -> Optional[str]:
        msg: Optional[str] = None

        # ---- M codes --------------------------------------------------
        m = block.get("M")
        if m is not None:
            m = int(m)
            if m in (2, 30):
                self.program_stopped = True
                self.laser_on = False
                self.status = "DONE"
                return None
            elif m == 0:
                self.program_stopped = True
                self.status = "STOP"
                return None
            elif m == 3:
                self.laser_on = True
                self.laser_dynamic = False
            elif m == 4:
                self.laser_on = True
                self.laser_dynamic = True
            elif m == 5:
                self.laser_on = False

        # ---- S (laser power) and F (feed rate) -----------------------
        s = block.get("S")
        if s is not None:
            self.laser_power = max(0.0, min(float(s), self.MAX_POWER))

        f = block.get("F")
        if f is not None:
            self.feed_rate = float(f)

        # ---- G codes --------------------------------------------------
        g_words = [int(w.value) for w in block.words if w.letter == "G"]

        for g in g_words:
            if g == 20:
                self.units = 20
            elif g == 21:
                self.units = 21
            elif g in (90, 91):
                self.distance_mode = g
            elif g == 4:
                p = block.get("P", 0.0)
                msg = f"DWELL {p} ms"
            elif g in (0, 1, 2, 3):
                self.motion_mode = g

        # ---- Motion --------------------------------------------------
        has_xy = block.has("X") or block.has("Y")
        if not has_xy:
            return msg

        motion = self.motion_mode
        for g in g_words:
            if g in (0, 1, 2, 3):
                motion = g

        target = self._resolve_target(block)

        if motion == 0:
            self._move_rapid(target)
        elif motion == 1:
            self._move_linear(target)
        elif motion == 2:
            self._move_arc(block, target, clockwise=True)
        elif motion == 3:
            self._move_arc(block, target, clockwise=False)

        return msg

    def _resolve_target(self, block: Block) -> Position:
        cur = self.position
        if self.distance_mode == 90:
            x = block.get("X", cur.x)
            y = block.get("Y", cur.y)
        else:
            x = cur.x + block.get("X", 0.0)
            y = cur.y + block.get("Y", 0.0)
        return Position(x, y)

    def _current_power_fraction(self) -> float:
        """Return laser power as 0.0–1.0 fraction."""
        return self.laser_power / self.MAX_POWER if self.laser_on else 0.0

    def _move_rapid(self, target: Position) -> None:
        seg = BurnSegment(
            motion="rapid",
            start=self.position.as_tuple(),
            end=target.as_tuple(),
            power=0.0,  # laser off during rapid
        )
        self.burn_path.append(seg)
        self.position = target

    def _move_linear(self, target: Position) -> None:
        seg = BurnSegment(
            motion="cut",
            start=self.position.as_tuple(),
            end=target.as_tuple(),
            power=self._current_power_fraction(),
        )
        self.burn_path.append(seg)
        self.position = target

    def _move_arc(self, block: Block, target: Position, clockwise: bool) -> None:
        start = self.position
        i = block.get("I", 0.0)
        j = block.get("J", 0.0)
        r = block.get("R")

        if r is not None:
            cx, cy = self._centre_from_radius(
                start.x, start.y, target.x, target.y, r, clockwise
            )
        else:
            cx = start.x + i
            cy = start.y + j

        pts = arc_points(
            (start.x, start.y), (target.x, target.y),
            (cx, cy), clockwise,
        )

        label = "arc_cw" if clockwise else "arc_ccw"
        seg = BurnSegment(
            motion=label,
            start=start.as_tuple(),
            end=target.as_tuple(),
            power=self._current_power_fraction(),
            arc_points=pts,
        )
        self.burn_path.append(seg)
        self.position = target

    @staticmethod
    def _centre_from_radius(
        x1: float, y1: float,
        x2: float, y2: float,
        r: float,
        clockwise: bool,
    ) -> Tuple[float, float]:
        dx = x2 - x1
        dy = y2 - y1
        dist = math.hypot(dx, dy)
        if dist == 0 or dist > 2 * abs(r):
            raise MachineError("Arc radius too small for start/end distance")
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2
        h = math.sqrt(r * r - (dist / 2) ** 2)
        px = -dy / dist
        py = dx / dist
        c1 = (mx + h * px, my + h * py)
        c2 = (mx - h * px, my - h * py)
        if r > 0:
            return c2 if clockwise else c1
        else:
            return c1 if clockwise else c2
