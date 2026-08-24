"""Card W0-A — physical feedback and typed provenance (P0-1, P0-2).

Provenance: ``scrum/20260812/task_2/W0_PRODUCT_CARDS.md`` §"Card W0-A", the
plan's ``PRODUCTION_COMPANION_PLAN.md`` §"Card W0-A", and the board rulings in
``scrum/20260812/task_2/BOARD_DECISIONS.md`` (D-1 carrier-type authority, D-2
physical requirements table, D-3 default-constructed boundary objects).

The two confirmed defects these cells pin:

1. ``runtime.py`` retained an injected manager's state source only via
   ``isinstance(BufferedRobotStateSource)``. A ``UnitreeSportStateSource`` is a
   plain class, so it was DISCARDED and the input-health feedback reads saw
   nothing from the physical path.
2. ``core/input_health.py`` inferred authority from producer strings:
   ``PHYSICAL_SOURCE_NAMES = {"", "unknown", "physical"}`` trusted ``unknown``
   as physical while ``unitree_sport`` was classified a simulator fixture.

Every property cell carries a seeded-failure companion: the mutant is the
pre-W0-A behaviour, and the cell shows the oracle rejects it. A test that only
asserts the fixed behaviour cannot tell you the oracle would have caught the
defect.
"""

from __future__ import annotations

import ast
import math
import subprocess
import sys
import time
from pathlib import Path

import pytest

from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.control.base import (
    CommissionedStateSource,
    as_observation_sink,
    declared_origin,
    is_robot_state_source,
)
from parcel_robot.control.models import FaultReason, RobotMotionState
from parcel_robot.control.state import BufferedRobotStateSource
from parcel_robot.core.input_health import (
    DEFAULT_REQUIRED_INPUTS,
    EvidenceOrigin,
    HealthAction,
    InputEvidence,
    RequiredInput,
    evaluate_input_health,
    evidence_origin,
    requirements_allowing_sim_fixtures,
    requirements_requiring_physical_inputs,
)
from parcel_robot.models import VelocityCommand

NOW = 1_000.0

#: A physically commissioned deployment: no synthetic origin satisfies
#: anything (board D-2).
PHYSICAL_REQUIREMENTS = requirements_requiring_physical_inputs()


# ---------------------------------------------------------------------------
# Fakes. The Unitree source is driven through its real ``_on_message`` decode
# path with a fake DDS message, so this exercises the shipped adapter rather
# than a hand-built RobotMotionState.
# ---------------------------------------------------------------------------


class _FakeImu:
    def __init__(self, yaw: float) -> None:
        self.rpy = (0.0, 0.0, yaw)


class _FakeSportModeState:
    """Shape-compatible stand-in for ``unitree_go.msg.dds_.SportModeState_``."""

    def __init__(self, *, yaw: float = 0.0, vx: float = 0.0, mode: int = 1) -> None:
        self.position = (1.0, 2.0, 0.3)
        self.velocity = (vx, 0.0, 0.0)
        self.imu_state = _FakeImu(yaw)
        self.yaw_speed = 0.0
        self.mode = mode
        self.error_code = 0
        self.foot_force = (10.0, 10.0, 10.0, 10.0)


def _unitree_source(clock):
    """A real ``UnitreeSportStateSource`` with no SDK and no channel I/O."""

    from parcel_robot.control.unitree_sport import (
        UnitreeChannelContext,
        UnitreeSportStateSource,
    )

    channel = UnitreeChannelContext(0, "lo", initializer=lambda domain, iface: None)
    return UnitreeSportStateSource(channel, clock=clock)


def _feed(source, message) -> None:
    source._on_message(message)


class _W0ABackend:
    """Minimal simulator backend for the runtime-level cells."""

    name = "w0a-fake"

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            nearest_obstacle_bearing_rad=0.0,
            backend="w0a-fake",
        )

    def move(self, command) -> None:
        del command

    def stop(self) -> None:
        return None

    def pose(self, pose) -> None:
        del pose


def _w0a_config(tmp_path):
    path = tmp_path / "w0a.yaml"
    path.write_text(
        "skills:\n  root: configs/skills\n"
        "navigation:\n  enabled: false\n"
        'memory:\n  path: ":memory:"\n'
        "poses: {}\nmodules: []\n",
        encoding="utf-8",
    )
    return path


