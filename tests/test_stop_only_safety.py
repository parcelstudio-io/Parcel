"""Authority and lifecycle tests for the independent stop-only principal."""

from __future__ import annotations

import ast
import os
import socket
import threading
from pathlib import Path

from gateway.core import GatewayCoreV1
from gateway.credentials import (
    PeerCredentialV1,
    single_writer_policy,
    writer_with_stop_only_policy,
)
from gateway.limits import default_limits
from gateway.process import BENCH_HASHES
from gateway.server import GatewayServerV1
from parcel_robot.bridge.fake_sport import FakeSportServiceV1
from parcel_robot.bridge.protocol import (
    MAX_GATEWAY_PACKET_BYTES,
    GatewayAckDispositionV1,
    GatewayAckV1,
    GatewayAcquireV1,
    GatewayBodyKindV1,
    GatewayCommandV1,
    GatewayHelloV1,
    GatewayStopReportV1,
    GatewayStopV1,
    decode_gateway_message,
    encode_gateway_message,
)
from parcel_robot.bridge.stop_only_gateway import StopOnlyGatewayClientV1
from parcel_robot.safety_supervisor import StopOnlySafetySupervisorV1

REPO = Path(__file__).resolve().parents[1]


def _core(*, writer_uid: int, stop_uid: int) -> GatewayCoreV1:
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


def test_historical_single_writer_policy_preserves_one_uid_semantics() -> None:
    policy = single_writer_policy(
        required_hashes=BENCH_HASHES,
        writer_id="parcel-runtime",
        uid=71,
    )
    peer = PeerCredentialV1(pid=1, uid=71, gid=9)
    assert policy.admits_peer(peer)
    assert policy.admits_lease_peer(peer)
    assert not policy.is_stop_only_peer(peer)


def test_stop_only_kernel_uid_cannot_acquire_positive_authority() -> None:
    core = _core(writer_uid=101, stop_uid=202)
    try:
        stop_peer = PeerCredentialV1(pid=2, uid=202, gid=7)
        assert core.policy.admits_peer(stop_peer)
        assert not core.policy.admits_lease_peer(stop_peer)
        assert core.policy.is_stop_only_peer(stop_peer)
        response = core.acquire(
            1,
            stop_peer,
            GatewayAcquireV1(
                writer_id="parcel-runtime",
                boot_epoch=core.boot_epoch,
                sequence=1,
                local_ttl_ms=100,
                hashes=BENCH_HASHES,
            ),
        )
        assert response.reason == "peer_not_authorized"
        assert response.disposition.value == "rejected"
        assert core.active_writer is None
        assert core.phase.value == "disarmed"
    finally:
        core.close()


