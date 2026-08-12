"""Card VS-1 — verify-on-approach state machine + per-kind refinement gate.

The five gate clauses of the card block
(``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md`` §6, "Card VS-1") are pinned
here, and only these are claimed:

1. checkpoint radii ``struct.pack``-identical to ``object_near_envelope_m``'s
   own outputs, and the view-admission angle ``struct.pack``-identical to
   ``2π / ScanPlanSpec.n_stops`` read off ``full_turn_scan_spec`` — plus an AST
   audit that the module states no geometry constant of its own;
2. the measured V-B phantom trace (constant bearing/range, no covariance
   shrink on closure) ends REFUTED and never VERIFIED, at every operating
   point in the envelope grid;
3. a covariance-trace increase, a persistence miss, or a failed identity
   re-check at any checkpoint is a veto verdict;
4. the per-kind refinement gate: the measured B-05 4.7785 m region
   displacement is a canned rejection, objects reject outside the vicinity
   band or Mahalanobis-inconsistent with the D2 covariance;
5. three consecutive same-pose ticks are ONE admissible view.

Three properties are stated as oracles and each is shown able to FAIL on a
seeded violation, so a green run is evidence rather than notation.

What these cells do NOT prove: real-camera persistence (the T0 arms' oracle
frustum never hallucinates), or anything about arrival. K0 is untouched by
this card; the module proposes verdicts and nothing else.
"""

from __future__ import annotations

import ast
import math
import pathlib
import random
import struct

import pytest

from parcel_robot.instructnav.scan import full_turn_scan_spec
from parcel_robot.instructnav.scoring import (
    ARRIVAL_BOUNDARY_EPSILON_M,
    INSIDE_PROBABILITY_THRESHOLD,
    NEXT_TO_BAND_M,
    TOWARDS_BAND_M,
    ApproachVerifyState,
    arrival_goal_region_for_relation,
    object_near_envelope_m,
)
from parcel_robot.navigation import lock_on_verify
from parcel_robot.navigation.lock_on_verify import (
    MAHALANOBIS_GATE_SIGMA,
    REGION_DILATION_M,
    VIEW_ADMISSION_SEPARATION_RAD,
    ApproachView,
    GroundedReference,
    LockOnVerifyConfig,
    LockOnVerifySession,
    ReferenceKind,
    admits_for_confirmation,
    arrival_band_outer_m,
    checkpoint_radii_m,
    refinement_gate,
    view_separation_rad,
)

#: The MEASURED B-05 false arrival (record §2.1(1)): the episode's grounded
#: sidewalk polygon is y ∈ [2.2, 4.2]; the committed south instance put the
#: fused/final point at (1.3480, −2.5785); dtg 4.778530810034543 is exactly
#: 2.2 − (−2.578530810034543).
B05_REGION_POLYGON = ((-6.0, 2.2), (6.0, 2.2), (6.0, 4.2), (-6.0, 4.2))
B05_WRONG_INSTANCE_XY = (1.3480, -2.578530810034543)
B05_DISPLACEMENT_M = 4.778530810034543

#: The operating points the phantom must be refuted at: one envelope per
#: reference kind the generator emits (bare object, lamppost point anchor,
#: tree, building).
OPERATING_POINTS = ((0.0, ""), (0.0, "lamppost"), (0.25, "tree"), (1.2, "building"))

TIGHT_COVARIANCE = ((0.04, 0.0), (0.0, 0.04))
#: Wide enough that the vicinity band, not the Mahalanobis clause, is the
#: binding constraint — used where the point under test is the band.
LOOSE_COVARIANCE = ((1.0, 0.0), (0.0, 1.0))


def _bits(value: float) -> bytes:
    return struct.pack("<d", float(value))


def _object_reference(radius_m: float = 0.25, label: str = "tree") -> GroundedReference:
    return GroundedReference(
        landmark_id="tree_2",
        kind=ReferenceKind.OBJECT,
        label=label,
        center=(10.0, 0.0),
        radius_m=radius_m,
    )


def _region_reference() -> GroundedReference:
    return GroundedReference(
        landmark_id="sidewalk_north",
        kind=ReferenceKind.REGION,
        label="sidewalk",
        polygon=B05_REGION_POLYGON,
    )


def _shrinking(step: int) -> tuple[tuple[float, float], tuple[float, float]]:
    """A covariance whose trace strictly decreases with each step."""

    sigma = 1.0 / float(step + 1)
    return ((sigma, 0.0), (0.0, sigma))


# --------------------------------------------------------------------------
# GATE 1 — derived constants, bit-identical, no local literals
# --------------------------------------------------------------------------


def test_checkpoint_radii_are_bit_identical_to_the_envelope() -> None:
    for radius, label in OPERATING_POINTS:
        envelope = object_near_envelope_m(radius, label=label)
        radii = checkpoint_radii_m(radius, label=label)
        assert [_bits(r) for r in radii] == [_bits(r) for r in sorted(set(envelope), reverse=True)]
        # Every checkpoint IS one of the envelope's own three numbers.
        for value in radii:
            assert any(_bits(value) == _bits(term) for term in envelope)
        # Outermost first, strictly decreasing, de-duplicated.
        assert list(radii) == sorted(radii, reverse=True)
        assert len(set(radii)) == len(radii)


def test_lamppost_branch_collapses_to_two_checkpoints() -> None:
    stand_off, minimum, vicinity = object_near_envelope_m(0.0, label="lamppost")
    assert _bits(stand_off) == _bits(vicinity)
    assert checkpoint_radii_m(0.0, label="lamppost") == (vicinity, minimum)


def test_view_admission_angle_is_the_scan_stop_separation_by_reference() -> None:
    spec = full_turn_scan_spec()
    assert spec.n_stops == 8
    expected = abs(spec.total_yaw_rad) / float(spec.n_stops)
    assert _bits(VIEW_ADMISSION_SEPARATION_RAD) == _bits(expected)
    assert _bits(VIEW_ADMISSION_SEPARATION_RAD) == _bits(2.0 * math.pi / 8.0)


def test_region_dilation_and_mahalanobis_gate_are_derived() -> None:
    assert _bits(REGION_DILATION_M) == _bits(ARRIVAL_BOUNDARY_EPSILON_M)
    expected = math.sqrt(-2.0 * math.log(1.0 - INSIDE_PROBABILITY_THRESHOLD))
    assert _bits(MAHALANOBIS_GATE_SIGMA) == _bits(expected)


def test_module_states_no_geometry_constant_of_its_own() -> None:
    """No-literal drift: a retune of any authority must move this module."""

    source = pathlib.Path(lock_on_verify.__file__).read_text(encoding="utf-8")
    # Dimension counts only: 0/1 are identity elements, 2 is the planar state
    # dimension (the chi-square DOF and the 2x2 covariance shape), 3 is the
    # minimum vertex count of a polygon. No metre, radian, or score lives here.
    allowed = {0, 1, 2, 3}
    offenders: list[float] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool):
                continue
            if float(node.value) not in allowed:
                offenders.append(float(node.value))
    assert offenders == [], f"undeclared numeric literals in lock_on_verify: {offenders}"


# --------------------------------------------------------------------------
# GATE 5 — self-confirmation killed at unit level
# --------------------------------------------------------------------------


def test_three_same_pose_ticks_are_one_admissible_view() -> None:
    reference = _object_reference()
    session = LockOnVerifySession(reference)
    view = ApproachView(
        robot_xy=(4.0, 0.0),
        fused_xy=(10.0, 0.0),
        covariance=TIGHT_COVARIANCE,
    )
    for _ in range(3):
        verdict = session.observe(view)
    assert session.confirming_views == 1
    assert session.fresh_views == 1
    assert verdict.reason == "view_not_independent"
    assert verdict.state is ApproachVerifyState.APPROACH


def test_admission_needs_a_whole_scan_arc_of_separation() -> None:
    fused = (0.0, 0.0)
    radius = 5.0
    first = ApproachView(robot_xy=(radius, 0.0), fused_xy=fused)
    quantum = VIEW_ADMISSION_SEPARATION_RAD
    just_short = ApproachView(
        robot_xy=(radius * math.cos(quantum * 0.99), radius * math.sin(quantum * 0.99)),
        fused_xy=fused,
    )
    just_over = ApproachView(
        robot_xy=(radius * math.cos(quantum), radius * math.sin(quantum)),
        fused_xy=fused,
    )
    assert not admits_for_confirmation(first, just_short)
    assert admits_for_confirmation(first, just_over)
    assert view_separation_rad(first, just_over) == pytest.approx(quantum)
    assert admits_for_confirmation(None, first)


# --------------------------------------------------------------------------
# GATE 2 — the measured V-B phantom
# --------------------------------------------------------------------------


def test_vb_constant_bearing_range_phantom_is_refuted_at_every_operating_point() -> None:
    """The phantom that walks with the robot: one view forever, then refuted."""

    for radius, label in OPERATING_POINTS:
        reference = _object_reference(radius_m=radius, label=label)
        session = LockOnVerifySession(reference)
        # The phantom starts ON the reference and then keeps a constant bearing
        # and a constant 3 m range as the body closes — the measured V-B
        # signature. Its aspect never moves and it never gets closer, so it can
        # never earn a second independent view.
        start_x = reference.center[0] - 3.0
        states = []
        for step in range(12):
            robot_x = start_x + 0.2 * step
            view = ApproachView(
                robot_xy=(robot_x, 0.0),
                fused_xy=(robot_x + 3.0, 0.0),
                covariance=LOOSE_COVARIANCE,
            )
            verdict = session.observe(view)
            states.append(verdict.state)
            if verdict.refuted:
                break
        assert ApproachVerifyState.VERIFIED not in states
        assert session.state is ApproachVerifyState.REJECTED
        assert session.confirming_views == 1
        assert session.negative_evidence() is not None