def _silent_audio():
    from parcel_robot.audio.devices import AudioDeviceStatus

    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="test",
    )


def _physical_evidence(state: RobotMotionState, *, now: float = NOW) -> dict:
    """The evidence table the runtime builds, for a PHYSICAL feedback datum."""

    return {
        RequiredInput.POSE: InputEvidence(
            captured_at=now,
            frame_id="odom",
            origin=EvidenceOrigin.PHYSICAL,
        ),
        RequiredInput.SCAN: InputEvidence(
            captured_at=now,
            frame_id="base_link",
            origin=EvidenceOrigin.PHYSICAL,
        ),
        RequiredInput.CONTROLLER_FEEDBACK: InputEvidence(
            captured_at=state.received_at,
            frame_id="base_link",
            payload_valid=state.fault_reason is FaultReason.NONE,
            origin=state.origin,
            fixture_label=None if state.origin is EvidenceOrigin.PHYSICAL else state.source,
        ),
    }


# ---------------------------------------------------------------------------
# GATE 1 — physical unitree_sport feedback satisfies a commissioned join
# ---------------------------------------------------------------------------


def test_commissioned_unitree_sport_feedback_satisfies_a_physical_join() -> None:
    source = _unitree_source(lambda: NOW)
    commissioned = CommissionedStateSource(
        source,
        origin=EvidenceOrigin.PHYSICAL,
        session_epoch="boot-1",
    )
    _feed(source, _FakeSportModeState(vx=0.3))

    state = commissioned.latest()
    assert state is not None
    assert state.source == "unitree_sport"
    assert state.origin is EvidenceOrigin.PHYSICAL
    assert state.session_epoch == "boot-1"

    verdict = evaluate_input_health(
        _physical_evidence(state), now=NOW, requirements=PHYSICAL_REQUIREMENTS
    )
    assert verdict.action is HealthAction.ALLOW
    assert verdict.translation_allowed


def test_seeded_failure_uninstrumented_unitree_source_cannot_reach_physical() -> None:
    """The mutant: skip commissioning and hand the raw vendor source over.

    This is the pre-W0-A world's premise — that a producer NAME is enough. The
    raw source declares nothing, so its datum is UNKNOWN and the join latches.
    """

    source = _unitree_source(lambda: NOW)
    _feed(source, _FakeSportModeState())
    raw = source.latest()

    assert raw is not None
    assert raw.source == "unitree_sport"  # the name that used to decide
    assert raw.origin is EvidenceOrigin.UNKNOWN
    assert declared_origin(source) is EvidenceOrigin.UNKNOWN

    verdict = evaluate_input_health(
        _physical_evidence(raw), now=NOW, requirements=PHYSICAL_REQUIREMENTS
    )
    assert verdict.action is HealthAction.LATCHED_STOP
    assert not verdict.translation_allowed
    assert any(fault.reason == "origin_unknown" for fault in verdict.faults)


def test_physical_source_is_retained_for_reading_whatever_its_class() -> None:
    """P0-1: the retention predicate must not be an isinstance on the sim buffer."""

    source = _unitree_source(lambda: NOW)
    assert not isinstance(source, BufferedRobotStateSource)
    # The retired predicate discarded it; the shipped one retains it.
    assert is_robot_state_source(source)
    assert is_robot_state_source(CommissionedStateSource(source, origin=EvidenceOrigin.PHYSICAL))


# ---------------------------------------------------------------------------
# GATE 2 — simulator / replay cannot satisfy physical requirements
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("origin", [EvidenceOrigin.SIMULATION, EvidenceOrigin.REPLAY])
@pytest.mark.parametrize("required_input", list(RequiredInput))
def test_synthetic_origins_cannot_satisfy_a_physical_requirement(
    origin: EvidenceOrigin,
    required_input: RequiredInput,
) -> None:
    evidence = {
        item: InputEvidence(
            captured_at=NOW,
            frame_id=DEFAULT_REQUIRED_INPUTS[item].frame_id,
            origin=EvidenceOrigin.PHYSICAL,
        )
        for item in RequiredInput
    }
    evidence[required_input] = InputEvidence(
        captured_at=NOW,
        frame_id=DEFAULT_REQUIRED_INPUTS[required_input].frame_id,
        origin=origin,
        fixture_label="labeled-and-still-forbidden",
    )

    verdict = evaluate_input_health(
        evidence, now=NOW, requirements=PHYSICAL_REQUIREMENTS
    )

    assert verdict.action is HealthAction.LATCHED_STOP
    assert not verdict.translation_allowed
    assert {fault.reason for fault in verdict.faults} == {"sim_fixture_forbidden"}


