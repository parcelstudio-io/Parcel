"""Card P0-D — the three navigation/perception unblocks, each seeded RED first.

``scrum/20260822/task_4/README.md``. Three mechanical defects, each diagnosed to
a line by a previous card and each blocking a whole class of measurement:

1. **MOVE1-D1, compounding gate attenuation.** ``_dispatch_active`` force-synced
   the velocity smoother to the *post*-gate command, so a constant reactive
   slow-scale ``s`` was re-applied to its own output every tick. Measured on the
   product path here: 0.02786 m/s delivered where one application of the same
   gate to the same policy gives 0.05909 m/s — a 2.12x speed loss that is not
   policy and not safety, just arithmetic.
2. **``ranking_margin`` identically 0.** The online map's background is one
   non-zero label strength among zeros, so median and MAD are both 0 and PG-3's
   robust z-score returns 0.0 for every query that map can ever ask.
3. **``set_query`` dropped ``person``.** A navigation directive REPLACED the
   detector batch with its goal noun, taking the PG-1 safety lease with it.

Each defect gets its measured before-number as well as its after-number, because
"it is fixed" without the number it was fixed from is not a measurement.
"""

from __future__ import annotations

import time as real_time
from pathlib import Path

import pytest
import yaml

from parcel_robot import runtime as runtime_module
from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.camera_channel.ingress import SAFETY_LEASE_QUERY, CameraIngress
from parcel_robot.core.velocity_smoother import VelocitySmoother
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.navigation.reactive_safety import apply_reactive_safety
from parcel_robot.online_map.entries import MapObservation, WriterProvenance
from parcel_robot.online_map.online_map import OnlineSemanticMap
from parcel_robot.perception.abstention import (
    DEFAULT_SIGNALS,
    RANKING_MARGIN_LABEL_STRENGTH,
    RANKING_MARGIN_ROBUST_Z,
    STRAY_LABEL_STRENGTH,
    AbstentionPolicy,
    label_strength_margin,
    ranking_margin,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]

DEFAULT_NAV_CONFIG = REPO / "configs" / "navigation" / "default.yaml"
PROTOTYPE_NAV_CONFIG = REPO / "configs" / "navigation" / "prototype.yaml"


# ==========================================================================
# Defect 1 — MOVE1-D1, the compounding gate attenuation
# ==========================================================================
#
# The numbers below are the ones the arithmetic fixes, not round targets:
#
#   linear_accel 0.9 m/s^2, dt 0.1 s  ->  the ramp climbs 0.09 m/s per tick
#   obstacle at 0.78 m, stop 0.65 m, slow 1.2 m  ->  gate scale s = 0.23636
#   policy target 0.25 m/s
#
#   compounding fixed point   v = s*a*dt/(1-s) = 0.02786 m/s
#   one application           v = s*0.25       = 0.05909 m/s
#
# MOVE-1's D6 discriminator was "below 0.9x a single application on >= 50 % of
# slowing ticks"; it CONFIRMED at 100 % of 255 ticks. This test is that
# discriminator, inverted into a requirement.

POLICY_TARGET_VX = 0.25
SLOW_BAND_OBSTACLE_M = 0.78
TICK_DT_S = 0.1


