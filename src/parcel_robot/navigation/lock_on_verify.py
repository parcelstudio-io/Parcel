"""Verify-on-approach lock-on state machine + per-kind refinement gate (card VS-1).

Why this module exists
----------------------
V-E was measured as a **wrong-instance commit against a silently rewritten
goal**, not as an arrival-check bug
(``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md`` §2.1(1)): the lock-on branch
retargeted the goal to the D2 fused point, built ``arrival_goal_region`` FROM
that rewritten candidate, and K0 then *correctly* verified arrival against the
region it was handed — final pose (1.3480, −2.5785) inside the south sidewalk
while the episode polygon was ``y ∈ [2.2, 4.2]``, dtg 4.778530810034543.
Compounding it, lock-on "views" were self-confirming: ``observe_candidate``
re-read the same grounded oracle candidate every tick and the per-tick
``now_ns`` made each re-read a *distinct* view token, so M-of-N reduced to
"any 3 consecutive ticks" with zero independent evidence (§2.1(1), §2.1(3)).

Core principle — reference/estimate separation (§2.2)
----------------------------------------------------
The mission's grounded goal (landmark id + geometry) is the **REFERENCE** and
is never rewritten by perception. A lock-on produces an **ESTIMATE** (fused
point + D2 covariance) that must stay consistent with the reference. K0 keeps
verifying arrival against the REFERENCE only — this module adds no arrival
predicate, widens no epsilon, and never special-cases a goal. It PROPOSES a
verdict; the arbiter/gate stack disposes.

What is verified, and against which authority
---------------------------------------------
* **Checkpoint radii** are the near-object envelope itself:
  :func:`~parcel_robot.instructnav.scoring.object_near_envelope_m` returns
  ``(stand_off, minimum_vicinity, vicinity)`` and those three values — sorted
  outward-in, de-duplicated, never re-arithmetised — ARE the re-verification
  schedule. ``tests/test_lock_on_verify.py`` pins them ``struct.pack``-equal
  to the envelope's own outputs (E5/E6/E8 derivation-over-exposure pattern).

  **AMENDMENT — card AF-2, 2026-08-11. Provenance:**
  ``scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md``, should-fix 1, "The
  verify-bypass shell is wider than ``towards``". The envelope is the NEAR
  relation's arrival band; it is not every relation's. K0's ``towards`` band
  reaches 2.5 m and ``next_to``'s reaches ``R + 1.5`` while the envelope's
  outermost radius is ``vicinity(R)`` (1.32 m for a lamppost, ``R + 1.32``
  generally) — so an arrival was claimable inside the K0 region with **zero
  checkpoints ever due**, and the identity re-check that would have refuted it
  never ran (measured: episode ``nav-object_goal-PH-31``, stopped 2.4699 m from
  a lamppost committed for a "tree" query; and the 0.18 m ``next_to`` shell).
  The schedule therefore also carries the ACTIVE RELATION's K0 outer band edge
  as its first (outermost) checkpoint whenever that edge lies outside the
  envelope — one derivation closing ``towards``, ``next_to`` and the
  metadata-``relative_band`` ``near`` override alike
  (:func:`arrival_band_outer_m`). The relation reaches this module as an INPUT;
  the bands themselves are read by reference from
  :mod:`parcel_robot.instructnav.scoring`, so no arrival number is restated
  here. Strictly ADDITIVE: an outer checkpoint can only make the machine ask
  for evidence EARLIER, never later, and it widens no arrival — K0 remains the
  sole arrival authority.
* **View admission** (the independent-evidence rule that kills
  self-confirmation) uses the full-turn scan's own stop separation,
  ``2π / ScanPlanSpec.n_stops`` from
  :func:`~parcel_robot.instructnav.scan.full_turn_scan_spec` — one admissible
  view per scan arc, consumed BY REFERENCE. Adjudication #8 rejected the
  earlier "derived from the confirmer's association constants" claim as a fake
  derivation (those constants are score-space and derive no geometry); this is
  the real in-tree authority.
* **Region refinement** dilates the grounded polygon by
  :data:`~parcel_robot.instructnav.scoring.ARRIVAL_BOUNDARY_EPSILON_M`, the
  boundary margin the interchangeable ranking and the differential-authority
  verdict already use — Mahalanobis against a polygon is undefined, which is
  why the gate is defined PER REFERENCE KIND (adjudication #7).
* **Object refinement** keeps the fused point inside the vicinity the same
  envelope publishes, and Mahalanobis-consistent with the D2 covariance at
  :data:`~parcel_robot.instructnav.scoring.INSIDE_PROBABILITY_THRESHOLD` — the
  same chance-constraint level K0's ``GoalRegion.contains`` uses. At zero /
  degenerate covariance the Mahalanobis clause is inert, exactly as K0's
  chance constraint reduces to boolean geometry at zero covariance.

No numeric policy of this module's own is written here. A threshold restated
locally would fork the authority the first time it is retuned — the failure
class D-15 is.

Freshness, and the one place this module fills a gap
----------------------------------------------------
The record fixes the M-of-N admission quantum (angular, above) and states that
each checkpoint "demands fresh evidence: persistence, covariance shrink,
optional SigLIP identity re-check". It does not define freshness for the
checkpoint machinery itself, and covariance shrink alone is spoofable — a
static Kalman filter re-fused with the *same* measurement shrinks its trace
monotonically, which is the metric form of the self-confirmation bug. So a
checkpoint may only be cleared by an observation whose GEOMETRY changed:
either the admission quantum in aspect angle, or a strictly closer range to
the estimate than at the previous clearance. Re-reading a cached candidate
from an unmoved pose changes neither; the measured V-B phantom (constant
bearing and range while the body closes on the reference) changes neither.

Nothing here publishes, flushes, or commits. ``LockOnVerifySession`` returns
verdicts; the P0-C stamp/flush seam and the FP-memory write are the wiring
card's (VS-4) business.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from parcel_robot.instructnav.relations import distance_to_region_m
from parcel_robot.instructnav.scan import full_turn_scan_spec
from parcel_robot.instructnav.scoring import (
    ARRIVAL_BOUNDARY_EPSILON_M,
    INSIDE_PROBABILITY_THRESHOLD,
    TOWARDS_BAND_M,
    ApproachVerifyState,
    next_to_band_from_centre,
    object_near_envelope_m,
)
from parcel_robot.instructnav.siglip import SIGLIP2_MATCH_THRESHOLD

__all__ = [
    "DOES_NOT_PROVE",
    "MAHALANOBIS_GATE_SIGMA",
    "REGION_DILATION_M",
    "VIEW_ADMISSION_SEPARATION_RAD",
    "ApproachView",
    "GroundedReference",
    "LockOnVerifyConfig",
    "LockOnVerifySession",
    "NegativeEvidence",
    "ReferenceKind",
    "RefinementVerdict",
    "VerifyVerdict",
    "admits_for_confirmation",
    "arrival_band_outer_m",
    "checkpoint_radii_m",
    "is_fresh_observation",
    "refinement_gate",
    "view_separation_rad",
]

Covariance2 = tuple[tuple[float, float], tuple[float, float]]

DOES_NOT_PROVE = (
    (
        "These cells prove the verify-on-approach state machine and the per-kind "
        "refinement gate on supplied traces; they do not prove real D455 "
        "persistence — in the T0 eval arms 'persistence' is the oracle frustum, "
        "which never hallucinates, so phantom-rejection power is exercised only "
        "by injected phantom traces (record §2.4)."
    ),
    (
        "The module PROPOSES verdicts. K0 remains the single arrival authority "
        "and is untouched: no epsilon is widened, no arrival reason is added, "
        "and no goal is special-cased here."
    ),
    (
        "The view-admission quantum is derived from the full-turn scan spec, not "
        "measured against real inter-view decorrelation; it is a structural "
        "anti-self-confirmation rule, not a statistical independence test."
    ),
)


def _scan_stop_separation_rad() -> float:
    """``2π / n_stops`` read off the full-turn scan spec (no local literal)."""

    spec = full_turn_scan_spec()
    return abs(spec.total_yaw_rad) / float(spec.n_stops)


#: Minimum angular separation between two views that may both count toward
#: M-of-N. One admissible view per full-turn scan arc (adjudication #8).
VIEW_ADMISSION_SEPARATION_RAD: float = _scan_stop_separation_rad()

#: Region refinement dilation — the interchangeable ranking's own boundary
#: margin, consumed by reference.
REGION_DILATION_M: float = ARRIVAL_BOUNDARY_EPSILON_M

#: Mahalanobis radius at K0's chance-constraint level. For a 2-D Gaussian
#: ``P(d² ≤ r²) = 1 − exp(−r²/2)``, so ``r = sqrt(−2·ln(1 − τ))`` with ``τ``
#: the same ``INSIDE_PROBABILITY_THRESHOLD`` ``GoalRegion.contains`` uses. The
#: ``2`` is the state dimension, not a tuned number.
MAHALANOBIS_GATE_SIGMA: float = math.sqrt(-2.0 * math.log(1.0 - INSIDE_PROBABILITY_THRESHOLD))


class ReferenceKind(str, Enum):
    """Which refinement gate applies (the pipeline's own dichotomy)."""

    #: Stuff-class / polygon goals: sidewalk, grass, road.
    REGION = "region"
    #: Countable things with a footprint and a near-object envelope.
    OBJECT = "object"

    @classmethod
    def from_goal_kind(cls, kind: object) -> ReferenceKind:
        """``"region"`` maps to REGION; everything else is an OBJECT.

        Mirrors ``pipeline.interchangeable_scan``'s test verbatim so this
        module cannot disagree with the ranking about what a region is.
        """

        return cls.REGION if str(kind or "") == cls.REGION.value else cls.OBJECT


@dataclass(frozen=True, slots=True)
class GroundedReference:
    """The mission's grounded goal. Perception never rewrites this.

    ``landmark_id`` is the never-rewritten promise the V-E trace broke; it is
    carried so a consumer can assert provenance without re-deriving geometry.

    ``relation`` / ``arrival_band_m`` are the card AF-2 amendment's inputs: the
    mission's TERMINAL RELATION, and — when K0 built a band-shaped arrival
    region for this commit — that region's band verbatim. They reach the
    checkpoint derivation and nothing else; no geometry here is re-derived from
    them (provenance: ``scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md``,
    should-fix 1). Defaulting both keeps every pre-amendment construction
    behaving exactly as before.
    """

    landmark_id: str
    kind: ReferenceKind
    label: str = ""
    polygon: tuple[tuple[float, float], ...] | None = None
    center: tuple[float, float] | None = None
    radius_m: float = 0.0
    relation: str = ""
    arrival_band_m: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        if not str(self.landmark_id):
            raise ValueError("landmark_id must be non-empty")
        if not isinstance(self.kind, ReferenceKind):
            raise TypeError("kind must be a ReferenceKind")
        radius = float(self.radius_m)
        if not math.isfinite(radius) or radius < 0.0:
            raise ValueError("radius_m must be finite and >= 0")
        if self.arrival_band_m is not None:
            band = tuple(self.arrival_band_m)
            if len(band) < 2 or not all(math.isfinite(float(v)) for v in band[:2]):
                raise ValueError("arrival_band_m must be a finite (min, max) pair")
            if not float(band[0]) <= float(band[1]):
                raise ValueError("arrival_band_m must satisfy min <= max")
        if self.kind is ReferenceKind.REGION:
            if self.polygon is None or len(self.polygon) < 3:
                raise ValueError("a region reference requires a >=3 vertex polygon")
            for point in self.polygon:
                _finite_xy(point, "polygon vertex")
        else:
            if self.center is None:
                raise ValueError("an object reference requires a center")
            _finite_xy(self.center, "center")

    def range_from(self, robot_xy: tuple[float, float]) -> float:
        """Range used by the checkpoint schedule.

        Regions: exact boundary distance (0 inside), the same question the
        interchangeable ranking asks. Objects: distance to the CENTRE, because
        every term of :func:`object_near_envelope_m` is centre-referenced (it
        adds the object's own radius).
        """

        _finite_xy(robot_xy, "robot_xy")
        if self.kind is ReferenceKind.REGION:
            assert self.polygon is not None
            return distance_to_region_m(self.polygon, (float(robot_xy[0]), float(robot_xy[1])))
        assert self.center is not None
        return math.hypot(float(robot_xy[0]) - self.center[0], float(robot_xy[1]) - self.center[1])

    def translated(self, dx: float, dy: float) -> GroundedReference:
        """This same reference, moved by ``(dx, dy)``. Geometry only.

        **Card AF-2, 2026-08-11. Provenance:**
        ``scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md``, should-fix 3
        ("Re-anchoring vs the frozen reference"). A goal stored only in world
        coordinates is wrong the moment its frame drifts, which is why the
        pipeline re-derives goal / arrival region / candidate from a fresh
        sighting of the SAME landmark. The verify session's reference is part of
        that same anchored geometry: left behind, the object gate would measure
        a healthy estimate against a stale centre, refute a good commitment, and
        write negative evidence AT THE TRUE TARGET — self-suppressing it for the
        whole TTL horizon. This is the translation, so a re-anchor can move it
        in the same transaction.

        ``landmark_id``, ``label``, ``radius_m``, ``relation`` and
        ``arrival_band_m`` are all frame-independent and are carried verbatim:
        a re-anchor moves WHERE the reference is, never WHAT it is.
        """

        shift_x, shift_y = float(dx), float(dy)
        if not (math.isfinite(shift_x) and math.isfinite(shift_y)):
            raise ValueError("re-anchor displacement must be finite")
        polygon = (
            None
            if self.polygon is None
            else tuple(
                (float(vertex[0]) + shift_x, float(vertex[1]) + shift_y)
                for vertex in self.polygon
            )
        )
        center = (
            None
            if self.center is None
            else (float(self.center[0]) + shift_x, float(self.center[1]) + shift_y)
        )
        return GroundedReference(
            landmark_id=self.landmark_id,
            kind=self.kind,
            label=self.label,
            polygon=polygon,
            center=center,
            radius_m=self.radius_m,
            relation=self.relation,
            arrival_band_m=self.arrival_band_m,
        )

    def checkpoint_radii_m(self) -> tuple[float, ...]:
        """This reference's re-verification schedule (outermost first).

        Card AF-2: the active relation's K0 outer band edge leads the schedule
        when it lies outside the near-object envelope, so no point inside the
        arrival region can be reached with zero checkpoints due.
        """

        return checkpoint_radii_m(
            self.radius_m,
            label=self.label,
            relation=self.relation,
            arrival_band_m=self.arrival_band_m,
        )


def arrival_band_outer_m(
    relation: str,
    object_radius_m: float = 0.0,
    *,
    label: str = "",
    band_m: tuple[float, float] | None = None,
) -> float | None:
    """K0's OUTER arrival-band edge for ``relation`` (card AF-2 amendment).

    Returned in the units :meth:`GroundedReference.range_from` speaks: distance
    to the object CENTRE for object relations, distance to the polygon for a
    region. ``None`` when the relation publishes no band this module can read.

    Every value is
    :func:`~parcel_robot.instructnav.scoring.arrival_goal_region_for_relation`'s
    own, by reference — ``TOWARDS_BAND_M``'s outer edge for ``towards``,
    :func:`~parcel_robot.instructnav.scoring.next_to_band_from_centre` for
    ``next_to`` (surface-anchored, so it grows with the anchor), and the near
    envelope's ``vicinity`` otherwise. ``band_m``, when given, is the arrival
    region's band as K0 actually built it for THIS commit and wins outright:
    that is how a ``near`` goal carrying a metadata ``relative_band`` override
    cannot reopen the gap. ``inside`` returns ``0.0`` — arrival there means
    distance-to-polygon zero, which every checkpoint already covers.

    Provenance: ``scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md``, should-fix 1.
    """

    if band_m is not None:
        outer = float(band_m[1])
        if not math.isfinite(outer):
            raise ValueError("band_m outer edge must be finite")
        return outer
    name = str(relation or "").strip().lower()
    if name == "towards":
        return float(TOWARDS_BAND_M[1])
    if name == "next_to":
        return float(next_to_band_from_centre(float(object_radius_m))[1])
    if name == "inside":
        return 0.0
    if not name:
        return None
    return float(object_near_envelope_m(float(object_radius_m), label=label)[2])


def checkpoint_radii_m(
    object_radius_m: float,
    *,
    label: str = "",
    relation: str = "",
    arrival_band_m: tuple[float, float] | None = None,
) -> tuple[float, ...]:
    """Re-verification checkpoints, outermost first — the envelope, verbatim.

    The three values are exactly
    :func:`~parcel_robot.instructnav.scoring.object_near_envelope_m`'s
    ``(stand_off, minimum_vicinity, vicinity)``: sorted descending (the order a
    closing approach crosses them) and de-duplicated (the lamppost branch makes
    ``stand_off == vicinity``). No arithmetic is applied, so each radius is
    bit-identical to the envelope's own output.

    **Card AF-2 amendment** (module docstring, "What is verified"): when the
    active relation's K0 outer band edge lies OUTSIDE the envelope's outermost
    radius it is prepended as the first checkpoint, so no relation can claim an
    arrival with zero checkpoints ever due. The edge is
    :func:`arrival_band_outer_m`'s, itself read by reference from the scorer's
    bands; the envelope's own three values are still bit-identical and still in
    order, because the amendment only ever INSERTS one radius ahead of them.
    Omit ``relation`` (the default) and the schedule is the pre-amendment one,
    which is what keeps every unrelated caller unchanged.
    """

    envelope = object_near_envelope_m(object_radius_m, label=label)
    ordered: list[float] = []
    for radius in sorted(envelope, reverse=True):
        if radius not in ordered:
            ordered.append(radius)
    outer = arrival_band_outer_m(
        relation, object_radius_m, label=label, band_m=arrival_band_m
    )
    if outer is not None and ordered and outer > ordered[0]:
        ordered.insert(0, outer)
    return tuple(ordered)


@dataclass(frozen=True, slots=True)
class ApproachView:
    """One observation offered to the session as the body closes on the goal.

    ``fused_xy`` / ``covariance`` are the D2 estimate (never the reference).
    ``persistence`` answers "was the target associated in THIS view?" — a
    single miss is not fatal away from a checkpoint, and is fatal at one.
    ``identity_score`` is the optional SigLIP re-check, computed by the caller
    through the existing matcher/``embed_fn`` seam so this module stays free of
    the model surface.
    """

    robot_xy: tuple[float, float]
    fused_xy: tuple[float, float]
    covariance: Covariance2 | None = None
    persistence: bool = True
    identity_score: float | None = None

    def __post_init__(self) -> None:
        _finite_xy(self.robot_xy, "robot_xy")
        _finite_xy(self.fused_xy, "fused_xy")
        if self.covariance is not None:
            _validate_covariance(self.covariance)
        if self.identity_score is not None:
            score = float(self.identity_score)
            if not math.isfinite(score):
                raise ValueError("identity_score must be finite")

    @property
    def aspect_rad(self) -> float:
        """World bearing from the ESTIMATE to the observer.

        The angle a second look must move through to be independent evidence:
        two observations taken from the same aspect are the same observation,
        however many ticks separate them.
        """

        return math.atan2(
            float(self.robot_xy[1]) - float(self.fused_xy[1]),
            float(self.robot_xy[0]) - float(self.fused_xy[0]),
        )

    @property
    def estimate_range_m(self) -> float:
        """Observer-to-estimate range (not the reference range)."""

        return math.hypot(
            float(self.fused_xy[0]) - float(self.robot_xy[0]),
            float(self.fused_xy[1]) - float(self.robot_xy[1]),
        )

    @property
    def covariance_trace(self) -> float:
        """D2 trace; ``inf`` when the caller supplied no covariance."""

        if self.covariance is None:
            return math.inf
        return float(self.covariance[0][0]) + float(self.covariance[1][1])


def view_separation_rad(previous: ApproachView, current: ApproachView) -> float:
    """Angular separation between two views, measured at the estimate."""

    return abs(_wrap_pi(current.aspect_rad - previous.aspect_rad))


def admits_for_confirmation(previous: ApproachView | None, current: ApproachView) -> bool:
    """The record's M-of-N admission rule: one view per scan arc.

    The first view of a session is always admissible; every later one must be
    at least :data:`VIEW_ADMISSION_SEPARATION_RAD` from the previous ADMITTED
    view. Consumers filter what reaches ``MultiViewConfirm`` with this —
    ``multi_view_confirm.py`` itself is untouched.
    """

    if previous is None:
        return True
    return view_separation_rad(previous, current) >= VIEW_ADMISSION_SEPARATION_RAD


def is_fresh_observation(previous: ApproachView | None, current: ApproachView) -> bool:
    """Did the observation GEOMETRY change since ``previous``?

    True when the view clears the admission quantum, or when the observer is
    strictly closer to the estimate than it was. Both are things a re-read of a
    cached candidate from an unmoved pose cannot produce, and neither is
    produced by a phantom that holds constant bearing and range.
    """

    if previous is None:
        return True
    if admits_for_confirmation(previous, current):
        return True
    return current.estimate_range_m < previous.estimate_range_m


@dataclass(frozen=True, slots=True)
class RefinementVerdict:
    """Is the fused ESTIMATE consistent with the grounded REFERENCE?"""

    accepted: bool
    reason: str
    kind: ReferenceKind
    displacement_m: float
    mahalanobis: float | None = None

    @property
    def rejected(self) -> bool:
        return not self.accepted


def refinement_gate(
    reference: GroundedReference,
    fused_xy: tuple[float, float],
    *,
    covariance: Covariance2 | None = None,
) -> RefinementVerdict:
    """Per-kind refinement gate (record §2.2(a)(iii), adjudication #7).

    REGION — the fused point must lie inside the grounded polygon dilated by
    :data:`REGION_DILATION_M`; ``displacement_m`` is the exact distance to the
    polygon (0 inside). Mahalanobis is not evaluated: it is undefined against a
    polygon, which is precisely why the gate is per-kind.

    OBJECT — the fused point must lie within the envelope's vicinity of the
    reference centre AND be Mahalanobis-consistent with the D2 covariance at
    :data:`MAHALANOBIS_GATE_SIGMA`. A degenerate/omitted covariance leaves the
    Mahalanobis clause inert (K0's own zero-covariance reduction).

    A rejection is a REFUTATION, not "no commit yet": the estimate contradicts
    the reference it claims to be.
    """

    _finite_xy(fused_xy, "fused_xy")
    point = (float(fused_xy[0]), float(fused_xy[1]))
    if reference.kind is ReferenceKind.REGION:
        assert reference.polygon is not None
        distance = distance_to_region_m(reference.polygon, point)
        if distance > REGION_DILATION_M:
            return RefinementVerdict(
                accepted=False,
                reason="fused_point_outside_dilated_region",
                kind=reference.kind,
                displacement_m=distance,
            )
        return RefinementVerdict(
            accepted=True,
            reason="fused_point_inside_dilated_region",
            kind=reference.kind,
            displacement_m=distance,
        )

    assert reference.center is not None
    _, _, vicinity_m = object_near_envelope_m(reference.radius_m, label=reference.label)
    displacement = math.hypot(point[0] - reference.center[0], point[1] - reference.center[1])
    if displacement > vicinity_m:
        return RefinementVerdict(
            accepted=False,
            reason="fused_point_outside_vicinity_band",
            kind=reference.kind,
            displacement_m=displacement,
        )
    distance = _mahalanobis(point, reference.center, covariance)
    if distance is not None and distance > MAHALANOBIS_GATE_SIGMA:
        return RefinementVerdict(
            accepted=False,
            reason="fused_point_mahalanobis_inconsistent",
            kind=reference.kind,
            displacement_m=displacement,
            mahalanobis=distance,
        )
    return RefinementVerdict(
        accepted=True,
        reason="fused_point_consistent_with_reference",
        kind=reference.kind,
        displacement_m=displacement,
        mahalanobis=distance,
    )


@dataclass(frozen=True, slots=True)
class LockOnVerifyConfig:
    """Numeric policy — every field defaults to an in-tree authority."""

    identity_threshold: float = SIGLIP2_MATCH_THRESHOLD

    def __post_init__(self) -> None:
        if not 0.0 <= self.identity_threshold <= 1.0:
            raise ValueError("identity_threshold must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class NegativeEvidence:
    """What a refutation hands to the false-positive memory (card VS-2)."""

    label: str
    world_xy: tuple[float, float]
    reason: str
    landmark_id: str
    range_m: float


@dataclass(frozen=True, slots=True)
class VerifyVerdict:
    """Result of one :meth:`LockOnVerifySession.observe` call."""

    state: ApproachVerifyState
    reason: str
    admitted: bool
    fresh: bool
    confirming_views: int
    fresh_views: int
    cleared_checkpoints: tuple[float, ...]
    pending_checkpoints: tuple[float, ...]
    covariance_trace: float
    reference_range_m: float
    refinement: RefinementVerdict

    @property
    def verified(self) -> bool:
        return self.state is ApproachVerifyState.VERIFIED

    @property
    def refuted(self) -> bool:
        return self.state is ApproachVerifyState.REJECTED

    @property
    def veto(self) -> bool:
        """A refutation vetoes the lock-on proposal (flush + resume search)."""

        return self.refuted


class LockOnVerifySession:
    """Verify-on-approach for ONE lock-on proposal against ONE reference.

    States are :class:`~parcel_robot.instructnav.scoring.ApproachVerifyState` —
    the stratum-2 approach/verify vocabulary already in the scorer, not a
    second enum. ``REJECTED`` is terminal (the proposal is vetoed).
    ``VERIFIED`` is **not**: every later view still runs the refinement gate,
    which is the direct fix for the measured "once committed the session
    returns ``None`` forever, no re-verification on approach" defect
    (record §2.1(3)).
    """

    def __init__(
        self,
        reference: GroundedReference,
        *,
        config: LockOnVerifyConfig | None = None,
        identity_fn: Callable[[ApproachView], float | None] | None = None,
    ) -> None:
        self.reference = reference
        self.config = config if config is not None else LockOnVerifyConfig()
        self.identity_fn = identity_fn
        self._checkpoints = reference.checkpoint_radii_m()
        self._state = ApproachVerifyState.APPROACH
        self._cleared: list[float] = []
        self._last_admitted: ApproachView | None = None
        self._last_fresh: ApproachView | None = None
        self._confirming_views = 0
        self._fresh_views = 0
        self._baseline_trace: float | None = None
        self._negative: NegativeEvidence | None = None

    @property
    def state(self) -> ApproachVerifyState:
        return self._state

    @property
    def checkpoints_m(self) -> tuple[float, ...]:
        return self._checkpoints

    @property
    def cleared_checkpoints(self) -> tuple[float, ...]:
        return tuple(self._cleared)

    @property
    def pending_checkpoints(self) -> tuple[float, ...]:
        return tuple(r for r in self._checkpoints if r not in self._cleared)

    @property
    def confirming_views(self) -> int:
        """Views admitted under the M-of-N angular quantum."""

        return self._confirming_views

    @property
    def fresh_views(self) -> int:
        return self._fresh_views

    def negative_evidence(self) -> NegativeEvidence | None:
        """The refutation record, once refuted; ``None`` otherwise."""

        return self._negative

    def reanchor(self, dx: float, dy: float) -> GroundedReference:
        """Move the reference with its landmark; keep every verdict so far.

        **Card AF-2, 2026-08-11. Provenance:**
        ``scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md``, should-fix 3. Called by
        the pipeline's ``_reanchor_landmark_goal`` in the SAME transaction that
        translates the goal, the arrival region and the candidate position, so
        the verify session can never be left checking a healthy estimate against
        a pre-drift centre.

        Verify STATE is deliberately preserved — cleared checkpoints stay
        cleared, the covariance baseline and the admitted/fresh view history
        stay as they are. A frame correction is not evidence about the target,
        so it neither clears nor confirms anything; it only says where the
        target has been all along. The schedule itself is position-independent
        (it derives from the radius, label, relation and band), so it does not
        move either.
        """

        self.reference = self.reference.translated(dx, dy)
        return self.reference

    def reset(self) -> None:
        self._state = ApproachVerifyState.APPROACH
        self._cleared.clear()
        self._last_admitted = None
        self._last_fresh = None
        self._confirming_views = 0
        self._fresh_views = 0
        self._baseline_trace = None
        self._negative = None

    def observe(self, view: ApproachView) -> VerifyVerdict:
        """Feed one approach view; returns the verdict for this tick."""

        if not isinstance(view, ApproachView):
            raise TypeError("view must be an ApproachView")

        refinement = refinement_gate(self.reference, view.fused_xy, covariance=view.covariance)
        reference_range = self.reference.range_from(view.robot_xy)

        if self._state is ApproachVerifyState.REJECTED:
            return self._verdict("already_refuted", view, refinement, reference_range, False, False)

        if refinement.rejected:
            return self._refute(refinement.reason, view, refinement, reference_range, False, False)

        admitted = admits_for_confirmation(self._last_admitted, view)
        fresh = is_fresh_observation(self._last_fresh, view)
        if admitted:
            self._confirming_views += 1
            self._last_admitted = view
        if fresh:
            self._fresh_views += 1
            self._last_fresh = view

        if self._state is ApproachVerifyState.VERIFIED:
            # Re-verification never stops: the gate above already ran.
            return self._verdict("verified_still_consistent", view, refinement, reference_range,
                                 admitted, fresh)

        if not fresh:
            return self._verdict("view_not_independent", view, refinement, reference_range,
                                 admitted, fresh)

        if self._baseline_trace is None:
            # The first independent view sets the covariance baseline. Nothing
            # can be "shrinking" before it, so no checkpoint clears here — a
            # session that starts inside a checkpoint still has to demonstrate
            # shrink on its next independent view.
            self._baseline_trace = view.covariance_trace
            return self._verdict("baseline_view", view, refinement, reference_range,
                                 admitted, fresh)

        due = tuple(r for r in self.pending_checkpoints if reference_range <= r)
        if due:
            failure = self._checkpoint_failure(view)
            if failure is not None:
                return self._refute(failure, view, refinement, reference_range, admitted, fresh)
            self._cleared.extend(due)
            self._baseline_trace = view.covariance_trace
            if not self.pending_checkpoints:
                self._state = ApproachVerifyState.VERIFIED
                return self._verdict("all_checkpoints_cleared", view, refinement, reference_range,
                                     admitted, fresh)
            self._state = ApproachVerifyState.VERIFY
            return self._verdict("checkpoint_cleared", view, refinement, reference_range,
                                 admitted, fresh)

        return self._verdict("approaching", view, refinement, reference_range, admitted, fresh)

    def _checkpoint_failure(self, view: ApproachView) -> str | None:
        """The three demands a checkpoint makes of fresh evidence."""

        if not view.persistence:
            return "persistence_miss_at_checkpoint"
        assert self._baseline_trace is not None
        if not view.covariance_trace < self._baseline_trace:
            # Covers both "increased" and "did not shrink" — the measured V-B
            # phantom does the latter while the body closes on the reference.
            return "covariance_did_not_shrink_at_checkpoint"
        score = view.identity_score
        if score is None and self.identity_fn is not None:
            score = self.identity_fn(view)
        if score is not None and float(score) < self.config.identity_threshold:
            return "identity_recheck_failed_at_checkpoint"
        return None

    def _refute(
        self,
        reason: str,
        view: ApproachView,
        refinement: RefinementVerdict,
        reference_range: float,
        admitted: bool,
        fresh: bool,
    ) -> VerifyVerdict:
        self._state = ApproachVerifyState.REJECTED
        self._negative = NegativeEvidence(
            label=self.reference.label or self.reference.landmark_id,
            world_xy=(float(view.fused_xy[0]), float(view.fused_xy[1])),
            reason=reason,
            landmark_id=self.reference.landmark_id,
            range_m=reference_range,
        )
        return self._verdict(reason, view, refinement, reference_range, admitted, fresh)

    def _verdict(
        self,
        reason: str,
        view: ApproachView,
        refinement: RefinementVerdict,
        reference_range: float,
        admitted: bool,
        fresh: bool,
    ) -> VerifyVerdict:
        return VerifyVerdict(
            state=self._state,
            reason=reason,
            admitted=admitted,
            fresh=fresh,
            confirming_views=self._confirming_views,
            fresh_views=self._fresh_views,
            cleared_checkpoints=self.cleared_checkpoints,
            pending_checkpoints=self.pending_checkpoints,
            covariance_trace=view.covariance_trace,
            reference_range_m=reference_range,
            refinement=refinement,
        )


def _mahalanobis(
    point: tuple[float, float],
    center: tuple[float, float],
    covariance: Covariance2 | None,
) -> float | None:
    """Mahalanobis distance, or ``None`` when the covariance is degenerate."""

    if covariance is None:
        return None
    a, b = float(covariance[0][0]), float(covariance[0][1])
    c, d = float(covariance[1][0]), float(covariance[1][1])
    determinant = a * d - b * c
    if not math.isfinite(determinant) or determinant <= 0.0:
        return None
    dx = point[0] - center[0]
    dy = point[1] - center[1]
    quadratic = (d * dx * dx - (b + c) * dx * dy + a * dy * dy) / determinant
    if not math.isfinite(quadratic) or quadratic < 0.0:
        return None
    return math.sqrt(quadratic)


def _validate_covariance(value: Covariance2) -> None:
    rows = tuple(value)
    if len(rows) != 2 or any(len(row) != 2 for row in rows):
        raise ValueError("covariance must be 2x2")
    a, b = float(rows[0][0]), float(rows[0][1])
    c, d = float(rows[1][0]), float(rows[1][1])
    if not all(math.isfinite(v) for v in (a, b, c, d)):
        raise ValueError("covariance entries must be finite")
    if a < 0.0 or d < 0.0:
        raise ValueError("covariance diagonal must be non-negative")


def _finite_xy(value: tuple[float, float], name: str) -> None:
    if len(value) < 2:
        raise ValueError(f"{name} must be an (x, y) pair")
    if not (math.isfinite(float(value[0])) and math.isfinite(float(value[1]))):
        raise ValueError(f"{name} must be finite")


def _wrap_pi(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi
