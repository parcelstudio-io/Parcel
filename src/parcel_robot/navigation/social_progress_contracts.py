"""Pure value contracts for proposal-only ``SOCIAL-PROGRESS-1``.

This module answers one narrow question: given typed social evidence and the
previous liveness memory, what *planning proposal* should be considered next?
It cannot emit velocity, authorize motion, relax a person envelope, or bypass
the downstream reactive gate.  The feature is disabled by default.

``contracts.v1`` already publishes ``DynamicTrackV1`` and the observation
spine publishes ``DynamicTrackV2``.  Defining a third track DTO here would make
their meanings drift, so :class:`SocialTrackEvidenceV1` wraps the current V2
track with the visibility/existence fields that the observation contract does
not yet carry.  Most importantly, an empty track tuple is not free-space
evidence: release after a social hold requires a separate, fresh
:class:`VisibilityEvidenceV1` certificate over the complete swept corridor.

The records are deterministic and stdlib-pure apart from importing the frozen
observation DTO. The sibling policy receives monotonic time and all state
explicitly.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from parcel_robot.contracts.navigation_snapshot_v2 import DynamicTrackV2

SCHEMA_VERSION = 1
# Public diagnostics retain and JSON-encode integer-valued counters and
# timestamps.  Unsigned 64-bit is the common runtime/wire domain (ROS 2
# ``uint64`` and monotonic nanoseconds) and gives the projection an absolute
# byte bound; Python's arbitrary-size integers do not.
MAX_PUBLIC_INTEGER = (1 << 64) - 1
MAX_EVIDENCE_REFS = 32
MAX_IDENTITY_LINEAGE = 16
# A track identifier participates in association/history keys and is retained
# in every public shadow row.  Match the repository's V1 identifier ceiling.
MAX_TRACK_ID_CHARS = 128
# ``contracts.v1.DynamicTrackV1`` already caps class labels at 64 characters.
MAX_TRACK_CLASS_ID_CHARS = 64
# The first predictor ladder permits position/velocity and acceleration state:
# a dense 6-state covariance is 6 x 6 = 36 entries.  Larger state tensors do
# not belong in this per-tick leaf DTO and must be referenced out-of-band.
MAX_TRACK_COVARIANCE_ENTRIES = 36


class VisibilityStateV1(str, Enum):
    """Whether a sensor bundle could disprove continued occupancy."""

    VISIBLE = "visible"
    OCCLUDED = "occluded"
    OUT_OF_FOV = "out_of_fov"
    EXPLICIT_FREE = "explicit_free"
    STALE = "stale"


class FlowRoleV1(str, Enum):
    UNKNOWN = "unknown"
    OWNER_PARALLEL = "owner_parallel"
    SAME_FLOW = "same_flow"
    OPPOSING = "opposing"
    CROSSING = "crossing"
    STATIONARY = "stationary"


class SocialVenueV1(str, Enum):
    UNKNOWN = "unknown"
    SIDEWALK = "sidewalk"
    CROSSWALK = "crosswalk"
    ELEVATOR = "elevator"


class CrosswalkPhaseV1(str, Enum):
    APPROACH_CURB = "approach_curb"
    WAIT_AUTHORITY = "wait_authority"
    OWNER_COMMITTED = "owner_committed"
    COMMIT_CROSS = "commit_cross"
    EXIT = "exit"


class ElevatorPhaseV1(str, Enum):
    QUEUE_OFFSET = "queue_offset"
    VERIFY_OPEN = "verify_open"
    ALLOW_EGRESS = "allow_egress"
    VERIFY_CAPACITY = "verify_capacity"
    ENTER_TRAILING_OWNER = "enter_trailing_owner"
    PARK_HOLD = "park_hold"
    EXIT = "exit"


class PassingSideV1(str, Enum):
    LEFT = "left"
    RIGHT = "right"


class SocialProgressStateV1(str, Enum):
    TRACK = "track"
    SLOW_YIELD = "slow_yield"
    HOLD_OCCUPIED = "hold_occupied"
    HOLD_UNCERTAIN = "hold_uncertain"
    HOLD_SEMANTIC = "hold_semantic"
    PROBE_RESUME = "probe_resume"
    COMMIT_PASSING_SIDE = "commit_passing_side"
    FORMATION_SWITCH = "formation_switch"
    SAFE_STAGING = "safe_staging"
    EVASIVE_REPLAN = "evasive_replan"
    REROUTE = "reroute"
    ASK_OWNER = "ask_owner"
    SAFE_HOLD = "safe_hold"


class SocialBlockCauseV1(str, Enum):
    NONE = "none"
    FEATURE_DISABLED = "feature_disabled"
    TRUE_DYNAMIC_BLOCK = "true_dynamic_block"
    UNCERTAIN_OCCLUSION = "uncertain_occlusion"
    OUT_OF_FOV = "out_of_fov"
    STALE_SENSOR = "stale_sensor"
    CLEAR_STREAK_INCOMPLETE = "clear_streak_incomplete"
    COSTMAP_GHOST = "costmap_ghost"
    RECIPROCAL_OSCILLATION = "reciprocal_oscillation"
    LOCALIZATION_FAILURE = "localization_failure"
    PLANNER_FAILURE = "planner_failure"
    CROSSWALK_AUTHORITY = "crosswalk_authority"
    CROSSWALK_EXIT_UNAVAILABLE = "crosswalk_exit_unavailable"
    ELEVATOR_DOOR_DISAGREEMENT = "elevator_door_disagreement"
    ELEVATOR_EGRESS = "elevator_egress"
    ELEVATOR_CAPACITY = "elevator_capacity"
    ELEVATOR_OWNER_ORDER = "elevator_owner_order"
    ELEVATOR_MOVING = "elevator_moving"
    UNKNOWN_RESOURCE = "unknown_resource"
    RECOVERY_BUDGET_EXHAUSTED = "recovery_budget_exhausted"


class SocialProposalV1(str, Enum):
    """Non-authoritative requests to an upstream planner or owner channel."""

    NONE = "none"
    CONTINUE_PLANNING = "continue_planning"
    SLOW_YIELD_CANDIDATE = "slow_yield_candidate"
    PROBE_RESUME_CANDIDATE = "probe_resume_candidate"
    COMMIT_PASS_LEFT_CANDIDATE = "commit_pass_left_candidate"
    COMMIT_PASS_RIGHT_CANDIDATE = "commit_pass_right_candidate"
    TRAILING_FORMATION_CANDIDATE = "trailing_formation_candidate"
    SAFE_STAGE_PLAN_REQUEST = "safe_stage_plan_request"
    EVASIVE_PATH_PLAN_REQUEST = "evasive_path_plan_request"
    ALTERNATE_ROUTE_PLAN_REQUEST = "alternate_route_plan_request"
    ASK_OWNER = "ask_owner"


def _finite(value: object, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return result


def _probability(value: object, name: str) -> float:
    result = _finite(value, name)
    if result < 0.0 or result > 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return result


def _public_integer(value: object, name: str, *, minimum: int = 0) -> int:
    """Validate one retained/public integer without rendering hostile input."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < minimum or value > MAX_PUBLIC_INTEGER:
        raise ValueError(f"{name} must be in [{minimum}, {MAX_PUBLIC_INTEGER}]")
    return value


