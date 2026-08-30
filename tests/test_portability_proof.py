"""Empirical vendor-portability proof: a second adapter runs the full stack.

The velocity HAL is only proven portable when a non-Unitree adapter passes the
same lifecycle the Unitree path is built for — registry construction, arming,
target tracking, feedback-confirmed stop, latched E-stop — with zero edits to
generic code.
"""

from __future__ import annotations

import time

import pytest

import parcel_robot.control.mock_vendor  # noqa: F401 - registers the factory
from parcel_robot.control.factory import controller_factory_names, create_control_manager
from parcel_robot.control.manager import ControlNotReadyError
from parcel_robot.control.models import ControlLifecycle
from parcel_robot.models import VelocityCommand
from parcel_robot.safety import SafetyLimits

CONFIG = {
    "control_hz": 100.0,
    "command_timeout_s": 0.5,
    "state_timeout_s": 0.5,
    "settled_linear_speed_mps": 0.05,
    "settled_yaw_speed_rad_s": 0.08,
    "mock_quadruped": {"tracking_lag_s": 0.03},
}


def _spin(manager, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        manager.tick()
        time.sleep(0.005)


@pytest.fixture()
def manager():
    built = create_control_manager("mock_quadruped", CONFIG, SafetyLimits())
    built.start(threaded=False)
    _spin(built, 0.05)
    yield built
    built.close()


def test_registry_offers_mock_and_the_gateway_physical_composition() -> None:
    names = controller_factory_names()
    assert "mock_quadruped" in names
    assert "motion_gateway_commissioned" in names
    assert "unitree_sport" not in names


def test_unknown_vendor_fails_closed() -> None:
    with pytest.raises(KeyError, match="unknown locomotion controller"):
        create_control_manager("spot", {}, SafetyLimits())


def test_second_vendor_tracks_velocity_through_the_manager(manager) -> None:
    manager.set_target(VelocityCommand(vx=0.3), source="portability-proof")
    _spin(manager, 0.4)
    status = manager.snapshot()
    assert status.lifecycle is ControlLifecycle.ACTIVE
    assert status.measured.vx == pytest.approx(0.3, abs=0.05)


def test_second_vendor_confirms_stop_with_real_feedback(manager) -> None:
    manager.set_target(VelocityCommand(vx=0.3), source="portability-proof")
    _spin(manager, 0.4)
    manager.stop("test_stop")
    _spin(manager, 0.5)
    status = manager.snapshot()
    assert status.stop_confirmed is True
    assert abs(status.measured.vx) < 0.05


def test_second_vendor_latches_emergency_stop(manager) -> None:
    manager.set_target(VelocityCommand(vx=0.3), source="portability-proof")
    _spin(manager, 0.2)
    manager.emergency_stop()
    _spin(manager, 0.3)
    status = manager.snapshot()
    assert status.emergency_stopped is True
    with pytest.raises(ControlNotReadyError):
        manager.set_target(VelocityCommand(vx=0.2), source="portability-proof")
    # Feedback shows the body settled before the latch may clear.
    _spin(manager, 0.3)
    manager.clear_emergency_stop()
    _spin(manager, 0.1)
    manager.set_target(VelocityCommand(vx=0.1), source="portability-proof")
    _spin(manager, 0.2)
    assert manager.snapshot().lifecycle is ControlLifecycle.ACTIVE


def test_second_vendor_ttl_watchdog_stops_stale_commands(manager) -> None:
    manager.set_target(VelocityCommand(vx=0.3), source="portability-proof", ttl=0.1)
    _spin(manager, 0.5)
    status = manager.snapshot()
    # The lease expired and nothing renewed it: the manager must have stopped
    # the robot on its own.
    assert status.lifecycle in {ControlLifecycle.IDLE, ControlLifecycle.STOPPING}
    assert abs(status.measured.vx) < 0.05
