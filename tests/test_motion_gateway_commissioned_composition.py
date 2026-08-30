"""Focused product composition proofs for the commissioned motion gateway."""

from __future__ import annotations

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
from gateway.ports import SportSampleV1, UnitreeLowStateSampleV1
from gateway.process import BENCH_HASHES
from gateway.server import GatewayServerV1
from parcel_robot.bridge.fake_gateway import FakeGatewayCoreV1
from parcel_robot.bridge.fake_sport import FakeSportFaultsV1, FakeSportServiceV1
from parcel_robot.bridge.gateway_client import (
    ArmResultV1,
    CommandResultV1,
    GatewayIdentityV1,
    GatewayProtocolError,
    MotionStateV2,
    StopResultV1,
)
from parcel_robot.bridge.protocol import GatewayBodyKindV1, GatewayHashesV1, GatewayPhaseV1
from parcel_robot.control.base import CommissionedStateSource
from parcel_robot.control.factory import (
    build_motion_gateway_commissioned_control_manager,
    controller_factory_names,
    create_control_manager,
)
from parcel_robot.control.manager import ControlNotReadyError
from parcel_robot.control.models import ControlLifecycle, FaultReason, TimedVelocitySetpoint
from parcel_robot.control.motion_gateway import (
    CommissionedGatewayError,
    CommissionedGatewayStateSourceV1,
    build_commissioned_gateway_pair,
)
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.models import VelocityCommand
from parcel_robot.safety import SafetyLimits

WRITER_ID = "parcel-runtime"
SESSION_EPOCH = "commissioned-test-session"
COMMISSIONED_HASHES = GatewayHashesV1(
    config_sha256="1" * 64,
    capability_sha256="2" * 64,
    calibration_sha256="3" * 64,
    firmware_sha256="4" * 64,
)
TEST_LIMITS = replace(
    default_limits(),
    stop_timeout_s=0.2,
    stop_retry_s=0.05,
)


def _motion_state_v2(**overrides: object) -> MotionStateV2:
    values: dict[str, object] = {
        "boot_epoch": "boot-v2",
        "phase": "disarmed",
        "state_sequence": 1,
        "state_age_ms": 0.0,
        "lease_active": False,
        "writer_id": "",
        "vx_mps": 0.0,
        "vy_mps": 0.0,
        "vyaw_rad_s": 0.0,
        "stationary": True,
        "last_stop_sequence": 0,
        "last_stop_reason": "",
        "body_kind": GatewayBodyKindV1.UNITREE_SDK2,
        "telemetry_valid": True,
        "vendor_position_m": (0.0, 0.0, 0.32),
        "vendor_rpy_rad": (0.0, 0.0, 0.0),
        "mode": 3,
        "error_code": 0,
        "source_time_s": 1_700_000_000.25,
        "sport_foot_force_raw": (10, 11, 12, 13),
        "feedback_integrity_ok": True,
        "feedback_integrity_reason": "ok",
        "commissioned_soc_ok": True,
        "commissioned_soc_reason": "soc_above_commissioned_minimum",
        "low_state_valid": True,
        "low_state_sequence": 1,
        "low_state_age_ms": 0.0,
        "low_state_tick": 1234,
        "battery_soc_percent": 87,
        "power_v": 30.5,
        "power_a": 1.25,
        "max_motor_temperature_raw": 43,
        "motor_lost_max_raw": 0,
        "foot_force_est_raw": (9, 10, 11, 12),
        "imu_temperature_raw": 39,
        "temperature_ntc_raw": (44, 45),
        "bms_status": 2,
    }
    values.update(overrides)
    return MotionStateV2(**values)  # type: ignore[arg-type]


