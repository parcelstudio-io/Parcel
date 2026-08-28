"""Card W0-B gates: the commissioning-only path.

Card: `scrum/20260812/task_2/W0_PRODUCT_CARDS.md` §"Card W0-B", grounding
`scrum/20260812/task_1/PRODUCTION_COMPANION_PLAN.md` §"CommissioningRecordV1".

Gate-to-test map (each gate item has a refusal *and* a companion that shows the
refusal discriminates - a control just inside the bound, or a seeded defect that
reddens the same assertion):

1. commissioning works while the normal flags are false
   -> test_commissioning_builds_while_every_normal_flag_is_false
      (+ test_normal_factory_still_refuses_* as the untouched-gates control)
2. cannot issue multi-axis / autonomous / over-limit / over-duration commands
   -> test_refuses_multi_axis*, test_refuses_a_foreign_writer*,
      test_refuses_over_limit*, test_refuses_over_duration*
3. interruption / state loss / process exit / failed stop -> latched failure
   -> test_latches_on_interruption, test_latches_on_state_loss,
      test_latches_when_a_previous_process_exited_mid_session,
      test_latches_when_the_stop_is_never_confirmed
4. only a reviewed evidence record can enable normal configuration
   -> test_record_defaults_authorize_nothing,
      test_a_complete_record_still_authorizes_nothing_until_reviewed,
      test_reviewed_record_enables_exactly_the_four_normal_flags
5. no path from this manager into RobotRuntime
   -> test_no_module_outside_the_commissioning_seam_imports_it,
      test_importing_commissioning_does_not_import_the_runtime,
      test_session_exposes_no_control_manager_surface,
      test_commissioning_builders_are_not_in_the_controller_registry

Nothing in this file touches hardware: every robot is an in-process fake reached
through the vendor seams that already existed (`client_factory`,
`subscriber_factory`, `message_type`, `initializer`).
"""

from __future__ import annotations

import ast
import dataclasses
import errno
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from parcel_robot.commissioning.limits import (
    ARMING_TTL_S,
    FOOTPRINT_RADIUS_M,
    MAX_LINEAR_MPS,
    MAX_TTL_S,
    MAX_YAW_RAD_S,
    MIN_LINEAR_MPS,
    MIN_YAW_RAD_S,
    REQUIRED_ACKNOWLEDGEMENTS,
    SETTLED_LINEAR_MPS,
    SETTLED_YAW_RAD_S,
    CommissioningArming,
    CommissioningAxis,
    CommissioningLatchedError,
    CommissioningLimits,
    CommissioningRefusedError,
    LatchReason,
    RefusalReason,
    assert_commissioning_command,
    assert_commissioning_duration,
    assert_commissioning_ttl,
    single_axis_command,
)
from parcel_robot.commissioning.record import (
    FRAME_DISCRIMINATION_YAW_RAD,
    AxisSignEvidence,
    CommissioningRecordV1,
    CommissioningReviewError,
    ObservationEvidence,
    ObservedDirection,
    RecordOutcome,
    StopEvidence,
    commissioned_control_config,
)
from parcel_robot.commissioning.session import (
    CommissioningJournal,
    CommissioningObserver,
    CommissioningSession,
    JournalState,
)
from parcel_robot.control.factory import (
    _CONTROLLER_FACTORIES,
    UnitreeCommissioningSeams,
    build_unitree_sport_commissioning_session,
    build_unitree_sport_control_manager,
    build_unitree_sport_observer,
    controller_factory_names,
)
from parcel_robot.control.manager import ControlManager
from parcel_robot.control.models import (
    ControllerCapabilities,
    ControlLimits,
    ControlTiming,
    RobotMotionState,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE
from parcel_robot.safety import SafetyLimits

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "src" / "parcel_robot"

#: A yaw large enough to tell odom from base_link (see FRAME_DISCRIMINATION_YAW_RAD).
RIG_YAW_RAD = 0.6
STEP_SPEED_MPS = 0.03
STEP_YAW_RAD_S = 0.10
STEP_DURATION_S = 0.15


# --------------------------------------------------------------------- fakes


class _FakeRig:
    """A supported robot on a support rig, in process.

    Velocity tracks the command with a first-order lag; odom position
    integrates the body velocity through a *fixed* yaw (feet off the ground, so
    a yaw command spins the legs, not the body - which also keeps the frame
    check deterministic).
    """

    def __init__(
        self,
        *,
        yaw: float = RIG_YAW_RAD,
        lag_s: float = 0.02,
        stop_works: bool = True,
        clock=time.monotonic,
    ) -> None:
        self.lock = threading.Lock()
        self.target = VelocityCommand()
        self.measured = VelocityCommand()
        self.position = [0.0, 0.0, 0.0]
        self.yaw = float(yaw)
        self.lag_s = float(lag_s)
        self.stop_works = bool(stop_works)
        self.mode = 3
        self.error_code = 0
        self.emergency = False
        self.moves = 0
        self.stops = 0
        self._clock = clock
        self._last = clock()

    def advance(self, now: float) -> None:
        with self.lock:
            dt = max(0.0, now - self._last)
            self._last = now
            alpha = 1.0 - math.exp(-dt / self.lag_s) if dt > 0.0 else 0.0
            current = self.measured
            target = self.target
            self.measured = VelocityCommand(
                vx=current.vx + (target.vx - current.vx) * alpha,
                vy=current.vy + (target.vy - current.vy) * alpha,
                vyaw=current.vyaw + (target.vyaw - current.vyaw) * alpha,
            )
            cosine, sine = math.cos(self.yaw), math.sin(self.yaw)
            self.position[0] += (cosine * self.measured.vx - sine * self.measured.vy) * dt
            self.position[1] += (sine * self.measured.vx + cosine * self.measured.vy) * dt


class _FakeController:
    name = "fake_rig"
    capabilities = ControllerCapabilities(
        body_velocity=True,
        lateral_velocity=True,
        high_level_balance=True,
        low_level_joint_control=False,
        requires_stop_confirmation=True,
    )

    def __init__(self, rig: _FakeRig) -> None:
        self._rig = rig

    def activate(self) -> None:
        return None

    def update(self, target, state, *, now) -> None:
        del state, now
        with self._rig.lock:
            if self._rig.emergency:
                raise RuntimeError("fake rig rejects motion while emergency-stopped")
            self._rig.target = target.command
            self._rig.moves += 1

    def stop(self, reason: str) -> None:
        del reason
        with self._rig.lock:
            self._rig.stops += 1
            if self._rig.stop_works:
                self._rig.target = VelocityCommand()

    def emergency_stop(self) -> None:
        with self._rig.lock:
            self._rig.emergency = True
            if self._rig.stop_works:
                self._rig.target = VelocityCommand()

    def clear_emergency_stop(self) -> None:
        with self._rig.lock:
            self._rig.emergency = False

    def close(self) -> None:
        self.stop("close")


class _FakeStateSource:
    name = "fake_rig_state"

    def __init__(self, rig: _FakeRig, *, clock=time.monotonic) -> None:
        self._rig = rig
        self._clock = clock
        self._sequence = 0
        self._started = False
        self.blank = False

    def start(self) -> None:
        self._started = True

    def latest(self) -> RobotMotionState | None:
        if not self._started or self.blank:
            return None
        now = self._clock()
        self._rig.advance(now)
        # The manager thread and the session both poll this; the sequence must
        # increase exactly once per sample or stop confirmation goes flaky.
        with self._rig.lock:
            self._sequence += 1
            return RobotMotionState(
                received_at=now,
                sequence=self._sequence,
                position=(self._rig.position[0], self._rig.position[1], 0.0),
                yaw=self._rig.yaw,
                velocity=self._rig.measured,
                mode=self._rig.mode,
                error_code=self._rig.error_code,
                source=self.name,
            )

    def close(self) -> None:
        self._started = False


def _band(**overrides: float) -> CommissioningLimits:
    return CommissioningLimits(**overrides)


def _private_manager(session: CommissioningSession) -> ControlManager:
    """Reach the session's manager the only way there is: through __dict__.

    The reach itself is the assertion - a session offers no public route to the
    ``ControlManager`` it drives, so a test that needs one has to go around it.
    """

    return vars(session)["_manager"]


def _wait_for(predicate, *, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _arming(**overrides) -> CommissioningArming:
    payload = {
        "operator": "operator-under-test",
        "robot_serial": "RIG-0001",
        "acknowledgements": REQUIRED_ACKNOWLEDGEMENTS,
        "observed_modes": (3,),
    }
    payload.update(overrides)
    return CommissioningArming.arm(**payload)


def _rig_session(
    tmp_path: Path,
    *,
    rig: _FakeRig | None = None,
    arming: CommissioningArming | None = None,
    limits: CommissioningLimits | None = None,
    stop_timeout_s: float = 0.4,
    journal_name: str = "journal.jsonl",
    sleeper=time.sleep,
) -> SimpleNamespace:
    """A commissioning session over the fake rig, clamped exactly like the factory."""

    band = limits or _band()
    rig = rig or _FakeRig()
    controller = _FakeController(rig)
    source = _FakeStateSource(rig)
    timing = ControlTiming(
        control_hz=100.0,
        command_timeout_s=0.2,
        state_timeout_s=0.25,
        startup_timeout_s=2.0,
        stop_timeout_s=stop_timeout_s,
        stop_retry_s=0.1,
        io_quiesce_timeout_s=1.0,
        stop_settled_samples=2,
        settled_linear_speed_mps=band.settled_linear_mps,
        settled_yaw_speed_rad_s=band.settled_yaw_rad_s,
    )
    manager = ControlManager(
        controller,
        source,
        limits=ControlLimits(
            max_vx=band.max_linear_mps,
            max_vy=band.max_linear_mps,
            max_vyaw=band.max_yaw_rad_s,
        ),
        timing=timing,
    )
    journal = CommissioningJournal.begin(tmp_path / journal_name, session_id="test-session")
    session = CommissioningSession(
        manager,
        arming=arming or _arming(),
        journal=journal,
        declared_velocity_frame="odom",
        limits=band,
        sleeper=sleeper,
    )
    return SimpleNamespace(
        session=session,
        rig=rig,
        manager=manager,
        source=source,
        journal=journal,
        band=band,
    )


# ------------------------------------------- gate 1: the normal gates untouched

_UNCOMMISSIONED = {
    "unitree_sport": {
        "interface": "test0",
        "enable_lease": False,
        "axes_commissioned": False,
        "state_frame_commissioned": False,
        "allowed_modes": [],
    }
}


def _commissioned_config() -> dict:
    return {
        "unitree_sport": {
            "interface": "test0",
            "enable_lease": True,
            "axes_commissioned": True,
            "state_frame_commissioned": True,
            "allowed_modes": [3],
        }
    }


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("enable_lease", False, "enable_lease must be true"),
        ("axes_commissioned", False, "axes_commissioned must be true"),
        ("state_frame_commissioned", False, "state_frame_commissioned must be true"),
        ("allowed_modes", [], "allowed_modes must be explicitly commissioned"),
    ],
)
def test_normal_factory_still_refuses_each_uncommissioned_flag(key, value, message) -> None:
    """The four normal gates behave exactly as before this card."""

    config = _commissioned_config()
    config["unitree_sport"][key] = value
    with pytest.raises(ValueError, match=message):
        build_unitree_sport_control_manager(config, SafetyLimits())