class _Clock:
    """A monotonic clock the test owns, installed as ``runtime.time``.

    ``_dispatch_active`` reads ``time.monotonic()`` itself, so a real-time loop
    would tick at dt ~ 1e-5 s and no ramp would move at all — the defect would
    be invisible for the wrong reason. Replacing the module-global name inside
    ``parcel_robot.runtime`` (and nowhere else) gives the dispatch tick a real
    100 ms without touching any other module's clock.
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.value = float(start)

    def monotonic(self) -> float:
        return self.value

    def monotonic_ns(self) -> int:
        return int(self.value * 1e9)

    def sleep(self, seconds: float) -> None:  # pragma: no cover - never slept in test
        del seconds

    def __getattr__(self, name: str):
        return getattr(real_time, name)


class _Backend:
    name = "p0d-dispatch"

    def __init__(self) -> None:
        self.commands: list[VelocityCommand] = []

    def observe(self) -> None:
        return None

    def move(self, command: VelocityCommand) -> None:
        self.commands.append(command)

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


def _dispatch_runtime(tmp_path: Path) -> RobotRuntime:
    """A real ``RobotRuntime`` on the product dispatch path, shaping OFF.

    Shaping off isolates the smoother/gate arithmetic: the actuator shaper is
    itself dt-limited and would otherwise be a second ramp in the measurement.
    """

    path = tmp_path / "p0d-dispatch.yaml"
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
    enabled: false
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
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


def _slow_band_observation(clock: _Clock) -> SimObservation:
    return SimObservation(
        timestamp=clock.value,
        robot=RobotPose(),
        owner=OwnerTrack(visible=False),
        nearest_obstacle_m=SLOW_BAND_OBSTACLE_M,
        nearest_obstacle_bearing_rad=0.0,
        backend="p0d-dispatch",
    )


def test_MOVE1_D1_a_constant_gate_scale_is_applied_once_per_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The product dispatch path, 60 ticks, one obstacle that never moves.

    SEED-RED (shipped code, ``velocity_smoother.force(post-gate)``):
    delivered 0.0278571 m/s against a single application of 0.0590909 m/s —
    ratio 0.471, i.e. MOVE-1's D6 confirmed on this bench too.
    """

    clock = _Clock()
    monkeypatch.setattr(runtime_module, "time", clock)
    runtime = _dispatch_runtime(tmp_path)
    try:
        for _ in range(60):
            clock.value += TICK_DT_S
            observation = _slow_band_observation(clock)
            runtime._observation = observation
            runtime.submit_motion(
                "voice", VelocityCommand(vx=POLICY_TARGET_VX), ttl=5.0
            )
            runtime._dispatch_active()

        assert runtime._proximity_state == "slowing", (
            "the bench must sit in the SLOW band; a stop measures nothing here"
        )
        delivered = runtime._last_sent.vx

        # What the gate does to the policy value in ONE application. Same gate,
        # same policy, same observation — the only difference is that nothing
        # ramped first, which is exactly the counterfactual MOVE-1 named.
        single, state = apply_reactive_safety(
            VelocityCommand(vx=POLICY_TARGET_VX),
            _slow_band_observation(clock),
            policy=runtime.reactive_safety_policy,
            now=clock.value,
        )
        assert state == "slowing"

        assert delivered == pytest.approx(single.vx, rel=1e-9), (
            f"the gate scale must land once: delivered {delivered!r} vs one "
            f"application {single.vx!r}"
        )
        # MOVE-1's D6 discriminator, inverted into the requirement.
        assert delivered >= 0.9 * single.vx
    finally:
        runtime.close()


def test_the_old_post_gate_force_is_the_compounding_mechanism() -> None:
    """Characterisation of the defect, so the fix has something to be a fix OF.

    ``force`` is not wrong — it is the right call for a STOP. Feeding it a
    merely *scaled* command is what compounds, and this is that geometric decay
    in nine lines with no runtime attached.
    """

    scale = 0.23636363636363636
    smoother = VelocitySmoother(linear_accel=0.9, linear_decel=1.4, yaw_accel=1.8)
    now = 0.0
    delivered = 0.0
    for _ in range(60):
        now += TICK_DT_S
        ramped = smoother.step(VelocityCommand(vx=POLICY_TARGET_VX), now=now)
        gated = VelocityCommand(vx=ramped.vx * scale)
        smoother.force(gated, now=now)
        delivered = gated.vx

    single_application = POLICY_TARGET_VX * scale
    fixed_point = scale * 0.9 * TICK_DT_S / (1.0 - scale)
    assert delivered == pytest.approx(fixed_point, rel=1e-6)
    assert delivered < 0.9 * single_application
    assert single_application / delivered == pytest.approx(2.12, abs=0.01)


