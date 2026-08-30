"""Run the two-role gateway and stop-only supervisor SOS-1 gates."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for _source_root in (REPO / "src", REPO):
    if str(_source_root) not in sys.path:
        sys.path.insert(0, str(_source_root))

from gateway.core import GatewayCoreV1
from gateway.credentials import PeerCredentialV1, writer_with_stop_only_policy
from gateway.limits import default_limits
from gateway.process import BENCH_HASHES
from gateway.server import GatewayServerV1
from parcel_robot.bridge.fake_sport import FakeSportServiceV1
from parcel_robot.bridge.protocol import (
    GatewayAcquireV1,
    GatewayBodyKindV1,
    GatewayCommandV1,
    GatewayStopV1,
)

WRITER_UID = 10_001
STOP_UID = 10_002
WRITER = PeerCredentialV1(pid=101, uid=WRITER_UID, gid=77)
STOPPER = PeerCredentialV1(pid=202, uid=STOP_UID, gid=77)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _core(*, writer_uid: int = WRITER_UID, stop_uid: int = STOP_UID) -> GatewayCoreV1:
    return GatewayCoreV1(
        FakeSportServiceV1(),
        policy=writer_with_stop_only_policy(
            required_hashes=BENCH_HASHES,
            writer_id="parcel-runtime",
            writer_uid=writer_uid,
            stop_uid=stop_uid,
        ),
        limits=default_limits(),
        body_kind=GatewayBodyKindV1.FAKE,
    )


def _acquire(core: GatewayCoreV1, peer: PeerCredentialV1, *, sequence: int = 1):
    return core.acquire(
        1,
        peer,
        GatewayAcquireV1(
            writer_id="parcel-runtime",
            boot_epoch=core.boot_epoch,
            sequence=sequence,
            local_ttl_ms=350,
            hashes=BENCH_HASHES,
        ),
    )


def _command(core: GatewayCoreV1, peer: PeerCredentialV1, *, sequence: int = 2):
    return core.command(
        1,
        peer,
        GatewayCommandV1(
            writer_id="parcel-runtime",
            boot_epoch=core.boot_epoch,
            sequence=sequence,
            local_ttl_ms=350,
            frame_id="base_link",
            vx_mps=0.1,
            vy_mps=0.0,
            vyaw_rad_s=0.0,
            task_id="sos1",
            trace_id=f"sos1-{sequence}",
            hashes=BENCH_HASHES,
        ),
    )


def _credential_and_stop_trials(count: int = 256) -> dict[str, object]:
    counters = {
        "cases": 0,
        "stop_uid_acquire_refused": 0,
        "stop_uid_command_refused": 0,
        "runtime_acquire_admitted": 0,
        "runtime_command_admitted": 0,
        "safety_stop_reached": 0,
        "latched": 0,
        "lease_invalidated": 0,
        "exact_zero": 0,
        "stationary_confirmed": 0,
    }
    for index in range(count):
        core = _core()
        try:
            rejected = _acquire(core, STOPPER)
            counters["stop_uid_acquire_refused"] += int(
                rejected.disposition.value == "rejected"
                and rejected.reason == "peer_not_authorized"
                and core.active_writer is None
            )
            acquired = _acquire(core, WRITER)
            counters["runtime_acquire_admitted"] += int(
                acquired.disposition.value == "accepted"
            )
            commanded = _command(core, WRITER)
            counters["runtime_command_admitted"] += int(
                commanded.disposition.value == "accepted"
            )
            report = core.explicit_stop(
                2,
                STOPPER,
                GatewayStopV1(
                    writer_id="parcel-safety",
                    boot_epoch=core.boot_epoch,
                    sequence=index + 1,
                    reason="sos1_independent_stop",
                    emergency=True,
                ),
            )
            state = core.state()
            counters["safety_stop_reached"] += int(
                report.reason == "client_stop:sos1_independent_stop"
            )
            counters["latched"] += int(state.phase.value == "latched")
            counters["lease_invalidated"] += int(not state.lease_active)
            counters["exact_zero"] += int(
                (state.vx_mps, state.vy_mps, state.vyaw_rad_s) == (0.0, 0.0, 0.0)
            )
            counters["stationary_confirmed"] += int(
                report.stop_rpc_completed and report.stationary_confirmed and state.stationary
            )
            refused_command = _command(core, STOPPER, sequence=index + 3)
            counters["stop_uid_command_refused"] += int(
                refused_command.disposition.value == "rejected"
                and core.active_writer is None
            )
            counters["cases"] += 1
        finally:
            core.close()
    return counters


def _api_gate() -> dict[str, object]:
    source = REPO / "src/parcel_robot/bridge/stop_only_gateway.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "StopOnlyGatewayClientV1"
    )
    public = sorted(
        node.name
        for node in target.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    )
    imported = sorted(
        {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and not node.level
        }
    )
    forbidden_methods = sorted(
        {"acquire", "clear", "command", "request", "send", "send_raw"} & set(public)
    )
    forbidden_imports = sorted(
        module
        for module in imported
        if any(
            token in module
            for token in ("unitree", "gateway.core", "gateway.ports", "fake_sport")
        )
    )
    return {
        "public_methods": public,
        "forbidden_methods": forbidden_methods,
        "forbidden_imports": forbidden_imports,
        "pass": not forbidden_methods and not forbidden_imports,
    }


def _notify_listener(path: Path) -> socket.socket:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    listener.settimeout(0.05)
    listener.bind(str(path))
    return listener


def _wait_message(listener: socket.socket, prefix: str, deadline_s: float = 3.0) -> bool:
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        try:
            message = listener.recv(4096).decode("utf-8")
        except TimeoutError:
            continue
        if message.startswith(prefix):
            return True
    return False


def _start_service(
    socket_path: Path,
    notify_path: Path,
) -> subprocess.Popen[bytes]:
    environ = dict(os.environ)
    existing = environ.get("PYTHONPATH", "")
    environ["PYTHONPATH"] = f"{REPO / 'src'}:{REPO}" + (f":{existing}" if existing else "")
    environ.update(
        {
            "PARCEL_ARMED": "0",
            "PARCEL_GATEWAY_SOCKET": str(socket_path),
            "NOTIFY_SOCKET": str(notify_path),
            "WATCHDOG_USEC": "400000",
        }
    )
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "parcel_robot.safety_supervisor",
            "--disarmed",
            "--poll-period-s",
            "0.02",
            "--gateway-timeout-s",
            "0.1",
            "--startup-timeout-s",
            "2.0",
        ],
        cwd=REPO,
        env=environ,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _lifecycle_signal(signal_number: int, *, keep_running: bool) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="parcel-sos1-") as directory:
        root = Path(directory)
        socket_path = root / "gateway.sock"
        notify_path = root / "notify.sock"
        listener = _notify_listener(notify_path)
        writer_uid = os.geteuid() + 10_000
        core = _core(writer_uid=writer_uid, stop_uid=os.geteuid())
        writer = PeerCredentialV1(pid=404, uid=writer_uid, gid=os.getegid())
        assert _acquire(core, writer).disposition.value == "accepted"
        assert _command(core, writer).disposition.value == "accepted"
        baseline_stops = core.stop_sequence
        halt = threading.Event()
        opened = threading.Event()
        server = GatewayServerV1(socket_path, core)
        thread = threading.Thread(
            target=server.serve,
            args=(halt,),
            kwargs={"opened_event": opened},
            daemon=True,
        )
        thread.start()
        assert opened.wait(2.0)
        process = _start_service(socket_path, notify_path)
        try:
            ready = _wait_message(listener, "READY=1")
            fresh_start_no_stop = core.stop_sequence == baseline_stops and not core.latched
            process.send_signal(signal_number)
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and not core.latched:
                time.sleep(0.01)
            latched = core.latched
            remained_running = process.poll() is None
            if keep_running and remained_running:
                process.send_signal(signal.SIGTERM)
            return_code = process.wait(timeout=3.0)
            state = core.state()
            return {
                "ready": ready,
                "fresh_start_no_stop": fresh_start_no_stop,
                "latched": latched,
                "exact_zero": (
                    state.vx_mps,
                    state.vy_mps,
                    state.vyaw_rad_s,
                )
                == (0.0, 0.0, 0.0),
                "stationary": state.stationary,
                "lease_invalidated": not state.lease_active,
                "kept_running_after_signal": remained_running,
                "expected_keep_running": keep_running,
                "return_code_zero": return_code == 0,
            }
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2.0)
            halt.set()
            thread.join(timeout=3.0)
            listener.close()


def _watchdog_failure_case() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="parcel-sos1-watchdog-") as directory:
        root = Path(directory)
        socket_path = root / "gateway.sock"
        notify_path = root / "notify.sock"
        listener = _notify_listener(notify_path)
        core = _core(writer_uid=os.geteuid() + 10_000, stop_uid=os.geteuid())
        halt = threading.Event()
        opened = threading.Event()
        server = GatewayServerV1(socket_path, core)
        thread = threading.Thread(
            target=server.serve,
            args=(halt,),
            kwargs={"opened_event": opened},
            daemon=True,
        )
        thread.start()
        assert opened.wait(2.0)
        process = _start_service(socket_path, notify_path)
        try:
            ready = _wait_message(listener, "READY=1")
            watchdog_before = _wait_message(listener, "WATCHDOG=1")
            halt.set()
            thread.join(timeout=3.0)
            while True:
                try:
                    listener.recv(4096)
                except TimeoutError:
                    break
            time.sleep(0.25)
            watchdog_after_failure = False
            deadline = time.monotonic() + 0.15
            while time.monotonic() < deadline:
                try:
                    message = listener.recv(4096).decode("utf-8")
                except TimeoutError:
                    continue
                watchdog_after_failure |= message.startswith("WATCHDOG=1")
            process.send_signal(signal.SIGTERM)
            return_code = process.wait(timeout=3.0)
            return {
                "ready": ready,
                "watchdog_before_failure": watchdog_before,
                "watchdog_after_failure": watchdog_after_failure,
                "nonzero_when_stop_unconfirmed": return_code != 0,
            }
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2.0)
            halt.set()
            thread.join(timeout=3.0)
            listener.close()


def _composition_gate() -> dict[str, object]:
    gateway = (REPO / "deploy/orin/services/parcel-gateway.service").read_text(
        encoding="utf-8"
    )
    runtime = (REPO / "deploy/orin/services/parcel-runtime.service").read_text(
        encoding="utf-8"
    )
    safety = (REPO / "deploy/orin/services/parcel-safety.service").read_text(
        encoding="utf-8"
    )
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    checks = {
        "entrypoint": 'parcel-safety = "parcel_robot.safety_supervisor:main"' in pyproject,
        "stop_uid": "PARCEL_GATEWAY_STOP_CLIENT_USER=parcel-safety" in gateway,
        "motion_group_gateway": "SupplementaryGroups=parcel-motion" in gateway,
        "motion_group_runtime": "SupplementaryGroups=parcel-motion" in runtime,
        "motion_group_safety": "SupplementaryGroups=parcel-motion" in safety,
        "socket_gateway": "PARCEL_GATEWAY_SOCKET=/run/parcel-gateway/gateway.sock" in gateway,
        "socket_runtime": "PARCEL_GATEWAY_SOCKET=/run/parcel-gateway/gateway.sock" in runtime,
        "socket_safety": "PARCEL_GATEWAY_SOCKET=/run/parcel-gateway/gateway.sock" in safety,
        "safety_exec": "ExecStart=/opt/parcel/bin/parcel-safety --disarmed" in safety,
        "safety_network_namespace": "PrivateNetwork=true" in safety,
        "safety_unix_only": "RestrictAddressFamilies=AF_UNIX" in safety,
        "safety_ip_denied": "IPAddressDeny=any" in safety,
    }
    return {"checks": checks, "pass": all(checks.values())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--run-label", required=True)
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    current = {
        name: _sha256((REPO / name).read_bytes()) for name in manifest["files"]
    }
    if current != manifest["files"]:
        raise SystemExit("frozen source/config hash mismatch")

    trials = _credential_and_stop_trials()
    api = _api_gate()
    lifecycle = {
        "sigusr1": _lifecycle_signal(signal.SIGUSR1, keep_running=True),
        "sigterm": _lifecycle_signal(signal.SIGTERM, keep_running=False),
        "sigint": _lifecycle_signal(signal.SIGINT, keep_running=False),
        "gateway_failure": _watchdog_failure_case(),
    }
    composition = _composition_gate()
    h1 = all(
        trials[key] == 256
        for key in (
            "stop_uid_acquire_refused",
            "stop_uid_command_refused",
            "runtime_acquire_admitted",
            "runtime_command_admitted",
        )
    )
    h2 = all(
        trials[key] == 256
        for key in (
            "safety_stop_reached",
            "latched",
            "lease_invalidated",
            "exact_zero",
            "stationary_confirmed",
        )
    )
    signal_gates = [lifecycle[name] for name in ("sigusr1", "sigterm", "sigint")]
    h4 = all(
        item["ready"]
        and item["fresh_start_no_stop"]
        and item["latched"]
        and item["exact_zero"]
        and item["stationary"]
        and item["lease_invalidated"]
        and item["return_code_zero"]
        and item["kept_running_after_signal"] == item["expected_keep_running"]
        for item in signal_gates
    ) and all(
        (
            lifecycle["gateway_failure"]["ready"],
            lifecycle["gateway_failure"]["watchdog_before_failure"],
            not lifecycle["gateway_failure"]["watchdog_after_failure"],
            lifecycle["gateway_failure"]["nonzero_when_stop_unconfirmed"],
        )
    )
    body = {
        "schema_version": 1,
        "study": "SOS-1",
        "manifest_sha256": _sha256(manifest_path.read_bytes()),
        "trials": trials,
        "api": api,
        "lifecycle": lifecycle,
        "composition": composition,
        "gates": {
            "SOS-H1": h1,
            "SOS-H2": h2,
            "SOS-H3": api["pass"],
            "SOS-H4": h4,
            "SOS-H5": composition["pass"],
        },
        "physical_readiness": False,
    }
    body["all_functional_gates_pass"] = all(body["gates"].values())
    body["normalized_digest"] = _sha256(_canonical(body))
    result = {"run_label": args.run_label, **body}
    _atomic_json(Path(args.output), result)
    return 0 if body["all_functional_gates_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
