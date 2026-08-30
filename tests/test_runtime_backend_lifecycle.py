from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "robot.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


def _audio_status() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic backend-lifecycle test status",
    )


class _LifecycleBackend:
    name = "lifecycle-test"

    def __init__(self, *, start_error: BaseException | None = None) -> None:
        self.start_error = start_error
        self.events: list[str] = []
        self.started = False
        self.closed = False
        self.close_count = 0
        self.observed = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            self.events.append("backend.start")
            self.started = True
        if self.start_error is not None:
            raise self.start_error

    def observe(self) -> SimObservation:
        with self._lock:
            assert self.started, "runtime observed before starting its backend"
            assert not self.closed, "runtime observed after closing its backend"
            self.events.append("backend.observe")
        self.observed.set()
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            backend=self.name,
        )

    def close(self) -> None:
        with self._lock:
            self.events.append("backend.close")
            self.close_count += 1
            self.closed = True

    def move(self, command: object) -> None:
        del command

    def stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


def _runtime(tmp_path: Path, backend: _LifecycleBackend) -> RobotRuntime:
    return RobotRuntime(
        _config(tmp_path),
        backend,
        audio_status=_audio_status(),
        loop_hz=50.0,
    )


def test_backend_starts_before_observation_and_closes_once(tmp_path: Path) -> None:
    backend = _LifecycleBackend()
    runtime = _runtime(tmp_path, backend)

    runtime.start()
    assert backend.observed.wait(1.0)
    runtime.close()
    runtime.close()

    assert backend.events.index("backend.start") < backend.events.index("backend.observe")
    assert backend.events[-1] == "backend.close"
    assert backend.close_count == 1
    assert runtime._backend_active is False
    assert runtime._backend_close_complete is True


def test_later_startup_failure_rolls_back_started_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _LifecycleBackend()
    runtime = _runtime(tmp_path, backend)

    def fail_manager_start(*, threaded: bool = True) -> None:
        del threaded
        assert backend.started
        raise RuntimeError("control manager startup failed")

    monkeypatch.setattr(runtime.control_manager, "start", fail_manager_start)

    with pytest.raises(RuntimeError, match="control manager startup failed"):
        runtime.start()

    assert "backend.observe" not in backend.events
    assert backend.events == ["backend.start", "backend.close"]
    assert backend.close_count == 1
    assert runtime._close_complete is True
    runtime.close()
    assert backend.close_count == 1


def test_backend_start_failure_closes_partially_started_backend(tmp_path: Path) -> None:
    backend = _LifecycleBackend(start_error=RuntimeError("DDS subscriber init failed"))
    runtime = _runtime(tmp_path, backend)

    with pytest.raises(RuntimeError, match="DDS subscriber init failed"):
        runtime.start()

    assert backend.events == ["backend.start", "backend.close"]
    assert backend.close_count == 1
    assert runtime._backend_active is False
    assert runtime._backend_close_complete is True
    assert runtime._close_complete is True
    runtime.close()
    assert backend.close_count == 1
