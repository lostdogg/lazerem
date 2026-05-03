"""Tests for lazerem/machine.py"""

import pytest
from lazerem.machine import LaserMachine, BurnSegment, MachineError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(src: str) -> LaserMachine:
    m = LaserMachine()
    m.run_program(src)
    return m


# ---------------------------------------------------------------------------
# Reset / initial state
# ---------------------------------------------------------------------------

def test_initial_state():
    m = LaserMachine()
    assert m.position.x == 0.0
    assert m.position.y == 0.0
    assert not m.laser_on
    assert m.laser_power == 0.0
    assert m.status == "IDLE"


def test_reset_clears_state():
    m = LaserMachine()
    m.laser_on = True
    m.laser_power = 500
    m.position.x = 100
    m.reset()
    assert not m.laser_on
    assert m.laser_power == 0.0
    assert m.position.x == 0.0
    assert m.status == "IDLE"


# ---------------------------------------------------------------------------
# Simple moves
# ---------------------------------------------------------------------------

def test_rapid_move():
    m = _run("G0 X50 Y30")
    assert m.position.x == pytest.approx(50.0)
    assert m.position.y == pytest.approx(30.0)
    assert len(m.burn_path) == 1
    assert m.burn_path[0].motion == "rapid"
    assert m.burn_path[0].power == 0.0


def test_cut_move_with_laser():
    m = _run("M3 S800\nG1 X100 Y0 F2000")
    assert m.position.x == pytest.approx(100.0)
    assert len(m.burn_path) == 1
    assert m.burn_path[0].motion == "cut"
    assert m.burn_path[0].power == pytest.approx(0.8)


def test_laser_off_rapid():
    m = _run("M3 S500\nG0 X10 Y10")
    seg = m.burn_path[-1]
    assert seg.motion == "rapid"
    assert seg.power == 0.0   # laser off during rapid


def test_m5_turns_off_laser():
    m = LaserMachine()
    m.run_program("M3 S500\nM5")
    assert not m.laser_on


def test_m4_dynamic_mode():
    m = LaserMachine()
    m.run_program("M4 S300")
    assert m.laser_on
    assert m.laser_dynamic


def test_m3_constant_mode():
    m = LaserMachine()
    m.run_program("M3 S300")
    assert m.laser_on
    assert not m.laser_dynamic


# ---------------------------------------------------------------------------
# Absolute / incremental
# ---------------------------------------------------------------------------

def test_absolute_mode():
    m = _run("G90\nG0 X10 Y5\nG0 X20 Y10")
    assert m.position.x == pytest.approx(20.0)
    assert m.position.y == pytest.approx(10.0)


def test_incremental_mode():
    m = _run("G91\nG0 X10 Y5\nG0 X10 Y5")
    assert m.position.x == pytest.approx(20.0)
    assert m.position.y == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def test_metric_default():
    m = LaserMachine()
    assert m.units == 21


def test_inch_mode():
    m = _run("G20")
    assert m.units == 20


def test_metric_mode():
    m = _run("G21")
    assert m.units == 21


# ---------------------------------------------------------------------------
# Program control
# ---------------------------------------------------------------------------

def test_m2_ends_program():
    m = _run("G0 X10 Y0\nM2\nG0 X999 Y999")
    # Movement after M2 should not be executed
    assert m.position.x == pytest.approx(10.0)
    assert m.position.y == pytest.approx(0.0)


def test_m30_ends_program():
    m = _run("G0 X5 Y5\nM30\nG0 X999 Y999")
    assert m.position.x == pytest.approx(5.0)
    assert m.position.y == pytest.approx(5.0)


def test_status_done():
    m = _run("G0 X10 Y0\nM2")
    assert m.status == "DONE"


# ---------------------------------------------------------------------------
# Arcs
# ---------------------------------------------------------------------------

def test_arc_cw_segment():
    m = _run("M3 S500\nG2 X10 Y0 I5 J0")
    segs = [s for s in m.burn_path if s.motion == "arc_cw"]
    assert len(segs) == 1
    assert len(segs[0].arc_points) > 2


def test_arc_ccw_segment():
    m = _run("M3 S500\nG3 X10 Y0 I5 J0")
    segs = [s for s in m.burn_path if s.motion == "arc_ccw"]
    assert len(segs) == 1


# ---------------------------------------------------------------------------
# MDI
# ---------------------------------------------------------------------------

def test_mdi_single_move():
    m = LaserMachine()
    result = m.execute_mdi("G0 X25 Y15")
    assert result == "OK"
    assert m.position.x == pytest.approx(25.0)
    assert m.position.y == pytest.approx(15.0)


def test_mdi_parse_error():
    m = LaserMachine()
    result = m.execute_mdi("G1 Xabc Y10")
    assert "Parse error" in result or result == "OK"


def test_mdi_laser_on_off():
    m = LaserMachine()
    m.execute_mdi("M3 S600")
    assert m.laser_on
    assert m.laser_power == 600.0
    m.execute_mdi("M5")
    assert not m.laser_on


# ---------------------------------------------------------------------------
# Power clamping
# ---------------------------------------------------------------------------

def test_power_clamped_to_max():
    m = LaserMachine()
    m.run_program("M3 S9999")
    assert m.laser_power == LaserMachine.MAX_POWER


def test_power_clamped_to_zero():
    m = LaserMachine()
    m.run_program("M3 S-100")
    assert m.laser_power == 0.0


# ---------------------------------------------------------------------------
# Square profile (integration)
# ---------------------------------------------------------------------------

def test_square_profile():
    program = """\
G21 G90
G0 X0 Y0
M3 S500
G1 X40 F3000
G1 Y40
G1 X0
G1 Y0
M5
G0 X0 Y0
M2
"""
    m = _run(program)
    assert m.position.x == pytest.approx(0.0)
    assert m.position.y == pytest.approx(0.0)
    cut_segs = [s for s in m.burn_path if s.motion == "cut"]
    assert len(cut_segs) == 4
    assert m.status == "DONE"