def test_sync_after_gate_keeps_the_pre_gate_ramp_but_collapses_a_zeroed_axis() -> None:
    """The two halves of the fix, in one tick each.

    A scaled axis keeps the ramp (so the scale lands once); a zeroed axis
    collapses it (so a stop is still a stop and the next tick re-accelerates
    from rest, byte-identically to ``force``).
    """

    scale = 0.25
    smoother = VelocitySmoother(linear_accel=0.9, linear_decel=1.4, yaw_accel=1.8)
    now = 0.0
    for _ in range(60):
        now += TICK_DT_S
        ramped = smoother.step(VelocityCommand(vx=POLICY_TARGET_VX), now=now)
        smoother.sync_after_gate(VelocityCommand(vx=ramped.vx * scale), now=now)
    assert ramped.vx == pytest.approx(POLICY_TARGET_VX, rel=1e-9)
    assert ramped.vx * scale == pytest.approx(POLICY_TARGET_VX * scale, rel=1e-9)

    # A gate that ZEROED the axis collapses the ramp, exactly as force did.
    # This is the rotate-in-place brake in ``_dispatch_active``: translation is
    # zeroed and the ramped yaw is passed through untouched, so the two calls
    # must be indistinguishable — now and on the tick after.
    forced = VelocitySmoother(linear_accel=0.9, linear_decel=1.4, yaw_accel=1.8)
    synced = VelocitySmoother(linear_accel=0.9, linear_decel=1.4, yaw_accel=1.8)
    for smoother_ in (forced, synced):
        ramped = smoother_.step(VelocityCommand(vx=POLICY_TARGET_VX, vyaw=0.4), now=0.1)
    braked = VelocityCommand(vyaw=ramped.vyaw)
    forced.force(braked, now=0.1)
    synced.sync_after_gate(braked, now=0.1)
    assert forced.step(VelocityCommand(vx=POLICY_TARGET_VX), now=0.2) == synced.step(
        VelocityCommand(vx=POLICY_TARGET_VX), now=0.2
    )

    # And a FULL stop is the same on both, which is the case the reactive gate
    # takes when the obstacle is inside the stop band.
    stopped_force = VelocitySmoother(linear_accel=0.9, linear_decel=1.4, yaw_accel=1.8)
    stopped_sync = VelocitySmoother(linear_accel=0.9, linear_decel=1.4, yaw_accel=1.8)
    for smoother_ in (stopped_force, stopped_sync):
        smoother_.step(VelocityCommand(vx=POLICY_TARGET_VX, vyaw=0.4), now=0.1)
    stopped_force.force(VelocityCommand(), now=0.1)
    stopped_sync.sync_after_gate(VelocityCommand(), now=0.1)
    assert stopped_force.step(
        VelocityCommand(vx=POLICY_TARGET_VX), now=0.2
    ) == stopped_sync.step(VelocityCommand(vx=POLICY_TARGET_VX), now=0.2)


