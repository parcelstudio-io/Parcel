"""Independent, network-free, stop-only safety supervisor process.

This process has no motion-positive API and no Unitree/DDS import. It observes
the commissioned gateway over its local Unix socket and can only request a
latched emergency STOP. Hardware GPIO/remote/audio adapters remain box-day
work; this slice accepts local operating-system signals: ``SIGUSR1`` latches
STOP and keeps supervising, while ``SIGINT``/``SIGTERM`` latch STOP before
shutdown.
"""

from __future__ import annotations

import argparse
import math
import os
import signal
import socket
import threading
import time
from dataclasses import dataclass

from parcel_robot.bridge.stop_only_gateway import (
    LatchedStopResultV1,
    StopOnlyGatewayClientV1,
    StopOnlyGatewayError,
    StopOnlyGatewayStateV1,
)

CONSOLE_SCRIPT_NAME = "parcel-safety"
SOCKET_ENV = "PARCEL_GATEWAY_SOCKET"
ARMED_ENV = "PARCEL_ARMED"
STATE_DIRECTORY_ENV = "STATE_DIRECTORY"
NOTIFY_SOCKET_ENV = "NOTIFY_SOCKET"
WATCHDOG_USEC_ENV = "WATCHDOG_USEC"
WATCHDOG_PID_ENV = "WATCHDOG_PID"
DEFAULT_SOCKET_NAME = "gateway.sock"


@dataclass(frozen=True)
class SafetyProbeV1:
    healthy: bool
    reason: str
    state: StopOnlyGatewayStateV1 | None
    stop: LatchedStopResultV1 | None = None


class StopOnlySafetySupervisorV1:
    """Read-only health probe plus one monotone transition: latched STOP."""

    def __init__(
        self,
        client: StopOnlyGatewayClientV1,
        *,
        max_state_age_ms: float = 250.0,
    ) -> None:
        if not isinstance(client, StopOnlyGatewayClientV1):
            raise TypeError("client must be StopOnlyGatewayClientV1")
        if (
            isinstance(max_state_age_ms, bool)
            or not isinstance(max_state_age_ms, (int, float))
            or not math.isfinite(float(max_state_age_ms))
            or not 1.0 <= float(max_state_age_ms) <= 5_000.0
        ):
            raise ValueError("max_state_age_ms must be finite and between 1 and 5000")
        self._client = client
        self._max_state_age_ms = float(max_state_age_ms)
        self._boot_epoch = client.boot_epoch
        self._stop_latched = False

    @property
    def authorizes_actuation(self) -> bool:
        return False

    @property
    def stop_latched(self) -> bool:
        return self._stop_latched

    def probe(self) -> SafetyProbeV1:
        """Earn one health sample or monotonically attempt a latched STOP."""

        try:
            state = self._client.state()
        except StopOnlyGatewayError:
            return SafetyProbeV1(False, "gateway_probe_failed", None)
        violation = self._state_violation(state)
        if violation:
            return self.stop(reason=violation)
        return SafetyProbeV1(True, "ok", state)

    def stop(self, *, reason: str) -> SafetyProbeV1:
        """Request emergency STOP and require a post-stop latched witness."""

        try:
            result = self._client.stop(reason=reason)
            state = self._client.state()
        except (StopOnlyGatewayError, ValueError, TypeError):
            return SafetyProbeV1(False, "stop_unconfirmed", None)
        confirmed = (
            result.confirmed_stationary
            and state.boot_epoch == self._boot_epoch
            and state.phase == "latched"
            and state.stationary
            and not state.lease_active
            and state.vx_mps == 0.0
            and state.vy_mps == 0.0
            and state.vyaw_rad_s == 0.0
        )
        if confirmed:
            self._stop_latched = True
            return SafetyProbeV1(True, "latched_stop_confirmed", state, result)
        return SafetyProbeV1(False, "stop_unconfirmed", state, result)

    def _state_violation(self, state: StopOnlyGatewayStateV1) -> str:
        if state.boot_epoch != self._boot_epoch:
            return "gateway_epoch_changed"
        if not math.isfinite(state.state_age_ms) or state.state_age_ms > self._max_state_age_ms:
            return "gateway_state_stale"
        if any(
            not math.isfinite(value) for value in (state.vx_mps, state.vy_mps, state.vyaw_rad_s)
        ):
            return "gateway_velocity_nonfinite"
        if state.phase not in {"disarmed", "armed", "latched"}:
            return "gateway_phase_unknown"
        moving = not state.stationary or any(
            value != 0.0 for value in (state.vx_mps, state.vy_mps, state.vyaw_rad_s)
        )
        if state.phase != "armed" and (state.lease_active or moving):
            return "motion_without_armed_lease"
        if state.phase == "armed" and not state.lease_active:
            return "armed_without_lease"
        return ""


class _SdNotifierV1:
    """Small best-effort sd_notify sender; never part of the STOP call path."""

    def __init__(self, address: str) -> None:
        self._address = address

    @property
    def supervised(self) -> bool:
        return bool(self._address)

    def send(self, message: str) -> bool:
        if not self._address:
            return True
        address = self._address
        if address.startswith("@"):
            address = "\0" + address[1:]
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
                channel.settimeout(0.25)
                channel.sendto(message.encode("utf-8"), address)
        except OSError:
            return False
        return True

    def ready(self) -> bool:
        return self.send("READY=1\nSTATUS=stop-only gateway supervision healthy")

    def watchdog(self) -> bool:
        return self.send("WATCHDOG=1")

    def stopping(self, status: str) -> bool:
        return self.send(f"STOPPING=1\nSTATUS={status}")