def test_view_consistent_phantom_without_covariance_shrink_is_refuted() -> None:
    """Stationary phantom inside the band: closure gives fresh views, no shrink."""

    for radius, label in OPERATING_POINTS:
        reference = _object_reference(radius_m=radius, label=label)
        session = LockOnVerifySession(reference)
        fused = (reference.center[0], reference.center[1])
        verdicts = []
        for step in range(24):
            robot_x = reference.center[0] - 8.0 + 0.4 * step
            verdicts.append(
                session.observe(
                    ApproachView(
                        robot_xy=(robot_x, 0.0),
                        fused_xy=fused,
                        covariance=TIGHT_COVARIANCE,
                    )
                )
            )
            if verdicts[-1].refuted:
                break
        assert not any(v.verified for v in verdicts)
        assert session.state is ApproachVerifyState.REJECTED
        assert verdicts[-1].reason == "covariance_did_not_shrink_at_checkpoint"
        assert verdicts[-1].veto


# --------------------------------------------------------------------------
# GATE 3 — checkpoint demands
# --------------------------------------------------------------------------


def _approach_views(
    reference: GroundedReference,
    *,
    steps: int = 24,
    start_offset_m: float = 8.0,
    trace: str = "shrinking",
    persistence_miss_step: int | None = None,
    identity_score: float | None = None,
) -> list[ApproachView]:
    views: list[ApproachView] = []
    for step in range(steps):
        robot_x = reference.center[0] - start_offset_m + 0.4 * step
        if trace == "shrinking":
            covariance = _shrinking(step)
        elif trace == "growing":
            sigma = 0.1 * float(step + 1)
            covariance = ((sigma, 0.0), (0.0, sigma))
        else:  # constant
            covariance = TIGHT_COVARIANCE
        views.append(
            ApproachView(
                robot_xy=(robot_x, 0.0),
                fused_xy=(reference.center[0], reference.center[1]),
                covariance=covariance,
                persistence=step != persistence_miss_step,
                identity_score=identity_score,
            )
        )
    return views


def _run(session: LockOnVerifySession, views: list[ApproachView]) -> list:
    verdicts = []
    for view in views:
        verdicts.append(session.observe(view))
        if verdicts[-1].refuted:
            break
    return verdicts


def test_covariance_trace_increase_at_a_checkpoint_vetoes() -> None:
    reference = _object_reference()
    session = LockOnVerifySession(reference)
    verdicts = _run(session, _approach_views(reference, trace="growing"))
    assert session.state is ApproachVerifyState.REJECTED
    assert verdicts[-1].reason == "covariance_did_not_shrink_at_checkpoint"
    assert verdicts[-1].veto


def test_persistence_miss_at_a_checkpoint_vetoes() -> None:
    reference = _object_reference()
    # Find the step at which the first checkpoint comes due, then blank it.
    probe = LockOnVerifySession(reference)
    views = _approach_views(reference)
    due_step = next(
        index
        for index, view in enumerate(views)
        if reference.range_from(view.robot_xy) <= reference.checkpoint_radii_m()[0]
    )
    _run(probe, views)
    assert probe.state is ApproachVerifyState.VERIFIED  # control: the same trace verifies

    session = LockOnVerifySession(reference)
    verdicts = _run(session, _approach_views(reference, persistence_miss_step=due_step))
    assert session.state is ApproachVerifyState.REJECTED
    assert verdicts[-1].reason == "persistence_miss_at_checkpoint"


def test_identity_recheck_failure_at_a_checkpoint_vetoes() -> None:
    reference = _object_reference()
    config = LockOnVerifyConfig()
    session = LockOnVerifySession(reference, config=config)
    below = config.identity_threshold / 2.0
    verdicts = _run(session, _approach_views(reference, identity_score=below))
    assert session.state is ApproachVerifyState.REJECTED
    assert verdicts[-1].reason == "identity_recheck_failed_at_checkpoint"

    # The same trace with a clearing score verifies, through the fn seam too.
    passing = LockOnVerifySession(reference, identity_fn=lambda _view: 1.0)
    _run(passing, _approach_views(reference))
    assert passing.state is ApproachVerifyState.VERIFIED


def test_a_consistent_shrinking_approach_clears_every_checkpoint() -> None:
    for radius, label in OPERATING_POINTS:
        reference = _object_reference(radius_m=radius, label=label)
        session = LockOnVerifySession(reference)
        _run(session, _approach_views(reference, steps=40, start_offset_m=12.0))
        assert session.state is ApproachVerifyState.VERIFIED
        assert session.pending_checkpoints == ()
        assert set(session.cleared_checkpoints) == set(reference.checkpoint_radii_m())
        assert session.negative_evidence() is None


def test_a_verified_session_keeps_re_verifying_and_can_still_be_refuted() -> None:
    """The measured defect was ``if self._committed: return None`` — forever."""

    reference = _object_reference()
    session = LockOnVerifySession(reference)
    _run(session, _approach_views(reference, steps=40, start_offset_m=12.0))
    assert session.state is ApproachVerifyState.VERIFIED

    drifted = session.observe(
        ApproachView(
            robot_xy=(9.0, 0.0),
            fused_xy=(reference.center[0] + 40.0, 0.0),
            covariance=TIGHT_COVARIANCE,
        )
    )
    assert drifted.refuted
    assert drifted.veto
    assert drifted.reason == "fused_point_outside_vicinity_band"