def test_seeded_failure_a_well_labeled_fixture_is_still_not_physical() -> None:
    """Mutant: 'the label proves it is honest, so let it through'.

    A label makes a fixture ADMISSIBLE where fixtures are commissioned. It
    never makes it PHYSICAL. Same datum, two tables, two verdicts.
    """

    fixture = {
        item: InputEvidence(
            captured_at=NOW,
            frame_id=DEFAULT_REQUIRED_INPUTS[item].frame_id,
            origin=EvidenceOrigin.SIMULATION,
            fixture_label="unit-test-fixture-v1",
        )
        for item in RequiredInput
    }

    assert evaluate_input_health(
        fixture, now=NOW, requirements=requirements_allowing_sim_fixtures()
    ).action is HealthAction.ALLOW
    assert evaluate_input_health(
        fixture, now=NOW, requirements=PHYSICAL_REQUIREMENTS
    ).action is HealthAction.LATCHED_STOP


# ---------------------------------------------------------------------------
# GATE 3 / D-3 — no string mints physical; defaults never satisfy a join
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "producer",
    [
        "",
        "unknown",
        "physical",  # all three were the retired PHYSICAL_SOURCE_NAMES
        "Physical",
        "unitree_sport",
        "unitree_sport_state",
        "socket",
        None,
        object(),
    ],
)
def test_no_producer_string_can_mint_physical_authority(producer: object) -> None:
    origin, _label = evidence_origin(producer)
    assert origin is not EvidenceOrigin.PHYSICAL
    assert origin is EvidenceOrigin.SIMULATION


def test_seeded_failure_the_retired_whitelist_would_have_minted_physical() -> None:
    """The exact retired mechanism, re-implemented, then rejected by the oracle."""

    retired_physical_source_names = frozenset({"", "unknown", "physical"})

    def retired_evidence_origin(source: object):
        name = str(source or "")
        if name not in retired_physical_source_names:
            return EvidenceOrigin.SIMULATION, name
        return EvidenceOrigin.PHYSICAL, None

    # The mutant hands physical authority to the two defaults and denies it to
    # the real vendor channel — the defect, exactly.
    assert retired_evidence_origin("unknown")[0] is EvidenceOrigin.PHYSICAL
    assert retired_evidence_origin("unitree_sport")[0] is EvidenceOrigin.SIMULATION

    def no_string_mints_physical_oracle(stamper) -> None:
        assert stamper("unknown")[0] is not EvidenceOrigin.PHYSICAL

    no_string_mints_physical_oracle(evidence_origin)
    with pytest.raises(AssertionError):
        no_string_mints_physical_oracle(retired_evidence_origin)


def test_default_constructed_boundary_objects_never_satisfy_a_physical_join() -> None:
    """Board D-3. Declaring nothing was the strongest authority in the system."""

    default_state = RobotMotionState(received_at=NOW, sequence=1)
    default_observation = SimObservation(
        timestamp=NOW, robot=RobotPose(), owner=OwnerTrack()
    )
    # Both defaults are the string that used to mean "physical".
    assert default_state.source == "unknown"
    assert default_observation.backend == "unknown"
    # Neither declares an origin, so neither is physical.
    assert default_state.origin is EvidenceOrigin.UNKNOWN
    assert evidence_origin(default_observation.backend)[0] is EvidenceOrigin.SIMULATION

    verdict = evaluate_input_health(
        _physical_evidence(default_state), now=NOW, requirements=PHYSICAL_REQUIREMENTS
    )
    assert verdict.action is HealthAction.LATCHED_STOP
    assert not verdict.translation_allowed


def test_a_string_origin_attribute_is_not_a_declaration() -> None:
    """Spoof attempt: name the attribute right, give it a string."""

    class _Spoof:
        name = "definitely_physical"
        origin = "physical"

        def latest(self):
            return None

    assert declared_origin(_Spoof()) is EvidenceOrigin.UNKNOWN
    # And the enum-valued member of the same name IS honoured.
    assert declared_origin(
        CommissionedStateSource(_Spoof(), origin=EvidenceOrigin.PHYSICAL)
    ) is EvidenceOrigin.PHYSICAL