def _watchdog_ping_period_s(environ: dict[str, str]) -> float:
    watchdog_pid = environ.get(WATCHDOG_PID_ENV, "")
    if watchdog_pid and watchdog_pid != str(os.getpid()):
        return 0.0
    raw = environ.get(WATCHDOG_USEC_ENV, "")
    if not raw.isdigit():
        return 0.0
    return int(raw) / 1_000_000.0 / 4.0


def _socket_from(args: argparse.Namespace, environ: dict[str, str]) -> str:
    explicit = args.socket or environ.get(SOCKET_ENV, "").strip()
    if explicit:
        return explicit
    state_directory = environ.get(STATE_DIRECTORY_ENV, "").split(":")[0]
    if state_directory:
        return os.path.join(state_directory, DEFAULT_SOCKET_NAME)
    raise SystemExit(
        f"{CONSOLE_SCRIPT_NAME}: --socket, {SOCKET_ENV}, or {STATE_DIRECTORY_ENV} is required"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=CONSOLE_SCRIPT_NAME,
        description="Parcel independent observe/latched-STOP-only supervisor",
    )
    parser.add_argument("--disarmed", action="store_true")
    parser.add_argument("--socket", default=None)
    parser.add_argument("--poll-period-s", type=float, default=0.1)
    parser.add_argument("--gateway-timeout-s", type=float, default=0.25)
    parser.add_argument("--startup-timeout-s", type=float, default=10.0)
    parser.add_argument("--max-state-age-ms", type=float, default=250.0)
    parser.add_argument("--max-ticks", type=int, default=None, help=argparse.SUPPRESS)
    return parser


def _validate_startup_args(args: argparse.Namespace, environ: dict[str, str]) -> None:
    armed = environ.get(ARMED_ENV, "0").strip()
    if armed not in {"", "0"}:
        raise SystemExit(f"{CONSOLE_SCRIPT_NAME}: {ARMED_ENV} must be 0; this process cannot arm")
    if not args.disarmed:
        raise SystemExit(f"{CONSOLE_SCRIPT_NAME}: --disarmed assertion is required")
    for name in ("poll_period_s", "gateway_timeout_s", "startup_timeout_s"):
        value = getattr(args, name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0.0
        ):
            raise SystemExit(f"{CONSOLE_SCRIPT_NAME}: --{name.replace('_', '-')} must be > 0")
    if args.max_ticks is not None and args.max_ticks < 1:
        raise SystemExit(f"{CONSOLE_SCRIPT_NAME}: --max-ticks must be positive")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    environ = dict(os.environ)
    _validate_startup_args(args, environ)

    stop_requested = threading.Event()
    shutdown_requested = threading.Event()
    requested_reason = {"value": "independent_safety_stop"}

    def request_latched_stop(signum: int, _frame: object) -> None:
        requested_reason["value"] = {
            signal.SIGUSR1: "local_stop_signal",
            signal.SIGINT: "supervisor_sigint",
            signal.SIGTERM: "supervisor_sigterm",
        }.get(signum, "supervisor_signal")
        stop_requested.set()
        if signum in {signal.SIGINT, signal.SIGTERM}:
            shutdown_requested.set()

    signal.signal(signal.SIGUSR1, request_latched_stop)
    signal.signal(signal.SIGINT, request_latched_stop)
    signal.signal(signal.SIGTERM, request_latched_stop)

    # Install every STOP-bearing handler before connecting or publishing
    # READY.  Publishing READY first left a small window in which a service
    # manager could deliver SIGINT/SIGTERM with the interpreter's default
    # disposition, bypassing the gateway STOP request entirely.
    socket_path = _socket_from(args, environ)
    deadline = time.monotonic() + float(args.startup_timeout_s)
    client: StopOnlyGatewayClientV1 | None = None
    while client is None and time.monotonic() < deadline:
        try:
            client = StopOnlyGatewayClientV1.connect(
                socket_path,
                timeout_s=float(args.gateway_timeout_s),
            )
        except StopOnlyGatewayError:
            time.sleep(min(float(args.poll_period_s), max(0.0, deadline - time.monotonic())))
    if client is None:
        return 2

    notifier = _SdNotifierV1(environ.get(NOTIFY_SOCKET_ENV, ""))
    supervisor = StopOnlySafetySupervisorV1(
        client,
        max_state_age_ms=float(args.max_state_age_ms),
    )
    initial = supervisor.probe()
    if not initial.healthy or not notifier.ready():
        client.close()
        return 2

    ping_period_s = _watchdog_ping_period_s(environ)
    next_ping = time.monotonic()
    ticks = 0
    exit_code = 0
    try:
        while True:
            if stop_requested.is_set():
                outcome = supervisor.stop(reason=requested_reason["value"])
                stop_requested.clear()
            else:
                outcome = supervisor.probe()
            if not outcome.healthy:
                # No watchdog credit is minted for an unhealthy or unconfirmed
                # state. A failed probe is never converted into positive proof.
                exit_code = 2
            now = time.monotonic()
            if outcome.healthy and ping_period_s > 0.0 and now >= next_ping and notifier.watchdog():
                next_ping = now + ping_period_s
            ticks += 1
            if shutdown_requested.is_set():
                if not supervisor.stop_latched:
                    final = supervisor.stop(reason=requested_reason["value"])
                    exit_code = 0 if final.healthy else 2
                break
            if args.max_ticks is not None and ticks >= args.max_ticks:
                final = supervisor.stop(reason="bounded_supervisor_exit")
                exit_code = 0 if final.healthy else 2
                break
            time.sleep(float(args.poll_period_s))
    finally:
        notifier.stopping(
            "latched stop confirmed" if supervisor.stop_latched else "stop unconfirmed"
        )
        client.close()
    return exit_code


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())
