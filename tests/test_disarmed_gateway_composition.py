"""Product-to-gateway composition at the deliberately disarmed P0 rung.

The tests use the real ``MotionGatewayClientV1``, Unix seqpacket server,
``GatewayCoreV1``, governor, writer, and fake Sport port.  They prove only the
desktop composition boundary: no Unitree SDK, DDS, Orin, or physical robot is
present, and the adapter has no motion-enabled mode.
"""

from __future__ import annotations

import ast
import os
import socket
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from gateway.core import GatewayCoreV1
from gateway.credentials import single_writer_policy
from gateway.limits import default_limits
from gateway.process import BENCH_HASHES
from gateway.seam import cli as gateway_cli
from gateway.seam.client import (
    ConnectResultV1,
    GatewayIdentityV1,
    MotionStateV1,
    StopResultV1,
)
from gateway.server import GatewayServerV1
from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.bridge.fake_sport import FakeSportServiceV1
from parcel_robot.bridge.protocol import GatewayPhaseV1
from parcel_robot.control.factory import (
    build_motion_gateway_disarmed_control_manager,
    controller_factory_names,
    create_control_manager,
)
from parcel_robot.control.manager import ControlNotReadyError
from parcel_robot.control.models import ControlLifecycle
from parcel_robot.control.motion_gateway import (
    DisarmedGatewayError,
    build_disarmed_gateway_pair,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.runtime import RobotRuntime
from parcel_robot.safety import SafetyLimits

WRITER_ID = "parcel-runtime"
TEST_LIMITS = replace(
    default_limits(),
    stop_timeout_s=0.2,
    stop_retry_s=0.05,
)

requires_seqpacket = pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "SOCK_SEQPACKET"),
    reason="the motion gateway speaks Unix SOCK_SEQPACKET",
)


@dataclass
class ServedGateway:
    socket_path: Path
    sport: FakeSportServiceV1
    events: list[dict[str, object]]
    core: GatewayCoreV1
    server: GatewayServerV1
    stop_event: threading.Event
    thread: threading.Thread

    @classmethod
    def start(cls, socket_path: Path) -> ServedGateway:
        events: list[dict[str, object]] = []
        sport = FakeSportServiceV1(event_sink=events.append)
        core = GatewayCoreV1(
            sport,
            policy=single_writer_policy(
                required_hashes=BENCH_HASHES,
                writer_id=WRITER_ID,
            ),
            limits=TEST_LIMITS,
        )
        server = GatewayServerV1(socket_path, core)
        stop_event = threading.Event()
        thread = threading.Thread(
            target=server.serve,
            args=(stop_event,),
            name="test-disarmed-product-gateway",
            daemon=True,
        )
        made = cls(socket_path, sport, events, core, server, stop_event, thread)
        thread.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if socket_path.exists():
                return made
            if not thread.is_alive():
                raise AssertionError("the gateway server exited before creating its socket")
            time.sleep(0.005)
        raise AssertionError("the gateway socket never appeared")

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5.0)
        assert not self.thread.is_alive()

    def event_count(self, name: str) -> int:
        return sum(row.get("event") == name for row in self.events)


class RuntimeBackend:
    """Simulator observation carrier; actuation must never reach this bypass."""

    name = "disarmed-runtime-fixture"

    def __init__(self) -> None:
        self.moves: list[VelocityCommand] = []
        self.stops = 0

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            nearest_obstacle_bearing_rad=0.0,
            backend=self.name,
        )

    def move(self, command: VelocityCommand) -> None:
        self.moves.append(command)

    def stop(self) -> None:
        self.stops += 1

    def pose(self, _pose: object) -> None:
        raise AssertionError("external-control runtime must not bypass through backend.pose")

    def trajectory(self, _skill: object) -> None:
        raise AssertionError("external-control runtime must not bypass through backend.trajectory")

    def expression(self, _offsets: dict[str, float]) -> None:
        return

    def move_owner(self, _dx: float, _dy: float) -> None:
        return


def _config(socket_path: Path, **gateway_overrides: object) -> dict[str, object]:
    gateway = {
        "mode": "disarmed",
        "socket_path": str(socket_path),
        "writer_id": WRITER_ID,
        "timeout_s": 1.0,
        **gateway_overrides,
    }
    return {
        "control_hz": 100.0,
        "command_timeout_s": 0.35,
        "state_timeout_s": 0.25,
        "startup_timeout_s": 1.0,
        "stop_timeout_s": 0.5,
        "stop_retry_s": 0.05,
        "io_quiesce_timeout_s": 1.5,
        "stop_settled_samples": 2,
        "settled_linear_speed_mps": 0.08,
        "settled_yaw_speed_rad_s": 0.12,
        "motion_gateway": gateway,
    }


