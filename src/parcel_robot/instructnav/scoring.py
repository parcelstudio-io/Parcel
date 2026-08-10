"""Episode scoring, goal-region predicates, and failure attribution (pure)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from parcel_robot.authority import DEFAULT_STAND_OFF_ENVELOPE

# Canonical relation bands — single arrival authority with city_semantics /
# pipeline / NAV_INSTRUCT scorer (K0). Never maintain parallel radii.
#
# NEXT_TO_BAND_M IS MEASURED TO THE ANCHOR'S *SURFACE* (2026-08-09, card S-1),
# which is what every stand-off authority in `parcel_robot.authority` is
# measured to. It used to be measured to the anchor's *centre*, and that made
# the band's usable width depend on how big the anchor is: for an anchor of
# circumscribed radius R the outer edge stayed put while the inner edge was
# pushed out by R, so past R = 0.38 m at Go2 scale `next_to`'s outer edge lay
# *inside* `near`'s inner edge and the two relations named incompatible
# regions. Measured 2026-08-08 (card B-1): `lamppost` (0.06) was the only
# city_block class that cleared it; `planter` (0.45), `tree` (0.58), `bench`
# (0.734) and every `building` (1.84-2.41) had an empty `next_to` region.
#
# The band's WIDTH (1.1 m) is a property of the relation, not of the anchor.
# `next_to_band_from_centre` is the ONE place the surface band is materialised
# into the anchor-centre coordinates every consumer works in; nothing else may
# add an offset. TOWARDS_BAND_M is deliberately still centre-anchored: it is a
# motion-stopped-short band around a *position*, and its region is built with
# `anchor_footprint_m = 0.0`.
NEXT_TO_BAND_M: tuple[float, float] = (0.4, 1.5)
TOWARDS_BAND_M: tuple[float, float] = (0.6, 2.5)

#: Posture names that count as "sitting" for the compound placement+posture
#: predicate. Compared case-insensitively after stripping separators, so
#: ``Sit``/``sit_down``/``SITTING`` all match the same posture.
SIT_POSTURE_ALIASES: frozenset[str] = frozenset({"sit", "sitting", "sitdown", "situp"})

#: Generous facing tolerance for social predicates (±60°). Deliberately loose:
#: a settled dog whose body is angled but whose head is on the owner reads as
#: "facing" to a person, and the yaw estimate is a body yaw, not a gaze vector.
FACING_TOLERANCE_RAD: float = math.radians(60.0)

#: Radius of the owner-anchored approach disc. Matches the NAV_INSTRUCT
#: ``follow_owner`` disc radius so the two loops cannot disagree on "at the
#: owner"; the difference is only that this one is anchored to an observed
#: owner position instead of the generator's frozen (2.0, -0.5).
OWNER_ARRIVAL_RADIUS_M: float = 1.8

#: Version of the scoring contract itself, so a derived re-scoring row can name
#: which scorer produced it without anyone having to diff the module. Bump on
#: any change to success, failure classification, or the recorded fields.
#: v1.2 added ``false_arrival`` + the differential-authority verdict fields;
#: it changes classification of failures only, never ``success``.
#: v1.3 added the stratum-2 arrival *evidence* layer (:class:`ArrivalEvidence`,
#: :func:`evidence_arrival_verified`, :class:`FalsePositiveMemory`). It adds a
#: requirement to the navigator's K0 predicate; it does not change how a
#: recorded trace is scored, so every persisted row re-scores identically.
#: v1.4 adds chance-constrained ``GoalRegion.contains`` under optional D2
#: anchor covariance (``P(inside) >= INSIDE_PROBABILITY_THRESHOLD``). The
#: zero-covariance / omitted-covariance path is the identical boolean test
#: as v1.3 (T0 byte-equal); non-zero covariance is opt-in only.
SCORING_VERSION: str = "instructnav-scoring-v1.4-chance-constrained-k0"

#: Chance-constraint threshold for K0 membership under detection (D2) covariance.
#: STRATA Stratum-1: at zero covariance the predicate reduces to today's boolean.
INSIDE_PROBABILITY_THRESHOLD: float = 0.9

#: ``M``-of-``N`` confirming-frame requirement for an arrival claim. Same shape
#: and same numbers as the tracker's confirmation rule
#: (``navigation.tracker.TrackerConfig``) — deliberately the same, because a
#: target that is not confirmed enough to *track* is not confirmed enough to
#: *arrive at*, and two different M-of-N rules would be a second authority.
ARRIVAL_CONFIRMING_FRAMES_M: int = 3
ARRIVAL_CONFIRMING_WINDOW_N: int = 5

#: Ceiling on the fraction of a target's observations that may disagree with
#: its dominant class before the arrival claim is refused. A third of frames
#: calling the "bench" something else is not a verified bench. Chosen as the
#: point where the dominant label stops being a majority under the 3-of-5 rule
#: (2 of 5 = 0.4), stepped down one frame to 1 of 3.
ARRIVAL_MAX_OTHER_CLASS_FRACTION: float = 1.0 / 3.0

#: Grid pitch for the false-positive memory. One metre matches the ObjectNav
#: arrival radius, so "the place I already rejected" is the same resolution as
#: "the place I would call arrival".
FALSE_POSITIVE_CELL_M: float = 1.0

#: Boundary tolerance zone for differential-authority verdicts (U32 / eval
#: instrument 5). The scorer's ``GoalRegion`` predicate and the navigator's own
#: terminal verification run on the same nominal geometry but sample the pose at
#: slightly different instants, so a pose within this band of the region
#: boundary is *not* evidence that the two authorities disagree — it is
#: quantisation. 0.05 m is half the 0.1 s control tick travelled at the ~1 m/s
#: cruise speed rounded down; it is deliberately much smaller than every arrival
#: band in this module (the narrowest, ``NEXT_TO_BAND_M``, is 1.1 m wide), so it
#: can never swallow a real disagreement.
ARRIVAL_BOUNDARY_EPSILON_M: float = 0.05

#: Mission/task terminal statuses that constitute a *claim of arrival* by the
#: navigator (the "system" authority in the differential check).
SYSTEM_ARRIVAL_STATUSES: frozenset[str] = frozenset({"arrived", "succeeded"})

#: Terminal reasons that constitute a claim of arrival even when the status is
#: a generic completion. ``tracking_owner`` is deliberately absent: a follow
#: that is still tracking has not asserted that it arrived anywhere.
SYSTEM_ARRIVAL_REASONS: frozenset[str] = frozenset(
    {"arrived", "arrived_verified", "at_follow_distance", "goal_reached"}
)


class FailureClass(str, Enum):
    GROUNDING_ERROR = "grounding_error"
    SEARCH_ERROR = "search_error"
    PLANNING_ERROR = "planning_error"
    CONTROL_ERROR = "control_error"
    TERMINATION = "termination"
    REFUSAL = "refusal"
    #: Claim-without-predicate (U32): the mission reported arrival while the K0
    #: GoalRegion predicate puts the final pose outside the region by more than
    #: :data:`ARRIVAL_BOUNDARY_EPSILON_M`. Never ``planning_error`` — a false
    #: arrival is a *verification* defect, and bucketing it with genuine
    #: navigation shortfalls is what hid it in the headline SR.
    FALSE_ARRIVAL = "false_arrival"
    NONE = "none"


class AuthorityCategory(str, Enum):
    """Differential-authority verdict category (eval instrument 5).

    The scorer is a *derived view* of arrival, not a peer of the navigator, so
    the invariant is one-way: ``scorer_arrival ⇒ system_arrival``. Every
    episode records both verdicts and the category below; only
    :attr:`FALSE_ARRIVAL` is also a failure class, because only it means the
    system asserted something untrue.
    """

    #: Both authorities agree (both arrived, or neither).
    AGREEMENT = "agreement"
    #: The two verdicts differ but the final pose is within
    #: :data:`ARRIVAL_BOUNDARY_EPSILON_M` of the region boundary — quantisation,
    #: not disagreement.
    TOLERATED_BOUNDARY = "tolerated_boundary"
    #: Scorer says arrived, system does not, and the pose is well inside the
    #: region. The one-way implication is violated.
    AUTHORITY_DISAGREEMENT = "authority_disagreement"
    #: System says arrived, scorer says the pose is well outside the region.
    FALSE_ARRIVAL = "false_arrival"
    #: No system verdict was supplied — the check was not measurable.
    UNKNOWN = "unknown"


class AttributionLayer(str, Enum):
    """L1–L6 refinement used by oracle counterfactual replay."""

    L1_PARSE = "L1_parse"
    L2A_VOCABULARY = "L2a_vocabulary"
    L2B_VISIBILITY = "L2b_visibility_gated"
    L3_EXPLORATION = "L3_exploration"
    L4_PLANNING = "L4_planning"
    L5_CONTROL = "L5_control"
    L6_TERMINATION = "L6_termination"
    NONE = "none"


@dataclass(frozen=True)
class GoalRegion:
    """The one arrival region shape. Every relation builds one of these.

    **``band_m`` on a ``relative_band`` is ALWAYS a distance to the anchor's
    CENTRE, and there is no second convention.** A relation whose band is
    naturally expressed against the anchor's *surface* — ``next_to``, and every
    ``near`` band, which is written as ``R + <composite>`` — materialises it
    into centre coordinates at construction time
    (:func:`next_to_band_from_centre` for ``next_to``,
    :func:`object_near_envelope_m` for ``near``). Nothing downstream carries a
    mode flag, so a persisted region cannot be re-read under the wrong
    convention and a consumer that reads ``band_m`` raw cannot be wrong about
    what it means.

    ``anchor_footprint_m`` is the anchor's own circumscribed radius. It is kept
    on the region because the predicates need it as a *guard* (never stand
    inside the anchor) and because the failure-attribution layer reports it —
    it is not a second copy of the band.
    """

    kind: str  # "disc" | "polygon" | "relative_band"
    center: tuple[float, float] | None = None
    radius_m: float | None = None
    polygon: tuple[tuple[float, float], ...] | None = None
    anchor_entity: str | None = None
    #: ``(lo, hi)`` distances to the anchor CENTRE. See the class docstring.
    band_m: tuple[float, float] | None = None
    anchor_footprint_m: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in {"disc", "polygon", "relative_band"}:
            raise ValueError(f"unsupported GoalRegion kind: {self.kind!r}")
        if self.kind == "disc":
            if self.center is None or self.radius_m is None:
                raise ValueError("disc GoalRegion requires center and radius_m")
            if not math.isfinite(self.radius_m) or self.radius_m <= 0.0:
                raise ValueError("disc radius_m must be finite and positive")
            _finite_xy(self.center)
        elif self.kind == "polygon":
            if self.polygon is None or len(self.polygon) < 3:
                raise ValueError("polygon GoalRegion requires ≥3 vertices")
            for point in self.polygon:
                _finite_xy(point)
        else:
            if self.band_m is None:
                raise ValueError("relative_band GoalRegion requires band_m")
            lo, hi = float(self.band_m[0]), float(self.band_m[1])
            if not (math.isfinite(lo) and math.isfinite(hi) and 0.0 <= lo < hi):
                raise ValueError("relative_band band_m must satisfy 0 ≤ min < max")
            if self.anchor_footprint_m < 0.0 or not math.isfinite(self.anchor_footprint_m):
                raise ValueError("anchor_footprint_m must be finite and ≥ 0")

    def contains(
        self,
        x: float,
        y: float,
        anchor_xy: tuple[float, float] | None = None,
        *,
        anchor_covariance: (
            tuple[tuple[float, float], tuple[float, float]] | None
        ) = None,
        probability_threshold: float = INSIDE_PROBABILITY_THRESHOLD,
    ) -> bool:
        """K0 membership — boolean at zero cov; ``P(inside)≥τ`` under D2 cov.

        ``anchor_covariance`` is the 2×2 world-frame covariance of the region's
        anchor (D2 fused target position). When omitted or numerically zero this
        is the *identical* boolean geometry the system has always used (T0
        byte-equal). With non-zero covariance it is the single chance-constrained
        upgrade — no second arrival authority.
        """

        exact = self._contains_exact(x, y, anchor_xy=anchor_xy)
        if not _has_nonzero_covariance(anchor_covariance):
            return exact
        if not math.isfinite(float(probability_threshold)) or not (
            0.0 <= float(probability_threshold) <= 1.0
        ):
            raise ValueError("probability_threshold must be in [0, 1]")
        return (
            p_inside_goal_region(
                x,
                y,
                self,
                anchor_xy=anchor_xy,
                anchor_covariance=anchor_covariance,
            )
            >= float(probability_threshold)
        )

    def _contains_exact(
        self,
        x: float,
        y: float,
        anchor_xy: tuple[float, float] | None = None,
    ) -> bool:
        if not (math.isfinite(x) and math.isfinite(y)):
            return False
        if self.kind == "disc":
            assert self.center is not None and self.radius_m is not None
            return math.hypot(x - self.center[0], y - self.center[1]) <= self.radius_m
        if self.kind == "polygon":
            assert self.polygon is not None
            return _point_in_polygon((x, y), self.polygon)
        anchor = anchor_xy if anchor_xy is not None else self.center
        if anchor is None or self.band_m is None:
            return False
        dist = math.hypot(x - anchor[0], y - anchor[1])
        lo, hi = float(self.band_m[0]), float(self.band_m[1])
        footprint = float(self.anchor_footprint_m)
        # Must sit in the band and not overlap the anchor footprint.
        return lo <= dist <= hi and dist >= footprint

    def distance_to(
        self,
        x: float,
        y: float,
        anchor_xy: tuple[float, float] | None = None,
    ) -> float:
        if not (math.isfinite(x) and math.isfinite(y)):
            return float("inf")
        if self._contains_exact(x, y, anchor_xy=anchor_xy):
            return 0.0
        if self.kind == "disc":
            assert self.center is not None and self.radius_m is not None
            return max(
                0.0,
                math.hypot(x - self.center[0], y - self.center[1]) - self.radius_m,
            )
        if self.kind == "polygon":
            assert self.polygon is not None
            return _distance_to_polygon((x, y), self.polygon)
        anchor = anchor_xy if anchor_xy is not None else self.center
        if anchor is None or self.band_m is None:
            return float("inf")
        dist = math.hypot(x - anchor[0], y - anchor[1])
        lo, hi = float(self.band_m[0]), float(self.band_m[1])
        footprint = float(self.anchor_footprint_m)
        # Distance to the nearest admissible ring point (outside footprint).
        target_r = max(lo, footprint)
        if dist < target_r:
            return target_r - dist
        if dist > hi:
            return dist - hi
        return 0.0

    def signed_distance_to_boundary(
        self,
        x: float,
        y: float,
        anchor_xy: tuple[float, float] | None = None,
    ) -> float:
        """Distance to the region boundary, **negative inside**.

        :meth:`distance_to` saturates at 0 inside the region, which cannot
        express "inside, but 1 cm from the edge". The differential-authority
        check needs exactly that: a verdict split is only meaningful when the
        pose is more than :data:`ARRIVAL_BOUNDARY_EPSILON_M` from the boundary
        on either side. Sign convention: ``< 0`` inside, ``> 0`` outside, and
        ``abs(...)`` is the distance to the nearest boundary point.
        """

        if not (math.isfinite(x) and math.isfinite(y)):
            return float("inf")
        if self.kind == "disc":
            assert self.center is not None and self.radius_m is not None
            return math.hypot(x - self.center[0], y - self.center[1]) - self.radius_m
        if self.kind == "polygon":
            assert self.polygon is not None
            edge = _distance_to_polygon_edges((x, y), self.polygon)
            return -edge if _point_in_polygon((x, y), self.polygon) else edge
        anchor = anchor_xy if anchor_xy is not None else self.center
        if anchor is None or self.band_m is None:
            return float("inf")
        dist = math.hypot(x - anchor[0], y - anchor[1])
        lo = max(float(self.band_m[0]), float(self.anchor_footprint_m))
        hi = float(self.band_m[1])
        if lo > hi:  # footprint swallows the band — the region is empty.
            return max(lo - dist, dist - hi)
        if dist < lo:
            return lo - dist
        if dist > hi:
            return dist - hi
        return -min(dist - lo, hi - dist)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "center": list(self.center) if self.center is not None else None,
            "radius_m": self.radius_m,
            "polygon": [list(p) for p in self.polygon] if self.polygon is not None else None,
            "anchor_entity": self.anchor_entity,
            "band_m": list(self.band_m) if self.band_m is not None else None,
            "anchor_footprint_m": self.anchor_footprint_m,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> GoalRegion:
        center_raw = data.get("center")
        center = (
            (float(center_raw[0]), float(center_raw[1]))
            if isinstance(center_raw, (list, tuple)) and len(center_raw) >= 2
            else None
        )
        polygon_raw = data.get("polygon")
        polygon = None
        if isinstance(polygon_raw, (list, tuple)) and polygon_raw:
            polygon = tuple((float(p[0]), float(p[1])) for p in polygon_raw)
        band_raw = data.get("band_m")
        band = (
            (float(band_raw[0]), float(band_raw[1]))
            if isinstance(band_raw, (list, tuple)) and len(band_raw) >= 2
            else None
        )
        radius = data.get("radius_m")
        return cls(
            kind=str(data["kind"]),
            center=center,
            radius_m=float(radius) if radius is not None else None,
            polygon=polygon,
            anchor_entity=(
                str(data["anchor_entity"]) if data.get("anchor_entity") is not None else None
            ),
            band_m=band,
            anchor_footprint_m=float(data.get("anchor_footprint_m") or 0.0),
        )


def objectnav_arrival_radius_m(object_radius_m: float = 0.0) -> float:
    """The community ObjectNav arrival radius, derived rather than written.

    The ObjectNav evaluation criterion is "within 1.0 m of the object". That
    1.0 m is not a free literal here: it is
    ``StandOffEnvelope.vicinity_margin_m``, the same authority field the near
    envelope already uses, so a scaled robot's arrival radius scales with its
    envelope instead of staying pinned to a Go2 number. The object's own radius
    is added because the criterion is a distance to the object's *surface*.
    """

    radius = float(object_radius_m)
    if not math.isfinite(radius) or radius < 0.0:
        raise ValueError("object_radius_m must be finite and >= 0")
    return float(DEFAULT_STAND_OFF_ENVELOPE.vicinity_margin_m) + radius


class ApproachVerifyState(str, Enum):
    """Stubborn-style approach-then-verify state for one committed target.

    A single-frame sighting is enough to *approach* something and never enough
    to *claim* it. The system used to have only the first half: one RESOLVED
    grounding committed a goal, and arrival was a geometry question from then
    on. These are the three states the evidence layer distinguishes.
    """

    #: Committed and being approached; evidence is still accumulating.
    APPROACH = "approach"
    #: Geometry satisfied; the evidence test is the remaining question.
    VERIFY = "verify"
    #: Evidence sufficient — this is the only state K0 may claim arrival in.
    VERIFIED = "verified"
    #: Evidence refuted the target. It goes to the false-positive memory.
    REJECTED = "rejected"


@dataclass(frozen=True)
class ArrivalEvidence:
    """Cumulative per-candidate evidence behind one arrival claim.

    Every field is a *count or a mean over frames*, never a single frame's
    reading. That is the whole point: the literal ``0.98`` that used to satisfy
    every confidence check was a per-frame number no accumulation could
    contradict.
    """

    #: Frames on which this target was associated with any detection.
    frames_seen: int = 0
    #: Sum of detection scores over those frames.
    cumulative_confidence: float = 0.0
    #: Fraction of observations that disagreed with the dominant class label.
    max_other_class: float = 0.0
    #: Hits within the last ``ARRIVAL_CONFIRMING_WINDOW_N`` opportunities.
    confirming_frames: int = 0
    #: Whether the target is associated in the frame the claim is made on.
    visible: bool = False

    def __post_init__(self) -> None:
        if self.frames_seen < 0:
            raise ValueError("frames_seen must be >= 0")
        if self.confirming_frames < 0:
            raise ValueError("confirming_frames must be >= 0")
        if not math.isfinite(self.cumulative_confidence) or self.cumulative_confidence < 0.0:
            raise ValueError("cumulative_confidence must be finite and >= 0")
        if not 0.0 <= self.max_other_class <= 1.0:
            raise ValueError("max_other_class must be in [0, 1]")

    @property
    def mean_confidence(self) -> float:
        if self.frames_seen <= 0:
            return 0.0
        return float(self.cumulative_confidence) / float(self.frames_seen)

    def as_dict(self) -> dict[str, Any]:
        return {
            "frames_seen": int(self.frames_seen),
            "cumulative_confidence": float(self.cumulative_confidence),
            "mean_confidence": float(self.mean_confidence),
            "max_other_class": float(self.max_other_class),
            "confirming_frames": int(self.confirming_frames),
            "visible": bool(self.visible),
        }


@dataclass(frozen=True)
class EvidenceVerdict:
    """Outcome of the evidence half of the ONE K0 arrival predicate."""

    state: ApproachVerifyState
    reason: str
    evidence: ArrivalEvidence

    @property
    def verified(self) -> bool:
        return self.state is ApproachVerifyState.VERIFIED

    @property
    def rejected(self) -> bool:
        return self.state is ApproachVerifyState.REJECTED

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "reason": self.reason,
            **self.evidence.as_dict(),
        }


def evidence_arrival_verified(
    evidence: ArrivalEvidence,
    *,
    minimum_confidence: float,
    confirming_frames_m: int = ARRIVAL_CONFIRMING_FRAMES_M,
    max_other_class: float = ARRIVAL_MAX_OTHER_CLASS_FRACTION,
    require_visible: bool = True,
) -> EvidenceVerdict:
    """The evidence half of K0. Fail-closed at every branch.

    Three questions, in the order that makes the answer cheapest to explain:

    1. **visibility** — is the target associated in *this* frame? (ObjectNav's
       viewability term; a claim made about something currently unobserved is
       a claim about memory, not about the world.)
    2. **``M``-of-``N``** — has it been confirmed across frames, not once?
    3. **evidence quality** — does the *mean* score clear the threshold, and do
       the class labels agree with themselves?

    Question 3 is where the calibrated threshold lands. A single frame at 0.98
    passes nothing here; a target seen five times at a mean 0.62 does, if 0.62
    is above the threshold the known-absent trials produced.

    ``REJECTED`` is returned only for *class disagreement* — the one signal
    that says "this is not what you think it is" rather than "you do not yet
    know". Not-yet-enough is ``APPROACH``/``VERIFY``, which keeps looking.
    """

    threshold = float(minimum_confidence)
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError("minimum_confidence must be in [0, 1]")
    if confirming_frames_m < 1:
        raise ValueError("confirming_frames_m must be >= 1")
    if not 0.0 <= float(max_other_class) <= 1.0:
        raise ValueError("max_other_class must be in [0, 1]")

    if evidence.max_other_class > float(max_other_class):
        return EvidenceVerdict(
            ApproachVerifyState.REJECTED, "class_disagreement", evidence
        )
    if require_visible and not evidence.visible:
        return EvidenceVerdict(
            ApproachVerifyState.APPROACH, "target_not_visible", evidence
        )
    if evidence.confirming_frames < int(confirming_frames_m):
        return EvidenceVerdict(
            ApproachVerifyState.VERIFY, "insufficient_confirming_frames", evidence
        )
    if evidence.frames_seen <= 0 or evidence.mean_confidence < threshold:
        return EvidenceVerdict(
            ApproachVerifyState.VERIFY, "insufficient_mean_confidence", evidence
        )
    return EvidenceVerdict(ApproachVerifyState.VERIFIED, "evidence_sufficient", evidence)


class FalsePositiveMemory:
    """Places that were checked and found not to hold what was claimed.

    VLFM names false-positive sensitivity as the open weakness at SOTA: a
    detector fires on the wrong thing, the robot walks to it, discovers the
    mistake, replans — and grounds on the same phantom again, forever. Nothing
    in this system remembered a rejection.

    Keyed by **map location** (a ``FALSE_POSITIVE_CELL_M`` grid cell) and label,
    not by candidate id, because an id is exactly the thing a detector does not
    provide. A rejection therefore survives the target being re-detected under
    a fresh id, which is the only version of "never re-tricked" that means
    anything.
    """

    def __init__(self, *, cell_m: float = FALSE_POSITIVE_CELL_M, max_entries: int = 256) -> None:
        cell = float(cell_m)
        if not math.isfinite(cell) or cell <= 0.0:
            raise ValueError("cell_m must be finite and positive")
        if int(max_entries) < 1:
            raise ValueError("max_entries must be >= 1")
        self.cell_m = cell
        self.max_entries = int(max_entries)
        self._entries: dict[tuple[int, int, str], dict[str, Any]] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def key(self, x: float, y: float, label: str) -> tuple[int, int, str]:
        if not (math.isfinite(float(x)) and math.isfinite(float(y))):
            raise ValueError("false-positive memory needs a finite location")
        return (
            math.floor(float(x) / self.cell_m),
            math.floor(float(y) / self.cell_m),
            _normalized_label(label),
        )

    def reject(self, x: float, y: float, label: str, *, reason: str = "") -> None:
        key = self.key(x, y, label)
        entry = self._entries.get(key)
        if entry is None:
            if len(self._entries) >= self.max_entries:
                self._entries.pop(next(iter(self._entries)))
            self._entries[key] = {
                "x": float(x),
                "y": float(y),
                "label": str(label),
                "reason": str(reason),
                "count": 1,
            }
            return
        entry["count"] = int(entry["count"]) + 1
        entry["reason"] = str(reason) or entry["reason"]

    def is_rejected(self, x: float, y: float, label: str) -> bool:
        """Has this label already been refuted at this place?

        Checks the containing cell and its eight neighbours, so a target
        re-detected 20 cm across a cell boundary is still the same rejection.
        """

        cx, cy, norm = self.key(x, y, label)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if (cx + dx, cy + dy, norm) in self._entries:
                    return True
        return False

    def entries(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(entry) for entry in self._entries.values())

    def clear(self) -> None:
        self._entries.clear()


def _normalized_label(label: object) -> str:
    return "".join(ch for ch in str(label).lower() if ch.isalnum())


def object_near_envelope_m(
    object_radius_m: float,
    *,
    label: str = "",
) -> tuple[float, float, float]:
    """Return ``(stand_off_m, minimum_vicinity_m, vicinity_m)`` for near-object goals.

    Shared by city_semantics metadata and the NAV_INSTRUCT episode generator so
    navigator verification and the scorer cannot disagree on the envelope.

    Every term is a named field of the
    :class:`~parcel_robot.core.authority.StandOffEnvelope` authority. The
    composite used to read ``radius + 0.32 + 0.8 + 0.06 + 0.04`` with the
    lamppost case written as the bare literal ``1.32`` — which embedded the
    0.32 footprint by value, so a scaled robot silently kept a Go2 stand-off.
    The decomposition is bit-for-bit identical at Go2 scale (the lamppost
    branch is exactly ``vicinity(0.0)``: ``0.32 + 1.0 == 1.32`` in IEEE-754
    double); ``tests/test_authority_family_equality.py`` pins it.
    """

    radius = float(object_radius_m)
    if not math.isfinite(radius) or radius < 0.0:
        raise ValueError("object_radius_m must be finite and ≥ 0")
    envelope = DEFAULT_STAND_OFF_ENVELOPE
    stand_off = envelope.stand_off(radius)
    if label == "lamppost":
        stand_off = envelope.point_anchor_stand_off()
    minimum = envelope.minimum_vicinity(radius)
    vicinity = envelope.vicinity(radius)
    if label == "building":
        stand_off = max(stand_off, envelope.vicinity(radius))
        vicinity = max(vicinity, stand_off + envelope.building_vicinity_pad_m)
        minimum = max(minimum, envelope.minimum_vicinity(radius))
    vicinity = max(vicinity, stand_off)
    if minimum > vicinity:
        raise ValueError("near envelope collapsed: minimum_vicinity > vicinity")
    return float(stand_off), float(minimum), float(vicinity)


def object_near_goal_region(
    center: tuple[float, float],
    object_radius_m: float,
    *,
    label: str = "",
    entity_id: str | None = None,
) -> GoalRegion:
    """Arrival authority for ``near`` object goals (relative band, not a bare radius).

    Membership is :meth:`GoalRegion.contains`. Under D2 detection covariance that
    becomes ``P(inside) >= INSIDE_PROBABILITY_THRESHOLD``; at zero covariance it
    is today's boolean point-in-band test (T0 byte-equal).
    """

    _finite_xy(center)
    _, minimum, vicinity = object_near_envelope_m(object_radius_m, label=label)
    return GoalRegion(
        kind="relative_band",
        center=(float(center[0]), float(center[1])),
        band_m=(minimum, vicinity),
        anchor_entity=entity_id,
        anchor_footprint_m=float(object_radius_m),
    )


def _standard_normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(float(value) / math.sqrt(2.0)))


def _has_nonzero_covariance(
    covariance: tuple[tuple[float, float], tuple[float, float]] | None,
) -> bool:
    if covariance is None:
        return False
    try:
        sxx = float(covariance[0][0])
        sxy = float(covariance[0][1])
        syx = float(covariance[1][0])
        syy = float(covariance[1][1])
    except (TypeError, IndexError, ValueError):
        return False
    if not all(math.isfinite(v) for v in (sxx, sxy, syx, syy)):
        return False
    return max(abs(sxx), abs(sxy), abs(syx), abs(syy)) > 0.0


def p_inside_goal_region(
    x: float,
    y: float,
    region: GoalRegion,
    *,
    anchor_xy: tuple[float, float] | None = None,
    anchor_covariance: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> float:
    """``P(point inside region)`` under optional D2 anchor covariance.

    At zero / omitted covariance this returns exactly ``1.0`` or ``0.0`` matching
    :meth:`GoalRegion._contains_exact` — the reduction that keeps T0 byte-equal.
    For ``relative_band`` / ``disc`` with non-zero covariance, radial uncertainty
    is the projection ``nᵀ Σ n`` of the anchor covariance onto the robot→anchor
    unit vector (STRATA Stratum-1 half-space form).
    """

    if not _has_nonzero_covariance(anchor_covariance):
        return 1.0 if region._contains_exact(x, y, anchor_xy=anchor_xy) else 0.0

    assert anchor_covariance is not None
    sxx = float(anchor_covariance[0][0])
    sxy = 0.5 * (float(anchor_covariance[0][1]) + float(anchor_covariance[1][0]))
    syy = float(anchor_covariance[1][1])

    if region.kind == "polygon":
        # Polygon K0 under *robot* pose uncertainty lives in pose.py; D2 cov is
        # an anchor/target uncertainty. Without an edge-normal model for a
        # moving polygon, refuse (fail closed) rather than invent a second rule.
        return 0.0

    if region.kind == "disc":
        assert region.center is not None and region.radius_m is not None
        cx, cy = float(region.center[0]), float(region.center[1])
        dist = math.hypot(float(x) - cx, float(y) - cy)
        dx, dy = float(x) - cx, float(y) - cy
        if dist <= 1e-12:
            nx, ny = 1.0, 0.0
        else:
            nx, ny = dx / dist, dy / dist
        variance = max(0.0, nx * (sxx * nx + sxy * ny) + ny * (sxy * nx + syy * ny))
        if variance <= 0.0:
            return 1.0 if dist <= float(region.radius_m) else 0.0
        return _standard_normal_cdf((float(region.radius_m) - dist) / math.sqrt(variance))

    # relative_band — the near / next_to / towards K0 shape.
    anchor = anchor_xy if anchor_xy is not None else region.center
    if anchor is None or region.band_m is None:
        return 0.0
    cx, cy = float(anchor[0]), float(anchor[1])
    dx, dy = float(x) - cx, float(y) - cy
    dist = math.hypot(dx, dy)
    if dist <= 1e-12:
        nx, ny = 1.0, 0.0
    else:
        nx, ny = dx / dist, dy / dist
    variance = max(0.0, nx * (sxx * nx + sxy * ny) + ny * (sxy * nx + syy * ny))
    lo = max(float(region.band_m[0]), float(region.anchor_footprint_m))
    hi = float(region.band_m[1])
    if lo > hi:
        return 0.0
    if variance <= 0.0:
        return 1.0 if lo <= dist <= hi else 0.0
    sigma = math.sqrt(variance)
    # P(lo ≤ d ≤ hi) ≈ Φ((hi-d)/σ) · Φ((d-lo)/σ) under radial Gaussian approx.
    return _standard_normal_cdf((hi - dist) / sigma) * _standard_normal_cdf(
        (dist - lo) / sigma
    )


def region_inside_goal_region(
    polygon: Sequence[tuple[float, float]],
    *,
    entity_id: str | None = None,
) -> GoalRegion:
    poly = tuple((float(p[0]), float(p[1])) for p in polygon)
    return GoalRegion(kind="polygon", polygon=poly, anchor_entity=entity_id)


def next_to_band_from_centre(
    anchor_footprint_m: float,
    band_m: tuple[float, float] = NEXT_TO_BAND_M,
) -> tuple[float, float]:
    """The surface-relative ``next_to`` band, in anchor-CENTRE coordinates.

    **This is the one definition of where "beside it" is.** Every consumer —
    the goal region the scorer verifies against, the planning band the approach
    solver samples in, the achievability predicate, the owner-anchored variant
    — goes through this function, so planning and verification cannot disagree
    about the same metre. Nothing else may add an offset.

    The band's WIDTH (1.1 m at the shipping values) is a property of the
    *relation* and must not depend on how big the anchor is. Measuring it from
    the centre made it depend: the outer edge stayed at 1.5 m while the inner
    edge was pushed out by the anchor's radius, so a 0.734 m bench had 0.77 m
    of band left and an anchor of 1.5 m or more had none at all. Measured on
    ``city_block`` (card B-1, 2026-08-08), no anchor above 0.38 m had a single
    admissible pose anywhere on its perimeter.
    """

    radius = float(anchor_footprint_m)
    if not math.isfinite(radius) or radius < 0.0:
        raise ValueError("anchor_footprint_m must be finite and >= 0")
    lo, hi = float(band_m[0]), float(band_m[1])
    if not (math.isfinite(lo) and math.isfinite(hi) and 0.0 <= lo < hi):
        raise ValueError("next_to band_m must satisfy 0 <= min < max")
    return (lo + radius, hi + radius)


def object_next_to_goal_region(
    center: tuple[float, float],
    footprint_m: float,
    *,
    entity_id: str | None = None,
    band_m: tuple[float, float] = NEXT_TO_BAND_M,
) -> GoalRegion:
    """K0 arrival region for ``next_to``. ``band_m`` is surface-relative.

    The region it stamps carries the band already materialised into
    anchor-centre coordinates by :func:`next_to_band_from_centre`, because
    :class:`GoalRegion` has exactly one convention for ``band_m`` and this is
    the only place ``next_to`` converts into it.
    """

    _finite_xy(center)
    return GoalRegion(
        kind="relative_band",
        center=(float(center[0]), float(center[1])),
        band_m=next_to_band_from_centre(footprint_m, band_m),
        anchor_entity=entity_id,
        anchor_footprint_m=float(footprint_m),
    )


def next_to_band_surface_slack_m(
    *,
    band_m: tuple[float, float] = NEXT_TO_BAND_M,
    envelope: Any = DEFAULT_STAND_OFF_ENVELOPE,
) -> float:
    """How much of the ``next_to`` band a body can actually stand in, in metres.

    Solve :func:`next_to_is_achievable` for the margin::

        (R + band_hi) - minimum_vicinity(R)
            = band_hi - footprint_radius - target_surface_clearance

    ``R`` cancels — that is the whole point of surface-anchoring the band — so
    this is a property of the **body and the band**, not of the anchor. At the
    shipping values it is ``1.5 - 0.32 - 0.8 = 0.38 m``: the outer 0.38 m of
    the 1.1 m band is the part a Go2-sized body can occupy, around an anchor of
    any size. Negative means ``next_to`` is unachievable for *every* anchor,
    which is a statement about this embodiment, not about the scene.

    Historical note: the same expression used to be
    ``next_to_achievable_anchor_radius_m()`` and returned the same 0.38 — as a
    maximum *anchor radius*, because the band was centre-anchored. It is the
    same arithmetic reading a different question, which is why the function was
    renamed rather than kept alongside a second one.
    """

    return (
        float(band_m[1])
        - float(envelope.footprint_radius_m)
        - float(envelope.target_surface_clearance_m)
    )


def next_to_is_achievable(
    anchor_radius_m: float,
    *,
    band_m: tuple[float, float] = NEXT_TO_BAND_M,
    envelope: Any = DEFAULT_STAND_OFF_ENVELOPE,
) -> bool:
    """Can a ``next_to`` pose around an anchor of this radius exist *at all*?

    One inequality between two authorities that already exist: the band's outer
    edge, materialised in centre coordinates, must clear
    :meth:`~parcel_robot.authority.StandOffEnvelope.minimum_vicinity` — the
    same ``R + r_foot + target_surface_clearance`` composite that sets the
    **inner** edge of the ``near`` band::

        achievable  <=>  next_to_band_from_centre(R)[1] >= minimum_vicinity(R)

    Written that way it is stated once and stays correct if either authority
    moves. Evaluated at today's authorities it reduces to ``band_hi >= r_foot +
    target_surface_clearance`` — **``R`` cancels**, so with a surface-anchored
    band no anchor size can make ``next_to`` empty, and the relation-family
    inversion card B-1 measured (``next_to``'s outer edge inside ``near``'s
    inner edge for R > 0.38 m) cannot recur. What can still refuse it is the
    *embodiment*: a body whose footprint plus comfort clearance exceeds the
    band's outer edge has nowhere to stand beside anything
    (:func:`next_to_band_surface_slack_m` < 0).

    **Necessary, not sufficient.** It asks only whether the band and the
    envelope leave any room; the rest of the scene can still fill that room,
    which is exactly what the pedestrians and buildings around ``bench_1`` do
    on three of its four sides even after the band clears.
    """

    radius = float(anchor_radius_m)
    if not math.isfinite(radius) or radius < 0.0:
        raise ValueError("anchor_radius_m must be finite and >= 0")
    return next_to_band_from_centre(radius, band_m)[1] >= float(
        envelope.minimum_vicinity(radius)
    )


def object_towards_goal_region(
    center: tuple[float, float],
    *,
    entity_id: str | None = None,
    band_m: tuple[float, float] = TOWARDS_BAND_M,
) -> GoalRegion:
    _finite_xy(center)
    return GoalRegion(
        kind="relative_band",
        center=(float(center[0]), float(center[1])),
        band_m=(float(band_m[0]), float(band_m[1])),
        anchor_entity=entity_id,
        anchor_footprint_m=0.0,
    )


def arrival_goal_region_for_relation(
    relation: str,
    *,
    center: tuple[float, float] | None = None,
    polygon: Sequence[tuple[float, float]] | None = None,
    object_radius_m: float = 0.0,
    label: str = "",
    entity_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> GoalRegion:
    """Build the single arrival GoalRegion for a terminal relation."""

    meta = metadata or {}
    raw = meta.get("goal_region")
    if relation == "inside":
        if polygon is not None and len(tuple(polygon)) >= 3:
            return region_inside_goal_region(polygon, entity_id=entity_id)
        if isinstance(raw, Mapping):
            return GoalRegion.from_mapping(raw)
        raise ValueError("inside relation requires a polygon GoalRegion")
    if center is None and isinstance(raw, Mapping) and raw.get("center") is not None:
        center_raw = raw["center"]
        center = (float(center_raw[0]), float(center_raw[1]))
    if center is None:
        raise ValueError(f"{relation} relation requires a center")
    if relation == "next_to":
        footprint = float(meta.get("radius_m", object_radius_m) or object_radius_m)
        return object_next_to_goal_region(center, footprint, entity_id=entity_id)
    if relation == "towards":
        return object_towards_goal_region(center, entity_id=entity_id)
    # Default / near: prefer explicit metadata authority when present and band-shaped.
    if isinstance(raw, Mapping) and str(raw.get("kind") or "") == "relative_band":
        return GoalRegion.from_mapping(raw)
    radius = float(meta.get("radius_m", object_radius_m) or object_radius_m)
    return object_near_goal_region(
        center,
        radius,
        label=str(meta.get("label") or label or ""),
        entity_id=entity_id,
    )


def owner_anchored_goal_region(
    owner_xy: tuple[float, float],
    *,
    radius_m: float = OWNER_ARRIVAL_RADIUS_M,
    entity_id: str | None = "owner",
) -> GoalRegion:
    """Arrival disc anchored to an *observed* owner position (SLIM-2).

    The NAV_INSTRUCT ``follow_owner`` / ``circle_owner`` generator discs are
    frozen at the owner's commissioning pose (2.0, −0.5) so the episode set
    stays byte-reproducible. That is correct for the seeded matrix and wrong
    for a live product-path run, where the owner can be moved before or during
    the episode. This builder takes the owner position as an argument so the
    caller decides which observation is authoritative — the e2e cases pass the
    owner's *final* observed position, which is the anchor the instruction
    ("go to the owner") actually refers to at the moment of arrival.

    Pure: no runtime imports, no globals, same inputs → same GoalRegion.
    """

    _finite_xy(owner_xy)
    radius = float(radius_m)
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError("radius_m must be finite and positive")
    return GoalRegion(
        kind="disc",
        center=(float(owner_xy[0]), float(owner_xy[1])),
        radius_m=radius,
        anchor_entity=entity_id,
    )


def owner_anchored_band_goal_region(
    owner_xy: tuple[float, float],
    *,
    band_m: tuple[float, float] = NEXT_TO_BAND_M,
    owner_footprint_m: float = 0.22,
    entity_id: str | None = "owner",
) -> GoalRegion:
    """Owner-anchored annulus (the "stand beside me, don't stand on me" band).

    Same anchor argument as :func:`owner_anchored_goal_region`; the band form
    is what a *social* arrival wants, because a bare disc admits standing
    inside the owner's footprint. ``owner_footprint_m`` defaults to the city
    owner capsule radius (0.22 m in ``city_block.xml``).

    ``band_m`` is surface-relative and materialised through the same
    :func:`next_to_band_from_centre` the object band uses — otherwise "beside
    the owner" and "beside the bench" would mean different things, which is the
    D5 defect class with a person on one side of it.
    """

    _finite_xy(owner_xy)
    return GoalRegion(
        kind="relative_band",
        center=(float(owner_xy[0]), float(owner_xy[1])),
        band_m=next_to_band_from_centre(owner_footprint_m, band_m),
        anchor_entity=entity_id,
        anchor_footprint_m=float(owner_footprint_m),
    )


@dataclass(frozen=True)
class OwnerArrivalOutcome:
    """Owner-anchored arrival verdict with every gate reported separately."""

    success: bool
    in_region: bool
    settled: bool
    facing_owner: bool | None
    facing_gates_success: bool
    distance_to_goal_m: float
    heading_error_rad: float | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "in_region": self.in_region,
            "settled": self.settled,
            "facing_owner": self.facing_owner,
            "facing_gates_success": self.facing_gates_success,
            "distance_to_goal_m": self.distance_to_goal_m,
            "heading_error_rad": self.heading_error_rad,
            "detail": self.detail,
        }


def evaluate_owner_arrival(
    *,
    robot_xy: tuple[float, float],
    owner_xy: tuple[float, float],
    settled: bool,
    robot_heading_rad: float | None = None,
    radius_m: float = OWNER_ARRIVAL_RADIUS_M,
    band_m: tuple[float, float] | None = None,
    owner_footprint_m: float = 0.22,
    facing_tolerance_rad: float = FACING_TOLERANCE_RAD,
    require_facing: bool = False,
) -> OwnerArrivalOutcome:
    """Score "the robot came to the owner" against an owner-anchored region.

    ``band_m`` selects the annulus form (:func:`owner_anchored_band_goal_region`);
    the default ``None`` uses the disc form. ``require_facing`` mirrors
    :func:`evaluate_sit_next_to`: **report-only in v1**, so a facing miss is
    visible and attributable without being able to fail an otherwise-correct
    arrival.
    """

    goal = (
        owner_anchored_goal_region(owner_xy, radius_m=radius_m)
        if band_m is None
        else owner_anchored_band_goal_region(
            owner_xy, band_m=band_m, owner_footprint_m=owner_footprint_m
        )
    )
    x, y = float(robot_xy[0]), float(robot_xy[1])
    in_region = goal.contains(x, y)
    distance = goal.distance_to(x, y)
    heading_error = _bearing_error_rad((x, y), robot_heading_rad, owner_xy)
    facing = None if heading_error is None else heading_error <= float(facing_tolerance_rad)
    success = bool(in_region and settled)
    if require_facing:
        success = success and bool(facing)
    return OwnerArrivalOutcome(
        success=success,
        in_region=bool(in_region),
        settled=bool(settled),
        facing_owner=facing,
        facing_gates_success=bool(require_facing),
        distance_to_goal_m=float(distance),
        heading_error_rad=heading_error,
        detail=_owner_arrival_detail(in_region, settled, facing, require_facing),
    )


@dataclass(frozen=True)
class SitNextToOutcome:
    """Compound placement + posture verdict, one boolean per gate.

    Every gate is reported separately so a failure names itself: a run that
    reaches the band but never sits is a *posture* miss, not a navigation
    miss, and the two must never be summarised into one opaque False.
    """

    success: bool
    in_next_to_band: bool
    sit_posture: bool
    settled: bool
    facing_owner: bool | None
    facing_gates_success: bool
    distance_to_band_m: float
    heading_error_rad: float | None
    posture: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "in_next_to_band": self.in_next_to_band,
            "sit_posture": self.sit_posture,
            "settled": self.settled,
            "facing_owner": self.facing_owner,
            "facing_gates_success": self.facing_gates_success,
            "distance_to_band_m": self.distance_to_band_m,
            "heading_error_rad": self.heading_error_rad,
            "posture": self.posture,
            "detail": self.detail,
        }


def is_sit_posture(posture: object) -> bool:
    """True when a runtime-reported posture/pose name means "sitting"."""

    if posture is None:
        return False
    token = "".join(ch for ch in str(posture).lower() if ch.isalnum())
    return token in SIT_POSTURE_ALIASES


def evaluate_sit_next_to(
    *,
    robot_xy: tuple[float, float],
    anchor_xy: tuple[float, float],
    anchor_footprint_m: float,
    posture: object,
    settled: bool,
    robot_heading_rad: float | None = None,
    owner_xy: tuple[float, float] | None = None,
    owner_visible: bool = False,
    band_m: tuple[float, float] = NEXT_TO_BAND_M,
    facing_tolerance_rad: float = FACING_TOLERANCE_RAD,
    entity_id: str | None = None,
    require_facing: bool = False,
) -> SitNextToOutcome:
    """Score "sit next to X": next-to band + Sit posture + settled (+ facing).

    Three gates decide success in v1:

    1. **Placement** — the robot is inside the K0 ``next_to`` annulus around
       the anchor, built by :func:`object_next_to_goal_region` with
       :data:`NEXT_TO_BAND_M`. This is the same band the navigator's terminal
       verification and the NAV_INSTRUCT scorer use; there is no second radius.
       ``band_m`` is surface-relative like the constant it defaults to, and is
       materialised by the builder — never here.
    2. **Posture** — the runtime reports an active Sit pose
       (:func:`is_sit_posture`).
    3. **Settle** — the robot has stopped.

    **Facing is measured but does NOT gate success in v1** (``require_facing``
    defaults to ``False``). The rule being measured is "face the owner if
    visible": when ``owner_visible`` is true and ``owner_xy``/
    ``robot_heading_rad`` are supplied, ``facing_owner`` is true iff the
    heading is within ``facing_tolerance_rad`` (±60° by default) of the
    bearing to the owner; otherwise ``facing_owner`` is ``None`` — *unknown*,
    never a silent ``False``.

    Why report-only: the facing rule is a chosen default (task_2 §8 open
    question 1), the yaw is a body yaw rather than a gaze vector, and no
    product-path run has ever measured what the settle heading actually is.
    Gating on an unmeasured convention would manufacture failures that say
    nothing about capability. Callers that want it enforced pass
    ``require_facing=True``; flip the default once the measured distribution
    justifies a threshold.
    """

    goal = object_next_to_goal_region(
        anchor_xy,
        anchor_footprint_m,
        entity_id=entity_id,
        band_m=band_m,
    )
    x, y = float(robot_xy[0]), float(robot_xy[1])
    in_band = goal.contains(x, y)
    distance = goal.distance_to(x, y)
    sitting = is_sit_posture(posture)

    heading_error: float | None = None
    facing: bool | None = None
    if owner_visible and owner_xy is not None:
        heading_error = _bearing_error_rad((x, y), robot_heading_rad, owner_xy)
        if heading_error is not None:
            facing = heading_error <= float(facing_tolerance_rad)

    success = bool(in_band and sitting and settled)
    if require_facing:
        success = success and bool(facing)
    return SitNextToOutcome(
        success=success,
        in_next_to_band=bool(in_band),
        sit_posture=bool(sitting),
        settled=bool(settled),
        facing_owner=facing,
        facing_gates_success=bool(require_facing),
        distance_to_band_m=float(distance),
        heading_error_rad=heading_error,
        posture="" if posture is None else str(posture),
        detail=_sit_next_to_detail(in_band, sitting, settled, facing, require_facing),
    )


def sample_stopped(step: Mapping[str, object]) -> bool:
    """Public view of the scorer's "this sample is stopped" convention.

    Exported so derived re-scorers cannot grow a second, subtly different
    stop test — the exact defect class the duplicated-family audit names.
    """

    return _stopped(step)


def swept_angle_rad(
    points: Sequence[tuple[float, float]],
    anchor_xy: tuple[float, float],
    *,
    min_radius_m: float = 1e-3,
) -> float:
    """Signed angle swept around ``anchor_xy`` by a polyline of poses.

    Accumulates wrapped bearing deltas, so a full counter-clockwise lap is
    ``+2π`` and a clockwise lap ``−2π``; back-and-forth motion cancels instead
    of accumulating. Samples closer than ``min_radius_m`` to the anchor
    contribute nothing (bearing is undefined at the anchor).
    """

    _finite_xy(anchor_xy)
    ax, ay = float(anchor_xy[0]), float(anchor_xy[1])
    total = 0.0
    previous: float | None = None
    for point in points:
        px, py = float(point[0]), float(point[1])
        if not (math.isfinite(px) and math.isfinite(py)):
            previous = None
            continue
        if math.hypot(px - ax, py - ay) < float(min_radius_m):
            previous = None
            continue
        bearing = math.atan2(py - ay, px - ax)
        if previous is not None:
            total += _wrap_angle(bearing - previous)
        previous = bearing
    return total


def orbit_revolutions(
    points: Sequence[tuple[float, float]],
    anchor_xy: tuple[float, float],
    *,
    radius_band_m: tuple[float, float] = (1.0, 3.0),
) -> tuple[float, float]:
    """Return ``(revolutions, in_band_fraction)`` for an orbit trajectory.

    ``revolutions`` is ``|swept angle| / 2π``. ``in_band_fraction`` is the
    share of samples whose distance to the anchor lies inside
    ``radius_band_m`` — an orbit that swept 2π while drifting far outside the
    corridor is not an orbit, and the two numbers are reported separately so
    the caller can say which one failed.
    """

    _finite_xy(anchor_xy)
    lo, hi = float(radius_band_m[0]), float(radius_band_m[1])
    if not (math.isfinite(lo) and math.isfinite(hi) and 0.0 <= lo < hi):
        raise ValueError("radius_band_m must satisfy 0 ≤ min < max")
    ax, ay = float(anchor_xy[0]), float(anchor_xy[1])
    samples = [
        (float(p[0]), float(p[1]))
        for p in points
        if math.isfinite(float(p[0])) and math.isfinite(float(p[1]))
    ]
    revolutions = abs(swept_angle_rad(samples, anchor_xy)) / (2.0 * math.pi)
    if not samples:
        return (0.0, 0.0)
    inside = sum(1 for px, py in samples if lo <= math.hypot(px - ax, py - ay) <= hi)
    return (revolutions, inside / len(samples))


def _bearing_error_rad(
    from_xy: tuple[float, float],
    heading_rad: float | None,
    target_xy: tuple[float, float] | None,
) -> float | None:
    if heading_rad is None or target_xy is None:
        return None
    if not math.isfinite(float(heading_rad)):
        return None
    dx = float(target_xy[0]) - float(from_xy[0])
    dy = float(target_xy[1]) - float(from_xy[1])
    if not (math.isfinite(dx) and math.isfinite(dy)) or math.hypot(dx, dy) <= 1e-6:
        return None
    return abs(_wrap_angle(math.atan2(dy, dx) - float(heading_rad)))


def _wrap_angle(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


def _owner_arrival_detail(
    in_region: bool,
    settled: bool,
    facing: bool | None,
    require_facing: bool,
) -> str:
    if not in_region:
        return "outside_owner_region"
    if not settled:
        return "never_settled"
    if require_facing and not facing:
        return "not_facing_owner"
    return "success"


def _sit_next_to_detail(
    in_band: bool,
    sitting: bool,
    settled: bool,
    facing: bool | None,
    require_facing: bool,
) -> str:
    if not in_band:
        return "outside_next_to_band"
    if not sitting:
        return "sit_posture_not_active"
    if not settled:
        return "never_settled"
    if require_facing and not facing:
        return "not_facing_owner"
    return "success"


def system_arrival_claim(
    status: object = None,
    reason: object = None,
) -> bool:
    """True when a mission status/reason pair *claims* the robot arrived.

    One place decides what "the system said it arrived" means, so the three
    harnesses cannot drift apart on it. ``completed``/``tracking_owner`` is
    deliberately not a claim: a follow that is still tracking has asserted
    nothing about arrival.
    """

    status_token = str(status or "").strip().lower()
    reason_token = str(reason or "").strip().lower()
    return status_token in SYSTEM_ARRIVAL_STATUSES or reason_token in SYSTEM_ARRIVAL_REASONS


@dataclass(frozen=True)
class ArrivalAuthorityVerdict:
    """Both arrival verdicts for one episode plus the disagreement category.

    ``scorer_arrival`` is the K0 ``GoalRegion`` predicate on the **final pose**
    — deliberately *not* :attr:`EpisodeScore.success`, which additionally
    requires the settle hold. Mixing the two is what made U31 and U32 look like
    the same defect.
    """

    scorer_arrival: bool
    system_arrival: bool | None
    category: AuthorityCategory
    distance_to_goal_m: float
    boundary_margin_m: float
    epsilon_m: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "scorer_arrival": self.scorer_arrival,
            "system_arrival": self.system_arrival,
            "authority_category": self.category.value,
            "distance_to_goal_m": self.distance_to_goal_m,
            "boundary_margin_m": self.boundary_margin_m,
            "epsilon_m": self.epsilon_m,
        }


def differential_arrival_verdict(
    goal: GoalRegion,
    final_xy: tuple[float, float],
    *,
    system_arrival: bool | None,
    anchor_xy: tuple[float, float] | None = None,
    epsilon_m: float = ARRIVAL_BOUNDARY_EPSILON_M,
    anchor_covariance: (
        tuple[tuple[float, float], tuple[float, float]] | None
    ) = None,
    probability_threshold: float = INSIDE_PROBABILITY_THRESHOLD,
) -> ArrivalAuthorityVerdict:
    """Record both arrival authorities and classify their (dis)agreement.

    The invariant under test is one-way — ``scorer_arrival ⇒ system_arrival``
    — because the scorer is a derived geometric view and the navigator is the
    authority that acts. The four outcomes:

    ============================  ================================
    verdicts                      category
    ============================  ================================
    agree                         ``agreement``
    differ, within ``epsilon_m``  ``tolerated_boundary``
    scorer only, beyond epsilon   ``authority_disagreement``
    system only, beyond epsilon   ``false_arrival`` (U32)
    ============================  ================================

    ``system_arrival=None`` means the harness could not observe a system
    verdict; the category is ``unknown`` and nothing is asserted.

    ``anchor_covariance`` (optional) engages the same chance-constrained K0
    predicate the navigator uses under D2; omitted / zero keeps the boolean.
    """

    if not math.isfinite(float(epsilon_m)) or float(epsilon_m) < 0.0:
        raise ValueError("epsilon_m must be finite and ≥ 0")
    x, y = float(final_xy[0]), float(final_xy[1])
    scorer_arrival = goal.contains(
        x,
        y,
        anchor_xy=anchor_xy,
        anchor_covariance=anchor_covariance,
        probability_threshold=probability_threshold,
    )
    dtg = goal.distance_to(x, y, anchor_xy=anchor_xy)
    margin = goal.signed_distance_to_boundary(x, y, anchor_xy=anchor_xy)
    near_boundary = math.isfinite(margin) and abs(margin) <= float(epsilon_m)

    if system_arrival is None:
        category = AuthorityCategory.UNKNOWN
    elif bool(system_arrival) == scorer_arrival:
        category = AuthorityCategory.AGREEMENT
    elif near_boundary:
        category = AuthorityCategory.TOLERATED_BOUNDARY
    elif scorer_arrival:
        category = AuthorityCategory.AUTHORITY_DISAGREEMENT
    else:
        category = AuthorityCategory.FALSE_ARRIVAL
    return ArrivalAuthorityVerdict(
        scorer_arrival=bool(scorer_arrival),
        system_arrival=None if system_arrival is None else bool(system_arrival),
        category=category,
        distance_to_goal_m=float(dtg),
        boundary_margin_m=float(margin),
        epsilon_m=float(epsilon_m),
    )


@dataclass(frozen=True)
class EpisodeScore:
    success: bool
    spl: float
    distance_to_goal_m: float
    time_to_goal_s: float | None
    failure: FailureClass
    detail: str
    oracle_success: bool = False
    oracle_sr_gap: float = 0.0  # OSR − SR for this episode (0 or 1)
    attribution_layer: AttributionLayer = AttributionLayer.NONE
    #: K0 predicate on the final pose (no settle hold) — the scorer authority.
    scorer_arrival: bool = False
    #: The navigator's own claim, or ``None`` when the caller did not supply one.
    system_arrival: bool | None = None
    authority_category: AuthorityCategory = AuthorityCategory.UNKNOWN

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "spl": self.spl,
            "distance_to_goal_m": self.distance_to_goal_m,
            "time_to_goal_s": self.time_to_goal_s,
            "failure": self.failure.value,
            "detail": self.detail,
            "oracle_success": self.oracle_success,
            "oracle_sr_gap": self.oracle_sr_gap,
            "attribution_layer": self.attribution_layer.value,
            "scorer_arrival": self.scorer_arrival,
            "system_arrival": self.system_arrival,
            "authority_category": self.authority_category.value,
        }


@dataclass(frozen=True)
class OracleAttribution:
    """Result of oracle counterfactual auto-replay (research addendum)."""

    layer: AttributionLayer
    grounding_gap: bool
    exploration_gap: bool
    detail: str


def score_episode(
    trace: Sequence[Mapping[str, object]],
    goal: GoalRegion,
    *,
    shortest_path_m: float,
    max_time_s: float,
    arrival_hold_s: float = 1.0,
    anchor_xy: tuple[float, float] | None = None,
    oracle_success: bool | None = None,
    system_arrival: bool | None = None,
    epsilon_m: float = ARRIVAL_BOUNDARY_EPSILON_M,
) -> EpisodeScore:
    """Score one instruction-nav episode.

    Success = agent inside the region, stopped, and holding for
    ``arrival_hold_s`` (agent-stop convention). SPL = S · L / max(L, P).

    ``system_arrival`` is the navigator's own arrival claim (eval instrument 5).
    When supplied — or when the trace carries an explicit ``system_arrival`` /
    ``arrival_claimed`` flag — both verdicts and their
    :class:`AuthorityCategory` are recorded on the result, and a claim whose
    final pose sits more than ``epsilon_m`` outside the GoalRegion is
    classified :attr:`FailureClass.FALSE_ARRIVAL` instead of being bucketed
    with genuine navigation shortfalls (U32).

    **It can never change ``success``.** The claim is an input to failure
    *attribution* only; the settle-hold predicate above is untouched by it.
    """

    if not math.isfinite(shortest_path_m) or shortest_path_m < 0.0:
        raise ValueError("shortest_path_m must be finite and ≥ 0")
    if not math.isfinite(max_time_s) or max_time_s <= 0.0:
        raise ValueError("max_time_s must be finite and positive")
    if not math.isfinite(arrival_hold_s) or arrival_hold_s < 0.0:
        raise ValueError("arrival_hold_s must be finite and ≥ 0")

    if not trace:
        failure = FailureClass.REFUSAL
        return EpisodeScore(
            success=False,
            spl=0.0,
            distance_to_goal_m=float("inf"),
            time_to_goal_s=None,
            failure=failure,
            detail="empty_trace",
            oracle_success=bool(oracle_success),
            oracle_sr_gap=1.0 if oracle_success else 0.0,
            attribution_layer=_layer_for_failure(failure),
        )

    path_length_m = _path_length(trace)
    final = trace[-1]
    fx, fy = _xy(final)
    dtg = goal.distance_to(fx, fy, anchor_xy=anchor_xy)
    hold = _arrival_hold(
        trace,
        goal,
        arrival_hold_s=arrival_hold_s,
        anchor_xy=anchor_xy,
    )
    success = hold is not None
    spl = 0.0
    if success and shortest_path_m > 0.0:
        spl = shortest_path_m / max(shortest_path_m, path_length_m)
    elif success and shortest_path_m == 0.0:
        spl = 1.0 if path_length_m <= 1e-6 else 0.0

    claim = system_arrival if system_arrival is not None else _trace_arrival_claim(trace)
    verdict = differential_arrival_verdict(
        goal,
        (fx, fy),
        system_arrival=claim,
        anchor_xy=anchor_xy,
        epsilon_m=epsilon_m,
    )
    failure = (
        FailureClass.NONE
        if success
        else _classify_failure(trace, goal, anchor_xy, verdict=verdict)
    )
    if oracle_success is not None:
        o_success = bool(oracle_success)
    else:
        # OSR − SR isolates termination: ever inside the region (ignore hold).
        o_success = success or _ever_inside(trace, goal, anchor_xy=anchor_xy)
    detail = _detail(success, failure, trace)
    if failure == FailureClass.FALSE_ARRIVAL:
        detail = f"false_arrival:claim_without_predicate:dtg={dtg:.4f}m"
    return EpisodeScore(
        success=success,
        spl=float(spl),
        distance_to_goal_m=float(dtg),
        time_to_goal_s=hold,
        failure=failure,
        detail=detail,
        oracle_success=o_success,
        oracle_sr_gap=float(int(o_success) - int(success)),
        attribution_layer=(
            AttributionLayer.NONE if success else _layer_for_failure(failure)
        ),
        scorer_arrival=verdict.scorer_arrival,
        system_arrival=verdict.system_arrival,
        authority_category=verdict.category,
    )


def score_episode_with_oracle(
    trace: Sequence[Mapping[str, object]],
    goal: GoalRegion,
    *,
    shortest_path_m: float,
    max_time_s: float,
    arrival_hold_s: float = 1.0,
    anchor_xy: tuple[float, float] | None = None,
    oracle_grounding_flips: bool,
    oracle_grounding_and_explore_flips: bool,
    system_arrival: bool | None = None,
    epsilon_m: float = ARRIVAL_BOUNDARY_EPSILON_M,
) -> tuple[EpisodeScore, OracleAttribution]:
    """Score plus L1–L6 attribution via oracle counterfactual hooks.

    Callers re-run failed episodes with (1) oracle grounding and (2) oracle
    grounding + scripted exploration; the first flip names the layer.
    """

    base = score_episode(
        trace,
        goal,
        shortest_path_m=shortest_path_m,
        max_time_s=max_time_s,
        arrival_hold_s=arrival_hold_s,
        anchor_xy=anchor_xy,
        oracle_success=oracle_grounding_and_explore_flips or oracle_grounding_flips,
        system_arrival=system_arrival,
        epsilon_m=epsilon_m,
    )
    if base.success:
        attr = OracleAttribution(
            layer=AttributionLayer.NONE,
            grounding_gap=False,
            exploration_gap=False,
            detail="success",
        )
        return base, attr

    if oracle_grounding_flips:
        layer = AttributionLayer.L2B_VISIBILITY
        # Vocabulary vs visibility: refusal / wrong label → L2a.
        if base.failure == FailureClass.GROUNDING_ERROR:
            detail_text = str(base.detail).lower()
            if "vocab" in detail_text or "unknown_label" in detail_text:
                layer = AttributionLayer.L2A_VOCABULARY
        attr = OracleAttribution(
            layer=layer,
            grounding_gap=True,
            exploration_gap=False,
            detail="oracle_grounding_flips",
        )
        return (
            EpisodeScore(
                success=base.success,
                spl=base.spl,
                distance_to_goal_m=base.distance_to_goal_m,
                time_to_goal_s=base.time_to_goal_s,
                failure=base.failure,
                detail=base.detail,
                oracle_success=True,
                oracle_sr_gap=1.0,
                attribution_layer=layer,
                scorer_arrival=base.scorer_arrival,
                system_arrival=base.system_arrival,
                authority_category=base.authority_category,
            ),
            attr,
        )

    if oracle_grounding_and_explore_flips:
        attr = OracleAttribution(
            layer=AttributionLayer.L3_EXPLORATION,
            grounding_gap=False,
            exploration_gap=True,
            detail="oracle_explore_flips",
        )
        return (
            EpisodeScore(
                success=base.success,
                spl=base.spl,
                distance_to_goal_m=base.distance_to_goal_m,
                time_to_goal_s=base.time_to_goal_s,
                failure=base.failure,
                detail=base.detail,
                oracle_success=True,
                oracle_sr_gap=1.0,
                attribution_layer=AttributionLayer.L3_EXPLORATION,
                scorer_arrival=base.scorer_arrival,
                system_arrival=base.system_arrival,
                authority_category=base.authority_category,
            ),
            attr,
        )

    # Neither oracle flip succeeds — map failure class to layer (not everything → L6).
    if base.failure == FailureClass.GROUNDING_ERROR:
        detail_text = str(base.detail).lower()
        layer = (
            AttributionLayer.L2A_VOCABULARY
            if "vocab" in detail_text or "unknown_label" in detail_text
            else AttributionLayer.L2B_VISIBILITY
        )
    elif base.failure == FailureClass.SEARCH_ERROR:
        layer = AttributionLayer.L3_EXPLORATION
    elif base.failure == FailureClass.PLANNING_ERROR:
        layer = AttributionLayer.L4_PLANNING
    elif base.failure == FailureClass.CONTROL_ERROR:
        layer = AttributionLayer.L5_CONTROL
    elif base.failure in {FailureClass.TERMINATION, FailureClass.FALSE_ARRIVAL}:
        layer = AttributionLayer.L6_TERMINATION
    elif base.failure == FailureClass.REFUSAL:
        layer = AttributionLayer.L1_PARSE
    else:
        layer = AttributionLayer.L6_TERMINATION
    attr = OracleAttribution(
        layer=layer,
        grounding_gap=False,
        exploration_gap=False,
        detail="oracle_no_flip",
    )
    return (
        EpisodeScore(
            success=base.success,
            spl=base.spl,
            distance_to_goal_m=base.distance_to_goal_m,
            time_to_goal_s=base.time_to_goal_s,
            failure=base.failure,
            detail=base.detail,
            oracle_success=False,
            oracle_sr_gap=0.0,
            attribution_layer=layer,
            scorer_arrival=base.scorer_arrival,
            system_arrival=base.system_arrival,
            authority_category=base.authority_category,
        ),
        attr,
    )


def _classify_failure(
    trace: Sequence[Mapping[str, object]],
    goal: GoalRegion,
    anchor_xy: tuple[float, float] | None,
    *,
    verdict: ArrivalAuthorityVerdict | None = None,
) -> FailureClass:
    """Precedence: refusal → grounding → search → control → **false arrival** →
    termination → planning.

    Terminal step-limit-inside-goal / termination+inside beats stale
    ``planning_error`` flags so near-miss timeouts stay L6 (K0 / D5).
    Control/collision still outranks termination (safety > attribution), and
    ``false_arrival`` sits directly below it: a claim contradicted by the K0
    predicate is a verification defect, so it must never fall through to
    ``planning_error``/``termination`` where it reads as a navigation
    shortfall (U32). It stays *below* refusal/grounding/search because a trace
    that already reported "I couldn't find it" names its own defect better.
    """

    texts = " ".join(_event_text(step) for step in trace).lower()
    flags = _collect_flags(trace)

    if flags["refusal"] or "couldn't form" in texts or "could not form" in texts:
        return FailureClass.REFUSAL
    if flags["grounding_error"] or flags["ambiguous"] or "unknown_label" in texts:
        return FailureClass.GROUNDING_ERROR
    if flags["search_error"] or flags["not_found"] or "semantic_target_not_found" in texts:
        return FailureClass.SEARCH_ERROR
    if flags["collision"] or flags["control_error"] or "collision" in texts:
        return FailureClass.CONTROL_ERROR
    if verdict is not None and verdict.category == AuthorityCategory.FALSE_ARRIVAL:
        return FailureClass.FALSE_ARRIVAL

    # Inside GoalRegion without a settled hold — termination (L6) before planning.
    final = trace[-1]
    fx, fy = _xy(final)
    inside_final = goal.contains(fx, fy, anchor_xy=anchor_xy)
    ever_inside = inside_final or _ever_inside(trace, goal, anchor_xy=anchor_xy)
    if (
        flags["termination_error"]
        or "navigation_step_limit_inside_goal" in texts
        or (ever_inside and (flags["step_limit"] or "navigation_step_limit" in texts))
        or (inside_final and not _stopped(final))
    ):
        return FailureClass.TERMINATION
    if flags["planning_error"] or flags["unreachable"] or "no_route" in texts:
        return FailureClass.PLANNING_ERROR
    if flags["attempted"]:
        return FailureClass.PLANNING_ERROR
    return FailureClass.REFUSAL


def _collect_flags(trace: Sequence[Mapping[str, object]]) -> dict[str, bool]:
    keys = (
        "refusal",
        "grounding_error",
        "search_error",
        "planning_error",
        "control_error",
        "termination_error",
        "collision",
        "not_found",
        "unreachable",
        "ambiguous",
        "attempted",
        "step_limit",
    )
    out = {key: False for key in keys}
    search_attempted = False
    unseen_or_not_found = False
    for step in trace:
        for key in keys:
            if bool(step.get(key)):
                out[key] = True
        failure = str(step.get("failure") or step.get("failure_class") or "").lower()
        if failure in out:
            out[failure] = True
        if failure == "termination":
            out["termination_error"] = True
        state = str(step.get("resolution_state") or step.get("grounding_outcome") or "").lower()
        if state in {"not_found", "unseen"}:
            unseen_or_not_found = True
            out["not_found"] = True
        if state in {"unreachable"}:
            out["planning_error"] = True
            out["unreachable"] = True
        if state in {"ambiguous", "grounding_error"}:
            out["grounding_error"] = True
            out["ambiguous"] = True
        if state in {"resolved", "memory_hit", "searching"}:
            out["attempted"] = True
        if state == "searching":
            search_attempted = True
        note = str(step.get("note") or "").lower()
        if "semantic_search" in note or "frontier" in note or "scan" in note:
            out["attempted"] = True
            search_attempted = True
        if "navigation_step_limit" in note or note.endswith("step_limit"):
            out["step_limit"] = True
        if "navigation_step_limit_inside_goal" in note:
            out["termination_error"] = True
            out["step_limit"] = True
        if bool(step.get("collision")) or note.endswith("_collision"):
            out["collision"] = True
            out["control_error"] = True
        reply = str(step.get("reply") or step.get("agent_reply") or "").lower()
        if "couldn't form" in reply or "could not form" in reply:
            out["refusal"] = True
        if "looked around" in reply and "couldn't find" in reply:
            search_attempted = True
            out["search_error"] = True
            out["not_found"] = True
        if "searched nearby" in reply:
            search_attempted = True
    # UNSEEN/not_found is grounding unless a search recovery was actually tried.
    if unseen_or_not_found and not out["search_error"]:
        if search_attempted:
            out["search_error"] = True
        else:
            out["grounding_error"] = True
    return out


def _trace_arrival_claim(trace: Sequence[Mapping[str, object]]) -> bool | None:
    """Read an explicit arrival claim out of the trace, or ``None`` if absent.

    Only the two explicit boolean keys the harnesses write are honoured —
    free-text ``note``/``reason`` fields are deliberately **not** sniffed, so
    adding this check cannot reclassify a historical trace by accident.
    """

    claim: bool | None = None
    for step in trace:
        for key in ("system_arrival", "arrival_claimed"):
            if key in step:
                claim = bool(claim) or bool(step[key])
    return claim


def _ever_inside(
    trace: Sequence[Mapping[str, object]],
    goal: GoalRegion,
    *,
    anchor_xy: tuple[float, float] | None,
) -> bool:
    for step in trace:
        x, y = _xy(step)
        if goal.contains(x, y, anchor_xy=anchor_xy):
            return True
    return False


def _arrival_hold(
    trace: Sequence[Mapping[str, object]],
    goal: GoalRegion,
    *,
    arrival_hold_s: float,
    anchor_xy: tuple[float, float] | None,
) -> float | None:
    if arrival_hold_s <= 0.0:
        final = trace[-1]
        fx, fy = _xy(final)
        if goal.contains(fx, fy, anchor_xy=anchor_xy) and _stopped(final):
            return _time_s(final)
        return None

    hold_start: float | None = None
    for step in trace:
        t = _time_s(step)
        x, y = _xy(step)
        inside = goal.contains(x, y, anchor_xy=anchor_xy)
        stopped = _stopped(step)
        if inside and stopped:
            if hold_start is None:
                hold_start = t
            if t - hold_start >= arrival_hold_s - 1e-9:
                return t
        else:
            hold_start = None
    return None


def _path_length(trace: Sequence[Mapping[str, object]]) -> float:
    if "path_length_m" in trace[-1]:
        try:
            value = float(trace[-1]["path_length_m"])  # type: ignore[arg-type]
            if math.isfinite(value) and value >= 0.0:
                return value
        except (TypeError, ValueError):
            pass
    total = 0.0
    prev: tuple[float, float] | None = None
    for step in trace:
        xy = _xy(step)
        if prev is not None:
            total += math.hypot(xy[0] - prev[0], xy[1] - prev[1])
        prev = xy
    return total


def _xy(step: Mapping[str, object]) -> tuple[float, float]:
    if "x" in step and "y" in step:
        return float(step["x"]), float(step["y"])  # type: ignore[arg-type]
    pos = step.get("position") or step.get("xy")
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        return float(pos[0]), float(pos[1])
    return 0.0, 0.0


def _time_s(step: Mapping[str, object]) -> float:
    for key in ("t_s", "time_s", "t"):
        if key in step:
            try:
                value = float(step[key])  # type: ignore[arg-type]
                if math.isfinite(value):
                    return value
            except (TypeError, ValueError):
                continue
    return 0.0


def _stopped(step: Mapping[str, object]) -> bool:
    if "stopped" in step:
        return bool(step["stopped"])
    if "agent_stop" in step:
        return bool(step["agent_stop"])
    speed = step.get("speed_mps")
    if isinstance(speed, (int, float)) and math.isfinite(float(speed)):
        return float(speed) <= 0.05
    vx = step.get("vx")
    vy = step.get("vy")
    if isinstance(vx, (int, float)) and isinstance(vy, (int, float)):
        return math.hypot(float(vx), float(vy)) <= 0.05
    note = str(step.get("note") or "").lower()
    return "stop" in note or bool(step.get("stop"))


def _event_text(step: Mapping[str, object]) -> str:
    parts = [
        str(step.get("note") or ""),
        str(step.get("reply") or ""),
        str(step.get("agent_reply") or ""),
        str(step.get("resolution_state") or ""),
        str(step.get("grounding_outcome") or ""),
    ]
    return " ".join(parts)


def _detail(
    success: bool,
    failure: FailureClass,
    trace: Sequence[Mapping[str, object]],
) -> str:
    if success:
        return "success"
    for step in reversed(trace):
        for key in ("detail", "note", "resolution_state", "grounding_outcome", "reply"):
            value = step.get(key)
            if value:
                return str(value)
    return failure.value


def _layer_for_failure(failure: FailureClass) -> AttributionLayer:
    return {
        FailureClass.REFUSAL: AttributionLayer.L1_PARSE,
        FailureClass.GROUNDING_ERROR: AttributionLayer.L2A_VOCABULARY,
        FailureClass.SEARCH_ERROR: AttributionLayer.L3_EXPLORATION,
        FailureClass.PLANNING_ERROR: AttributionLayer.L4_PLANNING,
        FailureClass.CONTROL_ERROR: AttributionLayer.L5_CONTROL,
        FailureClass.TERMINATION: AttributionLayer.L6_TERMINATION,
        # Terminal verification is the disagreeing party in a false arrival,
        # and terminal verification is L6. No new layer is invented for it.
        FailureClass.FALSE_ARRIVAL: AttributionLayer.L6_TERMINATION,
        FailureClass.NONE: AttributionLayer.NONE,
    }[failure]


def _finite_xy(point: tuple[float, float]) -> None:
    if not (math.isfinite(point[0]) and math.isfinite(point[1])):
        raise ValueError("coordinates must be finite")


def _point_in_polygon(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            intersection = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection:
                inside = not inside
        previous = current
    return inside


def _distance_to_polygon(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
) -> float:
    if _point_in_polygon(point, polygon):
        return 0.0
    return _distance_to_polygon_edges(point, polygon)


def _distance_to_polygon_edges(
    point: tuple[float, float],
    polygon: tuple[tuple[float, float], ...],
) -> float:
    """Unsigned distance to the polygon *outline* (no inside/outside test)."""

    best = float("inf")
    previous = polygon[-1]
    for current in polygon:
        best = min(best, _distance_point_to_segment(point, previous, current))
        previous = current
    return best


def _distance_point_to_segment(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    ax, ay = a
    bx, by = b
    px, py = point
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