def test_refutation_hands_negative_evidence_to_the_fp_memory() -> None:
    reference = _object_reference()
    session = LockOnVerifySession(reference)
    _run(session, _approach_views(reference, trace="constant"))
    evidence = session.negative_evidence()
    assert evidence is not None
    assert evidence.label == "tree"
    assert evidence.landmark_id == "tree_2"
    assert evidence.world_xy == (10.0, 0.0)
    assert evidence.reason == "covariance_did_not_shrink_at_checkpoint"
    # Refutation is terminal: further views cannot resurrect the proposal.
    again = session.observe(
        ApproachView(robot_xy=(9.9, 0.0), fused_xy=(10.0, 0.0), covariance=_shrinking(99))
    )
    assert again.state is ApproachVerifyState.REJECTED
    assert again.reason == "already_refuted"


# --------------------------------------------------------------------------
# GATE 4 — per-kind refinement gate
# --------------------------------------------------------------------------


def test_b05_wrong_instance_displacement_is_rejected() -> None:
    reference = _region_reference()
    verdict = refinement_gate(reference, B05_WRONG_INSTANCE_XY)
    assert verdict.rejected
    assert verdict.reason == "fused_point_outside_dilated_region"
    assert verdict.displacement_m == pytest.approx(B05_DISPLACEMENT_M, abs=1e-12)
    assert verdict.mahalanobis is None

    # And the state machine refuses to commit it, no matter how many ticks.
    session = LockOnVerifySession(reference)
    for _ in range(5):
        result = session.observe(
            ApproachView(
                robot_xy=(1.348, -3.5),
                fused_xy=B05_WRONG_INSTANCE_XY,
                covariance=TIGHT_COVARIANCE,
            )
        )
    assert result.refuted
    assert session.state is ApproachVerifyState.REJECTED


def test_region_gate_dilates_by_exactly_the_ranking_boundary_margin() -> None:
    reference = _region_reference()
    inside = refinement_gate(reference, (0.0, 3.0))
    assert inside.accepted
    assert inside.displacement_m == 0.0

    assert refinement_gate(reference, (0.0, 2.2 - REGION_DILATION_M * 0.9)).accepted
    assert refinement_gate(reference, (0.0, 2.2 - REGION_DILATION_M * 1.1)).rejected

    # The predicate IS "distance to the polygon <= the ranking's margin", swept
    # across the boundary so the flip point cannot be an accident.
    for step in range(200):
        point = (0.0, 2.2 - REGION_DILATION_M * 2.0 * step / 200.0)
        verdict = refinement_gate(reference, point)
        assert verdict.accepted is (verdict.displacement_m <= REGION_DILATION_M)


def test_object_gate_rejects_outside_the_vicinity_band() -> None:
    for radius, label in OPERATING_POINTS:
        reference = _object_reference(radius_m=radius, label=label)
        _, _, vicinity = object_near_envelope_m(radius, label=label)
        inside = refinement_gate(reference, (reference.center[0] + vicinity * 0.99, 0.0))
        assert inside.accepted
        outside = refinement_gate(reference, (reference.center[0] + vicinity * 1.01, 0.0))
        assert outside.rejected
        assert outside.reason == "fused_point_outside_vicinity_band"
        # The band edge is the predicate, swept (no covariance ⇒ Mahalanobis inert).
        for step in range(200):
            point = (reference.center[0] + vicinity * 2.0 * step / 200.0, 0.0)
            verdict = refinement_gate(reference, point)
            assert verdict.accepted is (verdict.displacement_m <= vicinity)


def test_object_gate_rejects_mahalanobis_inconsistent_fusions() -> None:
    reference = _object_reference()
    _, _, vicinity = object_near_envelope_m(reference.radius_m, label=reference.label)
    offset = vicinity * 0.9
    tight = ((1e-4, 0.0), (0.0, 1e-4))
    verdict = refinement_gate(reference, (reference.center[0] + offset, 0.0), covariance=tight)
    assert verdict.rejected
    assert verdict.reason == "fused_point_mahalanobis_inconsistent"
    assert verdict.mahalanobis is not None and verdict.mahalanobis > MAHALANOBIS_GATE_SIGMA

    loose_sigma = (offset / MAHALANOBIS_GATE_SIGMA) ** 2 * 1.01
    loose = ((loose_sigma, 0.0), (0.0, loose_sigma))
    assert refinement_gate(reference, (reference.center[0] + offset, 0.0), covariance=loose).accepted


def test_mahalanobis_clause_is_inert_at_zero_covariance() -> None:
    """K0's own reduction: zero covariance ⇒ the boolean geometry decides."""

    reference = _object_reference()
    _, _, vicinity = object_near_envelope_m(reference.radius_m, label=reference.label)
    point = (reference.center[0] + vicinity * 0.99, 0.0)
    zero = ((0.0, 0.0), (0.0, 0.0))
    assert refinement_gate(reference, point, covariance=zero).accepted
    assert refinement_gate(reference, point, covariance=None).accepted


