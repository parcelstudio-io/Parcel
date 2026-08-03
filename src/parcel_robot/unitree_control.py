from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

from parcel_robot.config import ConfigStore
from parcel_robot.control import (
    ControlLifecycle,
    ControlNotReadyError,
    build_unitree_sport_control_manager,
)
from parcel_robot.models import VelocityCommand

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "robot.yaml"
FALLBACK_CONFIG = Path(__file__).with_name("config") / "robot.yaml"
COMMISSIONING_MAX_LINEAR_MPS = 0.10
COMMISSIONING_MAX_YAW_RAD_S = 0.25
COMMISSIONING_MAX_DURATION_S = 2.0


def main() -> None:
    """Run a short, explicitly armed Unitree Sport commissioning command."""

    default_config = DEFAULT_CONFIG if DEFAULT_CONFIG.is_file() else FALLBACK_CONFIG
    parser = argparse.ArgumentParser(
        description="Commission Parcel's feedback-supervised Unitree Sport controller"
    )
    parser.add_argument("--config", default=str(default_config))
    parser.add_argument("--vx", type=float, default=0.0, help="forward velocity in m/s")
    parser.add_argument("--vy", type=float, default=0.0, help="lateral velocity in m/s")
    parser.add_argument("--vyaw", type=float, default=0.0, help="yaw velocity in rad/s")
    parser.add_argument("--duration", type=float, default=1.0)
    parser.add_argument(
        "--arm",
        action="store_true",
        help="required acknowledgement that this command can move physical hardware",
    )
    args = parser.parse_args()

    command = VelocityCommand(float(args.vx), float(args.vy), float(args.vyaw))
    if not args.arm:
        parser.error("--arm is required; support the robot and prepare a physical E-stop")
    if not math.isfinite(args.duration) or not 0.0 < args.duration <= COMMISSIONING_MAX_DURATION_S:
        parser.error(
            "--duration must be greater than zero and at most "
            f"{COMMISSIONING_MAX_DURATION_S:g} seconds"
        )
    if any(not math.isfinite(value) for value in (command.vx, command.vy, command.vyaw)):
        parser.error("velocity values must be finite")
    if command == VelocityCommand():
        parser.error("at least one velocity component must be non-zero")
    if sum(abs(value) > 1e-9 for value in (command.vx, command.vy, command.vyaw)) != 1:
        parser.error("commission only one velocity axis at a time")
    if abs(command.vx) > COMMISSIONING_MAX_LINEAR_MPS:
        parser.error(f"--vx is limited to {COMMISSIONING_MAX_LINEAR_MPS:g} m/s")
    if abs(command.vy) > COMMISSIONING_MAX_LINEAR_MPS:
        parser.error(f"--vy is limited to {COMMISSIONING_MAX_LINEAR_MPS:g} m/s")
    if abs(command.vyaw) > COMMISSIONING_MAX_YAW_RAD_S:
        parser.error(f"--vyaw is limited to {COMMISSIONING_MAX_YAW_RAD_S:g} rad/s")

    store = ConfigStore(args.config)
    manager = build_unitree_sport_control_manager(
        store.section("control"),
        store.safety_limits(),
    )
    interrupted = False
    try:
        manager.start()
        _wait_until_ready(manager)
        print(
            "Controller ready. Confirm the robot is supported, the area is clear, "
            "and an operator holds the physical E-stop.",
            flush=True,
        )
        started = time.monotonic()
        while time.monotonic() - started < args.duration:
            manager.set_target(command, source="commissioning_cli")
            status = manager.snapshot()
            if status.lifecycle == ControlLifecycle.FAULTED:
                raise RuntimeError(status.fault or "controller faulted")
            time.sleep(min(0.05, manager.timing.command_timeout_s / 3.0))
        manager.stop("commissioning_complete")
        _wait_until_stopped(manager)
        print(json.dumps(manager.snapshot().as_dict(), indent=2), flush=True)
    except KeyboardInterrupt:
        interrupted = True
        manager.emergency_stop()
        print("Emergency stop requested after keyboard interrupt.", flush=True)
        try:
            _wait_until_stopped(manager)
        except RuntimeError as error:
            raise RuntimeError(f"{error}; use the physical E-stop immediately") from error
    finally:
        try:
            if not interrupted:
                manager.stop("commissioning_shutdown")
        finally:
            manager.close()


def _wait_until_ready(manager, timeout_s: float | None = None) -> None:
    timeout = manager.timing.startup_timeout_s if timeout_s is None else timeout_s
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.snapshot()
        if status.lifecycle == ControlLifecycle.IDLE:
            return
        if status.lifecycle == ControlLifecycle.FAULTED:
            raise RuntimeError(status.fault or "controller failed while arming")
        time.sleep(0.02)
    raise ControlNotReadyError("Unitree Sport feedback did not become ready before timeout")


def _wait_until_stopped(manager) -> None:
    deadline = time.monotonic() + manager.timing.stop_timeout_s
    while time.monotonic() < deadline:
        status = manager.snapshot()
        if status.stop_confirmed:
            return
        if status.lifecycle == ControlLifecycle.FAULTED:
            raise RuntimeError(status.fault or "controller faulted while stopping")
        time.sleep(0.02)
    status = manager.snapshot()
    raise RuntimeError(status.fault or "physical stop was not confirmed before timeout")


if __name__ == "__main__":
    main()