def _bounded_ids(values: tuple[str, ...], name: str, maximum: int) -> None:
    if not isinstance(values, tuple):
        raise TypeError(f"{name} must be a tuple")
    if len(values) > maximum:
        raise ValueError(f"{name} exceeds {maximum} items")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} cannot contain duplicates")
    if any(not isinstance(value, str) or not value or len(value) > 128 for value in values):
        raise ValueError(f"{name} entries must be non-empty strings up to 128 characters")


@dataclass(frozen=True, slots=True)
class VisibilityEvidenceV1:
    """One bounded visibility verdict; explicit free is a positive certificate.

    ``corridor_fully_observed`` means the producer ray-checked the complete
    short swept footprint, not just the last track centroid.  A usable
    ``EXPLICIT_FREE`` certificate additionally requires LiDAR clear-ray
    provenance and no contradictory occupied evidence.  Freshness is checked
    by :func:`decide_social_progress` against caller-supplied time/config.
    """

    evidence_id: str
    visibility: VisibilityStateV1
    source_monotonic_s: float
    receive_monotonic_s: float
    corridor_fully_observed: bool = False
    corridor_coverage: float = 0.0
    camera_evidence_refs: tuple[str, ...] = ()
    lidar_mark_evidence_refs: tuple[str, ...] = ()
    lidar_clear_evidence_refs: tuple[str, ...] = ()
    contradictory_track_ids: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        if (
            not isinstance(self.evidence_id, str)
            or not self.evidence_id
            or len(self.evidence_id) > 128
        ):
            raise ValueError("evidence_id must be a non-empty string up to 128 characters")
        if not isinstance(self.visibility, VisibilityStateV1):
            raise TypeError("visibility must be VisibilityStateV1")
        source = _finite(self.source_monotonic_s, "source_monotonic_s", minimum=0.0)
        receive = _finite(self.receive_monotonic_s, "receive_monotonic_s", minimum=0.0)
        if receive < source:
            raise ValueError("receive_monotonic_s must not precede source_monotonic_s")
        if not isinstance(self.corridor_fully_observed, bool):
            raise TypeError("corridor_fully_observed must be a boolean")
        coverage = _probability(self.corridor_coverage, "corridor_coverage")
        _bounded_ids(self.camera_evidence_refs, "camera_evidence_refs", MAX_EVIDENCE_REFS)
        _bounded_ids(
            self.lidar_mark_evidence_refs,
            "lidar_mark_evidence_refs",
            MAX_EVIDENCE_REFS,
        )
        _bounded_ids(
            self.lidar_clear_evidence_refs,
            "lidar_clear_evidence_refs",
            MAX_EVIDENCE_REFS,
        )
        _bounded_ids(
            self.contradictory_track_ids,
            "contradictory_track_ids",
            MAX_EVIDENCE_REFS,
        )
        if self.corridor_fully_observed and coverage != 1.0:
            raise ValueError("a fully observed corridor must have coverage 1.0")
        if self.visibility is VisibilityStateV1.EXPLICIT_FREE:
            if not self.corridor_fully_observed or coverage != 1.0:
                raise ValueError("explicit_free requires complete swept-corridor coverage")
            if not self.lidar_clear_evidence_refs:
                raise ValueError("explicit_free requires LiDAR clear-ray provenance")
            if self.lidar_mark_evidence_refs or self.contradictory_track_ids:
                raise ValueError("explicit_free cannot carry contradictory occupied evidence")
        if self.visibility is VisibilityStateV1.VISIBLE and not (
            self.camera_evidence_refs or self.lidar_mark_evidence_refs
        ):
            raise ValueError("visible evidence requires camera or LiDAR mark provenance")

    def age_s(self, now_monotonic_s: float) -> float:
        now = _finite(now_monotonic_s, "now_monotonic_s", minimum=0.0)
        if now < self.source_monotonic_s:
            raise ValueError("now_monotonic_s must not precede evidence source time")
        return now - self.source_monotonic_s


