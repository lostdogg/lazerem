"""Multi-machine network control for the Ray5W laser control.

Provides a simulated multi-machine manager where each machine node runs
its G-code program in its own thread, and a central
:class:`NetworkController` dispatches jobs and collects status.

In a real deployment, each :class:`MachineNode` would wrap a serial/TCP
connection to a physical controller.  Here every node wraps a
:class:`~lazerem.machine.LaserMachine` instance so the module is fully
testable without hardware.

Usage::

    from lazerem.network_control import NetworkController, MachineNode

    ctrl = NetworkController()
    ctrl.add_node(MachineNode("Machine-A"))
    ctrl.add_node(MachineNode("Machine-B"))

    gcode = "G21 G90 G0 X0 Y0 M3 S500 G1 X40 F3000 M5 M2"
    ctrl.dispatch(gcode)          # sends to first idle node
    statuses = ctrl.status_all()  # list of per-node status dicts
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from .machine import LaserMachine


# ---------------------------------------------------------------------------
# Single machine node
# ---------------------------------------------------------------------------

class MachineNode:
    """Represents one laser machine in a multi-machine setup.

    Parameters
    ----------
    name:
        Human-readable identifier for this machine.
    machine:
        Optional pre-built :class:`LaserMachine`; a new one is created
        if not supplied.
    """

    def __init__(
        self,
        name: str,
        machine: Optional[LaserMachine] = None,
    ) -> None:
        self.name = name
        self.machine = machine or LaserMachine()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_messages: List[str] = []
        self._job_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_idle(self) -> bool:
        """``True`` when no job is running on this node."""
        with self._lock:
            return self._thread is None or not self._thread.is_alive()

    @property
    def status(self) -> str:
        """Machine status string (IDLE, RUNNING, DONE, ALARM …)."""
        return self.machine.status

    @property
    def job_count(self) -> int:
        """Total jobs run on this node."""
        return self._job_count

    @property
    def last_messages(self) -> List[str]:
        """Messages from the most recently completed job."""
        return list(self._last_messages)

    def run_async(
        self,
        gcode: str,
        on_complete: Optional[Callable[["MachineNode", List[str]], None]] = None,
        on_block: Optional[Callable] = None,
    ) -> bool:
        """Start *gcode* asynchronously.

        Returns ``False`` if this node is already busy, ``True`` if the
        job was accepted.
        """
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False

            def _run() -> None:
                msgs = self.machine.run_program(gcode, on_block=on_block)
                with self._lock:
                    self._last_messages = msgs
                    self._job_count += 1
                if on_complete:
                    on_complete(self, msgs)

            self._thread = threading.Thread(target=_run, daemon=True)
            self._thread.start()
            return True

    def run_sync(self, gcode: str) -> List[str]:
        """Run *gcode* synchronously (blocks until done)."""
        self._last_messages = self.machine.run_program(gcode)
        self._job_count += 1
        return list(self._last_messages)

    def stop(self) -> None:
        """Request emergency stop on this node."""
        self.machine.program_stopped = True

    def reset(self) -> None:
        """Reset machine state and wait for any running thread to finish."""
        self.stop()
        if self._thread:
            self._thread.join(timeout=2.0)
        self.machine.reset()

    def info(self) -> Dict[str, object]:
        """Return a status snapshot as a plain dict."""
        return {
            "name": self.name,
            "status": self.status,
            "idle": self.is_idle,
            "job_count": self._job_count,
            "position": self.machine.position.as_tuple(),
            "laser_on": self.machine.laser_on,
            "power": self.machine.laser_power,
        }


# ---------------------------------------------------------------------------
# Network controller
# ---------------------------------------------------------------------------

class NetworkController:
    """Manages a fleet of :class:`MachineNode` instances.

    Provides:
    * **dispatch** – send a job to the first available idle node, or
      queue it if all are busy.
    * **broadcast** – send the same job to every node simultaneously.
    * **status_all** – snapshot status of every node.
    """

    def __init__(self) -> None:
        self._nodes: List[MachineNode] = []
        self._pending: List[Tuple[str, Dict]] = []   # (gcode, options)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Node management
    # ------------------------------------------------------------------

    def add_node(self, node: MachineNode) -> None:
        """Register a node with the controller."""
        with self._lock:
            self._nodes.append(node)

    def remove_node(self, name: str) -> bool:
        """Remove a node by name.  Returns ``True`` if found."""
        with self._lock:
            before = len(self._nodes)
            self._nodes = [n for n in self._nodes if n.name != name]
            return len(self._nodes) < before

    @property
    def nodes(self) -> List[MachineNode]:
        return list(self._nodes)

    # ------------------------------------------------------------------
    # Job dispatch
    # ------------------------------------------------------------------

    def dispatch(
        self,
        gcode: str,
        on_complete: Optional[Callable[[MachineNode, List[str]], None]] = None,
        on_block: Optional[Callable] = None,
    ) -> Optional[str]:
        """Send *gcode* to the first idle node.

        Returns the name of the node that accepted the job, or ``None``
        if all nodes are busy (the job is added to the pending queue).
        """
        with self._lock:
            for node in self._nodes:
                if node.is_idle:
                    node.run_async(
                        gcode,
                        on_complete=lambda n, m, oc=on_complete: (
                            self._on_node_complete(n, m, oc)
                        ),
                        on_block=on_block,
                    )
                    return node.name
            # All busy – enqueue
            self._pending.append((gcode, {"on_complete": on_complete}))
            return None

    def _on_node_complete(
        self,
        node: MachineNode,
        messages: List[str],
        on_complete: Optional[Callable],
    ) -> None:
        if on_complete:
            on_complete(node, messages)
        # Try to dispatch next pending job
        with self._lock:
            if self._pending:
                gcode, opts = self._pending.pop(0)
                node.run_async(
                    gcode,
                    on_complete=lambda n, m: self._on_node_complete(
                        n, m, opts.get("on_complete")
                    ),
                )

    def broadcast(
        self,
        gcode: str,
        on_complete: Optional[Callable[[MachineNode, List[str]], None]] = None,
    ) -> int:
        """Send *gcode* to every node simultaneously.

        Returns the number of nodes that accepted the job (idle ones).
        """
        accepted = 0
        with self._lock:
            for node in self._nodes:
                if node.run_async(gcode, on_complete=on_complete):
                    accepted += 1
        return accepted

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status_all(self) -> List[Dict[str, object]]:
        """Return a list of info dicts from every registered node."""
        return [node.info() for node in self._nodes]

    def idle_count(self) -> int:
        """Number of currently idle nodes."""
        return sum(1 for n in self._nodes if n.is_idle)

    def stop_all(self) -> None:
        """Send emergency stop to every node."""
        for node in self._nodes:
            node.stop()

    def wait_all(self, timeout: float = 30.0) -> bool:
        """Block until all nodes are idle or *timeout* seconds elapses.

        Returns ``True`` if all nodes finished within the timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if all(n.is_idle for n in self._nodes):
                return True
            time.sleep(0.05)
        return False