def test_region_kind_matches_the_pipeline_dichotomy() -> None:
    assert ReferenceKind.from_goal_kind("region") is ReferenceKind.REGION
    assert ReferenceKind.from_goal_kind("object") is ReferenceKind.OBJECT
    assert ReferenceKind.from_goal_kind(None) is ReferenceKind.OBJECT


def test_reference_construction_is_fail_closed() -> None:
    with pytest.raises(ValueError):
        GroundedReference(landmark_id="r", kind=ReferenceKind.REGION, polygon=((0.0, 0.0),))
    with pytest.raises(ValueError):
        GroundedReference(landmark_id="o", kind=ReferenceKind.OBJECT)
    with pytest.raises(ValueError):
        GroundedReference(landmark_id="", kind=ReferenceKind.OBJECT, center=(0.0, 0.0))
    with pytest.raises(ValueError):
        ApproachView(robot_xy=(math.nan, 0.0), fused_xy=(1.0, 1.0))


# --------------------------------------------------------------------------
# Properties (each shown able to fail on a seeded violation)
# --------------------------------------------------------------------------


def _property_no_self_confirmation(session: LockOnVerifySession, views: list[ApproachView]) -> None:
    """ORACLE: repeating one observation can never move the session forward."""

    before = (session.state, session.confirming_views, session.cleared_checkpoints)
    for view in views:
        session.observe(view)
    after = (session.state, session.confirming_views, session.cleared_checkpoints)
    assert after[0] is before[0]
    assert after[1] <= before[1] + 1
    assert after[2] == before[2]


def test_property_repeated_identical_views_never_advance_the_machine() -> None:
    rng = random.Random(20260811)
    for _ in range(50):
        radius, label = rng.choice(OPERATING_POINTS)
        reference = _object_reference(radius_m=radius, label=label)
        _, _, vicinity = object_near_envelope_m(radius, label=label)
        angle = rng.uniform(-math.pi, math.pi)
        distance = rng.uniform(0.0, vicinity)
        fused = (
            reference.center[0] + distance * math.cos(angle),
            reference.center[1] + distance * math.sin(angle),
        )
        robot = (fused[0] - rng.uniform(0.5, 6.0), fused[1])
        view = ApproachView(robot_xy=robot, fused_xy=fused, covariance=_shrinking(rng.randint(0, 5)))
        session = LockOnVerifySession(reference)
        session.observe(view)
        _property_no_self_confirmation(session, [view] * rng.randint(2, 8))


def test_seeded_violation_kills_the_self_confirmation_property() -> None:
    """A session that counted every tick as a view would fail the oracle."""

    class _SelfConfirmingSession(LockOnVerifySession):
        def observe(self, view: ApproachView):  # type: ignore[override]
            self._confirming_views += 1
            self._cleared = list(self.checkpoints_m)
            self._state = ApproachVerifyState.VERIFIED
            return super()._verdict(
                "seeded_violation",
                view,
                refinement_gate(self.reference, view.fused_xy),
                self.reference.range_from(view.robot_xy),
                True,
                True,
            )

    reference = _object_reference()
    session = _SelfConfirmingSession(reference)
    view = ApproachView(robot_xy=(4.0, 0.0), fused_xy=(10.0, 0.0), covariance=TIGHT_COVARIANCE)
    session.observe(view)
    with pytest.raises(AssertionError):
        _property_no_self_confirmation(session, [view, view, view])


def _property_gate_agrees_with_geometry(
    reference: GroundedReference, point: tuple[float, float], accepted: bool
) -> None:
    """ORACLE: acceptance == the per-kind predicate computed independently."""

    if reference.kind is ReferenceKind.REGION:
        assert reference.polygon is not None
        expected = _point_in_polygon_or_within(point, reference.polygon, REGION_DILATION_M)
    else:
        assert reference.center is not None
        _, _, vicinity = object_near_envelope_m(reference.radius_m, label=reference.label)
        expected = math.hypot(
            point[0] - reference.center[0], point[1] - reference.center[1]
        ) <= vicinity
    assert accepted is expected


def _point_in_polygon_or_within(
    point: tuple[float, float], polygon: tuple[tuple[float, float], ...], margin: float
) -> bool:
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if (current[1] > point[1]) != (previous[1] > point[1]):
            x_at = (previous[0] - current[0]) * (point[1] - current[1]) / (
                previous[1] - current[1]
            ) + current[0]
            if point[0] < x_at:
                inside = not inside
        previous = current
    if inside:
        return True
    best = math.inf
    previous = polygon[-1]
    for current in polygon:
        best = min(best, _segment_distance(point, previous, current))
        previous = current
    return best <= margin


def _segment_distance(
    point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    if length == 0.0:
        return math.hypot(point[0] - a[0], point[1] - a[1])
    t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length))
    return math.hypot(point[0] - (a[0] + t * dx), point[1] - (a[1] + t * dy))