def test_stop_only_kernel_uid_raw_motion_fails_closed_but_stop_is_admitted(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "gateway.sock"
    writer_uid = os.geteuid() + 1
    core = _core(writer_uid=writer_uid, stop_uid=os.geteuid())
    server = GatewayServerV1(socket_path, core)
    stopped = threading.Event()
    opened = threading.Event()
    thread = threading.Thread(
        target=server.serve,
        args=(stopped,),
        kwargs={"opened_event": opened},
        daemon=True,
    )
    thread.start()
    assert opened.wait(2.0)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as raw_client:
            raw_client.settimeout(2.0)
            raw_client.connect(str(socket_path))
            hello = decode_gateway_message(raw_client.recv(MAX_GATEWAY_PACKET_BYTES))
            assert isinstance(hello, GatewayHelloV1)

            acquired = core.acquire(
                99,
                PeerCredentialV1(pid=1, uid=writer_uid, gid=7),
                GatewayAcquireV1(
                    writer_id="parcel-runtime",
                    boot_epoch=hello.boot_epoch,
                    sequence=1,
                    local_ttl_ms=350,
                    hashes=BENCH_HASHES,
                ),
            )
            assert acquired.disposition is GatewayAckDispositionV1.ACCEPTED
            assert core.writer.submitted == 0

            raw_client.sendall(
                encode_gateway_message(
                    GatewayCommandV1(
                        writer_id="parcel-runtime",
                        boot_epoch=hello.boot_epoch,
                        sequence=2,
                        local_ttl_ms=350,
                        frame_id="base_link",
                        vx_mps=0.1,
                        vy_mps=0.0,
                        vyaw_rad_s=0.0,
                        task_id="forged-stop-only-motion",
                        trace_id="forged-stop-only-motion",
                        hashes=BENCH_HASHES,
                    )
                )
            )
            refused = decode_gateway_message(
                raw_client.recv(MAX_GATEWAY_PACKET_BYTES)
            )
            assert isinstance(refused, GatewayAckV1)
            assert refused.disposition is GatewayAckDispositionV1.REJECTED
            assert refused.reason == "peer_not_authorized"
            assert core.writer.submitted == 0
            state = core.state()
            assert state.phase.value == "latched"
            assert state.stationary and not state.lease_active
            assert (state.vx_mps, state.vy_mps, state.vyaw_rad_s) == (0.0, 0.0, 0.0)

            before_stop = core.stop_sequence
            raw_client.sendall(
                encode_gateway_message(
                    GatewayStopV1(
                        writer_id="parcel-safety",
                        boot_epoch=hello.boot_epoch,
                        sequence=3,
                        reason="independent_test_stop_after_refused_motion",
                        emergency=True,
                    )
                )
            )
            report = decode_gateway_message(
                raw_client.recv(MAX_GATEWAY_PACKET_BYTES)
            )
            assert isinstance(report, GatewayStopReportV1)
            assert report.stop_sequence == before_stop + 1
            assert report.stop_rpc_completed and report.stationary_confirmed
            assert core.state().phase.value == "latched"
    finally:
        stopped.set()
        thread.join(timeout=3.0)
        assert not thread.is_alive()


def test_stop_only_kernel_uid_unconditionally_latches_runtime_lease() -> None:
    core = _core(writer_uid=101, stop_uid=202)
    try:
        writer = PeerCredentialV1(pid=1, uid=101, gid=7)
        stop_peer = PeerCredentialV1(pid=2, uid=202, gid=7)
        acquired = core.acquire(
            1,
            writer,
            GatewayAcquireV1(
                writer_id="parcel-runtime",
                boot_epoch=core.boot_epoch,
                sequence=1,
                local_ttl_ms=100,
                hashes=BENCH_HASHES,
            ),
        )
        assert acquired.disposition.value == "accepted"
        report = core.explicit_stop(
            2,
            stop_peer,
            GatewayStopV1(
                writer_id="parcel-safety",
                boot_epoch=core.boot_epoch,
                sequence=1,
                reason="independent_test_stop",
                emergency=True,
            ),
        )
        state = core.state()
        assert report.stop_rpc_completed and report.stationary_confirmed
        assert state.phase.value == "latched"
        assert state.stationary and not state.lease_active
        assert (state.vx_mps, state.vy_mps, state.vyaw_rad_s) == (0.0, 0.0, 0.0)
    finally:
        core.close()


def test_stop_only_client_and_supervisor_cross_the_real_seqpacket_seam(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "gateway.sock"
    core = _core(writer_uid=os.geteuid() + 1, stop_uid=os.geteuid())
    server = GatewayServerV1(socket_path, core)
    stopped = threading.Event()
    opened = threading.Event()
    thread = threading.Thread(
        target=server.serve,
        args=(stopped,),
        kwargs={"opened_event": opened},
        daemon=True,
    )
    thread.start()
    assert opened.wait(2.0)
    try:
        client = StopOnlyGatewayClientV1.connect(socket_path)
        supervisor = StopOnlySafetySupervisorV1(client)
        before = core.stop_sequence
        healthy = supervisor.probe()
        assert healthy.healthy and healthy.reason == "ok"
        assert core.stop_sequence == before
        outcome = supervisor.stop(reason="local_stop_signal")
        assert outcome.healthy and outcome.reason == "latched_stop_confirmed"
        assert supervisor.stop_latched
        assert outcome.state is not None and outcome.state.phase == "latched"
        assert client.authorizes_actuation is False
        assert supervisor.authorizes_actuation is False
        client.close()
    finally:
        stopped.set()
        thread.join(timeout=3.0)
        assert not thread.is_alive()


def test_stop_only_public_surface_and_imports_have_no_positive_authority() -> None:
    public = {name for name in vars(StopOnlyGatewayClientV1) if not name.startswith("_")}
    assert public == {
        "authorizes_actuation",
        "boot_epoch",
        "close",
        "connect",
        "identity",
        "reconnect",
        "state",
        "stop",
    }
    source_path = REPO / "src/parcel_robot/bridge/stop_only_gateway.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and not node.level
    }
    assert not any(
        token in module
        for module in imported
        for token in ("unitree", "gateway.core", "gateway.ports", "fake_sport")
    )
    assert not any(name in public for name in ("acquire", "command", "clear", "request"))


def test_service_and_packaging_name_the_real_stop_only_principal() -> None:
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    gateway = (REPO / "deploy/orin/services/parcel-gateway.service").read_text(
        encoding="utf-8"
    )
    runtime = (REPO / "deploy/orin/services/parcel-runtime.service").read_text(
        encoding="utf-8"
    )
    safety = (REPO / "deploy/orin/services/parcel-safety.service").read_text(
        encoding="utf-8"
    )
    assert 'parcel-safety = "parcel_robot.safety_supervisor:main"' in pyproject
    assert "PARCEL_GATEWAY_STOP_CLIENT_USER=parcel-safety" in gateway
    assert "PARCEL_GATEWAY_CLIENT_GROUP=parcel-motion" in gateway
    assert "SupplementaryGroups=parcel-motion" in gateway
    assert "SupplementaryGroups=parcel-motion" in runtime
    assert "SupplementaryGroups=parcel-motion" in safety
    assert "/opt/parcel/bin/parcel-safety --disarmed" in safety
    assert "PARCEL_GATEWAY_SOCKET=/run/parcel-gateway/gateway.sock" in safety
    assert "PrivateNetwork=true" in safety
    assert "RestrictAddressFamilies=AF_UNIX" in safety
    assert "IPAddressDeny=any" in safety


def test_safety_supervisor_installs_stop_handlers_before_ready() -> None:
    """READY must never advertise a process still using default STOP signals."""

    source = (REPO / "src/parcel_robot/safety_supervisor.py").read_text(
        encoding="utf-8"
    )
    ready_offset = source.index("notifier.ready()")
    for signal_name in ("SIGUSR1", "SIGINT", "SIGTERM"):
        handler_offset = source.index(
            f"signal.signal(signal.{signal_name}, request_latched_stop)"
        )
        assert handler_offset < ready_offset