@dataclass(frozen=True, slots=True)
class SocialTrackEvidenceV1:
    """Social fields layered over the observation spine's existing track DTO."""

    track: DynamicTrackV2
    existence_probability: float
    visibility_evidence: VisibilityEvidenceV1
    in_swept_corridor: bool
    risk_upper_bound: float
    within_hard_envelope: bool = False
    owner_identity_lineage: tuple[str, ...] = ()
    owner_identity_probability: float = 0.0
    group_id: str | None = None
    flow_role: FlowRoleV1 = FlowRoleV1.UNKNOWN
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        if not isinstance(self.track, DynamicTrackV2):
            raise TypeError("track must be DynamicTrackV2")
        if not self.track.track_id or len(self.track.track_id) > MAX_TRACK_ID_CHARS:
            raise ValueError(
                f"track_id must be a non-empty string up to {MAX_TRACK_ID_CHARS} characters"
            )
        if not self.track.class_id or len(self.track.class_id) > MAX_TRACK_CLASS_ID_CHARS:
            raise ValueError(
                f"class_id must be a non-empty string up to {MAX_TRACK_CLASS_ID_CHARS} characters"
            )
        # Check the O(1) structural bound before reading a single nested entry.
        if len(self.track.covariance) > MAX_TRACK_COVARIANCE_ENTRIES:
            raise ValueError(f"track covariance exceeds {MAX_TRACK_COVARIANCE_ENTRIES} entries")
        if self.track.radius_m < 0.0:
            raise ValueError("track radius_m must be non-negative")
        _probability(self.track.confidence, "track confidence")
        for value in self.track.covariance:
            _finite(value, "track covariance entry")
        _probability(self.existence_probability, "existence_probability")
        _probability(self.risk_upper_bound, "risk_upper_bound")
        _probability(self.owner_identity_probability, "owner_identity_probability")
        if not isinstance(self.visibility_evidence, VisibilityEvidenceV1):
            raise TypeError("visibility_evidence must be VisibilityEvidenceV1")
        if self.visibility_evidence.visibility is VisibilityStateV1.EXPLICIT_FREE:
            raise ValueError(
                "a live social track cannot carry explicit_free visibility; "
                "use the separate swept-corridor certificate"
            )
        if not isinstance(self.in_swept_corridor, bool):
            raise TypeError("in_swept_corridor must be a boolean")
        if not isinstance(self.within_hard_envelope, bool):
            raise TypeError("within_hard_envelope must be a boolean")
        _bounded_ids(
            self.owner_identity_lineage,
            "owner_identity_lineage",
            MAX_IDENTITY_LINEAGE,
        )
        if self.group_id is not None and (
            not isinstance(self.group_id, str) or not self.group_id or len(self.group_id) > 128
        ):
            raise ValueError("group_id must be None or a non-empty bounded string")
        if not isinstance(self.flow_role, FlowRoleV1):
            raise TypeError("flow_role must be FlowRoleV1")


