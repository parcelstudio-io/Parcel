from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from parcel_robot.bridge.client import FakeGatewayClientV1
from parcel_robot.bridge.protocol import (
    GatewayAckDispositionV1,
    GatewayAckV1,
    GatewayAcquireV1,
    GatewayPhaseV1,
)

ROOT = Path(__file__).resolve().parents[1]


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    source = str(ROOT / "src")
    current = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = source if not current else source + os.pathsep + current
    return environment


def _spawn_gateway(socket_path: Path, event_log: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "parcel_robot.bridge.fake_gateway_process",
            "--socket",
            str(socket_path),
            "--event-log",
            str(event_log),
        ],
        cwd=ROOT,
        env=_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _spawn_client(socket_path: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "parcel_robot.bridge.fake_client_process",
            "--socket",
            str(socket_path),
            "--writer-id",
            "sigkill-client",
            "--vx-mps",
            "0.2",
        ],
        cwd=ROOT,
        env=_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _events(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _wait_until(predicate: object, *, processes: tuple[subprocess.Popen[str], ...] = ()) -> None:
    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        for process in processes:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(
                    f"subprocess exited early rc={process.returncode}\nstdout={stdout}\nstderr={stderr}"
                )
        if callable(predicate) and predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for subprocess evidence")


def _connect_when_ready(
    socket_path: Path,
    gateway: subprocess.Popen[str],
) -> FakeGatewayClientV1:
    result: list[FakeGatewayClientV1] = []

    def connect() -> bool:
        try:
            result.append(FakeGatewayClientV1.connect(socket_path, timeout_s=0.1))
        except (FileNotFoundError, ConnectionRefusedError, TimeoutError, OSError):
            return False
        return True

    _wait_until(connect, processes=(gateway,))
    return result[0]


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3.0)


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "SOCK_SEQPACKET"),
    reason="N24 process proof requires Unix SOCK_SEQPACKET and SIGKILL",
)
def test_sigkill_client_stops_locally_never_resumes_and_restart_is_disarmed(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "gateway.sock"
    event_log = tmp_path / "gateway-events.jsonl"
    gateway = _spawn_gateway(socket_path, event_log)
    client: subprocess.Popen[str] | None = None
    observer: FakeGatewayClientV1 | None = None
    restarted: subprocess.Popen[str] | None = None
    restart_observer: FakeGatewayClientV1 | None = None
    try:
        probe = _connect_when_ready(socket_path, gateway)
        old_epoch = probe.hello.boot_epoch
        assert probe.hello.phase is GatewayPhaseV1.DISARMED
        probe.close()

        client = _spawn_client(socket_path)
        _wait_until(
            lambda: any(event["event"] == "move_applied" for event in _events(event_log)),
            processes=(gateway, client),
        )
        client.kill()  # SIGKILL: no close/finally path can issue the stop.
        client.wait(timeout=3.0)
        assert client.returncode == -signal.SIGKILL
        _wait_until(
            lambda: any(
                event["event"] == "gateway_stop_report"
                and event.get("reason") == "client_disconnected"
                and event.get("stationary_confirmed") is True
                for event in _events(event_log)
            ),
            processes=(gateway,),
        )

        events_after_kill = _events(event_log)
        physical = [
            event["event"]
            for event in events_after_kill
            if event["event"] in {"move_applied", "stop_move_succeeded"}
        ]
        assert physical[-1] == "stop_move_succeeded"

        observer = _connect_when_ready(socket_path, gateway)
        assert observer.hello.boot_epoch == old_epoch
        assert observer.hello.phase is GatewayPhaseV1.DISARMED
        state = observer.state(sequence=100)
        assert state.phase is GatewayPhaseV1.DISARMED
        assert state.stationary
        assert (state.vx_mps, state.vy_mps, state.vyaw_rad_s) == (0.0, 0.0, 0.0)

        # A recorded same-boot acquire cannot replay merely because the first
        # writer died and the gateway disarmed.
        replay = observer.request(
            GatewayAcquireV1(
                writer_id="sigkill-client",
                boot_epoch=old_epoch,
                sequence=1,
                local_ttl_ms=350,
                hashes=observer.hello.required_hashes,
            )
        )
        assert isinstance(replay, GatewayAckV1)
        assert replay.disposition is GatewayAckDispositionV1.REJECTED
        assert replay.reason == "client_sequence_not_increasing"
        observer.close()
        observer = None

        _stop_process(gateway)
        assert gateway.returncode == 0
        restarted = _spawn_gateway(socket_path, event_log)
        restart_observer = _connect_when_ready(socket_path, restarted)
        assert restart_observer.hello.boot_epoch != old_epoch
        assert restart_observer.hello.phase is GatewayPhaseV1.DISARMED

        prior_epoch = restart_observer.request(
            GatewayAcquireV1(
                writer_id="sigkill-client",
                boot_epoch=old_epoch,
                sequence=1,
                local_ttl_ms=350,
                hashes=restart_observer.hello.required_hashes,
            )
        )
        assert isinstance(prior_epoch, GatewayAckV1)
        assert prior_epoch.disposition is GatewayAckDispositionV1.REJECTED
        assert prior_epoch.reason == "boot_epoch_mismatch"
        assert restart_observer.state(sequence=2).phase is GatewayPhaseV1.DISARMED

        final_events = _events(event_log)
        starts = [event for event in final_events if event["event"] == "gateway_started"]
        assert len(starts) == 2
        assert starts[0]["boot_epoch"] != starts[1]["boot_epoch"]
        assert all(event["phase"] == "disarmed" for event in starts)
    finally:
        if observer is not None:
            observer.close()
        if restart_observer is not None:
            restart_observer.close()
        if client is not None and client.poll() is None:
            client.kill()
            client.wait(timeout=3.0)
        if restarted is not None:
            _stop_process(restarted)
        _stop_process(gateway)
