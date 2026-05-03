"""Batch job queue for the Ray5W laser control.

Allows users to queue multiple G-code programs with individual laser
settings and run them in sequence without manual intervention.

Usage::

    from lazerem.job_queue import JobQueue, QueuedJob

    q = JobQueue()
    q.add(QueuedJob("square.nc", gcode="G21 G90...\\nM2", power=500, speed=3000))
    q.add(QueuedJob("circle.nc", gcode="...", power=800, speed=2000, passes=2))

    machine = LaserMachine()
    for job, messages in q.run_all(machine):
        print(f"{job.name}: {messages}")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Generator, Iterator, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QueuedJob:
    """A single queued laser job."""

    name: str
    gcode: str = ""
    power: Optional[float] = None    # override S value in gcode (None = keep as-is)
    speed: Optional[float] = None    # override F value in gcode (None = keep as-is)
    passes: Optional[int] = None     # override machine.pass_count
    dithering: Optional[str] = None  # override machine.dithering_mode

    # Runtime state (set during execution)
    status: str = "pending"          # pending / running / done / error / skipped
    messages: List[str] = field(default_factory=list)
    elapsed: float = 0.0             # seconds

    def copy(self) -> "QueuedJob":
        return QueuedJob(
            name=self.name,
            gcode=self.gcode,
            power=self.power,
            speed=self.speed,
            passes=self.passes,
            dithering=self.dithering,
        )


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

class JobQueue:
    """An ordered list of :class:`QueuedJob` items with run-in-sequence logic.

    The queue does *not* own a machine; the caller supplies one to
    :meth:`run_all` / :meth:`run_next`.  This keeps the queue
    serialisable and testable independently of hardware.
    """

    def __init__(self) -> None:
        self._jobs: List[QueuedJob] = []
        self._running: bool = False
        self._stop_requested: bool = False

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def add(self, job: QueuedJob) -> None:
        """Append *job* to the end of the queue."""
        self._jobs.append(job)

    def insert(self, index: int, job: QueuedJob) -> None:
        """Insert *job* at *index*."""
        self._jobs.insert(max(0, index), job)

    def remove(self, index: int) -> Optional[QueuedJob]:
        """Remove and return the job at *index*, or ``None`` if out of range."""
        if 0 <= index < len(self._jobs):
            return self._jobs.pop(index)
        return None

    def move_up(self, index: int) -> bool:
        """Swap job at *index* with the one above it.  Returns success."""
        if index <= 0 or index >= len(self._jobs):
            return False
        self._jobs[index], self._jobs[index - 1] = (
            self._jobs[index - 1], self._jobs[index]
        )
        return True

    def move_down(self, index: int) -> bool:
        """Swap job at *index* with the one below it.  Returns success."""
        if index < 0 or index >= len(self._jobs) - 1:
            return False
        self._jobs[index], self._jobs[index + 1] = (
            self._jobs[index + 1], self._jobs[index]
        )
        return True

    def clear(self) -> None:
        """Remove all jobs."""
        self._jobs = []

    def reset_statuses(self) -> None:
        """Set all job statuses back to ``'pending'``."""
        for job in self._jobs:
            job.status = "pending"
            job.messages = []
            job.elapsed = 0.0

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def jobs(self) -> List[QueuedJob]:
        return list(self._jobs)

    def __len__(self) -> int:
        return len(self._jobs)

    def pending_count(self) -> int:
        return sum(1 for j in self._jobs if j.status == "pending")

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Request that the currently running queue stop after the current job."""
        self._stop_requested = True

    def run_all(
        self,
        machine: "LaserMachine",  # type: ignore[name-defined]
        on_job_start: Optional[Callable[["QueuedJob", int], None]] = None,
        on_job_end: Optional[Callable[["QueuedJob", int], None]] = None,
        on_block: Optional[Callable[[int, object], None]] = None,
    ) -> Generator[Tuple["QueuedJob", List[str]], None, None]:
        """Run all *pending* jobs in sequence.

        Yields ``(job, messages)`` after each job completes.

        Parameters
        ----------
        machine:
            The :class:`~lazerem.machine.LaserMachine` to use.
        on_job_start / on_job_end:
            Optional callbacks called with ``(job, index)`` before/after
            each job.
        on_block:
            Forwarded to ``machine.run_program`` as the per-block callback.
        """
        self._running = True
        self._stop_requested = False

        saved_pass_count = machine.pass_count
        saved_dithering = machine.dithering_mode

        try:
            for idx, job in enumerate(self._jobs):
                if self._stop_requested:
                    break
                if job.status != "pending":
                    continue

                job.status = "running"
                if on_job_start:
                    on_job_start(job, idx)

                # Apply per-job overrides
                if job.passes is not None:
                    machine.pass_count = job.passes
                if job.dithering is not None:
                    machine.dithering_mode = job.dithering

                gcode = self._apply_overrides(job)
                t0 = time.monotonic()
                try:
                    messages = machine.run_program(gcode, on_block=on_block)
                    job.status = "done"
                except Exception as exc:
                    messages = [f"ERROR: {exc}"]
                    job.status = "error"

                job.elapsed = time.monotonic() - t0
                job.messages = messages

                if on_job_end:
                    on_job_end(job, idx)

                yield job, messages

                if self._stop_requested:
                    break

                # Restore overridden settings after each job
                machine.pass_count = saved_pass_count
                machine.dithering_mode = saved_dithering
                machine.reset()
        finally:
            machine.pass_count = saved_pass_count
            machine.dithering_mode = saved_dithering
            self._running = False

    def run_next(
        self,
        machine: "LaserMachine",  # type: ignore[name-defined]
    ) -> Optional[Tuple["QueuedJob", List[str]]]:
        """Run the next pending job.  Returns ``(job, messages)`` or ``None``."""
        for job in self._jobs:
            if job.status == "pending":
                job.status = "running"
                gcode = self._apply_overrides(job)

                saved_pass = machine.pass_count
                saved_dith = machine.dithering_mode
                if job.passes is not None:
                    machine.pass_count = job.passes
                if job.dithering is not None:
                    machine.dithering_mode = job.dithering

                t0 = time.monotonic()
                try:
                    messages = machine.run_program(gcode)
                    job.status = "done"
                except Exception as exc:
                    messages = [f"ERROR: {exc}"]
                    job.status = "error"
                finally:
                    job.elapsed = time.monotonic() - t0
                    job.messages = messages
                    machine.pass_count = saved_pass
                    machine.dithering_mode = saved_dith
                return job, messages
        return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_overrides(self, job: QueuedJob) -> str:
        """Return G-code with S and F overrides prepended if set."""
        lines: List[str] = []
        if job.power is not None:
            lines.append(f"S{int(job.power)}")
        if job.speed is not None:
            lines.append(f"F{int(job.speed)}")
        if lines:
            return "\n".join(lines) + "\n" + job.gcode
        return job.gcode