def test_a_stop_still_stops_and_the_ramp_restarts_from_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loosening must not reach the stop band. Same bench, obstacle inside
    ``obstacle_stop_m``: every delivered command is exact zero translation."""

    clock = _Clock()
    monkeypatch.setattr(runtime_module, "time", clock)
    runtime = _dispatch_runtime(tmp_path)
    try:
        for _ in range(20):
            clock.value += TICK_DT_S
            runtime._observation = SimObservation(
                timestamp=clock.value,
                robot=RobotPose(),
                owner=OwnerTrack(visible=False),
                nearest_obstacle_m=0.30,
                nearest_obstacle_bearing_rad=0.0,
                backend="p0d-dispatch",
            )
            runtime.submit_motion(
                "voice", VelocityCommand(vx=POLICY_TARGET_VX), ttl=5.0
            )
            runtime._dispatch_active()
            assert runtime._last_sent.vx == 0.0
            assert runtime._last_sent.vy == 0.0
        assert runtime._proximity_state == "stopped"
        # And the ramp is genuinely at rest, not holding a pre-gate value.
        assert runtime.velocity_smoother._current.vx == 0.0
    finally:
        runtime.close()


# ==========================================================================
# Defect 2 — a ranking margin that can be non-zero
# ==========================================================================

PROV = WriterProvenance(
    session_id="p0d-test",
    seat="in_loop_query",
    detector_name="owlv2-b16-int8",
    scene_id="city_block",
)

#: The C-3 shadow corpus's two halves. Present: seeded into the map below.
#: Absent: corpus rows 10-12 plus the two classes the PG-3 bench measured the
#: label head refusing. An admission on any of these is an ``admission_flip``.
PRESENT_QUERIES = ("lamppost", "tree")
ABSENT_QUERIES = (
    "fire hydrant",
    "Narnia",
    "my office",
    "the moon",
    "a coffee shop",
)


def _map_observation(
    label: str, *, x: float, y: float, w: float, h: float, frame_id: str
) -> MapObservation:
    return MapObservation(
        label=label,
        score=0.4,
        surface_x=x,
        surface_y=y,
        surface_z=1.2,
        range_m=4.0,
        bearing_rad=0.0,
        depth_m=4.0,
        extent_w_m=w,
        extent_h_m=h,
        inlier_pixels=800,
        frame_id=frame_id,
        visit_id="v0",
        observed_wall_s=100.0,
        robot_x=0.0,
        robot_y=0.0,
        provenance=PROV,
    )


def _seeded_map(policy: AbstentionPolicy) -> OnlineSemanticMap:
    """C-2's own two-place fixture: eight frames, one lamppost, one tree."""

    m = OnlineSemanticMap(provenance=PROV, policy=policy)
    for i in range(8):
        m.note_frame(("lamppost", "tree"))
        m.note_pose(0.5 * i, 0.0)
        m.observe(
            _map_observation("lamppost", x=3.0, y=1.0, w=0.2, h=3.0, frame_id=f"a{i}")
        )
        m.observe(
            _map_observation("tree", x=-4.0, y=2.0, w=1.5, h=5.0, frame_id=f"b{i}")
        )
    return m


def _prototype_policy() -> AbstentionPolicy:
    data = yaml.safe_load(PROTOTYPE_NAV_CONFIG.read_text(encoding="utf-8"))
    return AbstentionPolicy.from_mapping(data["perception"]["abstention"])


def _evidence_roster_policy(**overrides: object) -> AbstentionPolicy:
    """The prototype profile with P1-D's VLM veto taken back out.

    P0-D's acceptance is about the EVIDENCE roster — label support, evidence
    count, ranking margin — and specifically that a label-strength margin makes
    it satisfiable where the robust z could not be. Card P1-D later added a
    fourth signal to the same profile, ``vlm_veto``, which needs a model on the
    host: with no seat installed it answers ``unavailable``, which the gate
    reads as ASK, so every one of these admissions would become a question and
    this file would be measuring P1-D's wiring instead of P0-D's estimator.

    Naming the three signals HERE rather than inheriting whatever the profile
    currently lists is the stronger arrangement: it stops this file drifting
    silently every time another card edits the overlay, and it keeps each
    card's acceptance measuring its own change. P1-D's own row 1 measures the
    full four-signal roster with a real verifier.
    """

    import dataclasses

    prototype = _prototype_policy()
    signals = tuple(s for s in prototype.signals if s != "vlm_veto")
    return dataclasses.replace(prototype, signals=signals, **overrides)


def test_the_shipped_robust_z_is_structurally_zero_on_the_maps_own_background() -> None:
    """The defect, as arithmetic. Not a tuning miss — a structural zero.

    One non-zero score among zeros has median 0 and MAD 0, and the guard that
    was written for "a degenerate map" fires on every healthy one.
    """

    assert ranking_margin([2.909294, 0.0, 0.0, 0.0]) == 0.0
    assert ranking_margin([8.2, 0.0, 0.0, 0.0, 0.0, 0.0]) == 0.0
    # Two entries is also below the estimator's three-value floor.
    assert ranking_margin([2.909294, 0.0]) == 0.0