class _TelemetryFakeSport(FakeSportServiceV1):
    """Contract-test fake; still never evidence of hardware qualification."""

    vendor_position_m = (0.0, 0.0, 0.32)
    vendor_rpy_rad = (0.0, 0.0, 0.0)
    mode = 3
    error_code = 0
    feedback_integrity_ok = True
    feedback_integrity_reason = "ok"
    commissioned_soc_ok = True
    commissioned_soc_reason = "soc_above_commissioned_minimum"
    sport_received_at_offset_s = 0.0
    low_received_at_offset_s = 0.0

    def state(self) -> SportSampleV1:
        sample = super().state()
        return SportSampleV1(
            sequence=sample.sequence,
            received_at_monotonic_s=(
                sample.received_at_monotonic_s + self.sport_received_at_offset_s
            ),
            vx_mps=sample.vx_mps,
            vy_mps=sample.vy_mps,
            vyaw_rad_s=sample.vyaw_rad_s,
            lease_active=sample.lease_active,
            telemetry_valid=True,
            vendor_position_m=self.vendor_position_m,
            vendor_rpy_rad=self.vendor_rpy_rad,
            mode=self.mode,
            error_code=self.error_code,
            source_time_s=1_700_000_000.0 + sample.sequence / 50.0,
            sport_foot_force_raw=(10, 11, 12, 13),
            feedback_integrity_ok=self.feedback_integrity_ok,
            feedback_integrity_reason=self.feedback_integrity_reason,
            commissioned_soc_ok=self.commissioned_soc_ok,
            commissioned_soc_reason=self.commissioned_soc_reason,
            low_state=UnitreeLowStateSampleV1(
                sequence=sample.sequence,
                received_at_monotonic_s=(
                    sample.received_at_monotonic_s + self.low_received_at_offset_s
                ),
                tick=sample.sequence,
                battery_soc_percent=87,
                power_v=30.5,
                power_a=1.25,
                max_motor_temperature_raw=43,
                motor_lost_max_raw=0,
                foot_force_est_raw=(9, 10, 11, 12),
                imu_temperature_raw=39,
                temperature_ntc_raw=(44, 45),
                bms_status=2,
            ),
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
    def start(
        cls,
        socket_path: Path,
        *,
        faults: FakeSportFaultsV1 | None = None,
        body_kind: GatewayBodyKindV1 = GatewayBodyKindV1.UNKNOWN,
        required_hashes: GatewayHashesV1 = COMMISSIONED_HASHES,
    ) -> ServedGateway:
        events: list[dict[str, object]] = []
        sport_type = (
            _TelemetryFakeSport
            if body_kind is GatewayBodyKindV1.UNITREE_SDK2
            else FakeSportServiceV1
        )
        sport = sport_type(faults=faults, event_sink=events.append)
        core = GatewayCoreV1(
            sport,
            policy=single_writer_policy(
                required_hashes=required_hashes,
                writer_id=WRITER_ID,
            ),
            limits=TEST_LIMITS,
            body_kind=body_kind,
        )
        server = GatewayServerV1(socket_path, core)
        stop_event = threading.Event()
        thread = threading.Thread(
            target=server.serve,
            args=(stop_event,),
            name="test-commissioned-product-gateway",
            daemon=True,
        )
        made = cls(socket_path, sport, events, core, server, stop_event, thread)
        thread.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if socket_path.exists():
                return made
            if not thread.is_alive():
                raise AssertionError("gateway exited before creating its socket")
            time.sleep(0.005)
        raise AssertionError("gateway socket never appeared")

    def close(self) -> None:
        if not self.thread.is_alive():
            return
        self.stop_event.set()
        self.thread.join(timeout=5.0)
        assert not self.thread.is_alive()

    def event_count(self, name: str) -> int:
        return sum(row.get("event") == name for row in self.events)


def _config(socket_path: Path, **gateway_overrides: object) -> dict[str, object]:
    return {
        "control_hz": 100.0,
        "command_timeout_s": 0.25,
        "state_timeout_s": 0.25,
        "startup_timeout_s": 0.5,
        "stop_timeout_s": 0.2,
        "stop_retry_s": 0.05,
        "io_quiesce_timeout_s": 1.0,
        "stop_settled_samples": 2,
        "settled_linear_speed_mps": 0.08,
        "settled_yaw_speed_rad_s": 0.12,
        "motion_gateway": {
            "mode": "commissioned",
            "socket_path": str(socket_path),
            "writer_id": WRITER_ID,
            "timeout_s": 0.5,
            "local_ttl_ms": 200,
            "session_epoch": SESSION_EPOCH,
            "expected_hashes": COMMISSIONED_HASHES.as_dict(),
            **gateway_overrides,
        },
    }


def _spin(manager: object, *, timeout_s: float, predicate) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        manager.tick()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError(f"condition did not settle: {manager.snapshot().as_dict()}")


def _wait_for_event(served: ServedGateway, name: str, *, timeout_s: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if served.event_count(name):
            return
        time.sleep(0.002)
    raise AssertionError(f"fake Sport event never arrived: {name}: {served.events}")


def _wait_for_source_state(
    source: CommissionedGatewayStateSourceV1,
    predicate,
    *,
    timeout_s: float = 0.5,
):
    """Wait at an explicit test seam for the asynchronous cache to advance."""

    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = source.latest()
        if last is not None and predicate(last):
            return last
        time.sleep(0.002)
    raise AssertionError(f"gateway state cache did not settle; last={last!r}")


@pytest.fixture
def unitree_attested_fixture(tmp_path: Path):
    # This is still FakeSport.  The explicit label exercises product policy;
    # it is not evidence that the fake discovered or attested a physical body.
    made = ServedGateway.start(
        tmp_path / "g.sock",
        body_kind=GatewayBodyKindV1.UNITREE_SDK2,
    )
    try:
        yield made
    finally:
        made.close()


@requires_seqpacket
def test_explicitly_unitree_labeled_fixture_exercises_arm_motion_and_socket_stops(
    unitree_attested_fixture: ServedGateway,
) -> None:
    served = unitree_attested_fixture
    assert "motion_gateway_commissioned" in controller_factory_names()
    manager = create_control_manager(
        "motion_gateway_commissioned",
        _config(served.socket_path),
        SafetyLimits(),
    )
    try:
        assert isinstance(manager.state_source, CommissionedStateSource)
        assert manager.state_source.origin is EvidenceOrigin.PHYSICAL
        assert manager.state_source.session_epoch != SESSION_EPOCH
        assert manager.state_source.session_epoch.startswith("motion-gateway-")
        producer_session_epoch = manager.state_source.session_epoch
        manager.start(threaded=False)
        _spin(
            manager,
            timeout_s=1.0,
            predicate=lambda: manager.snapshot().lifecycle is ControlLifecycle.IDLE,
        )

        assert served.core.phase is GatewayPhaseV1.DISARMED
        assert served.sport.writer_id is None
        assert served.core.audit.events("gateway_armed") == ()
        assert manager.controller.capabilities.body_velocity is False
        with pytest.raises(ControlNotReadyError, match="does not accept body-velocity"):
            manager.set_target(VelocityCommand(vx=0.05), source="pre-arm")

        with pytest.raises(CommissionedGatewayError, match="manager-owned"):
            manager.controller.arm(local_ttl_ms=200)
        target = manager.arm_and_set_target(
            VelocityCommand(vx=0.08, vy=0.01, vyaw=0.02),
            source="operator-motion",
            ttl=0.12,
        )
        arm = manager.controller.last_arm_result
        assert arm is not None
        assert arm.armed is True
        assert arm.boot_epoch == served.core.boot_epoch
        assert served.core.phase is GatewayPhaseV1.ARMED
        assert served.sport.writer_id == WRITER_ID
        assert manager.controller.capabilities.body_velocity is True

        commissioned = manager.state_source.latest()
        assert commissioned is not None
        assert commissioned.origin is EvidenceOrigin.PHYSICAL
        assert commissioned.session_epoch == producer_session_epoch
        assert commissioned.position == (0.0, 0.0, 0.0)
        assert (commissioned.roll, commissioned.pitch, commissioned.yaw) == (0.0, 0.0, 0.0)
        assert commissioned.mode == 3
        assert commissioned.error_code == 0
        assert commissioned.source_time_s is not None
        assert commissioned.foot_forces == ()
        truth = dict(commissioned.vendor_extra)
        assert truth["gateway_boot_epoch"] == served.core.boot_epoch
        assert truth["gateway_phase"] == "armed"
        assert truth["gateway_writer_id"] == WRITER_ID
        assert truth["gateway_commissioning_record_id"] == SESSION_EPOCH
        assert truth["unitree_battery_soc_percent"] == "87"
        assert truth["unitree_max_motor_temperature_raw"] == "43"
        assert truth["unitree_foot_force_est_raw"] == "9,10,11,12"
        assert truth["unitree_sport_foot_force_raw_unordered"] == "10,11,12,13"
        assert truth["unitree_feedback_integrity_ok"] == "true"
        assert truth["unitree_feedback_integrity_reason"] == "ok"
        assert truth["unitree_commissioned_soc_ok"] == "true"
        assert truth["unitree_commissioned_soc_reason"] == "soc_above_commissioned_minimum"

        manager.tick()
        _wait_for_event(served, "move_applied")
        result = manager.controller.last_command_result
        assert result is not None and result.admitted is True
        admitted = served.core.audit.events("command_admitted")[-1]
        ttl_ms = int(dict(admitted.detail)["local_ttl_ms"])
        remaining_at_issue_ms = int((target.valid_until - target.issued_at) * 1000.0)
        assert 1 <= ttl_ms <= min(200, remaining_at_issue_ms)

        stops_before = served.event_count("stop_move_succeeded")
        manager.stop("owner_stop")
        _spin(
            manager,
            timeout_s=1.0,
            predicate=lambda: manager.snapshot().stop_confirmed,
        )
        _wait_for_event(served, "stop_move_succeeded")
        assert served.event_count("stop_move_succeeded") > stops_before
        assert served.core.audit.events("client_stop_requested")[-1]
        assert served.core.phase is GatewayPhaseV1.DISARMED
        assert served.sport.writer_id is None
        assert manager.controller.capabilities.body_velocity is False
        with pytest.raises(ControlNotReadyError, match="does not accept body-velocity"):
            manager.set_target(VelocityCommand(vx=0.05), source="needs-rearm")

        manager.arm_and_set_target(
            VelocityCommand(vx=0.05),
            source="operator-motion-before-estop",
            ttl=0.12,
        )
        assert manager.controller.last_arm_result is not None
        assert manager.controller.last_arm_result.armed is True
        stops_before_estop = served.event_count("stop_move_succeeded")
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
        assert served.event_count("stop_move_succeeded") > stops_before_estop
        report = manager.controller.last_stop_result
        assert report is not None
        assert report.boot_epoch == served.core.boot_epoch
        assert report.reason == "client_stop:emergency_stop"
        assert report.confirmed_stationary is True
    finally:
        manager.close()


@requires_seqpacket
def test_threaded_manager_arms_and_installs_first_target_without_empty_target_stop(
    unitree_attested_fixture: ServedGateway,
) -> None:
    """The production 50 Hz path excludes the former arm/target race.

    Hold the manager-owned authority hook after the real gateway has armed for
    several control periods.  The background control thread must not enter its
    ``no_target`` branch during that deliberately widened window.  Once the
    hook returns, the already-validated target is visible to the very next tick.
    """

    served = unitree_attested_fixture
    config = _config(served.socket_path)
    config["control_hz"] = 50.0
    manager = build_motion_gateway_commissioned_control_manager(
        config,
        SafetyLimits(),
    )
    authority_verified = threading.Event()
    release_arm = threading.Event()
    result: list[object] = []
    failures: list[BaseException] = []
    try:
        manager.start(threaded=True)
        deadline = time.monotonic() + 1.0
        while (
            manager.snapshot().lifecycle is not ControlLifecycle.IDLE
            and time.monotonic() < deadline
        ):
            time.sleep(0.005)
        assert manager.snapshot().lifecycle is ControlLifecycle.IDLE

        original_acquire = manager.controller.acquire_motion_authority

        def delayed_acquire(owner_token: object) -> None:
            original_acquire(owner_token)
            authority_verified.set()
            if not release_arm.wait(0.5):
                raise RuntimeError("test did not release the verified arm")

        manager.controller.acquire_motion_authority = delayed_acquire

        def arm_target() -> None:
            try:
                result.append(
                    manager.arm_and_set_target(
                        VelocityCommand(vx=0.08, vy=0.01, vyaw=0.02),
                        source="threaded-operator-motion",
                        ttl=0.18,
                    )
                )
            except BaseException as error:  # noqa: BLE001 - assert race outcome
                failures.append(error)

        stops_before = served.event_count("stop_move_succeeded")
        worker = threading.Thread(target=arm_target, name="test-atomic-arm-target")
        worker.start()
        assert authority_verified.wait(0.5)

        # Four nominal 50 Hz periods pass with authority live and no target yet.
        time.sleep(0.08)
        assert served.core.phase is GatewayPhaseV1.ARMED
        assert served.sport.writer_id == WRITER_ID
        assert served.event_count("stop_move_succeeded") == stops_before
        assert served.core.audit.events("command_admitted") == ()

        release_arm.set()
        worker.join(timeout=1.0)
        assert not worker.is_alive()
        assert failures == []
        assert len(result) == 1
        target = result[0]
        assert target.source == "threaded-operator-motion"

        _wait_for_event(served, "move_applied")
        deadline = time.monotonic() + 0.5
        while (
            manager.snapshot().lifecycle is not ControlLifecycle.ACTIVE
            and time.monotonic() < deadline
        ):
            time.sleep(0.005)
        assert manager.snapshot().lifecycle is ControlLifecycle.ACTIVE
        assert served.event_count("stop_move_succeeded") == stops_before
    finally:
        release_arm.set()
        manager.close()


@requires_seqpacket
def test_operator_stop_crossing_atomic_arm_wins_and_no_target_is_installed(
    unitree_attested_fixture: ServedGateway,
) -> None:
    served = unitree_attested_fixture
    manager = build_motion_gateway_commissioned_control_manager(
        _config(served.socket_path),
        SafetyLimits(),
    )
    authority_verified = threading.Event()
    release_arm = threading.Event()
    failures: list[BaseException] = []
    try:
        manager.start(threaded=True)
        deadline = time.monotonic() + 1.0
        while (
            manager.snapshot().lifecycle is not ControlLifecycle.IDLE
            and time.monotonic() < deadline
        ):
            time.sleep(0.005)
        assert manager.snapshot().lifecycle is ControlLifecycle.IDLE

        original_acquire = manager.controller.acquire_motion_authority

        def delayed_acquire(owner_token: object) -> None:
            original_acquire(owner_token)
            authority_verified.set()
            if not release_arm.wait(0.5):
                raise RuntimeError("test did not release the verified arm")

        manager.controller.acquire_motion_authority = delayed_acquire

        def arm_target() -> None:
            try:
                manager.arm_and_set_target(
                    VelocityCommand(vx=0.08),
                    source="must-be-superseded",
                    ttl=0.18,
                )
            except BaseException as error:  # noqa: BLE001 - assert race outcome
                failures.append(error)

        worker = threading.Thread(target=arm_target, name="test-stop-crossing-arm")
        worker.start()
        assert authority_verified.wait(0.5)
        assert served.core.phase is GatewayPhaseV1.ARMED

        manager.stop("owner_stop_during_arm")
        assert served.core.phase is GatewayPhaseV1.DISARMED
        assert served.sport.writer_id is None

        release_arm.set()
        worker.join(timeout=1.0)
        assert not worker.is_alive()
        assert len(failures) == 1
        assert isinstance(failures[0], ControlNotReadyError)
        assert "superseded" in str(failures[0])
        assert manager.snapshot().target_source is None
        assert served.core.audit.events("command_admitted") == ()
        assert served.event_count("move_applied") == 0
    finally:
        release_arm.set()
        manager.close()


@requires_seqpacket
def test_gateway_v2_restores_physical_tilt_feedback_to_the_manager(tmp_path: Path) -> None:
    served = ServedGateway.start(
        tmp_path / "g.sock",
        body_kind=GatewayBodyKindV1.UNITREE_SDK2,
    )
    assert isinstance(served.sport, _TelemetryFakeSport)
    served.sport.vendor_rpy_rad = (0.8, 0.0, 0.0)
    manager = build_motion_gateway_commissioned_control_manager(
        _config(served.socket_path),
        SafetyLimits(),
    )
    try:
        manager.start(threaded=False)
        manager.tick()
        snapshot = manager.snapshot()
        assert snapshot.lifecycle is ControlLifecycle.FAULTED
        assert snapshot.fault == "robot_tilt_limit"
        assert served.core.audit.events("gateway_armed") == ()
        assert served.sport.writer_id is None
    finally:
        manager.close()
        served.close()


@requires_seqpacket
@pytest.mark.parametrize(
    ("integrity_ok", "integrity_reason", "soc_ok", "soc_reason", "expected"),
    (
        (
            False,
            "sport_mode_not_commissioned_13",
            True,
            "soc_above_commissioned_minimum",
            FaultReason.VENDOR_FAULT,
        ),
        (
            True,
            "ok",
            False,
            "soc_at_or_below_commissioned_minimum",
            FaultReason.POWER,
        ),
    ),
)
def test_v2_wire_verdicts_map_to_vendor_and_power_faults(
    unitree_attested_fixture: ServedGateway,
    integrity_ok: bool,
    integrity_reason: str,
    soc_ok: bool,
    soc_reason: str,
    expected: FaultReason,
) -> None:
    served = unitree_attested_fixture
    assert isinstance(served.sport, _TelemetryFakeSport)
    controller, source = build_commissioned_gateway_pair(
        served.socket_path,
        writer_id=WRITER_ID,
        session_epoch=SESSION_EPOCH,
        expected_hashes=COMMISSIONED_HASHES,
    )
    try:
        source.start()
        served.sport.feedback_integrity_ok = integrity_ok
        served.sport.feedback_integrity_reason = integrity_reason
        served.sport.commissioned_soc_ok = soc_ok
        served.sport.commissioned_soc_reason = soc_reason

        observed = _wait_for_source_state(
            source,
            lambda state: state.fault_reason is expected,
        )
        assert observed.fault_reason is expected
        truth = dict(observed.vendor_extra)
        assert truth["unitree_feedback_integrity_reason"] == integrity_reason
        assert truth["unitree_commissioned_soc_reason"] == soc_reason
    finally:
        controller.close()
        source.close()


@requires_seqpacket
def test_commissioned_nonzero_error_code_stays_raw_without_generic_fault(
    unitree_attested_fixture: ServedGateway,
) -> None:
    served = unitree_attested_fixture
    assert isinstance(served.sport, _TelemetryFakeSport)
    controller, source = build_commissioned_gateway_pair(
        served.socket_path,
        writer_id=WRITER_ID,
        session_epoch=SESSION_EPOCH,
        expected_hashes=COMMISSIONED_HASHES,
    )
    try:
        source.start()
        served.sport.error_code = 7
        served.sport.feedback_integrity_ok = True
        served.sport.feedback_integrity_reason = "ok"

        observed = _wait_for_source_state(
            source,
            lambda state: dict(state.vendor_extra).get(
                "unitree_sport_error_code_raw"
            )
            == "7",
        )
        assert observed.error_code == 0
        assert observed.fault_reason is FaultReason.NONE
        assert dict(observed.vendor_extra)["unitree_sport_error_code_raw"] == "7"
    finally:
        controller.close()
        source.close()


@requires_seqpacket
@pytest.mark.parametrize(
    ("offset_field", "stop_reason"),
    (
        ("sport_received_at_offset_s", "state_from_future"),
        ("low_received_at_offset_s", "low_state_from_future"),
    ),
)
def test_future_dated_v2_feedback_latches_and_never_becomes_fresh_evidence(
    unitree_attested_fixture: ServedGateway,
    offset_field: str,
    stop_reason: str,
) -> None:
    served = unitree_attested_fixture
    assert isinstance(served.sport, _TelemetryFakeSport)
    controller, source = build_commissioned_gateway_pair(
        served.socket_path,
        writer_id=WRITER_ID,
        session_epoch=SESSION_EPOCH,
        expected_hashes=COMMISSIONED_HASHES,
    )
    try:
        source.start()
        setattr(served.sport, offset_field, 5.0)

        deadline = time.monotonic() + 0.5
        while source.poll_error is None and time.monotonic() < deadline:
            time.sleep(0.002)
        with pytest.raises(
            CommissionedGatewayError,
            match="integrity or commissioned SOC",
        ):
            source.latest()
        assert served.core.phase is GatewayPhaseV1.LATCHED
        assert served.core.last_stop_reason == stop_reason
    finally:
        controller.close()
        source.close()


@requires_seqpacket
def test_future_dated_v1_state_is_replaced_by_latched_neutral_evidence(
    unitree_attested_fixture: ServedGateway,
) -> None:
    served = unitree_attested_fixture
    assert isinstance(served.sport, _TelemetryFakeSport)
    served.sport.sport_received_at_offset_s = 5.0

    observed = served.core.state()

    assert observed.phase is GatewayPhaseV1.LATCHED
    assert observed.last_stop_reason == "state_from_future"
    assert observed.state_age_ms >= 0.0
    assert (observed.vx_mps, observed.vy_mps, observed.vyaw_rad_s) == (0.0, 0.0, 0.0)


@requires_seqpacket
def test_reconnect_and_gateway_restart_remain_disarmed(tmp_path: Path) -> None:
    socket_path = tmp_path / "g.sock"
    first = ServedGateway.start(
        socket_path,
        body_kind=GatewayBodyKindV1.UNITREE_SDK2,
    )
    second: ServedGateway | None = None
    manager = build_motion_gateway_commissioned_control_manager(
        _config(socket_path),
        SafetyLimits(),
    )
    try:
        manager.start(threaded=False)
        _spin(
            manager,
            timeout_s=1.0,
            predicate=lambda: manager.snapshot().lifecycle is ControlLifecycle.IDLE,
        )
        manager.arm_and_set_target(
            VelocityCommand(vx=0.05),
            source="reconnect-probe",
            ttl=0.15,
        )
        assert manager.controller.last_arm_result is not None
        assert manager.controller.last_arm_result.armed is True
        armed_events = len(first.core.audit.events("gateway_armed"))

        same_boot = manager.controller.reconnect_disarmed(settle_timeout_s=0.3)
        assert same_boot.armed is False
        assert same_boot.gateway_restarted is False
        assert first.core.phase is GatewayPhaseV1.DISARMED
        assert len(first.core.audit.events("gateway_armed")) == armed_events
        assert manager.controller.capabilities.body_velocity is False

        manager.stop("reconnect_disarmed_sync")
        _spin(
            manager,
            timeout_s=1.0,
            predicate=lambda: manager.snapshot().lifecycle is ControlLifecycle.IDLE,
        )
        manager.arm_and_set_target(
            VelocityCommand(vx=0.05),
            source="restart-probe",
            ttl=0.15,
        )
        assert manager.controller.last_arm_result is not None
        assert manager.controller.last_arm_result.armed is True
        old_epoch = first.core.boot_epoch
        first.close()
        second = ServedGateway.start(
            socket_path,
            body_kind=GatewayBodyKindV1.UNITREE_SDK2,
        )
        with pytest.raises(CommissionedGatewayError, match="boot epoch changed"):
            manager.controller.reconnect_disarmed(settle_timeout_s=0.3)
        assert second.core.boot_epoch != old_epoch
        assert second.core.phase is GatewayPhaseV1.DISARMED
        assert second.sport.writer_id is None
        assert second.core.audit.events("gateway_armed") == ()
        assert manager.controller.capabilities.body_velocity is False
    finally:
        # A restart changes the vendor sequence epoch.  The commissioned source
        # intentionally latches that ordering change, so tear down the shared
        # socket directly instead of asking this manager to certify a cross-
        # boot physical-stop sequence.
        manager.controller.close()
        manager.state_source.close()
        first.close()
        if second is not None:
            second.close()


@requires_seqpacket
def test_mismatched_commissioned_hashes_never_produce_physical_feedback(
    unitree_attested_fixture: ServedGateway,
) -> None:
    served = unitree_attested_fixture
    wrong_hashes = dict(COMMISSIONED_HASHES.as_dict())
    wrong_hashes["firmware_sha256"] = "f" * 64
    if wrong_hashes["firmware_sha256"] == COMMISSIONED_HASHES.firmware_sha256:
        wrong_hashes["firmware_sha256"] = "e" * 64
    manager = build_motion_gateway_commissioned_control_manager(
        _config(served.socket_path, expected_hashes=wrong_hashes),
        SafetyLimits(),
    )
    with pytest.raises(GatewayProtocolError, match="hashes do not match"):
        manager.start(threaded=False)
    assert served.core.phase is GatewayPhaseV1.DISARMED
    assert served.sport.writer_id is None
    assert served.core.audit.events("gateway_armed") == ()
    manager.close()


@requires_seqpacket
def test_fake_body_kind_is_refused_before_physical_feedback(tmp_path: Path) -> None:
    served = ServedGateway.start(
        tmp_path / "g.sock",
        body_kind=GatewayBodyKindV1.FAKE,
    )
    manager = build_motion_gateway_commissioned_control_manager(
        _config(served.socket_path),
        SafetyLimits(),
    )
    try:
        with pytest.raises(CommissionedGatewayError, match="UNITREE_SDK2 V2 body attestation"):
            manager.start(threaded=False)
        assert served.core.phase is GatewayPhaseV1.DISARMED
        assert served.sport.writer_id is None
        assert served.core.audit.events("gateway_armed") == ()
    finally:
        manager.close()
        served.close()


def test_fake_gateway_core_hard_codes_fake_body_kind() -> None:
    core = FakeGatewayCoreV1(
        FakeSportServiceV1(),
        required_hashes=COMMISSIONED_HASHES,
    )
    try:
        assert "body_kind" not in core.hello().as_dict()
        assert core.state_v2().body_kind is GatewayBodyKindV1.FAKE
    finally:
        core.close()


@requires_seqpacket
def test_stale_connect_evidence_is_refused(tmp_path: Path) -> None:
    served = ServedGateway.start(
        tmp_path / "g.sock",
        body_kind=GatewayBodyKindV1.UNITREE_SDK2,
    )
    served.sport.faults = FakeSportFaultsV1(stale_state_by_s=0.4)
    manager = build_motion_gateway_commissioned_control_manager(
        _config(served.socket_path),
        SafetyLimits(),
    )
    try:
        with pytest.raises(CommissionedGatewayError, match="freshness"):
            manager.start(threaded=False)
        assert served.core.audit.events("gateway_armed") == ()
    finally:
        manager.close()
        served.close()


@requires_seqpacket
def test_frozen_vendor_sequence_cannot_confirm_the_startup_stop(tmp_path: Path) -> None:
    served = ServedGateway.start(
        tmp_path / "g.sock",
        body_kind=GatewayBodyKindV1.UNITREE_SDK2,
    )
    # Let the gateway earn its own boot-time stationary witness, then freeze
    # the source before the product manager establishes its distinct boundary.
    served.sport.faults = FakeSportFaultsV1(out_of_order_state=True)
    manager = build_motion_gateway_commissioned_control_manager(
        _config(served.socket_path),
        SafetyLimits(),
    )
    try:
        manager.start(threaded=False)
        raw_source = manager.state_source._inner
        first = raw_source.latest()
        second = raw_source.latest()
        assert first is second

        _spin(
            manager,
            timeout_s=0.6,
            predicate=lambda: manager.snapshot().lifecycle is ControlLifecycle.FAULTED,
        )
        snapshot = manager.snapshot()
        assert snapshot.stop_confirmed is False
        assert snapshot.fault == "physical_stop_not_confirmed"
    finally:
        manager.controller.close()
        manager.state_source.close()
        served.close()


def test_arm_refuses_an_accepted_lease_without_a_new_physical_sample(
    tmp_path: Path,
) -> None:
    class FrozenArmClient:
        writer_id = WRITER_ID

        def __init__(self) -> None:
            self.identity = GatewayIdentityV1(
                "frozen-boot",
                "disarmed",
            )
            self._armed = False
            self._deadline = 0.0
            self.closed = False

        @property
        def armed(self) -> bool:
            return self._armed and time.monotonic() < self._deadline

        def state_v2(self) -> MotionStateV2:
            armed = self.armed
            return _motion_state_v2(
                boot_epoch="frozen-boot",
                phase="armed" if armed else "disarmed",
                state_sequence=7,
                lease_active=armed,
                writer_id=WRITER_ID if armed else "",
                low_state_sequence=7,
            )

        def acquire(self, *, local_ttl_ms: int) -> ArmResultV1:
            self._armed = True
            self._deadline = time.monotonic() + local_ttl_ms / 1000.0
            return ArmResultV1(
                armed=True,
                reason="",
                boot_epoch="frozen-boot",
                local_ttl_ms=local_ttl_ms,
                authority_deadline_monotonic_s=self._deadline,
            )

        def close(self) -> None:
            self.closed = True
            self._armed = False

    client = FrozenArmClient()

    def connect(*_args: object, **_kwargs: object):
        return client

    controller, source = build_commissioned_gateway_pair(
        tmp_path / "g.sock",
        writer_id=WRITER_ID,
        session_epoch=SESSION_EPOCH,
        expected_hashes=COMMISSIONED_HASHES,
        local_ttl_ms=20,
        client_factory=connect,
    )
    try:
        source.start()
        controller.activate()
        with pytest.raises(CommissionedGatewayError, match="fresh verified writer sample"):
            controller.arm(local_ttl_ms=20)
        assert client.closed is True
        assert controller.armed is False
    finally:
        controller.close()
        source.close()


def test_commissioned_factory_requires_an_explicit_session_and_hash_manifest(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="session_epoch"):
        build_motion_gateway_commissioned_control_manager(
            _config(tmp_path / "g.sock", session_epoch=""),
            SafetyLimits(),
        )
    with pytest.raises(TypeError, match="expected_hashes"):
        build_motion_gateway_commissioned_control_manager(
            _config(tmp_path / "g.sock", expected_hashes=None),
            SafetyLimits(),
        )
    with pytest.raises(ValueError, match="BENCH_HASHES"):
        build_motion_gateway_commissioned_control_manager(
            _config(tmp_path / "g.sock", expected_hashes=BENCH_HASHES.as_dict()),
            SafetyLimits(),
        )


def test_each_manager_mints_a_unique_producer_epoch(tmp_path: Path) -> None:
    first = build_motion_gateway_commissioned_control_manager(
        _config(tmp_path / "g.sock"),
        SafetyLimits(),
    )
    second = build_motion_gateway_commissioned_control_manager(
        _config(tmp_path / "g.sock"),
        SafetyLimits(),
    )
    try:
        assert first.state_source.session_epoch.startswith("motion-gateway-")
        assert second.state_source.session_epoch.startswith("motion-gateway-")
        assert first.state_source.session_epoch != second.state_source.session_epoch
        assert first.state_source.session_epoch != SESSION_EPOCH
        assert second.state_source.session_epoch != SESSION_EPOCH
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize(
    ("overrides", "expected_fault"),
    (
        (
            {
                "feedback_integrity_ok": False,
                "feedback_integrity_reason": "sport_mode_not_commissioned_13",
            },
            FaultReason.VENDOR_FAULT,
        ),
        (
            {
                "commissioned_soc_ok": False,
                "commissioned_soc_reason": "soc_at_or_below_commissioned_minimum",
            },
            FaultReason.POWER,
        ),
        (
            {
                "feedback_integrity_ok": False,
                "feedback_integrity_reason": "sport_error_code_not_commissioned_7",
                "commissioned_soc_ok": False,
                "commissioned_soc_reason": "soc_at_or_below_commissioned_minimum",
            },
            FaultReason.VENDOR_FAULT,
        ),
    ),
)
def test_commissioned_state_maps_integrity_and_battery_verdicts_to_faults(
    overrides: dict[str, object],
    expected_fault: FaultReason,
) -> None:
    class FaultSession:
        connected = True
        session_epoch = "producer-fault-epoch"
        commissioning_record_id = "record-fault"

        def state(self) -> MotionStateV2:
            return _motion_state_v2(**overrides)

        def close(self) -> None:
            self.connected = False

    source = CommissionedGatewayStateSourceV1(FaultSession())  # type: ignore[arg-type]
    try:
        source.start()
        state = source.latest()
        assert state is not None
        assert state.fault_reason is expected_fault
        truth = dict(state.vendor_extra)
        assert (
            truth["unitree_feedback_integrity_ok"]
            == str(overrides.get("feedback_integrity_ok", True)).lower()
        )
        assert truth["unitree_feedback_integrity_reason"] == overrides.get(
            "feedback_integrity_reason", "ok"
        )
        assert (
            truth["unitree_commissioned_soc_ok"]
            == str(overrides.get("commissioned_soc_ok", True)).lower()
        )
        assert truth["unitree_commissioned_soc_reason"] == overrides.get(
            "commissioned_soc_reason", "soc_above_commissioned_minimum"
        )
    finally:
        source.close()


def test_source_seed_timestamp_uses_the_pre_query_lower_bound() -> None:
    class SlowSession:
        connected = True
        session_epoch = "producer-epoch"
        commissioning_record_id = "record-7"

        def state(self) -> MotionStateV2:
            time.sleep(0.03)
            return _motion_state_v2(
                boot_epoch="boot-7",
                last_stop_sequence=1,
                last_stop_reason="gateway_boot",
            )

        def close(self) -> None:
            self.connected = False

    source = CommissionedGatewayStateSourceV1(SlowSession())  # type: ignore[arg-type]
    source.start()
    state = source.latest()
    assert state is not None
    assert time.monotonic() - state.received_at >= 0.02
    source.close()


def test_latest_is_nonblocking_while_ipc_is_delayed_and_cache_ages_stale() -> None:
    """A stuck state exchange never occupies the manager-facing cache read."""

    class DelayedSession:
        connected = True
        session_epoch = "delayed-producer-epoch"
        commissioning_record_id = "delayed-record"

        def __init__(self) -> None:
            self.calls = 0
            self.poll_entered = threading.Event()
            self.release = threading.Event()

        def state(self) -> MotionStateV2:
            self.calls += 1
            if self.calls == 1:
                return _motion_state_v2(
                    boot_epoch="delayed-boot",
                    state_sequence=41,
                    low_state_sequence=41,
                )
            self.poll_entered.set()
            self.release.wait(0.5)
            return _motion_state_v2(
                boot_epoch="delayed-boot",
                state_sequence=42,
                low_state_sequence=42,
            )

        def close(self) -> None:
            self.connected = False
            self.release.set()

    session = DelayedSession()
    source = CommissionedGatewayStateSourceV1(  # type: ignore[arg-type]
        session,
        poll_interval_s=0.001,
        shutdown_timeout_s=0.05,
    )
    source.start()
    first = source.latest()
    assert first is not None and first.sequence == 41
    assert session.poll_entered.wait(0.2)

    durations: list[float] = []
    for _ in range(1_000):
        started_at = time.perf_counter()
        assert source.latest() is first
        durations.append(time.perf_counter() - started_at)
    ordered = sorted(durations)
    p99_s = ordered[989]
    assert p99_s < 0.01
    assert max(ordered) < 0.05

    # The delayed exchange cannot mint a new receipt timestamp. The exact
    # cached object remains visible and ages past a representative 50 ms
    # health window, which lets the existing manager watchdog fail closed.
    while time.monotonic() - first.received_at < 0.06:
        time.sleep(0.002)
    stale = source.latest()
    assert stale is first
    assert time.monotonic() - stale.received_at >= 0.05

    closed_at = time.monotonic()
    source.close()
    assert time.monotonic() - closed_at < 0.2
    assert source.poller_alive is False
    assert source.latest() is None


def test_low_state_only_advancement_surfaces_without_refreshing_sport() -> None:
    """Battery/thermal updates use a merged sequence, never fake Sport age."""

    class SplitRateSession:
        connected = True
        session_epoch = "split-rate-producer-epoch"
        commissioning_record_id = "split-rate-record"

        def __init__(self) -> None:
            self.calls = 0
            self.low_poll_entered = threading.Event()
            self.release_low = threading.Event()

        def state(self) -> MotionStateV2:
            self.calls += 1
            if self.calls == 1:
                return _motion_state_v2(
                    boot_epoch="split-rate-boot",
                    state_sequence=50,
                    low_state_sequence=500,
                    battery_soc_percent=87,
                )
            self.low_poll_entered.set()
            self.release_low.wait(0.3)
            return _motion_state_v2(
                boot_epoch="split-rate-boot",
                # Sport is deliberately quiet while LowState advances.
                state_sequence=50,
                state_age_ms=80.0,
                low_state_sequence=501,
                battery_soc_percent=4,
                max_motor_temperature_raw=91,
                commissioned_soc_ok=False,
                commissioned_soc_reason="soc_at_or_below_commissioned_minimum",
            )

        def close(self) -> None:
            self.connected = False
            self.release_low.set()

    session = SplitRateSession()
    raw = CommissionedGatewayStateSourceV1(  # type: ignore[arg-type]
        session,
        poll_interval_s=0.001,
        shutdown_timeout_s=0.05,
    )
    source = CommissionedStateSource(
        raw,
        origin=EvidenceOrigin.PHYSICAL,
        session_epoch=session.session_epoch,
    )
    try:
        source.start()
        first = source.latest()
        assert first is not None
        first_truth = dict(first.vendor_extra)
        assert first.sequence == 50
        assert first_truth["gateway_state_sequence"] == "50"
        assert first_truth["gateway_cache_sequence"] == "50"
        assert first_truth["unitree_low_state_sequence"] == "500"
        sport_received_at = first.received_at
        assert session.low_poll_entered.wait(0.2)
        time.sleep(0.03)
        session.release_low.set()

        deadline = time.monotonic() + 0.2
        updated = first
        while time.monotonic() < deadline:
            candidate = source.latest()
            if (
                candidate is not None
                and dict(candidate.vendor_extra).get("unitree_low_state_sequence")
                == "501"
            ):
                updated = candidate
                break
            time.sleep(0.001)
        updated_truth = dict(updated.vendor_extra)
        assert updated.sequence == 51
        assert updated_truth["gateway_cache_sequence"] == "51"
        assert updated_truth["gateway_state_sequence"] == "50"
        assert updated_truth["unitree_low_state_sequence"] == "501"
        assert updated_truth["unitree_battery_soc_percent"] == "4"
        assert updated_truth["unitree_max_motor_temperature_raw"] == "91"
        assert updated.received_at == sport_received_at
        assert time.monotonic() - updated.received_at >= 0.03
        assert updated.fault_reason is FaultReason.POWER
        assert updated.origin is EvidenceOrigin.PHYSICAL
        assert source.latched_reason is None
    finally:
        source.close()


def test_dropped_state_ipc_latches_error_without_fabricating_a_sample() -> None:
    class DroppedSession:
        connected = True
        session_epoch = "drop-producer-epoch"
        commissioning_record_id = "drop-record"

        def __init__(self) -> None:
            self.calls = 0
            self.dropped = threading.Event()

        def state(self) -> MotionStateV2:
            self.calls += 1
            if self.calls == 1:
                return _motion_state_v2(
                    boot_epoch="drop-boot",
                    state_sequence=7,
                    low_state_sequence=7,
                )
            self.connected = False
            self.dropped.set()
            raise OSError("injected AF_UNIX peer loss")

        def close(self) -> None:
            self.connected = False

    session = DroppedSession()
    source = CommissionedGatewayStateSourceV1(  # type: ignore[arg-type]
        session,
        poll_interval_s=0.001,
        shutdown_timeout_s=0.05,
    )
    source.start()
    seeded = source.latest()
    assert seeded is not None and seeded.sequence == 7
    assert session.dropped.wait(0.2)
    deadline = time.monotonic() + 0.2
    while (
        (source.poll_error is None or source.poller_alive)
        and time.monotonic() < deadline
    ):
        time.sleep(0.001)

    with pytest.raises(CommissionedGatewayError, match="injected AF_UNIX peer loss"):
        source.latest()
    assert source._last_motion_state is seeded
    assert source._last_motion_state.sequence == 7
    assert source.poller_alive is False
    source.close()


def test_background_sequence_regression_is_terminal_and_poller_does_not_restart() -> None:
    class RegressingSession:
        connected = True
        session_epoch = "regressed-producer-epoch"
        commissioning_record_id = "regressed-record"

        def __init__(self) -> None:
            self.calls = 0
            self.regressed = threading.Event()

        def state(self) -> MotionStateV2:
            self.calls += 1
            if self.calls == 1:
                return _motion_state_v2(
                    boot_epoch="regressed-boot",
                    state_sequence=20,
                    low_state_sequence=20,
                )
            self.regressed.set()
            return _motion_state_v2(
                boot_epoch="regressed-boot",
                state_sequence=19,
                low_state_sequence=19,
            )

        def close(self) -> None:
            self.connected = False

    session = RegressingSession()
    source = CommissionedGatewayStateSourceV1(  # type: ignore[arg-type]
        session,
        poll_interval_s=0.001,
        shutdown_timeout_s=0.05,
    )
    source.start()
    poller = source._poll_thread
    source.start()
    assert source._poll_thread is poller
    assert session.regressed.wait(0.2)
    deadline = time.monotonic() + 0.2
    while (
        (source.poll_error is None or source.poller_alive)
        and time.monotonic() < deadline
    ):
        time.sleep(0.001)

    with pytest.raises(CommissionedGatewayError, match="state sequence regressed"):
        source.latest()
    assert source._last_motion_state is not None
    assert source._last_motion_state.sequence == 20
    assert source.poller_alive is False
    with pytest.raises(CommissionedGatewayError, match="state sequence regressed"):
        source.start()
    source.close()


def test_background_poll_cannot_overlap_active_motion_or_delay_stop(tmp_path: Path) -> None:
    """The session atomically excludes observational I/O after acquire.

    A poll that began while disarmed may delay *arming*, when no authority
    exists. Once acquire succeeds, an injected 300 ms poll poison must never be
    entered, and the active stop must complete far below that poison delay.
    """

    class AuthorityRaceClient:
        writer_id = WRITER_ID

        def __init__(self) -> None:
            self.identity = GatewayIdentityV1("authority-race-boot", "disarmed")
            self._armed = False
            self._deadline = 0.0
            self._moving = False
            self._sequence = 0
            self._stop_sequence = 0
            self._last_stop_reason = ""
            self.acquire_calls = 0
            self.block_disarmed_poll = True
            self.disarmed_poll_entered = threading.Event()
            self.release_disarmed_poll = threading.Event()
            self.armed_poll_entered = threading.Event()
            self.release_armed_poll = threading.Event()
            self.closed = False

        @property
        def armed(self) -> bool:
            return self._armed and time.monotonic() < self._deadline

        def state_v2(self) -> MotionStateV2:
            if threading.current_thread().name == "parcel-motion-gateway-state-poll":
                if self.armed:
                    self.armed_poll_entered.set()
                    self.release_armed_poll.wait(0.3)
                elif self.block_disarmed_poll:
                    self.block_disarmed_poll = False
                    self.disarmed_poll_entered.set()
                    self.release_disarmed_poll.wait(0.3)
            self._sequence += 1
            armed = self.armed
            return _motion_state_v2(
                boot_epoch="authority-race-boot",
                phase="armed" if armed else "disarmed",
                state_sequence=self._sequence,
                lease_active=armed,
                writer_id=WRITER_ID if armed else "",
                vx_mps=0.05 if self._moving else 0.0,
                stationary=not self._moving,
                last_stop_sequence=self._stop_sequence,
                last_stop_reason=self._last_stop_reason,
                low_state_sequence=self._sequence,
            )

        def acquire(self, *, local_ttl_ms: int) -> ArmResultV1:
            self.acquire_calls += 1
            self._armed = True
            self._deadline = time.monotonic() + local_ttl_ms / 1000.0
            return ArmResultV1(
                armed=True,
                reason="",
                boot_epoch="authority-race-boot",
                local_ttl_ms=local_ttl_ms,
                authority_deadline_monotonic_s=self._deadline,
            )

        def command(
            self,
            *,
            vx_mps: float,
            vy_mps: float,
            vyaw_rad_s: float,
            local_ttl_ms: int,
            task_id: str,
            trace_id: str,
        ) -> CommandResultV1:
            del vx_mps, vy_mps, vyaw_rad_s, task_id, trace_id
            assert self.armed
            self._moving = True
            self._deadline = time.monotonic() + local_ttl_ms / 1000.0
            return CommandResultV1(
                admitted=True,
                clamped=False,
                reason="",
                boot_epoch="authority-race-boot",
                authority_deadline_monotonic_s=self._deadline,
            )

        def stop(self, *, reason: str, emergency: bool) -> StopResultV1:
            del emergency
            self._armed = False
            self._moving = False
            self._sequence += 1
            self._stop_sequence += 1
            self._last_stop_reason = f"client_stop:{reason}"
            return StopResultV1(
                boot_epoch="authority-race-boot",
                stop_sequence=self._stop_sequence,
                reason=self._last_stop_reason,
                stop_rpc_completed=True,
                stationary_confirmed=True,
                state_sequence=self._sequence,
            )

        def close(self) -> None:
            self.closed = True
            self._armed = False
            self._moving = False
            self.release_disarmed_poll.set()
            self.release_armed_poll.set()

    client = AuthorityRaceClient()

    def connect(*_args: object, **_kwargs: object) -> AuthorityRaceClient:
        return client

    controller, source = build_commissioned_gateway_pair(
        tmp_path / "authority-race.sock",
        writer_id=WRITER_ID,
        session_epoch="authority-race-producer",
        expected_hashes=COMMISSIONED_HASHES,
        local_ttl_ms=350,
        state_timeout_s=0.1,
        timeout_s=0.35,
        client_factory=connect,
    )
    arm_errors: list[BaseException] = []
    try:
        source.start()
        controller.activate()
        assert client.disarmed_poll_entered.wait(0.2)

        def arm() -> None:
            try:
                controller.arm(local_ttl_ms=350)
            except BaseException as error:  # noqa: BLE001 - assert race outcome
                arm_errors.append(error)

        arm_thread = threading.Thread(target=arm, name="test-arm-behind-disarmed-poll")
        arm_thread.start()
        time.sleep(0.03)
        assert client.acquire_calls == 0
        client.release_disarmed_poll.set()
        arm_thread.join(timeout=0.5)
        assert not arm_thread.is_alive()
        assert arm_errors == []
        assert controller.armed is True

        armed_state = source.latest()
        assert armed_state is not None
        assert dict(armed_state.vendor_extra)["gateway_phase"] == "armed"
        now = time.monotonic()
        controller.update(
            TimedVelocitySetpoint(
                command=VelocityCommand(vx=0.05),
                source="authority-race",
                sequence=1,
                issued_at=now,
                valid_until=now + 0.2,
            ),
            replace(armed_state, origin=EvidenceOrigin.PHYSICAL),
            now=now,
        )
        time.sleep(0.04)
        assert client.armed_poll_entered.is_set() is False

        stop_started_at = time.monotonic()
        controller.stop("race-stop")
        stop_elapsed_s = time.monotonic() - stop_started_at
        assert stop_elapsed_s < 0.1
        assert client.armed_poll_entered.is_set() is False
        assert controller.last_stop_result is not None
        assert controller.last_stop_result.confirmed_stationary is True
    finally:
        client.release_disarmed_poll.set()
        client.release_armed_poll.set()
        source.close()
        controller.close()