def test_property_refinement_gate_matches_independent_geometry() -> None:
    rng = random.Random(815)
    references = [_region_reference()] + [
        _object_reference(radius_m=radius, label=label) for radius, label in OPERATING_POINTS
    ]
    for _ in range(400):
        reference = rng.choice(references)
        point = (rng.uniform(-8.0, 14.0), rng.uniform(-8.0, 8.0))
        verdict = refinement_gate(reference, point)
        _property_gate_agrees_with_geometry(reference, point, verdict.accepted)


def test_seeded_violation_kills_the_refinement_geometry_property() -> None:
    reference = _region_reference()
    # The B-05 point is 4.78 m outside; "accepted" is the seeded violation.
    with pytest.raises(AssertionError):
        _property_gate_agrees_with_geometry(reference, B05_WRONG_INSTANCE_XY, True)


def _property_shrink_decides_the_verdict(
    session: LockOnVerifySession, shrinking: bool
) -> None:
    """ORACLE: a closing approach verifies iff its D2 trace keeps shrinking."""

    if shrinking:
        assert session.state is ApproachVerifyState.VERIFIED
    else:
        assert session.state is ApproachVerifyState.REJECTED


def test_property_covariance_shrink_decides_the_approach_verdict() -> None:
    rng = random.Random(2026)
    for _ in range(40):
        radius, label = rng.choice(OPERATING_POINTS)
        reference = _object_reference(radius_m=radius, label=label)
        shrinking = rng.random() < 0.5
        session = LockOnVerifySession(reference)
        _run(
            session,
            _approach_views(
                reference,
                steps=40,
                start_offset_m=12.0,
                trace="shrinking" if shrinking else "constant",
            ),
        )
        _property_shrink_decides_the_verdict(session, shrinking)


def test_seeded_violation_kills_the_shrink_property() -> None:
    reference = _object_reference()
    session = LockOnVerifySession(reference)
    _run(session, _approach_views(reference, steps=40, start_offset_m=12.0, trace="constant"))
    assert session.state is ApproachVerifyState.REJECTED
    with pytest.raises(AssertionError):
        _property_shrink_decides_the_verdict(session, True)


def test_does_not_prove_is_recorded() -> None:
    assert len(lock_on_verify.DOES_NOT_PROVE) >= 3
    assert all(isinstance(item, str) and item for item in lock_on_verify.DOES_NOT_PROVE)


# --------------------------------------------------------------------------
# AF-2 AMENDMENT — no relation may claim an arrival with zero checkpoints due
#
# Provenance: scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md, should-fix 1 ("The
# verify-bypass shell is wider than ``towards``"). The near-object envelope is
# the NEAR relation's arrival band; ``towards`` reaches 2.5 m and ``next_to``
# reaches R+1.5, both outside it, so the verify machine could be bypassed
# entirely inside K0's own arrival region. One derivation closes towards,
# next_to and the metadata-``relative_band`` near override.
# --------------------------------------------------------------------------

#: Every terminal relation ``arrival_goal_region_for_relation`` builds a K0
#: region for. ``inside`` is the region-kind arrival.
AF2_RELATIONS = ("near", "towards", "next_to", "inside")


def _k0_region(relation: str, radius_m: float, label: str):
    if relation == "inside":
        return arrival_goal_region_for_relation("inside", polygon=B05_REGION_POLYGON)
    return arrival_goal_region_for_relation(
        relation,
        center=(10.0, 0.0),
        object_radius_m=radius_m,
        label=label,
        metadata={"radius_m": radius_m, "label": label},
    )


def _reference_for(relation: str, radius_m: float, label: str) -> GroundedReference:
    region = _k0_region(relation, radius_m, label)
    band = None if region.band_m is None else (float(region.band_m[0]), float(region.band_m[1]))
    if relation == "inside":
        return GroundedReference(
            landmark_id="sidewalk_north",
            kind=ReferenceKind.REGION,
            label="sidewalk",
            polygon=B05_REGION_POLYGON,
            relation=relation,
            arrival_band_m=band,
        )
    return GroundedReference(
        landmark_id="anchor_1",
        kind=ReferenceKind.OBJECT,
        label=label,
        center=(10.0, 0.0),
        radius_m=radius_m,
        relation=relation,
        arrival_band_m=band,
    )


def _dead_zone(reference: GroundedReference, region) -> list[tuple[float, float]]:
    """Points K0 calls an arrival where NO checkpoint is due (must be empty)."""

    radii = reference.checkpoint_radii_m()
    offenders: list[tuple[float, float]] = []
    for step in range(1201):
        # Radial sweep out to well past every band, on two bearings so the
        # polygon case is sampled off-axis too.
        distance = 0.005 * step
        for bearing in (0.0, 0.7):
            point = (
                10.0 + distance * math.cos(bearing),
                0.0 + distance * math.sin(bearing),
            )
            if relation_contains(region, point) and not any(
                reference.range_from(point) <= radius for radius in radii
            ):
                offenders.append(point)
    return offenders


def relation_contains(region, point: tuple[float, float]) -> bool:
    return bool(region.contains(float(point[0]), float(point[1])))