def test_commissioning_refuses_to_declare_unknown() -> None:
    source = _unitree_source(lambda: NOW)
    with pytest.raises(ValueError, match="UNKNOWN is not one"):
        CommissionedStateSource(source, origin=EvidenceOrigin.UNKNOWN)
    with pytest.raises(TypeError, match="EvidenceOrigin"):
        CommissionedStateSource(source, origin="physical")


# ---------------------------------------------------------------------------
# GATES 4-8 — the hold/latch severity contract, each with a seeded failure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("missing", HealthAction.HOLD),
        ("stale", HealthAction.HOLD),
        ("unknown_origin", HealthAction.LATCHED_STOP),
        ("future", HealthAction.LATCHED_STOP),
        ("wrong_frame", HealthAction.LATCHED_STOP),
        ("invalid_payload", HealthAction.LATCHED_STOP),
        ("nan_timestamp", HealthAction.LATCHED_STOP),
    ],
)
def test_physical_feedback_fault_severity_is_exact(
    case: str, expected: HealthAction
) -> None:
    spec = DEFAULT_REQUIRED_INPUTS[RequiredInput.CONTROLLER_FEEDBACK]
    evidence = {
        item: InputEvidence(
            captured_at=NOW,
            frame_id=DEFAULT_REQUIRED_INPUTS[item].frame_id,
            origin=EvidenceOrigin.PHYSICAL,
        )
        for item in RequiredInput
    }
    physical = {"origin": EvidenceOrigin.PHYSICAL}
    faulted: InputEvidence | None
    if case == "missing":
        faulted = None
    elif case == "stale":
        faulted = InputEvidence(
            captured_at=NOW - spec.max_age_s - 0.001, frame_id="base_link", **physical
        )
    elif case == "unknown_origin":
        faulted = InputEvidence(captured_at=NOW, frame_id="base_link")
    elif case == "future":
        faulted = InputEvidence(captured_at=NOW + 1.0, frame_id="base_link", **physical)
    elif case == "wrong_frame":
        faulted = InputEvidence(captured_at=NOW, frame_id="odom", **physical)
    elif case == "invalid_payload":
        faulted = InputEvidence(
            captured_at=NOW, frame_id="base_link", payload_valid=False, **physical
        )
    else:
        faulted = InputEvidence(captured_at=math.nan, frame_id="base_link", **physical)
    evidence[RequiredInput.CONTROLLER_FEEDBACK] = faulted

    verdict = evaluate_input_health(
        evidence, now=NOW, requirements=PHYSICAL_REQUIREMENTS
    )

    assert verdict.action is expected
    assert not verdict.translation_allowed


def test_seeded_failure_severity_oracle_rejects_a_hold_where_a_latch_is_due() -> None:
    """Mutant: downgrade the future-dated latch to a recoverable HOLD."""

    def severity_oracle(action: HealthAction) -> None:
        assert action is HealthAction.LATCHED_STOP

    evidence = {
        item: InputEvidence(
            captured_at=NOW,
            frame_id=DEFAULT_REQUIRED_INPUTS[item].frame_id,
            origin=EvidenceOrigin.PHYSICAL,
        )
        for item in RequiredInput
    }
    evidence[RequiredInput.POSE] = InputEvidence(
        captured_at=NOW + 1.0, frame_id="odom", origin=EvidenceOrigin.PHYSICAL
    )
    severity_oracle(
        evaluate_input_health(evidence, now=NOW, requirements=PHYSICAL_REQUIREMENTS).action
    )
    with pytest.raises(AssertionError):
        severity_oracle(HealthAction.HOLD)