def test_label_strength_margin_separates_a_corroborated_place_from_a_stray() -> None:
    """The 2026-08-21 bench's separation, as a gate. PROVISIONAL numbers."""

    # A lone corroborated entry is decisive; a lone stray is exactly at the
    # floor, so any threshold above 1.0 refuses it.
    assert label_strength_margin([2.909294, 0.0, 0.0]) == pytest.approx(
        2.909294 / STRAY_LABEL_STRENGTH
    )
    assert label_strength_margin([STRAY_LABEL_STRENGTH, 0.0, 0.0]) == 1.0
    # With two matching candidates the runner-up is the alternative.
    assert label_strength_margin([8.2, 2.8, 0.0]) == pytest.approx(8.2 / 2.8)
    assert label_strength_margin([3.2, 2.8]) == pytest.approx(3.2 / 2.8)
    # No match at all is not a decisive match.
    assert label_strength_margin([0.0, 0.0, 0.0]) == 0.0
    assert label_strength_margin([]) == 0.0


@pytest.mark.parametrize(
    ("mode", "expected_admissions"),
    [
        (RANKING_MARGIN_ROBUST_Z, 0),
        (RANKING_MARGIN_LABEL_STRENGTH, len(PRESENT_QUERIES)),
    ],
)
def test_the_prototype_signal_set_admits_what_the_map_saw_and_nothing_else(
    mode: str, expected_admissions: int
) -> None:
    """The card's acceptance, with the seed-RED arm kept in the suite.

    SEED-RED (``robust_z``, the shipped estimator): 0 of 2 present queries
    admitted; ``lamppost`` refused ``indecisive_ranking`` with
    ``ranking_margin 0.0`` and ``background_mad 0.0``.
    GREEN (``label_strength``): 2 of 2 admitted at margin 24.244, and
    ``admission_flip`` still 0 across all five absent queries.
    """

    policy = _evidence_roster_policy(ranking_margin_mode=mode)
    m = _seeded_map(policy)

    admitted = [q for q in PRESENT_QUERIES if m.resolve(q).admitted]
    assert len(admitted) == expected_admissions

    # The hard half, and it holds under BOTH estimators: nothing the robot
    # never saw is ever admitted. This is C-3's `admission_flip`, and 0 is the
    # only acceptable count.
    flips = [q for q in ABSENT_QUERIES if m.resolve(q).admitted]
    assert flips == []

    if mode == RANKING_MARGIN_ROBUST_Z:
        refusal = m.resolve("lamppost")
        assert refusal.verdict.reason == "indecisive_ranking"
        assert refusal.verdict.signals["ranking_margin"] == 0.0
        assert refusal.diagnostics["background_mad"] == 0.0
    else:
        grounded = m.resolve("lamppost")
        assert grounded.verdict.reason == "grounded"
        assert grounded.verdict.signals["ranking_margin"] > 1.0