def _runtime_config(tmp_path: Path) -> Path:
    repo = Path(__file__).resolve().parents[1]
    path = tmp_path / "runtime.yaml"
    path.write_text(
        f"""
skills:
  root: {repo / "configs" / "skills"}
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


def _text_audio() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="disarmed gateway integration",
    )


def _spin(manager: object, *, timeout_s: float, predicate) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        manager.tick()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError(f"condition did not settle: {manager.snapshot().as_dict()}")


@pytest.fixture
def served(tmp_path: Path):
    made = ServedGateway.start(tmp_path / "gateway.sock")
    try:
        yield made
    finally:
        made.close()


@requires_seqpacket
def test_registered_product_manager_starts_disarmed_and_cannot_form_motion(
    served: ServedGateway,
) -> None:
    assert "motion_gateway_disarmed" in controller_factory_names()
    manager = create_control_manager(
        "motion_gateway_disarmed",
        _config(served.socket_path),
        SafetyLimits(),
    )
    try:
        manager.start(threaded=False)
        _spin(
            manager,
            timeout_s=1.0,
            predicate=lambda: manager.snapshot().lifecycle is ControlLifecycle.IDLE,
        )

        assert served.core.phase is GatewayPhaseV1.DISARMED
        assert served.sport.writer_id is None
        assert manager.controller.capabilities.body_velocity is False
        with pytest.raises(ControlNotReadyError, match="does not accept body-velocity"):
            manager.set_target(VelocityCommand(vx=0.01), source="runtime-product-slice")

        assert served.event_count("lease_acquired") == 0
        assert served.event_count("move_called") == 0
        assert served.event_count("move_accepted") == 0
        assert served.event_count("move_applied") == 0
        assert served.core.phase is GatewayPhaseV1.DISARMED
    finally:
        manager.close()


@requires_seqpacket
def test_normal_runtime_accepts_explicit_disarmed_manager_without_backend_bypass(
    served: ServedGateway,
    tmp_path: Path,
) -> None:
    manager = build_motion_gateway_disarmed_control_manager(
        _config(served.socket_path),
        SafetyLimits(),
    )
    backend = RuntimeBackend()
    runtime = RobotRuntime(
        _runtime_config(tmp_path),
        backend,
        audio_status=_text_audio(),
        control_manager=manager,
    )
    try:
        assert runtime.control_manager is manager
        assert runtime._synchronous_control_dispatch is False
        manager.start(threaded=False)
        _spin(
            manager,
            timeout_s=1.0,
            predicate=lambda: manager.snapshot().lifecycle is ControlLifecycle.IDLE,
        )

        runtime.manual_motion(0.05, 0.0, 0.0)
        runtime._dispatch_active()

        assert backend.moves == []
        assert served.event_count("lease_acquired") == 0
        assert served.event_count("move_called") == 0
        assert served.core.phase is GatewayPhaseV1.DISARMED
    finally:
        runtime.close()


@requires_seqpacket
def test_ordinary_stop_witnesses_zero_without_latching_or_claiming_a_lease(
    served: ServedGateway,
) -> None:
    manager = build_motion_gateway_disarmed_control_manager(
        _config(served.socket_path),
        SafetyLimits(),
    )
    try:
        manager.start(threaded=False)
        _spin(
            manager,
            timeout_s=1.0,
            predicate=lambda: manager.snapshot().lifecycle is ControlLifecycle.IDLE,
        )
        stops_before = served.event_count("stop_move_succeeded")

        manager.stop("owner_stop")
        _spin(
            manager,
            timeout_s=1.0,
            predicate=lambda: manager.snapshot().stop_confirmed,
        )

        # A fresh DISARMED + zero state is already the required witness. Sending
        # a non-lease stop would unnecessarily latch the gateway, so it is
        # deliberately elided while the fake remains observably at exact zero.
        assert served.event_count("stop_move_succeeded") == stops_before
        assert served.core.phase is GatewayPhaseV1.DISARMED
        assert served.sport.writer_id is None
        assert served.event_count("move_called") == 0
    finally:
        manager.close()


@requires_seqpacket
def test_emergency_stop_always_crosses_the_socket_and_latches_the_gateway(
    served: ServedGateway,
) -> None:
    manager = build_motion_gateway_disarmed_control_manager(
        _config(served.socket_path),
        SafetyLimits(),
    )
    try:
        manager.start(threaded=False)
        _spin(
            manager,
            timeout_s=1.0,
            predicate=lambda: manager.snapshot().lifecycle is ControlLifecycle.IDLE,
        )
        stops_before = served.event_count("stop_move_succeeded")

        manager.emergency_stop()
        _spin(
            manager,
            timeout_s=1.0,
            predicate=lambda: (
                manager.snapshot().emergency_stopped
                and manager.snapshot().stop_confirmed
                and served.core.phase is GatewayPhaseV1.LATCHED
            ),
        )

        report = manager.controller.last_stop_result
        assert report is not None
        assert report.reason == "client_stop:emergency_stop"
        assert report.confirmed_stationary is True
        assert served.event_count("stop_move_succeeded") > stops_before
        assert served.event_count("lease_acquired") == 0
        assert served.event_count("move_called") == 0
        with pytest.raises(DisarmedGatewayError, match="restart the gateway"):
            manager.clear_emergency_stop()
    finally:
        manager.close()


@requires_seqpacket
def test_explicit_reconnect_returns_disarmed_and_never_reacquires(
    served: ServedGateway,
) -> None:
    manager = build_motion_gateway_disarmed_control_manager(
        _config(served.socket_path),
        SafetyLimits(),
    )
    try:
        manager.start(threaded=False)
        source = manager.state_source
        result = source.reconnect_disarmed(settle_timeout_s=0.2)

        assert result.armed is False
        assert result.identity.phase == "disarmed"
        assert source.latest() is not None
        assert served.event_count("lease_acquired") == 0
        assert served.event_count("move_called") == 0
        assert served.core.phase is GatewayPhaseV1.DISARMED
    finally:
        manager.close()


def test_configuration_has_only_an_exact_disarmed_mode(tmp_path: Path) -> None:
    socket_path = tmp_path / "gateway.sock"
    for unsafe in ("armed", "vendor", "fake", True, None):
        with pytest.raises(ValueError, match="must be exactly 'disarmed'"):
            build_motion_gateway_disarmed_control_manager(
                _config(socket_path, mode=unsafe),
                SafetyLimits(),
            )
    for extra in ({"sport": "vendor"}, {"auto_acquire": True}, {"armed": True}):
        with pytest.raises(ValueError, match="unknown control.motion_gateway keys"):
            build_motion_gateway_disarmed_control_manager(
                _config(socket_path, **extra),
                SafetyLimits(),
            )


@pytest.mark.parametrize(
    ("hello_phase", "state_phase", "lease_active", "writer_id"),
    [
        ("armed", "armed", True, "other-writer"),
        ("latched", "latched", False, ""),
        ("disarmed", "disarmed", True, "other-writer"),
    ],
)
def test_connect_refuses_non_disarmed_gateway_truth(
    tmp_path: Path,
    hello_phase: str,
    state_phase: str,
    lease_active: bool,
    writer_id: str,
) -> None:
    class UnsafePhaseClient:
        armed = False

        def __init__(self) -> None:
            self.identity = GatewayIdentityV1(
                boot_epoch="test-boot",
                phase=hello_phase,
            )
            self.closed = False

        def state(self) -> MotionStateV1:
            return MotionStateV1(
                boot_epoch="test-boot",
                phase=state_phase,
                state_sequence=1,
                state_age_ms=0.0,
                lease_active=lease_active,
                writer_id=writer_id,
                vx_mps=0.0,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
                stationary=True,
                last_stop_sequence=0,
                last_stop_reason="",
            )

        def close(self) -> None:
            self.closed = True

    client = UnsafePhaseClient()
    _controller, source = build_disarmed_gateway_pair(
        tmp_path / "gateway.sock",
        client_factory=lambda *_args, **_kwargs: client,
    )
    with pytest.raises(DisarmedGatewayError, match="phase, epoch, or lease"):
        source.start()
    assert client.closed


def test_reconnect_refuses_phase_change_and_drops_session(tmp_path: Path) -> None:
    class PhaseChangingClient:
        armed = False

        def __init__(self) -> None:
            self.identity = GatewayIdentityV1("boot-1", "disarmed")
            self.closed = False

        def state(self) -> MotionStateV1:
            return MotionStateV1(
                boot_epoch=self.identity.boot_epoch,
                phase=self.identity.phase,
                state_sequence=1,
                state_age_ms=0.0,
                lease_active=self.identity.phase == "armed",
                writer_id="other-writer" if self.identity.phase == "armed" else "",
                vx_mps=0.0,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
                stationary=True,
                last_stop_sequence=0,
                last_stop_reason="",
            )

        def reconnect(self, *, settle_timeout_s: float) -> ConnectResultV1:
            assert settle_timeout_s == 0.2
            previous = self.identity.boot_epoch
            self.identity = GatewayIdentityV1("boot-2", "latched")
            return ConnectResultV1(self.identity, False, True, previous)

        def close(self) -> None:
            self.closed = True

    client = PhaseChangingClient()
    _controller, source = build_disarmed_gateway_pair(
        tmp_path / "gateway.sock",
        client_factory=lambda *_args, **_kwargs: client,
    )
    source.start()
    with pytest.raises(DisarmedGatewayError, match="phase, epoch, or lease"):
        source.reconnect_disarmed(settle_timeout_s=0.2)
    assert client.closed
    assert source.latest() is None


@pytest.mark.parametrize(
    ("boot_epoch", "phase", "lease_active", "writer_id"),
    [
        ("boot-2", "disarmed", False, ""),
        ("boot-1", "armed", True, "parcel-runtime"),
        ("boot-1", "disarmed", True, "other-writer"),
        ("boot-1", "disarmed", False, "other-writer"),
    ],
)
def test_every_state_sample_rechecks_epoch_phase_and_lease(
    tmp_path: Path,
    boot_epoch: str,
    phase: str,
    lease_active: bool,
    writer_id: str,
) -> None:
    class DriftingClient:
        armed = False

        def __init__(self) -> None:
            self.identity = GatewayIdentityV1("boot-1", "disarmed")
            self.boot_epoch = "boot-1"
            self.phase = "disarmed"
            self.lease_active = False
            self.writer_id = ""
            self.closed = False

        def state(self) -> MotionStateV1:
            return MotionStateV1(
                boot_epoch=self.boot_epoch,
                phase=self.phase,
                state_sequence=1,
                state_age_ms=0.0,
                lease_active=self.lease_active,
                writer_id=self.writer_id,
                vx_mps=0.0,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
                stationary=True,
                last_stop_sequence=0,
                last_stop_reason="",
            )

        def close(self) -> None:
            self.closed = True

    client = DriftingClient()
    _controller, source = build_disarmed_gateway_pair(
        tmp_path / "gateway.sock",
        client_factory=lambda *_args, **_kwargs: client,
    )
    source.start()
    client.boot_epoch = boot_epoch
    client.phase = phase
    client.lease_active = lease_active
    client.writer_id = writer_id

    with pytest.raises(DisarmedGatewayError, match="phase, epoch, or lease"):
        source.latest()
    assert client.closed
    assert source.latest() is None


def test_stop_report_must_match_connected_boot_epoch_without_state_prequery(
    tmp_path: Path,
) -> None:
    class WrongEpochStopClient:
        armed = False
        identity = GatewayIdentityV1("boot-1", "disarmed")

        def __init__(self) -> None:
            self.state_calls = 0
            self.stop_calls = 0
            self.closed = False

        def state(self) -> MotionStateV1:
            self.state_calls += 1
            return MotionStateV1(
                boot_epoch="boot-1",
                phase="disarmed",
                state_sequence=1,
                state_age_ms=0.0,
                lease_active=False,
                writer_id="",
                vx_mps=0.0,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
                stationary=True,
                last_stop_sequence=0,
                last_stop_reason="",
            )

        def stop(self, *, reason: str, emergency: bool) -> StopResultV1:
            self.stop_calls += 1
            assert reason == "emergency_stop"
            assert emergency
            return StopResultV1(
                boot_epoch="boot-2",
                stop_sequence=1,
                reason="client_stop:emergency_stop",
                stop_rpc_completed=True,
                stationary_confirmed=True,
                state_sequence=2,
            )

        def close(self) -> None:
            self.closed = True

    client = WrongEpochStopClient()
    controller, source = build_disarmed_gateway_pair(
        tmp_path / "gateway.sock",
        client_factory=lambda *_args, **_kwargs: client,
    )
    source.start()
    controller.activate()
    state_calls_before = client.state_calls
    with pytest.raises(DisarmedGatewayError, match="epoch or stationary"):
        controller.emergency_stop()
    assert client.stop_calls == 1
    assert client.state_calls == state_calls_before
    assert client.closed
    assert source.latest() is None


def test_emergency_stop_does_not_wait_for_a_state_query(tmp_path: Path) -> None:
    class StopOnlyClient:
        armed = False
        identity = GatewayIdentityV1(boot_epoch="test-boot", phase="disarmed")

        def __init__(self) -> None:
            self.state_calls = 0
            self.stop_calls = 0

        def state(self):
            self.state_calls += 1
            return MotionStateV1(
                boot_epoch="test-boot",
                phase="disarmed",
                state_sequence=1,
                state_age_ms=0.0,
                lease_active=False,
                writer_id="",
                vx_mps=0.0,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
                stationary=True,
                last_stop_sequence=0,
                last_stop_reason="",
            )

        def stop(self, *, reason: str, emergency: bool) -> StopResultV1:
            self.stop_calls += 1
            assert reason == "emergency_stop"
            assert emergency is True
            return StopResultV1(
                boot_epoch="test-boot",
                stop_sequence=1,
                reason="client_stop:emergency_stop",
                stop_rpc_completed=True,
                stationary_confirmed=True,
                state_sequence=2,
            )

        def close(self) -> None:
            return

    client = StopOnlyClient()

    def connect(*_args: object, **_kwargs: object):
        return client

    controller, source = build_disarmed_gateway_pair(
        tmp_path / "gateway.sock",
        client_factory=connect,
    )
    try:
        source.start()
        controller.activate()
        state_calls_before_stop = client.state_calls
        controller.emergency_stop()
        assert client.stop_calls == 1
        assert client.state_calls == state_calls_before_stop
    finally:
        controller.close()
        source.close()


def test_ordinary_stop_does_not_elide_on_stale_stationary_state(tmp_path: Path) -> None:
    class StaleClient:
        armed = False
        identity = GatewayIdentityV1(boot_epoch="test-boot", phase="disarmed")

        def __init__(self) -> None:
            self.stop_calls = 0

        def state(self) -> MotionStateV1:
            return MotionStateV1(
                boot_epoch="test-boot",
                phase="disarmed",
                state_sequence=1,
                state_age_ms=251.0,
                lease_active=False,
                writer_id="",
                vx_mps=0.0,
                vy_mps=0.0,
                vyaw_rad_s=0.0,
                stationary=True,
                last_stop_sequence=0,
                last_stop_reason="",
            )

        def stop(self, *, reason: str, emergency: bool) -> StopResultV1:
            self.stop_calls += 1
            assert reason == "owner_stop"
            assert emergency is False
            return StopResultV1(
                boot_epoch="test-boot",
                stop_sequence=1,
                reason="client_stop:owner_stop",
                stop_rpc_completed=True,
                stationary_confirmed=True,
                state_sequence=2,
            )

        def close(self) -> None:
            return

    client = StaleClient()

    def connect(*_args: object, **_kwargs: object):
        return client

    controller, source = build_disarmed_gateway_pair(
        tmp_path / "gateway.sock",
        state_timeout_s=0.25,
        client_factory=connect,
    )
    try:
        source.start()
        controller.activate()
        controller.stop("owner_stop")
        assert client.stop_calls == 1
    finally:
        controller.close()
        source.close()


def test_adapter_source_contains_no_arm_command_or_vendor_import() -> None:
    """Structural anti-regression: the disarmed classes cannot grow motion."""

    from parcel_robot.control import motion_gateway

    source = Path(motion_gateway.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source, feature_version=(3, 10))
    disarmed_classes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name
        in {
            "_DisarmedGatewaySessionV1",
            "DisarmedGatewayStateSourceV1",
            "DisarmedGatewayControllerV1",
        }
    }
    assert set(disarmed_classes) == {
        "_DisarmedGatewaySessionV1",
        "DisarmedGatewayStateSourceV1",
        "DisarmedGatewayControllerV1",
    }
    calls = {
        node.func.attr
        for class_node in disarmed_classes.values()
        for node in ast.walk(class_node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
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
    assert "acquire" not in calls
    assert "command" not in calls
    assert not any("unitree" in name or "fake_sport" in name for name in imported)


def test_gateway_vendor_mode_refuses_incomplete_access_before_backend_build(
    tmp_path: Path,
) -> None:
    args = gateway_cli._parser().parse_args(
        [
            "--disarmed",
            "--sport",
            "vendor",
            "--socket",
            str(tmp_path / "gateway.sock"),
            "--audit-log",
            str(tmp_path / "audit.jsonl"),
        ]
    )
    with pytest.raises(
        gateway_cli.GatewayLaunchError,
        match="invalid vendor client/socket access",
    ):
        gateway_cli.settings_from(args, {"PARCEL_ARMED": "0"})
