from __future__ import annotations

import importlib.util
import logging
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from parcel_robot.geometry import ROBOT_FOOTPRINT_RADIUS_M

# This file is copied into the frozen BARN v8 reference tree as a reviewed
# replacement.  That tree predates the C3 stall-attribution leaf, so keep the
# same soft-dependency discipline used for the other post-bundle navigation
# leaves below.  The fallback is deliberately the pre-C3 behaviour: progress
# hysteresis and person-yield handling remain available, while the opt-in held
# release door cannot arm without its implementation module.
try:
    from . import stall_attribution as stall
except ImportError:  # pragma: no cover - exercised in the isolated BARN bundle
    class _BundleStallAttribution:
        HELD_RELEASE_NOTE = "semantic_replan_after_held_route"
        _PROGRESS_HYSTERESIS_M = 0.025

        @staticmethod
        def goal_progress_made(best_distance_m: float | None, distance_m: float) -> bool:
            return (
                best_distance_m is None
                or distance_m
                < best_distance_m - _BundleStallAttribution._PROGRESS_HYSTERESIS_M
            )

        @staticmethod
        def person_yield_holds(
            nearest_person_m: float | None,
            person_stop_m: float,
        ) -> bool:
            return nearest_person_m is not None and nearest_person_m < person_stop_m

        @staticmethod
        def held_release_due(
            metadata: dict,
            route_status: str | None,
            body_is_still: bool,
            *,
            enabled: bool,
        ) -> bool:
            del metadata, route_status, body_is_still, enabled
            return False

    stall = _BundleStallAttribution()
from .approach import (
    point_in_polygon,
    point_in_polygon_with_clearance,
    safe_approach_pose,
)
from .base import GoalPose, MidLevelCommand, Mission, NavObservation
from .collision import CollisionPolicy, apply_collision_brake
from .goals import (
    SemanticGoal,
    navigation_directive_is_blocked,
    semantic_goal_from_directive,
)
from .grounder import PlaceGrounder

# The frozen BARN v8 bundle predates scene-bound POI admission.  Its reviewed
# replacement copy of this module must retain the historical direct-grounder
# behaviour without expanding the bundle allowlist.  Product builds import the
# admission authority; only a bundle where that leaf is absent takes this seam.
try:
    from .poi_admission import ground_admitted_poi, poi_lookup_metadata
except ImportError:  # pragma: no cover - exercised in the isolated BARN bundle
    def ground_admitted_poi(grounder: Any, directive: str) -> Any:
        return grounder.ground(directive)

    def poi_lookup_metadata(grounder: Any, error: BaseException) -> dict[str, str]:
        del error
        disabled = str(getattr(grounder, "disabled_reason", "") or "")
        return {"poi_grounding_disabled": disabled} if disabled else {}
from .registry import ModelRegistry
from .search import ActiveSemanticSearch
from .semantic_map import ObservationSemanticMap, SemanticCandidate, SemanticMap

# Stratum-1 pose authority. Every pose read below names its REP-105 frame
# explicitly: MAP for world-frame goals / semantic memory / K0 arrival, ODOM for
# short-horizon control. The seam lives in ``navigation/base.py`` so the
# controller and the pipeline share one accessor.
#
# This file is a v8 *replacement* source copied into frozen BARN bundles whose
# ``navigation/base.py`` predates the seam, so the import must be soft on the
# NAMES, not just on the module: importing a missing name from a module that
# does exist raises ImportError just the same, and that is what broke the
# historical sidecar the first time this landed. The fallback reproduces the
# pre-seam read exactly, which is what a bundle always did.
try:
    from .base import _HAS_POSE, MAP_FRAME
    from .base import pose_in as _pose_in
except ImportError:  # pragma: no cover — frozen BARN bundle path
    MAP_FRAME = "map"
    _HAS_POSE = False

    class _BundlePose:
        __slots__ = ("x", "y", "yaw")

        def __init__(self, x: float, y: float, yaw: float) -> None:
            self.x = x
            self.y = y
            self.yaw = yaw

        @property
        def xy(self) -> tuple[float, float]:
            return (self.x, self.y)

        @property
        def is_healthy(self) -> bool:
            return True

        @property
        def is_exact(self) -> bool:
            return True

    def _pose_in(observation: Any, frame: Any) -> Any:
        return _BundlePose(
            float(observation.position[0]),
            float(observation.position[1]),
            math.radians(float(observation.heading_deg)),
        )

    # ``_legacy_yaw`` used to be defined here as the bundle fallback for the
    # ``position[2]``-as-yaw read (U34). It is gone: nothing in this file
    # consumes a phantom yaw any more, so a frozen bundle gets the corrected
    # ``_pose_in(...).yaw`` above, which reads ``heading_deg`` -- the same field
    # the pre-seam code should always have read.


# The chance constraint is the only piece the pipeline needs from the pose
# module directly, and it is only ever reached at non-zero covariance.
try:
    from parcel_robot.pose import p_inside_polygon
except ImportError:  # pragma: no cover — frozen BARN bundle path
    p_inside_polygon = None  # type: ignore[assignment]

# Card R10 arrival table. Soft for the SAME reason as the import above, and it
# is not a theoretical concern: this file is one of the three the BARN v8 policy
# bundle REPLACES into a frozen historical ``parcel_robot`` tree
# (``evals/external/barn_v8_policy_bundle.py`` V8_REPLACEMENTS), and that tree
# predates ``navigation/arrival_semantics.py``. A hard import here reddened
# ``test_barn_v8_policy_bundle`` with
# ``ModuleNotFoundError: No module named 'parcel_robot.navigation.arrival_semantics'``
# from inside the policy sidecar. Adding the module to the bundle was not an
# option — the bundle's file counts and digests are pinned and frozen. The
# constant is a string, so the fallback is the string, and a bundle run simply
# never has an owner-facing terminal to orient for.
try:
    from .arrival_semantics import FACE_OWNER as ARRIVAL_FACE_OWNER
except ImportError:  # pragma: no cover — frozen BARN bundle path
    ARRIVAL_FACE_OWNER = "owner"

if TYPE_CHECKING:
    from .experimental_all_ray_shield import V8AllRayShieldConfig

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]

# Historical BARN isolated bundles ship an older parcel_robot tree that predates
# ``parcel_robot.paths`` (K7 packaging). ``pipeline.py`` is a v8 *replacement*
# source copied into those frozen bundles, so a hard import of the packaging
# module breaks the sidecar with ModuleNotFoundError. Keep it soft and fall back
# to REPO_ROOT — the exact resolution the bundle used before K7.
try:
    from parcel_robot.paths import parcel_roots, resolve_navigation_config

    _HAS_PARCEL_PATHS = True
except ImportError:  # pragma: no cover — frozen BARN bundle path
    parcel_roots = None  # type: ignore[assignment]
    resolve_navigation_config = None  # type: ignore[assignment]
    _HAS_PARCEL_PATHS = False

# Same rule for attribute-qualified goals ("the big tree"): ``attributes``
# postdates every frozen bundle. A bundle's own ``goals.py`` has no attribute
# field either, so the filter simply never engages there.
# Region-aware fallback distance (arbitration 2026-08-07): boundary, not
# centroid, ranks stuff-class candidates. Bundles predate it — soft import.
try:
    from parcel_robot.instructnav.relations import nearest_point_in_region
except ImportError:  # pragma: no cover — frozen BARN bundle path
    nearest_point_in_region = None  # type: ignore[assignment]

try:
    from .attributes import filter_candidates_by_attributes
    from .attributes import merge_results as merge_attribute_results

    _HAS_ATTRIBUTES = True
except ImportError:  # pragma: no cover — frozen BARN bundle path
    filter_candidates_by_attributes = None  # type: ignore[assignment]
    merge_attribute_results = None  # type: ignore[assignment]
    _HAS_ATTRIBUTES = False

# Same rule for the N11 pacing layer: ``traffic_aware`` postdates every frozen
# bundle, so the v8 replacement copy of this file must degrade to "no ramp
# memory" rather than fail to import. Yield-advance is a pacing optimisation;
# a BARN sidecar simply runs without it, exactly as it did before N11.
try:
    from .traffic_aware import RampMemory

    _HAS_TRAFFIC_AWARE = True
except ImportError:  # pragma: no cover — frozen BARN bundle path
    RampMemory = None  # type: ignore[assignment, misc]
    _HAS_TRAFFIC_AWARE = False

# Stratum-2 association authority. Same soft-import rule: ``tracker`` postdates
# every frozen bundle, and a bundle without it simply keeps the oracle-id
# association it always had.
try:
    from .tracker import Detection, MultiObjectTracker, TrackerConfig

    _HAS_TRACKER = True
except ImportError:  # pragma: no cover — frozen BARN bundle path
    Detection = None  # type: ignore[assignment, misc]
    MultiObjectTracker = None  # type: ignore[assignment, misc]
    TrackerConfig = None  # type: ignore[assignment, misc]
    _HAS_TRACKER = False

# Historical BARN isolated bundles ship an older parcel_robot tree without
# instructnav/. Keep the import soft so grid_v1 sidecars still load.
#
# ---------------------------------------------------------------------------
# A soft import must degrade for ABSENCE and ONLY for absence.
#
# The guard below covers the entire semantic-nav ladder. If it swallows any
# ImportError, an import cycle anywhere in the tree can flip _HAS_INSTRUCTNAV to
# False and quietly turn GrounderV2 / ProposerBus / GoalArbiter / SemanticMemory2D
# / value-directed search into no-ops — with a fully green test suite, because
# whether the cycle fires depends on module import ORDER. That regression has
# already shipped once (instructnav/arbiter.py -> parcel_robot.core.arbiter ->
# core/__init__ -> navigation/__init__ -> navigation.pipeline).
#
# So: "the module is not in this tree" degrades; anything else — a cycle, a
# partially initialized module, a name that vanished, a broken dependency — is a
# defect and is raised. tests/test_import_order_no_cycle.py is the standing gate.
# ---------------------------------------------------------------------------

#: Set when a soft import legitimately degraded (module genuinely absent).
#: ``None`` means the ladder is fully wired. Read it for health reporting.
INSTRUCTNAV_IMPORT_ERROR: ImportError | None = None
DETECTION_LOCK_ON_IMPORT_ERROR: ImportError | None = None
LOCK_ON_VERIFY_IMPORT_ERROR: ImportError | None = None
ROUTE_MEMORY_IMPORT_ERROR: ImportError | None = None


def _is_genuine_absence(exc: ImportError) -> bool:
    """True only when ``exc`` means "that module is not in this tree".

    A circular import raises a plain ``ImportError`` ("cannot import name X from
    partially initialized module ..."), never ``ModuleNotFoundError`` — so the
    isinstance check alone already separates the two dominant cases. The
    ``find_spec`` probe additionally rejects a ``ModuleNotFoundError`` raised
    from *inside* a module that does exist (a missing third-party dependency of
    an instructnav module is our problem, not a bundle shape).
    """

    if not isinstance(exc, ModuleNotFoundError):
        return False
    missing = getattr(exc, "name", None)
    if not missing:
        return False
    try:
        return importlib.util.find_spec(missing) is None
    except (ImportError, AttributeError, ValueError):
        # The parent package itself cannot be located/loaded — absent.
        return True


def _reraise_if_not_absent(exc: ImportError, ladder: str, gate: str) -> None:
    if _is_genuine_absence(exc):
        return
    raise ImportError(
        f"{ladder} failed to import for a reason that is NOT a missing module: "
        f"{exc!r}. Refusing to degrade silently — doing so would disable the "
        f"{ladder} at runtime while every test stays green. This is almost "
        f"always an import cycle opened by a new cross-package import; move the "
        f"shared symbol into a leaf module or import it lazily. Gate: {gate}."
    ) from exc


try:
    from parcel_robot.instructnav.arbiter import GoalArbiter, ProposerBus, SE2Goal
    from parcel_robot.instructnav.grounding import (
        GrounderV2,
        GroundingOutcome,
        honest_not_found_reply,
    )
    from parcel_robot.instructnav.memory import SemanticMemory, SemanticMemory2D
    from parcel_robot.instructnav.near_arrival import near_band_fallback_point
    from parcel_robot.instructnav.scan import ScanRecoveryAction, full_turn_scan_spec
    from parcel_robot.instructnav.scoring import (
        ARRIVAL_CONFIRMING_FRAMES_M,
        ArrivalEvidence,
        FalsePositiveMemory,
        GoalRegion,
        arrival_goal_region_for_relation,
        evidence_arrival_verified,
    )
    from parcel_robot.instructnav.search_entity import PlanTimePriorCache
    from parcel_robot.voice.amendment import clarification_from_grounding

    from .instructnav_recovery import (
        ScanBehaviorController,
        ground_query,
        ingest_observation_memory,
        recovery_action_for,
        search_entity_plan_step,
        select_search_entity_frontier,
    )
    from .value_directed_scan import (
        SCAN_PROPOSER_SOURCE,
        ScanLookDecision,
        ValueDirectedScanSession,
        paint_look,
    )
    from .value_evidence import ValueEvidencePolicy
    from .value_map import SemanticValueMap2D

    _HAS_INSTRUCTNAV = True
except ImportError as _exc:  # pragma: no cover — frozen BARN bundle path
    _reraise_if_not_absent(
        _exc, "the InstructNav ladder", "tests/test_import_order_no_cycle.py"
    )
    INSTRUCTNAV_IMPORT_ERROR = _exc
    logging.getLogger(__name__).warning(
        "InstructNav ladder unavailable (%s) — semantic navigation, grounding, "
        "scan recovery and value-directed search are DISABLED for this process.",
        _exc,
    )
    GoalArbiter = None  # type: ignore[misc, assignment]
    ProposerBus = None  # type: ignore[misc, assignment]
    SE2Goal = None  # type: ignore[misc, assignment]
    GrounderV2 = None  # type: ignore[misc, assignment]
    GroundingOutcome = None  # type: ignore[misc, assignment]
    honest_not_found_reply = None  # type: ignore[misc, assignment]
    SemanticMemory = None  # type: ignore[misc, assignment]
    SemanticMemory2D = None  # type: ignore[misc, assignment]
    near_band_fallback_point = None  # type: ignore[misc, assignment]
    ScanRecoveryAction = None  # type: ignore[misc, assignment]
    full_turn_scan_spec = None  # type: ignore[misc, assignment]
    GoalRegion = None  # type: ignore[misc, assignment]
    arrival_goal_region_for_relation = None  # type: ignore[misc, assignment]
    ARRIVAL_CONFIRMING_FRAMES_M = 3
    ArrivalEvidence = None  # type: ignore[misc, assignment]
    FalsePositiveMemory = None  # type: ignore[misc, assignment]
    evidence_arrival_verified = None  # type: ignore[misc, assignment]
    clarification_from_grounding = None  # type: ignore[misc, assignment]
    ScanBehaviorController = None  # type: ignore[misc, assignment]
    ground_query = None  # type: ignore[misc, assignment]
    ingest_observation_memory = None  # type: ignore[misc, assignment]
    recovery_action_for = None  # type: ignore[misc, assignment]
    search_entity_plan_step = None  # type: ignore[misc, assignment]
    select_search_entity_frontier = None  # type: ignore[misc, assignment]
    PlanTimePriorCache = None  # type: ignore[misc, assignment]
    SCAN_PROPOSER_SOURCE = "scan_behavior"
    ScanLookDecision = None  # type: ignore[misc, assignment]
    ValueDirectedScanSession = None  # type: ignore[misc, assignment]
    paint_look = None  # type: ignore[misc, assignment]
    ValueEvidencePolicy = None  # type: ignore[misc, assignment]
    SemanticValueMap2D = None  # type: ignore[misc, assignment]
    _HAS_INSTRUCTNAV = False

#: Card A3 / NAV-CORE fix 5.  The typed non-arrival a chance-constrained claim
#: gets when no detector confirmed it: the pose is inexact, its covariance has
#: never been calibrated on any host, and an uncalibrated probability is not
#: allowed to become an arrival.  A REFUSAL, so it belongs in the same family
#: as ``target_not_resighted`` and ``outside_arrival_region``.
ARRIVAL_UNCALIBRATED_CONFIDENCE_REASON = "arrival_confidence_uncalibrated"

# D3 lock-on is a separate soft import (same pattern as value_directed_scan):
# keep it out of the instructnav try so a detection_adapter miss cannot disable
# the whole GrounderV2 / ScanBehavior ladder.
try:
    from .detection_lock_on import (
        LOCK_ON_PLAN_STEP_ID,
        LOCK_ON_PROPOSER_SOURCE,
        DetectionLockOnSession,
    )

    _HAS_DETECTION_LOCK_ON = True
except ImportError as _exc:  # pragma: no cover — optional D3 module
    _reraise_if_not_absent(
        _exc, "the D3 detection lock-on module", "tests/test_import_order_no_cycle.py"
    )
    DETECTION_LOCK_ON_IMPORT_ERROR = _exc
    DetectionLockOnSession = None  # type: ignore[misc, assignment]
    LOCK_ON_PLAN_STEP_ID = "align_then_translate"
    LOCK_ON_PROPOSER_SOURCE = "detection_lock_on"
    _HAS_DETECTION_LOCK_ON = False


# VS-4 verify-on-approach consumes two Wave-2 pure modules (VS-1's session +
# per-kind refinement gate, VS-2's negative-evidence memory). Same soft-import
# pattern, separate try: a miss must disable the verify path only, never the D3
# lock-on or the GrounderV2 ladder.
try:
    from parcel_robot.detection_adapter.false_positive_memory import (
        NegativeEvidenceMemory,
    )

    from .lock_on_verify import (
        ApproachView,
        GroundedReference,
        LockOnVerifySession,
        ReferenceKind,
        admits_for_confirmation,
        refinement_gate,
    )

    _HAS_LOCK_ON_VERIFY = True
except ImportError as _exc:  # pragma: no cover — optional VS-1/VS-2 modules
    _reraise_if_not_absent(
        _exc, "the VS-1/VS-2 verify-on-approach modules", "tests/test_import_order_no_cycle.py"
    )
    LOCK_ON_VERIFY_IMPORT_ERROR = _exc
    NegativeEvidenceMemory = None  # type: ignore[misc, assignment]
    ApproachView = None  # type: ignore[misc, assignment]
    GroundedReference = None  # type: ignore[misc, assignment]
    LockOnVerifySession = None  # type: ignore[misc, assignment]
    ReferenceKind = None  # type: ignore[misc, assignment]
    admits_for_confirmation = None  # type: ignore[misc, assignment]
    refinement_gate = None  # type: ignore[misc, assignment]
    _HAS_LOCK_ON_VERIFY = False


# RM-2 route memory: a fourth soft import, deliberately separate again. The
# place graph is a leaf module (RM-1 pins "no navigation imports" with an AST
# walk), so importing it here cannot open a cycle; a miss must disable route
# memory only.
try:
    from parcel_robot.pose import POSE_PROVIDER_KEY
    from parcel_robot.route_memory.place_graph import (
        DEFAULT_ATTACH_RADIUS_M as ROUTE_MEMORY_ATTACH_RADIUS_M,
    )
    from parcel_robot.route_memory.proposer import (
        DEFAULT_WAYPOINT_REACHED_M,
        PLACE_ROUTE_SOURCE,
        chain_length_m,
        waypoint_goal_from_chain,
    )
    from parcel_robot.route_memory.runtime_hook import RouteMemoryPlaceHook

    _HAS_ROUTE_MEMORY = True
except ImportError as _exc:  # pragma: no cover — optional RM-1 module
    _reraise_if_not_absent(
        _exc, "the RM-1 place-graph modules", "tests/test_import_order_no_cycle.py"
    )
    ROUTE_MEMORY_IMPORT_ERROR = _exc
    RouteMemoryPlaceHook = None  # type: ignore[misc, assignment]
    waypoint_goal_from_chain = None  # type: ignore[misc, assignment]
    chain_length_m = None  # type: ignore[misc, assignment]
    PLACE_ROUTE_SOURCE = "route_memory_place"
    POSE_PROVIDER_KEY = "pose_provider"
    ROUTE_MEMORY_ATTACH_RADIUS_M = 8.05
    DEFAULT_WAYPOINT_REACHED_M = 0.25
    _HAS_ROUTE_MEMORY = False


def soft_import_health() -> dict[str, object]:
    """Machine-readable state of this module's soft imports.

    A caller that expects semantic navigation should assert
    ``soft_import_health()["instructnav"] is True`` at startup rather than
    discovering the no-op ladder from a silently degraded run.
    """

    return {
        "instructnav": _HAS_INSTRUCTNAV,
        "instructnav_error": (
            None if INSTRUCTNAV_IMPORT_ERROR is None else repr(INSTRUCTNAV_IMPORT_ERROR)
        ),
        "detection_lock_on": _HAS_DETECTION_LOCK_ON,
        "detection_lock_on_error": (
            None
            if DETECTION_LOCK_ON_IMPORT_ERROR is None
            else repr(DETECTION_LOCK_ON_IMPORT_ERROR)
        ),
        "lock_on_verify": _HAS_LOCK_ON_VERIFY,
        "lock_on_verify_error": (
            None
            if LOCK_ON_VERIFY_IMPORT_ERROR is None
            else repr(LOCK_ON_VERIFY_IMPORT_ERROR)
        ),
        "route_memory": _HAS_ROUTE_MEMORY,
        "route_memory_error": (
            None if ROUTE_MEMORY_IMPORT_ERROR is None else repr(ROUTE_MEMORY_IMPORT_ERROR)
        ),
    }


def _semantic_source_policy(data: Any) -> Any:
    """Card C-3. Read ``perception.semantic_source`` from a navigation config.

    Returns ``None`` when the axis is unavailable or unset, which means "consult
    the process default", which ships as ``oracle`` — so a config that has never
    heard of this card behaves exactly as it did.

    A MALFORMED source is NOT swallowed. Everything else this loader touches
    degrades softly, but a typo'd source that read as "the default" would look
    identical to a cutover that never happened, and the whole point of the POI
    disable is that it cannot fail silently.
    """

    try:
        from parcel_robot.perception_source.selection import SemanticSourcePolicy
    except ImportError:  # pragma: no cover — frozen BARN bundle path
        return None
    section = (data or {}).get("perception") if isinstance(data, dict) else None
    if not isinstance(section, dict):
        return None
    return SemanticSourcePolicy.from_mapping(section)


def _build_grounder(pois_path: Any, policy: Any) -> PlaceGrounder:
    """Construct the POI arm, degrading ONLY where the outcome is identical.

    A frozen BARN v8 bundle ships a ``parcel_robot`` tree that predates this
    card — including a ``PlaceGrounder`` with no ``for_semantic_source`` — while
    taking THIS module as a reviewed replacement source. Calling the classmethod
    unconditionally turned the whole v8 bundle derivation into an
    ``AttributeError`` inside the policy sidecar.

    The degrade is deliberately asymmetric, because the incident audit's own
    lesson is that "a soft-import that degrades a capability to None on
    ImportError turned a loud mistake into a quiet one":

    * **oracle** (or no source axis at all, which is what a frozen bundle has) —
      fall back to ``from_yaml``. That is byte-identical to what the classmethod
      would have returned, so the degrade changes nothing and may be silent.
    * **off-oracle** — RAISE. Here the fallback would silently re-arm the second
      oracle this card exists to disable, and a cutover run that quietly kept
      its POI table is precisely the false-positive REVISION §1 was written to
      prevent. Failing loudly is the only safe direction.
    """

    factory = getattr(PlaceGrounder, "for_semantic_source", None)
    if callable(factory):
        return factory(pois_path, policy)
    if policy is not None and not getattr(policy, "poi_grounding_enabled", True):
        raise RuntimeError(
            "perception.semantic_source is off-oracle but this PlaceGrounder "
            "predates card C-3 and cannot empty its POI table; refusing to run "
            "a cutover with the POI second-oracle still armed"
        )
    return PlaceGrounder.from_yaml(pois_path)