# ---------------------------------------------------------------------------
# GATE 5 — reordering, and a latch that actually latches (verdict RC-1c)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("duplicate", "sequence_duplicate"),
        ("reordered", "sequence_reordered"),
        ("receipt_backward", "receipt_regression"),
    ],
)
def test_out_of_order_physical_feedback_latches_exactly(case: str, reason: str) -> None:
    clock = {"t": NOW}
    source = _unitree_source(lambda: clock["t"])
    commissioned = CommissionedStateSource(source, origin=EvidenceOrigin.PHYSICAL)

    # Run the stream up to a sequence with room to regress beneath it.
    for _ in range(10):
        _feed(source, _FakeSportModeState())
    first = commissioned.latest()
    assert first is not None and first.fault_reason is FaultReason.NONE
    assert first.sequence == 10

    # Rewrite the vendor source's internal cursor to replay the disorder the
    # transport can really deliver.
    if case == "duplicate":
        # A re-delivered message: same sequence, LATER receipt. (Same sequence
        # AND same receipt is just a second poll of one sample, which is normal
        # and must not fault — see the dedicated cell below.)
        source._sequence -= 1
        clock["t"] = NOW + 0.01
    elif case == "reordered":
        source._sequence -= 5
    else:
        clock["t"] = NOW - 1.0
    _feed(source, _FakeSportModeState())

    faulted = commissioned.latest()
    assert faulted is not None
    assert faulted.fault_reason is FaultReason.COMMS
    assert ("provenance_fault", reason) in faulted.vendor_extra
    assert commissioned.latched_reason == reason

    verdict = evaluate_input_health(
        _physical_evidence(faulted, now=faulted.received_at),
        now=faulted.received_at,
        requirements=PHYSICAL_REQUIREMENTS,
    )
    assert verdict.action is HealthAction.LATCHED_STOP


def test_polling_the_same_sample_twice_is_not_a_disorder() -> None:
    """``latest()`` is a poll. The runtime calls it twice per tick by design.

    Regression cell: an ordering check that compares only sequence numbers
    reads the second poll of one sample as a duplicate and latches the whole
    deployment on its first healthy tick. This was caught by the runtime cell
    below before it could ship.
    """

    source = _unitree_source(lambda: NOW)
    commissioned = CommissionedStateSource(source, origin=EvidenceOrigin.PHYSICAL)
    _feed(source, _FakeSportModeState())

    for _ in range(5):
        state = commissioned.latest()
        assert state.fault_reason is FaultReason.NONE
    assert commissioned.latched_reason is None


def test_seeded_failure_colliding_keys_with_a_different_payload_latch() -> None:
    """Fable audit item 1, as an executed probe.

    The exemption for a re-polled sample used to be keyed on
    ``(sequence, received_at)`` alone. A source that reuses a key for a
    DIFFERENT payload therefore drew a clean physical ALLOW — provenance
    laundering through a key collision. The shipped Unitree adapter cannot do
    this (host monotonic receipt, per-message sequence), but the seam is public
    and W0-C's adapters are unwritten, so the probe is pinned here.
    """

    source = BufferedRobotStateSource()
    commissioned = CommissionedStateSource(source, origin=EvidenceOrigin.PHYSICAL)

    first = RobotMotionState(
        received_at=NOW,
        sequence=7,
        source="vendor",
        velocity=VelocityCommand(vx=0.0),
    )
    source.update(first)
    assert commissioned.latest().fault_reason is FaultReason.NONE

    # Same (sequence, received_at). Different robot.
    collided = RobotMotionState(
        received_at=NOW,
        sequence=7,
        source="vendor",
        velocity=VelocityCommand(vx=0.9),
        position=(5.0, 5.0, 0.0),
    )
    source._latest = collided  # bypass the buffer's own ordering guard

    laundered = commissioned.latest()
    assert laundered.fault_reason is FaultReason.COMMS
    assert ("provenance_fault", "sequence_duplicate") in laundered.vendor_extra
    assert commissioned.latched_reason == "sequence_duplicate"

    verdict = evaluate_input_health(
        _physical_evidence(laundered, now=NOW), now=NOW, requirements=PHYSICAL_REQUIREMENTS
    )
    assert verdict.action is HealthAction.LATCHED_STOP

    # The mutant is the pre-fix rule: keys match, therefore same sample.
    def content_identity_oracle(action: HealthAction) -> None:
        assert action is HealthAction.LATCHED_STOP

    content_identity_oracle(verdict.action)
    with pytest.raises(AssertionError):
        content_identity_oracle(HealthAction.ALLOW)