def test_normal_factory_still_builds_when_every_flag_is_commissioned() -> None:
    """Control for the four refusals above: the gates discriminate."""

    manager = build_unitree_sport_control_manager(_commissioned_config(), SafetyLimits())
    assert manager.controller.name == "unitree_sport"
    assert manager.controller.allowed_modes == frozenset({3})


def test_commissioning_builds_while_every_normal_flag_is_false(tmp_path) -> None:
    """GATE 1. The defect: commissioning could not bootstrap. Now it can."""

    with pytest.raises(ValueError, match="enable_lease must be true"):
        build_unitree_sport_control_manager(_UNCOMMISSIONED, SafetyLimits())

    session = build_unitree_sport_commissioning_session(
        _UNCOMMISSIONED,
        SafetyLimits(),
        arming=_arming(),
        journal_path=tmp_path / "bootstrap.jsonl",
        seams=UnitreeCommissioningSeams(channel_initializer=lambda *_: None),
    )
    assert isinstance(session, CommissioningSession)
    assert not isinstance(session, ControlManager)
    assert session.limits.max_linear_mps == MAX_LINEAR_MPS


def test_commissioning_factory_clamps_limits_and_timing_below_production(tmp_path) -> None:
    """Configuration can only make the commissioning envelope tighter."""

    config = {
        "command_timeout_s": 0.35,
        "settled_linear_speed_mps": 0.08,
        "settled_yaw_speed_rad_s": 0.12,
        "max_vx": 1.0,
        "max_vy": 0.5,
        "max_vyaw": 1.5,
        **_UNCOMMISSIONED,
    }
    session = build_unitree_sport_commissioning_session(
        config,
        SafetyLimits(),
        arming=_arming(),
        journal_path=tmp_path / "clamped.jsonl",
        seams=UnitreeCommissioningSeams(channel_initializer=lambda *_: None),
    )
    manager = _private_manager(session)
    assert manager.limits.max_vx == MAX_LINEAR_MPS
    assert manager.limits.max_vy == MAX_LINEAR_MPS
    assert manager.limits.max_vyaw == pytest.approx(MAX_YAW_RAD_S)
    assert manager.timing.command_timeout_s <= MAX_TTL_S
    # The live production thresholds are ABOVE the whole commissioning band.
    assert manager.timing.settled_linear_speed_mps == SETTLED_LINEAR_MPS < 0.08
    assert manager.timing.settled_yaw_speed_rad_s == SETTLED_YAW_RAD_S < 0.12


def test_commissioning_factory_forces_identity_axis_signs(tmp_path) -> None:
    """A configured, unverified sign must not colour the numbers being measured."""

    config = {
        "unitree_sport": {
            **_UNCOMMISSIONED["unitree_sport"],
            "lateral_sign": -1,
            "yaw_sign": -1,
        }
    }
    session = build_unitree_sport_commissioning_session(
        config,
        SafetyLimits(),
        arming=_arming(),
        journal_path=tmp_path / "signs.jsonl",
        seams=UnitreeCommissioningSeams(channel_initializer=lambda *_: None),
    )
    manager = _private_manager(session)
    assert manager.controller.lateral_sign == 1
    assert manager.controller.yaw_sign == 1
    assert manager.state_source.lateral_sign == 1
    assert manager.state_source.yaw_sign == 1


