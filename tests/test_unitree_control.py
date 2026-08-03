from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from parcel_robot import unitree_control
from parcel_robot.safety import SafetyLimits


def test_commissioning_cli_closes_manager_when_shutdown_stop_fails(monkeypatch) -> None:
    class FakeStore:
        def section(self, name: str):
            assert name == "control"
            return {}

        def safety_limits(self) -> SafetyLimits:
            return SafetyLimits()

    class FakeManager:
        def __init__(self) -> None:
            self.timing = SimpleNamespace(command_timeout_s=0.35)
            self.stop_reasons: list[str] = []
            self.closed = 0

        def start(self) -> None:
            pass

        def stop(self, reason: str) -> None:
            self.stop_reasons.append(reason)
            raise RuntimeError("StopMove offline")

        def close(self) -> None:
            self.closed += 1

    manager = FakeManager()
    ticks = iter((0.0, 1.0))
    monkeypatch.setattr(sys, "argv", ["parcel-unitree-control", "--vx", "0.05", "--arm"])
    monkeypatch.setattr(unitree_control, "ConfigStore", lambda _: FakeStore())
    monkeypatch.setattr(
        unitree_control,
        "build_unitree_sport_control_manager",
        lambda *_: manager,
    )
    monkeypatch.setattr(unitree_control, "_wait_until_ready", lambda *_: None)
    monkeypatch.setattr(unitree_control.time, "monotonic", lambda: next(ticks))

    with pytest.raises(RuntimeError, match="StopMove offline"):
        unitree_control.main()

    assert manager.stop_reasons == ["commissioning_complete", "commissioning_shutdown"]
    assert manager.closed == 1