@dataclass(frozen=True, slots=True)
class SemanticContextV1:
    """Authoritative venue phase facts; never inferred from pedestrian flow."""

    venue: SocialVenueV1 = SocialVenueV1.UNKNOWN
    crosswalk_phase: CrosswalkPhaseV1 | None = None
    elevator_phase: ElevatorPhaseV1 | None = None
    candidate_enters_resource: bool = False
    traffic_authority_confirmed: bool = False
    owner_committed: bool = False
    exit_visible_and_feasible: bool = False
    sufficient_crossing_time: bool = False
    elevator_door_open_lidar: bool = False
    elevator_door_open_vision: bool = False
    elevator_egress_clear: bool = False
    elevator_capacity_available: bool = False
    owner_entered_ahead: bool = False
    elevator_car_moving: bool = False
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        if not isinstance(self.venue, SocialVenueV1):
            raise TypeError("venue must be SocialVenueV1")
        if self.crosswalk_phase is not None and not isinstance(
            self.crosswalk_phase, CrosswalkPhaseV1
        ):
            raise TypeError("crosswalk_phase must be CrosswalkPhaseV1 or None")
        if self.elevator_phase is not None and not isinstance(self.elevator_phase, ElevatorPhaseV1):
            raise TypeError("elevator_phase must be ElevatorPhaseV1 or None")
        if self.venue is SocialVenueV1.CROSSWALK:
            if self.crosswalk_phase is None or self.elevator_phase is not None:
                raise ValueError("crosswalk venue requires only crosswalk_phase")
        elif self.venue is SocialVenueV1.ELEVATOR:
            if self.elevator_phase is None or self.crosswalk_phase is not None:
                raise ValueError("elevator venue requires only elevator_phase")
        elif self.crosswalk_phase is not None or self.elevator_phase is not None:
            raise ValueError("venue phases are invalid outside their matching venue")
        for name in (
            "candidate_enters_resource",
            "traffic_authority_confirmed",
            "owner_committed",
            "exit_visible_and_feasible",
            "sufficient_crossing_time",
            "elevator_door_open_lidar",
            "elevator_door_open_vision",
            "elevator_egress_clear",
            "elevator_capacity_available",
            "owner_entered_ahead",
            "elevator_car_moving",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class SocialLivenessV1:
    """Caller-measured liveness facts; no free-form stop-reason parsing."""

    progress_requested: bool = False
    sensor_health_ok: bool = True
    localization_healthy: bool = True
    planner_healthy: bool = True
    hard_envelope_violated: bool = False
    costmap_blocked_without_live_track: bool = False
    block_duration_s: float = 0.0
    stable_progress_confirmed: bool = False
    formation_switch_available: bool = False
    safe_staging_candidate_available: bool = False
    safe_evasion_candidate_available: bool = False
    alternate_route_available: bool = False
    reciprocal_oscillation: bool = False
    passing_side_candidate: PassingSideV1 | None = None
    owner_query_already_made: bool = False

    def __post_init__(self) -> None:
        for name in (
            "progress_requested",
            "sensor_health_ok",
            "localization_healthy",
            "planner_healthy",
            "hard_envelope_violated",
            "costmap_blocked_without_live_track",
            "stable_progress_confirmed",
            "formation_switch_available",
            "safe_staging_candidate_available",
            "safe_evasion_candidate_available",
            "alternate_route_available",
            "reciprocal_oscillation",
            "owner_query_already_made",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")
        _finite(self.block_duration_s, "block_duration_s", minimum=0.0)
        if self.passing_side_candidate is not None and not isinstance(
            self.passing_side_candidate, PassingSideV1
        ):
            raise TypeError("passing_side_candidate must be PassingSideV1 or None")


@dataclass(frozen=True, slots=True)
class SocialProgressConfigV1:
    """Default-off thresholds; none is a physical safety clearance."""

    enabled: bool = False
    max_source_age_s: float = 0.25
    max_transport_delay_s: float = 0.10
    clear_streak_required: int = 2
    active_existence_min: float = 0.05
    slow_risk_upper_bound: float = 0.20
    hold_risk_upper_bound: float = 0.50
    resume_risk_upper_bound: float = 0.05
    recovery_after_s: float = 1.0
    ask_owner_after_s: float = 5.0
    safe_hold_after_s: float = 8.0
    initial_recovery_budget: int = 3
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")
        for name in (
            "max_source_age_s",
            "max_transport_delay_s",
            "recovery_after_s",
            "ask_owner_after_s",
            "safe_hold_after_s",
        ):
            if _finite(getattr(self, name), name, minimum=0.0) == 0.0:
                raise ValueError(f"{name} must be positive")
        _public_integer(self.clear_streak_required, "clear_streak_required", minimum=1)
        _public_integer(self.initial_recovery_budget, "initial_recovery_budget")
        for name in (
            "active_existence_min",
            "slow_risk_upper_bound",
            "hold_risk_upper_bound",
            "resume_risk_upper_bound",
        ):
            _probability(getattr(self, name), name)
        if not (
            self.resume_risk_upper_bound < self.slow_risk_upper_bound < self.hold_risk_upper_bound
        ):
            raise ValueError("risk thresholds must satisfy resume < slow < hold")
        if not self.recovery_after_s < self.ask_owner_after_s < self.safe_hold_after_s:
            raise ValueError("liveness thresholds must satisfy recovery < ask < safe_hold")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object] | None) -> SocialProgressConfigV1:
        """Parse the product config seam without truthiness or unknown-key drift.

        A missing section and an empty mapping both preserve the disabled
        default.  Values are not coerced: in particular ``"false"`` and
        ``0`` are not booleans and fail loudly in :meth:`__post_init__`.
        """

        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise TypeError("social progress config must be a mapping or None")
        allowed = {
            "enabled",
            "max_source_age_s",
            "max_transport_delay_s",
            "clear_streak_required",
            "active_existence_min",
            "slow_risk_upper_bound",
            "hold_risk_upper_bound",
            "resume_risk_upper_bound",
            "recovery_after_s",
            "ask_owner_after_s",
            "safe_hold_after_s",
            "initial_recovery_budget",
            "schema_version",
        }
        if any(not isinstance(key, str) for key in value):
            raise TypeError("social progress config keys must be strings")
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown social progress config keys: {unknown}")
        return cls(**dict(value))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class SocialProgressObservationV1:
    """One coherent social-progress tick for an extras/runtime ingress seam."""

    now_monotonic_s: float
    tracks: tuple[SocialTrackEvidenceV1, ...]
    corridor_evidence: VisibilityEvidenceV1 | None
    semantics: SemanticContextV1
    liveness: SocialLivenessV1
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        now = _finite(self.now_monotonic_s, "now_monotonic_s", minimum=0.0)
        if self.schema_version != SCHEMA_VERSION or isinstance(self.schema_version, bool):
            raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
        if not isinstance(self.tracks, tuple):
            raise TypeError("tracks must be a tuple of SocialTrackEvidenceV1")
        if len(self.tracks) > 64:
            raise ValueError("tracks exceeds 64 items")
        if any(not isinstance(track, SocialTrackEvidenceV1) for track in self.tracks):
            raise TypeError("tracks must be a tuple of SocialTrackEvidenceV1")
        track_ids = [item.track.track_id for item in self.tracks]
        if len(track_ids) != len(set(track_ids)):
            raise ValueError("tracks cannot contain duplicate track_id values")
        if self.corridor_evidence is not None and not isinstance(
            self.corridor_evidence, VisibilityEvidenceV1
        ):
            raise TypeError("corridor_evidence must be VisibilityEvidenceV1 or None")
        if not isinstance(self.semantics, SemanticContextV1):
            raise TypeError("semantics must be SemanticContextV1")
        if not isinstance(self.liveness, SocialLivenessV1):
            raise TypeError("liveness must be SocialLivenessV1")
        evidence = [item.visibility_evidence for item in self.tracks]
        if self.corridor_evidence is not None:
            evidence.append(self.corridor_evidence)
        if any(
            item.source_monotonic_s > now or item.receive_monotonic_s > now for item in evidence
        ):
            raise ValueError("evidence time cannot be after observation time")