def test_an_equal_valued_rebuild_of_the_same_sample_is_still_not_a_disorder() -> None:
    """The exemption still covers a source that rebuilds an EQUAL datum.

    Identity is checked first, but a source returning a fresh object with every
    field equal is re-presenting the same sample, not re-delivering a new one.
    """

    source = BufferedRobotStateSource()
    commissioned = CommissionedStateSource(source, origin=EvidenceOrigin.PHYSICAL)
    fields = {"received_at": NOW, "sequence": 3, "source": "vendor"}

    source.update(RobotMotionState(**fields))
    assert commissioned.latest().fault_reason is FaultReason.NONE

    source._latest = RobotMotionState(**fields)  # equal, not identical
    assert commissioned.latest().fault_reason is FaultReason.NONE
    assert commissioned.latched_reason is None


def test_the_ordering_latch_survives_a_subsequent_clean_tick() -> None:
    """Verdict RC-1c: a latch that a clean sample clears is not a latch."""

    clock = {"t": NOW}
    source = _unitree_source(lambda: clock["t"])
    commissioned = CommissionedStateSource(source, origin=EvidenceOrigin.PHYSICAL)
    for _ in range(10):
        _feed(source, _FakeSportModeState())
    commissioned.latest()

    source._sequence -= 5  # the disorder
    _feed(source, _FakeSportModeState())
    assert commissioned.latest().fault_reason is FaultReason.COMMS

    # Now a perfectly clean, fresh, in-order sample arrives.
    clock["t"] = NOW + 1.0
    source._sequence = 100
    _feed(source, _FakeSportModeState())
    recovered = commissioned.latest()

    assert recovered.fault_reason is FaultReason.COMMS
    assert commissioned.latched_reason == "sequence_reordered"
    assert evaluate_input_health(
        _physical_evidence(recovered, now=recovered.received_at),
        now=recovered.received_at,
        requirements=PHYSICAL_REQUIREMENTS,
    ).action is HealthAction.LATCHED_STOP


def test_seeded_failure_a_stateless_latch_would_reauthorize_on_recovery() -> None:
    """Mutant: judge each sample independently, with no memory."""

    def latch_persistence_oracle(action_after_clean_tick: HealthAction) -> None:
        assert action_after_clean_tick is HealthAction.LATCHED_STOP

    clock = {"t": NOW}
    source = _unitree_source(lambda: clock["t"])
    commissioned = CommissionedStateSource(source, origin=EvidenceOrigin.PHYSICAL)
    for _ in range(10):
        _feed(source, _FakeSportModeState())
    commissioned.latest()
    source._sequence -= 5
    _feed(source, _FakeSportModeState())
    commissioned.latest()
    clock["t"] = NOW + 1.0
    source._sequence = 100
    _feed(source, _FakeSportModeState())
    recovered = commissioned.latest()

    latch_persistence_oracle(
        evaluate_input_health(
            _physical_evidence(recovered, now=recovered.received_at),
            now=recovered.received_at,
            requirements=PHYSICAL_REQUIREMENTS,
        ).action
    )
    with pytest.raises(AssertionError):
        latch_persistence_oracle(HealthAction.ALLOW)


def test_a_session_epoch_change_latches() -> None:
    source = BufferedRobotStateSource()
    commissioned = CommissionedStateSource(
        source, origin=EvidenceOrigin.PHYSICAL, session_epoch="boot-1"
    )
    source.update(
        RobotMotionState(
            received_at=NOW,
            sequence=1,
            source="vendor",
            session_epoch="boot-1",
            origin=EvidenceOrigin.PHYSICAL,
        )
    )
    assert commissioned.latest().fault_reason is FaultReason.NONE

    source.update(
        RobotMotionState(
            received_at=NOW + 0.1,
            sequence=2,
            source="vendor",
            session_epoch="boot-2",  # the robot rebooted under us
            origin=EvidenceOrigin.PHYSICAL,
        )
    )
    assert commissioned.latest().fault_reason is FaultReason.COMMS
    assert commissioned.latched_reason == "session_epoch_mismatch"


