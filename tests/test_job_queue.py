"""Tests for lazerem.job_queue."""

from __future__ import annotations

import pytest
from lazerem.job_queue import JobQueue, QueuedJob
from lazerem.machine import LaserMachine

_SIMPLE_GCODE = "G21 G90\nG0 X0 Y0\nM3 S500\nG1 X10 F3000\nM5\nM2\n"


class TestQueuedJob:
    def test_defaults(self):
        job = QueuedJob(name="test", gcode=_SIMPLE_GCODE)
        assert job.status == "pending"
        assert job.messages == []
        assert job.elapsed == 0.0

    def test_copy(self):
        job = QueuedJob(name="orig", gcode="M2", power=700, passes=2)
        c = job.copy()
        assert c.name == "orig"
        assert c.power == 700
        assert c.passes == 2
        assert c is not job


class TestJobQueue:
    def test_empty_queue(self):
        q = JobQueue()
        assert len(q) == 0
        assert q.pending_count() == 0

    def test_add_and_count(self):
        q = JobQueue()
        q.add(QueuedJob("j1", gcode=_SIMPLE_GCODE))
        q.add(QueuedJob("j2", gcode=_SIMPLE_GCODE))
        assert len(q) == 2
        assert q.pending_count() == 2

    def test_remove(self):
        q = JobQueue()
        q.add(QueuedJob("j1", gcode="M2"))
        q.add(QueuedJob("j2", gcode="M2"))
        removed = q.remove(0)
        assert removed is not None
        assert removed.name == "j1"
        assert len(q) == 1

    def test_remove_out_of_range(self):
        q = JobQueue()
        assert q.remove(0) is None

    def test_move_up(self):
        q = JobQueue()
        q.add(QueuedJob("a", gcode="M2"))
        q.add(QueuedJob("b", gcode="M2"))
        assert q.move_up(1)
        assert q.jobs[0].name == "b"
        assert q.jobs[1].name == "a"

    def test_move_up_first_fails(self):
        q = JobQueue()
        q.add(QueuedJob("a", gcode="M2"))
        assert not q.move_up(0)

    def test_move_down(self):
        q = JobQueue()
        q.add(QueuedJob("a", gcode="M2"))
        q.add(QueuedJob("b", gcode="M2"))
        assert q.move_down(0)
        assert q.jobs[0].name == "b"

    def test_move_down_last_fails(self):
        q = JobQueue()
        q.add(QueuedJob("a", gcode="M2"))
        assert not q.move_down(0)

    def test_clear(self):
        q = JobQueue()
        q.add(QueuedJob("j1", gcode="M2"))
        q.clear()
        assert len(q) == 0

    def test_reset_statuses(self):
        q = JobQueue()
        j = QueuedJob("j1", gcode="M2")
        q.add(j)
        j.status = "done"
        q.reset_statuses()
        assert q.jobs[0].status == "pending"

    def test_run_next(self):
        q = JobQueue()
        q.add(QueuedJob("j1", gcode=_SIMPLE_GCODE))
        m = LaserMachine()
        result = q.run_next(m)
        assert result is not None
        job, msgs = result
        assert job.status == "done"
        assert job.elapsed >= 0.0

    def test_run_next_empty(self):
        q = JobQueue()
        m = LaserMachine()
        assert q.run_next(m) is None

    def test_run_next_skips_non_pending(self):
        q = JobQueue()
        j = QueuedJob("j1", gcode="M2")
        j.status = "done"
        q.add(j)
        q.add(QueuedJob("j2", gcode=_SIMPLE_GCODE))
        m = LaserMachine()
        result = q.run_next(m)
        assert result is not None
        assert result[0].name == "j2"

    def test_run_all_generator(self):
        q = JobQueue()
        q.add(QueuedJob("j1", gcode=_SIMPLE_GCODE))
        q.add(QueuedJob("j2", gcode=_SIMPLE_GCODE))
        m = LaserMachine()
        completed = list(q.run_all(m))
        assert len(completed) == 2
        for job, msgs in completed:
            assert job.status == "done"

    def test_power_override(self):
        q = JobQueue()
        q.add(QueuedJob("j1", gcode="G21 G90\nM3\nG1 X10 F3000\nM5\nM2",
                        power=800))
        m = LaserMachine()
        q.run_next(m)
        # Machine should have set power at some point
        assert q.jobs[0].status == "done"

    def test_insert(self):
        q = JobQueue()
        q.add(QueuedJob("a", gcode="M2"))
        q.add(QueuedJob("c", gcode="M2"))
        q.insert(1, QueuedJob("b", gcode="M2"))
        assert q.jobs[1].name == "b"