def test_commissioning_factory_takes_modes_only_from_the_arming_token(tmp_path) -> None:
    config = {
        "unitree_sport": {
            **_UNCOMMISSIONED["unitree_sport"],
            "allowed_modes": [7, 8, 9],
        }
    }
    session = build_unitree_sport_commissioning_session(
        config,
        SafetyLimits(),
        arming=_arming(observed_modes=(1, 3)),
        journal_path=tmp_path / "modes.jsonl",
        seams=UnitreeCommissioningSeams(channel_initializer=lambda *_: None),
    )
    assert _private_manager(session).controller.allowed_modes == frozenset({1, 3})


def test_commissioning_factory_refuses_to_build_without_observed_modes(tmp_path) -> None:
    with pytest.raises(CommissioningRefusedError) as excinfo:
        build_unitree_sport_commissioning_session(
            _UNCOMMISSIONED,
            SafetyLimits(),
            arming=_arming(observed_modes=()),
            journal_path=tmp_path / "nomodes.jsonl",
            seams=UnitreeCommissioningSeams(channel_initializer=lambda *_: None),
        )
    assert excinfo.value.reason is RefusalReason.MODES_NOT_OBSERVED


def test_commissioning_factory_refuses_without_an_arming_token(tmp_path) -> None:
    with pytest.raises(CommissioningRefusedError) as excinfo:
        build_unitree_sport_commissioning_session(
            _UNCOMMISSIONED,
            SafetyLimits(),
            arming=SimpleNamespace(observed_modes=(3,)),
            journal_path=tmp_path / "noarm.jsonl",
        )
    assert excinfo.value.reason is RefusalReason.NOT_ARMED


# ------------------------------------------------------- gate 2: the refusals


def test_refuses_multi_axis_commands() -> None:
    with pytest.raises(CommissioningRefusedError) as excinfo:
        assert_commissioning_command(VelocityCommand(vx=0.03, vy=0.03), _band())
    assert excinfo.value.reason is RefusalReason.MULTI_AXIS


def test_single_axis_control_passes_the_same_guard() -> None:
    """Companion: the multi-axis refusal is not refusing everything."""

    assert assert_commissioning_command(VelocityCommand(vx=0.03), _band()) is CommissioningAxis.VX


def test_seeded_multi_axis_command_is_refused_at_the_dispatch_boundary(
    tmp_path, monkeypatch
) -> None:
    """Seeded defect: make the builder emit two axes; the guard still refuses.

    Proves the refusal lives in `assert_commissioning_command`, not merely in
    the shape of `CommissioningAxis`.
    """

    rig = _rig_session(tmp_path)
    monkeypatch.setattr(
        "parcel_robot.commissioning.session.single_axis_command",
        lambda axis, speed: VelocityCommand(vx=float(speed), vy=float(speed)),
    )
    try:
        rig.session.start()
        with pytest.raises(CommissioningRefusedError) as excinfo:
            rig.session.run_axis_step(CommissioningAxis.VX, STEP_SPEED_MPS, STEP_DURATION_S)
        assert excinfo.value.reason is RefusalReason.MULTI_AXIS
        assert rig.rig.moves == 0
    finally:
        rig.session.close()


@pytest.mark.parametrize(
    ("axis", "speed", "reason"),
    [
        (CommissioningAxis.VX, MAX_LINEAR_MPS + 0.001, RefusalReason.OVER_LIMIT),
        (CommissioningAxis.VY, -(MAX_LINEAR_MPS + 0.001), RefusalReason.OVER_LIMIT),
        (CommissioningAxis.VYAW, MAX_YAW_RAD_S * 1.01, RefusalReason.OVER_LIMIT),
        (CommissioningAxis.VX, MIN_LINEAR_MPS - 0.001, RefusalReason.UNDER_LIMIT),
        (CommissioningAxis.VYAW, MIN_YAW_RAD_S * 0.5, RefusalReason.UNDER_LIMIT),
    ],
)
def test_refuses_out_of_band_speeds(axis, speed, reason) -> None:
    with pytest.raises(CommissioningRefusedError) as excinfo:
        assert_commissioning_command(single_axis_command(axis, speed), _band())
    assert excinfo.value.reason is reason


@pytest.mark.parametrize(
    ("axis", "speed"),
    [
        (CommissioningAxis.VX, MAX_LINEAR_MPS),
        (CommissioningAxis.VY, MIN_LINEAR_MPS),
        (CommissioningAxis.VYAW, MAX_YAW_RAD_S),
        (CommissioningAxis.VYAW, MIN_YAW_RAD_S),
    ],
)
def test_band_edges_are_accepted(axis, speed) -> None:
    """Companion: the band refuses what is outside it and nothing more."""

    assert assert_commissioning_command(single_axis_command(axis, speed), _band()) is axis


def test_seeded_over_limit_command_is_refused_again_by_the_manager(tmp_path) -> None:
    """Seeded defect: bypass the session guard entirely. The clamped
    ``ControlLimits`` on the commissioning manager refuses the same command."""

    rig = _rig_session(tmp_path)
    try:
        rig.session.start()
        with pytest.raises(ValueError, match="exceeds the physical limit"):
            rig.manager.set_target(VelocityCommand(vx=0.6), source="commissioning")
    finally:
        rig.session.close()


def test_refuses_over_duration_steps() -> None:
    band = _band()
    with pytest.raises(CommissioningRefusedError) as excinfo:
        assert_commissioning_duration(band.max_duration_s + 0.01, band)
    assert excinfo.value.reason is RefusalReason.OVER_DURATION
    assert assert_commissioning_duration(band.max_duration_s, band) == band.max_duration_s


def test_seeded_wider_limits_cannot_be_constructed() -> None:
    """Seeded defect: a caller tries to widen the band. Every axis refuses."""

    with pytest.raises(ValueError, match="linear band"):
        CommissioningLimits(max_linear_mps=0.5)
    with pytest.raises(ValueError, match="yaw band"):
        CommissioningLimits(max_yaw_rad_s=1.0)
    with pytest.raises(ValueError, match="duration"):
        CommissioningLimits(max_duration_s=5.0)
    with pytest.raises(ValueError, match="TTL"):
        CommissioningLimits(max_ttl_s=1.0)
    with pytest.raises(ValueError, match="stationarity"):
        CommissioningLimits(settled_linear_mps=0.08)
    # Companion: the band itself constructs.
    assert CommissioningLimits().max_linear_mps == MAX_LINEAR_MPS


def test_refuses_over_ttl_leases() -> None:
    band = _band()
    with pytest.raises(CommissioningRefusedError) as excinfo:
        assert_commissioning_ttl(band.max_ttl_s + 0.01, band)
    assert excinfo.value.reason is RefusalReason.OVER_TTL
    assert assert_commissioning_ttl(band.max_ttl_s, band) == band.max_ttl_s


def test_refuses_non_finite_commands_and_durations() -> None:
    band = _band()
    for value in (float("nan"), float("inf")):
        with pytest.raises(CommissioningRefusedError) as excinfo:
            single_axis_command(CommissioningAxis.VX, value)
        assert excinfo.value.reason is RefusalReason.NON_FINITE
        with pytest.raises(CommissioningRefusedError):
            assert_commissioning_duration(value, band)


def test_refuses_a_zero_command() -> None:
    with pytest.raises(CommissioningRefusedError) as excinfo:
        assert_commissioning_command(VelocityCommand(), _band())
    assert excinfo.value.reason is RefusalReason.ZERO_COMMAND