def test_property_no_k0_arrival_point_has_zero_checkpoints_due() -> None:
    """AF-2 gate: for EVERY relation with a K0 region, the shell is closed."""

    for relation in AF2_RELATIONS:
        for radius, label in OPERATING_POINTS:
            if relation == "inside":
                region = _k0_region(relation, radius, label)
                reference = _reference_for(relation, radius, label)
                # Sample the polygon itself, not a radial sweep about (10, 0).
                inside_points = [(0.0, 3.2), (-5.9, 2.3), (5.9, 4.1), (1.348, 2.2)]
                radii = reference.checkpoint_radii_m()
                for point in inside_points:
                    assert region.contains(*point)
                    assert any(reference.range_from(point) <= r for r in radii), (
                        f"{relation}: {point} is a K0 arrival with no checkpoint due"
                    )
                continue
            region = _k0_region(relation, radius, label)
            reference = _reference_for(relation, radius, label)
            offenders = _dead_zone(reference, region)
            assert offenders == [], (
                f"{relation} r={radius} label={label!r}: "
                f"{len(offenders)} K0 arrival points with zero checkpoints due, "
                f"first {offenders[0]}; schedule {reference.checkpoint_radii_m()}"
            )


def test_the_audit_next_to_shell_now_fails_closed() -> None:
    """The audit's exact repro: ``next_to`` contains(R+1.45), none due."""

    radius = 0.25
    region = _k0_region("next_to", radius, "tree")
    probe = (10.0 + radius + 1.45, 0.0)
    assert region.contains(*probe), "the probe is not inside K0's next_to band"

    # Pre-amendment schedule (the envelope alone) — the measured 0.18 m shell.
    envelope_only = checkpoint_radii_m(radius, label="tree")
    assert not any((radius + 1.45) <= r for r in envelope_only), (
        "the shell the audit measured is not reproducible"
    )
    assert (radius + NEXT_TO_BAND_M[1]) - max(envelope_only) == pytest.approx(0.18, abs=1e-9)

    # Amended schedule — the K0 outer edge leads it, so a checkpoint IS due.
    reference = _reference_for("next_to", radius, "tree")
    radii = reference.checkpoint_radii_m()
    assert radii[0] == pytest.approx(radius + NEXT_TO_BAND_M[1])
    assert any(reference.range_from(probe) <= r for r in radii)
    # Strictly additive: the envelope's own three values survive, in order.
    assert list(radii[1:]) == list(envelope_only)


def test_the_towards_bypass_that_produced_ph31_is_closed() -> None:
    """PH-31: stopped 2.4699 m from a lamppost, inside K0, no checkpoint due."""

    region = _k0_region("towards", 0.06, "lamppost")
    probe = (10.0 + 2.4699, 0.0)
    assert region.contains(*probe)

    envelope_only = checkpoint_radii_m(0.06, label="lamppost")
    assert not any(2.4699 <= r for r in envelope_only)

    reference = _reference_for("towards", 0.06, "lamppost")
    radii = reference.checkpoint_radii_m()
    assert radii[0] == pytest.approx(TOWARDS_BAND_M[1])
    assert any(reference.range_from(probe) <= r for r in radii)


def test_a_metadata_relative_band_override_cannot_reopen_the_gap() -> None:
    """``near`` carrying a wider metadata band still gets an outer checkpoint."""

    wide = (0.5, 4.0)
    reference = GroundedReference(
        landmark_id="tree_2",
        kind=ReferenceKind.OBJECT,
        label="tree",
        center=(10.0, 0.0),
        radius_m=0.25,
        relation="near",
        arrival_band_m=wide,
    )
    radii = reference.checkpoint_radii_m()
    assert radii[0] == pytest.approx(4.0)
    assert any(reference.range_from((13.9, 0.0)) <= r for r in radii)


def test_arrival_band_outer_is_k0s_own_band_by_reference() -> None:
    """Derivation-over-exposure: the module never restates an arrival number."""

    for radius, label in OPERATING_POINTS:
        for relation in ("near", "towards", "next_to"):
            region = _k0_region(relation, radius, label)
            assert region.band_m is not None
            derived = arrival_band_outer_m(relation, radius, label=label)
            assert _bits(derived) == _bits(region.band_m[1]), (
                f"{relation} r={radius} label={label!r}: "
                f"{derived} != K0's {region.band_m[1]}"
            )
    assert arrival_band_outer_m("inside") == 0.0
    assert arrival_band_outer_m("") is None


def test_the_amendment_is_additive_and_default_off() -> None:
    """Omitting the relation reproduces the pre-amendment schedule exactly."""

    for radius, label in OPERATING_POINTS:
        envelope = object_near_envelope_m(radius, label=label)
        expected = tuple(sorted(set(envelope), reverse=True))
        assert checkpoint_radii_m(radius, label=label) == expected
        # ``near`` is the envelope's own relation: it adds nothing.
        assert checkpoint_radii_m(radius, label=label, relation="near") == expected
        # An outer edge INSIDE the envelope is never inserted.
        assert (
            checkpoint_radii_m(radius, label=label, arrival_band_m=(0.0, 0.1)) == expected
        )