@pytest.mark.parametrize(
    ("mode", "expected_admissions"),
    [
        (RANKING_MARGIN_ROBUST_Z, 0),
        (RANKING_MARGIN_LABEL_STRENGTH, 2),
    ],
)
def test_the_c3_mission_path_admits_under_the_prototype_signal_set(
    mode: str, expected_admissions: int
) -> None:
    """The same acceptance, on the MISSION path rather than the map's API.

    ``ObservationSemanticMap.query`` -> ``_abstention_filtered`` is what a
    directive actually traverses under ``semantic_source: learned_map``, and it
    reaches the gate with a different background: ``evidence_confidence`` per
    candidate, not C-2's label strength.

    SEED-RED (``robust_z``): 0 of 2 present queries admitted, both
    ``indecisive_ranking`` at margin 0.0.
    SEED-RED (``label_strength`` with the WHOLE-map background, i.e. before the
    ``_abstention_filtered`` half of the fix): also 0 of 2, both
    ``indecisive_ranking`` at margin exactly 1.0 — the two fixture places tie at
    0.8647, so the ratio is 1.0 and no threshold above it can pass.
    GREEN: 2 of 2 admitted at margin 7.2055, absent queries unchanged.
    """


    from test_c3_cutover import _FakeEntry, _FakeMap, _observation

    from parcel_robot.navigation.base import NavObservation
    from parcel_robot.navigation.goals import SemanticGoal
    from parcel_robot.navigation.semantic_map import (
        ObservationSemanticMap,
        semantic_candidates_from_observation,
    )
    from parcel_robot.perception_source.selection import (
        SOURCE_LEARNED_MAP,
        SemanticSourcePolicy,
        use_learned_map,
        use_semantic_source,
    )

    policy = _evidence_roster_policy(ranking_margin_mode=mode)
    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    use_learned_map(
        _FakeMap(
            [
                _FakeEntry("e1", "bench", 3.0, 0.0, names=("bench",)),
                _FakeEntry("e2", "lamppost", 5.0, 1.0, names=("lamppost",)),
            ]
        )
    )
    try:
        rows = semantic_candidates_from_observation(_observation())
        semantic_map = ObservationSemanticMap(abstention=policy)

        def ask(query: str) -> tuple[int, dict]:
            nav = NavObservation(
                position=(0.0, 0.0, 0.0),
                extras={"semantic_candidates": rows, "detector_support": {}},
            )
            found = semantic_map.query(SemanticGoal(query=query, kind="object"), nav)
            return len(found), nav.extras.get("abstention_verdict", {})

        admitted = [q for q in ("bench", "lamppost") if ask(q)[0] == 1]
        assert len(admitted) == expected_admissions

        for query in ("Narnia", "my office", "the moon", "a coffee shop"):
            count, verdict = ask(query)
            assert count == 0, f"admission_flip on an absent query: {query}"
            assert verdict["reason"] == "no_observations"
    finally:
        use_semantic_source(None)
        use_learned_map(None)


def test_the_default_policy_is_pg3s_six_signals_and_pg3s_estimator() -> None:
    """Flag-off byte identity, as a construction property.

    The default policy must be the shipped one field for field, so a build that
    reads no config cannot notice this card.
    """

    policy = AbstentionPolicy()
    assert policy.enabled is False
    assert policy.signals == DEFAULT_SIGNALS
    assert policy.ranking_margin_mode == RANKING_MARGIN_ROBUST_Z
    assert AbstentionPolicy.from_mapping(None) == policy
    assert AbstentionPolicy.from_mapping({}) == policy
    default = yaml.safe_load(DEFAULT_NAV_CONFIG.read_text(encoding="utf-8"))
    from_default_yaml = AbstentionPolicy.from_mapping(
        default["perception"]["abstention"]
    )
    assert from_default_yaml.signals == DEFAULT_SIGNALS
    assert from_default_yaml.ranking_margin_mode == RANKING_MARGIN_ROBUST_Z


def test_an_unknown_signal_or_estimator_is_refused_not_defaulted() -> None:
    with pytest.raises(ValueError, match="unknown abstention signal"):
        AbstentionPolicy(signals=("label_support", "vibes"))
    with pytest.raises(ValueError, match="ranking_margin_mode"):
        AbstentionPolicy(ranking_margin_mode="cosine")
    with pytest.raises(TypeError, match="signals"):
        AbstentionPolicy(signals="label_support")
    with pytest.raises(ValueError, match="at least one signal"):
        AbstentionPolicy(enabled=True, signals=())
    with pytest.raises(ValueError, match="unknown perception.abstention key"):
        AbstentionPolicy.from_mapping({"signal": ["label_support"]})