def test_refuses_an_arming_token_missing_any_acknowledgement() -> None:
    for missing in sorted(REQUIRED_ACKNOWLEDGEMENTS):
        with pytest.raises(CommissioningRefusedError) as excinfo:
            CommissioningArming.arm(
                operator="op",
                robot_serial="RIG",
                acknowledgements=REQUIRED_ACKNOWLEDGEMENTS - {missing},
                observed_modes=(3,),
            )
        assert excinfo.value.reason is RefusalReason.MISSING_ACKNOWLEDGEMENT
        assert missing in str(excinfo.value)
    # Companion: with all three, arming succeeds.
    assert _arming().acknowledgements == REQUIRED_ACKNOWLEDGEMENTS


def test_refuses_an_expired_or_foreign_arming_token() -> None:
    arming = CommissioningArming.arm(
        operator="op",
        robot_serial="RIG",
        acknowledgements=REQUIRED_ACKNOWLEDGEMENTS,
        observed_modes=(3,),
        ttl_s=1.0,
        clock=lambda: 100.0,
    )
    arming.assert_valid(100.5)
    with pytest.raises(CommissioningRefusedError) as excinfo:
        arming.assert_valid(101.5)
    assert excinfo.value.reason is RefusalReason.ARMING_EXPIRED

    foreign = CommissioningArming(
        operator="op",
        robot_serial="RIG",
        acknowledgements=REQUIRED_ACKNOWLEDGEMENTS,
        armed_at=0.0,
        pid=os.getpid() + 1,
        observed_modes=(3,),
    )
    with pytest.raises(CommissioningRefusedError) as excinfo:
        foreign.assert_valid(0.0)
    assert excinfo.value.reason is RefusalReason.ARMING_FOREIGN_PROCESS


def test_refuses_motion_without_observed_modes(tmp_path) -> None:
    rig = _rig_session(tmp_path, arming=_arming(observed_modes=()))
    try:
        rig.session.start()
        with pytest.raises(CommissioningRefusedError) as excinfo:
            rig.session.run_axis_step(CommissioningAxis.VX, STEP_SPEED_MPS, STEP_DURATION_S)
        assert excinfo.value.reason is RefusalReason.MODES_NOT_OBSERVED
        assert rig.rig.moves == 0
    finally:
        rig.session.close()


def test_refuses_motion_before_the_session_is_started(tmp_path) -> None:
    rig = _rig_session(tmp_path)
    try:
        with pytest.raises(CommissioningRefusedError) as excinfo:
            rig.session.run_axis_step(CommissioningAxis.VX, STEP_SPEED_MPS, STEP_DURATION_S)
        assert excinfo.value.reason is RefusalReason.SESSION_NOT_STARTED
    finally:
        rig.session.close()


def test_refuses_a_foreign_writer_and_latches(tmp_path) -> None:
    """The autonomous refusal: any writer but this session latches the session."""

    rig = _rig_session(tmp_path)
    session = rig.session
    real_snapshot = rig.manager.snapshot

    def hijacked(**kwargs):
        status = real_snapshot(**kwargs)
        return SimpleNamespace(
            lifecycle=status.lifecycle,
            fault=status.fault,
            target_source="navigation",
            stop_confirmed=status.stop_confirmed,
        )

    try:
        session.start()
        rig.manager.snapshot = hijacked  # type: ignore[method-assign]
        with pytest.raises(CommissioningLatchedError) as excinfo:
            session.run_axis_step(CommissioningAxis.VX, STEP_SPEED_MPS, STEP_DURATION_S)
        assert excinfo.value.reason is LatchReason.FOREIGN_WRITER
        assert session.latched
    finally:
        rig.manager.snapshot = real_snapshot  # type: ignore[method-assign]
        session.close()


def test_a_step_with_only_this_writer_completes(tmp_path) -> None:
    """Companion to the foreign-writer latch: the honest case runs."""

    rig = _rig_session(tmp_path)
    try:
        rig.session.start()
        evidence = rig.session.run_axis_step(
            CommissioningAxis.VX,
            STEP_SPEED_MPS,
            STEP_DURATION_S,
            observed_direction=ObservedDirection.FORWARD,
        )
        assert not rig.session.latched
        assert evidence.samples > 0
        assert evidence.feedback_agrees
        assert evidence.sign == 1
    finally:
        rig.session.close()


# ---------------------------------------------------------- gate 3: the latches


def test_latches_on_interruption(tmp_path) -> None:
    # Armed only after start(), so the interrupt lands inside the step rather
    # than during arming (which has its own latch, tested separately).
    interrupt = {"armed": False, "count": 0}

    def interrupting_sleeper(seconds: float) -> None:
        if interrupt["armed"]:
            interrupt["count"] += 1
            if interrupt["count"] >= 2:
                raise KeyboardInterrupt
        time.sleep(seconds)

    rig = _rig_session(tmp_path, sleeper=interrupting_sleeper)
    try:
        rig.session.start()
        interrupt["armed"] = True
        with pytest.raises(CommissioningLatchedError) as excinfo:
            rig.session.run_axis_step(CommissioningAxis.VX, STEP_SPEED_MPS, STEP_DURATION_S)
        assert excinfo.value.reason is LatchReason.INTERRUPTED
        assert rig.session.latched
        # The latch delivers an emergency stop; the manager does it off-thread.
        assert _wait_for(lambda: rig.rig.emergency)
        with pytest.raises(CommissioningLatchedError):
            rig.session.run_axis_step(CommissioningAxis.VY, STEP_SPEED_MPS, STEP_DURATION_S)
    finally:
        rig.session.close()
    record = rig.session.record(performed_at="2026-08-12T00:00:00Z")
    assert record.outcome is RecordOutcome.FAILED
    assert "interrupted" in record.failure_reason


def test_latches_on_state_loss(tmp_path) -> None:
    rig = _rig_session(tmp_path)
    source = rig.source
    calls = {"n": 0}
    real_latest = source.latest

    def failing_latest():
        calls["n"] += 1
        if calls["n"] > 4:
            return None
        return real_latest()

    try:
        rig.session.start()
        source.latest = failing_latest  # type: ignore[method-assign]
        with pytest.raises(CommissioningLatchedError) as excinfo:
            rig.session.run_axis_step(CommissioningAxis.VX, STEP_SPEED_MPS, STEP_DURATION_S)
        assert excinfo.value.reason is LatchReason.STATE_LOST
        assert rig.session.latched
    finally:
        source.latest = real_latest  # type: ignore[method-assign]
        rig.session.close()


def test_latches_when_the_stop_is_never_confirmed(tmp_path) -> None:
    """Seeded defect: StopMove that returns success without stopping the robot."""

    rig = _rig_session(tmp_path, rig=_FakeRig(stop_works=False), stop_timeout_s=0.3)
    try:
        rig.session.start()
        with pytest.raises(CommissioningLatchedError) as excinfo:
            rig.session.run_axis_step(
                CommissioningAxis.VX,
                STEP_SPEED_MPS,
                STEP_DURATION_S,
                observed_direction=ObservedDirection.FORWARD,
            )
        assert excinfo.value.reason is LatchReason.STOP_NOT_CONFIRMED
    finally:
        rig.session.close()
    record = rig.session.record(performed_at="2026-08-12T00:00:00Z")
    assert record.outcome is RecordOutcome.FAILED
    assert record.stop is not None
    assert record.stop.confirmed is False
    assert record.stop.settle_latency_s >= 0.25
    assert not record.authorizes_configuration()


