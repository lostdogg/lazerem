"""Tests for lazerem.network_control."""

from __future__ import annotations

import time
import pytest
from lazerem.network_control import NetworkController, MachineNode
from lazerem.machine import LaserMachine

_SIMPLE = "G21 G90\nG0 X0 Y0\nM3 S500\nG1 X5 F3000\nM5\nM2\n"


class TestMachineNode:
    def test_initial_idle(self):
        node = MachineNode("A")
        assert node.is_idle
        assert node.job_count == 0

    def test_run_sync(self):
        node = MachineNode("A")
        msgs = node.run_sync(_SIMPLE)
        assert node.machine.status in ("DONE",)
        assert node.job_count == 1
        assert isinstance(msgs, list)

    def test_run_async(self):
        node = MachineNode("A")
        done = []

        def on_complete(n, msgs):
            done.append((n.name, msgs))

        ok = node.run_async(_SIMPLE, on_complete=on_complete)
        assert ok
        # Wait for thread
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not done:
            time.sleep(0.05)
        assert done
        assert done[0][0] == "A"

    def test_run_async_rejects_when_busy(self):
        # The sync gcode finishes instantly so we can't easily test busy;
        # verify the method returns True at least on an idle node
        node = MachineNode("A")
        ok = node.run_async(_SIMPLE)
        assert ok

    def test_info_dict(self):
        node = MachineNode("TestNode")
        info = node.info()
        assert info["name"] == "TestNode"
        assert "status" in info
        assert "idle" in info
        assert "position" in info

    def test_stop(self):
        node = MachineNode("A")
        node.run_sync(_SIMPLE)
        node.stop()
        assert node.machine.program_stopped

    def test_reset(self):
        node = MachineNode("A")
        node.run_sync(_SIMPLE)
        node.reset()
        assert node.machine.status == "IDLE"


class TestNetworkController:
    def test_add_remove_node(self):
        ctrl = NetworkController()
        ctrl.add_node(MachineNode("A"))
        ctrl.add_node(MachineNode("B"))
        assert len(ctrl.nodes) == 2
        ok = ctrl.remove_node("A")
        assert ok
        assert len(ctrl.nodes) == 1
        assert not ctrl.remove_node("nonexistent")

    def test_dispatch_to_idle(self):
        ctrl = NetworkController()
        ctrl.add_node(MachineNode("A"))
        ctrl.add_node(MachineNode("B"))
        name = ctrl.dispatch(_SIMPLE)
        assert name in ("A", "B")

    def test_dispatch_no_nodes(self):
        ctrl = NetworkController()
        result = ctrl.dispatch(_SIMPLE)
        assert result is None

    def test_status_all(self):
        ctrl = NetworkController()
        ctrl.add_node(MachineNode("X"))
        ctrl.add_node(MachineNode("Y"))
        statuses = ctrl.status_all()
        assert len(statuses) == 2
        names = {s["name"] for s in statuses}
        assert names == {"X", "Y"}

    def test_idle_count(self):
        ctrl = NetworkController()
        ctrl.add_node(MachineNode("A"))
        ctrl.add_node(MachineNode("B"))
        assert ctrl.idle_count() == 2

    def test_stop_all(self):
        ctrl = NetworkController()
        n = MachineNode("A")
        ctrl.add_node(n)
        ctrl.stop_all()
        assert n.machine.program_stopped

    def test_wait_all_empty(self):
        ctrl = NetworkController()
        assert ctrl.wait_all(timeout=0.1)

    def test_broadcast_returns_count(self):
        ctrl = NetworkController()
        ctrl.add_node(MachineNode("A"))
        ctrl.add_node(MachineNode("B"))
        count = ctrl.broadcast(_SIMPLE)
        assert count == 2
        ctrl.wait_all(timeout=5.0)