def test_a_dropped_signal_relaxes_that_gate_and_only_that_gate() -> None:
    """Dropping ``navigability`` must not also drop ``evidence_count``.

    A signal set is not a master switch, and the way this would go wrong
    silently is by relaxing more than it says.
    """

    prototype = _evidence_roster_policy()
    m = _seeded_map(prototype)
    # `tree` in this fixture has ground_evidence_fraction 0.0 (the robot never
    # walked past it), which is what `not_navigable` refuses. Under the
    # prototype set that gate is off, so the tree admits...
    assert m.resolve("tree").admitted
    # ...but restoring the signal brings exactly that refusal back.
    with_navigability = AbstentionPolicy(
        enabled=True,
        min_evidence_frames=prototype.min_evidence_frames,
        min_ranking_margin=prototype.min_ranking_margin,
        signals=(*prototype.signals, "navigability"),
        ranking_margin_mode=prototype.ranking_margin_mode,
    )
    strict = _seeded_map(with_navigability)
    assert strict.resolve("tree").verdict.reason == "not_navigable"


def test_the_prototype_profile_is_default_yaml_with_one_block_changed() -> None:
    """The overlay is a copy, and a copy that drifts is a second config.

    ``default.yaml`` does not move (the frozen ``nav_instruct`` v4 baseline
    reads it), so the prototype profile is a whole file — and the only defence
    against it rotting is a test that says what may differ.
    """

    default = yaml.safe_load(DEFAULT_NAV_CONFIG.read_text(encoding="utf-8"))
    prototype = yaml.safe_load(PROTOTYPE_NAV_CONFIG.read_text(encoding="utf-8"))

    differences: list[str] = []
    missing = object()

    def walk(a: dict, b: dict, path: str = "") -> None:
        for key in sorted(set(a) | set(b)):
            here = f"{path}.{key}".lstrip(".")
            left, right = a.get(key, missing), b.get(key, missing)
            if isinstance(left, dict) and isinstance(right, dict):
                walk(left, right, here)
            elif left != right:
                differences.append(here)

    walk(default, prototype)
    assert set(differences) == {
        "perception.semantic_source",
        "perception.abstention.enabled",
        "perception.abstention.signals",
        "perception.abstention.ranking_margin_mode",
        "perception.abstention.min_evidence_frames",
        "perception.abstention.min_ranking_margin",
        # Card P1-D: the ASK posture, and the seat that answers the veto.
        # Added to this pin rather than the pin being loosened — the set is
        # still exhaustive and still says out loud exactly which keys the
        # prototype profile is allowed to move.
        "perception.abstention.ask_below_threshold",
        "perception.abstention.veto_model",
        # Card P1-B: the map-persistence + query-batch block. Same treatment —
        # ONE new path named here, the set stays exhaustive, and the block is
        # absent from default.yaml so the shipped file has not moved. The
        # runtime refuses unknown keys INSIDE it (``_p1b_map_settings``), so
        # this pin guards the block's existence and that one guards its shape.
        "perception.online_map",
    }
    assert prototype["perception"]["semantic_source"] == "learned_map"


# ==========================================================================
# Defect 3 — set_query unions instead of replacing
# ==========================================================================


class _StubDetector:
    def detect(self, *args, **kwargs):  # pragma: no cover - never polled here
        del args, kwargs
        return []


def test_a_directive_narrows_the_batch_and_can_never_drop_person() -> None:
    """SEED-RED (shipped code): ``('lamppost',)`` — ``person`` gone.

    ``set_query`` REPLACED the batch, so one navigation directive removed the
    query the PG-1 safety lease rides on and ``patrol/mission.py`` requires.
    """

    ingress = CameraIngress(backend=object(), detector=_StubDetector())
    ingress.pinned_queries = ("person", "lamppost")
    ingress.set_query(("person", "lamppost"))
    assert ingress.stats.last_query == ("person", "lamppost")

    ingress.set_query("bench")
    assert SAFETY_LEASE_QUERY in ingress.stats.last_query
    assert ingress.stats.last_query == ("person", "lamppost", "bench")

    # Even with no pinned batch at all, a directive cannot produce a batch that
    # never asks about people.
    bare = CameraIngress(backend=object(), detector=_StubDetector())
    bare.set_query("bench")
    assert bare.stats.last_query == ("person", "bench")