@dataclass(frozen=True, slots=True)
class SocialProgressMemoryV1:
    """Minimal caller-persisted state needed for hysteresis and budgets."""

    prior_state: SocialProgressStateV1 = SocialProgressStateV1.TRACK
    release_certificate_required: bool = False
    clear_streak: int = 0
    last_clear_evidence_id: str | None = None
    recovery_budget_remaining: int = 3

    def __post_init__(self) -> None:
        if not isinstance(self.prior_state, SocialProgressStateV1):
            raise TypeError("prior_state must be SocialProgressStateV1")
        if not isinstance(self.release_certificate_required, bool):
            raise TypeError("release_certificate_required must be a boolean")
        _public_integer(self.clear_streak, "clear_streak")
        _public_integer(self.recovery_budget_remaining, "recovery_budget_remaining")
        if self.last_clear_evidence_id is not None and (
            not isinstance(self.last_clear_evidence_id, str)
            or not self.last_clear_evidence_id
            or len(self.last_clear_evidence_id) > 128
        ):
            raise ValueError(
                "last_clear_evidence_id must be None or a non-empty string up to 128 characters"
            )
        if not self.release_certificate_required and self.clear_streak:
            raise ValueError("clear_streak must be zero when no release certificate is required")


@dataclass(frozen=True, slots=True)
class SocialProgressDecisionV1:
    """A planning proposal, explicitly not a motion authorization."""

    state: SocialProgressStateV1
    cause: SocialBlockCauseV1
    proposal: SocialProposalV1
    blocker_id: str | None
    evidence_age_s: float | None
    clear_streak: int
    risk_upper_bound: float
    recovery_budget_remaining: int
    resume_eligible: bool
    next_memory: SocialProgressMemoryV1
    requires_downstream_safety_gate: bool = field(default=True, init=False)
    authorizes_motion: bool = field(default=False, init=False)
    schema_version: int = field(default=SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.state, SocialProgressStateV1):
            raise TypeError("state must be SocialProgressStateV1")
        if not isinstance(self.cause, SocialBlockCauseV1):
            raise TypeError("cause must be SocialBlockCauseV1")
        if not isinstance(self.proposal, SocialProposalV1):
            raise TypeError("proposal must be SocialProposalV1")
        if self.blocker_id is not None and (
            not isinstance(self.blocker_id, str)
            or not self.blocker_id
            or len(self.blocker_id) > 128
        ):
            raise ValueError("blocker_id must be None or a non-empty string up to 128 characters")
        if self.evidence_age_s is not None:
            _finite(self.evidence_age_s, "evidence_age_s", minimum=0.0)
        _public_integer(self.clear_streak, "clear_streak")
        _public_integer(self.recovery_budget_remaining, "recovery_budget_remaining")
        _probability(self.risk_upper_bound, "risk_upper_bound")
        if not isinstance(self.resume_eligible, bool):
            raise TypeError("resume_eligible must be a boolean")
        if not isinstance(self.next_memory, SocialProgressMemoryV1):
            raise TypeError("next_memory must be SocialProgressMemoryV1")
        if self.resume_eligible != (self.state is SocialProgressStateV1.PROBE_RESUME):
            raise ValueError("only PROBE_RESUME decisions may be resume eligible")
        if self.state is SocialProgressStateV1.PROBE_RESUME and (
            self.proposal is not SocialProposalV1.PROBE_RESUME_CANDIDATE
        ):
            raise ValueError("PROBE_RESUME requires a probe-resume proposal")


__all__ = [
    "MAX_PUBLIC_INTEGER",
    "MAX_TRACK_CLASS_ID_CHARS",
    "MAX_TRACK_COVARIANCE_ENTRIES",
    "MAX_TRACK_ID_CHARS",
    "CrosswalkPhaseV1",
    "ElevatorPhaseV1",
    "FlowRoleV1",
    "PassingSideV1",
    "SemanticContextV1",
    "SocialBlockCauseV1",
    "SocialLivenessV1",
    "SocialProgressConfigV1",
    "SocialProgressDecisionV1",
    "SocialProgressMemoryV1",
    "SocialProgressObservationV1",
    "SocialProgressStateV1",
    "SocialProposalV1",
    "SocialTrackEvidenceV1",
    "SocialVenueV1",
    "VisibilityEvidenceV1",
    "VisibilityStateV1",
]