def test_a_working_stop_is_confirmed_and_measured(tmp_path) -> None:
    """Companion: the same path with a stop that works produces real numbers."""

    rig = _rig_session(tmp_path)
    try:
        rig.session.start()
        rig.session.run_axis_step(
            CommissioningAxis.VX,
            STEP_SPEED_MPS,
            STEP_DURATION_S,
            observed_direction=ObservedDirection.FORWARD,
        )
    finally:
        rig.session.close()
    record = rig.session.record(performed_at="2026-08-12T00:00:00Z")
    assert record.stop is not None
    assert record.stop.confirmed is True
    assert 0.0 <= record.stop.request_latency_s < 0.2
    assert 0.0 < record.stop.settle_latency_s < 0.4
    assert record.stop.distance_method == "odom_delta"
    assert 0.0 < record.stop.distance_m < 0.05


def test_latches_when_a_previous_process_exited_mid_session(tmp_path) -> None:
    """GATE 3, process exit. A real ``os._exit`` mid-step, then a fresh open."""

    journal = tmp_path / "killed.jsonl"
    child = (
        "import os\n"
        "from parcel_robot.commissioning.session import CommissioningJournal, JournalState\n"
        f"journal = CommissioningJournal.begin({str(journal)!r}, session_id='killed')\n"
        "journal.append(JournalState.MOVING, axis='vx', speed=0.03)\n"
        "os._exit(9)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", child],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 9, result.stderr
    assert journal.exists()

    with pytest.raises(CommissioningLatchedError) as excinfo:
        CommissioningJournal.begin(journal, session_id="recovery")
    assert excinfo.value.reason is LatchReason.PROCESS_EXIT
    states = [entry["state"] for entry in CommissioningJournal(journal, session_id="r").entries()]
    assert states[-1] == JournalState.LATCHED.value
    assert JournalState.MOVING.value in states


def test_a_cleanly_finished_journal_refuses_reuse_without_latching(tmp_path) -> None:
    """Companion: a clean exit is a refusal to reuse, not a process-exit latch."""

    rig = _rig_session(tmp_path, journal_name="clean.jsonl")
    rig.session.start()
    rig.session.close()
    with pytest.raises(CommissioningRefusedError) as excinfo:
        CommissioningJournal.begin(tmp_path / "clean.jsonl", session_id="again")
    assert excinfo.value.reason is RefusalReason.JOURNAL_ALREADY_USED
    entries = CommissioningJournal(tmp_path / "clean.jsonl", session_id="x").entries()
    assert entries[-1]["state"] == JournalState.COMPLETE.value


def test_a_latched_session_writes_a_latched_journal(tmp_path) -> None:
    rig = _rig_session(tmp_path, rig=_FakeRig(stop_works=False), stop_timeout_s=0.3)
    try:
        rig.session.start()
        with pytest.raises(CommissioningLatchedError):
            rig.session.run_axis_step(CommissioningAxis.VX, STEP_SPEED_MPS, STEP_DURATION_S)
    finally:
        rig.session.close()
    entries = CommissioningJournal(rig.journal.path, session_id="x").entries()
    assert entries[-1]["state"] == JournalState.LATCHED.value
    assert entries[-1]["latch_reason"] == LatchReason.STOP_NOT_CONFIRMED.value


def test_a_latched_session_refuses_every_later_call(tmp_path) -> None:
    rig = _rig_session(tmp_path, rig=_FakeRig(stop_works=False), stop_timeout_s=0.3)
    rig.session.start()
    with pytest.raises(CommissioningLatchedError):
        rig.session.run_axis_step(CommissioningAxis.VX, STEP_SPEED_MPS, STEP_DURATION_S)
    for call in (
        lambda: rig.session.start(),
        lambda: rig.session.run_axis_step(CommissioningAxis.VY, STEP_SPEED_MPS, STEP_DURATION_S),
    ):
        with pytest.raises(CommissioningLatchedError):
            call()
    rig.session.close()


def test_a_failed_teardown_latches_instead_of_destroying_the_record(tmp_path) -> None:
    """The record must survive the exact case it exists to document.

    ``ControlManager.close()`` raises ``ControlNotReadyError`` when its stop was
    never delivered or confirmed. If that escaped ``CommissioningSession.close``
    then ``record()`` — which closes first — would raise too, and the evidence
    of a failed stop would be destroyed precisely when it matters most. Seeded
    with a rig whose ``StopMove`` does nothing, which is what makes the
    underlying manager close raise.
    """

    rig = _rig_session(tmp_path, rig=_FakeRig(stop_works=False), stop_timeout_s=0.3)
    rig.session.start()
    with pytest.raises(CommissioningLatchedError):
        rig.session.run_axis_step(CommissioningAxis.VX, STEP_SPEED_MPS, STEP_DURATION_S)

    rig.session.close()  # must not raise
    rig.session.close()  # and must be idempotent

    record = rig.session.record(performed_at="2026-08-12T00:00:00Z")
    assert record.outcome is RecordOutcome.FAILED
    assert rig.session.latch_reason is LatchReason.STOP_NOT_CONFIRMED
    assert not record.authorizes_configuration()
    entries = CommissioningJournal(rig.journal.path, session_id="x").entries()
    assert entries[-1]["state"] == JournalState.LATCHED.value


def _out_of_quota(*_args: object, **_kwargs: object) -> None:
    """The exact failure this repo's own host produced on 2026-08-13."""

    raise OSError(errno.EDQUOT, "Disk quota exceeded")


def test_a_journal_write_failure_at_teardown_still_returns_the_record(tmp_path) -> None:
    """Seeded Errno 122. The record must survive a journal that cannot be written.

    The first teardown fix stopped `ControlManager.close()` from destroying the
    record. This is the same class one layer down: the latch/finalize *journal
    writes* in the teardown path. A full or over-quota filesystem is not
    hypothetical here — it is what took this host out mid-card — and it must
    cost the operator a digest, never the evidence.
    """

    rig = _rig_session(tmp_path)
    rig.session.start()
    rig.session.run_axis_step(
        CommissioningAxis.VX,
        STEP_SPEED_MPS,
        STEP_DURATION_S,
        observed_direction=ObservedDirection.FORWARD,
    )
    landed = CommissioningJournal(rig.journal.path, session_id="x").entries()

    rig.journal._write = _out_of_quota  # type: ignore[method-assign]

    rig.session.close()  # must not raise
    record = rig.session.record(performed_at="2026-08-12T00:00:00Z")

    assert record.outcome is RecordOutcome.FAILED
    assert rig.session.latch_reason is LatchReason.JOURNAL_WRITE_FAILED
    assert "Disk quota exceeded" in record.failure_reason
    # The step's evidence survives in the record even though the journal died.
    assert record.axis_sign(CommissioningAxis.VX) == 1
    assert record.stop is not None and record.stop.confirmed
    assert not record.authorizes_configuration()
    # The on-disk journal is left non-terminal on purpose: a journal that could
    # not record its own ending is an abandoned session, and re-opening latches.
    after = CommissioningJournal(rig.journal.path, session_id="x").entries()
    assert [entry["state"] for entry in after] == [entry["state"] for entry in landed]
    assert after[-1]["state"] not in {JournalState.COMPLETE.value, JournalState.LATCHED.value}
    with pytest.raises(CommissioningLatchedError) as excinfo:
        CommissioningJournal.begin(rig.journal.path, session_id="next")
    assert excinfo.value.reason is LatchReason.PROCESS_EXIT