class DirectiveNavigator:
    """NL directive → POI goal → navigator model → collision-filtered mid-level cmd."""

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        grounder: PlaceGrounder,
        model_id: str = "stub_v0",
        arrive_radius_m: float = 1.5,
        collision: CollisionPolicy | None = None,
        safety: dict[str, Any] | None = None,
        all_ray_shield: V8AllRayShieldConfig | None = None,
        semantic_map: SemanticMap | None = None,
        search: ActiveSemanticSearch | None = None,
        semantic_memory: SemanticMemory | None = None,
        progress_timeout_steps: int = 400,
        max_semantic_replans: int = 2,
        terminal_stop_timeout_steps: int = 30,
        scan_budget_steps: int = 80,
        frontier_budget_steps: int = 300,
        instructnav_recovery: bool = True,
        value_directed_search: bool = False,
        detection_lock_on: bool = False,
        lock_on_verify_on_approach: bool = False,
        person_aware_nav: bool = False,
        route_memory: bool = False,
        held_stall_release: bool = False,
        inside_probability_threshold: float | None = None,
        arrival_confidence_threshold: float | None = None,
    ):
        if not 10 <= progress_timeout_steps <= 10_000:
            raise ValueError("progress timeout must be between 10 and 10000 steps")
        if not 0 <= max_semantic_replans <= 10:
            raise ValueError("semantic replan limit must be between 0 and 10")
        if not 2 <= terminal_stop_timeout_steps <= 1_000:
            raise ValueError("terminal stop timeout must be between 2 and 1000 steps")
        self.registry = registry
        self.grounder = grounder
        self.model_id = model_id
        self.arrive_radius_m = arrive_radius_m
        self.collision = collision or CollisionPolicy()
        self.safety = safety or {}
        self.all_ray_shield = all_ray_shield
        self.semantic_map = semantic_map or ObservationSemanticMap()
        self.search = search or ActiveSemanticSearch(max_steps=scan_budget_steps)
        if semantic_memory is not None:
            self.memory = semantic_memory
        elif _HAS_INSTRUCTNAV and SemanticMemory2D is not None:
            self.memory = SemanticMemory2D()
        elif _HAS_INSTRUCTNAV and SemanticMemory is not None:
            self.memory = SemanticMemory()
        else:
            self.memory = None
        self.proposer_bus = ProposerBus() if _HAS_INSTRUCTNAV and ProposerBus is not None else None
        self.goal_arbiter = GoalArbiter() if _HAS_INSTRUCTNAV and GoalArbiter is not None else None
        # P0-C proposal-buffer flush: the (task_id, plan_revision) every SE2Goal
        # this navigator publishes is stamped with, so the executive's committed
        # revision (flushed into proposer_bus/goal_arbiter as revision sinks) can
        # atomically reject proposals authored under a corrected-away revision.
        # Defaults ("", 0) keep an unwired navigator byte-for-byte as before -- a
        # proposal is stale only relative to a *committed* revision, and an
        # uncommitted channel commits nothing. runtime.set_active_revision feeds
        # the live mission's key on plan accept / nav start.
        self._active_task_id: str = ""
        self._active_plan_revision: int = 0
        self.grounder_v2 = GrounderV2() if _HAS_INSTRUCTNAV and GrounderV2 is not None else None
        # C2/C3 opt-in: flag-off must stay byte-identical to the fixed-spin path.
        self.value_directed_search = (
            bool(value_directed_search) and _HAS_INSTRUCTNAV and SemanticValueMap2D is not None
        )
        self.semantic_value_map = (
            SemanticValueMap2D(shape=(64, 64), resolution_m=0.5, origin_global_cell=(-32, -32))
            if self.value_directed_search
            else None
        )
        self._value_scan_session = (
            ValueDirectedScanSession(value_map=self.semantic_value_map)
            if self.value_directed_search and ValueDirectedScanSession is not None
            else None
        )
        # VS-5: the evidence policy VS-3 froze. It replaces the substring/floor
        # painter this pipeline used to run inline: value comes from the query
        # MATCH SCORE through the SigLIP seam, a look with nothing
        # query-relevant in it paints a MISS (which LOWERS the cone's value), and
        # ``evidence_count`` is the number the empty-map delegation keys on.
        self._value_evidence = (
            ValueEvidencePolicy()
            if self.value_directed_search and ValueEvidencePolicy is not None
            else None
        )
        # VS-5 non-vacuity telemetry (counters only; no decision reads these).
        self.value_paints = 0
        self.value_evidence_paints = 0
        self.value_miss_paints = 0
        self.value_cells_painted = 0
        self.value_directed_frontiers = 0
        self.value_baseline_frontiers = 0
        self._plan_time_prior = None
        # D3 opt-in: detection-triggered SEARCH→NAVIGATE lock-on. Flag-off keeps
        # the frustum multi-view commit path byte-identical.
        self.detection_lock_on = (
            bool(detection_lock_on)
            and _HAS_INSTRUCTNAV
            and _HAS_DETECTION_LOCK_ON
            and DetectionLockOnSession is not None
        )
        self._detection_lock_on = (
            DetectionLockOnSession() if self.detection_lock_on else None
        )
        # VS-4 opt-in: arrival integrity + verify-on-approach (card VS-4,
        # 2026-08-11). Strictly a REFUSAL channel layered on the D3 lock-on:
        # it never chooses an instance, never widens an arrival, and cannot be
        # on unless ``detection_lock_on`` is. Flag-OFF every branch it owns is
        # guarded, so the unconditional path is byte-identical.
        self.lock_on_verify_on_approach = (
            bool(lock_on_verify_on_approach)
            and self.detection_lock_on
            and _HAS_LOCK_ON_VERIFY
        )
        if self.detection_lock_on and not self.lock_on_verify_on_approach:
            # AF-2 (scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md, Notes): this is
            # the OLD DEFECTIVE ARM and it is still reachable. Without
            # verify-on-approach the lock-on retargets the mission goal to its
            # own D2 fused point and builds ``arrival_goal_region`` FROM that
            # rewritten candidate — the measured V-E wrong-instance false
            # arrival (nav-region_goal-B-05: final pose on the SOUTH sidewalk
            # while the episode polygon was the north one, dtg 4.7785 m) — and
            # a committed session never re-verifies, so nothing can refute it.
            # Measured on the v4 minival: SR 0.32 -> 0.24, 1 false arrival, 2
            # episodes lost; with verify on, 0.32 / 0 / 0 (W2_WIRE1_STATUS.md
            # §5). NOT a hard refusal: whether this combination should be
            # refused outright is owner decision-queue item 6 of the Wave-2
            # audit ("whether the defective lock-on-without-verify combination
            # should be refused outright"), and refusing it here would silently
            # move a flag-conditional arm the record still allows.
            logger.warning(
                "detection_lock_on is ON while lock_on_verify_on_approach is OFF: "
                "this is the measured V-E defective arm (wrong-instance commit "
                "against a silently rewritten goal, false arrival at dtg 4.7785 m "
                "on nav-region_goal-B-05; v4 minival SR 0.32->0.24, 2 episodes "
                "lost). Enable lock_on_verify_on_approach, or turn detection_lock_on "
                "off. Owner decision queue item 6, "
                "scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md."
            )
        self._lock_on_fp_memory = (
            NegativeEvidenceMemory() if self.lock_on_verify_on_approach else None
        )
        self._lock_on_verify: Any | None = None
        self._lock_on_verify_session_id = ""
        self._lock_on_last_admitted: Any | None = None
        self._lock_on_view_index = 0
        self._lock_on_hypothesis_committed = False
        self._lock_on_instance_id = ""
        #: Non-vacuity evidence for the card's gate (adjudication #19); never
        #: read by any decision. Same pattern as D15-B's engagement counters.
        self.lock_on_verify_states: list[tuple[str, str]] = []
        self.lock_on_sessions = 0
        self.lock_on_verify_ticks = 0
        self.lock_on_admitted_views = 0
        self.lock_on_deferred_ticks = 0
        self.lock_on_instance_switches = 0
        self.lock_on_commits = 0
        self.lock_on_refutations = 0
        #: AF-2: how many (class, cell) keys those refutations were written at.
        #: Two per refutation whenever the estimate and the grounded candidate
        #: fall in different cells — the case the audit measured inert.
        self.lock_on_refutation_cells = 0
        self.lock_on_suppressions = 0
        self.lock_on_reanchors = 0
        self.lock_on_flushes = 0
        # D15-B opt-in: person-aware navigation (card D15-B, 2026-08-11).
        #
        # The D-15 regression is a COMPLIANT robot deadlocking behind a human:
        # ``apply_reactive_safety`` vetoes translation whenever a person's
        # clearance is inside ``person_stop_m + |v|·reaction_time_s``, and the
        # planner — which never sees that veto — replans the same blocked route
        # until the budget expires (FOLLOWUP_DESIGNS.md §1.1).
        #
        # Flag-ON adds two PROPOSER-side behaviours and nothing else:
        #   (i) people the planner is BLIND to are published into the payload
        #       its own dynamic-agent cost layer already consumes, so A* can
        #       route AROUND them (measured: a declared person on the route
        #       turns a 0.03 m deadlock into a 3.86 m detour, W1_D15_STATUS.md);
        #  (ii) the commanded translation is capped at ``compliant_speed`` —
        #       the float-lattice supremum below the gate's own veto boundary —
        #       so the veto ring shrinks because the PROPOSAL slowed down.
        # ``apply_reactive_safety`` is untouched and still disposes every tick;
        # the cap can only ever REDUCE a commanded speed, so a proposer/gate
        # disagreement can lose the capability but can never grant motion the
        # gate would have refused. Flag-OFF is byte-identical: every branch
        # below is guarded, and the observation handed to the navigator is the
        # same object.
        self.person_aware_nav = bool(person_aware_nav)
        #: Ticks on which the flag-on path actually engaged. Non-vacuity
        #: evidence for the card's gate; never read by any decision.
        self.person_costs_published_ticks = 0
        self.person_compliant_cap_ticks = 0
        self._person_keepout_unavailable = False
        # RM-2 opt-in: route memory on the product path (card RM-2,
        # scrum/20260811/task_2/SLAM_M_PLAN.md, 2026-08-12).
        #
        # Three mechanisms, all behind this one flag:
        #   (1) AUTO-TEACH  — every tick's MAP-frame pose is offered to a
        #       session-scoped RoutePlaceGraph, so a route the robot has
        #       actually driven is remembered as recorded edges;
        #   (2) BEYOND-REACH TRIGGER — when the planner has PROVED it cannot
        #       route to a committed goal that is out of window range, memory is
        #       consulted BEFORE the instance is released and blacklisted;
        #   (3) CONSUMPTION — a remembered chain becomes ONE interim SE2Goal,
        #       stamped with the active (task_id, plan_revision), resolved
        #       through ``goal_arbiter`` (veto and lethal rules untouched), and
        #       on a win stored as an interim navigation target ONLY.
        #
        # The mission goal, the K0 arrival region and the arrival predicate are
        # NEVER replaced: ``self.mission.goal`` keeps the committed approach pose
        # for its whole life, ``_inside_arrival_goal_region`` keeps verifying
        # against the true target, and the chain hands back to normal planning as
        # soon as the true goal is inside the live planner window. Memory returns
        # an empty tuple ⇒ this whole path is inert and behaviour is today's,
        # verbatim (RM-1's fail-closed contract).
        #
        # Flag-OFF ``self._route_memory`` is None and every branch below is
        # guarded on that, so the unconditional path is byte-identical.
        self.route_memory = (
            bool(route_memory) and _HAS_ROUTE_MEMORY and RouteMemoryPlaceHook is not None
        )
        self._route_memory = RouteMemoryPlaceHook() if self.route_memory else None
        #: Card C3 / F1. Opt-in; flag-OFF the watchdog is byte-identical to HEAD
        #: (``stall_attribution.held_release_due`` short-circuits before it reads
        #: or writes anything). Enabling it moves frozen panel/minival rows.
        self.held_stall_release = bool(held_stall_release)
        #: The chain memory last handed back, in travel order (RECORDED edges).
        self._route_memory_chain: tuple[Any, ...] = ()
        #: The interim navigation target. NOT the mission goal, never an arrival.
        self._route_memory_target: GoalPose | None = None
        #: The (task_id, plan_revision) the live chain was authored under.
        self._route_memory_stamp: tuple[str, int] = ("", 0)
        #: Best remaining recorded distance seen on the live chain, and the
        #: consecutive ticks it has failed to improve — "active AND advancing".
        self._route_memory_best_remaining_m: float | None = None
        self._steps_route_memory_stalled = 0
        #: Hand-back probe state (see ``_route_memory_navigate``).
        self._route_memory_probing = False
        self._route_memory_probe_refuted = False
        self._route_memory_robot_xy: tuple[float, float] | None = None
        self._route_memory_tick = 0
        self._route_memory_now_s = 0.0
        #: Committed instances memory has already spent its one chain on. The
        #: livelock guard: without it a retired chain is re-armed on the next
        #: unroutable tick and the release the deferral suspended never returns.
        #: Mission-scoped, exactly like ``_unreachable_candidates``.
        self._route_memory_spent: set[str] = set()
        #: The task id a waypoint proposal is currently buffered under in the
        #: shared ``ProposerBus``, or ``None``. Recorded at PUBLISH time rather
        #: than read off ``_active_task_id`` at withdrawal time, because a
        #: correction may switch tasks in between (AUDIT_WAVE2 finding 1).
        self._route_memory_published_task: str | None = None
        #: Ticks the hand-back probe has been held waiting for the planner to
        #: actually plan for the TRUE goal (AUDIT_WAVE2 finding 2).
        self._steps_route_memory_probing = 0
        #: Append-only non-vacuity counters; read by no decision.
        self.route_memory_keyframes = 0
        self.route_memory_routes_found = 0
        self.route_memory_proposals = 0
        self.route_memory_wins = 0
        self.route_memory_vetoes = 0
        self.route_memory_chain_ticks = 0
        self.route_memory_deferred_releases = 0
        self.route_memory_flushes = 0
        self.route_memory_handbacks = 0
        self.scan_behavior = (
            ScanBehaviorController(
                value_directed=self.value_directed_search,
                value_session=self._value_scan_session,
            )
            if _HAS_INSTRUCTNAV and ScanBehaviorController is not None
            else None
        )
        self.progress_timeout_steps = progress_timeout_steps
        self.max_semantic_replans = max_semantic_replans
        self.terminal_stop_timeout_steps = terminal_stop_timeout_steps
        self.scan_budget_steps = int(scan_budget_steps)
        self.frontier_budget_steps = int(frontier_budget_steps)
        # Baseline / pre-N-O2: frustum only. Candidate: memory → ScanBehavior → SearchEntity.
        # Without instructnav (historical BARN bundles), recovery stays off.
        self.instructnav_recovery = bool(instructnav_recovery) and _HAS_INSTRUCTNAV
        self._navigator = self._create_navigator(model_id, arrive_radius_m)
        self.mission: Mission | None = None
        self._best_goal_distance_m: float | None = None
        self._steps_without_progress = 0
        self._terminal_verification_steps = 0
        self._paused = False
        self._status_before_pause: str | None = None
        self._frozen_steps_without_progress = 0
        self._frozen_terminal_verification_steps = 0
        self._scan_steps = 0
        self._frontier_steps = 0
        self._already_scanned = False
        self._already_searched = False
        self._recovery_phase = "frustum"  # frustum|memory|scan|frontier|failed
        self._frontier_target: tuple[float, float] | None = None
        self._frontier_viewpoints: list[tuple[float, float]] = []
        # N11 yield-advance pacing: memory only; never a gate or command source.
        self._ramp = RampMemory() if _HAS_TRAFFIC_AWARE else None
        self._ramp_fallback_ticks = 0
        self._ramp_clock = "unset"  # unset|stamp|tick — never mix two time bases
        # Consumed by the runtime after ``step``: the single seed hand-off to
        # the S-curve shaper, which is the ramp that actually binds recovery.
        self.pending_ramp_seed_mps: float | None = None
        # Chance-constrained membership threshold. ``None`` means "ask
        # configs/navigation/pose.yaml", so the value lives in exactly one
        # place; it is only ever consulted when the pose covariance is
        # non-zero, i.e. never under TruthPoseProvider.
        self._inside_probability_threshold = (
            None
            if inside_probability_threshold is None
            else float(inside_probability_threshold)
        )
        # Stratum-2: association is a geometric question, answered by a
        # classical filter, not by string equality on an oracle id.
        self._tracker = (
            MultiObjectTracker(TrackerConfig()) if _HAS_TRACKER else None
        )
        # A second, separate tracker for dynamic agents. Separate rather than
        # shared so a pedestrian standing beside the bench can never be bound
        # as "the bench", and so the two association problems keep independent
        # gates: a person moves metres per second, street furniture does not.
        self._people_tracker = (
            MultiObjectTracker(
                TrackerConfig(
                    # People are fast and their detections are looser, so both
                    # the process noise and the measurement sigma are wider
                    # than the furniture tracker's.
                    process_accel_sigma=1.5,
                    measurement_sigma_m=0.3,
                    initial_velocity_sigma_mps=2.0,
                )
            )
            if _HAS_TRACKER
            else None
        )
        self._tracker_last_time_s: float | None = None
        self._target_track_id: int | None = None
        # Stratum-2: places already checked and refuted. VLFM's named open
        # weakness is that nothing remembers a rejection, so the same phantom
        # is grounded on forever.
        self._false_positives = (
            FalsePositiveMemory() if _HAS_INSTRUCTNAV and FalsePositiveMemory is not None else None
        )
        # Instances this mission committed to and then proved it cannot route
        # to. Per-mission, like the false-positive memory: "I could not reach
        # that lamppost from here" is a fact about this attempt, not about the
        # world. See ``_unroutable_goal_recovery``.
        self._unreachable_candidates: set[str] = set()
        self._steps_goal_unroutable = 0
        # Consecutive ticks the local obstacle gate hard-stopped translation.
        # See ``_gate_blocked_route_recovery``.
        self._steps_gate_blocked = 0
        self._gate_blocked_anchor_xy: tuple[float, float] | None = None
        self._body_is_still = True
        self._arrival_confidence_threshold = (
            None
            if arrival_confidence_threshold is None
            else float(arrival_confidence_threshold)
        )

    @classmethod
    def from_config(cls, path: str | Path | None = None, **overrides: Any) -> DirectiveNavigator:
        if path is None:
            cfg_path = (
                resolve_navigation_config("configs/navigation/default.yaml")
                if _HAS_PARCEL_PATHS
                else (REPO_ROOT / "configs/navigation/default.yaml").resolve()
            )
        else:
            cfg_path = Path(path).expanduser().resolve()
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

        def resolve(p: str | Path) -> Path:
            candidate = Path(p).expanduser()
            if candidate.is_absolute():
                return candidate
            for root in parcel_roots() if _HAS_PARCEL_PATHS else ():
                from_root = (root / candidate).resolve()
                if from_root.exists():
                    return from_root
            from_repo = (REPO_ROOT / candidate).resolve()
            if from_repo.exists():
                return from_repo
            return (cfg_path.parent / candidate).resolve()

        models_root = resolve(
            overrides.get("models_root") or data.get("models_root") or "configs/navigation/models"
        )
        pois_path = resolve(
            overrides.get("pois_path")
            or overrides.get("pois")
            or data.get("pois_path")
            or data.get("pois")
            or "configs/navigation/cities/demo_pois.yaml"
        )

        registry = ModelRegistry.load(models_root)
        # Card C-3 REVISION 1. The POI table is a second oracle that fires
        # before semantic search; off-oracle it is constructed EMPTY. Under the
        # shipping source (``oracle``) this is exactly ``from_yaml`` and the
        # table, the scoring and the ``known_poi`` metadata are unchanged.
        grounder = _build_grounder(pois_path, _semantic_source_policy(data))
        safety = dict(data.get("safety") or {})
        search_config = dict(data.get("semantic_search") or {})
        progress_config = dict(data.get("progress_watchdog") or {})
        terminal_config = dict(data.get("terminal_verification") or {})
        stop_m = float(safety.get("stop_distance_m", 0.8))
        max_vyaw = float(safety.get("max_vyaw", 1.5))
        predictive_mode = str(
            overrides.get("predictive_mode", safety.get("predictive_mode", "stop"))
        )
        # Lazy: keep BARN v8 shield off the default import/grep surface.
        from .experimental_all_ray_shield import V8_ALL_RAY_MODE, V8AllRayShieldConfig

        all_ray_shield: V8AllRayShieldConfig | None = None
        if predictive_mode == V8_ALL_RAY_MODE:
            raw_all_ray_profile = safety.get("all_ray_yaw_swept_cap")
            if not isinstance(raw_all_ray_profile, dict):
                raise ValueError(
                    "all-ray predictive mode requires an exact safety.all_ray_yaw_swept_cap mapping"
                )
            all_ray_shield = V8AllRayShieldConfig.from_mapping(raw_all_ray_profile)
            if not math.isclose(
                all_ray_shield.stop_distance_m,
                stop_m,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise ValueError("all-ray and collision stop distances must match exactly")
        # Card PG-3: install the calibrated abstention policy the config asks
        # for. `perception.abstention.enabled` ships FALSE and a disabled policy
        # is short-circuited before any field is read, so this line cannot move
        # the shipping path; it exists so the cutover is a config change and not
        # a new piece of safety logic written under time pressure. Unknown keys
        # in that block raise — a typo'd safety flag must not read as "default".
        #
        # Imported HERE, not at module scope, for two independent reasons:
        #
        # 1. `perception_abstention` reads R20's refusal sentence out of
        #    `navigation.goals`, so a top-level import would close a cycle and
        #    make `import parcel_robot.perception.abstention` fail on a cold
        #    interpreter. Found by card PG-3's own seed canary, which is the
        #    only thing in the tree that imports that module first.
        # 2. The frozen BARN v8 policy bundle REPLACES this file into a
        #    `parcel_robot` tree that predates the module
        #    (`evals/external/barn_v8_policy_bundle.py::V8_REPLACEMENTS`), so a
        #    hard dependency here breaks the isolated policy sidecar. Same
        #    reason `navigation/semantic_map.py::_active_chain` guards its own
        #    import, and the same fail-safe: a tree with no abstention module
        #    has no abstention, which IS the pre-PG-3 path.
        try:
            from parcel_robot.perception.abstention import (
                AbstentionPolicy,
                use_abstention_policy,
            )
        except ImportError:  # pragma: no cover — frozen BARN bundle path
            pass
        else:
            use_abstention_policy(
                AbstentionPolicy.from_mapping(
                    (data.get("perception") or {}).get("abstention")
                )
            )
        return cls(
            registry=registry,
            grounder=grounder,
            model_id=str(
                overrides.get("model_id")
                or data.get("active_model")
                or data.get("default_model")
                or "stub_v0"
            ),
            arrive_radius_m=float(
                overrides.get("arrive_radius_m") or data.get("arrive_radius_m") or 1.5
            ),
            collision=CollisionPolicy(
                person_stop_m=float(
                    overrides.get("person_stop_m", safety.get("person_stop_m", stop_m + 0.4))
                ),
                person_slow_m=float(
                    overrides.get("person_slow_m", safety.get("person_slow_m", 2.5))
                ),
                obstacle_stop_m=float(
                    overrides.get("obstacle_stop_m", safety.get("obstacle_stop_m", stop_m))
                ),
                obstacle_slow_m=float(
                    overrides.get("obstacle_slow_m", safety.get("obstacle_slow_m", 1.2))
                ),
                slow_scale=float(overrides.get("slow_scale", safety.get("slow_scale", 0.35))),
                reaction_time_s=float(
                    overrides.get("reaction_time_s", safety.get("reaction_time_s", 0.12))
                ),
                predictive_mode=predictive_mode,
            ),
            safety=safety,
            all_ray_shield=all_ray_shield,
            search=ActiveSemanticSearch(
                max_steps=int(
                    overrides.get("search_max_steps", search_config.get("max_steps", 80))
                ),
                yaw_rate=min(
                    max_vyaw,
                    float(overrides.get("search_yaw_rate", search_config.get("yaw_rate", 0.35))),
                ),
            ),
            progress_timeout_steps=int(
                overrides.get(
                    "progress_timeout_steps",
                    progress_config.get("timeout_steps", 400),
                )
            ),
            max_semantic_replans=int(
                overrides.get(
                    "max_semantic_replans",
                    progress_config.get("max_semantic_replans", 2),
                )
            ),
            held_stall_release=bool(
                overrides.get(
                    "held_stall_release",
                    progress_config.get("held_stall_release", False),
                )
            ),
            terminal_stop_timeout_steps=int(
                overrides.get(
                    "terminal_stop_timeout_steps",
                    terminal_config.get("stop_timeout_steps", 30),
                )
            ),
            scan_budget_steps=int(
                overrides.get(
                    "scan_budget_steps",
                    search_config.get("max_steps", 80),
                )
            ),
            frontier_budget_steps=int(
                overrides.get(
                    "frontier_budget_steps",
                    search_config.get("frontier_budget_steps", 300),
                )
            ),
            instructnav_recovery=bool(
                overrides.get(
                    "instructnav_recovery",
                    data.get("instructnav_recovery", True),
                )
            ),
            value_directed_search=bool(
                overrides.get(
                    "value_directed_search",
                    data.get("value_directed_search", False),
                )
            ),
            detection_lock_on=bool(
                overrides.get(
                    "detection_lock_on",
                    data.get("detection_lock_on", False),
                )
            ),
            lock_on_verify_on_approach=bool(
                overrides.get(
                    "lock_on_verify_on_approach",
                    data.get("lock_on_verify_on_approach", False),
                )
            ),
            person_aware_nav=bool(
                overrides.get(
                    "person_aware_nav",
                    data.get("person_aware_nav", False),
                )
            ),
            route_memory=bool(
                overrides.get(
                    "route_memory",
                    data.get("route_memory", False),
                )
            ),
            semantic_memory=overrides.get("semantic_memory"),
            # Stratum-2 perception tier: ``null`` (the shipping default) means
            # "use the goal's own minimum_confidence", which is the value the
            # system already used. A tier that calibrates its own threshold
            # against known-absent trials writes it here.
            arrival_confidence_threshold=overrides.get(
                "arrival_confidence_threshold",
                (data.get("perception") or {}).get("arrival_confidence_threshold"),
            ),
        )

    def _planner_gate_ring_m(self) -> float:
        """The ring THIS navigator's own brake enforces, for its own planner.

        Card A2, fix 3 ("one clearance authority"). ``_apply_safety`` brakes
        every command this object emits at ``self.collision.obstacle_stop_m``
        (``configs/navigation/default.yaml`` ``safety.stop_distance_m``, 0.8 m
        of body-surface clearance on the shipped config), which is a STRICTER
        authority than the runtime reactive gate's 0.65 m ring. There is no
        excuse for the planner underneath to hold a third opinion: NAV-CORE
        sampled 8 stalls and every one of them ended inside a brake ring with
        the route still ``status=planned``, arm A's at ~0.79 m against exactly
        this number.

        What travels is the RING, in the convention the brake reads it in
        (``LidarObstacle.distance_m``, body-surface to obstacle-surface). The
        frame conversion into the grid's own centre-to-surface inflation is the
        planner's, once, in ``grid_navigator._planner_coupling_ring_m`` via
        ``ClearanceProfile.gate_range_ring_m``. The planner moves UP to agree;
        nothing here can move what ``apply_collision_brake`` enforces.
        """

        return float(self.collision.obstacle_stop_m)

    def _create_navigator(self, model_id: str, arrive_radius_m: float) -> Any:
        """Build the controller, commissioning its planner with our own brake.

        Card A2. The ring only reaches models that HAVE an occupancy planner to
        inflate — ``StubNavigator`` is a point-goal controller with no map and a
        strict keyword signature, and handing it a number it would have to
        ignore is how a safety-relevant value gets silently dropped.
        """

        options: dict[str, Any] = {"arrive_radius_m": arrive_radius_m}
        if self.registry.get(model_id).type.lower() == "grid":
            options["map_gate_clearance_m"] = self._planner_gate_ring_m()
        return self.registry.create(model_id, **options)

    def set_model(self, model_id: str) -> None:
        if self._navigator is not None:
            self._navigator.close()
        self.model_id = model_id
        self._navigator = self._create_navigator(model_id, self.arrive_radius_m)

    def list_models(self):
        return self.registry.list()

    @property
    def dynamic_cost_active(self) -> bool:
        """Whether the active model planned against dynamic-agent costs last tick."""

        return bool(getattr(self._navigator, "dynamic_cost_active", False))

    def parse(self, directive: str) -> Mission:
        if navigation_directive_is_blocked(directive):
            raise ValueError("negated or hypothetical navigation directive")
        try:
            goal = ground_admitted_poi(self.grounder, directive)
            return Mission(
                directive=directive,
                goal=goal,
                status="idle",
                metadata={"goal_source": "known_poi"},
            )
        except LookupError as poi_error:
            semantic_goal = semantic_goal_from_directive(directive)
            # Card C-3 REVISION 1 (off-oracle the POI arm is empty by
            # construction) and card C1/F1 (the loaded scene is not the scene
            # the POI table was surveyed on). Recording WHY makes "the mission
            # reached the place through perception" a checkable claim rather
            # than an inference from the absence of a known_poi tag.
            return Mission(
                directive=directive,
                goal=None,
                status="unresolved",
                semantic_goal=semantic_goal,
                metadata={
                    "goal_source": "semantic_search",
                    **poi_lookup_metadata(self.grounder, poi_error),
                    "semantic_query": semantic_goal.query,
                    "resolution_state": "unresolved",
                    # Directive modifiers, recorded so the runtime and the
                    # panel can see what the phrasing asked for.
                    "directive_superlative": semantic_goal.superlative,
                    "directive_attributes": list(semantic_goal.attributes),
                    "directive_pace": semantic_goal.pace,
                },
            )

    def start(self, directive: str | Mission) -> Mission:
        if isinstance(directive, Mission):
            mission = directive
            if mission.status == "idle":
                mission.status = "running"
        else:
            mission = self.parse(directive)
            mission.status = "running" if mission.goal is not None else "searching"
        self.search.reset()
        self._best_goal_distance_m = None
        self._steps_without_progress = 0
        self._terminal_verification_steps = 0
        # Fresh start clears any prior pause (resume-as-fresh-dispatch).
        self._paused = False
        self._status_before_pause = None
        self._frozen_steps_without_progress = 0
        self._frozen_terminal_verification_steps = 0
        self._scan_steps = 0
        self._frontier_steps = 0
        self._already_scanned = False
        self._already_searched = False
        self._frontier_target = None
        self._frontier_viewpoints = []
        self._recovery_phase = "frustum"
        self._unreachable_candidates = set()
        self._steps_goal_unroutable = 0
        self._steps_gate_blocked = 0
        self._gate_blocked_anchor_xy = None
        # RM-2: MISSION BOUNDARY. The graph survives (that is the whole point --
        # a route driven under an earlier directive is what makes the next one
        # solvable), the ingest TRACK does not. Skipping this is the one failure
        # AUDIT_WAVE1_FABLE.md called out by name: the teleport from one
        # episode's end pose to the next one's start pose would be recorded as a
        # traversal, handing the router an edge across ground nothing walked.
        self._reset_route_memory_track()
        if self.scan_behavior is not None:
            self.scan_behavior.reset()
        if self._value_scan_session is not None:
            self._value_scan_session.reset()
        # VS-5: the belief map is MISSION-scoped, like VS-3's policy ledger. A
        # map that kept a previous mission's evidence would report
        # ``evidence_count > 0`` before this mission has looked at anything, and
        # the empty-map delegation would silently not fire on its first frontier.
        if self.semantic_value_map is not None:
            self.semantic_value_map.reset()
        if self._value_evidence is not None:
            self._value_evidence.reset()
        if self._detection_lock_on is not None:
            self._detection_lock_on.reset()
        if self.lock_on_verify_on_approach:
            # VS-2's memory is MISSION-scoped; the counters are append-only
            # evidence and deliberately survive (D15-B's pattern).
            self._end_lock_on_verify()
            self._lock_on_last_admitted = None
            self._lock_on_hypothesis_committed = False
            self._lock_on_instance_id = ""
            if self._lock_on_fp_memory is not None:
                self._lock_on_fp_memory.reset()
        if self.value_directed_search and PlanTimePriorCache is not None:
            query = str(
                mission.metadata.get("semantic_query")
                or getattr(mission.semantic_goal, "query", "")
                or ""
            )
            self._plan_time_prior = (
                PlanTimePriorCache.from_query_table(query) if query.strip() else None
            )
        else:
            self._plan_time_prior = None
        self._reset_ramp_memory()
        mission.metadata.pop("paused", None)
        mission.metadata.setdefault("replan_count", 0)
        mission.metadata.setdefault(
            "grounding_outcome",
            GroundingOutcome.UNSEEN.value if GroundingOutcome is not None else "UNSEEN",
        )
        mission.metadata.setdefault("recovery_phase", "frustum")
        if self.value_directed_search:
            mission.metadata["value_directed_search"] = True
        if self.detection_lock_on:
            mission.metadata["detection_lock_on"] = True
        if self.lock_on_verify_on_approach:
            mission.metadata["lock_on_verify_on_approach"] = True
        if mission.goal is not None:
            self._navigator.reset(mission)
        self.mission = mission
        return mission

    def done(self) -> bool:
        return self.mission is None or self.mission.status in {"arrived", "failed", "idle"}

    def set_active_revision(self, task_id: str, plan_revision: int) -> None:
        """Bind the (task_id, plan_revision) future SE2Goal proposals are stamped with.

        The runtime calls this when a plan revision commits for the mission's task
        (plan accept / correction) so this navigator's proposals carry the same key
        the executive flushes into the proposer_bus / goal_arbiter revision sinks.
        A stale-revision straggler is then rejected by ``GoalArbiter.resolve``.
        """

        # The two assignments below are the pre-RM-2 body, in the pre-RM-2 ORDER,
        # with the pre-RM-2 exception behaviour: ``str(task_id)`` is evaluated and
        # stored, THEN ``int(plan_revision)``, so a non-integer revision leaves the
        # task id already updated exactly as it always did. Computing the "changed"
        # predicate from the tuple ahead of the assignments (RM-2's first shape)
        # quietly moved that exception boundary on the unconditional path.
        previous = (self._active_task_id, self._active_plan_revision)
        self._active_task_id = str(task_id)
        self._active_plan_revision = int(plan_revision)
        # RM-2: a CORRECTION is exactly a change of the active revision key. A
        # pending waypoint chain was derived under the OLD one, so it is gone --
        # withdrawn from the buffer by the revision-neutral purge and dropped as
        # an interim target here, in the same call. The mission goal is untouched:
        # a correction that keeps the same goal simply re-derives the chain on the
        # next trigger.
        #
        # AUDIT_WAVE2 finding 1: the withdrawal keys off the task the proposal was
        # PUBLISHED under (``_route_memory_published_task``), not off
        # ``_active_task_id``. A correction may SWITCH tasks -- ``runtime`` re-points
        # the key on every accepted plan, including non-nav voice plans -- and
        # purging under the new task left the old task's waypoint buffered and still
        # able to win ``GoalArbiter.resolve`` inside its TTL.
        if self._route_memory is not None and (
            self._active_task_id,
            self._active_plan_revision,
        ) != previous:
            self._flush_route_memory_waypoints("revision_changed")

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """Freeze tick budgets and retain the Mission (≠ ``stop()``)."""

        if self.mission is None or self._paused:
            return
        if self.mission.status in {"arrived", "failed", "idle"}:
            return
        self._status_before_pause = self.mission.status_value()
        self._frozen_steps_without_progress = self._steps_without_progress
        self._frozen_terminal_verification_steps = self._terminal_verification_steps
        # String literal keeps BARN historical-bundle base.py import-compatible.
        self.mission.status = "paused"
        self.mission.metadata["paused"] = True
        self._paused = True
        self._reset_ramp_memory()

    def resume(self) -> None:
        if not self._paused or self.mission is None:
            return
        restored = self._status_before_pause or "running"
        self.mission.status = restored
        self.mission.metadata.pop("paused", None)
        self._steps_without_progress = self._frozen_steps_without_progress
        self._terminal_verification_steps = self._frozen_terminal_verification_steps
        self._status_before_pause = None
        self._paused = False

    def snapshot(self) -> dict[str, object]:
        mission = self.mission
        route_status = getattr(self._navigator, "last_route_status", None)
        return {
            "paused": self._paused,
            "steps_without_progress": self._steps_without_progress,
            "terminal_verification_steps": self._terminal_verification_steps,
            "mission_status": None if mission is None else mission.status_value(),
            "has_mission": mission is not None,
            # SOCIAL-PROGRESS-1 reads these typed planner facts in shadow mode.
            # They deliberately expose no command and do not parse the
            # free-form MidLevelCommand note.  Frozen policy bundles may call
            # this method, so the existing keys and control path stay intact.
            "route_status": None if route_status is None else str(route_status),
            "body_is_still": self._body_is_still,
            "steps_gate_blocked": self._steps_gate_blocked,
            "progress_demand": bool(
                mission is not None
                and mission.status_value()
                not in {"arrived", "failed", "idle", "paused", "verifying"}
            ),
        }

    def step(self, observation: NavObservation) -> MidLevelCommand:
        if self.mission is None:
            return MidLevelCommand(stop=True, note="no_mission")
        if self._paused:
            # Budgets stay frozen; do not advance watchdog counters.
            return MidLevelCommand(stop=True, note="mission_paused")
        # RM-2 AUTO-TEACH, before the LOST hold: RM-1 refuses a LOST pose and
        # breaks its own track on it, and that break is exactly what must be
        # recorded (MAP jumps on recovery). Returning first would hide it.
        if self._route_memory is not None:
            self._route_memory_teach(observation)
        if self._owner_face_turn_active():
            # Phase B owns LOST as a latch invalidation, not the resumable
            # travel hold below: once target verification is latched, stale or
            # unhealthy pose feedback must fail the terminal claim closed.
            self._update_tracker(observation)
            self._update_body_stillness(observation)
            return self._step_owner_face_turn(observation)
        lost = self._pose_lost_hold(observation)
        if lost is not None:
            return lost
        self._update_tracker(observation)
        # Card A2 fix 3.4: one displacement witness per tick, read by both the
        # gate-blocked and the unroutable-goal releases below.
        self._update_body_stillness(observation)
        if self.mission.goal is None:
            # VS-5: the searching path is the value map's path; stamp its
            # counters here, the one place every searching command returns
            # through. Flag-off returns the identical object.
            return self._value_map_telemetry_note(
                self._step_semantic_resolution(observation)
            )
        self._reanchor_landmark_goal(observation)
        # VS-4: re-verify the committed reference BEFORE anything acts on it,
        # terminal verification included — a proposal refuted on the doorstep is
        # exactly the one that must not be allowed to claim an arrival.
        if self.lock_on_verify_on_approach and self._lock_on_verify is not None:
            refused = self._verify_lock_on_on_approach(observation)
            if refused is not None:
                return refused
        if self.mission.status == "verifying":
            return self._step_terminal_verification(observation)
        control_observation = self._control_observation(observation)
        # D15-B (i): the planner plans against the people it can see when the
        # flag is on. Flag-off this is the SAME OBJECT, so the navigator sees
        # exactly what it saw before this card.
        plan_observation = (
            self._publish_person_costs(control_observation)
            if self.person_aware_nav
            else control_observation
        )
        # RM-2 (iii): flag-off this is the SAME call it always was.
        cmd = (
            self._navigator.act(plan_observation, self.mission)
            if self._route_memory is None
            else self._route_memory_navigate(plan_observation)
        )
        geometrically_arrived = bool(cmd.stop) or self.mission.status == "arrived"
        inside_arrival = self._inside_arrival_goal_region(observation)
        if geometrically_arrived or inside_arrival:
            if self.mission.semantic_goal is None:
                self.mission.status = "arrived"
                return MidLevelCommand(stop=True, note=cmd.note or "arrived")
            # Geometric approach-pose tolerance OR shared GoalRegion membership
            # both request stop. Semantic success still requires relation + settle.
            self.mission.status = "verifying"
            self.mission.metadata["plan_step"] = "verify_relation_and_stopped"
            if inside_arrival and geometrically_arrived:
                self.mission.metadata["arrival_trigger"] = "goal_region_or_pose"
            elif inside_arrival:
                self.mission.metadata["arrival_trigger"] = "goal_region"
            else:
                self.mission.metadata["arrival_trigger"] = "approach_pose"
            self._terminal_verification_steps = 0
            return self._step_terminal_verification(observation, entering=True)

        stalled = self._progress_watchdog(control_observation)
        if stalled is not None:
            return stalled
        unroutable = self._unroutable_goal_recovery(observation)
        if unroutable is not None:
            return unroutable
        # RM-2 trigger (ii): the beyond-window case, which is CLIPPED to
        # ``partial`` and never reaches the hook above. Arms only; returns
        # nothing, so the tick proceeds exactly as it would have.
        if self._route_memory is not None:
            self._route_memory_partial_recovery()
        gate_blocked = self._gate_blocked_route_recovery(observation)
        if gate_blocked is not None:
            return gate_blocked

        obstacle_bearing = control_observation.extras.get("obstacle_bearing_rad")
        if not isinstance(obstacle_bearing, (int, float)):
            obstacle_bearing = None
        vx, vy, cnote = apply_collision_brake(
            cmd.vx,
            cmd.vy,
            nearest_person_m=control_observation.nearest_person_m,
            nearest_obstacle_m=control_observation.nearest_obstacle_m,
            nearest_obstacle_bearing_rad=obstacle_bearing,
            policy=self.pose_aware_collision_policy(observation),
        )
        person_gate_stop = cnote == "person_stop"
        # Count *this* tick's obstacle-gate verdict for the next tick's
        # blocked-route check. Read here rather than inferred later because
        # ``cnote`` is rewritten by the all-ray shield below, and only the
        # unmodified obstacle verdict is the proof this counter is about.
        # ``person_stop`` deliberately never counts: yielding to a person is
        # the gate doing its job, not evidence that a route is impassable.
        #
        # Card A2 (NAV-GLUE), fix 3.4 — the second half of this guard used to be
        # ``self._steps_without_progress > 0`` and NAV-CORE measured why that is
        # the wrong witness. A SEMANTIC goal is re-estimated from a noisy
        # detector every tick, so ``_progress_watchdog``'s running minimum
        # distance-to-goal keeps ratcheting down while the body stands still.
        # Over a fully stopped 900-tick arm-A episode the counter peaked at
        # FOUR, the 60-tick release never fired, and the mission spent its whole
        # step budget parked at 0.79 m with the route still ``status=planned``.
        # That is the silent-stall class (33/60 arm A). The witness is now the
        # BODY — it did not travel while the gate hard-stopped it — which no
        # amount of goal jitter can reset.
        if cnote == "obstacle_stop" and self._body_is_still:
            self._steps_gate_blocked += 1
        else:
            self._steps_gate_blocked = 0
        ramp_seed = self._update_ramp_memory(control_observation, cmd.vx, cnote)
        max_vx = float(self.safety.get("max_vx", 1.0))
        max_vy = float(self.safety.get("max_vy", 1.0))
        max_vyaw = float(self.safety.get("max_vyaw", 1.5))
        vx = max(-max_vx, min(max_vx, vx))
        # Preserve bounded lateral motion from controllers that intentionally
        # use it (for example close repositioning or recovery). The default
        # point-goal controller is forward-preferred and normally emits vy=0.
        vy = max(-max_vy, min(max_vy, vy))
        vyaw = max(-max_vyaw, min(max_vyaw, cmd.vyaw))
        # Yield-advance: on the first clear tick after person_stop, lift this
        # tick's post-brake command as well as the navigator slew seed. Still
        # bounded by max_vx and every downstream shield/gate.
        if (
            ramp_seed > 0.0
            and not person_gate_stop
            and cnote == "clear"
            and vx >= 0.0
        ):
            vx = max(vx, min(ramp_seed, max_vx))
        # D15-B (ii): proposer-side compliant-speed cap. Applied AFTER every
        # existing clamp and lift so it is the last word this pipeline has on
        # translation magnitude, and BEFORE the shields/gate that dispose of it.
        if self.person_aware_nav:
            vx, vy, cap_note = self._person_compliant_translation(
                control_observation, vx, vy
            )
            if cap_note:
                cnote = f"{cnote}|{cap_note}"
        if self.all_ray_shield is not None:
            from .experimental_all_ray_shield import apply_v8_all_ray_shield

            try:
                shield = apply_v8_all_ray_shield(
                    vx,
                    vy,
                    vyaw,
                    control_observation.lidar,
                    angle_min_rad=control_observation.extras.get("lidar_angle_min_rad"),
                    angle_increment_rad=control_observation.extras.get("lidar_angle_increment_rad"),
                    config=self.all_ray_shield,
                )
            except (TypeError, ValueError, RuntimeError):
                vx = 0.0
                vy = 0.0
                cnote = f"{cnote}|all_ray_contract_invalid_stop"
            else:
                vx = shield.output_vx_mps
                vy = shield.output_vy_mps
                cnote = f"{cnote}|{shield.note}"
        note = f"{cmd.note}|{cnote}" if cmd.note else cnote
        # VS-4: stamp the verify counters onto the approach ticks — the trace is
        # where adjudication #19's conjuncts have to be assertable from. Both
        # returns below are non-terminal (``stop=False``), so ``reason`` (the
        # runner's terminal-note field) is never touched by this.
        note = self._lock_on_telemetry_note(note)
        # Person-stop authority is decided by apply_collision_brake; keep the
        # zero return even if a later shield note rewrites ``cnote``.
        if person_gate_stop or cnote.endswith("_stop"):
            return MidLevelCommand(vx=0.0, vy=0.0, vyaw=vyaw, stop=False, note=note)
        return MidLevelCommand(vx=vx, vy=vy, vyaw=vyaw, stop=False, note=note)

    # Below this the navigator is not "running" in any sense worth
    # remembering: the align branch emits vx=0.0 at every corner
    # (grid_navigator align cut), and recording that as a running tick wipes
    # exactly the memory this feature exists to hold (arbitration OB-4).
    RAMP_RUNNING_FLOOR_MPS = 0.05

    # ---- D15-B: person-aware navigation (flag ``person_aware_nav``) --------
    #
    # Everything below runs ONLY under the flag. It reads the person channels
    # the observation already publishes — ``nearest_person_m`` (+ bearing),
    # ``extras['dynamic_agents']`` and ``extras['owner_track']``, the same
    # payloads ``grid_navigator._refresh_dynamic_costs`` consumes — and never
    # invents perception. A harness that publishes no person channel therefore
    # gets no behaviour change even flag-ON; that is a property of the harness,
    # not of this code (see W1_D15_STATUS.md, handoff H-1).

    def _person_keepout_tools(self) -> tuple[Any, Any, Any, Any] | None:
        """Soft-import the derived keepout module and the gate's own predicates.

        Imported here rather than at module scope because this file is copied
        verbatim into frozen BARN bundles whose package predates both modules;
        a hard import would break them on load. Flag-ON with the module absent
        degrades to flag-OFF behaviour, loudly, once.

        ``_toward`` is IMPORTED from the gate rather than restated: the whole
        point of the cap is to agree with the disposer's own arithmetic.
        """

        if self._person_keepout_unavailable:
            return None
        try:
            from parcel_robot.models import VelocityCommand

            from . import person_keepout
            from .reactive_safety import ReactiveSafetyPolicy, _toward
        except ImportError as error:  # pragma: no cover — frozen bundle path
            self._person_keepout_unavailable = True
            logger.warning("person_aware_nav disabled: %s", error)
            return None
        return person_keepout, ReactiveSafetyPolicy, _toward, VelocityCommand

    def _person_keepout_policy(self, policy_cls: Any) -> Any:
        """The clearance authority the keepout derives from.

        ``ReactiveSafetyPolicy()`` defaults ARE the authority
        (``SafetyEnvelope.person_stop(0.0)`` / ``person_comfort_band_m``), which
        is what a commissioned gate is floored to. A commissioning file may make
        the LIVE gate stricter; that can only make this proposal be refused, and
        never make a refused command approved, because the cap below is a
        minimum with the pipeline's existing clamps.
        """

        return policy_cls()

    def _declared_people(
        self, observation: NavObservation
    ) -> list[tuple[float, float | None]]:
        """``(clearance_m, bearing_rad)`` for every person the observation declares.

        Clearance convention is the gate's (base-centre to person surface), so
        payload CENTRES are converted with the same
        ``owner_collision_envelope_m`` the gate subtracts when it turns the
        owner's centre distance into a clearance.
        """

        tools = self._person_keepout_tools()
        if tools is None:
            return []
        _, policy_cls, _, _ = tools
        policy = self._person_keepout_policy(policy_cls)
        people: list[tuple[float, float | None]] = []

        nearest = observation.nearest_person_m
        if isinstance(nearest, (int, float)) and math.isfinite(float(nearest)):
            bearing = observation.extras.get("person_bearing_rad")
            people.append(
                (
                    float(nearest),
                    float(bearing)
                    if isinstance(bearing, (int, float)) and not isinstance(bearing, bool)
                    else None,
                )
            )

        robot = _pose_in(observation, MAP_FRAME)
        yaw = getattr(robot, "yaw", 0.0)
        for key in ("dynamic_agents", "owner_track"):
            for x, y, _ in _person_payload_entries(observation.extras.get(key)):
                dx = x - robot.x
                dy = y - robot.y
                clearance = math.hypot(dx, dy) - policy.owner_collision_envelope_m
                people.append(
                    (max(0.0, clearance), _wrap_to_pi(math.atan2(dy, dx) - yaw))
                )
        return people

    def _publish_person_costs(self, observation: NavObservation) -> NavObservation:
        """Give the planner the people it would otherwise be BLIND to.

        The planner already owns an additive dynamic-agent cost layer
        (``GridPlanner.set_dynamic_cost_layer``: a cost, never a mask — it can
        only make a cell more expensive, so it cannot open a route that hard
        inflation closed), fed from ``extras['dynamic_agents']`` /
        ``extras['owner_track']``. D-15's bystander reached that layer through
        NEITHER: the harness publishes no payload and the person is not in the
        LiDAR either, so A* replanned straight through a human it could not see.

        Flag-ON, a person carried only on the SENSED scalar channel
        (``nearest_person_m`` + ``person_bearing_rad``) is converted into one
        payload entry in the planner's own contract. Deliberately narrow:

        * it runs ONLY when both payloads are empty, so a person can never be
          costed twice (the runtime publishes both channels for the same body);
        * it does not touch existing entries — measured, widening their
          ``radius_m`` to the keepout ring FLATTENS the Gaussian lobe and
          destroys the very cost gradient A* detours on (0.05 m of progress
          against 3.86 m; the same "flat mesa" defect ``dynamic_costs`` records
          for 2026-08-04). The ring belongs in a cost layer of its own —
          ``person_keepout.keepout_cost_field`` is written and tested for it —
          which lives in ``grid_navigator``/``grid_planner``, files no card in
          this batch owns (handoff H-2, W1_D15_STATUS.md);
        * the footprint is the person's own collision envelope from the policy,
          never an invented radius.

        Perception is not invented here: the person must already be sensed.
        """

        tools = self._person_keepout_tools()
        if tools is None:
            return observation
        _, policy_cls, _, _ = tools
        policy = self._person_keepout_policy(policy_cls)
        if _person_payload_entries(
            observation.extras.get("dynamic_agents")
        ) or _person_payload_entries(observation.extras.get("owner_track")):
            return observation

        nearest = observation.nearest_person_m
        bearing = observation.extras.get("person_bearing_rad")
        if not isinstance(nearest, (int, float)) or isinstance(nearest, bool):
            return observation
        if not isinstance(bearing, (int, float)) or isinstance(bearing, bool):
            return observation
        distance = float(nearest) + policy.owner_collision_envelope_m
        if not (math.isfinite(distance) and math.isfinite(float(bearing))):
            return observation

        robot = _pose_in(observation, MAP_FRAME)
        angle = float(bearing) + getattr(robot, "yaw", 0.0)
        extras = dict(observation.extras)
        extras["dynamic_agents"] = [
            {
                "id": str(observation.extras.get("person_id") or "person"),
                "x": robot.x + distance * math.cos(angle),
                "y": robot.y + distance * math.sin(angle),
                "vx": 0.0,
                "vy": 0.0,
                "radius_m": policy.owner_collision_envelope_m,
            }
        ]
        self.person_costs_published_ticks += 1
        return replace(observation, extras=extras)

    def _person_compliant_translation(
        self,
        observation: NavObservation,
        vx: float,
        vy: float,
    ) -> tuple[float, float, str]:
        """Cap the commanded translation at the gate's compliant speed.

        For each declared person INSIDE the comfort band that the command is
        CLOSING ON, ``compliant_speed(clearance)`` is the largest speed whose
        predictive stop ring still clears them. Taking the minimum and scaling
        the command down leaves the direction alone — the route is the planner's
        business — and hands ``apply_reactive_safety`` a command its own
        inequality accepts.

        The cap binds on any CLOSING command — ``|Δbearing| < pi/2`` — which is
        the gate's own ``_toward`` predicate at a deliberately STRICTER
        half-angle (the gate uses a 1.15 rad cone). A proposer may be stricter
        than its disposer but never looser, and the wider predicate is what
        holds the closed-loop floor: one tick closes at most
        ``compliant_speed·dt``, and ``dt`` (0.1 s) is below ``reaction_time_s``
        (0.12 s), so clearance converges to ``person_stop_m`` FROM ABOVE and
        never crosses it. Moving AWAY is never capped — retreating from a person
        is not the behaviour to throttle.

        Measured on the card's declared-bystander cell, owner-declared bystander
        at D-15's clearance: gate vetoes 0.985 -> 0.000 of translating ticks,
        minimum person clearance 1.2000 m = ``person_stop_m`` exactly, never
        below (W1_D15_STATUS.md §4.1).

        Never raises the command: ``scale <= 1`` by construction. A clearance
        inside ``person_stop_m`` yields ``0.0`` (no compliant speed exists) and
        the robot proposes a stop, which is what the gate would have imposed.
        """

        speed = math.hypot(vx, vy)
        if speed <= 0.0:
            return vx, vy, ""
        tools = self._person_keepout_tools()
        if tools is None:
            return vx, vy, ""
        keepout, policy_cls, toward, velocity_cls = tools
        policy = self._person_keepout_policy(policy_cls)
        command = velocity_cls(vx=vx, vy=vy, vyaw=0.0)

        limit: float | None = None
        binding_clearance = math.inf
        for clearance, bearing in self._declared_people(observation):
            if clearance >= policy.person_slow_m:
                continue
            # Unknown bearing fails closed to head-on, exactly as the gate's
            # ``_toward`` does with ``bearing is None``.
            if not toward(command, bearing, half_angle=math.pi / 2.0):
                continue
            compliant = keepout.compliant_speed(clearance, policy=policy)
            if limit is None or compliant < limit:
                # ``compliant_speed`` is monotone in clearance, so the smallest
                # limit and the smallest clearance are the same person.
                limit = compliant
                binding_clearance = clearance
        if limit is None or speed <= limit:
            return vx, vy, ""

        scale = limit / speed
        capped_vx = vx * scale
        capped_vy = vy * scale
        # Scaling is not exact on the float lattice: ``hypot(vx·s, vy·s)`` can
        # land an ULP ABOVE ``limit``, and the gate compares the magnitude it
        # actually receives — one ULP is the difference between a moving robot
        # and a vetoed one at this boundary. Verify with the gate's own
        # inequality and step down until it holds. Measured before this guard:
        # 0.519 of translating ticks vetoed on the cell's owner-declared pin
        # case; after: 0.000 (W1_D15_STATUS.md §4.1).
        for _ in range(_COMPLIANT_CAP_LATTICE_STEPS):
            magnitude = math.hypot(capped_vx, capped_vy)
            if magnitude <= 0.0 or not keepout.gate_vetoes(
                binding_clearance, magnitude, policy=policy
            ):
                break
            capped_vx = math.nextafter(capped_vx, 0.0)
            capped_vy = math.nextafter(capped_vy, 0.0)
        self.person_compliant_cap_ticks += 1
        return capped_vx, capped_vy, f"person_compliant_cap={limit:.4f}"

    def _reset_ramp_memory(self) -> None:
        if self._ramp is not None:
            self._ramp.reset()
        self._ramp_fallback_ticks = 0
        self._ramp_clock = "unset"
        self.pending_ramp_seed_mps = None

    def _update_ramp_memory(
        self,
        observation: NavObservation,
        commanded_vx: float,
        collision_note: str,
    ) -> float:
        """Yield-advance memory across brief person-stops (never a gate).

        On release the seed goes to BOTH serial rate limiters, because they are
        in series and the slower one binds (arbitration OB-3, measured — see
        the deviation note in OPUS_STATUS 2026-08-06 fix round):

        ==============================================  ========  ==========
        variant                                         2.0 s     ticks->80%
        ==============================================  ========  ==========
        today (no seed)                                 1.226 m   8
        navigator slew only (pre-round wiring)          1.306 m   7
        shaper only (OB-3 as literally worded)          1.240 m   8
        both (this)                                     1.651 m   1
        ==============================================  ========  ==========

        Seeding the shaper alone is a near no-op because the shaper *tracks the
        navigator's command*, and an unseeded navigator is still ramping from
        zero — so the clamp in ``_apply_yield_advance_seed`` (seed ≤ the
        authorised command) collapses it. ``RampMemory`` remains the single
        source of the value; both call sites are rate limiters, not writers.

        Returns the release seed on the first clear tick after a stop (else
        0.0) so ``step`` can also lift this tick's post-brake command.
        """

        if self._ramp is None:
            return 0.0
        now_s = self._ramp_now_s(observation)
        seed = 0.0
        try:
            if collision_note == "person_stop":
                self._ramp.note_stopped(now_s)
                return 0.0
            if self._ramp.state == "stopped":
                seed = self._ramp.release(now_s)
                if seed > 0.0:
                    # Limiter 1: the navigator's own slew state.
                    seed_ramp = getattr(self._navigator, "seed_ramp", None)
                    if callable(seed_ramp):
                        seed_ramp(seed)
                    # Limiter 2: published for the runtime's S-curve shaper.
                    self.pending_ramp_seed_mps = seed
            if commanded_vx > self.RAMP_RUNNING_FLOOR_MPS:
                self._ramp.note_running(now_s, commanded_vx)
        except ValueError as error:
            logger.warning("ramp memory reset: %s", error)
            self._reset_ramp_memory()
            return 0.0
        return self._final_metre_creep(observation, seed, collision_note)

    #: The band in which the yield policy applies. N11's residual is a
    #: *final-approach* problem: the measured failure was a robot 0.33 m outside
    #: the region on the clock, not a robot that could not cross a street.
    FINAL_APPROACH_BAND_M = 1.0
    #: Crawl the yield policy may seed when the memory has decayed to nothing.
    #: Deliberately tiny — it is a creep, and it is a *recovery* speed that
    #: every downstream authority still bounds on the same tick.
    FINAL_APPROACH_CREEP_MPS = 0.12
    #: Prediction horizon for "will the stream have cleared?".
    FINAL_APPROACH_HORIZON_S = 1.5

    #: Scan-while-translating (card seamless-pacing seam 1, 2026-08-09). When the
    #: grounder has RESOLVED a single (non-interchangeable) target and the body is
    #: already roughly facing it, close distance during the multi-view
    #: confirmation instead of rotating in place and only then translating —
    #: the audit's "opening full-turn scan even when the frustum already RESOLVED
    #: the target". Reuses the yield creep (one value) and is hard-gated so it can
    #: neither drive a collision nor bias an instance ranking: it never fires for
    #: a region/"nearest" look-around sweep, only when the target is within the
    #: half-angle ahead (a straight-line approach, not an arc the actuator shaper
    #: fights), only past ``_SCAN_CREEP_MIN_RANGE_M`` (the commit/approach owns the
    #: close range), and only with a measured omnidirectional clearance beyond a
    #: full creep reaction horizon — and it is still bounded by every downstream
    #: reactive gate. Absent clearance data it does NOT creep (fail-safe).
    SCAN_CREEP_MPS = FINAL_APPROACH_CREEP_MPS
    _SCAN_CREEP_MAX_BEARING_RAD = 0.30
    #: Below this range the commit + terminal-approach path owns the close
    #: distance, so there is no reason to creep during confirmation. 1.5 m, not
    #: the retired 1.2 F-proximity value.
    _SCAN_CREEP_MIN_RANGE_M = 1.5
    _SCAN_CREEP_CLEARANCE_M = 1.0

    def _final_metre_creep(
        self,
        observation: NavObservation,
        seed: float,
        collision_note: str,
    ) -> float:
        """Yield-advance for the last metre, on the tracker's predicted paths.

        The N11 residual, measured: with a crosswalk stream running, the robot
        reaches 0.33 m short of the sidewalk region and then alternates
        person-stop / re-ramp-from-zero until the 240 s budget expires. The
        ramp memory already covers *short* interruptions; what it cannot cover
        is a stop long enough that ``release`` legitimately returns 0.0, after
        which the robot restarts from a standstill inside the last metre and
        the next pedestrian arrives before it has moved.

        This adds exactly one thing: when the safety gate has **already
        opened**, the robot is inside the final approach band, and the
        *tracker's own constant-velocity predictions* say no person will enter
        the person-stop envelope within the horizon, the release seed floors at
        a creep instead of zero.

        Safety argument, unchanged from ``RampMemory``'s: this is not a gate
        and not a command source. It is only ever consulted on a tick where
        ``apply_collision_brake`` already returned ``clear``, it only raises a
        *recovery* seed, and the seed is still bounded by ``max_vx``, the
        reactive gate, the TTC gate, the shaper and the arbiter on that same
        tick. It cannot make the robot move on a tick it would otherwise have
        stopped on.

        The predictions come from :mod:`parcel_robot.navigation.tracker` and
        not from ``extras['dynamic_agents']['vx']``: the payload's velocity is
        simulator truth, and a policy that consumes oracle velocity is not a
        policy that would survive a real detector.
        """

        if collision_note != "clear" or seed >= self.FINAL_APPROACH_CREEP_MPS:
            return seed
        # ``getattr``: the ramp-memory unit tests drive this path on a bare
        # ``object.__new__(DirectiveNavigator)`` with only the ramp attributes
        # set, and a pacing helper must not require a whole navigator.
        mission = getattr(self, "mission", None)
        if mission is None or mission.goal is None:
            return seed
        robot = _pose_in(observation, MAP_FRAME)
        remaining = math.hypot(mission.goal.x - robot.x, mission.goal.y - robot.y)
        if remaining > self.FINAL_APPROACH_BAND_M:
            return seed
        if not self._predicted_people_clear(observation, robot):
            return seed
        mission.metadata["final_metre_yield"] = {
            "remaining_m": remaining,
            "seed_before_mps": seed,
            "seed_after_mps": self.FINAL_APPROACH_CREEP_MPS,
            "horizon_s": self.FINAL_APPROACH_HORIZON_S,
        }
        creep = self.FINAL_APPROACH_CREEP_MPS
        seed_ramp = getattr(self._navigator, "seed_ramp", None)
        if callable(seed_ramp):
            seed_ramp(creep)
        self.pending_ramp_seed_mps = creep
        return creep

    def _predicted_people_clear(self, observation: NavObservation, robot: Any) -> bool:
        """Will every confirmed person stay outside the stop envelope?

        Fail-closed: no people tracker, or no confirmed person track at all,
        returns ``False`` — an absence of tracks is not evidence of an empty
        pavement, it is an absence of evidence.
        """

        people = getattr(self, "_people_tracker", None)
        if people is None:
            return False
        confirmed = people.confirmed
        if not confirmed:
            return False
        stop_m = float(self.collision.person_stop_m)
        steps = 6
        for index in range(steps + 1):
            horizon = self.FINAL_APPROACH_HORIZON_S * index / steps
            for track in confirmed:
                px, py = track.predicted_position(horizon)
                if math.hypot(px - robot.x, py - robot.y) <= stop_m:
                    return False
        return True

    def take_pending_ramp_seed(self) -> float | None:
        """Consume the published yield-advance seed (single reader: runtime)."""

        seed = self.pending_ramp_seed_mps
        self.pending_ramp_seed_mps = None
        return seed

    def _ramp_now_s(self, observation: NavObservation) -> float:
        """Monotonic seconds for the pacing memory, from ONE clock per mission.

        Mixing a sensor stamp with the tick fallback guarantees a time
        regression the moment the stamp drops out, so the first tick decides
        the base and the mission keeps it.
        """

        if self._ramp_clock != "tick":
            stamp = observation.extras.get("odometry_timestamp_s")
            if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
                value = float(stamp)
                if math.isfinite(value):
                    self._ramp_clock = "stamp"
                    return value
            if self._ramp_clock == "stamp":
                # The stamp vanished mid-mission: switching bases would look
                # like a jump backwards. Restart the memory on the tick clock.
                if self._ramp is not None:
                    self._ramp.reset()
                self._ramp_fallback_ticks = 0
        self._ramp_clock = "tick"
        self._ramp_fallback_ticks += 1
        return float(self._ramp_fallback_ticks) * 0.1

    #: Slack added to the target's own radius when deciding whether a LiDAR
    #: return belongs to the committed target. It covers the footprint-add
    #: approximation in the range→surface-point projection, range quantisation,
    #: and the tracker's own position sigma. It is *not* a free parameter: it
    #: has to stay well under the narrowest arrival band (``NEXT_TO_BAND_M`` is
    #: 1.1 m wide) or a neighbouring body could be exempted as "the target".
    TARGET_ASSOCIATION_SLACK_M = 0.45
    #: Gate for re-finding the committed candidate in a later frame.
    CANDIDATE_ASSOCIATION_GATE_M = 0.75

    def _update_tracker(self, observation: NavObservation) -> None:
        """Feed this tick's candidates to the classical tracker.

        This is the association authority replacing oracle-id equality. It runs
        on every tick, including ticks where the mission has not resolved a
        target yet — a track needs its M-of-N history *before* the first
        arrival question is asked, not after.
        """

        if self._tracker is None or Detection is None:
            return
        raw = observation.extras.get("semantic_candidates")
        if not isinstance(raw, (list, tuple)):
            raw = ()
        now = observation.extras.get("time_s")
        now_s = float(now) if isinstance(now, (int, float)) and math.isfinite(now) else None
        if now_s is None or self._tracker_last_time_s is None or now_s < self._tracker_last_time_s:
            dt = 0.1
        else:
            dt = max(0.0, now_s - self._tracker_last_time_s)
        self._tracker_last_time_s = now_s
        detections = []
        for index, item in enumerate(raw[:64]):
            if not isinstance(item, dict):
                continue
            point = _candidate_xy(item)
            if point is None:
                continue
            try:
                score = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            if not math.isfinite(score):
                score = 0.0
            detections.append(
                Detection(
                    x=point[0],
                    y=point[1],
                    label=str(item.get("label") or ""),
                    score=max(0.0, min(1.0, score)),
                    source_id=str(item.get("id") or f"candidate-{index}"),
                )
            )
        self._tracker.step(detections, dt_s=dt)
        self._update_people_tracker(observation, dt)
        self._bind_target_track()

    def _update_people_tracker(self, observation: NavObservation, dt: float) -> None:
        """Track dynamic agents from POSITION ONLY.

        ``extras['dynamic_agents']`` carries ``vx``/``vy`` straight from the
        simulator. Feeding those to the yield policy would be consuming oracle
        velocity in a dispositive position, so only the positions are ingested
        and the velocity is the Kalman filter's own estimate.
        """

        if self._people_tracker is None or Detection is None:
            return
        raw = observation.extras.get("dynamic_agents")
        if not isinstance(raw, (list, tuple)):
            self._people_tracker.step([], dt_s=dt)
            return
        detections = []
        for item in raw[:16]:
            if not isinstance(item, dict):
                continue
            try:
                x = float(item["x"])
                y = float(item["y"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (math.isfinite(x) and math.isfinite(y)):
                continue
            detections.append(Detection(x=x, y=y, label="person", score=1.0))
        self._people_tracker.step(detections, dt_s=dt)

    def _bind_target_track(self) -> None:
        """(Re-)bind the committed target to a confirmed track, geometrically."""

        if self._tracker is None or self.mission is None:
            return
        committed = _position(self.mission.metadata.get("candidate_position"))
        if committed is None:
            return
        current = self._tracker.track_by_id(self._target_track_id or -1)
        gate = self.CANDIDATE_ASSOCIATION_GATE_M + float(
            self.mission.metadata.get("candidate_radius_m", 0.0) or 0.0
        )
        if current is not None and math.hypot(
            current.mean[0] - committed[0], current.mean[1] - committed[1]
        ) <= gate:
            return
        track = self._tracker.nearest_confirmed(
            committed[0], committed[1], max_distance_m=gate
        )
        self._target_track_id = track.track_id if track is not None else None

    def _tracked_target_xy(self) -> tuple[float, float] | None:
        """Where the committed target *is*, per the tracker.

        Falls back to the position recorded at commit time when no track has
        been confirmed for it — a committed goal without a live track is the
        normal state for a region the robot is standing inside, whose centroid
        left the frustum.
        """

        if self.mission is None:
            return None
        if self._tracker is not None and self._target_track_id is not None:
            track = self._tracker.track_by_id(self._target_track_id)
            if track is not None:
                return track.position
        committed = _position(self.mission.metadata.get("candidate_position"))
        return None if committed is None else (committed[0], committed[1])

    def _target_association_radius_m(self) -> float:
        if self.mission is None:
            return self.TARGET_ASSOCIATION_SLACK_M
        radius = float(self.mission.metadata.get("candidate_radius_m", 0.0) or 0.0)
        return max(0.0, radius) + self.TARGET_ASSOCIATION_SLACK_M

    def _lidar_point_is_target(
        self,
        observation: NavObservation,
        distance: float,
        bearing: float,
        target_xy: tuple[float, float] | None,
    ) -> bool:
        """Geometric replacement for ``obstacle_id in target_ids``.

        The test is **"does this ray hit the target?"**, not "is this return
        near the target's centre". That distinction is load-bearing: the LiDAR
        contract reports footprint-to-*surface* clearance, so a return on a
        body of unknown radius lands short of that body's centre by exactly the
        radius the semantic channel usually does not carry. A centre-distance
        test therefore fails on precisely the objects it most needs to accept
        (a 0.88 m-radius lamp post reads 0.88 m "away" from itself).

        So: project the target onto the ray. The return belongs to the target
        when the ray points at it (perpendicular offset within the target's
        radius plus :attr:`TARGET_ASSOCIATION_SLACK_M`) and the return is not
        *beyond* it (range no farther than the target's own along-ray distance
        plus the same slack). For a convex body of unknown radius the first
        return along the bearing to that body **is** its near surface.

        The lateral slack is what bounds the mistake this can make: a body
        standing between the robot and the target, within the slack of the line
        of sight, is exempted from *local evasion only*. Every other authority
        — the reactive gate, the TTC gate, and the runtime's own final brake —
        still sees the unmodified sensor view on the same tick.
        """

        if target_xy is None:
            return False
        robot = _pose_in(observation, MAP_FRAME)
        ray = float(distance) + ROBOT_FOOTPRINT_RADIUS_M
        angle = robot.yaw + float(bearing)
        return _ray_hits_target(
            robot_xy=(robot.x, robot.y),
            ray_angle_rad=angle,
            ray_range_m=ray,
            target_xy=target_xy,
            gate_m=self._target_association_radius_m(),
        )

    def _target_clearance(self, observation: NavObservation) -> float | None:
        """Nearest LiDAR clearance to the *tracked* target, or ``None``.

        Stratum-2 replacement for ``_current_target_clearance(obs, ids)``: the
        set of "returns that are the target" is now decided by geometry against
        the tracked position, so a detector that renames the object between
        frames, or a LiDAR that never shared the id space at all, still yields
        the measurement the ``near`` band needs.
        """

        target_xy = self._tracked_target_xy()
        if target_xy is None:
            return None
        raw = observation.extras.get("lidar_obstacles")
        if not isinstance(raw, (list, tuple)):
            return None
        clearances: list[float] = []
        for item in raw[:64]:
            if not isinstance(item, dict):
                continue
            value = item.get("distance_m")
            bearing = item.get("bearing_rad")
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0.0
                or isinstance(bearing, bool)
                or not isinstance(bearing, (int, float))
                or not math.isfinite(float(bearing))
            ):
                continue
            if self._lidar_point_is_target(
                observation, float(value), float(bearing), target_xy
            ):
                clearances.append(float(value))
        return min(clearances, default=None)

    def _control_observation(self, observation: NavObservation) -> NavObservation:
        """Exclude only a validated relational target from local obstacle evasion.

        A lamppost remains present in raw LiDAR and terminal verification, but
        the point controller must be allowed to approach its precomputed safe
        stand-off pose. All other returns remain collision obstacles, and the
        runtime's independent final brake still sees the unmodified sensor view.

        **Stratum 2:** "is this return the target?" used to be
        ``obstacle_id in {candidate_id, *associated_lidar_ids}`` — an oracle
        join between two id spaces that only exists because the simulator hands
        the same string to the semantic channel and the range channel. A
        detector and a LiDAR share no id space at all. The question is now
        answered geometrically against the tracked target position.
        """

        if (
            self.mission is None
            or self.mission.semantic_goal is None
            or self.mission.semantic_goal.terminal_relation not in {"near", "next_to", "towards"}
        ):
            return observation
        target_xy = self._tracked_target_xy()
        if target_xy is None:
            return observation
        raw_lidar = observation.extras.get("lidar_obstacles")
        if not isinstance(raw_lidar, (list, tuple)):
            nearest_bearing = observation.extras.get("obstacle_bearing_rad")
            nearest_distance = observation.nearest_obstacle_m
            if (
                nearest_distance is None
                or not isinstance(nearest_bearing, (int, float))
                or isinstance(nearest_bearing, bool)
                or not self._lidar_point_is_target(
                    observation, float(nearest_distance), float(nearest_bearing), target_xy
                )
            ):
                return observation
            extras = dict(observation.extras)
            extras.update(
                {
                    "obstacle_id": None,
                    "obstacle_bearing_rad": None,
                    "terminal_target_clearance_m": observation.nearest_obstacle_m,
                }
            )
            return replace(observation, nearest_obstacle_m=None, extras=extras)

        alternatives: list[tuple[float, float, str | None]] = []
        target_clearance: float | None = None
        for item in raw_lidar[:64]:
            if not isinstance(item, dict):
                continue
            obstacle_id = str(item["id"]) if item.get("id") else None
            try:
                distance = float(item["distance_m"])
                bearing = float(item["bearing_rad"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                not math.isfinite(distance)
                or not math.isfinite(bearing)
                or distance < 0.0
                or not -math.pi <= bearing <= math.pi
            ):
                continue
            if self._lidar_point_is_target(observation, distance, bearing, target_xy):
                target_clearance = (
                    distance if target_clearance is None else min(target_clearance, distance)
                )
            else:
                alternatives.append((distance, bearing, obstacle_id))
        nearest = min(alternatives, default=None, key=lambda item: item[0])
        extras = dict(observation.extras)
        extras["terminal_target_clearance_m"] = target_clearance
        extras["obstacle_id"] = nearest[2] if nearest is not None else None
        extras["obstacle_bearing_rad"] = nearest[1] if nearest is not None else None
        return replace(
            observation,
            nearest_obstacle_m=nearest[0] if nearest is not None else None,
            extras=extras,
        )

    def _ingest_memory(self, observation: NavObservation) -> None:
        if self.memory is None:
            return
        if ingest_observation_memory is not None:
            ingest_observation_memory(self.memory, observation)
            return
        raw = observation.extras.get("semantic_candidates", [])
        if not isinstance(raw, (list, tuple)):
            return
        now = float(observation.extras.get("time_s") or 0.0)
        if not math.isfinite(now):
            now = 0.0
        entities: list[dict[str, object]] = []
        for item in raw[:64]:
            if not isinstance(item, dict):
                continue
            entities.append(
                {
                    "id": item.get("id"),
                    "label": item.get("label"),
                    "kind": item.get("kind", "object"),
                    "position": item.get("position")
                    or item.get("centroid")
                    or (
                        [
                            sum(float(p[0]) for p in (item.get("polygon") or []))
                            / max(len(item.get("polygon") or []), 1),
                            sum(float(p[1]) for p in (item.get("polygon") or []))
                            / max(len(item.get("polygon") or []), 1),
                        ]
                        if item.get("polygon")
                        else None
                    ),
                    "polygon": item.get("polygon"),
                    "confidence": item.get("confidence", 0.98),
                }
            )
        if entities:
            self.memory.observe(entities, now_s=now)

    def _memory_candidates(
        self, semantic_goal: Any, observation: NavObservation
    ) -> list[SemanticCandidate]:
        if self.memory is None:
            return []
        now = float(observation.extras.get("time_s") or 0.0)
        recalled = self.memory.recall(semantic_goal.query, now_s=now)
        # Also try alias-normalized recalls via frustum matcher on memory snapshots.
        if not recalled:
            for entity in self.memory.recall_all(now_s=now):
                if _label_matches(semantic_goal.query, entity.label, ()):
                    recalled = (*recalled, entity)
        out: list[SemanticCandidate] = []
        for entity in recalled:
            if entity.kind != semantic_goal.kind and not (
                semantic_goal.kind == "region" and entity.kind == "region"
            ):
                # Allow object queries against object memories only.
                if semantic_goal.kind == "object" and entity.kind != "object":
                    continue
                if semantic_goal.kind == "region" and entity.kind != "region":
                    continue
            out.append(
                SemanticCandidate(
                    candidate_id=entity.entity_id,
                    label=entity.label,
                    x=entity.x,
                    y=entity.y,
                    confidence=entity.confidence,
                    kind=entity.kind,
                    polygon=entity.polygon or (),
                    source="semantic_memory",
                    observed_at=entity.last_seen_s,
                    reachable=True,
                    metadata={},
                )
            )
        # A commitment this mission already released as unroutable must not
        # come back through the memory door either (``_unroutable_goal_recovery``).
        if self._unreachable_candidates:
            out = [
                item
                for item in out
                if item.candidate_id not in self._unreachable_candidates
            ]
        # MAP: semantic memory is a world-frame store, so ranking recalled
        # entities by range is a MAP-frame question.
        robot_x, robot_y = _pose_in(observation, MAP_FRAME).xy
        return sorted(
            out,
            key=lambda item: (
                -item.confidence,
                math.hypot(item.x - robot_x, item.y - robot_y),
                item.candidate_id,
            ),
        )

    def _try_detection_lock_on(
        self,
        semantic_goal: Any,
        mapped: SemanticCandidate | None,
        observation: NavObservation,
        *,
        robot_xy: tuple[float, float],
    ) -> SemanticCandidate | MidLevelCommand | None:
        """D3: D1+SigLIP detection trigger → ONE stamped SE2Goal → candidate.

        Returns the locked SemanticCandidate on commit, a stop command on arbiter
        veto, or ``None`` while evidence is still accumulating.
        """

        assert self.mission is not None
        session = self._detection_lock_on
        if session is None:
            return None
        now_s = float(observation.extras.get("time_s") or 0.0)
        now_ns = int(max(0.0, now_s) * 1_000_000_000) + int(self._scan_steps)
        decision = session.observe_candidate(
            query=str(semantic_goal.query),
            candidate=mapped,
            robot_xy=robot_xy,
            now_ns=now_ns,
        )
        if decision is None:
            if self._scan_steps + 1 >= self.scan_budget_steps:
                reply = (
                    honest_not_found_reply(
                        _refusal_label(semantic_goal),
                        scanned=self._already_scanned,
                        searched=self._already_searched,
                    )
                    if honest_not_found_reply is not None
                    else "target not confirmed"
                )
                self.mission.status = "failed"
                self.mission.metadata.update(
                    {
                        "resolution_state": "not_found",
                        "recovery_phase": "failed",
                        "reply": reply,
                        "lock_on_outcome": "budget_exhausted",
                    }
                )
                return MidLevelCommand(stop=True, note="detection_lock_on_budget")
            return None
        self.mission.metadata["lock_on_credibility"] = decision.credibility
        self.mission.metadata["lock_on_siglip_score"] = decision.siglip_score
        self.mission.metadata["arrival_anchor_covariance"] = (
            (float(decision.covariance[0][0]), float(decision.covariance[0][1])),
            (float(decision.covariance[1][0]), float(decision.covariance[1][1])),
        )
        self.mission.metadata["lock_on_source"] = LOCK_ON_PROPOSER_SOURCE
        if (
            _HAS_INSTRUCTNAV
            and SE2Goal is not None
            and self.proposer_bus is not None
            and self.goal_arbiter is not None
        ):
            proposed = session.build_se2_goal(
                decision,
                task_id=self._active_task_id,
                plan_revision=self._active_plan_revision,
                now_s=now_s,
            )
            self.proposer_bus.publish(proposed)
            self.goal_arbiter.set_plan_step(LOCK_ON_PLAN_STEP_ID)
            chosen = self.goal_arbiter.resolve((proposed,), now_s=now_s)
            if chosen is None:
                self.mission.status = "failed"
                self.mission.metadata["resolution_state"] = "arbiter_veto"
                return MidLevelCommand(stop=True, note="detection_lock_on_vetoed")
            self.mission.metadata["lock_on_se2"] = chosen.as_dict()
        # Prefer the grounded instance; retarget xy to the fused metric estimate.
        base = mapped if mapped is not None else decision.source_candidate
        if base is None:
            base = SemanticCandidate(
                candidate_id=decision.candidate_id,
                label=decision.label,
                x=float(decision.position[0]),
                y=float(decision.position[1]),
                confidence=float(decision.confidence),
                kind="object",
                source=LOCK_ON_PROPOSER_SOURCE,
                reachable=True,
                metadata={
                    "covariance_xy": decision.covariance,
                    "lock_on": True,
                },
            )
            return base
        meta = dict(base.metadata or {})
        meta["covariance_xy"] = decision.covariance
        meta["lock_on"] = True
        meta["lock_on_credibility"] = decision.credibility
        return SemanticCandidate(
            candidate_id=base.candidate_id,
            label=base.label,
            x=float(decision.position[0]),
            y=float(decision.position[1]),
            z=float(getattr(base, "z", 0.0) or 0.0),
            confidence=float(decision.confidence),
            kind=base.kind,
            polygon=base.polygon,
            source=base.source,
            observed_at=base.observed_at,
            reachable=base.reachable,
            metadata=meta,
        )

    # ------------------------------------------------------------------
    # VS-4 — arrival integrity + verify-on-approach (record §2.2(a) + (b))
    #
    # Every method below returns early unless ``lock_on_verify_on_approach`` is
    # on, and the flag can only be on when ``detection_lock_on`` is: the
    # unconditional path is byte-identical (adjudication #9). The architecture
    # is reference/estimate separation — the grounded instance is the
    # REFERENCE and perception never rewrites it; a lock-on produces an
    # ESTIMATE that must stay consistent with the reference; K0 keeps verifying
    # the reference and is untouched here (no epsilon, no arrival reason, no
    # special case). This path can only ever WITHHOLD or RETRACT a proposal.
    # ------------------------------------------------------------------

    def _lock_on_grounded_reference(
        self,
        semantic_goal: Any,
        result: SemanticCandidate,
    ) -> Any | None:
        """The mission's REFERENCE, built from the grounded instance only.

        Never from the fused point: that rewrite is the measured V-E defect
        (record §2.1(1)). Returns ``None`` when the candidate carries no usable
        geometry, which leaves the whole verify path inert for that commit —
        refusals are added by evidence, never by its absence.

        AF-2 (``scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md``, should-fix 1): the
        terminal RELATION and — when K0 built a band-shaped arrival region for
        this very commit — that region's band travel with the reference, because
        the checkpoint schedule must cover the whole K0 arrival region and the
        near-object envelope alone does not (``towards`` reaches 2.5 m,
        ``next_to`` reaches ``R+1.5``). The band handed over is
        :meth:`_build_arrival_goal_region`'s own output, i.e. literally the
        region K0 will verify the arrival against, so the two cannot disagree.
        """

        if not self.lock_on_verify_on_approach or GroundedReference is None:
            return None
        landmark_id = str(getattr(result, "candidate_id", "") or "")
        if not landmark_id:
            return None
        kind = ReferenceKind.from_goal_kind(getattr(semantic_goal, "kind", ""))
        polygon = tuple(
            (float(point[0]), float(point[1]))
            for point in (getattr(result, "polygon", None) or ())
            if isinstance(point, (list, tuple)) and len(point) >= 2
        )
        relation = str(getattr(semantic_goal, "terminal_relation", "") or "")
        arrival_band = self._arrival_band_for_commit(relation, result)
        try:
            if kind is ReferenceKind.REGION:
                if len(polygon) < 3:
                    return None
                return GroundedReference(
                    landmark_id=landmark_id,
                    kind=kind,
                    label=str(result.label or ""),
                    polygon=polygon,
                    relation=relation,
                    arrival_band_m=arrival_band,
                )
            return GroundedReference(
                landmark_id=landmark_id,
                kind=kind,
                label=str(result.label or ""),
                center=(float(result.x), float(result.y)),
                radius_m=_metadata_float(
                    result.metadata, "radius_m", default=0.0, minimum=0.0, maximum=5.0
                ),
                relation=relation,
                arrival_band_m=arrival_band,
            )
        except (TypeError, ValueError):
            return None

    def _arrival_band_for_commit(
        self,
        relation: str,
        result: SemanticCandidate,
    ) -> tuple[float, float] | None:
        """K0's own arrival band for this commit, or ``None`` if it has none.

        Read off :meth:`_build_arrival_goal_region` — the single place this
        pipeline builds the region K0 verifies arrival against — so the verify
        schedule is derived from the SAME authority rather than a second copy of
        it. A polygon (``inside``) region carries no band and returns ``None``;
        VS-1 then derives the edge from the relation itself.
        """

        try:
            region = self._build_arrival_goal_region(relation, result)
        except (TypeError, ValueError, KeyError):
            return None
        if not isinstance(region, dict):
            return None
        band = region.get("band_m")
        if not isinstance(band, (list, tuple)) or len(band) < 2:
            return None
        try:
            low, high = float(band[0]), float(band[1])
        except (TypeError, ValueError):
            return None
        if not (math.isfinite(low) and math.isfinite(high)) or low > high:
            return None
        return (low, high)

    def _lock_on_view_candidate(
        self,
        semantic_goal: Any,
        observation: NavObservation,
    ) -> SemanticCandidate | None:
        """This tick's perception answer for the instance under verification.

        Before a commit there is nothing to associate to, so this is perception's
        own ranking (``ObservationSemanticMap.query`` order). After a commit the
        association is the pipeline's OWN stratum-2 geometry — nearest candidate
        to the tracked target position inside
        :attr:`CANDIDATE_ASSOCIATION_GATE_M` + the target's radius, the same gate
        :meth:`_bind_target_track` uses — never an oracle id join. That is what
        keeps a lock-on REFINING one instance instead of switching to another
        (record §2.2(a)(i)).
        """

        candidates = list(self._resolution_semantic_map.query(semantic_goal, observation))
        if not candidates:
            return None
        anchor = self._tracked_target_xy()
        if anchor is None or self.mission is None or self.mission.goal is None:
            return candidates[0]
        gate = self.CANDIDATE_ASSOCIATION_GATE_M + float(
            self.mission.metadata.get("candidate_radius_m", 0.0) or 0.0
        )
        best: SemanticCandidate | None = None
        best_distance: float | None = None
        for candidate in candidates:
            distance = math.hypot(float(candidate.x) - anchor[0], float(candidate.y) - anchor[1])
            if distance <= gate and (best_distance is None or distance < best_distance):
                best, best_distance = candidate, distance
        return best

    def _lock_on_estimate_xy(self, candidate: SemanticCandidate) -> tuple[float, float]:
        """The current D2 estimate, or this measurement before any fusion."""

        session = self._detection_lock_on
        estimate = None if session is None else session.localizer.estimate
        if estimate is None:
            return (float(candidate.x), float(candidate.y))
        return (float(estimate.position[0]), float(estimate.position[1]))

    def _lock_on_track_instance(self, candidate: SemanticCandidate) -> None:
        """One hypothesis per INSTANCE — a different instance is a new estimate.

        The measured D2 defect is that ``MetricLocalizer`` "fuses every
        measurement into one [x, y] state with no association gate"
        (record §2.1(1)). Left alone that produces an estimate which is about no
        instance in particular — a mixture of two sidewalks sits between them,
        outside both, and the refinement gate would then refute a perfectly good
        reference on the strength of our own contaminated fusion. Refusals must
        come from evidence about the target, so the estimator restarts whenever
        the instance under observation changes. Strictly an ADDITION of state
        hygiene: it cannot admit anything the flag-off path refuses.
        """

        candidate_id = str(getattr(candidate, "candidate_id", "") or "")
        if not candidate_id or candidate_id == self._lock_on_instance_id:
            return
        if self._detection_lock_on is not None:
            self._detection_lock_on.reset()
        self._lock_on_instance_id = candidate_id
        self._lock_on_last_admitted = None
        self._lock_on_hypothesis_committed = False
        self.lock_on_instance_switches += 1

    def _lock_on_fuse(
        self,
        semantic_goal: Any,
        observation: NavObservation,
        candidate: SemanticCandidate | None = None,
    ) -> tuple[Any, ApproachView] | None:
        """Fuse one view into D2 and return ``(estimate, view)``.

        M-of-N admission is the record's independent-evidence rule consumed by
        reference from VS-1 (``admits_for_confirmation``: one admissible view per
        full-turn scan arc, measured at the estimate). D2 fuses every view; only
        the CONFIRMER is gated, which is what kills the measured
        self-confirmation (a re-read of one cached candidate from an unmoved
        pose can no longer advance the window).
        """

        session = self._detection_lock_on
        if session is None or ApproachView is None:
            return None
        if candidate is None:
            candidate = self._lock_on_view_candidate(semantic_goal, observation)
        if candidate is None:
            return None
        self._lock_on_track_instance(candidate)
        robot = _pose_in(observation, MAP_FRAME)
        probe = ApproachView(robot_xy=robot.xy, fused_xy=self._lock_on_estimate_xy(candidate))
        admit = bool(admits_for_confirmation(self._lock_on_last_admitted, probe))
        now_s = float(observation.extras.get("time_s") or 0.0)
        now_ns = int(max(0.0, now_s) * 1_000_000_000) + int(self._lock_on_view_index)
        estimate = session.fuse_view(
            query=str(semantic_goal.query),
            candidate=candidate,
            robot_xy=robot.xy,
            now_ns=now_ns,
            admit_for_confirmation=admit,
        )
        self._lock_on_view_index += 1
        if admit:
            self._lock_on_last_admitted = probe
            self.lock_on_admitted_views += 1
        if estimate is None:
            return None
        if estimate.committed and not self._lock_on_hypothesis_committed:
            self._lock_on_hypothesis_committed = True
            self.lock_on_commits += 1
        view = ApproachView(
            robot_xy=robot.xy,
            fused_xy=estimate.position,
            covariance=estimate.covariance,
            persistence=self._lock_on_target_persists(observation),
            identity_score=float(estimate.identity_score),
        )
        return estimate, view

    def _lock_on_target_persists(self, observation: NavObservation) -> bool:
        """Is the committed detection still ASSOCIATED in this view?

        For an OBJECT the answer is the pipeline's own stratum-2 association
        between the semantic detection and the RANGE channel:
        :meth:`_target_clearance` returns the nearest LiDAR return whose ray
        geometry says it belongs to the tracked target, and ``None`` when no
        return does. "A detection with nothing behind it" — the phantom class
        this card exists to refuse — is exactly the case that returns ``None``.

        A REGION has no depth signature (a sidewalk IS the ground plane), so a
        region reference persists on the semantic channel alone; VS-1 only
        consults persistence AT a checkpoint, and K0 keeps sole authority over
        the arrival itself either way.
        """

        session = self._lock_on_verify
        if session is None or session.reference.kind is not ReferenceKind.OBJECT:
            return True
        return self._target_clearance(observation) is not None

    def _lock_on_observe_estimate(
        self,
        semantic_goal: Any,
        observation: NavObservation,
        mapped: SemanticCandidate | None = None,
    ) -> None:
        """Deference (§2.2(a)(i)): the lock-on OBSERVES; it never picks the instance.

        With ``lock_on_verify_on_approach`` on, the instance is fixed by the
        SAME authority the flag-off arm uses — the grounder's ranking, and for
        interchangeable (region / "nearest") queries the scan-complete
        boundary-aware ranking. The session still fuses D2 and still runs its
        M-of-N, but its product is the ESTIMATE (an approach pose), never the
        choice of which instance the mission is about.
        """

        if not self.lock_on_verify_on_approach:
            return
        self.lock_on_deferred_ticks += 1
        # ``mapped`` is the grounder's own pick for this tick — the SAME
        # candidate the flag-off arm would commit and the same one the
        # unconditional lock-on path feeds. Handing the estimator the ranking's
        # instance is what keeps "refine, never switch" true upstream of the
        # commit as well as after it.
        self._lock_on_fuse(semantic_goal, observation, mapped)

    def _lock_on_admission_guard(
        self,
        semantic_goal: Any,
        result: SemanticCandidate,
        observation: NavObservation,
    ) -> MidLevelCommand | None:
        """Run BEFORE any commit: FP memory, then the per-kind refinement gate.

        Returns a command when the commit is REFUSED, ``None`` when it may
        proceed unchanged. Two refusal reasons, both from the record:
        a remembered refutation at this place (VS-2's negative evidence,
        consulted before accepting any hypothesis at a remembered location), and
        a fused estimate that contradicts the grounded reference (§2.2(a)(iii) —
        "violation is a REFUTATION, not a commit").
        """

        memory = self._lock_on_fp_memory
        if memory is None or self.mission is None:
            return None
        reference = self._lock_on_grounded_reference(semantic_goal, result)
        if reference is None:
            return None
        label = reference.label or reference.landmark_id
        world_xy = (float(result.x), float(result.y))
        suppression = memory.consult(label, world_xy, view_index=self._lock_on_view_index)
        if suppression.suppressed:
            self.lock_on_suppressions += 1
            self.mission.metadata["lock_on_suppression"] = suppression.reason
            self.mission.metadata["lock_on_suppression_strength"] = suppression.strength
            return self._lock_on_refuse(
                reason=f"fp_memory_suppressed:{suppression.reason}",
                reference=reference,
                world_xy=world_xy,
                record_refutation=False,
            )
        session = self._detection_lock_on
        estimate = None if session is None else session.localizer.estimate
        if estimate is None or refinement_gate is None:
            return None
        verdict = refinement_gate(
            reference, estimate.position, covariance=estimate.covariance
        )
        self.mission.metadata["lock_on_refinement"] = verdict.reason
        self.mission.metadata["lock_on_refinement_displacement_m"] = verdict.displacement_m
        if verdict.accepted:
            return None
        return self._lock_on_refuse(
            reason=verdict.reason,
            reference=reference,
            world_xy=(float(estimate.position[0]), float(estimate.position[1])),
            # AF-2 (should-fix 2): the refusal is about THIS grounded candidate,
            # so the memory has to hold it at the candidate's cell too — this is
            # the cell the guard consults on the very next sighting, and the
            # refinement-gate class of refusal is precisely the one where the
            # estimate is metres away from it.
            reference_xy=world_xy,
            record_refutation=True,
        )

    def _begin_lock_on_verify(
        self,
        semantic_goal: Any,
        result: SemanticCandidate,
    ) -> None:
        """Open the verify-on-approach session for a freshly committed reference."""

        self._end_lock_on_verify()
        if not self.lock_on_verify_on_approach or LockOnVerifySession is None:
            return
        reference = self._lock_on_grounded_reference(semantic_goal, result)
        if reference is None or self.mission is None:
            return
        self._lock_on_verify = LockOnVerifySession(reference)
        self.lock_on_sessions += 1
        self._lock_on_verify_session_id = f"{reference.landmark_id}#{self.lock_on_sessions}"
        self.mission.metadata["lock_on_verify_session"] = self._lock_on_verify_session_id
        self.mission.metadata["lock_on_verify_checkpoints_m"] = list(
            self._lock_on_verify.checkpoints_m
        )

    def _end_lock_on_verify(self) -> None:
        self._lock_on_verify = None
        self._lock_on_verify_session_id = ""

    def _verify_lock_on_on_approach(
        self,
        observation: NavObservation,
    ) -> MidLevelCommand | None:
        """One re-verification tick on a COMMITTED reference (record §2.2(b)).

        The session is the machine (VS-1): checkpoints derive from the near-object
        envelope, each demands fresh evidence (persistence, covariance shrink,
        SigLIP identity re-check), and ``VERIFIED`` is not terminal — every later
        view still runs the refinement gate. A refutation is a VETO: flush the
        proposal through the P0-C revision seam, write negative evidence, resume
        search. Nothing here can admit an arrival.

        Between roughly 8 m and 12 m a target is visible but the grid planner's
        local costmap cannot yet route to it (W2_EVAL_STATUS.md §3). No
        checkpoint is due at those ranges — they are the near-object envelope,
        metres not tens of metres — so the proposal simply stays PENDING and
        keeps being re-verified while the planner closes range. Nothing is
        weakened to achieve that: the window is quiet because no evidence is due.
        """

        session = self._lock_on_verify
        if (
            session is None
            or self.mission is None
            or self.mission.semantic_goal is None
            or self.mission.goal is None
        ):
            return None
        fused = self._lock_on_fuse(self.mission.semantic_goal, observation)
        if fused is None:
            return None
        _estimate, view = fused
        verdict = session.observe(view)
        self.lock_on_verify_ticks += 1
        self.lock_on_verify_states.append(
            (self._lock_on_verify_session_id, verdict.state.value)
        )
        self.mission.metadata["lock_on_verify_state"] = verdict.state.value
        self.mission.metadata["lock_on_verify_reason"] = verdict.reason
        self.mission.metadata["lock_on_verify_states"] = list(self.lock_on_verify_states)
        self.mission.metadata["lock_on_cleared_checkpoints_m"] = list(
            verdict.cleared_checkpoints
        )
        if not verdict.veto:
            return None
        negative = session.negative_evidence()
        world_xy = (
            (float(negative.world_xy[0]), float(negative.world_xy[1]))
            if negative is not None
            else (float(view.fused_xy[0]), float(view.fused_xy[1]))
        )
        return self._lock_on_refuse(
            reason=verdict.reason,
            reference=session.reference,
            world_xy=world_xy,
            reference_xy=self._lock_on_reference_xy(session.reference),
            record_refutation=True,
        )

    def _lock_on_reference_xy(self, reference: Any) -> tuple[float, float] | None:
        """The GROUNDED candidate's own cell — the one the guard consults.

        AF-2 (``scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md``, should-fix 2).
        Objects publish a centre; a region's representative point is its
        polygon centroid, the same point the semantic map hands the grounder as
        a region candidate's ``(x, y)``.
        """

        center = getattr(reference, "center", None)
        if isinstance(center, (list, tuple)) and len(center) >= 2:
            try:
                point = (float(center[0]), float(center[1]))
            except (TypeError, ValueError):
                return None
            return point if all(math.isfinite(v) for v in point) else None
        polygon = tuple(getattr(reference, "polygon", None) or ())
        if not polygon:
            return None
        try:
            point = (
                sum(float(vertex[0]) for vertex in polygon) / len(polygon),
                sum(float(vertex[1]) for vertex in polygon) / len(polygon),
            )
        except (TypeError, ValueError, IndexError):
            return None
        return point if all(math.isfinite(v) for v in point) else None

    def _lock_on_refuse(
        self,
        *,
        reason: str,
        reference: Any,
        world_xy: tuple[float, float],
        record_refutation: bool,
        reference_xy: tuple[float, float] | None = None,
    ) -> MidLevelCommand:
        """Withdraw the lock-on proposal and resume the search, honestly.

        The instance is NOT added to ``_unreachable_candidates``: a refutation is
        evidence about a hypothesis at a PLACE, and VS-2's memory is the thing
        that carries it (class + world cell, TTL/decay). Excluding the id would
        make the re-encounter unobservable, which is precisely the suppression
        the design wants to happen on the next sighting.

        **AF-2 amendment** (``AUDIT_WAVE2_FABLE.md``, should-fix 2): the
        refutation is written at BOTH the estimate's cell and the grounded
        candidate's cell. The dominant refutation class on the live arm is the
        refinement gate — "the fused point is metres away from the reference it
        claims to be" — and it USED to record only at the estimate's cell while
        :meth:`_lock_on_admission_guard` consults at the CANDIDATE's, so a wrong
        reference more than a cell away from its estimate was re-committed and
        re-refuted until the replan ladder was spent (measured live: 24
        refutations, 1 suppression). VS-2's contract is untouched — the two
        writes are two ordinary ``record_refutation`` calls, and the second is
        skipped when both points fall in the SAME cell so a single refutation
        can never reinforce (and so double the TTL horizon of) one entry.
        """

        assert self.mission is not None
        if record_refutation and self._lock_on_fp_memory is not None:
            memory = self._lock_on_fp_memory
            label = reference.label or reference.landmark_id
            cells = [(float(world_xy[0]), float(world_xy[1]))]
            if reference_xy is not None:
                candidate_cell = (float(reference_xy[0]), float(reference_xy[1]))
                if memory.key(label, candidate_cell) != memory.key(label, cells[0]):
                    cells.append(candidate_cell)
            for cell in cells:
                memory.record_refutation(
                    label,
                    cell,
                    view_index=self._lock_on_view_index,
                    reason=reason,
                )
            self.lock_on_refutations += 1
            self.lock_on_refutation_cells += len(cells)
        self._flush_lock_on_proposal()
        self._end_lock_on_verify()
        if self._detection_lock_on is not None:
            # Drop the contradicted hypothesis so the next sighting starts from
            # a fresh measurement rather than re-deriving the refuted estimate.
            self._detection_lock_on.reset()
        self._lock_on_last_admitted = None
        self._lock_on_hypothesis_committed = False
        self._lock_on_instance_id = ""
        self.mission.metadata["lock_on_refusal"] = reason
        self.mission.metadata["lock_on_refutations"] = self.lock_on_refutations
        self.mission.metadata["lock_on_suppressions"] = self.lock_on_suppressions
        replans = int(self.mission.metadata.get("replan_count", 0))
        if replans < self.max_semantic_replans:
            resumed = self._begin_semantic_replan(
                replans, note="semantic_replan_after_lock_on_refutation"
            )
            # The refusal tick is an early return, so it never reaches the note
            # stamp in ``step``; stamp it here or the REJECTED verdict — the one
            # state the gate must see — never reaches a trace. Non-terminal
            # command, so the runner's ``reason`` field is untouched.
            return MidLevelCommand(
                vx=resumed.vx,
                vy=resumed.vy,
                vyaw=resumed.vyaw,
                stop=resumed.stop,
                note=self._lock_on_telemetry_note(resumed.note or ""),
            )
        # The ladder is spent: every hypothesis this mission could form was
        # refuted. Fail through the existing not-found exit — the honest
        # classification is "I did not find it", not "I arrived".
        reply = (
            honest_not_found_reply(
                _refusal_label(self.mission.semantic_goal),
                scanned=self._already_scanned,
                searched=self._already_searched,
            )
            if honest_not_found_reply is not None
            else "target not confirmed"
        )
        self.mission.status = "failed"
        self.mission.metadata.update(
            {
                "resolution_state": "not_found",
                "recovery_phase": "failed",
                "reply": reply,
                "lock_on_outcome": "refuted",
            }
        )
        return self._target_missing_command()

    def _flush_lock_on_proposal(self) -> None:
        """Withdraw the refuted lock-on proposal from the buffers, revision-NEUTRALLY.

        **Amended by card AF-2 (2026-08-11); provenance
        ``scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md``, BLOCKING finding.**
        This used to self-commit ``plan_revision + 1`` on the ProposerBus and the
        GoalArbiter. Revision authority belongs to the EXECUTIVE (the P0-C
        discipline): the ledger never lowers, the runtime restamps this navigator
        with the executive's (lower) revision on every nav start/resume and plan
        accept, and from that moment every goal this pipeline published was
        "stale", ``GoalArbiter.resolve`` returned ``None`` and the mission died
        ``arbiter_veto`` with no way to heal.

        A refusal is a statement about ONE proposal, not about the plan, so it
        purges the buffer and leaves the ledger alone:
        :meth:`ProposerBus.flush_task` drops this task's buffered goals without
        touching :class:`~parcel_robot.revision.CommittedRevisions`, and the
        arbiter's paired ``flush_task`` keeps the two sinks uniform. The real
        stale-drop semantics — an owner correction bumping ``plan_revision`` —
        are untouched, and the very next proposal this navigator publishes under
        the SAME revision buffers and resolves normally.
        """

        if self.proposer_bus is None or self.goal_arbiter is None:
            return
        flush_bus = getattr(self.proposer_bus, "flush_task", None)
        flush_arbiter = getattr(self.goal_arbiter, "flush_task", None)
        if not callable(flush_bus) or not callable(flush_arbiter):
            # Historical bundles predate the AF-2 amendment. Withdrawing nothing
            # is safe (the refusal path already releases the mission goal and
            # resumes the search); bumping the revision was not.
            return
        flush_bus(self._active_task_id)
        flush_arbiter(self._active_task_id)
        self.lock_on_flushes += 1
        # RM-2: a refusal withdraws the lock-on proposal AND any waypoint chain
        # derived while that refuted commitment was live. The buffers are already
        # purged above; this drops the interim target in the same transaction.
        # Counted only when something was actually pending, so ``flushes`` stays
        # a record of withdrawals rather than of call sites.
        if self._route_memory is not None and self._route_memory_chain:
            self._clear_route_memory_chain()
            self.route_memory_flushes += 1
            if self.mission is not None:
                self.mission.metadata["route_memory_flush"] = "lock_on_refusal"

    def _lock_on_telemetry_note(self, note: str) -> str:
        """Append the card's non-vacuity counters to a note, for the trace.

        ``MidLevelCommand.note`` is the only navigator-side channel the frozen
        eval runner persists per step, and adjudication #19's conjuncts have to
        be assertable FROM TRACES. Appended after a ``|`` delimiter and only on
        non-terminal commands, so no substring the runner keys on
        (``semantic_search_scan`` prefix, ``semantic_target_not_found``,
        ``frontier``) is introduced or displaced.
        """

        if not self.lock_on_verify_on_approach:
            return note
        # The LAST VERDICT, not the live session: a refutation ends the session,
        # and "the session is gone" is exactly the state the gate must be able
        # to see. ``sessions`` is the ordinal that groups verdicts by session.
        state = (
            self.lock_on_verify_states[-1][1] if self.lock_on_verify_states else ""
        )
        return (
            f"{note}|lock_on_verify={state}"
            f",sessions={self.lock_on_sessions}"
            f",views={self.lock_on_verify_ticks}"
            f",commits={self.lock_on_commits}"
            f",refutations={self.lock_on_refutations}"
            f",suppressions={self.lock_on_suppressions}"
        )

    def _commit_semantic_candidate(
        self,
        semantic_goal: Any,
        result: SemanticCandidate,
        observation: NavObservation,
        *,
        grounding_outcome: str,
    ) -> MidLevelCommand:
        assert self.mission is not None
        self._clear_terminal_pose_diagnostics()
        if self.lock_on_verify_on_approach:
            refused = self._lock_on_admission_guard(semantic_goal, result, observation)
            if refused is not None:
                return refused
        pose, approach_costs = self._solve_semantic_approach_pose(
            semantic_goal,
            result,
            observation,
        )
        if pose is None:
            # "No admissible approach pose for THIS instance" is a fact about
            # one instance, not about the directive. Failing the mission on it
            # outright was the sibling of the unroutable-goal defect
            # (REGION_INSTANCE_STATUS.md follow-up, non-claim 3): the mission
            # threw away a directive it might still be able to satisfy at
            # another instance. Same release, same per-mission memory, same
            # exclusion from the rescan, same replan budget — the only
            # difference is which authority produced the proof (the approach
            # solver here, A* there). The K0-band fallback above has already run
            # and also found no collision-clear pose, so this instance is
            # genuinely boxed in and the honest release stands.
            self.mission.metadata["grounding_outcome"] = grounding_outcome
            self.mission.metadata["unreachable_pose_candidate"] = str(result.candidate_id)
            # Card R10: the give-up NAMES the candidates it tried. Without this
            # the live failure was a bare ``semantic_target_unreachable`` with
            # nothing to read — an owner heard "I couldn't get there" and an
            # engineer got one enum. The rows come from the resampler's own
            # bookkeeping, so they cannot drift from what it actually did.
            attempts = approach_costs.get("inside_resample_attempts")
            if attempts:
                self.mission.metadata["inside_resample_attempts"] = attempts
            return self._release_unreachable_candidate(
                str(result.candidate_id),
                note="semantic_replan_after_unreachable_pose",
            )
        self.mission.goal = pose
        self.mission.status = "running"
        self.mission.metadata.update(
            {
                "resolution_state": "resolved",
                "grounding_outcome": grounding_outcome,
                "recovery_phase": self._recovery_phase,
                "candidate_id": result.candidate_id,
                "candidate_label": result.label,
                # Card A2 fix 1: what the map SAW, kept beside what the owner
                # asked for, so the re-sight can ask for the committed thing.
                "candidate_kind": result.kind,
                "candidate_confidence": result.confidence,
                "candidate_source": result.source,
                "target_polygon": result.polygon,
                "terminal_relation": semantic_goal.terminal_relation,
                "terminal_behavior": semantic_goal.terminal_behavior,
                # Card R10 — the arrival table's local half, recorded on the
                # mission so the terminal narration reads the SAME row the
                # planner used instead of re-deriving it from the goal string.
                "place_class": getattr(semantic_goal, "place_class", "object"),
                "arrival_face": getattr(semantic_goal, "face", "goal"),
                "arrival_do_not_cross": bool(getattr(semantic_goal, "do_not_cross", False)),
                "arrival_ask_hint": getattr(semantic_goal, "ask_hint", ""),
                "arrival_relation_source": getattr(semantic_goal, "relation_source", "table"),
                "candidate_position": (result.x, result.y, result.z),
                "candidate_radius_m": _metadata_float(
                    result.metadata, "radius_m", default=0.0, minimum=0.0, maximum=5.0
                ),
                "associated_lidar_ids": sorted(_candidate_obstacle_ids(result)),
                "terminal_clearance_m": _metadata_float(
                    result.metadata,
                    "terminal_clearance_m",
                    default=0.32,
                    minimum=0.10,
                    maximum=1.0,
                ),
                **approach_costs,
                "vicinity_radius_m": _metadata_float(
                    result.metadata,
                    "vicinity_radius_m",
                    default=math.hypot(pose.x - result.x, pose.y - result.y)
                    + (pose.arrival_radius_m or 0.12),
                    minimum=0.5,
                    maximum=4.0,
                ),
                "minimum_vicinity_radius_m": _metadata_float(
                    result.metadata,
                    "minimum_vicinity_radius_m",
                    default=_metadata_float(
                        result.metadata,
                        "radius_m",
                        default=0.0,
                        minimum=0.0,
                        maximum=2.0,
                    )
                    + ROBOT_FOOTPRINT_RADIUS_M
                    + max(
                        self.collision.obstacle_stop_m,
                        _metadata_float(
                            result.metadata,
                            "target_min_surface_clearance_m",
                            default=self.collision.obstacle_stop_m,
                            minimum=0.1,
                            maximum=2.0,
                        ),
                    ),
                    minimum=0.4,
                    maximum=4.0,
                ),
                "terminal_support_clearance_m": _metadata_float(
                    result.metadata,
                    "terminal_support_clearance_m",
                    default=0.32,
                    minimum=0.1,
                    maximum=1.0,
                ),
                "support_polygon": result.metadata.get("support_polygon") or (),
                "arrival_goal_region": self._build_arrival_goal_region(
                    semantic_goal.terminal_relation,
                    result,
                ),
                # Stratum-1 landmark-relative goal storage (GraphNav anchoring).
                # The world-frame goal above stays the primary and only fallback;
                # these three fields let a LATER sighting of the SAME landmark
                # re-derive it, so a drifting frame moves the robot's estimate of
                # where it is without moving where the goal actually is.
                # ``goal_landmark_id`` is never rewritten -- re-anchoring can
                # only ever refine an instance, never switch to another one.
                "goal_landmark_id": str(result.candidate_id),
                "goal_landmark_position": (float(result.x), float(result.y)),
                "goal_landmark_offset": (
                    float(pose.x) - float(result.x),
                    float(pose.y) - float(result.y),
                    float(pose.heading_deg),
                ),
                "plan": (
                    "confirm_target_from_camera_depth",
                    "choose_collision_free_terminal_pose",
                    "align_then_translate",
                    f"verify_{semantic_goal.terminal_relation}_and_stopped",
                ),
                "plan_step": "align_then_translate",
            }
        )
        if not self._approach_goal_admitted(pose, result.confidence, observation):
            self.mission.status = "failed"
            self.mission.metadata["resolution_state"] = "arbiter_veto"
            return MidLevelCommand(stop=True, note="semantic_goal_vetoed")
        self._navigator.reset(self.mission)
        # MAP: ``pose`` is a world-frame approach pose, so the seed distance is
        # a MAP-frame measurement.
        robot_map = _pose_in(observation, MAP_FRAME)
        self._best_goal_distance_m = math.hypot(
            pose.x - robot_map.x,
            pose.y - robot_map.y,
        )
        self._steps_without_progress = 0
        self._steps_goal_unroutable = 0
        self._steps_gate_blocked = 0
        self._gate_blocked_anchor_xy = None
        self._terminal_verification_steps = 0
        # Bind the freshly committed target to a confirmed track now, so the
        # very next tick's geometric association has an anchor.
        self._bind_target_track()
        # VS-4: the committed REFERENCE (this grounded instance and its
        # geometry, which is what ``arrival_goal_region`` above was built from)
        # now gets a re-verification schedule as range closes.
        if self.lock_on_verify_on_approach:
            self._begin_lock_on_verify(semantic_goal, result)
        return MidLevelCommand(
            vx=0.0,
            vy=0.0,
            vyaw=0.0,
            note=self._lock_on_telemetry_note("semantic_target_resolved"),
        )

    def _solve_semantic_approach_pose(
        self,
        semantic_goal: Any,
        result: SemanticCandidate,
        observation: NavObservation,
    ) -> tuple[GoalPose | None, dict[str, Any]]:
        """Resolve one currently observed, gate-clear terminal pose.

        Keeping this solver in one method matters after a commitment: an
        obstacle can become visible only on final approach.  The retry path
        must use the identical support, K0-band and etiquette authorities as
        the first commitment rather than growing a second placement policy.
        """

        assert self.mission is not None
        approach_costs: dict[str, Any] = {}
        pose = safe_approach_pose(
            semantic_goal,
            result,
            observation,
            footprint_clearance_m=ROBOT_FOOTPRINT_RADIUS_M,
            obstacle_stop_m=self.collision.obstacle_stop_m,
            tracks=_dynamic_tracks_from_observation(observation),
            cost_out=approach_costs,
        )
        if pose is not None:
            self.mission.metadata["approach_pose_source"] = "support_gated"
        else:
            # Before conceding this instance, try a collision-clear pose in the
            # same K0 near/next-to band.  This never widens the verified band or
            # relaxes the obstacle ring.
            pose = self._fallback_near_arrival_pose(
                semantic_goal,
                result,
                observation,
            )
        if pose is not None:
            pose = self._apply_arrival_etiquette(
                semantic_goal,
                result,
                observation,
                pose,
            )
        return pose, approach_costs

    def _approach_goal_admitted(
        self,
        pose: GoalPose,
        confidence: float,
        observation: NavObservation,
    ) -> bool:
        """Submit a local terminal-pose proposal through the existing arbiter."""

        if not (
            _HAS_INSTRUCTNAV
            and SE2Goal is not None
            and self.proposer_bus is not None
            and self.goal_arbiter is not None
        ):
            return True
        now_s = float(observation.extras.get("time_s") or 0.0)
        proposed = SE2Goal(
            source="grounder",
            pose=(pose.x, pose.y, math.radians(pose.heading_deg)),
            confidence=float(confidence),
            ttl_s=2.0,
            plan_step_id="align_then_translate",
            issued_s=now_s,
            priority=10,
            task_id=self._active_task_id,
            plan_revision=self._active_plan_revision,
        )
        self.proposer_bus.publish(proposed)
        self.goal_arbiter.set_plan_step("align_then_translate")
        return self.goal_arbiter.resolve((proposed,), now_s=now_s) is not None

    def _clear_terminal_pose_diagnostics(self) -> None:
        """Drop authority/phase facts left by an earlier commitment attempt."""

        assert self.mission is not None
        for key in (
            "approach_pose_source",
            "approach_preference_source",
            "approach_refused_reason",
            "support_pose_refused_reason",
            "arrival_face_applied",
            "terminal_relation_verified",
            "owner_face_phase",
            "owner_face_anchor_xy",
            "owner_face_target_heading_deg",
            "owner_face_turn_steps",
            "owner_face_turn_budget_steps",
            "owner_face_yaw_clamped",
            "owner_face_proposed_vyaw",
            "owner_face_max_vyaw",
            "owner_face_phase_a_verified",
            "owner_face_phase_a_goal",
            "owner_face_phase_a_invalidated_reason",
            "owner_face_failure_reason",
            "owner_face_final_pose",
            "owner_face_final_owner_xy",
        ):
            self.mission.metadata.pop(key, None)

    def _apply_arrival_etiquette(
        self,
        semantic_goal: Any,
        result: SemanticCandidate,
        observation: NavObservation,
        pose: GoalPose,
    ) -> GoalPose | None:
        """Local terminal etiquette from the arrival table — card R10 item 4.

        Two rules, both LOCAL, neither reachable from a hosted argument:

        * ``do_not_cross`` (portals): a terminal pose inside the target's own
          polygon means the robot planned to stand IN the doorway. That is
          refused here, which sends the instance down the SAME unreachable
          release every other proved-impossible pose takes rather than growing a
          second failure path. Stopping in a threshold is the social-competency
          violation the Francis et al. principles name, and it is also how a
          companion ends up blocking the one route the owner needs.
        * ``face == owner``: retain the target-facing approach heading through
          live semantic/K0 verification, then apply the social final heading as
          a separately verified zero-translation turn. This prevents etiquette
          from making its own target re-sight impossible.
        """

        face = str(getattr(semantic_goal, "face", "") or "")
        do_not_cross = bool(getattr(semantic_goal, "do_not_cross", False))
        if do_not_cross and result.polygon and point_in_polygon((pose.x, pose.y), result.polygon):
            if self.mission is not None:
                self.mission.metadata["arrival_refused_reason"] = "portal_terminal_inside_threshold"
            return None
        if face != ARRIVAL_FACE_OWNER:
            return pose
        if self.mission is not None:
            self.mission.metadata["arrival_face_applied"] = "deferred"
            self.mission.metadata["owner_face_phase"] = "approach_target"
        return pose

    @staticmethod
    def _owner_xy(observation: NavObservation) -> tuple[float, float] | None:
        """The owner's map position from the navigator's own owner channel.

        ``extras["owner_track"]`` is the runtime's W4 payload: a tuple that is
        EMPTY when the owner is not visible, so "no rows" already means "not
        tracked" and there is no second visibility flag to disagree with.
        """

        rows = observation.extras.get("owner_track") or ()
        if not isinstance(rows, (list, tuple)) or not rows:
            return None
        row = rows[0]
        if not isinstance(row, dict):
            return None
        try:
            x = float(row["x"])
            y = float(row["y"])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        return (x, y)

    def _fallback_near_arrival_pose(
        self,
        semantic_goal: Any,
        result: SemanticCandidate,
        observation: NavObservation,
    ) -> GoalPose | None:
        """Approach pose inside the K0 ``near`` vicinity band when the
        support-gated :func:`safe_approach_pose` solver finds none.

        This search-reground fallback never widens a band or weakens a gate: an
        admitted point remains inside the candidate's K0 vicinity band and keeps
        full footprint-to-surface clearance from every non-target obstacle.
        ``near`` and ``next_to`` share that verified band; ``towards`` uses its
        own stop-short waypoint. With no admissible collision-clear point this
        returns ``None`` and leaves the existing unreachable-release to fail honestly.
        """

        if near_band_fallback_point is None or GoalPose is None or self.mission is None:
            return None
        if getattr(semantic_goal, "terminal_relation", "") not in {"near", "next_to"}:
            return None
        if not bool(getattr(result, "reachable", True)):
            return None
        band = _near_fallback_band(
            result.metadata,
            obstacle_stop_m=self.collision.obstacle_stop_m,
        )
        if band is None:
            return None
        inner, outer = band
        robot_map = _pose_in(observation, MAP_FRAME)
        blocked = self._non_target_obstacle_points(observation, result)
        # The same footprint-to-surface clearance the reactive gate enforces, so
        # a pose this admits is one the gate will also let the body reach.
        clearance = ROBOT_FOOTPRINT_RADIUS_M + self.collision.obstacle_stop_m
        point = near_band_fallback_point(
            center=(float(result.x), float(result.y)),
            band_m=(inner, outer),
            robot_xy=robot_map.xy,
            blocked_points=blocked,
            clearance_m=clearance,
        )
        if point is None:
            return None
        x, y = point
        heading = math.degrees(math.atan2(result.y - y, result.x - x))
        arrival_radius = _metadata_float(
            result.metadata, "arrival_radius_m", default=0.12, minimum=0.05, maximum=0.5
        )
        self.mission.metadata["approach_pose_source"] = "near_band_fallback"
        return GoalPose(
            x=float(x),
            y=float(y),
            z=float(result.z),
            heading_deg=float(heading),
            poi_id=str(result.candidate_id),
            label=str(result.label),
            arrival_radius_m=arrival_radius,
        )

    def _non_target_obstacle_points(
        self,
        observation: NavObservation,
        result: SemanticCandidate,
    ) -> tuple[tuple[str | None, float, float], ...]:
        """Observed obstacle SURFACE points with the target's own body removed.

        Mirrors the collision-authority projection the approach solver uses (the
        LiDAR footprint-to-surface contract plus the nominal body radius), then
        drops any surface within the target's own footprint (radius + the
        stratum-2 association slack) so the object never blocks its own vicinity
        band. Every other observed surface stays a solid — no gate is relaxed.
        """

        raw = observation.extras.get("lidar_obstacles")
        if not isinstance(raw, (list, tuple)):
            return ()
        robot = _pose_in(observation, MAP_FRAME)
        radius = _metadata_float(
            result.metadata, "radius_m", default=0.0, minimum=0.0, maximum=5.0
        )
        exclude_r = radius + self.TARGET_ASSOCIATION_SLACK_M
        cx, cy = float(result.x), float(result.y)
        points: list[tuple[str | None, float, float]] = []
        for item in raw[:64]:
            if not isinstance(item, dict):
                continue
            try:
                distance = float(item["distance_m"])
                bearing = float(item["bearing_rad"])
            except (KeyError, TypeError, ValueError):
                continue
            if not math.isfinite(distance) or not math.isfinite(bearing) or distance < 0.0:
                continue
            ray = distance + ROBOT_FOOTPRINT_RADIUS_M
            angle = robot.yaw + bearing
            px = robot.x + ray * math.cos(angle)
            py = robot.y + ray * math.sin(angle)
            if math.hypot(px - cx, py - cy) <= exclude_r:
                continue
            points.append((str(item["id"]) if item.get("id") else None, px, py))
        return tuple(points)

    def _pose_lost_hold(self, observation: NavObservation) -> MidLevelCommand | None:
        """Stop and hold while MAP localization is ``LOST``.

        Driving on a pose you know is wrong is the failure mode GraphNav names
        explicitly. ``LOST`` therefore stops the body; it does **not** fail the
        mission, because the goal is still valid and health can return.
        ``DEGRADED`` deliberately does *not* stop -- it only blocks the arrival
        claim in :meth:`_semantic_arrival_verified`, which is the smallest
        honest response to "I am less sure than usual".

        ``TruthPoseProvider`` can never reach this branch: it is ``HEALTHY`` by
        construction. Today only a config-injected drift provider can.
        """

        mission = self.mission
        if mission is None or not _HAS_POSE:
            return None
        pose = _pose_in(observation, MAP_FRAME)
        health = getattr(getattr(pose, "health", None), "value", "healthy")
        if health != "lost":
            if mission.metadata.get("pose_health") == "lost":
                mission.metadata["pose_health"] = health
            return None
        mission.metadata["pose_health"] = "lost"
        mission.metadata["resolution_state"] = "pose_lost"
        mission.metadata["plan_step"] = "hold_localization_lost"
        return MidLevelCommand(stop=True, note="pose_lost_hold")

    #: A re-anchor below this displacement is a no-op. It exists so that an
    #: unchanged landmark cannot perturb the goal by a float round-trip: the
    #: whole point is that nothing moves when nothing moved.
    LANDMARK_REANCHOR_EPSILON_M = 1e-9

    def _reanchor_landmark_goal(self, observation: NavObservation) -> bool:
        """Re-derive the world goal from a fresh sighting of the SAME landmark.

        GraphNav's fielded lesson: a goal stored only in world coordinates is
        wrong the moment the frame it was stored in drifts. A goal stored as
        ``landmark_id + offset`` survives, because re-observing the landmark
        re-establishes the anchor.

        Hard constraints, both tested:

        * **Re-anchor only, never switch.** Only a candidate carrying the
          *identical* ``candidate_id`` is accepted. Seeing a second bench does
          not move a goal committed to the first one.
        * **World-frame stays the fallback.** POIs and any goal committed
          without a landmark id (no ``goal_landmark_id`` in metadata) are
          untouched by this path and keep the behavior they always had.
        """

        mission = self.mission
        if mission is None or mission.goal is None:
            return False
        landmark_id = mission.metadata.get("goal_landmark_id")
        offset = mission.metadata.get("goal_landmark_offset")
        anchor = mission.metadata.get("goal_landmark_position")
        if not isinstance(landmark_id, str) or offset is None or anchor is None:
            return False
        raw = observation.extras.get("semantic_candidates")
        if not isinstance(raw, (list, tuple)):
            return False
        fresh: tuple[float, float] | None = None
        for item in raw[:64]:
            if not isinstance(item, dict) or item.get("id") != landmark_id:
                continue
            position = item.get("position") or item.get("centroid")
            if isinstance(position, (list, tuple)) and len(position) >= 2:
                try:
                    fresh = (float(position[0]), float(position[1]))
                except (TypeError, ValueError):
                    return False
            break
        if fresh is None or not all(math.isfinite(value) for value in fresh):
            return False
        dx = fresh[0] - float(anchor[0])
        dy = fresh[1] - float(anchor[1])
        if math.hypot(dx, dy) <= self.LANDMARK_REANCHOR_EPSILON_M:
            return False
        mission.goal = replace(
            mission.goal,
            x=fresh[0] + float(offset[0]),
            y=fresh[1] + float(offset[1]),
        )
        mission.metadata["goal_landmark_position"] = fresh
        mission.metadata["candidate_position"] = (
            fresh[0],
            fresh[1],
            (mission.metadata.get("candidate_position") or (0.0, 0.0, 0.0))[2],
        )
        mission.metadata["landmark_reanchor_count"] = (
            int(mission.metadata.get("landmark_reanchor_count", 0)) + 1
        )
        mission.metadata["landmark_reanchor_delta_m"] = math.hypot(dx, dy)
        # The arrival authority is anchored to the same landmark, so it has to
        # travel with it -- otherwise K0 would verify against a stale polygon.
        region = mission.metadata.get("arrival_goal_region")
        if isinstance(region, dict):
            mission.metadata["arrival_goal_region"] = _translated_goal_region(region, dx, dy)
        # AF-2 (AUDIT_WAVE2_FABLE.md, should-fix 3): the verify session's
        # GROUNDED REFERENCE is anchored to the same landmark and is part of the
        # same transaction. Left behind under real frame drift, the object gate
        # would measure a perfectly healthy estimate against a pre-drift centre,
        # refute a good commitment, and write negative evidence AT THE TRUE
        # TARGET -- self-suppressing it for the whole TTL horizon. Static sim
        # never drifts, so this is invisible there and hardware-relevant; the
        # branch is flag-gated (the session is None flag-off) and retract-only,
        # so it can only ever remove a refusal.
        session = self._lock_on_verify
        if session is not None:
            reanchor = getattr(session, "reanchor", None)
            if callable(reanchor):
                reanchor(dx, dy)
                self.lock_on_reanchors += 1
        # The progress watchdog measures distance to the goal; a re-anchor moves
        # the goal, so its baseline is stale and must not read as a stall.
        self._best_goal_distance_m = None
        self._steps_without_progress = 0
        return True

    def _step_semantic_resolution(self, observation: NavObservation) -> MidLevelCommand:
        """Frustum → memory → ScanBehavior → SearchEntity → honest refusal.

        When ``instructnav_recovery`` is False (``--mode baseline``), only the
        current frustum is considered — no memory, scan, or frontier.
        """

        assert self.mission is not None
        semantic_goal = self.mission.semantic_goal
        if semantic_goal is None:
            self.mission.status = "failed"
            return MidLevelCommand(stop=True, note="semantic_goal_missing")

        if self.instructnav_recovery:
            self._ingest_memory(observation)
        frustum = self._resolution_semantic_map.query(semantic_goal, observation)
        memory_hits = (
            self._memory_candidates(semantic_goal, observation)
            if self.instructnav_recovery
            else []
        )
        # Stratum-2: anything already checked and refuted at this place is not
        # a candidate again. This is the only thing standing between a
        # false-positive detection and an unbounded ground → walk → reject →
        # ground-the-same-phantom loop.
        frustum = self._drop_remembered_false_positives(frustum)
        memory_hits = self._drop_remembered_false_positives(memory_hits)
        # MAP: candidates are world-frame semantics, so grounding geometry is a
        # MAP-frame question.
        robot_map = _pose_in(observation, MAP_FRAME)
        robot_x, robot_y = robot_map.xy
        # U34 (D-4): this was ``_legacy_yaw(observation)``, i.e.
        # ``position[2]`` -- the robot's STANDING HEIGHT (0.27 m on a Go2) read
        # as a yaw in radians, a phantom 15.5 deg heading error on every
        # grounding call. Yaw comes from the pose provider, in the same frame
        # as the xy directly above it.
        robot_yaw = robot_map.yaw
        # Attributes narrow the candidate set BEFORE the superlative picks from
        # it: "the closest big tree" is "among the big trees, the closest".
        attributes = tuple(getattr(semantic_goal, "attributes", ()) or ())
        if attributes and _HAS_ATTRIBUTES:
            frustum_filter = filter_candidates_by_attributes(list(frustum), attributes)
            # Memory rows carry no size today, so a remembered instance cannot
            # claim "big" — it is dropped and reported, never assumed to match.
            memory_filter = filter_candidates_by_attributes(memory_hits, attributes)
            detail = merge_attribute_results(frustum_filter, memory_filter).detail
            self.mission.metadata["attribute_query"] = " ".join(
                (*attributes, str(semantic_goal.query))
            )
            if detail:
                self.mission.metadata["attribute_filter"] = detail
            # Emptying the set is the honest outcome, not a reason to drop the
            # attribute: the ladder below reports UNSEEN naming the attribute.
            frustum = list(frustum_filter.kept)
            memory_hits = list(memory_filter.kept)
        # Region goals are stuff classes: any same-label instance satisfies
        # the directive, so grounding tie-breaks to the nearest instead of
        # asking "which sidewalk?" on every two-sided street. An explicit
        # superlative ("the nearest lamppost") asks for exactly the same
        # tie-break by name: the owner already said which one they mean.
        interchangeable = (
            semantic_goal.kind == "region"
            or getattr(semantic_goal, "superlative", None) == "nearest"
        )
        # VS-5: paint THIS look into the belief map, at the ONE ingress — the
        # frustum list grounding itself is about to read, after the
        # false-positive and attribute filters. Until this card the map was
        # painted only from inside ``_step_scan_behavior``, and only on the
        # ticks that reached the bottom of it, so a sighting that resolved
        # immediately (the frustum branch below) and every frontier tick painted
        # NOTHING: the map ran empty, which is the mechanical half of the
        # measured V-D no-op (§2.1(2a)). One ingress, one paint per searching
        # tick, hit or miss. Flag-off this returns immediately.
        self._paint_scan_observation(semantic_goal, observation, frustum)
        if ground_query is not None and self.grounder_v2 is not None:
            grounded, mapped = ground_query(
                semantic_goal.query,
                frustum=list(frustum),
                memory_hits=memory_hits,
                robot_xy=(robot_x, robot_y),
                robot_yaw_rad=robot_yaw,
                grounder=self.grounder_v2,
                interchangeable=interchangeable,
            )
        else:
            # Soft-import fallback (historical BARN bundles without GrounderV2).
            from parcel_robot.instructnav.grounding import resolve_grounding as _resolve

            grounded = _resolve(
                frustum=[
                    {
                        "id": c.candidate_id,
                        "label": c.label,
                        "confidence": c.confidence,
                        "x": c.x,
                        "y": c.y,
                        "distance_m": _candidate_ground_distance_m(
                            c, robot_x, robot_y
                        ),
                        "candidate": c,
                    }
                    for c in frustum
                ],
                memory=[
                    {
                        "id": c.candidate_id,
                        "label": c.label,
                        "confidence": c.confidence,
                        "x": c.x,
                        "y": c.y,
                        "distance_m": _candidate_ground_distance_m(
                            c, robot_x, robot_y
                        ),
                        "candidate": c,
                    }
                    for c in memory_hits
                ],
                interchangeable=interchangeable,
            )
            mapped = None
            if grounded.candidate is not None:
                raw_c = grounded.candidate.get("candidate")
                mapped = raw_c if isinstance(raw_c, SemanticCandidate) else None

        self.mission.metadata["grounding_outcome"] = grounded.outcome.value

        if grounded.outcome == GroundingOutcome.AMBIGUOUS:
            self.mission.status = "failed"
            self.mission.metadata["resolution_state"] = "ambiguous"
            self.mission.metadata["recovery_phase"] = "clarify"
            if clarification_from_grounding is not None:
                act = clarification_from_grounding(
                    grounded, query=str(semantic_goal.query)
                )
                self.mission.metadata["reply"] = act.reply
                self.mission.metadata["clarification_kind"] = act.kind
                self.mission.metadata["clarification_labels"] = list(act.candidate_labels)
            else:
                self.mission.metadata["reply"] = (
                    f"I can see more than one {semantic_goal.query}; "
                    "please say which one you mean."
                )
            return MidLevelCommand(stop=True, note="semantic_target_ambiguous")

        if not self.instructnav_recovery:
            if grounded.outcome == GroundingOutcome.RESOLVED and mapped is not None:
                return self._commit_semantic_candidate(
                    semantic_goal,
                    mapped,
                    observation,
                    grounding_outcome=GroundingOutcome.RESOLVED.value,
                )
            reply = honest_not_found_reply(
                _refusal_label(semantic_goal), scanned=False, searched=False
            )
            self.mission.status = "failed"
            self.mission.metadata.update(
                {
                    "resolution_state": "unseen",
                    "grounding_outcome": GroundingOutcome.UNSEEN.value,
                    "recovery_phase": "baseline_frustum_only",
                    "reply": reply,
                }
            )
            return self._target_missing_command()

        action = (
            recovery_action_for(
                grounded.outcome,
                already_scanned=self._already_scanned,
                already_searched=self._already_searched,
            )
            if recovery_action_for is not None
            else None
        )

        if action == ScanRecoveryAction.NAVIGATE or (
            action is None
            and grounded.outcome
            in {GroundingOutcome.RESOLVED, GroundingOutcome.MEMORY_HIT}
        ):
            if (
                grounded.outcome == GroundingOutcome.MEMORY_HIT
                and mapped is not None
                and self._recovery_phase != "scan"
            ):
                self._recovery_phase = "memory"
                return self._commit_semantic_candidate(
                    semantic_goal,
                    mapped,
                    observation,
                    grounding_outcome=GroundingOutcome.MEMORY_HIT.value,
                )
            # RESOLVED (and scan-phase MEMORY_HIT): confirm with multi-view search.
            # D3 flag-on: detection-triggered lock-on (D1+SigLIP) replaces the
            # frustum required_observations commit; flag-off keeps the legacy path.
            self._recovery_phase = (
                "scan" if self._recovery_phase == "scan" else "frustum"
            )
            self.mission.status = "searching"
            self.mission.metadata["recovery_phase"] = self._recovery_phase
            self.mission.metadata["resolution_state"] = "searching"
            if (
                self.detection_lock_on
                and self._detection_lock_on is not None
                and not self.lock_on_verify_on_approach
            ):
                locked = self._try_detection_lock_on(
                    semantic_goal,
                    mapped,
                    observation,
                    robot_xy=(robot_x, robot_y),
                )
                self._scan_steps += 1
                if isinstance(locked, SemanticCandidate):
                    return self._commit_semantic_candidate(
                        semantic_goal,
                        locked,
                        observation,
                        grounding_outcome=GroundingOutcome.RESOLVED.value,
                    )
                if isinstance(locked, MidLevelCommand):
                    return locked
                # Still accumulating D1 evidence — steer toward the grounded target.
                result = MidLevelCommand(
                    vx=0.0,
                    vy=0.0,
                    vyaw=self.search.yaw_rate,
                    note="detection_lock_on_scan",
                )
            else:
                # VS-4 (§2.2(a)(i)): with verify-on-approach on, the lock-on
                # DEFERS — it fuses this view into D2 and runs its M-of-N under
                # the independent-evidence rule, but the instance is chosen by
                # the same authority the flag-off arm uses (the grounder's
                # ranking; for interchangeable queries the scan-complete
                # boundary-aware ranking). That is the direct fix for the
                # measured wrong-instance commit: there is no longer a second
                # commit door for perception to walk through.
                if self.lock_on_verify_on_approach:
                    self._lock_on_observe_estimate(semantic_goal, observation, mapped)
                result = self.search.observe(
                    semantic_goal, self._resolution_semantic_map, observation
                )
                self._scan_steps += 1
                if isinstance(result, SemanticCandidate):
                    return self._commit_semantic_candidate(
                        semantic_goal,
                        result,
                        observation,
                        grounding_outcome=GroundingOutcome.RESOLVED.value,
                    )
            if isinstance(result, MidLevelCommand) and not result.stop:
                # Steer the confirming rotation TOWARD the grounded target so it
                # stays in the frustum for the second sighting. The multi-view
                # gate (``required_observations``) rotated at a fixed +yaw_rate,
                # which pushes a target that flickered in on the frustum's
                # trailing edge straight back OUT before it can be confirmed —
                # the second search-reground defect (2026-08-09): a bench seen
                # for a single tick never reaches two sightings, so it is never
                # committed and the scan spins out its budget. Centering the
                # target (yaw toward its bearing, held still once centred) keeps
                # it visible without weakening the two-sighting anti-false-
                # positive gate. When the grounder gave no mapped instance we
                # keep the original sweep. Interchangeable (region / "nearest")
                # goals keep the look-around sweep untouched: their multi-view
                # is a deliberate revolution to rank instances, not a single
                # target to keep centred, and centring one would stop the sweep.
                vyaw = result.vyaw
                vx = 0.0
                if mapped is not None and not interchangeable:
                    bearing = math.atan2(mapped.y - robot_y, mapped.x - robot_x) - robot_yaw
                    bearing = (bearing + math.pi) % (2.0 * math.pi) - math.pi
                    rate = float(self.search.yaw_rate)
                    vyaw = max(-rate, min(rate, 1.6 * bearing))
                    # Seam 1: scan-WHILE-translating toward the resolved target.
                    # Every clause is a hard gate — see SCAN_CREEP_MPS. Absent
                    # clearance data (`nearest_obstacle_m is None`) it does not
                    # creep, and the omnidirectional clearance requirement is far
                    # more conservative than the creep needs.
                    target_range = math.hypot(mapped.y - robot_y, mapped.x - robot_x)
                    clearance = observation.nearest_obstacle_m
                    if (
                        abs(bearing) <= self._SCAN_CREEP_MAX_BEARING_RAD
                        and target_range > self._SCAN_CREEP_MIN_RANGE_M
                        and clearance is not None
                        and clearance > self._SCAN_CREEP_CLEARANCE_M
                    ):
                        vx = self.SCAN_CREEP_MPS
                return MidLevelCommand(
                    vx=vx,
                    vy=0.0,
                    vyaw=vyaw,
                    note=result.note or "semantic_search_scan",
                )
            # Confirmation budget exhausted without required_observations —
            # fail closed (do not commit a single-frame hit).
            reply = honest_not_found_reply(
                _refusal_label(semantic_goal),
                scanned=self._already_scanned,
                searched=self._already_searched,
            )
            self.mission.status = "failed"
            self.mission.metadata.update(
                {
                    "resolution_state": "not_found",
                    "grounding_outcome": grounded.outcome.value,
                    "recovery_phase": "failed",
                    "reply": reply,
                }
            )
            return self._target_missing_command()

        if action == ScanRecoveryAction.CLARIFY:
            self.mission.status = "failed"
            self.mission.metadata["resolution_state"] = "ambiguous"
            return MidLevelCommand(stop=True, note="semantic_target_ambiguous")

        if action == ScanRecoveryAction.REPORT:
            reply = honest_not_found_reply(
                _refusal_label(semantic_goal),
                scanned=self._already_scanned,
                searched=self._already_searched,
            )
            self.mission.status = "failed"
            self.mission.metadata.update(
                {
                    "resolution_state": "not_found",
                    "grounding_outcome": GroundingOutcome.UNSEEN.value,
                    "recovery_phase": "failed",
                    "reply": reply,
                }
            )
            return self._target_missing_command()

        if action == ScanRecoveryAction.SCAN or (
            grounded.outcome == GroundingOutcome.UNSEEN and not self._already_scanned
        ):
            return self._step_scan_behavior(semantic_goal, observation)

        # SEARCH (UNSEEN after scan) or frontier continuation.
        # ``_already_searched`` means the frontier budget was exhausted (report),
        # not that SearchEntity has merely started — otherwise the next UNSEEN
        # tick would jump straight to REPORT.
        if self._recovery_phase != "frontier":
            self._recovery_phase = "frontier"
            self._frontier_target = None
            if search_entity_plan_step is not None:
                self.mission.metadata["recovery_plan_step"] = search_entity_plan_step(
                    semantic_goal.query
                )
        self.mission.metadata["recovery_phase"] = "frontier"
        return self._step_search_entity_frontier(semantic_goal, observation)

    def _drop_remembered_false_positives(
        self, candidates: list[SemanticCandidate]
    ) -> list[SemanticCandidate]:
        if self._false_positives is None or not candidates:
            return candidates
        kept = [
            candidate
            for candidate in candidates
            if not self._false_positives.is_rejected(
                candidate.x, candidate.y, candidate.label
            )
        ]
        if len(kept) != len(candidates) and self.mission is not None:
            self.mission.metadata["false_positives_filtered"] = (
                int(self.mission.metadata.get("false_positives_filtered", 0))
                + (len(candidates) - len(kept))
            )
        return kept

    @property
    def _resolution_semantic_map(self) -> SemanticMap:
        """The semantic map minus instances this mission proved unroutable.

        The exclusion has to live on the *map handle*, not only on the ladder's
        own frustum list: ``ActiveSemanticSearch.observe`` and the ScanBehavior
        branch both re-query the map themselves, so a released commitment would
        otherwise be re-confirmed and re-committed on the very next tick.
        With nothing excluded this returns ``self.semantic_map`` unchanged, so
        the ordinary path keeps the identical object it always had.
        """

        if not self._unreachable_candidates:
            return self.semantic_map
        return _ExcludingSemanticMap(
            self.semantic_map, frozenset(self._unreachable_candidates)
        )

    def _step_scan_behavior(
        self,
        semantic_goal: Any,
        observation: NavObservation,
    ) -> MidLevelCommand:
        """ScanBehavior recovery: full-turn stops → populate memory → re-ground."""

        assert self.mission is not None
        self._recovery_phase = "scan"
        self.mission.status = "searching"
        self.mission.metadata["recovery_phase"] = "scan"
        self.mission.metadata["resolution_state"] = "searching"
        if self.scan_behavior is None or full_turn_scan_spec is None:
            # Fallback: legacy continuous yaw search.
            result = self.search.observe(semantic_goal, self._resolution_semantic_map, observation)
            self._scan_steps += 1
            if isinstance(result, SemanticCandidate):
                return self._commit_semantic_candidate(
                    semantic_goal,
                    result,
                    observation,
                    grounding_outcome=GroundingOutcome.RESOLVED.value,
                )
            if isinstance(result, MidLevelCommand) and not result.stop:
                return MidLevelCommand(
                    vx=0.0,
                    vy=0.0,
                    vyaw=result.vyaw,
                    note=result.note or "semantic_search_scan",
                )
            self._already_scanned = True
            if self.frontier_budget_steps <= 0:
                reply = honest_not_found_reply(
                    _refusal_label(semantic_goal), scanned=True, searched=False
                )
                self.mission.status = "failed"
                self.mission.metadata.update(
                    {
                        "resolution_state": "not_found",
                        "recovery_phase": "failed",
                        "reply": reply,
                    }
                )
                return self._target_missing_command()
            return self._step_search_entity_frontier(semantic_goal, observation)

        if not self.scan_behavior.started:
            dwell = max(1, round(self.scan_behavior.spec.dwell_s * 10.0))
            self.scan_behavior.dwell_steps_per_stop = dwell
            # U34 (D-4): the scan's start heading was ``position[2]`` (the
            # standing height), so every full-turn scan began 15.5 deg from
            # where the robot was actually pointing and its stop bearings were
            # all offset by that constant.
            # C2: full_turn_scan_spec is ONLY the first-UNSEEN VLFM init.
            spec = self.scan_behavior.start(
                _pose_in(observation, MAP_FRAME).yaw,
                spec=full_turn_scan_spec(),
            )
            self.mission.metadata["recovery_plan_step"] = spec.as_plan_step()
            self._publish_scan_viewpoint(observation)

        self._scan_steps += 1
        # Interchangeable (stuff-class / explicit "nearest") queries must not
        # commit to the FIRST instance that rotates into the frustum: which
        # sidewalk is nearest is only answerable after looking around, and
        # first-seen-wins made the answer depend on scan direction
        # (arbitration 2026-08-07, region-instance selection). Unique-target
        # queries keep the early commit — there is nothing to rank.
        interchangeable_scan = getattr(semantic_goal, "kind", "") == "region" or (
            getattr(semantic_goal, "superlative", None) == "nearest"
        )
        # Re-ground every tick while scanning — in-range targets may enter frustum.
        frustum = self._resolution_semantic_map.query(semantic_goal, observation)
        if frustum and not interchangeable_scan:
            confirmed = self.search.observe(
                semantic_goal, self._resolution_semantic_map, observation
            )
            if isinstance(confirmed, SemanticCandidate):
                return self._commit_semantic_candidate(
                    semantic_goal,
                    confirmed,
                    observation,
                    grounding_outcome=GroundingOutcome.RESOLVED.value,
                )
        mem = self._memory_candidates(semantic_goal, observation)
        if mem and self._scan_steps > 1 and not interchangeable_scan:
            return self._commit_semantic_candidate(
                semantic_goal,
                mem[0],
                observation,
                grounding_outcome=GroundingOutcome.MEMORY_HIT.value,
            )

        # VS-5: the paint moved UP to the single ingress in
        # ``_step_semantic_resolution`` (every searching tick, before grounding),
        # so this call site is gone — it painted only the ticks that got past the
        # commit doors above, which is why the map ran empty.
        cmd = self.scan_behavior.step(observation)
        if cmd is not None and self._scan_steps < self.scan_budget_steps:
            return cmd

        # C2: after init (or a value look) completes, GP-UCB may request another
        # dwell before handing off to SearchEntity. Flag-off skips this block.
        if (
            self.value_directed_search
            and self._value_scan_session is not None
            and self.scan_behavior is not None
            and self._scan_steps < self.scan_budget_steps
            and not interchangeable_scan
        ):
            if not self._value_scan_session.init_done:
                self._value_scan_session.mark_init_complete()
            robot_map = _pose_in(observation, MAP_FRAME)
            choice = self._value_scan_session.choose_next_look(
                origin_world_xy=robot_map.xy,
                current_yaw_rad=robot_map.yaw,
            )
            self.mission.metadata["scan_look_decision"] = choice.decision.value
            self.mission.metadata["scan_look_ucb"] = choice.ucb
            if (
                choice.decision == ScanLookDecision.LOOK
                and choice.yaw_rad is not None
            ):
                self.scan_behavior.enqueue_value_look(choice.yaw_rad)
                self._publish_scan_viewpoint(observation, yaw_rad=choice.yaw_rad)
                cmd = self.scan_behavior.step(observation)
                if cmd is not None:
                    return cmd

        if interchangeable_scan:
            # Scan complete: choose over EVERYTHING seen, ranked by the
            # grounder's boundary-aware distance (nearest steppable region
            # wins, not nearest centroid and not first-seen).
            pool = list(self._resolution_semantic_map.query(semantic_goal, observation))
            seen_ids = {c.candidate_id for c in pool}
            pool.extend(
                c
                for c in self._memory_candidates(semantic_goal, observation)
                if c.candidate_id not in seen_ids
            )
            if pool and ground_query is not None and self.grounder_v2 is not None:
                # MAP: the scan-completion ranking is over world-frame region
                # polygons, the same frame the grounding origin above uses.
                robot_map = _pose_in(observation, MAP_FRAME)
                grounded, mapped = ground_query(
                    semantic_goal.query,
                    frustum=pool,
                    robot_xy=robot_map.xy,
                    robot_yaw_rad=robot_map.yaw,
                    grounder=self.grounder_v2,
                    interchangeable=True,
                )
                if (
                    grounded.outcome
                    in {GroundingOutcome.RESOLVED, GroundingOutcome.MEMORY_HIT}
                    and mapped is not None
                ):
                    return self._commit_semantic_candidate(
                        semantic_goal,
                        mapped,
                        observation,
                        grounding_outcome=grounded.outcome.value,
                    )
            elif pool:
                return self._commit_semantic_candidate(
                    semantic_goal,
                    pool[0],
                    observation,
                    grounding_outcome=GroundingOutcome.RESOLVED.value,
                )

        # Scan finished (or budget exhausted) without a commit → SearchEntity.
        self._already_scanned = True
        self.scan_behavior.reset()
        if self.frontier_budget_steps <= 0:
            reply = honest_not_found_reply(
                _refusal_label(semantic_goal), scanned=True, searched=False
            )
            self.mission.status = "failed"
            self.mission.metadata.update(
                {
                    "resolution_state": "not_found",
                    "grounding_outcome": GroundingOutcome.UNSEEN.value,
                    "recovery_phase": "failed",
                    "reply": reply,
                }
            )
            return self._target_missing_command()
        self._recovery_phase = "frontier"
        self.mission.metadata["recovery_phase"] = "frontier"
        self._frontier_target = None
        if search_entity_plan_step is not None:
            self.mission.metadata["recovery_plan_step"] = search_entity_plan_step(
                semantic_goal.query
            )
        return self._step_search_entity_frontier(semantic_goal, observation)

    def _step_search_entity_frontier(
        self,
        semantic_goal: Any,
        observation: NavObservation,
    ) -> MidLevelCommand:
        """Bounded SearchEntity frontier crawl (SearchOwner ring pattern + priors)."""

        assert self.mission is not None
        self._frontier_steps += 1
        # MAP: frontier targets and coverage viewpoints are world-frame.
        robot_xy = _pose_in(observation, MAP_FRAME).xy
        self._record_frontier_viewpoint(robot_xy)

        frontier_hits = self._resolution_semantic_map.query(semantic_goal, observation)
        if frontier_hits:
            return self._commit_semantic_candidate(
                semantic_goal,
                frontier_hits[0],
                observation,
                grounding_outcome=GroundingOutcome.RESOLVED.value,
            )
        mem = self._memory_candidates(semantic_goal, observation)
        if mem:
            return self._commit_semantic_candidate(
                semantic_goal,
                mem[0],
                observation,
                grounding_outcome=GroundingOutcome.MEMORY_HIT.value,
            )

        if self._frontier_steps >= self.frontier_budget_steps:
            self._already_searched = True
            reply = honest_not_found_reply(
                _refusal_label(semantic_goal),
                scanned=self._already_scanned or self._scan_steps > 0,
                searched=True,
            )
            self.mission.status = "failed"
            self.mission.metadata.update(
                {
                    "resolution_state": "not_found",
                    "grounding_outcome": GroundingOutcome.UNSEEN.value,
                    "recovery_phase": "failed",
                    "reply": reply,
                }
            )
            return self._target_missing_command()

        origin = robot_xy
        if self.mission.metadata.get("last_seen_xy"):
            raw = self.mission.metadata["last_seen_xy"]
            if isinstance(raw, (list, tuple)) and len(raw) >= 2:
                origin = (float(raw[0]), float(raw[1]))

        if self._frontier_target is None or math.hypot(
            self._frontier_target[0] - robot_xy[0],
            self._frontier_target[1] - robot_xy[1],
        ) < 0.35:
            self._frontier_target = self._select_semantic_frontier(
                origin, robot_xy, query_label=semantic_goal.query
            )
            if (
                self._frontier_target is not None
                and _HAS_INSTRUCTNAV
                and SE2Goal is not None
                and self.proposer_bus is not None
                and self.goal_arbiter is not None
            ):
                now_s = float(observation.extras.get("time_s") or 0.0)
                proposed = SE2Goal(
                    source="search_entity",
                    pose=(self._frontier_target[0], self._frontier_target[1], 0.0),
                    confidence=0.4,
                    ttl_s=3.0,
                    plan_step_id="search_entity",
                    issued_s=now_s,
                    priority=4,
                    task_id=self._active_task_id,
                    plan_revision=self._active_plan_revision,
                )
                self.proposer_bus.publish(proposed)
                self.goal_arbiter.set_plan_step("search_entity")
                chosen = self.goal_arbiter.resolve((proposed,), now_s=now_s)
                if chosen is None:
                    self._frontier_target = None

        if self._frontier_target is None:
            return MidLevelCommand(
                vx=0.0,
                vy=0.0,
                vyaw=0.35,
                note="search_entity_spin",
            )

        dx = self._frontier_target[0] - robot_xy[0]
        dy = self._frontier_target[1] - robot_xy[1]
        # U34 (D-4): frontier bearings were computed against ``position[2]``
        # (standing height) with a 0.0 fallback, so the align gate below turned
        # to a heading 15.5 deg off the frontier it had chosen.
        heading = _pose_in(observation, MAP_FRAME).yaw
        bearing = math.atan2(dy, dx) - heading
        while bearing > math.pi:
            bearing -= 2.0 * math.pi
        while bearing < -math.pi:
            bearing += 2.0 * math.pi
        if abs(bearing) > 0.45:
            return MidLevelCommand(
                vx=0.0,
                vy=0.0,
                vyaw=max(-0.6, min(0.6, 1.6 * bearing)),
                note="search_entity_align",
            )
        return MidLevelCommand(
            vx=0.22,
            vy=0.0,
            vyaw=max(-0.35, min(0.35, 0.8 * bearing)),
            note="search_entity_frontier",
        )

    def _select_semantic_frontier(
        self,
        origin: tuple[float, float],
        robot_xy: tuple[float, float],
        *,
        query_label: str = "",
        rings: int = 3,
        bearings: int = 12,
        ring_step_m: float = 2.0,
        travel_weight: float = 0.06,
    ) -> tuple[float, float] | None:
        """SearchEntity frontier: semantic prior − geodesic (+ coverage novelty)."""

        if select_search_entity_frontier is not None:
            # VS-5 empty-map delegation, made TOTAL at the call site. The scorer
            # itself delegates to the flag-off scorer object on an evidence-free
            # map (``ValueMapFrontierScorer.baseline_scorer``), but the scorer
            # cannot reach the CANDIDATES: with a value map in hand the callee
            # also stamps ``coverage_gain`` from the map's unknown_fraction
            # instead of the flag-off novelty test, and a map full of MISSES is
            # no longer unknown. Passing ``None`` here is not an approximation of
            # the flag-off call — it IS the flag-off call, same function, same
            # arguments, so ``evidence_count == 0`` gives a bit-identical
            # frontier decision sequence however many misses have been painted.
            directed = self._value_map_has_evidence()
            if self.value_directed_search:
                if directed:
                    self.value_directed_frontiers += 1
                else:
                    self.value_baseline_frontiers += 1
            return select_search_entity_frontier(
                origin_xy=origin,
                robot_xy=robot_xy,
                query_label=query_label or "unknown",
                covered=self._frontier_viewpoints,
                rings=rings,
                bearings=bearings,
                ring_step_m=ring_step_m,
                travel_weight=travel_weight,
                value_map=self.semantic_value_map if directed else None,
                plan_prior=self._plan_time_prior if directed else None,
            )
        # Soft-import fallback without SearchEntity helpers.
        scored: list[tuple[float, int, tuple[float, float]]] = []
        index = 0
        for ring in range(1, rings + 1):
            radius = ring * ring_step_m
            for step in range(bearings):
                angle = 2.0 * math.pi * step / bearings
                candidate = (
                    origin[0] + math.cos(angle) * radius,
                    origin[1] + math.sin(angle) * radius,
                )
                index += 1
                if self._frontier_already_covered(candidate):
                    continue
                travel = math.hypot(candidate[0] - robot_xy[0], candidate[1] - robot_xy[1])
                scored.append((1.0 - travel_weight * travel, index, candidate))
        if not scored:
            return None
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][2]

    def _frontier_already_covered(self, candidate: tuple[float, float]) -> bool:
        radius = 1.5
        return any(
            math.hypot(candidate[0] - x, candidate[1] - y) <= radius
            for x, y in self._frontier_viewpoints
        )

    def _publish_scan_viewpoint(
        self,
        observation: NavObservation,
        *,
        yaw_rad: float | None = None,
    ) -> None:
        """Plan scan stops as SE2 viewpoints through ProposerBus / base-lease."""

        if (
            not self.value_directed_search
            or self._value_scan_session is None
            or SE2Goal is None
            or self.proposer_bus is None
            or self.goal_arbiter is None
        ):
            return
        robot_map = _pose_in(observation, MAP_FRAME)
        yaw = float(yaw_rad) if yaw_rad is not None else float(robot_map.yaw)
        if self.scan_behavior is not None and yaw_rad is None:
            current = self.scan_behavior.current_stop_yaw
            if current is not None:
                yaw = float(current)
        now_s = float(observation.extras.get("time_s") or 0.0)
        proposed = self._value_scan_session.se2_viewpoint(
            x=robot_map.x,
            y=robot_map.y,
            yaw_rad=yaw,
            now_s=now_s,
            task_id=self._active_task_id,
            plan_revision=self._active_plan_revision,
        )
        self.proposer_bus.publish(proposed)
        self.goal_arbiter.set_plan_step(proposed.plan_step_id)
        self.goal_arbiter.resolve((proposed,), now_s=now_s)
        if self.mission is not None:
            self.mission.metadata["scan_proposer_source"] = SCAN_PROPOSER_SOURCE

    def _paint_scan_observation(
        self,
        semantic_goal: Any,
        observation: NavObservation,
        frustum: list[Any],
    ) -> None:
        """Paint the current look into the shared SemanticValueMap2D belief.

        VS-5: the paint tuple is VS-3's, not this method's. The replaced painter
        floored every scanned cone at ``0.15`` (and every irrelevant sighting at
        ``0.05``) with ``conf=1.0``, so LOOKING somewhere RAISED its value
        whether or not anything relevant was there — a scanned-cone marker, and
        the reason the map could not distinguish "searched here, nothing" from
        "never looked". The policy replaces both floors and the substring
        branch: ``value = match_score x observation_confidence`` through the
        SigLIP seam, and a cone with no query-relevant evidence in it paints a
        MISS at the SAME optical-axis confidence, which pulls the fused value of
        every covered cell DOWN so the search stops re-looking there.

        ``frustum`` is the one ingress — the very list grounding is about to
        read, after the false-positive and attribute filters — so this method
        invents no second perception channel (record §2.1(2a)). Its caller is
        the single ingress point in :meth:`_step_semantic_resolution`, which
        runs on EVERY searching tick: the frustum-confirm ticks, the scan ticks
        and the frontier crawl alike. The evidence a look produces therefore
        survives the release of a commitment the planner could not route to
        (``_begin_semantic_replan`` clears scan/frontier state but not the
        belief map), which is how the ~12 m frustum / ~8 m local-costmap window
        the record names is closed by the existing frontier machinery rather
        than by a new mechanism.
        """

        if (
            not self.value_directed_search
            or self.semantic_value_map is None
            or self._value_evidence is None
            or paint_look is None
        ):
            return
        robot_map = _pose_in(observation, MAP_FRAME)
        paint = self._value_evidence.paint(
            str(getattr(semantic_goal, "query", "") or ""), frustum
        )
        painted = paint_look(
            self.semantic_value_map,
            origin_world_xy=robot_map.xy,
            heading_rad=robot_map.yaw,
            value=paint.value,
            conf=paint.conf,
            is_evidence=paint.is_evidence,
        )
        self.value_paints += 1
        self.value_cells_painted += int(painted)
        if paint.is_evidence:
            self.value_evidence_paints += 1
        else:
            self.value_miss_paints += 1
        if self.mission is not None:
            self.mission.metadata["value_map_evidence_count"] = (
                self.semantic_value_map.evidence_count
            )
            self.mission.metadata["value_map_last_paint"] = paint.as_tuple()

    def _value_map_has_evidence(self) -> bool:
        """The empty-map delegation predicate (VS-3's frozen ``evidence_count``).

        False means the map holds nothing that could move a decision, and every
        value-directed branch must then be the flag-off branch — not an
        approximation of it, the same call.
        """

        return (
            self.value_directed_search
            and self.semantic_value_map is not None
            and self.semantic_value_map.evidence_count > 0
        )

    def _value_map_telemetry_note(self, cmd: MidLevelCommand) -> MidLevelCommand:
        """Stamp the VS-5 counters onto a non-terminal searching command.

        ``MidLevelCommand.note`` is the only navigator-side channel the frozen
        eval runner persists per step (VS-4 §14.4), and the card's non-vacuity
        conjunct — that the value-directed path ENGAGED — has to be assertable
        from traces. Appended after a ``|`` delimiter, only under the flag, and
        only on non-terminal commands, so the runner's own note keys are
        untouched: the ``semantic_search_scan`` prefix test still sees the same
        prefix, ``reason`` (set only from a terminal note) is never written, and
        none of ``frontier`` / ``semantic_target_not_found`` / ``scan_for_target``
        appears in the suffix.
        """

        if not self.value_directed_search or cmd.stop:
            return cmd
        evidence = (
            self.semantic_value_map.evidence_count
            if self.semantic_value_map is not None
            else 0
        )
        suffix = (
            f"value_map=evidence={evidence}"
            f",paints={self.value_paints}"
            f",hits={self.value_evidence_paints}"
            f",misses={self.value_miss_paints}"
            f",cells={self.value_cells_painted}"
            f",directed={self.value_directed_frontiers}"
            f",delegated={self.value_baseline_frontiers}"
        )
        return replace(cmd, note=f"{cmd.note}|{suffix}" if cmd.note else suffix)

    def suspend_scan_for_summons(self) -> None:
        """Acoustic/attention summons: suspend in-flight scan (do not cancel)."""

        if self.scan_behavior is not None:
            self.scan_behavior.suspend()
        if self.mission is not None:
            self.mission.metadata["scan_suspended"] = True

    def resume_scan_after_summons(self) -> None:
        if self.scan_behavior is not None:
            self.scan_behavior.resume()
        if self.mission is not None:
            self.mission.metadata.pop("scan_suspended", None)

    def _record_frontier_viewpoint(self, position: tuple[float, float]) -> None:
        spacing = 0.8
        if not self._frontier_viewpoints or all(
            math.hypot(position[0] - x, position[1] - y) > spacing
            for x, y in self._frontier_viewpoints[-4:]
        ):
            self._frontier_viewpoints.append(position)
        if len(self._frontier_viewpoints) > 256:
            del self._frontier_viewpoints[:128]

    def _progress_watchdog(self, observation: NavObservation) -> MidLevelCommand | None:
        assert self.mission is not None and self.mission.goal is not None
        # MAP, not ODOM. The hysteresis, the person-yield clause and the stall
        # taxonomy are card C3's leaf, ``navigation/stall_attribution``.
        robot_map = _pose_in(observation, MAP_FRAME)
        distance = math.hypot(self.mission.goal.x - robot_map.x, self.mission.goal.y - robot_map.y)
        if stall.goal_progress_made(self._best_goal_distance_m, distance):
            self._best_goal_distance_m = distance
            self._steps_without_progress = 0
            return None
        if stall.person_yield_holds(observation.nearest_person_m, self.collision.person_stop_m):
            return None
        self._steps_without_progress += 1
        if self._steps_without_progress < self.progress_timeout_steps:
            return None

        replans = int(self.mission.metadata.get("replan_count", 0))
        if self.mission.semantic_goal is not None and replans < self.max_semantic_replans:
            if stall.held_release_due(
                self.mission.metadata,
                getattr(self._navigator, "last_route_status", None),
                self._body_is_still,
                enabled=self.held_stall_release,
            ):
                return self._release_unreachable_candidate(
                    str(self.mission.metadata.get("candidate_id") or ""),
                    note=stall.HELD_RELEASE_NOTE,
                )
            return self._begin_semantic_replan(
                replans,
                note="semantic_replan_after_no_progress",
            )

        self.mission.status = "failed"
        self.mission.metadata["resolution_state"] = "stalled"
        self.mission.metadata["plan_step"] = "failed"
        return MidLevelCommand(stop=True, note="navigation_no_progress")

    #: Consecutive ticks the global planner may report the committed goal
    #: unroutable, with zero goal progress, before the mission releases that
    #: commitment. 6.0 s at the 10 Hz control rate — long enough that a
    #: transient blockage (a pedestrian standing on the goal cell) clears
    #: first, and far short of ``progress_timeout_steps`` (200), so the release
    #: happens while the ladder still has replans left to spend on an
    #: alternate.
    UNROUTABLE_GOAL_STEPS = 60

    #: One terminal-pose retry for a committed ``near`` / ``next_to`` object.
    #:
    #: A route failure proves that the selected pose cannot be executed from
    #: the current observation; it does not prove that every pose in the
    #: object's already-approved K0 arrival region is blocked. The retry is
    #: deliberately one-shot so fresh perception can repair that distinction
    #: without turning a genuinely boxed-in object into an unbounded resample
    #: loop. No alternate pose means the existing fail-closed release runs on
    #: the same tick.
    TERMINAL_POSE_REPLAN_LIMIT = 1

    def _unroutable_goal_recovery(
        self,
        observation: NavObservation,
    ) -> MidLevelCommand | None:
        """Release a commitment the planner has *proved* it cannot route to.

        ``goal_blocked`` / ``no_path`` is not "slow": it is the A* planner
        reporting that no traversable cell exists in the goal region. The grid
        controller's only answer is ``_recovery_command``, which at the
        shipping ``recovery_reverse_steps=0`` is pure in-place yaw — so a
        semantic goal that lands inside an inflated obstacle makes the robot
        spin until the progress watchdog fails the mission, and the watchdog's
        replan re-grounds the *same* instance and re-derives the *same*
        unroutable pose. Committing forever to an instance you cannot reach is
        the defect; the NavigateTo contract already names the answer
        (``alternate_candidate`` / ``rescan``).

        So: release the commitment, remember the instance as unreachable *for
        this mission*, and hand back to the resolution ladder, which re-grounds
        without it — the look-around finds the alternate. Only when the ladder
        itself exhausts does the mission fail, and it fails saying so.

        Returns ``None`` on every tick that is not this case, including for
        navigator models that expose no route status at all.
        """

        if self.mission is None or self.mission.semantic_goal is None:
            return None
        status = getattr(self._navigator, "last_route_status", None)
        if status not in {"goal_blocked", "no_path"}:
            self._steps_goal_unroutable = 0
            return None
        # Unroutable *while the body is still travelling* is a detour in
        # progress, not a dead goal. Card A2 fix 3.4: the witness used to be
        # ``_steps_without_progress == 0`` — the distance-to-goal watchdog — and
        # a semantic goal that jitters with its detector kept resetting it, so
        # this release never fired: 778 ticks of ``grid_recover_scan
        # status=goal_blocked`` in one measured episode, in-place yaw the whole
        # way, ending in the step limit with no typed reason. In-place recovery
        # yaw is exactly the case the body-displacement witness reads correctly
        # and the goal-distance one does not.
        if not self._body_is_still:
            self._steps_goal_unroutable = 0
            return None
        self._steps_goal_unroutable += 1
        if self._steps_goal_unroutable < self.UNROUTABLE_GOAL_STEPS:
            return None

        # RM-2 trigger (i): consult route memory BEFORE the release. The release
        # is irreversible for this mission -- a blacklisted candidate can never
        # be re-grounded -- so "I have a recorded route to that place" has to be
        # asked here or it can never be asked at all. Memory answers ``()`` for
        # anything it has not actually driven, in which case this falls straight
        # through to the byte-identical release below.
        if self._route_memory is not None and self._route_memory_defer_release(
            trigger=f"unroutable:{status}"
        ):
            self.route_memory_deferred_releases += 1
            self.mission.metadata["route_memory_deferred_release"] = str(status)
            # DEFER, do not cancel: the counter is reset so the suspended
            # UNROUTABLE_GOAL_STEPS budget starts over if the chain retires
            # without getting anywhere. Nothing is blacklisted.
            self._steps_goal_unroutable = 0
            return None

        replanned = self._retry_committed_terminal_pose(
            observation,
            trigger=f"unroutable:{status}",
        )
        if replanned is not None:
            return replanned

        self.mission.metadata["unroutable_route_status"] = str(status)
        return self._release_unreachable_candidate(
            str(self.mission.metadata.get("candidate_id") or ""),
            note="semantic_replan_after_unroutable_goal",
        )

    def _retry_committed_terminal_pose(
        self,
        observation: NavObservation,
        *,
        trigger: str,
    ) -> MidLevelCommand | None:
        """Re-solve one blocked terminal pose without abandoning its object.

        ``goal_blocked`` and the local obstacle gate are evidence against the
        *selected pose*. For ``near`` / ``next_to`` an object exposes a whole
        verified arrival region, so blacklisting the object before asking the
        existing approach solver for another point loses valid solutions. A
        fresh, exact-id sighting gets one bounded retry through the same support,
        clearance, etiquette, K0-region, and goal-arbiter authorities used at
        initial commitment.

        Any missing evidence, unchanged pose, solver refusal, or arbiter veto
        returns ``None``. The caller then executes the pre-existing unreachable
        release immediately; this method never weakens a gate or keeps a boxed
        target alive.
        """

        mission = self.mission
        if mission is None or mission.goal is None or mission.semantic_goal is None:
            return None
        if mission.semantic_goal.terminal_relation not in {"near", "next_to"}:
            return None
        # Preserve the resolution ladder's candidate-selection authority. Its
        # first recovery move is instance substitution: salvaging the first
        # blocked sighting locally can turn "the lamppost" into a verified
        # arrival at a farther, contextually wrong instance that merely entered
        # view first. Once the ladder has actually ruled out one instance, terminal
        # pose diversity on the alternate is the remaining recovery axis. This
        # is the bounded candidate-then-pose schedule; it contains no object-id
        # or scene-specific exception.
        if not self._unreachable_candidates:
            mission.metadata["terminal_pose_replan_refusal"] = (
                "candidate_alternative_not_yet_tried"
            )
            return None
        attempts = int(mission.metadata.get("terminal_pose_replan_attempts", 0))
        if attempts >= self.TERMINAL_POSE_REPLAN_LIMIT:
            return None

        # Count the opportunity, not only a success. A blind or boxed-in
        # object therefore cannot be re-sampled again after another hold window.
        mission.metadata["terminal_pose_replan_attempts"] = attempts + 1
        mission.metadata["terminal_pose_replan_trigger"] = str(trigger)

        candidate = self._terminal_retry_candidate(observation)
        if candidate is None:
            return None

        previous = mission.goal
        self._clear_terminal_pose_diagnostics()
        pose, approach_costs = self._solve_semantic_approach_pose(
            mission.semantic_goal,
            candidate,
            observation,
        )
        if pose is None:
            mission.metadata["terminal_pose_replan_refusal"] = "no_safe_pose"
            return None
        displacement = math.hypot(pose.x - previous.x, pose.y - previous.y)
        if displacement < self.GATE_HOLD_DISPLACEMENT_M:
            mission.metadata["terminal_pose_replan_refusal"] = "pose_unchanged"
            mission.metadata["terminal_pose_replan_displacement_m"] = displacement
            return None
        committed_region = self._arrival_goal_region()
        if committed_region is None or not committed_region.contains(pose.x, pose.y):
            mission.metadata["terminal_pose_replan_refusal"] = (
                "outside_committed_arrival_region"
            )
            return None
        if not self._approach_goal_admitted(pose, candidate.confidence, observation):
            mission.metadata["terminal_pose_replan_refusal"] = "arbiter_veto"
            return None

        return self._commit_terminal_pose_retry(
            observation=observation,
            candidate=candidate,
            previous=previous,
            pose=pose,
            approach_costs=approach_costs,
            trigger=trigger,
            displacement=displacement,
        )

    def _terminal_retry_candidate(
        self,
        observation: NavObservation,
    ) -> SemanticCandidate | None:
        """Return the exact committed candidate only while its geometry agrees."""

        mission = self.mission
        assert mission is not None and mission.semantic_goal is not None
        candidate_id = str(mission.metadata.get("candidate_id") or "")
        candidate = next(
            (
                item
                for item in self.semantic_map.query(mission.semantic_goal, observation)
                if item.candidate_id == candidate_id
            ),
            None,
        )
        if candidate is None:
            mission.metadata["terminal_pose_replan_refusal"] = "candidate_not_visible"
            return None
        # Identity is insufficient: retaining the old K0 region while solving
        # against changed polygon/support/clearance geometry would combine two
        # incompatible safety proofs.
        if not self._terminal_retry_geometry_matches_commit(candidate):
            mission.metadata["terminal_pose_replan_refusal"] = (
                "candidate_geometry_changed"
            )
            return None
        return candidate

    def _terminal_retry_geometry_matches_commit(
        self,
        candidate: SemanticCandidate,
    ) -> bool:
        """Bind a pose retry to the exact geometry already commissioned at K0."""

        mission = self.mission
        if mission is None or mission.semantic_goal is None:
            return False
        committed_region = mission.metadata.get("arrival_goal_region")
        refreshed_region = self._build_arrival_goal_region(
            mission.semantic_goal.terminal_relation,
            candidate,
        )
        if refreshed_region != committed_region:
            return False
        if _polygon(candidate.polygon) != _polygon(mission.metadata.get("target_polygon")):
            return False
        if _polygon(candidate.metadata.get("support_polygon")) != _polygon(
            mission.metadata.get("support_polygon")
        ):
            return False
        scalar_geometry = (
            (
                "candidate_radius_m",
                _metadata_float(
                    candidate.metadata,
                    "radius_m",
                    default=0.0,
                    minimum=0.0,
                    maximum=5.0,
                ),
            ),
            (
                "terminal_clearance_m",
                _metadata_float(
                    candidate.metadata,
                    "terminal_clearance_m",
                    default=0.32,
                    minimum=0.10,
                    maximum=1.0,
                ),
            ),
            (
                "terminal_support_clearance_m",
                _metadata_float(
                    candidate.metadata,
                    "terminal_support_clearance_m",
                    default=0.32,
                    minimum=0.10,
                    maximum=1.0,
                ),
            ),
        )
        for key, refreshed in scalar_geometry:
            committed = mission.metadata.get(key)
            if isinstance(committed, bool) or not isinstance(committed, (int, float)):
                return False
            if not math.isclose(float(committed), refreshed, rel_tol=0.0, abs_tol=1e-12):
                return False
        return True

    def _commit_terminal_pose_retry(
        self,
        *,
        observation: NavObservation,
        candidate: SemanticCandidate,
        previous: GoalPose,
        pose: GoalPose,
        approach_costs: dict[str, Any],
        trigger: str,
        displacement: float,
    ) -> MidLevelCommand:
        """Commit an admitted retry and reset only pose-dependent state."""

        # A route-memory waypoint is relative to the old terminal pose. Purge
        # only that source's pending proposal before resetting the local planner.
        if self._route_memory is not None:
            self._flush_route_memory_waypoints("terminal_pose_replanned")
        mission = self.mission
        assert mission is not None and mission.semantic_goal is not None
        mission.goal = pose
        mission.status = "running"
        mission.metadata.update(
            {
                "resolution_state": "resolved",
                "plan_step": "align_then_translate",
                "candidate_position": (candidate.x, candidate.y, candidate.z),
                "candidate_confidence": candidate.confidence,
                "candidate_source": candidate.source,
                "target_polygon": candidate.polygon,
                "associated_lidar_ids": sorted(_candidate_obstacle_ids(candidate)),
                "goal_landmark_position": (float(candidate.x), float(candidate.y)),
                "goal_landmark_offset": (
                    float(pose.x) - float(candidate.x),
                    float(pose.y) - float(candidate.y),
                    float(pose.heading_deg),
                ),
                "terminal_pose_replan_count": int(
                    mission.metadata.get("terminal_pose_replan_count", 0)
                )
                + 1,
                "terminal_pose_replan_previous": (
                    float(previous.x),
                    float(previous.y),
                    float(previous.heading_deg),
                ),
                "terminal_pose_replan_goal": (
                    float(pose.x),
                    float(pose.y),
                    float(pose.heading_deg),
                ),
                "terminal_pose_replan_displacement_m": displacement,
                **approach_costs,
            }
        )
        mission.metadata.pop("terminal_pose_replan_refusal", None)
        self._navigator.reset(mission)
        robot_map = _pose_in(observation, MAP_FRAME)
        self._best_goal_distance_m = math.hypot(
            pose.x - robot_map.x,
            pose.y - robot_map.y,
        )
        self._steps_without_progress = 0
        self._steps_goal_unroutable = 0
        self._steps_gate_blocked = 0
        self._gate_blocked_anchor_xy = None
        self._terminal_verification_steps = 0
        return MidLevelCommand(
            note=f"semantic_terminal_pose_replanned_after_{trigger}"
        )

    # ------------------------------------------------------------------
    # RM-2 — route memory on the product path. Every method below returns
    # immediately unless ``route_memory`` is on (``self._route_memory`` is None
    # flag-off), so the unconditional path is byte-identical.
    # ------------------------------------------------------------------

    #: Half the rolling planner window (RM-1's ``DEFAULT_ATTACH_RADIUS_M``,
    #: 161 cells * 0.10 m / 2 = 8.05 m), used here for the two questions it
    #: already answers: is the committed goal OUT of live-map range (so this is
    #: an at-range problem memory can help with, not an inside-obstacle one), and
    #: has it come back INTO range (so the chain hands back to normal planning)?
    #: One number, RM-1's derivation, no second constant.
    ROUTE_MEMORY_RANGE_M = ROUTE_MEMORY_ATTACH_RADIUS_M

    #: Mirror of ``controller.replan_interval_steps`` in every shipping grid model
    #: config (5). Mirrored rather than imported because this class is handed a
    #: NAVIGATOR, not a config: the navigator's own ``replan_interval_steps`` is
    #: preferred whenever it publishes one and this is the fallback for a
    #: stand-in that does not. ``tests/test_rm2_route_memory_product_path.py``
    #: pins it by reference against the yaml, so a cadence retune reddens the
    #: gate instead of silently invalidating the probe budget below.
    GRID_REPLAN_INTERVAL_STEPS = 5

    #: Consecutive ticks a live chain may fail to shorten before it is retired
    #: and today's release path resumes. Same 60 ticks / 6.0 s at 10 Hz, and the
    #: same reasoning, as :attr:`UNROUTABLE_GOAL_STEPS`: long enough for a
    #: transient blockage on the remembered route to clear, short enough that a
    #: chain going nowhere cannot spend the whole watchdog budget. Deliberately
    #: NOT a new number -- the deferral it bounds is a suspension of exactly that
    #: budget, so it is the same clock.
    ROUTE_MEMORY_STALL_STEPS = UNROUTABLE_GOAL_STEPS

    def _reset_route_memory_track(self) -> None:
        """Mission boundary: break the ingest track, drop any live chain.

        AUDIT_WAVE2 finding 1(a): the boundary must withdraw the BUFFERED
        proposal too, not only the chain. ``stop()`` + ``start()`` keep the same
        ``(task_id, plan_revision)`` key, so mission N's waypoint was neither
        stale nor flushed and survived into mission N+1's bus, where it still won
        arbitration inside its TTL.
        """

        if self._route_memory is None:
            return
        self._flush_route_memory_waypoints("mission_boundary")
        self._route_memory.reset_track()
        self._clear_route_memory_chain()
        # Mission-scoped, like ``_unreachable_candidates``: a new directive is
        # entitled to memory's help even on an instance the previous one could
        # not reach, because the robot is somewhere else by then.
        self._route_memory_spent = set()

    def _clear_route_memory_chain(self) -> None:
        self._route_memory_chain = ()
        self._route_memory_target = None
        self._route_memory_stamp = ("", 0)
        self._route_memory_best_remaining_m = None
        self._steps_route_memory_stalled = 0
        self._route_memory_probing = False
        self._route_memory_probe_refuted = False
        self._steps_route_memory_probing = 0

    def _route_memory_commitment_key(self) -> str:
        """The candidate id the release door blacklists — memory's key too.

        One key, read off the same metadata slot
        :meth:`_unroutable_goal_recovery` hands
        :meth:`_release_unreachable_candidate`, so "memory already tried and
        failed on this instance" and "this instance was released" can never
        disagree about *which* instance they mean.
        """

        if self.mission is None:
            return ""
        return str(self.mission.metadata.get("candidate_id") or "")

    def _route_memory_defer_release(self, *, trigger: str) -> bool:
        """Is the release suspended right now? The ONE answer to that question.

        Two ways it can be True, and they are not the same thing:

        * a chain is **already live**. It is live and advancing by construction —
          :meth:`_route_memory_hand_back` runs earlier in the same tick and
          retires any chain that has stopped advancing — so the deferral simply
          continues. Critically this does NOT re-arm: calling
          :meth:`_arm_route_memory_chain` again would re-query the same route and
          reset :attr:`_steps_route_memory_stalled` to zero, which is precisely
          how a stalled chain would hide its own stall and hold the release off
          forever;
        * no chain is live and memory has one to offer, so a fresh one is armed.

        Everything else is False, and False means today's release path runs
        unchanged.
        """

        if self._route_memory is None:
            return False
        if self._route_memory_chain:
            return True
        return self._arm_route_memory_chain(trigger=trigger)

    def _flush_route_memory_waypoints(self, reason: str) -> int:
        """Withdraw pending waypoints, revision-NEUTRALLY (the AF-2 amendment).

        The card's requirement is that ``flush_task`` clears pending waypoints on
        refusal or correction, and this is the single door that does it: the two
        sinks' :meth:`~parcel_robot.instructnav.arbiter.ProposerBus.flush_task`
        purge the buffered proposal, and the interim target is dropped in the
        same call so no half-withdrawn state can survive.

        It is the revision-NEUTRAL purge on purpose. Reaching for
        ``commit_revision`` here would repeat the measured AF-2 defect exactly
        (proposer self-commits ``plan_revision + 1``, the runtime restamps lower,
        every later proposal is stale and the mission dies ``arbiter_veto``
        forever). Withdrawing a waypoint is a statement about one proposal, never
        about the plan.
        """

        if self._route_memory is None:
            return 0
        if (
            not self._route_memory_chain
            and self._route_memory_target is None
            and self._route_memory_published_task is None
        ):
            # Nothing of this card's is pending, so nothing of this card's is
            # withdrawn. The published-task test is the third one on purpose: the
            # chain and the target are cleared by several paths, and without it a
            # buffered proposal whose chain had already gone would never be
            # reached by any flush at all (AUDIT_WAVE2 finding 1).
            return 0
        had_target = self._route_memory_target is not None
        self._clear_route_memory_chain()
        dropped = self._withdraw_route_memory_proposal()
        if had_target or dropped:
            self.route_memory_flushes += 1
            if self.mission is not None:
                self.mission.metadata["route_memory_flush"] = str(reason)
        return dropped

    def _withdraw_route_memory_proposal(self) -> int:
        """Purge route memory's OWN buffered proposal, and nothing else.

        Two corrections from the Wave-2 audit live in this one method.

        **Whose entry.** The purge keys off ``_route_memory_published_task`` — the
        task id the proposal was actually published under — never off
        ``_active_task_id``. A correction can SWITCH tasks, and by the time this
        runs the active key may already be the new one; keying off it left the old
        task's waypoint buffered and winning.

        **How much.** ``ProposerBus.flush_task`` is TASK-scoped by AF-2's design:
        it drops EVERY source's proposal for that task. That is right for a
        correction and wrong for a route-memory-private event such as a MAP
        re-anchor or this card's own chain retirement, where no other proposer's
        goal became invalid. ``instructnav/arbiter.py`` is consumed and not
        amended by this card, so the source-scoped withdrawal is composed from its
        public surface: read the buffer, flush the task, put everyone else back.
        ``publish`` refuses a stale proposal, so a survivor that a concurrent
        commit has just invalidated stays dropped — the restore can only ever be a
        subset of what was there, never a resurrection.
        """

        task = self._route_memory_published_task
        self._route_memory_published_task = None
        if task is None or self.proposer_bus is None or self.goal_arbiter is None:
            return 0
        flush_bus = getattr(self.proposer_bus, "flush_task", None)
        flush_arbiter = getattr(self.goal_arbiter, "flush_task", None)
        poll = getattr(self.proposer_bus, "poll", None)
        publish = getattr(self.proposer_bus, "publish", None)
        if not callable(flush_bus) or not callable(flush_arbiter):
            # Historical bundle without the AF-2 amendment: withdrawing nothing is
            # safe (the interim target is already dropped above and the pipeline
            # never polls the bus), and reaching for ``commit_revision`` is not.
            return 0
        survivors: tuple[Any, ...] = ()
        mine = 0
        scoped = callable(poll) and callable(publish)
        if scoped:
            buffered = tuple(poll(now_s=float(self._route_memory_now_s)))
            survivors = tuple(
                goal
                for goal in buffered
                if getattr(goal, "source", "") != PLACE_ROUTE_SOURCE
            )
            mine = len(buffered) - len(survivors)
        dropped = int(flush_bus(task) or 0)
        flush_arbiter(task)
        for goal in survivors:
            publish(goal)
        # Report only what was route memory's: the restored entries were never
        # withdrawn as far as any caller of this method is concerned.
        return mine if scoped else min(dropped, 1)

    def _route_memory_teach(self, observation: NavObservation) -> None:
        """AUTO-TEACH: offer this tick's MAP pose to the place graph.

        MAP, through the sanctioned seam, because that is RM-1's hard contract
        (``record_visit`` raises on anything else) and because it is the right
        answer: ODOM drifts without bound and an ODOM place graph describes a
        world that does not exist.

        Labels come from the mission's RESOLVED candidate — the instance the
        ladder actually committed to, not every phantom the frustum reported —
        so a keyframe is tagged with a place the robot went to on purpose.

        This runs on EVERY tick of an active mission, including searching ticks
        and including ``PoseHealth.LOST`` ones: RM-1 refuses a LOST pose and
        breaks the track itself, which is exactly the behaviour wanted (MAP jumps
        on recovery, so no edge may span it).
        """

        hook = self._route_memory
        if hook is None:
            return
        try:
            pose = _pose_in(observation, MAP_FRAME)
        except (AttributeError, TypeError, ValueError):
            return
        self._route_memory_tick += 1
        # Cached for the recovery hooks and the proposer, neither of which has an
        # observation in hand at the point it needs the pose.
        self._route_memory_robot_xy = (float(pose.x), float(pose.y))
        raw_now = observation.extras.get("time_s")
        if isinstance(raw_now, (int, float)) and not isinstance(raw_now, bool):
            self._route_memory_now_s = float(raw_now)
        labels: tuple[str, ...] = ()
        if self.mission is not None and self.mission.goal is not None:
            label = self.mission.metadata.get("candidate_label")
            if isinstance(label, str) and label.strip():
                labels = (label.strip(),)
        provider = observation.extras.get(POSE_PROVIDER_KEY)
        reanchored = hook.reanchored_from_provider(provider) if provider is not None else False
        if reanchored:
            # AUDIT_WAVE1_FABLE.md: prefer the provider's OWN correction event
            # over RM-1's distance backstop. A live chain is a list of MAP
            # snapshots taken before the jump; the robot's pose is now on the
            # other side of it, so the recorded geometry and the current estimate
            # no longer describe the same frame. RM-1 refuses to ROUTE over an
            # edge laid across a jump for exactly this reason — driving a chain
            # extracted across one would be the same claim by another door.
            self._flush_route_memory_waypoints("map_reanchor")
        try:
            keyframe = hook.record(
                pose,
                semantic_labels=labels,
                timestamp_tick=self._route_memory_tick,
                reanchored=reanchored,
            )
        except (TypeError, ValueError) as error:
            # A pose the contract refuses is a wiring bug in THIS method, not a
            # reason to take the mission down. Say so once, then stay out of the
            # way: the flag-off behaviour is the fallback.
            logger.warning("route_memory ingestion disabled this tick: %s", error)
            return
        if keyframe is not None:
            self.route_memory_keyframes += 1

    def _route_memory_goal_is_at_range(self) -> bool:
        """At-range (memory's problem) vs inside-obstacle (today's release path).

        Two independent readings, and BOTH must say at-range:

        * geometry — the committed goal is further than half the rolling window
          (:attr:`ROUTE_MEMORY_RANGE_M`), so the planner is not looking at the
          goal at all: ``RollingGridPlanner.plan`` clipped it to the window edge
          and planned somewhere else;
        * the planner's own last :class:`RoutePlan`, when it exposes one — a
          ``planning_target_world`` that differs from ``requested_goal_world`` IS
          that clip, stated by the planner rather than inferred.

        A goal that sits INSIDE the window and is still unroutable is a goal
        buried in an inflated obstacle. Memory has nothing to say about that: no
        remembered route ends anywhere the planner can now reach, and pretending
        otherwise would spend the mission's budget re-approaching a blocked cell.
        Those keep today's release path, unchanged.
        """

        if self.mission is None or self.mission.goal is None:
            return False
        robot_xy = self._route_memory_robot_xy
        if robot_xy is None:
            return False
        distance = math.hypot(
            self.mission.goal.x - robot_xy[0], self.mission.goal.y - robot_xy[1]
        )
        if distance <= self.ROUTE_MEMORY_RANGE_M:
            return False
        plan = getattr(self._navigator, "_last_plan", None)
        requested = getattr(plan, "requested_goal_world", None)
        target = getattr(plan, "planning_target_world", None)
        if requested is not None and target is not None:
            clipped = (
                abs(float(target[0]) - float(requested[0])) > 1e-9
                or abs(float(target[1]) - float(requested[1])) > 1e-9
            )
            return bool(clipped)
        # No RoutePlan surface (stub navigator, historical bundle): the geometry
        # reading stands on its own.
        return True

    def _arm_route_memory_chain(self, *, trigger: str) -> bool:
        """Ask memory for a route to the committed goal and, if it has one, arm it.

        Returns ``True`` only when a chain was obtained AND the waypoint it
        implies WON arbitration. Every other outcome — no commitment, goal inside
        the window, memory has no route, the arbiter vetoed, **memory already
        spent its one chain on this instance** — returns ``False``, and the
        caller then does exactly what it did before this card existed.

        The last of those is the livelock guard. A remembered route that has
        stopped advancing is retired by :meth:`_route_memory_hand_back`, and
        without this the very next unroutable tick would re-query memory, get the
        SAME recorded chain back, re-arm it, and defer the release again — a
        tight loop, at the ``UNROUTABLE_GOAL_STEPS`` cadence, whose only exit is
        the progress watchdog. With it, a retired chain gives the release back
        after :attr:`ROUTE_MEMORY_STALL_STEPS` + ``UNROUTABLE_GOAL_STEPS`` ticks.

        **What this does NOT say (AUDIT_WAVE2 finding 3).** It is *not* "one chain
        per committed instance". ``_route_memory_spent`` is keyed on the candidate
        id and cleared at every mission boundary, and — deliberately — the release
        funnel's own flush (``_begin_semantic_replan``, reason
        ``candidate_released``) does NOT mark the instance spent. So a 400-tick
        progress-watchdog replan that re-grounds and re-commits the SAME candidate
        gets a fresh chain, and a doomed world can therefore see the release
        postponed to the watchdog cadence rather than to the 120-tick bound above.

        That is a two-sided decision, taken on measured evidence and recorded in
        ``RM2_STATUS.md`` §5.4: marking the funnel's flush spent postpones nothing
        in the doomed world worth having, and in the adjacent RECOVERABLE world it
        converts a measured arrival (t=762, dtg 2.48 m — the second chain is the
        one that works) into a blacklist failure. The honest bound is not "one
        chain": it is that the deferral only ever suspends the release while a
        chain is ADVANCING, and that termination is guaranteed by the
        flag-INDEPENDENT ``progress_timeout_steps`` x ``max_semantic_replans``
        ladder, which route memory neither extends nor resets.
        """

        hook = self._route_memory
        if (
            hook is None
            or self.mission is None
            or self.mission.goal is None
            or self._route_memory_robot_xy is None
        ):
            return False
        if self._route_memory_commitment_key() in self._route_memory_spent:
            return False
        if not self._route_memory_goal_is_at_range():
            return False
        chain = hook.route(
            (self.mission.goal.x, self.mission.goal.y), self._route_memory_robot_xy
        )
        if not chain:
            # RM-1's fail-closed contract: () means "memory has no route", never
            # "maybe". Today's behaviour, verbatim.
            return False
        self.route_memory_routes_found += 1
        self._route_memory_chain = tuple(chain)
        self._route_memory_stamp = (self._active_task_id, self._active_plan_revision)
        self._route_memory_best_remaining_m = None
        self._steps_route_memory_stalled = 0
        self.mission.metadata["route_memory_trigger"] = str(trigger)
        armed = self._publish_route_memory_waypoint()
        if not armed:
            self._clear_route_memory_chain()
        return armed

    def _publish_route_memory_waypoint(self) -> bool:
        """Chain -> stamped SE2Goal -> arbiter -> interim target. The one door.

        Nothing else in this pipeline may write ``_route_memory_target``. The
        proposal is stamped with the pipeline's ACTIVE ``(task_id,
        plan_revision)`` exactly like the lock-on and grounder proposals, is
        published into the shared ``ProposerBus`` (so the P0-C flush can reach
        it), and is then resolved by ``goal_arbiter``. The arbiter's TTL, stale
        revision and LETHAL vetoes are applied unchanged and unweakened; a veto
        means no interim target, which means today's behaviour.

        The winner is stored as an interim NAVIGATION target and nothing else. It
        is not the mission goal, it is not written to ``self.mission.goal``, and
        no arrival predicate anywhere reads it.
        """

        hook = self._route_memory
        chain = self._route_memory_chain
        if (
            hook is None
            or not chain
            or self.mission is None
            or self.mission.goal is None
            or self._route_memory_robot_xy is None
            or not _HAS_INSTRUCTNAV
            or SE2Goal is None
            or self.proposer_bus is None
            or self.goal_arbiter is None
            or waypoint_goal_from_chain is None
            or GoalPose is None
        ):
            return False
        now_s = float(self._route_memory_now_s)
        proposed = waypoint_goal_from_chain(
            chain,
            robot_xy=self._route_memory_robot_xy,
            now_s=now_s,
            task_id=self._active_task_id,
            plan_revision=self._active_plan_revision,
            plan_step_id="align_then_translate",
            reach_radius_m=self.ROUTE_MEMORY_RANGE_M,
            final_heading_xy=(self.mission.goal.x, self.mission.goal.y),
        )
        if proposed is None:
            # The chain is spent: the robot stands on its last keyframe and the
            # rest is the planner's leg.
            self._route_memory_target = None
            return False
        self.route_memory_proposals += 1
        self.proposer_bus.publish(proposed)
        # Recorded HERE, at the publish, so a withdrawal can always find its own
        # entry no matter what the active key has become in the meantime
        # (AUDIT_WAVE2 finding 1).
        self._route_memory_published_task = str(proposed.task_id)
        self.goal_arbiter.set_plan_step(proposed.plan_step_id)
        chosen = self.goal_arbiter.resolve((proposed,), now_s=now_s)
        won = chosen is not None and chosen.source == proposed.source
        hook.note_proposal(won=won)
        if not won:
            self.route_memory_vetoes += 1
            self._route_memory_target = None
            self.mission.metadata["route_memory_waypoint_vetoed"] = True
            return False
        if not self._route_memory_chain or self._route_memory_stamp != (
            self._active_task_id,
            self._active_plan_revision,
        ):
            # A correction landed between ``resolve`` returning a winner and this
            # store. Writing the target now would leave it orphaned — an interim
            # target with no chain behind it and a stamp that no longer matches —
            # which is inert today only because ``_route_memory_navigate`` refuses
            # to drive without a chain. Fail closed instead of relying on that.
            self._route_memory_target = None
            self._withdraw_route_memory_proposal()
            return False
        self.route_memory_wins += 1
        assert chosen is not None and chosen.pose is not None
        x, y, yaw = chosen.pose
        self._route_memory_target = GoalPose(
            x=float(x),
            y=float(y),
            z=float(self.mission.goal.z),
            heading_deg=math.degrees(float(yaw)),
            poi_id="",
            label="route_memory_waypoint",
            # The keyframe arrival disc RM-1's spacing was derived from: two
            # consecutive keyframes are 0.50 m apart precisely so their 0.25 m
            # discs do not overlap, so 0.25 m is what "at this waypoint" means.
            arrival_radius_m=DEFAULT_WAYPOINT_REACHED_M,
        )
        self.mission.metadata["route_memory_waypoint"] = (float(x), float(y))
        self.mission.metadata["route_memory_chain_len"] = len(chain)
        self.mission.metadata.pop("route_memory_waypoint_vetoed", None)
        return True

    def _route_memory_partial_recovery(self) -> None:
        """RM-2 trigger (ii): prolonged non-progress on a CLIPPED (partial) plan.

        The beyond-window case never reaches ``_unroutable_goal_recovery`` at
        all, and that is the measured reason route memory could not have been
        "already wired": ``RollingGridPlanner.plan`` CLIPS a goal outside the
        window to the window edge and reports ``partial``, which is a perfectly
        healthy status. A robot pushing a partial plan into a wall reports
        ``partial`` forever while going nowhere, and the only thing that ever
        ends it today is the 200-tick progress watchdog failing the mission.

        So: ``partial`` + the commitment still grounded + the same non-progress
        hysteresis the unroutable path uses. Never returns a command; it only
        arms the chain, and the tick continues exactly as it would have.
        """

        if (
            self._route_memory is None
            or self.mission is None
            or self.mission.goal is None
            or self.mission.semantic_goal is None
            # A LIVE chain, not merely a live waypoint: on the one tick a
            # hand-back probe is in flight the target is None while the chain is
            # very much still running, and re-arming there would silently
            # overwrite the probe.
            or self._route_memory_chain
        ):
            return
        status = getattr(self._navigator, "last_route_status", None)
        if status != "partial":
            return
        if self._steps_without_progress < self.UNROUTABLE_GOAL_STEPS:
            return
        self._route_memory_defer_release(trigger="partial_non_progress")

    def _route_memory_navigate(
        self, plan_observation: NavObservation
    ) -> MidLevelCommand:
        """CONSUMPTION: drive the interim waypoint when one is live, else normally.

        The navigator is handed a PROXY :class:`Mission` whose ``goal`` is the
        interim waypoint. ``self.mission`` is not touched — its ``goal`` is still
        the committed approach pose, its ``arrival_goal_region`` is still the K0
        region built from the real target, and ``_inside_arrival_goal_region``
        (evaluated by the caller against the real mission, every tick, including
        these ticks) is still the only thing that can claim an arrival.

        Reaching the waypoint therefore CANNOT be an arrival: the proxy's
        ``arrived`` status and the navigator's ``stop`` are consumed here and
        converted into "advance the chain", and the command handed back is
        non-terminal.
        """

        assert self.mission is not None
        if not self._route_memory_chain:
            return self._navigator.act(plan_observation, self.mission)
        if self._route_memory_stale():
            self._flush_route_memory_waypoints("stale_revision")
            return self._navigator.act(plan_observation, self.mission)
        # --- the hand-back PROBE ------------------------------------------
        # Earlier ticks handed the navigator the TRUE goal to see whether normal
        # planning can reach it now. The verdict is the planner's, and it is only
        # read once the planner has actually PLANNED for that goal — see
        # ``_route_memory_probe_verdict``.
        if self._route_memory_probing:
            budget = self._route_memory_probe_budget()
            self._steps_route_memory_probing += 1
            held_out = self._steps_route_memory_probing >= budget
            verdict = self._route_memory_probe_verdict(held_out=held_out)
            if verdict is None:
                if not held_out:
                    # The planner has not answered about the TRUE goal yet — its
                    # plan in hand is still the waypoint's. Hold the probe: keep
                    # handing it the true goal, tick after tick, until it plans
                    # for it or the budget is out.
                    return self._navigator.act(plan_observation, self.mission)
                # Held out with a RoutePlan surface that never once named the
                # probed goal: this planner is suppressing replans (a committed
                # detour). Fail closed — REFUTED is the answer that loses
                # nothing, because the chain keeps running and normal planning
                # still owns whatever leg is left at the end of it.
                self.mission.metadata["route_memory_probe"] = "timeout"
                verdict = False
            self._route_memory_probing = False
            self._steps_route_memory_probing = 0
            if verdict:
                # Routable again: memory is done, and the mission finishes the
                # way it always would have.
                self.route_memory_handbacks += 1
                self.mission.metadata["route_memory_handback"] = "goal_routable"
                self._clear_route_memory_chain()
                return self._navigator.act(plan_observation, self.mission)
            # Refuted. In RANGE is not the same as ROUTABLE -- the goal can be
            # 7 m away with the barrier still between. Probe once per chain, so
            # a refuted probe cannot become a one-tick-on/one-tick-off
            # oscillation between the two goals; the chain now simply runs to
            # exhaustion and normal planning owns whatever is left.
            self.mission.metadata.setdefault(
                "route_memory_probe",
                str(getattr(self._navigator, "last_route_status", None)),
            )
            self._route_memory_probe_refuted = True
        if self._route_memory_target is None and not self._publish_route_memory_waypoint():
            # Chain spent (or vetoed): the remaining leg is the planner's, and
            # memory's turn on this instance is over. Re-querying would hand back
            # the same recorded route — the graph has not changed — so the
            # commitment is marked spent and today's release path becomes
            # reachable again (the livelock guard; see ``_arm_route_memory_chain``).
            self.route_memory_handbacks += 1
            self._route_memory_spent.add(self._route_memory_commitment_key())
            self.mission.metadata.setdefault("route_memory_handback", "chain_spent")
            self.mission.metadata["route_memory_spent"] = sorted(self._route_memory_spent)
            self._clear_route_memory_chain()
            return self._navigator.act(plan_observation, self.mission)
        if self._route_memory_hand_back():
            return self._navigator.act(plan_observation, self.mission)
        assert self._route_memory_target is not None
        proxy = Mission(
            directive=self.mission.directive,
            goal=self._route_memory_target,
            status="running",
            semantic_goal=self.mission.semantic_goal,
            metadata=self.mission.metadata,
        )
        cmd = self._navigator.act(plan_observation, proxy)
        self.route_memory_chain_ticks += 1
        if not (cmd.stop or proxy.status == "arrived"):
            return cmd
        # The waypoint is reached. Re-derive the next one from the SAME recorded
        # chain and hold this tick; the next tick drives on. Whatever happens,
        # ``stop`` is dropped: an interim waypoint is not an arrival.
        self._publish_route_memory_waypoint()
        return MidLevelCommand(
            vx=0.0, vy=0.0, vyaw=0.0, stop=False, note="route_memory_waypoint_reached"
        )

    def _route_memory_stale(self) -> bool:
        """A chain authored under a superseded revision can never be driven."""

        if self._route_memory_stamp != (self._active_task_id, self._active_plan_revision):
            return True
        if self.goal_arbiter is None:
            return False
        committed = getattr(self.goal_arbiter, "committed_revision", None)
        if not callable(committed):
            return False
        return int(committed(self._active_task_id)) > int(self._active_plan_revision)

    def _route_memory_hand_back(self) -> bool:
        """Start a hand-back probe, or retire a chain that has stopped advancing.

        Two retirement conditions, both structural:

        * **the true goal came back into range** — it is inside half the rolling
          window again, so the planner has live occupancy for it. That is a
          NECESSARY condition for handing back, not a sufficient one: a goal 7 m
          away with the barrier still between it and the robot is in range and
          not routable. So this arms a PROBE — the true goal is handed to the
          planner and HELD there until the planner has demonstrably planned for
          it (``_route_memory_probe_verdict`` / ``_route_memory_probe_budget``,
          AUDIT_WAVE2 finding 2), not for one tick. Exactly one probe per chain;
        * **the chain stopped advancing** for :attr:`ROUTE_MEMORY_STALL_STEPS`
          ticks. "Active AND advancing" is the condition under which the release
          is deferred, so the moment the second half stops being true the
          deferral ends and today's release path resumes.
        """

        if self.mission is None or self.mission.goal is None:
            return True
        robot_xy = self._route_memory_robot_xy
        if robot_xy is None:
            return True
        distance = math.hypot(
            self.mission.goal.x - robot_xy[0], self.mission.goal.y - robot_xy[1]
        )
        if distance <= self.ROUTE_MEMORY_RANGE_M and not self._route_memory_probe_refuted:
            self._route_memory_probing = True
            self._steps_route_memory_probing = 0
            self._route_memory_target = None
            self.mission.metadata.pop("route_memory_probe", None)
            self.mission.metadata["route_memory_handback"] = "probing"
            return True
        remaining = self._route_memory_remaining_m()
        if remaining is None:
            self._clear_route_memory_chain()
            return True
        best = self._route_memory_best_remaining_m
        if best is None or remaining < best - 0.025:
            # Same 25 mm quantum ``_progress_watchdog`` uses for "real closing of
            # the gap"; one threshold for progress, not two.
            self._route_memory_best_remaining_m = remaining
            self._steps_route_memory_stalled = 0
            return False
        self._steps_route_memory_stalled += 1
        if self._steps_route_memory_stalled < self.ROUTE_MEMORY_STALL_STEPS:
            return False
        # Retirement, and the end of memory's turn on this instance. The route
        # was recorded, it was driven, and it did not get the robot anywhere:
        # marking the commitment spent is what lets ``_unroutable_goal_recovery``
        # reach its release again instead of re-arming the same dead chain until
        # the progress watchdog kills the mission.
        self.route_memory_handbacks += 1
        self._route_memory_spent.add(self._route_memory_commitment_key())
        self.mission.metadata["route_memory_handback"] = "chain_stalled"
        self.mission.metadata["route_memory_spent"] = sorted(self._route_memory_spent)
        self._clear_route_memory_chain()
        return True

    def _route_memory_probe_budget(self) -> int:
        """Ticks a hand-back probe may hold the true goal waiting for a real plan.

        Derived, twice over. ``GridNavigator`` replans on its OWN cadence
        (``replan_interval_steps``) and **never because the goal changed**
        (``grid_navigator.py``'s ``should_replan``), so one cadence period is the
        smallest hold that can contain a plan computed for the probed goal, and
        two gives a whole period of slack for the phase the probe happened to be
        armed on. The period is read off the navigator when it publishes one and
        falls back to :attr:`GRID_REPLAN_INTERVAL_STEPS`, the value every shipping
        model config pins.

        This is the fail-closed timeout, not the mechanism: a planner that has
        replanned for the true goal is detected immediately by
        :meth:`_route_memory_probe_verdict` and the hold ends early.
        """

        interval = getattr(self._navigator, "replan_interval_steps", None)
        if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
            interval = self.GRID_REPLAN_INTERVAL_STEPS
        return 2 * int(interval)

    def _route_memory_probe_verdict(self, *, held_out: bool) -> bool | None:
        """``True`` routable, ``False`` refuted, ``None`` the planner has not answered.

        **AUDIT_WAVE2 finding 2.** The probe used to be a single tick: hand the
        navigator the true goal once, read ``last_route_status`` next tick. That
        read is not a verdict about the true goal. ``GridNavigator`` replans on
        its own 5-tick cadence and **not** because the goal changed, and
        suppresses replans entirely under a committed detour, so the status the
        probe read was usually the CACHED WAYPOINT plan's — and a cached
        ``planned`` was taken as "the true goal is routable again", destroying the
        chain the moment the goal entered the 8.05 m disc while it was still
        walled off, in exactly the scenario class this card exists to win.
        Measured: 5 of 5 cadence phases produced a false hand-back and a mission
        that failed at dtg 9.10 m where a per-tick-replanning stand-in arrived.

        ``goal_routable`` is now returned only on a DEMONSTRABLE verdict, of which
        there are exactly two kinds:

        1. the planner publishes a :class:`RoutePlan` whose
           ``requested_goal_world`` is the goal being probed — the same field
           :meth:`_route_memory_goal_is_at_range` already reads. That is the
           planner saying, itself, which goal the status is about, and it ends the
           hold immediately;
        2. the planner publishes no ``RoutePlan`` at all (stub navigator,
           historical bundle) **and** the probe has been held for its full budget,
           i.e. at least two of the shipping cadence's periods of consecutive
           true-goal acts, after which no cadenced planner can still be answering
           about the waypoint.

        Everything else is ``None`` — "ask again" — and a ``None`` that survives
        the budget fails closed to REFUTED. Every path here is biased toward
        KEEPING the chain, which is the direction that cannot destroy a route the
        robot has actually driven.
        """

        status = getattr(self._navigator, "last_route_status", None)
        if status is None:
            return None
        if self.mission is not None and self.mission.goal is not None:
            plan = getattr(self._navigator, "_last_plan", None)
            requested = getattr(plan, "requested_goal_world", None)
            if requested is not None:
                planned_for_the_probe = (
                    abs(float(requested[0]) - self.mission.goal.x) <= 1e-9
                    and abs(float(requested[1]) - self.mission.goal.y) <= 1e-9
                )
                return (status in {"planned", "at_goal"}) if planned_for_the_probe else None
        if not held_out:
            return None
        return status in {"planned", "at_goal"}

    def _route_memory_remaining_m(self) -> float | None:
        """Recorded distance still to travel along the live chain, or ``None``."""

        chain = self._route_memory_chain
        robot_xy = self._route_memory_robot_xy
        if not chain or robot_xy is None or chain_length_m is None:
            return None
        best_i = 0
        best_d = float("inf")
        for i, keyframe in enumerate(chain):
            d = math.hypot(keyframe.x - robot_xy[0], keyframe.y - robot_xy[1])
            if d < best_d:
                best_d = d
                best_i = i
        return best_d + chain_length_m(chain[best_i:])

    #: Ceiling on the ``Z_r`` term one pose estimate may add to every proximity
    #: threshold on one tick. A localizer that reports a 10 m sigma is broken,
    #: and the fail-closed answer to *that* is the pose-health path
    #: (``PoseHealth.LOST`` already refuses arrival claims), not a 10 m
    #: stopping envelope that would freeze the robot with no way back. Bounded
    #: on the *widening* only: the term can never shrink a threshold.
    MAX_POSE_UNCERTAINTY_M = 1.0

    def pose_aware_collision_policy(self, observation: NavObservation) -> CollisionPolicy:
        """This tick's :class:`CollisionPolicy`, widened by ISO/TS-15066 ``Z_r``.

        Lane B's hand-off, wired: ``PoseEstimate.position_sigma_m``
        (``sqrt(sigma_xx + sigma_yy)``) is exactly the scalar
        :attr:`~parcel_robot.authority.SafetyEnvelope.pose_uncertainty_m`
        expects, and ``stop_distance(v)`` carries it as an additive term:

            ``stop_distance(v) = r_foot + v*tau + v^2/(2a) + Z_s + Z_r``

        So a pose that is uncertain by ``sigma`` moves every proximity boundary
        out by exactly ``sigma``, and that is what this returns: the configured
        policy with ``sigma`` added to each of the four distances. Adding the
        same term to a stop and its slow band preserves ``stop < slow``, so the
        policy still validates, and the transformation is monotone — it can
        only ever brake earlier, never later.

        **Inert at sigma = 0, by construction and by assertion.** With the
        shipping :class:`~parcel_robot.pose.TruthPoseProvider` the covariance is
        exactly zero, ``sigma`` is exactly ``0.0``, and this returns
        ``self.collision`` — the *same object*, so the equality is identity, not
        a float comparison. Every existing measurement, frozen row and eval
        digest is therefore untouched; ``tests/test_pose_uncertainty_envelope.py``
        pins both halves (identity at zero, widening under a drift provider).

        MAP frame: ``Z_r`` is the uncertainty of the robot's position in the
        world, which is a MAP-frame quantity. ODOM is smooth-but-drifting by
        construction and its covariance is not the one this term is about.
        """

        sigma = self._pose_uncertainty_m(observation)
        if sigma <= 0.0:
            return self.collision
        return replace(
            self.collision,
            person_stop_m=self.collision.person_stop_m + sigma,
            person_slow_m=self.collision.person_slow_m + sigma,
            obstacle_stop_m=self.collision.obstacle_stop_m + sigma,
            obstacle_slow_m=self.collision.obstacle_slow_m + sigma,
        )

    def _pose_uncertainty_m(self, observation: NavObservation) -> float:
        """``Z_r`` for this tick: bounded, non-negative, 0.0 when unavailable."""

        try:
            sigma = float(_pose_in(observation, MAP_FRAME).position_sigma_m)
        except (AttributeError, TypeError, ValueError):
            # Pre-seam bundle poses and legacy stubs expose no covariance at
            # all. Absent evidence of uncertainty is reported as absent, which
            # is the pre-wiring behaviour exactly.
            return 0.0
        if not math.isfinite(sigma) or sigma <= 0.0:
            return 0.0
        return min(sigma, self.MAX_POSE_UNCERTAINTY_M)

    def _target_missing_command(self) -> MidLevelCommand:
        """The ladder is exhausted — say *why*, not just "not found".

        A mission that released one or more instances as unreachable did not
        fail to find the thing; it found it and could not get to it. Reporting
        that as ``semantic_target_not_found`` would make the release path
        (which exists precisely so a reachable alternate gets its chance) look
        like a perception failure in every single-instance scene. Unchanged for
        every mission that never released anything, which is all of them
        until one of the three release authorities fires.
        """

        note = (
            "semantic_target_unreachable"
            if self._unreachable_candidates
            else "semantic_target_not_found"
        )
        return MidLevelCommand(stop=True, note=note)

    def _release_unreachable_candidate(
        self,
        candidate_id: str,
        *,
        note: str,
    ) -> MidLevelCommand:
        """Drop one instance this mission has proved it cannot reach, and rescan.

        The single exit for every "I have proof this instance is not reachable
        from here" authority: A* (``_unroutable_goal_recovery``), the obstacle
        gate (``_gate_blocked_route_recovery``), and the approach solver
        (``_commit_semantic_candidate`` with a ``None`` pose). One release, one
        per-mission memory, one exclusion door, one replan budget — three
        authorities with three different ladders is the D5 defect class.

        Remembering the instance is what makes it converge: the watchdog's own
        replan re-grounds from the same frustum and re-derives the byte-identical
        commitment, which is exactly the loop this exists to break.
        """

        assert self.mission is not None
        if candidate_id:
            self._unreachable_candidates.add(candidate_id)
            self.mission.metadata["unreachable_candidates"] = sorted(
                self._unreachable_candidates
            )
        replans = int(self.mission.metadata.get("replan_count", 0))
        if replans < self.max_semantic_replans:
            return self._begin_semantic_replan(replans, note=note)
        # The ladder is spent. Fail honestly, and name the actual reason:
        # every instance this mission could ground was unreachable from here.
        self.mission.status = "failed"
        self.mission.metadata["resolution_state"] = "unreachable"
        self.mission.metadata["plan_step"] = "failed"
        return MidLevelCommand(stop=True, note="semantic_target_unreachable")

    def release_current_candidate(self, reason: str) -> bool:
        """Release the committed target and replan — the runtime's N20 entry point.

        The ONE place outside the navigator's own tick that may drive the single
        release door (:meth:`_release_unreachable_candidate`). The runtime's
        yield policy calls it when patience expires on a person-blocked approach:
        the committed approach pose is held behind a person who will not clear
        it, and the mission may have an alternative to try — another instance, or
        the same target re-approached after a re-ground — before it ends. It
        reuses the SAME exclusion door A* (``_unroutable_goal_recovery``), the
        obstacle gate (``_gate_blocked_route_recovery``) and the approach solver
        (a ``None`` pose) use, so there is exactly ONE release authority and no
        second person-stop dwell counter living in a second tree — the D5 defect
        class N20 was filed to respect. ``person_stop`` remains untouched as a
        motion gate: this method never sees or proposes a velocity, it only
        drops a commitment the runtime has proved (via its patience budget) is
        not going to clear.

        Returns ``True`` when the mission CONTINUES — the replan budget had room,
        so the resolution ladder will now look for an alternative — and
        ``False`` when the release exhausted that budget and the mission ended
        honestly (no alternative left to try, ``semantic_target_unreachable``).
        A no-op returning ``False`` when there is no active semantic mission with
        a committed target to release.
        """

        if (
            self.mission is None
            or self.mission.semantic_goal is None
            or self.mission.goal is None
        ):
            return False
        candidate_id = str(self.mission.metadata.get("candidate_id") or "")
        self.mission.metadata["yield_release_reason"] = str(reason)
        self._release_unreachable_candidate(
            candidate_id, note="semantic_replan_after_person_block"
        )
        # The door either began a replan (status 'searching' → the mission
        # continues) or spent the ladder and failed honestly (status 'failed').
        return self.mission is not None and self.mission.status != "failed"

    #: Consecutive ticks the local obstacle gate may hard-stop translation,
    #: with zero goal progress, before the mission accepts that as proof that
    #: the route it is holding cannot be executed by this body. Same 6.0 s at
    #: 10 Hz, and the same reasoning, as :attr:`UNROUTABLE_GOAL_STEPS`.
    GATE_BLOCKED_ROUTE_STEPS = 60

    #: Displacement that counts as the body having MOVED while the obstacle gate
    #: was hard-stopping it (card A2). One cell of the shipped 0.10 m planner
    #: grid, and comfortably above the largest single-update MAP correction
    #: NAV-CORE measured over 120 episodes (0.029 m, median 0.009 m), so
    #: localisation noise alone cannot masquerade as escape and reset the
    #: release the way goal jitter used to.
    GATE_HOLD_DISPLACEMENT_M = 0.10

    def _update_body_stillness(self, observation: NavObservation) -> None:
        """Set :attr:`_body_is_still` — did the body travel, this stretch of ticks?

        Card A2 (NAV-GLUE) fix 3.4, and the one witness both release paths now
        use. Both used to ask ``_steps_without_progress``, i.e. "is the distance
        to the goal still falling", and NAV-CORE measured what that costs
        off-oracle: a semantic goal is re-estimated from a detector that
        scatters 0.15 m per axis, so the watchdog's running minimum keeps
        ratcheting down while the body stands still. Over a fully stopped
        900-tick arm-A episode ``_steps_gate_blocked`` peaked at FOUR against a
        60-tick release, and the ``goal_blocked`` release never fired at all
        through 778 ticks of in-place recovery yaw.

        The body cannot be talked out of its own displacement. MAP, not ODOM:
        the anchor has to survive hundreds of ticks, so it needs the globally
        consistent frame for the same reason ``_progress_watchdog`` does, and
        the threshold sits an order of magnitude above the largest single-update
        MAP correction NAV-CORE measured (0.029 m over 120 episodes).
        """

        robot_map = _pose_in(observation, MAP_FRAME)
        here = (robot_map.x, robot_map.y)
        anchor = self._gate_blocked_anchor_xy
        if anchor is None:
            self._gate_blocked_anchor_xy = here
            self._body_is_still = True
            return
        if math.hypot(here[0] - anchor[0], here[1] - anchor[1]) > self.GATE_HOLD_DISPLACEMENT_M:
            self._gate_blocked_anchor_xy = here
            self._body_is_still = False
            return
        self._body_is_still = True

    def _gate_blocked_route_recovery(
        self,
        observation: NavObservation,
    ) -> MidLevelCommand | None:
        """Release a commitment the *safety gate* has proved unexecutable.

        Sibling of :meth:`_unroutable_goal_recovery`, and the same defect: the
        mission holding a plan it already has proof it cannot execute. There
        the proof comes from A* ("no traversable cell in the goal region");
        here it comes from the obstacle gate, and the disagreement that
        produces it is measurable:

        * the global planner inflates obstacles by ``inflation_radius_m``
          (0.42 m at the shipping config), so a route may bring the body to
          0.10 m of an observed surface and still report ``planned``;
        * the collision gate hard-stops translation at
          ``CollisionPolicy.obstacle_stop_m`` (0.8 m footprint-to-surface,
          i.e. 1.12 m centre-to-surface).

        A corridor between those two numbers is *routable and impassable*.
        Measured 2026-08-07, "sit next to the lamppost", static city: the
        A\\* route from (0,0) to the committed pose passes 0.71 m from
        ``obstacle_bollard``'s centre; the body decelerates under the
        projected speed cap and parks at exactly 0.800 m from its surface with
        ``status=planned|obstacle_stop``, ``vx=0``, for 190 ticks, until the
        progress watchdog fails the mission — whose replan re-grounds the same
        instance and re-derives the same route. Zero displacement after the
        first 0.6 m.

        The gate is not touched, weakened, or second-guessed: it is *believed*.
        What changes is that six seconds of "my own gate will not let me
        execute this, and I am no nearer than I was" now releases the
        commitment instead of spending the whole watchdog budget on it. The
        released instance is remembered exactly as an unroutable one is, so
        the rescan cannot re-commit it, and the ladder's own budget still
        bounds the whole thing.

        Returns ``None`` on every tick that is not this case.
        """

        if self.mission is None or self.mission.semantic_goal is None:
            return None
        if self._steps_gate_blocked < self.GATE_BLOCKED_ROUTE_STEPS:
            return None
        # Card A2: the stale-count re-read used to be ``_steps_without_progress
        # == 0``, and it shared the defect that pinned the counter at four — a
        # jittering semantic goal could reset it on the very tick the release
        # was due. The counter now advances only on ticks the BODY did not
        # travel, so it is its own proof and needs no second opinion here.
        replanned = self._retry_committed_terminal_pose(
            observation,
            trigger="obstacle_stop",
        )
        if replanned is not None:
            return replanned

        self.mission.metadata["blocked_route_gate"] = "obstacle_stop"
        self.mission.metadata["gate_blocked_steps"] = int(self._steps_gate_blocked)
        return self._release_unreachable_candidate(
            str(self.mission.metadata.get("candidate_id") or ""),
            note="semantic_replan_after_blocked_route",
        )

    def _begin_semantic_replan(self, replans: int, *, note: str) -> MidLevelCommand:
        assert self.mission is not None and self.mission.semantic_goal is not None
        # VS-4: the single replan funnel is also the single place a verify
        # session dies. A released commitment must never leave a session
        # verifying against a reference the mission no longer holds — including
        # the ~8-12 m visible-but-unroutable release the grid planner produces.
        if self.lock_on_verify_on_approach:
            self._end_lock_on_verify()
        # RM-2: the single release funnel is also the single place a route-memory
        # chain dies. Every release authority (A*, the obstacle gate, the
        # approach solver, the runtime's ``release_current_candidate``) arrives
        # here, and a chain that outlived the commitment it was derived for would
        # keep driving the navigator toward a waypoint on the way to a goal this
        # mission no longer holds.
        if self._route_memory is not None:
            self._flush_route_memory_waypoints("candidate_released")
        self.mission.goal = None
        self.mission.status = "searching"
        self.mission.metadata.update(
            {
                "replan_count": replans + 1,
                "resolution_state": note,
                "plan_step": "confirm_target_from_camera_depth",
            }
        )
        self.search.reset()
        if self.scan_behavior is not None:
            self.scan_behavior.reset()
        self._best_goal_distance_m = None
        self._steps_without_progress = 0
        self._steps_goal_unroutable = 0
        self._steps_gate_blocked = 0
        self._gate_blocked_anchor_xy = None
        self._terminal_verification_steps = 0
        self._recovery_phase = "frustum"
        self._scan_steps = 0
        self._frontier_steps = 0
        self._already_scanned = False
        self._already_searched = False
        self._frontier_target = None
        self._frontier_viewpoints = []
        return MidLevelCommand(note=note)

    def _step_terminal_verification(
        self,
        observation: NavObservation,
        *,
        entering: bool = False,
    ) -> MidLevelCommand:
        """Hold zero until both the live relation and physical stop are true."""

        assert self.mission is not None and self.mission.semantic_goal is not None
        relation_verified = self._semantic_arrival_verified(observation)
        self.mission.metadata["terminal_relation_verified"] = relation_verified
        if _motion_feedback_is_settled(observation):
            if relation_verified:
                if self._owner_face_turn_required():
                    return self._begin_owner_face_turn(observation)
                self.mission.status = "arrived"
                self.mission.metadata["resolution_state"] = "verified"
                self.mission.metadata["plan_step"] = "completed"
                return MidLevelCommand(stop=True, note="arrived_verified")
            replans = int(self.mission.metadata.get("replan_count", 0))
            if replans < self.max_semantic_replans:
                return self._begin_semantic_replan(
                    replans,
                    note="semantic_replan_after_verification_failure",
                )
            self.mission.status = "failed"
            self.mission.metadata["resolution_state"] = "verification_failed"
            self.mission.metadata["plan_step"] = "failed"
            return MidLevelCommand(stop=True, note="semantic_arrival_verification_failed")

        self._terminal_verification_steps += 1
        if self._terminal_verification_steps >= self.terminal_stop_timeout_steps:
            self.mission.status = "failed"
            self.mission.metadata["resolution_state"] = "stop_not_confirmed"
            self.mission.metadata["plan_step"] = "failed"
            return MidLevelCommand(stop=True, note="terminal_stop_not_confirmed")
        return MidLevelCommand(
            stop=True,
            note=(
                "semantic_stop_requested" if entering else "semantic_waiting_for_stop_confirmation"
            ),
        )

    def _owner_face_turn_required(self) -> bool:
        mission = self.mission
        return bool(
            mission is not None
            and mission.semantic_goal is not None
            and str(getattr(mission.semantic_goal, "face", "") or "")
            == ARRIVAL_FACE_OWNER
            and mission.metadata.get("owner_face_phase") != "complete"
        )

    def _owner_face_turn_active(self) -> bool:
        return bool(
            self._owner_face_turn_required()
            and self.mission is not None
            and self.mission.metadata.get("owner_face_phase") == "turning"
        )

    def _begin_owner_face_turn(self, observation: NavObservation) -> MidLevelCommand:
        """Latch a verified target-facing arrival, then commission yaw only."""

        assert self.mission is not None and self.mission.goal is not None
        robot_map = _pose_in(observation, MAP_FRAME)
        owner = self._owner_xy(observation)
        if not robot_map.is_healthy:
            return self._fail_owner_face_turn("owner_face_pose_unhealthy")
        if observation.extras.get("perception_fresh") is not True:
            return self._fail_owner_face_turn("owner_face_pose_stale")
        if not _motion_feedback_is_fresh(observation):
            return self._fail_owner_face_turn("owner_face_feedback_stale")
        if owner is None:
            return self._fail_owner_face_turn("owner_face_owner_lost")

        anchor = (float(robot_map.x), float(robot_map.y))
        heading = self._owner_heading_deg(anchor, owner)
        if heading is None:
            return self._fail_owner_face_turn("owner_face_owner_coincident")
        phase_a_goal = self.mission.goal
        self.mission.goal = replace(
            phase_a_goal,
            x=anchor[0],
            y=anchor[1],
            heading_deg=heading,
        )
        self.mission.metadata.update(
            {
                "owner_face_phase": "turning",
                "owner_face_phase_a_verified": True,
                "owner_face_phase_a_goal": (
                    float(phase_a_goal.x),
                    float(phase_a_goal.y),
                    float(phase_a_goal.heading_deg),
                ),
                "owner_face_anchor_xy": anchor,
                "owner_face_target_heading_deg": heading,
                "owner_face_turn_steps": 0,
                "owner_face_turn_budget_steps": self._owner_face_turn_budget_steps(),
                "plan_step": "face_owner_after_verified_arrival",
            }
        )
        self.mission.status = "running"
        self._terminal_verification_steps = 0
        self._navigator.reset(self.mission)
        return MidLevelCommand(note="owner_face_turn_started")

    def _step_owner_face_turn(self, observation: NavObservation) -> MidLevelCommand:
        """Run Phase B through the normal controller, permitting yaw only."""

        assert self.mission is not None and self.mission.goal is not None
        reason = self._owner_face_guard_reason(observation)
        if reason is not None:
            return self._fail_owner_face_turn(reason)
        owner = self._owner_xy(observation)
        robot_map = _pose_in(observation, MAP_FRAME)
        assert owner is not None
        heading = self._owner_heading_deg(robot_map.xy, owner)
        if heading is None:
            return self._fail_owner_face_turn("owner_face_owner_coincident")
        self.mission.goal = replace(self.mission.goal, heading_deg=heading)
        self.mission.metadata["owner_face_target_heading_deg"] = heading

        if self._owner_face_completion_ready(observation, heading):
            return self._complete_owner_face_turn(observation, owner)
        command = self._navigator.act(self._control_observation(observation), self.mission)
        try:
            proposed_vx = float(command.vx)
            proposed_vy = float(command.vy)
            proposed_vyaw = float(command.vyaw)
        except (TypeError, ValueError, OverflowError):
            return self._fail_owner_face_turn("owner_face_command_invalid")
        if (
            not math.isfinite(proposed_vx)
            or not math.isfinite(proposed_vy)
            or abs(proposed_vx) > 1e-9
            or abs(proposed_vy) > 1e-9
        ):
            return self._fail_owner_face_turn("owner_face_translation_proposed")
        if not math.isfinite(proposed_vyaw):
            return self._fail_owner_face_turn("owner_face_yaw_non_finite")
        try:
            max_vyaw = float(self.safety.get("max_vyaw", 1.5))
        except (TypeError, ValueError, OverflowError):
            return self._fail_owner_face_turn("owner_face_yaw_limit_invalid")
        if not math.isfinite(max_vyaw) or max_vyaw < 0.0:
            return self._fail_owner_face_turn("owner_face_yaw_limit_invalid")
        bounded_vyaw = max(-max_vyaw, min(max_vyaw, proposed_vyaw))
        if bounded_vyaw != proposed_vyaw:
            self.mission.metadata["owner_face_yaw_clamped"] = True
            self.mission.metadata["owner_face_proposed_vyaw"] = proposed_vyaw
            self.mission.metadata["owner_face_max_vyaw"] = max_vyaw
        steps = int(self.mission.metadata.get("owner_face_turn_steps", 0)) + 1
        self.mission.metadata["owner_face_turn_steps"] = steps
        budget = int(self.mission.metadata.get("owner_face_turn_budget_steps", 0))
        if budget <= 0 or steps >= budget:
            return self._fail_owner_face_turn("owner_face_turn_timeout")
        if command.stop or self.mission.status == "arrived":
            self.mission.status = "verifying"
            return MidLevelCommand(stop=True, note="owner_face_waiting_for_stop_confirmation")
        self.mission.status = "running"
        return replace(command, vx=0.0, vy=0.0, vyaw=bounded_vyaw, stop=False)

    def _owner_face_guard_reason(self, observation: NavObservation) -> str | None:
        assert self.mission is not None and self.mission.semantic_goal is not None
        robot_map = _pose_in(observation, MAP_FRAME)
        if not robot_map.is_healthy:
            return "owner_face_pose_unhealthy"
        if observation.extras.get("perception_fresh") is not True:
            return "owner_face_pose_stale"
        if not _motion_feedback_is_fresh(observation):
            return "owner_face_feedback_stale"
        if self._owner_xy(observation) is None:
            return "owner_face_owner_lost"
        anchor = _finite_xy(self.mission.metadata.get("owner_face_anchor_xy"))
        if anchor is None:
            return "owner_face_anchor_invalid"
        if math.hypot(robot_map.x - anchor[0], robot_map.y - anchor[1]) > 0.02:
            return "owner_face_translation_detected"
        relation = self.mission.semantic_goal.terminal_relation
        if not self._terminal_environment_is_clear(observation, relation=relation):
            return "owner_face_environment_invalidated"
        if not self._owner_face_k0_geometry_holds(robot_map):
            return "owner_face_geometry_invalidated"
        return None

    def _owner_face_k0_geometry_holds(self, robot_map: Any) -> bool:
        assert self.mission is not None and self.mission.semantic_goal is not None
        region = self._arrival_goal_region()
        if region is None:
            return False
        relation = self.mission.semantic_goal.terminal_relation
        if relation == "inside":
            polygon = getattr(region, "polygon", None)
            if not polygon:
                return False
            clearance = float(
                self.mission.metadata.get(
                    "terminal_clearance_m", ROBOT_FOOTPRINT_RADIUS_M
                )
            )
            return self._inside_polygon_verified(
                robot_map,
                tuple((float(x), float(y)) for x, y in polygon),
                clearance,
            )
        if not region.contains(
            robot_map.x,
            robot_map.y,
            anchor_covariance=self._arrival_anchor_covariance(),
            probability_threshold=self.inside_probability_threshold,
        ):
            return False
        return relation != "near" or self._on_support_surface(robot_map.x, robot_map.y)

    def _owner_face_completion_ready(
        self,
        observation: NavObservation,
        target_heading_deg: float,
    ) -> bool:
        robot_map = _pose_in(observation, MAP_FRAME)
        tolerance = float(getattr(self._navigator, "align_exit_deg", 7.0))
        error = abs(_wrapped_degrees(target_heading_deg - math.degrees(robot_map.yaw)))
        return error <= tolerance and _motion_feedback_is_settled(observation)

    def _owner_face_turn_budget_steps(self) -> int:
        """A controller-derived full-turn bound plus the stop-settle budget."""

        rate = max(0.1, float(getattr(self._navigator, "max_yaw_rate", 0.8)))
        accel = max(0.1, float(getattr(self._navigator, "max_yaw_accel", 1.6)))
        dt = max(0.01, float(getattr(self._navigator, "control_dt_s", 0.1)))
        cruise = math.ceil(math.pi / (rate * dt))
        ramps = 2 * math.ceil(rate / (accel * dt))
        return int(cruise + ramps + self.terminal_stop_timeout_steps)

    @staticmethod
    def _owner_heading_deg(
        robot_xy: tuple[float, float],
        owner_xy: tuple[float, float],
    ) -> float | None:
        dx = owner_xy[0] - robot_xy[0]
        dy = owner_xy[1] - robot_xy[1]
        if math.hypot(dx, dy) <= 1e-9:
            return None
        return math.degrees(math.atan2(dy, dx))

    def _complete_owner_face_turn(
        self,
        observation: NavObservation,
        owner_xy: tuple[float, float],
    ) -> MidLevelCommand:
        assert self.mission is not None
        robot_map = _pose_in(observation, MAP_FRAME)
        self.mission.status = "arrived"
        self.mission.metadata.update(
            {
                "owner_face_phase": "complete",
                "arrival_face_applied": ARRIVAL_FACE_OWNER,
                "owner_face_final_pose": (
                    float(robot_map.x),
                    float(robot_map.y),
                    math.degrees(float(robot_map.yaw)),
                ),
                "owner_face_final_owner_xy": owner_xy,
                "resolution_state": "verified",
                "plan_step": "completed",
            }
        )
        return MidLevelCommand(stop=True, note="arrived_verified")

    def _fail_owner_face_turn(self, reason: str) -> MidLevelCommand:
        assert self.mission is not None
        self.mission.status = "failed"
        self.mission.metadata.update(
            {
                "owner_face_phase": "failed",
                "owner_face_phase_a_verified": False,
                "owner_face_phase_a_invalidated_reason": reason,
                "owner_face_failure_reason": reason,
                "terminal_relation_verified": False,
                "resolution_state": "owner_face_verification_failed",
                "plan_step": "failed",
            }
        )
        return MidLevelCommand(stop=True, note=reason)

    def _semantic_arrival_verified(self, observation: NavObservation) -> bool:
        if self.mission is None or self.mission.semantic_goal is None:
            return True
        relation = self.mission.semantic_goal.terminal_relation
        # MAP: K0 is the single arrival authority and arrival is a world-frame
        # claim, so it reads the globally consistent frame -- never ODOM.
        robot_map = _pose_in(observation, MAP_FRAME)
        # GraphNav lesson (stratum 1): when localization is DEGRADED or LOST,
        # refuse to declare arrival rather than guess. This is an honest
        # not-verified, not a crash and not a failure -- the mission keeps its
        # existing verification budget and can recover if health returns.
        if not robot_map.is_healthy:
            self.mission.metadata["arrival_not_verified_reason"] = "pose_unhealthy"
            self.mission.metadata["pose_health"] = str(
                getattr(getattr(robot_map, "health", None), "value", "unknown")
            )
            return False
        if self.mission.metadata.get("arrival_not_verified_reason") == "pose_unhealthy":
            self.mission.metadata.pop("arrival_not_verified_reason", None)
        position = (robot_map.x, robot_map.y)
        if observation.extras.get("perception_fresh") is not True:
            self.mission.metadata["arrival_not_verified_reason"] = "perception_stale"
            return False
        if not self._terminal_environment_is_clear(observation, relation=relation):
            self.mission.metadata["arrival_not_verified_reason"] = (
                "terminal_environment_not_clear"
            )
            return False
        candidate = self._resight_committed_candidate(observation)
        arrival_region = self._arrival_goal_region()
        # Card A2 (NAV-GLUE) fix 2 — is this target one the ORACLE described?
        off_oracle = candidate is not None and self._arrival_target_is_off_oracle(candidate)
        if candidate is None:
            if relation != "inside" or arrival_region is None:
                self.mission.metadata["arrival_not_verified_reason"] = (
                    "target_not_resighted"
                )
                return False
            # Standing inside a region routinely puts its centroid outside
            # the camera frustum, so a same-tick re-sighting is the wrong
            # requirement for a static committed region: the polygon the
            # grounder committed at RESOLVED time is the arrival authority.
            polygon = getattr(arrival_region, "polygon", None)
            if not polygon:
                return False
            clearance = float(self.mission.metadata.get("terminal_clearance_m", 0.32))
            # Card A3 fix 5: nothing was re-sighted on this tick, so an inexact
            # pose has only its own covariance to argue with -- and that is the
            # R3 mechanism. Geometry on an exact pose still decides; a
            # chance-constrained claim without a detector does not.
            return self._inside_polygon_verified(
                robot_map,
                tuple((float(px), float(py)) for px, py in polygon),
                clearance,
                detector_confirmed=False,
            )
        # Card A2 fix 2 kept this check for EVERY target, oracle or not. The
        # off-oracle path below replaces only what is unsatisfiABLE off-oracle
        # (a polygon nobody surveyed, a LiDAR id join that does not exist); the
        # committed region is plain geometry that an observed map can satisfy,
        # so it stays a live refusal and ``outside_arrival_region`` stays a
        # TYPED non-arrival rather than becoming a claim.
        if arrival_region is not None and not arrival_region.contains(
            position[0],
            position[1],
            anchor_covariance=self._arrival_anchor_covariance(),
            probability_threshold=self.inside_probability_threshold,
        ):
            self.mission.metadata["arrival_not_verified_reason"] = "outside_arrival_region"
            return False
        # Stratum-2 evidence half of the ONE K0 predicate. Geometry says "I am
        # in the right place"; evidence says "and the thing I came for is
        # really there". A single frame at a literal 0.98 satisfied the old
        # predicate outright, which is precisely why U32's false arrival could
        # exist. Region membership keeps pure GoalRegion geometry (the branch
        # above, where no live candidate is required at all).
        if not self._arrival_evidence_verified(relation):
            self.mission.metadata.setdefault(
                "arrival_not_verified_reason", "arrival_evidence_insufficient"
            )
            return False
        if relation == "inside":
            polygon = _polygon(candidate.get("polygon"))
            if not polygon and off_oracle:
                # Card A2 fix 2: a region the dog learned by looking is a
                # remembered PLACE, not a surveyed polygon. Standing on it,
                # re-confirmed by this tick's detection, is the arrival.
                return self._off_oracle_arrival_verified(robot_map, candidate, relation)
            clearance = float(self.mission.metadata.get("terminal_clearance_m", 0.32))
            return bool(polygon) and self._inside_polygon_verified(
                robot_map, polygon, clearance
            )
        if relation in {"near", "next_to", "towards"}:
            if arrival_region is None:
                # Fail closed when the shared authority is missing.
                return False
            if relation == "near":
                target_clearance = self._target_clearance(observation)
                if target_clearance is None and off_oracle:
                    # Card A2 fix 2, the exact 15/60 case: the surface half of
                    # this check is unsatisfiABLE here, not unsatisfied. No
                    # polygon, no id join, and no range return the geometry can
                    # attribute to the target — so the band is measured to the
                    # detection itself instead of to a surface nothing observed.
                    return self._off_oracle_arrival_verified(
                        robot_map, candidate, relation
                    )
                radius = float(self.mission.metadata.get("candidate_radius_m", 0.0))
                minimum = float(self.mission.metadata.get("minimum_vicinity_radius_m", 0.0))
                maximum = float(self.mission.metadata.get("vicinity_radius_m", 1.35))
                minimum_surface = max(
                    0.0,
                    minimum - radius - ROBOT_FOOTPRINT_RADIUS_M,
                )
                maximum_surface = maximum - radius - ROBOT_FOOTPRINT_RADIUS_M
                if (
                    target_clearance is None
                    or maximum_surface < minimum_surface
                    or not minimum_surface - 1e-6 <= target_clearance <= maximum_surface + 1e-6
                ):
                    self.mission.metadata["arrival_not_verified_reason"] = (
                        "target_surface_unobserved"
                        if target_clearance is None
                        else "surface_clearance_out_of_band"
                    )
                    self.mission.metadata["arrival_target_clearance_m"] = (
                        None if target_clearance is None else float(target_clearance)
                    )
                    return False
                if not self._on_support_surface(position[0], position[1]):
                    self.mission.metadata["arrival_not_verified_reason"] = (
                        "outside_support_polygon"
                    )
                    return False
                return True
            # next_to / towards: GoalRegion membership is the spatial authority.
            return True
        return False

    def _arrival_target_is_off_oracle(self, candidate: dict[str, Any]) -> bool:
        """Does this target carry NONE of the evidence only an oracle supplies?

        Card A2 (NAV-GLUE) fix 2. The simulator's semantic channel ships a
        POLYGON for a region and an ``associated_lidar_ids`` join between the
        semantic id space and the range id space for an object. A detector and a
        LiDAR share no id space at all, and a map the dog built by looking
        stores a surface POINT — so off-oracle BOTH halves are simply absent and
        the two arrival branches that consume them (``inside``'s polygon
        containment, ``near``'s surface-clearance band) are unsatisfiABLE rather
        than unsatisfied. NAV-CORE measured the cost: 15/60 arm-A episodes drove
        to the place, resolved it, and wrote ``target_surface_unobserved``.

        The predicate is POSITIVE about provenance, not merely about absent
        fields, and that distinction is load-bearing: the sim's own camera
        fixtures ship an object with no polygon and no id join either, and
        answering their ``near`` band from a metric distance would relax a live
        oracle check (caught by
        ``test_near_object_arrival_requires_vicinity_and_safe_support_region``,
        which stands one pose too far down the sidewalk and must refuse). So the
        candidate has to SAY it came from the map the dog built — the ingress
        stamps ``metadata['semantic_source'] = 'learned_map'`` and
        ``source = 'online_map'`` (``semantic_map.learned_map_candidates``) —
        and to carry neither piece of oracle evidence. Every other candidate
        keeps the pre-A2 path exactly, byte for byte.
        """

        metadata = candidate.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        observed_map = (
            metadata.get("semantic_source") == "learned_map"
            or candidate.get("source") == "online_map"
        )
        if not observed_map:
            return False
        if _polygon(candidate.get("polygon")):
            return False
        return not metadata.get("associated_lidar_ids")

    def _off_oracle_arrival_verified(
        self,
        robot_map: Any,
        candidate: dict[str, Any],
        relation: str,
    ) -> bool:
        """Metric band + THIS TICK's detection — the off-oracle arrival claim.

        Card A2 fix 2, and the whole of it. Two things must both be true: the
        goal class was re-detected in THIS frame (``candidate`` is what
        :meth:`_resight_committed_candidate` returned, so a remembered anchor
        cannot stand in for a live look), and the body is inside the terminal
        band the mission itself committed to, measured to that fresh detection
        rather than to a surface nothing observed.

        What this deliberately is NOT: an arrival from the localiser's own
        confidence. NAV-CORE's refuter R3 produced a false arrival at
        ``p = 0.9922`` with the body 0.534 m from the goal against a 0.5 m band,
        because the chance constraint was reading a covariance nothing has
        calibrated (H7's missed L5/NEES row). Until card A3 lands that
        calibration, no covariance and no probability threshold may VERIFY
        anything on this path — they may only refuse. The detector
        re-confirmation is what makes the claim, and it is unconditional.
        """

        assert self.mission is not None
        metadata = self.mission.metadata
        # The BAND's centre is the tracker's fused estimate of where the target
        # is, not the single box this frame happened to produce: a detector that
        # scatters its estimate by 0.15 m per axis (0.212 m radial RMS, measured)
        # cannot also be the ruler. The single box's job is the OTHER half —
        # ``candidate`` is this tick's re-sighting, associated to that same
        # anchor inside ``CANDIDATE_ASSOCIATION_GATE_M``, and without it this
        # method is never reached.
        del candidate
        point = self._tracked_target_xy()
        if point is None:
            metadata["arrival_not_verified_reason"] = "target_not_resighted"
            return False
        distance = math.hypot(point[0] - robot_map.x, point[1] - robot_map.y)
        metadata["arrival_off_oracle_distance_m"] = float(distance)
        maximum = float(metadata.get("vicinity_radius_m", 0.0) or 0.0)
        # ``inside`` has no stand-off: the terminal relation IS being on the
        # place. Every band relation keeps the minimum the mission committed to.
        minimum = (
            0.0
            if relation == "inside"
            else float(metadata.get("minimum_vicinity_radius_m", 0.0) or 0.0)
        )
        if maximum <= 0.0 or not minimum - 1e-6 <= distance <= maximum + 1e-6:
            metadata["arrival_not_verified_reason"] = "outside_off_oracle_arrival_band"
            return False
        metadata.pop("arrival_not_verified_reason", None)
        metadata["arrival_verified_by"] = "off_oracle_band_and_resight"
        return True

    def _arrival_evidence(self) -> Any:
        """Cumulative evidence for the committed target, from the tracker."""

        if ArrivalEvidence is None:
            return None
        if self._tracker is None or self._target_track_id is None:
            return ArrivalEvidence()
        track = self._tracker.track_by_id(self._target_track_id)
        if track is None:
            return ArrivalEvidence()
        frames_seen = sum(track.class_counts.values())
        return ArrivalEvidence(
            frames_seen=int(frames_seen),
            cumulative_confidence=float(track.cumulative_score),
            max_other_class=float(track.max_other_class_fraction),
            confirming_frames=int(sum(1 for hit in track.window if hit)),
            visible=bool(track.window and track.window[-1] and track.misses == 0),
        )

    def _arrival_confidence_floor(self) -> float:
        if self._arrival_confidence_threshold is not None:
            return self._arrival_confidence_threshold
        goal = self.mission.semantic_goal if self.mission is not None else None
        return float(getattr(goal, "minimum_confidence", 0.0) or 0.0)

    def _arrival_evidence_verified(self, relation: str) -> bool:
        """Run the evidence gate and record its verdict on the mission.

        A ``REJECTED`` verdict is the one that writes to the false-positive
        memory: the target's own class labels contradicted each other, which is
        a statement that the thing is not what it was grounded as. Everything
        else is "not yet", which keeps the verification budget running.
        """

        if evidence_arrival_verified is None or self.mission is None:
            return True
        evidence = self._arrival_evidence()
        if evidence is None:
            return True
        verdict = evidence_arrival_verified(
            evidence,
            minimum_confidence=self._arrival_confidence_floor(),
            confirming_frames_m=ARRIVAL_CONFIRMING_FRAMES_M,
        )
        self.mission.metadata["arrival_evidence"] = verdict.as_dict()
        if verdict.verified:
            self.mission.metadata.pop("arrival_not_verified_reason", None)
            return True
        self.mission.metadata["arrival_not_verified_reason"] = verdict.reason
        if verdict.rejected:
            self._remember_false_positive(verdict.reason)
        return False

    def _remember_false_positive(self, reason: str) -> None:
        if self._false_positives is None or self.mission is None:
            return
        target = self._tracked_target_xy()
        if target is None:
            return
        label = str(self.mission.metadata.get("candidate_label") or "")
        if not label:
            goal = self.mission.semantic_goal
            label = str(getattr(goal, "query", "") or "")
        if not label:
            return
        self._false_positives.reject(target[0], target[1], label, reason=reason)
        self.mission.metadata["false_positive_memory"] = len(self._false_positives)
        self.mission.metadata["false_positive_last"] = {
            "x": target[0],
            "y": target[1],
            "label": label,
            "reason": reason,
        }

    #: Fallback when ``configs/navigation/pose.yaml`` cannot be read (frozen
    #: BARN bundles ship no configs). Mirrors that file's shipping value.
    DEFAULT_INSIDE_PROBABILITY_THRESHOLD = 0.9

    @property
    def inside_probability_threshold(self) -> float:
        if self._inside_probability_threshold is None:
            threshold = self.DEFAULT_INSIDE_PROBABILITY_THRESHOLD
            if _HAS_POSE:
                try:
                    from parcel_robot.pose import load_pose_config

                    threshold = load_pose_config().inside_probability_threshold
                except (OSError, ValueError, ImportError):
                    pass
            self._inside_probability_threshold = float(threshold)
        return self._inside_probability_threshold

    def _inside_polygon_verified(
        self,
        robot_map: Any,
        polygon: tuple[tuple[float, float], ...],
        clearance_m: float,
        *,
        detector_confirmed: bool = True,
    ) -> bool:
        """Inside-relation membership, chance-constrained when pose is uncertain.

        At zero pose covariance -- which is every run with
        :class:`~parcel_robot.pose.TruthPoseProvider` -- this is the *identical*
        call to :func:`point_in_polygon_with_clearance` the system has always
        made, taken on the identical floats. Nothing about T0 can move.

        With a non-zero covariance it becomes the stratum-1 chance constraint:
        ``P(inside | pose covariance) >= inside_probability_threshold`` under
        the half-space Gaussian approximation. A polygon predicate evaluated on
        a point estimate silently claims certainty the estimate does not have.

        **Card A3 / NAV-CORE fix 5 -- the calibration floor.** The chance
        constraint is only as honest as the covariance feeding it, and no
        covariance in this tree has ever been calibrated: H7 row L5 never
        measured NEES, H7's teleport moved the published sigma 1.00 -> 3.10 mm
        while the pose was 7 m wrong, and NAV-CORE refuter R3 turned exactly
        that into a WRONG ANSWER -- an arrival declared at ``p = 0.9922`` with
        the body 0.534 m outside a 0.5 m band. So a probability may REFUSE an
        arrival and may never MANUFACTURE one: when the pose is inexact, the
        claim additionally needs the detector confirmation card A2 made the
        rule for its off-oracle path ("no covariance and no probability
        threshold may verify anything here -- they may only refuse"). The one
        caller that had no detector in hand is the committed-region branch of
        :meth:`_semantic_arrival_verified`, which is why the parameter exists
        and defaults to the confirmed case.
        """

        if not _HAS_POSE or getattr(robot_map, "is_exact", True):
            return point_in_polygon_with_clearance(
                (robot_map.x, robot_map.y), polygon, clearance_m
            )
        probability = p_inside_polygon(robot_map, polygon, clearance_m=clearance_m)
        if self.mission is not None:
            self.mission.metadata["inside_probability"] = probability
            self.mission.metadata["inside_probability_threshold"] = (
                self.inside_probability_threshold
            )
        if not detector_confirmed:
            if self.mission is not None:
                self.mission.metadata["arrival_not_verified_reason"] = (
                    ARRIVAL_UNCALIBRATED_CONFIDENCE_REASON
                )
            return False
        return probability >= self.inside_probability_threshold

    def _arrival_goal_region(self) -> Any:
        if self.mission is None or GoalRegion is None:
            return None
        raw = self.mission.metadata.get("arrival_goal_region")
        if raw is None:
            return None
        if isinstance(raw, GoalRegion):
            return raw
        if isinstance(raw, dict):
            try:
                return GoalRegion.from_mapping(raw)
            except (TypeError, ValueError, KeyError):
                return None
        return None

    def _on_support_surface(self, x: float, y: float) -> bool:
        """Is ``(x, y)`` on the committed target's support surface (or is there none)?

        A ``near`` arrival requires standing ON the object's support polygon (the
        sidewalk it stands on) with footprint clearance. One place answers it, so
        the arrival TRIGGER (``_inside_arrival_goal_region``) and the terminal
        VERIFICATION (``_semantic_arrival_verified``) cannot disagree about the
        surface. Objects with no support polygon place no such constraint.
        """

        if self.mission is None:
            return True
        support = _polygon(self.mission.metadata.get("support_polygon"))
        if not support:
            return True
        support_clearance = float(
            self.mission.metadata.get("terminal_support_clearance_m", 0.32)
        )
        return point_in_polygon_with_clearance((x, y), support, support_clearance)

    def _resight_committed_candidate(self, observation: NavObservation) -> Any:
        """The committed target re-sighted in THIS frame, or ``None``.

        One place asks "is the thing I came for visible right now", so the
        arrival TRIGGER and the terminal VERIFICATION cannot disagree about it —
        the near arrival trigger uses it to avoid stopping to verify while still
        facing away from the target (whose re-sighting the verification then
        requires), and the verification uses it as the evidence gate.
        """

        if self.mission is None or self.mission.semantic_goal is None:
            return None
        return _current_semantic_candidate(
            observation,
            self.mission.metadata,
            # Card A2 fix 1: re-find the thing this mission COMMITTED to, which
            # is what this method's own docstring promises. It used to ask for
            # ``semantic_goal.kind`` — the goal's kind is a function of the
            # owner's phrasing ("go to the bed" -> region, "sit by the bed" ->
            # object), so once the kind-tolerant query lets a region goal commit
            # to an object-kinded learned-map row, asking for the GOAL's kind
            # here means the committed target can never be re-sighted and every
            # such episode dies ``target_not_resighted`` one metre from the
            # place. Falls back to the goal's kind when nothing was recorded, so
            # a frozen bundle without the field keeps its behaviour.
            expected_kind=str(
                self.mission.metadata.get("candidate_kind")
                or self.mission.semantic_goal.kind
            ),
            minimum_confidence=self.mission.semantic_goal.minimum_confidence,
            target_xy=self._tracked_target_xy(),
            gate_m=self.CANDIDATE_ASSOCIATION_GATE_M
            + float(self.mission.metadata.get("candidate_radius_m", 0.0) or 0.0),
        )

    def _inside_arrival_goal_region(self, observation: NavObservation) -> bool:
        if self.mission is None or self.mission.status != "running":
            return False
        if self.mission.semantic_goal is None:
            return False
        region = self._arrival_goal_region()
        if region is None:
            return False
        # MAP: K0 arrival authority. A GoalRegion is a world-frame object.
        robot_map = _pose_in(observation, MAP_FRAME)
        # Region "inside" (card seamless-pacing seam 3, 2026-08-09): converge the
        # instant the robot stands INSIDE the committed region polygon with the
        # SAME terminal clearance `_semantic_arrival_verified` requires (0.32 m
        # from every edge) — never on a raw edge hit. This previously returned
        # False unconditionally and left arrival to the geometric approach-pose
        # heading align, which spins `align_goal` in place (no meaningful heading
        # exists inside a polygon), is braked by the comfort gate, and burns the
        # entire step budget while already arrived — the
        # `navigation_step_limit_inside_goal` rows ("go to the sidewalk", "walk
        # onto the sidewalk"). Triggering on the identical inside-with-clearance
        # predicate the verification then re-checks makes trigger ⊆ verify, so it
        # converges the case without inventing an arrival the K0 scorer would not
        # also grant (terminal clearance is preserved, not a raw edge hit).
        if self.mission.semantic_goal.terminal_relation == "inside":
            polygon = getattr(region, "polygon", None)
            if not polygon:
                return False
            # Same footprint-radius fallback the "inside" terminal verification
            # uses; referenced by symbol so this read does not re-spell the
            # retired 0.32 F-robot-radius literal (authority-no-literal-drift).
            clearance = float(
                self.mission.metadata.get(
                    "terminal_clearance_m", ROBOT_FOOTPRINT_RADIUS_M
                )
            )
            return self._inside_polygon_verified(
                robot_map,
                tuple((float(px), float(py)) for px, py in polygon),
                clearance,
            )
        # D4: chance-constrained K0 under D2 anchor covariance when present;
        # zero / omitted covariance is today's boolean (T0 byte-equal).
        cov = self._arrival_anchor_covariance()
        if not region.contains(
            robot_map.x,
            robot_map.y,
            anchor_covariance=cov,
            probability_threshold=self.inside_probability_threshold,
        ):
            return False
        if cov is not None and self.mission is not None:
            from parcel_robot.instructnav.scoring import p_inside_goal_region

            self.mission.metadata["arrival_inside_probability"] = p_inside_goal_region(
                robot_map.x,
                robot_map.y,
                region,
                anchor_covariance=cov,
            )
            self.mission.metadata["arrival_inside_probability_threshold"] = (
                self.inside_probability_threshold
            )
        # The `near` K0 band is a full annulus, but a valid STAND pose
        # additionally lies on the object's support surface (the sidewalk it
        # stands on) — exactly what `_semantic_arrival_verified` enforces at
        # terminal verification. The arrival TRIGGER must read the same region,
        # or the robot stops to verify the instant it crosses the band from the
        # off-surface side (approaching the lamppost across the road, band edge
        # at y≈1.77 due south of a sidewalk that starts at y=2.2) and then fails
        # support-polygon verification having never reached the surface — the
        # 'walks to the object, declares failure 3/3' defect. One region,
        # checked identically at trigger and at verify; a NARROWING of the
        # trigger, never a widening of any band. Objects with no support polygon
        # are unaffected (the whole annulus stays valid).
        if self.mission.semantic_goal.terminal_relation == "near":
            if not self._on_support_surface(robot_map.x, robot_map.y):
                return False
            # The near verification additionally requires the target re-sighted
            # in-frame. Triggering the stop on band membership alone lets the
            # robot halt while still facing along its approach heading (not at
            # the target) — the band is a full annulus but the planned approach
            # pose faces the anchor, and only there is the anchor in frustum.
            # Deferring the trigger until the target is actually re-sighted lets
            # the robot finish the approach and its terminal heading align, so
            # the very next verification tick can succeed instead of failing
            # 'target_not_resighted' from a pose that never faced the anchor.
            if self._resight_committed_candidate(observation) is None:
                return False
        return True

    def _arrival_anchor_covariance(
        self,
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """D2 planar covariance stamped at lock-on / commit, or None (T0 path)."""

        if self.mission is None:
            return None
        raw = self.mission.metadata.get("arrival_anchor_covariance")
        if raw is None:
            return None
        try:
            row0, row1 = raw[0], raw[1]
            cov = (
                (float(row0[0]), float(row0[1])),
                (float(row1[0]), float(row1[1])),
            )
        except (TypeError, ValueError, IndexError, KeyError):
            return None
        if max(abs(v) for row in cov for v in row) <= 0.0:
            return None
        return cov

    def _build_arrival_goal_region(
        self,
        relation: str,
        result: SemanticCandidate,
    ) -> dict[str, Any] | None:
        if arrival_goal_region_for_relation is None or GoalRegion is None:
            raw = result.metadata.get("goal_region")
            return dict(raw) if isinstance(raw, dict) else None
        try:
            region = arrival_goal_region_for_relation(
                relation,
                center=(result.x, result.y),
                polygon=result.polygon,
                object_radius_m=float(result.metadata.get("radius_m") or 0.0),
                label=str(result.label or ""),
                entity_id=str(result.candidate_id),
                metadata=result.metadata,
            )
        except (TypeError, ValueError):
            raw = result.metadata.get("goal_region")
            return dict(raw) if isinstance(raw, dict) else None
        return region.as_dict()

    def _terminal_environment_is_clear(
        self,
        observation: NavObservation,
        *,
        relation: str,
    ) -> bool:
        if observation.extras.get("collision") is not False:
            return False
        if (
            observation.nearest_person_m is not None
            and observation.nearest_person_m < self.collision.person_stop_m
        ):
            return False
        # Stratum 2: geometric target association, not an oracle id join.
        target_xy = (
            self._tracked_target_xy()
            if self.mission is not None and relation in {"near", "next_to", "towards"}
            else None
        )
        # For "inside" the committed region itself is the destination: street
        # furniture standing in the region (bench, lamppost) must not
        # permanently fail verification while the robot is stopped on the
        # sidewalk it was sent to. This narrows the terminal VERIFICATION
        # check only — reactive_safety.py and the TTC gate keep full
        # authority over motion at all times.
        region_polygon: tuple[tuple[float, float], ...] = ()
        if relation == "inside":
            arrival_region = self._arrival_goal_region()
            polygon = getattr(arrival_region, "polygon", None)
            if polygon:
                region_polygon = tuple(
                    (float(px), float(py)) for px, py in polygon
                )
        # MAP: LiDAR returns are projected into the world-frame arrival polygon,
        # so the projection origin must be the same frame as the polygon.
        robot_map = _pose_in(observation, MAP_FRAME)
        yaw = robot_map.yaw
        robot_x = robot_map.x
        robot_y = robot_map.y

        def _in_region(distance: float, bearing: object) -> bool:
            if not region_polygon:
                return False
            if isinstance(bearing, bool) or not isinstance(bearing, (int, float)):
                return False
            if not math.isfinite(float(bearing)):
                return False
            point = (
                robot_x + float(distance) * math.cos(yaw + float(bearing)),
                robot_y + float(distance) * math.sin(yaw + float(bearing)),
            )
            return point_in_polygon_with_clearance(point, region_polygon, 0.0)

        raw = observation.extras.get("lidar_obstacles")
        if isinstance(raw, (list, tuple)):
            for item in raw[:64]:
                if not isinstance(item, dict):
                    return False
                distance = item.get("distance_m")
                if (
                    isinstance(distance, bool)
                    or not isinstance(distance, (int, float))
                    or not math.isfinite(float(distance))
                    or float(distance) < 0.0
                ):
                    return False
                bearing = item.get("bearing_rad")
                if (
                    isinstance(bearing, (int, float))
                    and not isinstance(bearing, bool)
                    and math.isfinite(float(bearing))
                    and self._lidar_point_is_target(
                        observation, float(distance), float(bearing), target_xy
                    )
                ):
                    continue
                if float(distance) < self.collision.obstacle_stop_m and not _in_region(
                    float(distance), item.get("bearing_rad")
                ):
                    return False
        nearest = observation.nearest_obstacle_m
        nearest_bearing = observation.extras.get("obstacle_bearing_rad")
        nearest_is_target = (
            nearest is not None
            and isinstance(nearest_bearing, (int, float))
            and not isinstance(nearest_bearing, bool)
            and math.isfinite(float(nearest_bearing))
            and self._lidar_point_is_target(
                observation, float(nearest), float(nearest_bearing), target_xy
            )
        )
        return (
            nearest is None
            or nearest_is_target
            or nearest >= self.collision.obstacle_stop_m
            or _in_region(float(nearest), observation.extras.get("obstacle_bearing_rad"))
        )

    def stop(self) -> None:
        if self.mission is not None:
            self.mission.status = "idle"
        self.mission = None
        self._best_goal_distance_m = None
        self._steps_without_progress = 0
        self._terminal_verification_steps = 0
        self._paused = False
        self._status_before_pause = None
        self._frozen_steps_without_progress = 0
        self._frozen_terminal_verification_steps = 0
        self._reset_ramp_memory()
        if self._tracker is not None:
            self._tracker.reset()
        if self._people_tracker is not None:
            self._people_tracker.reset()
        self._tracker_last_time_s = None
        self._target_track_id = None
        if self._false_positives is not None:
            # The memory is per-mission: "never re-tricked" has to hold across
            # this mission's replans, and claiming it across a whole session
            # would need a persistence story nothing here has.
            self._false_positives.clear()
        self._unreachable_candidates = set()
        self._steps_goal_unroutable = 0
        self._steps_gate_blocked = 0
        self._gate_blocked_anchor_xy = None
        # RM-2: the other mission boundary (see ``start``).
        self._reset_route_memory_track()

    def close(self) -> None:
        self.stop()
        self._navigator.close()


@dataclass(frozen=True)
class _ExcludingSemanticMap:
    """A :class:`SemanticMap` view with named instances removed.

    Wrapping rather than adding an ``exclude_ids`` keyword keeps the
    ``SemanticMap`` protocol and ``ActiveSemanticSearch.observe`` untouched:
    everything downstream still receives "the map", and only the mission — the
    one authority that knows which instance it released — decides what is in
    it.
    """

    inner: SemanticMap
    excluded: frozenset[str]

    def query(
        self, goal: SemanticGoal, observation: NavObservation
    ) -> list[SemanticCandidate]:
        return [
            candidate
            for candidate in self.inner.query(goal, observation)
            if candidate.candidate_id not in self.excluded
        ]


#: Float-lattice steps the compliant-speed cap may walk down while proving its
#: own output against the gate's inequality (card D15-B). A rounding residue is
#: a handful of ULPs; this bound only stops a pathological loop.
_COMPLIANT_CAP_LATTICE_STEPS = 64


def _wrap_to_pi(angle: float) -> float:
    """Fold an angle into ``[-pi, pi)`` — the convention every bearing here uses."""

    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _person_payload_entries(raw: Any) -> list[tuple[float, float, dict[str, Any]]]:
    """``(x, y, item)`` for a dynamic-agent / owner-track payload (card D15-B).

    Same contract as ``grid_navigator._refresh_dynamic_costs`` and
    ``_update_people_tracker`` read: a sequence of dicts carrying at least
    finite ``x``/``y``. Malformed entries are skipped rather than raising —
    a bad track must not take a mission down, and the gate is unaffected either
    way.
    """

    if not isinstance(raw, (list, tuple)):
        return []
    entries: list[tuple[float, float, dict[str, Any]]] = []
    for item in raw[:16]:
        if not isinstance(item, dict):
            continue
        try:
            x = float(item["x"])
            y = float(item["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        entries.append((x, y, item))
    return entries


def _dynamic_tracks_from_observation(observation: NavObservation) -> tuple[Any, ...]:
    """Parse ``observation.extras['dynamic_agents']`` (same contract as grid).

    Uses the stdlib-pure ``traffic_aware.tracks_from_payload`` so approach
    ranking stays free of the numpy dynamic-layer import. Malformed payloads
    degrade to empty tracks (static approach ordering) rather than aborting
    the mission mid-resolution.
    """

    try:
        from .traffic_aware import tracks_from_payload

        return tracks_from_payload(observation.extras.get("dynamic_agents") or ())
    except (TypeError, ValueError) as error:
        logger.warning("approach traffic ranking disabled this commit: %s", error)
        return ()

def _refusal_label(semantic_goal: Any) -> str:
    """Name the attribute in refusals: "a big tree", not just "a tree".

    An attribute that narrowed the search must appear in the report, otherwise
    the refusal quietly claims something stronger than what was checked.
    """

    attributes = tuple(getattr(semantic_goal, "attributes", ()) or ())
    return " ".join((*attributes, str(semantic_goal.query))).strip()


def _label_matches(query: str, label: str, aliases: tuple[str, ...] | list[str]) -> bool:
    from .semantic_map import _matches

    return _matches(query, label, aliases)


def _metadata_float(
    metadata: dict[str, Any],
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(metadata.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and minimum <= value <= maximum else default


def _near_fallback_band(
    metadata: dict[str, Any],
    *,
    obstacle_stop_m: float,
) -> tuple[float, float] | None:
    """Read the unchanged K0 vicinity band without widening either bound."""

    radius = _metadata_float(
        metadata, "radius_m", default=0.0, minimum=0.0, maximum=5.0
    )
    inner = _metadata_float(
        metadata,
        "minimum_vicinity_radius_m",
        default=radius + ROBOT_FOOTPRINT_RADIUS_M + obstacle_stop_m,
        minimum=0.1,
        maximum=4.0,
    )
    outer = _metadata_float(
        metadata,
        "vicinity_radius_m",
        default=inner + 0.2,
        minimum=0.5,
        maximum=4.0,
    )
    return (inner, outer) if 0.0 < inner <= outer else None


def _polygon(value: object) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return ()
    try:
        polygon = tuple((float(point[0]), float(point[1])) for point in value)
    except (IndexError, TypeError, ValueError):
        return ()
    return polygon if all(math.isfinite(axis) for point in polygon for axis in point) else ()


def _position(value: object) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        position = (
            float(value[0]),
            float(value[1]),
            float(value[2]) if len(value) > 2 else 0.0,
        )
    except (TypeError, ValueError):
        return None
    return position if all(math.isfinite(axis) for axis in position) else None


def _translated_goal_region(region: dict[str, Any], dx: float, dy: float) -> dict[str, Any]:
    """Shift a serialized GoalRegion by ``(dx, dy)`` — landmark re-anchoring.

    Only the geometry moves; kind, radius, band, and anchor identity are
    invariants of the relation and must not be touched here.
    """

    out = dict(region)
    center = out.get("center")
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        out["center"] = (float(center[0]) + dx, float(center[1]) + dy)
    polygon = out.get("polygon")
    if isinstance(polygon, (list, tuple)) and polygon:
        shifted = []
        for point in polygon:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                return dict(region)
            shifted.append((float(point[0]) + dx, float(point[1]) + dy))
        out["polygon"] = tuple(shifted)
    return out


def _current_semantic_candidate(
    observation: NavObservation,
    metadata: dict[str, Any],
    *,
    expected_kind: str,
    minimum_confidence: float,
    target_xy: tuple[float, float] | None = None,
    gate_m: float = 0.75,
) -> dict[str, Any] | None:
    """Re-find the committed target in this frame — geometrically.

    This used to be ``item["id"] == metadata["candidate_id"]``: the sim's
    semantic channel emits a stable oracle id per body, so "the same object"
    was a string comparison. A detector emits a fresh box per frame with no id
    at all, so the question is answered by distance to the tracked target
    position, inside ``gate_m``.

    ``target_xy=None`` falls back to the id comparison. That path is only
    reachable when no track and no committed position exist — i.e. from a
    frozen BARN bundle without the tracker, which keeps the behaviour it had.
    """

    raw = observation.extras.get("semantic_candidates")
    if not isinstance(raw, (list, tuple)):
        return None
    if target_xy is None:
        candidate_id = metadata.get("candidate_id")
        if not isinstance(candidate_id, str):
            return None
        matched = next(
            (
                item
                for item in raw[:64]
                if isinstance(item, dict) and item.get("id") == candidate_id
            ),
            None,
        )
    else:
        best: dict[str, Any] | None = None
        best_distance = float(gate_m)
        for item in raw[:64]:
            if not isinstance(item, dict) or item.get("kind") != expected_kind:
                continue
            point = _candidate_xy(item)
            if point is None:
                continue
            distance = math.hypot(point[0] - target_xy[0], point[1] - target_xy[1])
            if distance <= best_distance:
                best_distance = distance
                best = item
        matched = best
    if matched is None:
        return None
    confidence = matched.get("confidence")
    reachable = matched.get("reachable", True)
    if (
        matched.get("kind") != expected_kind
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(float(confidence))
        or not minimum_confidence <= float(confidence) <= 1.0
        or reachable is not True
    ):
        return None
    return matched


def _ray_hits_target(
    *,
    robot_xy: tuple[float, float],
    ray_angle_rad: float,
    ray_range_m: float,
    target_xy: tuple[float, float],
    gate_m: float,
) -> bool:
    """Does a range return along ``ray_angle_rad`` belong to ``target_xy``?

    Two conditions, both necessary:

    * **lateral** — the perpendicular offset of the target from the ray is
      within ``gate_m`` (the ray points at the target);
    * **along-ray** — the return is no farther than the target's own along-ray
      distance plus ``gate_m`` (the return is the target's near surface or
      something in front of it, never something behind it).
    """

    dx = target_xy[0] - robot_xy[0]
    dy = target_xy[1] - robot_xy[1]
    ux = math.cos(ray_angle_rad)
    uy = math.sin(ray_angle_rad)
    along = dx * ux + dy * uy
    if along <= 0.0:
        # The target is behind the ray; nothing on this bearing is it.
        return False
    perpendicular = abs(dx * uy - dy * ux)
    if perpendicular > gate_m:
        return False
    return float(ray_range_m) <= along + gate_m


def _candidate_xy(item: dict[str, Any]) -> tuple[float, float] | None:
    """Planar centre of a raw candidate payload (position, centroid, polygon)."""

    center = item.get("position") or item.get("centroid")
    if center is None:
        polygon = item.get("polygon") or ()
        if not polygon:
            return None
        try:
            return (
                sum(float(p[0]) for p in polygon) / len(polygon),
                sum(float(p[1]) for p in polygon) / len(polygon),
            )
        except (IndexError, TypeError, ValueError, ZeroDivisionError):
            return None
    if not isinstance(center, (list, tuple)) or len(center) < 2:
        return None
    try:
        x, y = float(center[0]), float(center[1])
    except (TypeError, ValueError):
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def _finite_xy(value: object) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x, y = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def _wrapped_degrees(value: float) -> float:
    return (float(value) + 180.0) % 360.0 - 180.0


def _motion_feedback_values(
    observation: NavObservation,
) -> tuple[float, float, float, float] | None:
    feedback = observation.extras.get("motion_feedback")
    if not isinstance(feedback, dict):
        return None
    if feedback.get("fresh") is not True:
        return None
    values = (
        feedback.get("linear_speed_mps"),
        feedback.get("yaw_speed_rad_s"),
        feedback.get("settled_linear_speed_mps"),
        feedback.get("settled_yaw_speed_rad_s"),
    )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
        for value in values
    ):
        return None
    return tuple(float(value) for value in values)  # type: ignore[return-value]


def _motion_feedback_is_fresh(observation: NavObservation) -> bool:
    return _motion_feedback_values(observation) is not None


def _motion_feedback_is_settled(observation: NavObservation) -> bool:
    feedback = observation.extras.get("motion_feedback")
    if not isinstance(feedback, dict) or feedback.get("stop_confirmed") is not True:
        return False
    values = _motion_feedback_values(observation)
    if values is None:
        return False
    linear, yaw, linear_limit, yaw_limit = values
    return linear <= linear_limit and yaw <= yaw_limit


def _candidate_obstacle_ids(candidate: object) -> frozenset[str]:
    candidate_id = getattr(candidate, "candidate_id", None)
    metadata = getattr(candidate, "metadata", {})
    ids = {candidate_id} if isinstance(candidate_id, str) and candidate_id else set()
    values = metadata.get("associated_lidar_ids") if isinstance(metadata, dict) else None
    if isinstance(values, (list, tuple)):
        ids.update(
            value for value in values[:16] if isinstance(value, str) and 0 < len(value) <= 128
        )
    return frozenset(ids)


# ``_obstacle_ids(metadata)`` used to live here. It answered "which LiDAR
# returns are the target?" with ``{candidate_id} | associated_lidar_ids`` — an
# id join that only closes because the simulator hands the same string to the
# semantic channel and the range channel. It is deleted, not deprecated: every
# caller now asks :meth:`DirectiveNavigator._lidar_point_is_target`, which
# compares a projected surface point against the tracked target position. The
# ``associated_lidar_ids`` metadata key survives as telemetry and as the input
# ``approach.py`` still records, but nothing gates on it any more.


def _candidate_ground_distance_m(candidate: Any, robot_x: float, robot_y: float) -> float:
    """Boundary distance for polygon (stuff) candidates, centroid otherwise.

    Fallback-path twin of the grounder's region-aware distance (arbitration
    2026-08-07): "the sidewalk" ranks by the distance to the region you can
    step onto, not to its centroid across the street.
    """

    polygon = getattr(candidate, "polygon", None)
    if polygon and len(polygon) >= 3 and nearest_point_in_region is not None:
        try:
            nearest = nearest_point_in_region(polygon, (robot_x, robot_y), inset_m=0.0)
        except ValueError:
            pass
        else:
            return math.hypot(nearest[0] - robot_x, nearest[1] - robot_y)
    return math.hypot(candidate.x - robot_x, candidate.y - robot_y)