def test_seeded_violation_kills_the_no_dead_zone_property() -> None:
    """The property is evidence, not notation: the OLD schedule fails it.

    Same oracle, same sweep, the pre-amendment reference (no relation) — every
    relation whose K0 band reaches outside the near-object envelope produces a
    non-empty dead zone, which is exactly the measured bypass.
    """

    shells: dict[str, float] = {}
    for relation in ("towards", "next_to"):
        for radius, label in OPERATING_POINTS:
            region = _k0_region(relation, radius, label)
            blind = GroundedReference(
                landmark_id="anchor_1",
                kind=ReferenceKind.OBJECT,
                label=label,
                center=(10.0, 0.0),
                radius_m=radius,
            )
            key = f"{relation}:{radius}:{label}"
            # The shell's WIDTH: how far K0's band reaches past the envelope.
            shell = arrival_band_outer_m(relation, radius, label=label) - max(
                object_near_envelope_m(radius, label=label)
            )
            shells[key] = shell
            offenders = _dead_zone(blind, region)
            if shell > 0.0:
                assert offenders, f"{key}: a {shell:.4f} m shell produced no dead zone"
            else:
                assert not offenders, f"{key}: no shell, yet a dead zone appeared"

    # The two shells the audit names, measured here: towards on a lamppost and
    # next_to on any anchor (R cancels — the band is surface-anchored).
    assert shells["towards:0.0:lamppost"] == pytest.approx(2.5 - 1.32, abs=1e-9)
    assert shells["next_to:0.25:tree"] == pytest.approx(0.18, abs=1e-9)
    # A big anchor's near envelope already reaches past both bands, so the
    # bypass is anchor-size dependent — which is why it was invisible at scale.
    assert shells["towards:1.2:building"] < 0.0
    assert shells["next_to:1.2:building"] < 0.0


# --------------------------------------------------------------------------
# AF-2 — the reference travels with its landmark (should-fix 3)
# --------------------------------------------------------------------------


def test_translated_moves_geometry_and_nothing_else() -> None:
    reference = GroundedReference(
        landmark_id="lamp_post_1",
        kind=ReferenceKind.OBJECT,
        label="lamppost",
        center=(4.0, -1.0),
        radius_m=0.06,
        relation="towards",
        arrival_band_m=(0.6, 2.5),
    )
    moved = reference.translated(1.5, -0.25)
    assert moved.center == pytest.approx((5.5, -1.25))
    for field in ("landmark_id", "kind", "label", "radius_m", "relation", "arrival_band_m"):
        assert getattr(moved, field) == getattr(reference, field)
    assert moved.checkpoint_radii_m() == reference.checkpoint_radii_m()
    # Frozen: the original is untouched.
    assert reference.center == pytest.approx((4.0, -1.0))

    region = _region_reference().translated(0.0, 3.0)
    assert region.polygon == tuple((x, y + 3.0) for x, y in B05_REGION_POLYGON)
    # The polygon moved with the frame: what used to be inside at y=3.2 is now
    # inside at y=6.2, and the old point is outside by exactly the shift.
    assert region.range_from((0.0, 6.2)) == 0.0
    assert region.range_from((0.0, 3.2)) == pytest.approx(2.0)

    with pytest.raises(ValueError):
        reference.translated(float("nan"), 0.0)


def test_reanchor_keeps_every_verdict_the_session_has_reached() -> None:
    """A frame correction is not evidence: it clears and confirms nothing."""

    reference = _object_reference()
    session = LockOnSessionAtCheckpoint = LockOnVerifySession(reference)
    cleared_before = _drive_until_a_checkpoint_clears(session, reference)
    assert cleared_before, "the fixture never cleared a checkpoint"

    session.reanchor(0.0, 4.0)
    assert session.reference.center == pytest.approx((10.0, 4.0))
    assert session.cleared_checkpoints == cleared_before
    assert session.checkpoints_m == reference.checkpoint_radii_m()
    assert session.state is not ApproachVerifyState.REJECTED
    assert LockOnSessionAtCheckpoint is session

    # A healthy estimate in the NEW frame is consistent again; the pre-drift
    # reference would have refuted it (the audit's self-suppression scenario).
    healthy = ApproachView(robot_xy=(0.0, 4.0), fused_xy=(10.0, 4.0))
    assert refinement_gate(session.reference, healthy.fused_xy).accepted
    assert refinement_gate(reference, healthy.fused_xy).rejected


def _drive_until_a_checkpoint_clears(session, reference) -> tuple[float, ...]:
    for step, distance in enumerate((6.0, 4.0, 2.0, 1.4, 1.2, 1.0, 0.8)):
        bearing = 0.9 * step
        view = ApproachView(
            robot_xy=(
                reference.center[0] + distance * math.cos(bearing),
                reference.center[1] + distance * math.sin(bearing),
            ),
            fused_xy=reference.center,
            covariance=_shrinking(step),
        )
        session.observe(view)
        if session.cleared_checkpoints:
            return session.cleared_checkpoints
    return session.cleared_checkpoints