def test_an_unreadable_journal_costs_the_digest_not_the_record(tmp_path) -> None:
    """Companion: `record()` survives a digest it cannot compute, fail-closed."""

    rig = _rig_session(tmp_path)
    rig.session.start()
    rig.session.close()
    rig.journal.digest = _out_of_quota  # type: ignore[method-assign]

    record = rig.session.record(performed_at="2026-08-12T00:00:00Z")
    assert record.journal_digest == ""
    assert "journal_digest" in record.missing_evidence()
    assert not record.authorizes_configuration()


def test_a_live_path_journal_failure_latches_by_name(tmp_path) -> None:
    """A lost journal line mid-session ends it under a named latch, not an OSError."""

    rig = _rig_session(tmp_path)
    rig.session.start()
    rig.journal._write = _out_of_quota  # type: ignore[method-assign]

    with pytest.raises(CommissioningLatchedError) as excinfo:
        rig.session.run_axis_step(CommissioningAxis.VX, STEP_SPEED_MPS, STEP_DURATION_S)
    assert excinfo.value.reason is LatchReason.JOURNAL_WRITE_FAILED
    record = rig.session.record(performed_at="2026-08-12T00:00:00Z")
    assert record.outcome is RecordOutcome.FAILED


def test_the_session_context_manager_latches_on_an_escaping_error(tmp_path) -> None:
    """Companion: an exception crossing the session boundary latches it."""

    rig = _rig_session(tmp_path)
    with pytest.raises(RuntimeError, match="operator walked away"), rig.session as session:
        assert session is rig.session
        raise RuntimeError("operator walked away")
    assert rig.session.latched
    assert rig.session.latch_reason is LatchReason.UNEXPECTED_ERROR


# --------------------------------------------- gate 4: the record and its review


def _complete_record(**overrides) -> CommissioningRecordV1:
    axes = tuple(
        AxisSignEvidence(
            axis=axis,
            commanded_speed=STEP_YAW_RAD_S if axis.is_angular else STEP_SPEED_MPS,
            samples=12,
            mean_measured_speed=(
                STEP_YAW_RAD_S if axis.is_angular else STEP_SPEED_MPS
            ) * 0.8,
            mean_cross_axis_speed=0.0,
            mean_yaw_rad=RIG_YAW_RAD,
            evidence_floor=SETTLED_YAW_RAD_S if axis.is_angular else SETTLED_LINEAR_MPS,
            observed_direction=direction,
            declared_velocity_frame="odom",
        )
        for axis, direction in (
            (CommissioningAxis.VX, ObservedDirection.FORWARD),
            (CommissioningAxis.VY, ObservedDirection.LEFT),
            (CommissioningAxis.VYAW, ObservedDirection.COUNTERCLOCKWISE),
        )
    )
    payload = {
        "record_id": "rec-1",
        "operator": "operator-under-test",
        "robot_serial": "RIG-0001",
        "performed_at": "2026-08-12T12:00:00Z",
        "outcome": RecordOutcome.PASSED,
        "declared_velocity_frame": "odom",
        "observed_modes": (3,),
        "axis_signs": axes,
        "observation": ObservationEvidence(samples=25, duration_s=1.0, modes_seen=(3,)),
        "stop": StopEvidence(
            request_latency_s=0.004,
            settle_latency_s=0.06,
            distance_m=0.004,
            distance_method="odom_delta",
            settled_linear_mps=SETTLED_LINEAR_MPS,
            settled_yaw_rad_s=SETTLED_YAW_RAD_S,
            confirmed=True,
            timeout_s=0.4,
        ),
        "journal_digest": "a" * 64,
        "software_revision": "test-revision",
    }
    payload.update(overrides)
    return CommissioningRecordV1(**payload)


def test_record_defaults_authorize_nothing() -> None:
    record = CommissioningRecordV1(
        record_id="bare",
        operator="op",
        robot_serial="RIG",
        performed_at="2026-08-12T12:00:00Z",
    )
    assert record.outcome is RecordOutcome.FAILED
    assert not record.authorizes_configuration()
    missing = set(record.missing_evidence())
    assert {"axis_sign:vx", "axis_sign:vy", "axis_sign:vyaw", "velocity_frame"} <= missing
    assert {"observed_modes", "observation", "stop_confirmation", "review"} <= missing
    with pytest.raises(CommissioningReviewError):
        commissioned_control_config({}, record)


def test_a_complete_record_still_authorizes_nothing_until_reviewed() -> None:
    record = _complete_record()
    assert record.missing_evidence() == ("review",)
    with pytest.raises(CommissioningReviewError, match="review"):
        commissioned_control_config({}, record)


def test_the_operator_cannot_review_their_own_record() -> None:
    record = _complete_record()
    with pytest.raises(CommissioningReviewError, match="other than its operator"):
        record.reviewed_by(
            reviewer="Operator-Under-Test",
            reviewed_at="2026-08-12T13:00:00Z",
            accepted=True,
        )


def test_a_rejected_review_authorizes_nothing() -> None:
    record = _complete_record().reviewed_by(
        reviewer="second-person",
        reviewed_at="2026-08-12T13:00:00Z",
        accepted=False,
    )
    assert not record.is_reviewed()
    assert not record.authorizes_configuration()


def test_a_review_does_not_survive_a_changed_record() -> None:
    """Seeded defect: edit the evidence after review. The attestation unbinds."""

    reviewed = _complete_record().reviewed_by(
        reviewer="second-person",
        reviewed_at="2026-08-12T13:00:00Z",
        accepted=True,
    )
    assert reviewed.authorizes_configuration()
    tampered = reviewed.replace(observed_modes=(3, 4))
    assert not tampered.is_reviewed()
    assert not tampered.authorizes_configuration()
    tampered_stop = reviewed.replace(
        stop=StopEvidence(
            request_latency_s=0.0,
            settle_latency_s=0.0,
            distance_m=0.0,
            distance_method="odom_delta",
            settled_linear_mps=SETTLED_LINEAR_MPS,
            settled_yaw_rad_s=SETTLED_YAW_RAD_S,
            confirmed=True,
        )
    )
    assert not tampered_stop.is_reviewed()


def test_forged_derived_flags_in_a_saved_record_are_ignored(tmp_path) -> None:
    """Seeded defect: hand-edit the file to claim it is authorized."""

    record = _complete_record(outcome=RecordOutcome.FAILED)
    path = record.save(tmp_path / "forged.json")
    payload = json.loads(path.read_text())
    payload["derived"]["authorizes_configuration"] = True
    payload["derived"]["reviewed"] = True
    payload["axis_signs"][0]["derived"]["sign"] = 1
    payload["review"] = {
        "reviewer": "not-the-operator",
        "reviewed_at": "2026-08-12T13:00:00Z",
        "record_digest": "0" * 64,
        "accepted": True,
    }
    path.write_text(json.dumps(payload))
    reloaded = CommissioningRecordV1.load(path)
    assert not reloaded.is_reviewed()
    assert not reloaded.authorizes_configuration()
    with pytest.raises(CommissioningReviewError):
        commissioned_control_config({}, reloaded)


def test_record_round_trips_and_keeps_its_digest(tmp_path) -> None:
    record = _complete_record().reviewed_by(
        reviewer="second-person",
        reviewed_at="2026-08-12T13:00:00Z",
        accepted=True,
    )
    path = record.save(tmp_path / "record.json")
    reloaded = CommissioningRecordV1.load(path)
    assert reloaded.content_digest() == record.content_digest()
    assert reloaded.is_reviewed()
    assert reloaded.authorizes_configuration()
    assert reloaded.as_dict() == record.as_dict()