def test_provenance_fields_are_preserved_through_the_commissioned_seam() -> None:
    source = BufferedRobotStateSource()
    commissioned = CommissionedStateSource(
        source, origin=EvidenceOrigin.PHYSICAL, session_epoch="boot-7"
    )
    source.update(
        RobotMotionState(
            received_at=NOW,          # host receipt
            sequence=41,
            source="unitree_sport",
            source_time_s=12.5,       # vendor/device clock, a different domain
            velocity=VelocityCommand(vx=0.25),
        )
    )

    state = commissioned.latest()
    assert state.received_at == NOW
    assert state.source_time_s == 12.5
    assert state.sequence == 41
    assert state.source == "unitree_sport"
    assert state.velocity.vx == 0.25
    assert state.origin is EvidenceOrigin.PHYSICAL
    assert state.session_epoch == "boot-7"


# ---------------------------------------------------------------------------
# GATE 9 — the simulator-only write seam, and missing geometry
# ---------------------------------------------------------------------------


def test_the_observation_sink_is_simulator_only() -> None:
    sim = BufferedRobotStateSource()
    assert as_observation_sink(sim) is sim

    physical = CommissionedStateSource(
        _unitree_source(lambda: NOW), origin=EvidenceOrigin.PHYSICAL
    )
    # A physical source has no write seam at all ...
    assert not hasattr(physical, "update_observation")
    assert as_observation_sink(physical) is None


def test_a_physical_declaration_refuses_the_sink_even_if_the_method_exists() -> None:
    """Defence in depth: the refusal does not rely on the method being absent."""

    class _WritablePhysical(BufferedRobotStateSource):
        origin = EvidenceOrigin.PHYSICAL

    writable = _WritablePhysical()
    assert callable(writable.update_observation)
    assert as_observation_sink(writable) is None


def test_a_write_only_source_does_not_crash_the_collision_gate(tmp_path) -> None:
    """Fable audit item 2: the two seams are independent, so honour that.

    A source implementing ``update_observation`` but not ``latest`` is
    protocol-violating, but the split made it *reachable*: the sink guard
    passed and the reader was then called unconditionally, so ``_collision_safe``
    raised AttributeError instead of gating. Crash-not-silent-auth, but a crash
    in the final reactive brake is still a new failure mode.
    """

    from parcel_robot.control.adapters import BackendVelocityController
    from parcel_robot.control.manager import ControlManager
    from parcel_robot.runtime import RobotRuntime

    class _WriteOnlySource(BufferedRobotStateSource):
        """Sink present, reader absent."""

        latest = None  # type: ignore[assignment]

    backend = _W0ABackend()
    source = _WriteOnlySource()
    manager = ControlManager(BackendVelocityController(backend), source)
    runtime = RobotRuntime(
        _w0a_config(tmp_path),
        backend,
        audio_status=_silent_audio(),
        control_manager=manager,
    )
    try:
        assert runtime._observation_sink is source   # the write seam is present
        assert runtime._control_state_source is None  # the read seam is not

        command, state = runtime._collision_safe(
            VelocityCommand(vx=0.4), backend.observe(), now=time.monotonic()
        )
        # No AttributeError, and no translation authorised off a source that
        # cannot be read.
        assert command.vx == 0.0
        assert state in {"stopped", "clear"}
    finally:
        runtime.close()


def test_missing_geometry_holds_exactly_and_never_emits_physical_translation() -> None:
    evidence = {
        item: InputEvidence(
            captured_at=NOW,
            frame_id=DEFAULT_REQUIRED_INPUTS[item].frame_id,
            origin=EvidenceOrigin.PHYSICAL,
        )
        for item in RequiredInput
    }
    evidence[RequiredInput.SCAN] = None

    verdict = evaluate_input_health(
        evidence, now=NOW, requirements=PHYSICAL_REQUIREMENTS
    )

    # Exactly a HOLD — recoverable, not a latch — and never translation.
    assert verdict.action is HealthAction.HOLD
    assert not verdict.translation_allowed
    assert [fault.required_input for fault in verdict.faults] == [RequiredInput.SCAN]
    assert [fault.reason for fault in verdict.faults] == ["missing"]


