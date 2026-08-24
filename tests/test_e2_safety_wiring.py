"""Lane E2 — the safety CONTRACT and the safety WIRING must agree.

Three wiring defects this module pins:

1. **P0-B latches.** ``HealthAction.LATCHED_STOP`` is a *latch*: a single
   recovered tick must not silently re-authorize translation. Only an explicit
   operator acknowledgement clears it, and the acknowledgement is refused while
   the fault is still live.
2. **Simulated inputs are labeled.** POSE and CONTROLLER_FEEDBACK are stamped
   from their producer exactly like SCAN, so a stub pose cannot satisfy a
   physical-sensor requirement. Under a physically commissioned deployment the
   same evidence is a ``LATCHED_STOP``.
3. **The person-clearance guard is symmetric with the obstacle guard**, and the
   product path (runtime-constructed policy, not just the bare dataclass)
   actually carries the derived social floor.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.authority import DEFAULT_SAFETY_ENVELOPE
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.core.hard_stop import ZERO_COMMAND
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
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.navigation.reactive_safety import (
    ReactiveSafetyPolicy,
    scan_evidence_from_observation,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]

ROBOT_CONFIGS = (
    REPO / "configs" / "robot.yaml",
    REPO / "configs" / "robot.acoustic.yaml",
    REPO / "src" / "parcel_robot" / "config" / "robot.yaml",
    REPO / "src" / "parcel_robot" / "runtime_assets" / "configs" / "robot.yaml",
)

BACKEND_NAME = "e2-safety-wiring"


class _Backend:
    name = BACKEND_NAME

    def observe(self) -> SimObservation:
        return _observation()

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del transcript, tools, context
        return AgentDecision("no planning in this test")


def _observation(*, timestamp: float | None = None) -> SimObservation:
    return SimObservation(
        timestamp=time.monotonic() if timestamp is None else timestamp,
        robot=RobotPose(),
        owner=OwnerTrack(),
        nearest_obstacle_m=10.0,
        nearest_obstacle_bearing_rad=0.0,
        backend=BACKEND_NAME,
    )


def _runtime(tmp_path: Path, *, extra: str = "") -> RobotRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "e2-safety.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
  shaping:
    enabled: true
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
poses: {{}}
modules: []
{extra}""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="test",
        ),
    )


def _seed(runtime: RobotRuntime, observation: SimObservation) -> SimObservation:
    with runtime._lock:
        runtime._observation = observation
    # Card W0-A amendment: writing simulator observations is the
    # ObservationSink seam, not the read-only RobotStateSource seam.
    if runtime._observation_sink is not None:
        runtime._observation_sink.update_observation(observation)
    return observation


# ---------------------------------------------------------------------------
# 1 — P0-B actually latches
# ---------------------------------------------------------------------------


def test_latched_stop_survives_a_single_tick_recovery(tmp_path: Path) -> None:
    """The defect: ``= bool(health.stop_latched)`` auto-cleared on recovery."""

    runtime = _runtime(tmp_path)
    try:
        now = time.monotonic()
        # Future-dated evidence is a LATCHED_STOP (not a recoverable HOLD).
        ahead = now + 5.0
        faulted = _seed(runtime, _observation(timestamp=ahead))
        runtime._collision_safe(VelocityCommand(vx=0.4), faulted, now=now)
        assert runtime._input_health_latched is True
        assert runtime.input_health_latch()["faults"] == [
            "pose:timestamp_in_future",
            "scan:timestamp_in_future",
            "controller_feedback:timestamp_in_future",
        ]

        # One tick later the input has recovered and the JOIN says ALLOW ...
        assert runtime._evaluate_dispatch_input_health(
            faulted, now=ahead
        ).action is HealthAction.ALLOW
        # ... and the latch must still forbid translation.
        gated, state = runtime._collision_safe(
            VelocityCommand(vx=0.4), faulted, now=ahead
        )
        assert runtime._input_health_latched is True
        assert gated.vx == 0.0
        assert gated.vy == 0.0
        assert state == "stopped"
        assert (
            runtime._finalize_for_actuator(
                VelocityCommand(vx=0.4),
                gated_command=gated,
                proximity_state=state,
                active=None,
                now=ahead,
            )
            == ZERO_COMMAND
        )
    finally:
        runtime.close()


def test_latch_clear_is_refused_while_the_fault_is_still_live(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        now = time.monotonic()
        faulted = _seed(runtime, _observation(timestamp=now + 5.0))
        runtime._collision_safe(VelocityCommand(vx=0.4), faulted, now=now)
        assert runtime._input_health_latched is True

        message = runtime.clear_input_health_latch(now=now)
        assert message.startswith("input health still latched")
        assert runtime._input_health_latched is True
    finally:
        runtime.close()


def test_operator_acknowledgement_is_the_only_clear(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    try:
        now = time.monotonic()
        ahead = now + 5.0
        faulted = _seed(runtime, _observation(timestamp=ahead))
        runtime._collision_safe(VelocityCommand(vx=0.4), faulted, now=now)

        assert runtime.clear_input_health_latch(now=ahead) == "Input health latch cleared"
        assert runtime._input_health_latched is False
        assert runtime.input_health_latch()["faults"] == []
        assert runtime.clear_input_health_latch(now=ahead) == "input health not latched"

        gated, state = runtime._collision_safe(
            VelocityCommand(vx=0.4), faulted, now=ahead
        )
        assert gated.vx == pytest.approx(0.4)
        assert state == "clear"
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# 2 — simulated inputs are labeled fixtures, not "physical"
# ---------------------------------------------------------------------------


def test_simulated_pose_and_feedback_carry_a_labeled_sim_fixture_origin(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    try:
        observation = _seed(runtime, _observation())
        for sample in (
            evidence_origin(observation.backend),
            evidence_origin(runtime._control_state_source.latest().source),
        ):
            origin, label = sample
            assert origin is EvidenceOrigin.SIMULATION
            assert isinstance(label, str) and label.strip()
        scan = scan_evidence_from_observation(observation)
        assert scan is not None and scan.origin is EvidenceOrigin.SIMULATION
        assert runtime.input_health_latch()["sim_fixture_inputs_allowed"] is True
        # Card W0-A: the retained source is declared, not name-inferred.
        assert runtime.input_health_latch()["state_source_origin"] == "simulation"
    finally:
        runtime.close()


def test_simulated_pose_latches_under_physical_commissioning(tmp_path: Path) -> None:
    """The labeled-fixture path is the ONLY way a stub pose is accepted."""

    runtime = _runtime(tmp_path, extra="safety:\n  require_physical_inputs: true\n")
    try:
        observation = _seed(runtime, _observation())
        assert runtime.input_health_latch()["sim_fixture_inputs_allowed"] is False
        # Card W0-A / board D-2 amendment: this used to be
        # ``is DEFAULT_REQUIRED_INPUTS``, and that WAS the gap — the default
        # table is the simulator one and still admits fixture SCAN geometry, so
        # a physically commissioned deployment was accepting stub geometry and
        # relying on POSE/FEEDBACK to dominate the join. The physical table
        # withdraws every fixture allowance, SCAN included.
        assert runtime._input_health_requirements == requirements_requiring_physical_inputs()
        assert all(
            spec.sim_fixture_allowed is False
            for spec in runtime._input_health_requirements.values()
        )
        verdict = runtime._evaluate_dispatch_input_health(
            observation, now=time.monotonic()
        )
        assert verdict.action is HealthAction.LATCHED_STOP
        reasons = {
            fault.reason for fault in verdict.faults if fault.action is HealthAction.LATCHED_STOP
        }
        assert reasons == {"sim_fixture_forbidden"}
        # SCAN now joins them: stub geometry is refused on its own account.
        assert {fault.required_input for fault in verdict.faults} == {
            RequiredInput.POSE,
            RequiredInput.SCAN,
            RequiredInput.CONTROLLER_FEEDBACK,
        }
    finally:
        runtime.close()


def test_unlabeled_sim_fixture_pose_latches_even_where_fixtures_are_allowed() -> None:
    now = 100.0
    evidence = {
        RequiredInput.POSE: InputEvidence(
            captured_at=now,
            frame_id="odom",
            payload_valid=True,
            origin=EvidenceOrigin.SIMULATION,
            fixture_label="   ",
        ),
    }
    verdict = evaluate_input_health(
        evidence,
        now=now,
        requirements={
            RequiredInput.POSE: requirements_allowing_sim_fixtures()[RequiredInput.POSE]
        },
    )
    assert verdict.action is HealthAction.LATCHED_STOP
    assert verdict.faults[0].reason == "sim_fixture_unlabeled"


def test_requirements_allowing_sim_fixtures_only_relaxes_the_producer() -> None:
    relaxed = requirements_allowing_sim_fixtures()
    for required_input, spec in DEFAULT_REQUIRED_INPUTS.items():
        assert relaxed[required_input].frame_id == spec.frame_id
        assert relaxed[required_input].max_age_s == spec.max_age_s
        assert relaxed[required_input].sim_fixture_allowed is True
    # The default table is untouched: pose/feedback still forbid fixtures.
    assert DEFAULT_REQUIRED_INPUTS[RequiredInput.POSE].sim_fixture_allowed is False
    assert (
        DEFAULT_REQUIRED_INPUTS[RequiredInput.CONTROLLER_FEEDBACK].sim_fixture_allowed
        is False
    )


# ---------------------------------------------------------------------------
# 3 — person clearance: symmetric guard + the yaml reaching the convention
# ---------------------------------------------------------------------------


def test_the_person_floor_guard_is_now_symmetric_with_the_obstacle_guard() -> None:
    """The asymmetry is CLOSED (lane E5, owner-authorized 2026-08-10).

    This test used to pin the gap AS a gap (``person_stop_m=1.0`` accepted while
    ``obstacle_stop_m=0.5`` was rejected), with a note that it would flip in the
    same change that landed the bundle. This is that change: owner authorization
    2026-08-10, "1. person clearance. Implement your recommendation".

    Measured cost/benefit of turning the guard on, re-measured by E5 on this
    tree (``scrum/20260809/task_15/E5_PERSON_CLEARANCE_STATUS.md``):
    min_pedestrian_surface_m 0.357 -> 0.530 m and personal_space_time_total_s
    3.8 -> 2.3 s, hard collisions 0 throughout. FOLLOW_BENCH_V1 follow_success
    stays 9/9 because ``desired_distance_m`` was derived up to 1.85 m in the
    same change; leaving it at 1.6 m (inside the new 1.75 m keepout) was what
    cost 9/9 -> 6/9 in E2's measurement. Embodied behaviour is UNMOVED (997
    steps, clearance 0.883147); only its manifest sha moves, because the
    manifest SHA-locks ``configs/robot.yaml``.
    """

    # Card DOOR-1 (2026-08-22) did to the OBSTACLE half exactly what P1-E did to
    # the person half two paragraphs down: it moved WHERE this floor comes from.
    # It used to be the shipped ``SafetyEnvelope.obstacle_stop_floor_m`` (0.6 m),
    # which made the shipped envelope its own floor — and at 0.6 m the
    # DIRECTIONAL gate still refuses every corridor narrower than 1.10 m, so no
    # profile could commission a ring that fits through an interior doorway. It
    # is now ``OBSTACLE_STOP_FLOOR_M`` (0.41 m), the body's ISO/TS-15066 stopping
    # distance at the APPROACH regime. The guard is unchanged in kind — still a
    # refusal at construction, still naming ``obstacle_stop_m`` — so the probe
    # moves from the retired 0.5 to a value under the new floor.
    with pytest.raises(ValueError, match="obstacle_stop_m"):
        ReactiveSafetyPolicy(obstacle_stop_m=0.40)
    # ...and the prototype's indoor ring, which is the DOOR-1 deliverable, is
    # accepted where 0.5 used to be refused.
    assert ReactiveSafetyPolicy(obstacle_stop_m=0.45).obstacle_stop_m == pytest.approx(0.45)
    # Card P1-E (2026-08-22) moved WHERE this floor comes from: it used to be
    # the shipped social zone (1.2 m), which made the commissioning value its
    # own floor and made an indoor 0.7 m profile a refusal to boot; it is now
    # ``PERSON_SOCIAL_ZONE_FLOOR_M`` (0.68 m), the body's ISO/TS-15066 stopping
    # distance at cruise. The guard is unchanged in kind — still a refusal at
    # construction, still naming ``person_stop_m`` — so the probe moves from
    # the retired 1.0 to a value under the new floor.
    with pytest.raises(ValueError, match="person_stop_m"):
        ReactiveSafetyPolicy(person_stop_m=0.6)
    # Commissioning STRICTER than the authority is still allowed, in both
    # families: the floor is a floor, not an equality.
    assert ReactiveSafetyPolicy(person_stop_m=1.4).person_stop_m == pytest.approx(1.4)
    # ...and commissioning LOOSER than the shipped 1.2 is now allowed too, down
    # to (and including) the floor. That is the P1-E deliverable.
    assert ReactiveSafetyPolicy(person_stop_m=0.7).person_stop_m == pytest.approx(0.7)
    assert ReactiveSafetyPolicy().person_stop_m == pytest.approx(
        DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)
    )


@pytest.mark.parametrize("path", ROBOT_CONFIGS, ids=lambda p: p.as_posix()[-44:])
def test_every_robot_config_copy_now_agrees_with_the_person_authority(
    path: Path,
) -> None:
    """All four copies carry the authority's 1.2/2.5, and a DERIVED keepout.

    The 1.0/2.0 disagreement was pre-existing since 2026-08-02 and pinned here
    as a disagreement until the owner authorized closing it (2026-08-10). The
    assertions are written against the authority, not against fresh literals,
    so the four copies still cannot fork from each other or from the envelope.

    ``owner_keepout_m`` is asserted as the SUM it must be, because that is
    exactly the ring ``apply_reactive_safety`` refuses to translate into: it is
    a derivation that happens to be written down, not an independent knob.
    """

    yaml = pytest.importorskip("yaml")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    safety = document["safety"]
    assert safety["person_stop_m"] == DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)
    assert safety["person_slow_m"] == DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m

    envelope_m = document["spatial_behaviors"]["owner_collision_envelope_m"]
    assert document["owner_follow"]["owner_keepout_m"] == pytest.approx(
        safety["person_stop_m"] + envelope_m
    )


def test_the_runtime_constructed_policy_reflects_the_yaml_not_a_hidden_literal(
    tmp_path: Path,
) -> None:
    """The RUNTIME-built policy, not the bare dataclass — where the gap was live.

    Three cells, and the middle one is the point of the whole lane:

    * no ``safety`` section -> the envelope derivation (1.2 / 2.5);
    * the SHIPPED ``configs/robot.yaml`` -> the same 1.2 / 2.5, read off disk,
      through the real ``RobotRuntime`` construction path;
    * a config that tries to inject the retired 1.0 -> **refused**, not
      silently honoured.
    """

    runtime = _runtime(tmp_path)
    try:
        assert runtime.reactive_safety_policy.person_stop_m == pytest.approx(
            DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)
        )
    finally:
        runtime.close()

    yaml = pytest.importorskip("yaml")
    shipped_safety = yaml.safe_load(
        (REPO / "configs" / "robot.yaml").read_text(encoding="utf-8")
    )["safety"]
    shipped = _runtime(
        tmp_path / "shipped",
        extra=(
            "safety:\n"
            f"  person_stop_m: {shipped_safety['person_stop_m']}\n"
            f"  person_slow_m: {shipped_safety['person_slow_m']}\n"
        ),
    )
    try:
        assert shipped.reactive_safety_policy.person_stop_m == pytest.approx(
            DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)
        )
        assert shipped.reactive_safety_policy.person_slow_m == pytest.approx(
            DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m
        )
    finally:
        shipped.close()

    # Card P1-E: 1.0 is now a legal indoor commissioning (it clears the 0.68 m
    # floor), so the "refused" cell probes UNDER the floor instead. What is
    # being pinned is unchanged: a config cannot walk the person clearance down
    # without limit, and the limit is a refusal to construct.
    with pytest.raises(ValueError, match="person_stop_m"):
        _runtime(
            tmp_path / "undercut",
            extra="safety:\n  person_stop_m: 0.6\n  person_slow_m: 2.0\n",
        )


def test_no_hardcoded_one_metre_person_fallback_remains() -> None:
    """No construction path may restate the retired 1.0 m / 2.0 m clearance.

    Covers ``.get(..., 1.0)`` config fallbacks AND keyword defaults: E5 found
    two more sites after E2 fixed the first two (``brain/observations.py``'s
    ``person_stop_m: float = 1.0`` snapshot default, which decides
    ``collision_imminent`` for the language plane, and the FOLLOW_BENCH_V1
    runner's own copy of the runtime merge).
    """

    import re

    pattern = re.compile(
        r"person_stop_m\"?\s*[,:=]\s*(?:float\s*=\s*)?1\.0"
        r"|person_slow_m\"?\s*[,:=]\s*(?:float\s*=\s*)?2\.0"
    )
    for path in (
        REPO / "src" / "parcel_robot" / "runtime.py",
        REPO / "src" / "parcel_robot" / "simulation" / "headless_city.py",
        REPO / "src" / "parcel_robot" / "brain" / "observations.py",
        REPO / "src" / "parcel_robot" / "navigation" / "follow.py",
        REPO / "evals" / "companion_nav" / "runner.py",
    ):
        assert not pattern.search(path.read_text(encoding="utf-8")), path


def test_the_runtime_person_clearance_defaults_derive_from_the_envelope(
    tmp_path: Path,
) -> None:
    """A config with no ``safety`` section must still land on the envelope."""

    runtime = _runtime(tmp_path)
    try:
        assert "person_stop_m" not in runtime.store.section("safety")
        assert runtime.person_stop_m == DEFAULT_SAFETY_ENVELOPE.person_stop(0.0)
        assert runtime.person_slow_m == DEFAULT_SAFETY_ENVELOPE.person_comfort_band_m
    finally:
        runtime.close()