def test_reviewed_record_enables_exactly_the_four_normal_flags() -> None:
    """GATE 4, and the loop the defect opened: the record closes it."""

    record = _complete_record().reviewed_by(
        reviewer="second-person",
        reviewed_at="2026-08-12T13:00:00Z",
        accepted=True,
    )
    config = commissioned_control_config({"unitree_sport": {"interface": "test0"}}, record)
    sport = config["unitree_sport"]
    assert sport["enable_lease"] is True
    assert sport["axes_commissioned"] is True
    assert sport["state_frame_commissioned"] is True
    assert sport["allowed_modes"] == [3]
    assert sport["lateral_sign"] == 1
    assert sport["yaw_sign"] == 1
    assert sport["state_velocity_frame"] == "odom"
    assert sport["commissioning_record_digest"] == record.content_digest()
    assert sport["interface"] == "test0"
    # The output is exactly what the untouched normal gate demands.
    manager = build_unitree_sport_control_manager(config, SafetyLimits())
    assert manager.controller.allowed_modes == frozenset({3})


def test_commissioned_control_config_does_not_mutate_its_input() -> None:
    record = _complete_record().reviewed_by(
        reviewer="second-person",
        reviewed_at="2026-08-12T13:00:00Z",
        accepted=True,
    )
    original = {"unitree_sport": {"interface": "test0"}}
    commissioned_control_config(original, record)
    assert original == {"unitree_sport": {"interface": "test0"}}


def test_an_axis_sign_needs_an_operator_observation() -> None:
    """The frame-cancellation finding: vendor feedback alone cannot sign an axis."""

    evidence = AxisSignEvidence(
        axis=CommissioningAxis.VY,
        commanded_speed=0.03,
        samples=10,
        mean_measured_speed=0.028,
        mean_cross_axis_speed=0.0,
        mean_yaw_rad=RIG_YAW_RAD,
        evidence_floor=SETTLED_LINEAR_MPS,
        declared_velocity_frame="odom",
    )
    assert evidence.feedback_agrees
    assert evidence.sign is None  # UNCERTAIN by default
    left = dataclasses.replace(evidence, observed_direction=ObservedDirection.LEFT)
    right = dataclasses.replace(evidence, observed_direction=ObservedDirection.RIGHT)
    unseen = dataclasses.replace(evidence, observed_direction=ObservedDirection.NONE)
    assert left.sign == 1
    assert right.sign == -1
    assert unseen.sign is None


def test_a_sign_below_the_evidence_floor_is_unknown() -> None:
    evidence = AxisSignEvidence(
        axis=CommissioningAxis.VX,
        commanded_speed=0.03,
        samples=10,
        mean_measured_speed=SETTLED_LINEAR_MPS / 2.0,
        mean_cross_axis_speed=0.0,
        mean_yaw_rad=RIG_YAW_RAD,
        evidence_floor=SETTLED_LINEAR_MPS,
        observed_direction=ObservedDirection.FORWARD,
        declared_velocity_frame="odom",
    )
    assert not evidence.moved
    assert evidence.sign is None


def test_the_velocity_frame_claim_is_not_discriminating_near_zero_yaw() -> None:
    """A frame check at yaw ~ 0 proves nothing, and the record says so."""

    baseline = _complete_record()
    near_zero = baseline.replace(
        axis_signs=tuple(
            dataclasses.replace(evidence, mean_yaw_rad=FRAME_DISCRIMINATION_YAW_RAD * 0.9)
            for evidence in baseline.axis_signs
        )
    )
    assert not near_zero.velocity_frame_confirmed
    assert "velocity_frame" in near_zero.missing_evidence()
    # Companion: the same evidence at a discriminating yaw confirms.
    assert baseline.velocity_frame_confirmed


def test_cross_axis_leak_refuses_the_frame_claim() -> None:
    baseline = _complete_record()
    leaking = dataclasses.replace(
        baseline.axis_signs[0], mean_cross_axis_speed=SETTLED_LINEAR_MPS * 2
    )
    record = baseline.replace(axis_signs=(leaking, *baseline.axis_signs[1:]))
    assert not record.velocity_frame_confirmed


# ------------------------------------ gate 5: no path into the autonomous runtime


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            names.add(f"{prefix}{node.module or ''}")
            for alias in node.names:
                names.add(f"{prefix}{node.module or ''}.{alias.name}")
    return names


def _python_sources() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def test_no_module_outside_the_commissioning_seam_imports_it() -> None:
    """GATE 5. Only the CLI and one lazy factory may reach physical commissioning."""

    allowed = {
        PACKAGE_ROOT / "unitree_control.py",
        PACKAGE_ROOT / "control" / "factory.py",
    }
    offenders: list[str] = []
    for path in _python_sources():
        if PACKAGE_ROOT / "commissioning" in path.parents or path in allowed:
            continue
        imported = _imported_modules(path)
        if any(
            name == "parcel_robot.commissioning"
            or name.startswith(("parcel_robot.commissioning.", ".commissioning."))
            or name == ".commissioning"
            for name in imported
        ):
            offenders.append(str(path.relative_to(PACKAGE_ROOT)))
    assert offenders == []


def test_the_runtime_module_never_mentions_commissioning() -> None:
    """The autonomous runtime cannot import the physical W0-B session package."""

    runtime = (PACKAGE_ROOT / "runtime.py").read_text()
    assert "parcel_robot.commissioning" not in runtime
    assert "CommissioningSession" not in runtime
    imported = _imported_modules(PACKAGE_ROOT / "runtime.py")
    assert [
        name
        for name in imported
        if name == "parcel_robot.commissioning"
        or name.startswith("parcel_robot.commissioning.")
    ] == []


def test_the_commissioning_package_imports_no_runtime_or_navigation() -> None:
    forbidden = ("runtime", "navigation", "instructnav", "route_memory", "evals", "brain")
    for path in sorted((PACKAGE_ROOT / "commissioning").rglob("*.py")):
        for module in _imported_modules(path):
            assert not any(f"parcel_robot.{name}" in module for name in forbidden), (
                f"{path.name} imports {module}"
            )