def test_evidence_origin_module_is_a_stdlib_only_leaf() -> None:
    """Board D-5's standing condition, pinned.

    ``EvidenceOrigin`` lives in its own root module for exactly one reason: the
    boundary layers must be able to declare provenance without importing a
    package ``__init__``. If this module ever grows a ``parcel_robot`` import,
    the reason it exists is gone and W0-B's commissioning leaf invariant breaks
    again — silently, at some import site far from here.

    Precedent: ``tests/test_p4_place_graph.py::
    test_place_graph_imports_no_onnx_torch_or_navigation``.
    """

    from parcel_robot import evidence_origin as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # a relative import is by definition intra-package
                imported.append("." * node.level + (node.module or ""))
            else:
                imported.append(node.module or "")

    assert not any(name.startswith("parcel_robot") for name in imported), (
        f"evidence_origin must import nothing from parcel_robot: {imported}"
    )
    assert not any(name.startswith(".") for name in imported), (
        f"evidence_origin must have no relative imports: {imported}"
    )
    for name in imported:
        root = name.split(".", 1)[0]
        assert root in sys.stdlib_module_names, (
            f"evidence_origin imports non-stdlib {name!r}: {imported}"
        )

    # And the property the AST walk is a proxy for, measured directly.
    probe_source = (
        "import sys, parcel_robot.evidence_origin as m; "
        "print(sorted(k for k in sys.modules if k.startswith('parcel_robot')))"
    )
    probe = subprocess.run(
        [sys.executable, "-c", probe_source],
        capture_output=True,
        text=True,
        check=True,
    )
    assert probe.stdout.strip() == "['parcel_robot', 'parcel_robot.evidence_origin']", (
        f"importing evidence_origin pulled in more than itself: {probe.stdout!r}"
    )


def test_the_simulator_default_table_is_preserved_untouched() -> None:
    """The card preserves the shipped simulator default until deliberately migrated."""

    assert DEFAULT_REQUIRED_INPUTS[RequiredInput.SCAN].sim_fixture_allowed is True
    assert DEFAULT_REQUIRED_INPUTS[RequiredInput.POSE].sim_fixture_allowed is False
    assert (
        DEFAULT_REQUIRED_INPUTS[RequiredInput.CONTROLLER_FEEDBACK].sim_fixture_allowed
        is False
    )
    # ... and the physical table differs from it in exactly that one cell.
    physical = requirements_requiring_physical_inputs()
    differing = {
        item
        for item in RequiredInput
        if physical[item].sim_fixture_allowed
        != DEFAULT_REQUIRED_INPUTS[item].sim_fixture_allowed
    }
    assert differing == {RequiredInput.SCAN}
    for item in RequiredInput:
        assert physical[item].frame_id == DEFAULT_REQUIRED_INPUTS[item].frame_id
        assert physical[item].max_age_s == DEFAULT_REQUIRED_INPUTS[item].max_age_s


# ---------------------------------------------------------------------------
# The runtime wiring itself (P0-1), end to end
# ---------------------------------------------------------------------------


def test_runtime_reads_an_injected_physical_source_and_never_writes_to_it(
    tmp_path,
) -> None:
    """The whole of P0-1 in one cell, against a real RobotRuntime."""

    from parcel_robot.control.adapters import BackendVelocityController
    from parcel_robot.control.manager import ControlManager
    from parcel_robot.runtime import RobotRuntime

    vendor = _unitree_source(time.monotonic)
    physical = CommissionedStateSource(
        vendor, origin=EvidenceOrigin.PHYSICAL, session_epoch="boot-1"
    )
    backend = _W0ABackend()
    manager = ControlManager(BackendVelocityController(backend), physical)

    runtime = RobotRuntime(
        _w0a_config(tmp_path),
        backend,
        audio_status=_silent_audio(),
        control_manager=manager,
    )
    try:
        # RETAINED for reading — the retired isinstance discarded exactly this.
        assert runtime._control_state_source is physical
        # ... and NOT retained as a write seam.
        assert runtime._observation_sink is None
        assert runtime.input_health_latch()["state_source_origin"] == "physical"
        # A physical deployment does not get the fixture allowance.
        assert runtime._sim_fixture_inputs_allowed is False

        _feed(vendor, _FakeSportModeState())
        assert runtime._control_state_source.latest() is not None

        # The feedback channel now really reads the physical datum.
        verdict = runtime._evaluate_dispatch_input_health(
            backend.observe(), now=time.monotonic()
        )
        feedback_faults = [
            fault
            for fault in verdict.faults
            if fault.required_input is RequiredInput.CONTROLLER_FEEDBACK
        ]
        assert feedback_faults == []
    finally:
        runtime.close()