def test_the_pin_is_satisfied_by_any_phrase_naming_the_whole_word_person() -> None:
    """``camera_ingress_queries: ["a person", ...]`` is a valid C-1 batch and
    must not grow a second, redundant ``person`` prompt."""

    ingress = CameraIngress(backend=object(), detector=_StubDetector())
    ingress.pinned_queries = ("a person", "lamppost")
    ingress.set_query(("a person", "lamppost"))
    assert ingress.stats.last_query == ("a person", "lamppost")
    ingress.set_query("bench")
    assert ingress.stats.last_query == ("a person", "lamppost", "bench")
    # "personnel" is not "person" — the C-1 config check spells this out and the
    # pin has to agree with it or the two guards disagree about the same word.
    other = CameraIngress(backend=object(), detector=_StubDetector())
    other.set_query("personnel carrier")
    assert other.stats.last_query == ("person", "personnel carrier")


def test_clearing_the_query_still_turns_the_eye_off() -> None:
    """The pin protects a NARROWING, not the off switch.

    ``clear_query`` is an operator stopping the camera, and a pinned ``person``
    that survived it would leave the detector running forever.
    """

    ingress = CameraIngress(backend=object(), detector=_StubDetector())
    ingress.pinned_queries = ("person", "lamppost")
    ingress.set_query("bench")
    assert ingress.has_query
    ingress.clear_query()
    assert ingress.stats.last_query == ()
    assert not ingress.has_query
    ingress.set_query([])
    assert ingress.stats.last_query == ()


class _Harness:
    """``RobotRuntime._set_camera_query_from_directive``, bound to nothing else.

    The SHIPPED method, not a re-implementation of it: everything it reads is a
    plain attribute, so the two the defect lives between — the configured batch
    and the attached ingress — are the whole fixture.
    """

    def __init__(self, ingress, queries: list[str] | None) -> None:
        import threading

        self._lock = threading.RLock()
        self._camera_ingress = ingress
        self._camera_stream_config = (
            None
            if queries is None
            else runtime_module.CameraStreamConfig.from_section(
                {"camera_ingress": True, "camera_ingress_queries": queries}
            )
        )
        self.set_from_directive = RobotRuntime._set_camera_query_from_directive.__get__(
            self
        )


def test_the_directive_lane_re_supplies_the_configured_batch() -> None:
    """The runtime half of the same property, through a real ingress.

    SEED-RED (shipped code): after ``go to the bench`` the live batch was
    ``('bench',)`` — the configured ``camera_ingress_queries`` were gone and
    ``person`` with them.
    """

    ingress = CameraIngress(backend=object(), detector=_StubDetector())
    ingress.pinned_queries = ("person", "lamppost")
    harness = _Harness(ingress, ["person", "lamppost"])

    harness.set_from_directive("go to the bench")
    assert ingress.stats.last_query == ("person", "lamppost", "bench")

    # A second directive replaces the previous NOUN but never the batch.
    harness.set_from_directive("walk to the tree")
    assert ingress.stats.last_query == ("person", "lamppost", "tree")

    # A directive naming something already in the batch does not duplicate it.
    harness.set_from_directive("go to the lamppost")
    assert ingress.stats.last_query == ("person", "lamppost")

    # No configured batch at all still keeps the safety query.
    bare = CameraIngress(backend=object(), detector=_StubDetector())
    _Harness(bare, None).set_from_directive("walk to the tree")
    assert bare.stats.last_query == ("person", "tree")


def test_the_directive_lane_stays_a_no_op_without_an_ingress() -> None:
    _Harness(None, None).set_from_directive("go to the bench")  # must not raise

    ingress = CameraIngress(backend=object(), detector=_StubDetector())
    _Harness(ingress, ["person", "lamppost"]).set_from_directive("   ")
    assert ingress.stats.last_query == ()