def test_importing_commissioning_does_not_import_the_runtime() -> None:
    """Executed proof, not just an AST read: nothing pulls the runtime in."""

    code = (
        "import sys\n"
        "import parcel_robot.commissioning  # noqa: F401\n"
        "leaked = [m for m in sys.modules if m.startswith('parcel_robot.') and "
        "any(k in m for k in ('runtime', 'navigation', 'instructnav', 'brain'))]\n"
        "print(','.join(sorted(leaked)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_session_exposes_no_control_manager_surface(tmp_path) -> None:
    """A session cannot be duck-typed into the runtime's control-manager slot."""

    rig = _rig_session(tmp_path)
    session = rig.session
    try:
        control_surface = {
            "set_target",
            "tick",
            "snapshot",
            "state_source",
            "controller",
            "timing",
            "emergency_stop",
            "clear_emergency_stop",
            "clear_fault",
        }
        for name in control_surface:
            assert not hasattr(session, name), f"session exposes {name}"
        for name in dir(session):
            if name.startswith("_"):
                continue
            assert not isinstance(getattr(session, name), ControlManager)
    finally:
        session.close()


def test_commissioning_builders_are_not_in_the_controller_registry() -> None:
    registered = set(controller_factory_names())
    assert "unitree_sport_commissioning" not in registered
    assert "commissioning" not in registered
    values = set(_CONTROLLER_FACTORIES.values())
    assert build_unitree_sport_commissioning_session not in values
    assert build_unitree_sport_observer not in values
    assert build_unitree_sport_control_manager in values


def test_the_observer_has_no_controller_at_all() -> None:
    rig = _FakeRig()
    observer = CommissioningObserver(_FakeStateSource(rig), declared_velocity_frame="odom")
    for name in ("controller", "set_target", "stop", "emergency_stop", "run_axis_step"):
        assert not hasattr(observer, name)


# --------------------------------------------------- derivations and provenance


def test_derived_constants_are_pinned_by_reference() -> None:
    """Card rule 6: constants derive, and a moved source reddens the gate."""

    assert FOOTPRINT_RADIUS_M == DEFAULT_ROBOT_PROFILE.footprint_radius_m
    assert MAX_YAW_RAD_S == MAX_LINEAR_MPS / FOOTPRINT_RADIUS_M
    assert MIN_YAW_RAD_S == MIN_LINEAR_MPS / FOOTPRINT_RADIUS_M
    assert SETTLED_LINEAR_MPS == MIN_LINEAR_MPS / 2.0
    assert SETTLED_YAW_RAD_S == MIN_YAW_RAD_S / 2.0
    live = ControlTiming()
    assert MAX_TTL_S == live.command_timeout_s
    assert CommissioningLimits().max_duration_s == live.stop_timeout_s
    assert FRAME_DISCRIMINATION_YAW_RAD == pytest.approx(math.asin(0.5))
    assert ARMING_TTL_S == 120.0


def test_production_settled_thresholds_do_not_discriminate_inside_the_band() -> None:
    """The finding this card works around, pinned at its true strength.

    An earlier version of this test claimed the production thresholds sit above
    the *entire* commissioning band. That is true on the linear axis and FALSE
    on yaw: production calls 0.12 rad/s settled and the yaw cap is 0.15625, so
    0.12 lands inside the band. The honest statement is the one asserted here —
    total blindness on linear, partial blindness on yaw — and it is still a
    defect, because most of the yaw band lies under 0.12 rad/s.
    """

    live = ControlTiming()

    # Linear: the production threshold is above the whole band, so at every
    # speed this path can command, a moving robot reads as "settled".
    assert live.settled_linear_speed_mps > MAX_LINEAR_MPS

    # Yaw: the production threshold falls INSIDE the band. It discriminates
    # above 0.12 rad/s and is blind below it — which covers the band floor
    # through most of its range.
    assert MIN_YAW_RAD_S < live.settled_yaw_speed_rad_s < MAX_YAW_RAD_S
    blind_fraction = (live.settled_yaw_speed_rad_s - MIN_YAW_RAD_S) / (
        MAX_YAW_RAD_S - MIN_YAW_RAD_S
    )
    assert blind_fraction > 0.5  # measured 0.61 at 7242660

    # What the clamp actually guarantees on both axes: commissioning's own
    # thresholds sit below its own floor, and strictly below production's.
    assert SETTLED_LINEAR_MPS < MIN_LINEAR_MPS
    assert SETTLED_YAW_RAD_S < MIN_YAW_RAD_S
    assert SETTLED_LINEAR_MPS < live.settled_linear_speed_mps
    assert SETTLED_YAW_RAD_S < live.settled_yaw_speed_rad_s


# ------------------------------------------------------------- the observer


def test_the_observer_refuses_a_robot_that_is_already_moving() -> None:
    rig = _FakeRig()
    rig.measured = VelocityCommand(vx=0.2)
    rig.target = VelocityCommand(vx=0.2)
    observer = CommissioningObserver(_FakeStateSource(rig), declared_velocity_frame="odom")
    observer.start()
    try:
        with pytest.raises(CommissioningRefusedError) as excinfo:
            observer.observe(min_samples=3, timeout_s=1.0)
        assert excinfo.value.reason is RefusalReason.ROBOT_NOT_STATIONARY
    finally:
        observer.close()


def test_the_observer_refuses_a_vendor_error_code() -> None:
    rig = _FakeRig()
    rig.error_code = 5
    observer = CommissioningObserver(_FakeStateSource(rig), declared_velocity_frame="odom")
    observer.start()
    try:
        with pytest.raises(CommissioningRefusedError) as excinfo:
            observer.observe(min_samples=3, timeout_s=1.0)
        assert excinfo.value.reason is RefusalReason.VENDOR_FAULT
    finally:
        observer.close()


def test_the_observer_refuses_a_silent_state_stream() -> None:
    rig = _FakeRig()
    source = _FakeStateSource(rig)
    source.blank = True
    observer = CommissioningObserver(source, declared_velocity_frame="odom")
    observer.start()
    try:
        with pytest.raises(CommissioningRefusedError) as excinfo:
            observer.observe(min_samples=3, timeout_s=0.2)
        assert excinfo.value.reason is RefusalReason.NO_FEEDBACK
    finally:
        observer.close()


def test_the_observer_reports_the_modes_the_next_phase_needs() -> None:
    rig = _FakeRig()
    observer = CommissioningObserver(_FakeStateSource(rig), declared_velocity_frame="odom")
    observer.start()
    try:
        evidence = observer.observe(min_samples=5, timeout_s=2.0)
    finally:
        observer.close()
    assert evidence.modes_seen == (3,)
    assert evidence.samples >= 5
    assert evidence.sample_hz > 0.0
    assert evidence.declared_velocity_frame == "odom"


# --------------------------------------------------- the whole card, end to end


def test_full_session_produces_a_record_that_enables_configuration(tmp_path) -> None:
    """Observe -> arm -> three one-axis steps -> record -> review -> config."""

    rig = _FakeRig()
    observer = CommissioningObserver(_FakeStateSource(rig), declared_velocity_frame="odom")
    observer.start()
    try:
        observation = observer.observe(min_samples=5, timeout_s=2.0)
    finally:
        observer.close()

    harness = _rig_session(
        tmp_path,
        rig=rig,
        arming=_arming(observed_modes=observation.modes_seen),
    )
    session = harness.session
    session.adopt_observation(observation)
    directions = {
        CommissioningAxis.VX: ObservedDirection.FORWARD,
        CommissioningAxis.VY: ObservedDirection.LEFT,
        CommissioningAxis.VYAW: ObservedDirection.COUNTERCLOCKWISE,
    }
    try:
        session.start()
        for axis, direction in directions.items():
            speed = STEP_YAW_RAD_S if axis.is_angular else STEP_SPEED_MPS
            session.run_axis_step(
                axis, speed, STEP_DURATION_S, observed_direction=direction
            )
    finally:
        session.close()

    assert not session.latched
    assert session.steps_run == 3
    record = session.record(
        record_id="e2e-1",
        performed_at="2026-08-12T12:00:00Z",
        software_revision="test-revision",
    )
    assert record.outcome is RecordOutcome.PASSED, record.failure_reason
    assert record.axes_confirmed
    assert record.velocity_frame_confirmed
    assert record.stop_confirmed
    assert record.journal_digest
    assert record.missing_evidence() == ("review",)

    reviewed = record.reviewed_by(
        reviewer="second-person",
        reviewed_at="2026-08-12T13:00:00Z",
        accepted=True,
    )
    assert reviewed.authorizes_configuration()
    config = commissioned_control_config(_UNCOMMISSIONED, reviewed)
    manager = build_unitree_sport_control_manager(config, SafetyLimits())
    assert manager.controller.allowed_modes == frozenset({3})
    assert manager.controller.lateral_sign == 1
    assert manager.controller.yaw_sign == 1
