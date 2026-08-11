from __future__ import annotations

import importlib.util
import logging
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from parcel_robot.geometry import ROBOT_FOOTPRINT_RADIUS_M

from .approach import point_in_polygon_with_clearance, safe_approach_pose
from .base import GoalPose, MidLevelCommand, Mission, NavObservation
from .collision import CollisionPolicy, apply_collision_brake
from .goals import (
    SemanticGoal,
    navigation_directive_is_blocked,
    semantic_goal_from_directive,
)
from .grounder import PlaceGrounder
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
    SemanticValueMap2D = None  # type: ignore[misc, assignment]
    _HAS_INSTRUCTNAV = False

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
    }


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
        self._navigator = registry.create(model_id, arrive_radius_m=arrive_radius_m)
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
        grounder = PlaceGrounder.from_yaml(pois_path)
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

    def set_model(self, model_id: str) -> None:
        if self._navigator is not None:
            self._navigator.close()
        self.model_id = model_id
        self._navigator = self.registry.create(model_id, arrive_radius_m=self.arrive_radius_m)

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
            goal = self.grounder.ground(directive)
            return Mission(
                directive=directive,
                goal=goal,
                status="idle",
                metadata={"goal_source": "known_poi"},
            )
        except LookupError:
            semantic_goal = semantic_goal_from_directive(directive)
            return Mission(
                directive=directive,
                goal=None,
                status="unresolved",
                semantic_goal=semantic_goal,
                metadata={
                    "goal_source": "semantic_search",
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
        if self.scan_behavior is not None:
            self.scan_behavior.reset()
        if self._value_scan_session is not None:
            self._value_scan_session.reset()
        if self._detection_lock_on is not None:
            self._detection_lock_on.reset()
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

        self._active_task_id = str(task_id)
        self._active_plan_revision = int(plan_revision)

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
        return {
            "paused": self._paused,
            "steps_without_progress": self._steps_without_progress,
            "terminal_verification_steps": self._terminal_verification_steps,
            "mission_status": None if mission is None else mission.status_value(),
            "has_mission": mission is not None,
        }

    def step(self, observation: NavObservation) -> MidLevelCommand:
        if self.mission is None:
            return MidLevelCommand(stop=True, note="no_mission")
        if self._paused:
            # Budgets stay frozen; do not advance watchdog counters.
            return MidLevelCommand(stop=True, note="mission_paused")
        lost = self._pose_lost_hold(observation)
        if lost is not None:
            return lost
        self._update_tracker(observation)
        if self.mission.goal is None:
            return self._step_semantic_resolution(observation)
        self._reanchor_landmark_goal(observation)
        if self.mission.status == "verifying":
            return self._step_terminal_verification(observation)
        control_observation = self._control_observation(observation)
        cmd = self._navigator.act(control_observation, self.mission)
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
        unroutable = self._unroutable_goal_recovery()
        if unroutable is not None:
            return unroutable
        gate_blocked = self._gate_blocked_route_recovery()
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
        if cnote == "obstacle_stop" and self._steps_without_progress > 0:
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

    def _commit_semantic_candidate(
        self,
        semantic_goal: Any,
        result: SemanticCandidate,
        observation: NavObservation,
        *,
        grounding_outcome: str,
    ) -> MidLevelCommand:
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
        if pose is None:
            # Before conceding this instance, try the K0-band approach fallback.
            # ``safe_approach_pose`` plans a ``near`` pose on the object's
            # SUPPORT SURFACE (the sidewalk it sits on). For a wide object on a
            # narrow strip flanked by other furniture — a 0.73 m bench on a 2 m
            # sidewalk with a lamppost and a tree ~2.5 m to each side — that
            # support-gated ring has no admissible point from ANY robot pose, so
            # the solver returns ``None`` unconditionally, the release below
            # banishes the only real target from the excluding semantic map, and
            # the search-reground loop spins out its whole budget never seeing
            # the bench again (2026-08-09 root cause). But the directive's own
            # success test — the same K0 vicinity band the mission then verifies
            # against — accepts any collision-clear pose in that band, sidewalk
            # or not. Committing there is a grounded arrival at the real object,
            # not a hallucination: we only reach here for a candidate already
            # grounded, confirmed, reachable, and frustum-visible.
            pose = self._fallback_near_arrival_pose(semantic_goal, result, observation)
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
                "candidate_confidence": result.confidence,
                "candidate_source": result.source,
                "target_polygon": result.polygon,
                "terminal_relation": semantic_goal.terminal_relation,
                "terminal_behavior": semantic_goal.terminal_behavior,
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
        now_s = float(observation.extras.get("time_s") or 0.0)
        if (
            _HAS_INSTRUCTNAV
            and SE2Goal is not None
            and self.proposer_bus is not None
            and self.goal_arbiter is not None
        ):
            proposed = SE2Goal(
                source="grounder",
                pose=(pose.x, pose.y, math.radians(pose.heading_deg)),
                confidence=float(result.confidence),
                ttl_s=2.0,
                plan_step_id="align_then_translate",
                issued_s=now_s,
                priority=10,
                task_id=self._active_task_id,
                plan_revision=self._active_plan_revision,
            )
            self.proposer_bus.publish(proposed)
            self.goal_arbiter.set_plan_step("align_then_translate")
            chosen = self.goal_arbiter.resolve((proposed,), now_s=now_s)
            if chosen is None:
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
        self._terminal_verification_steps = 0
        # Bind the freshly committed target to a confirmed track now, so the
        # very next tick's geometric association has an anchor.
        self._bind_target_track()
        return MidLevelCommand(vx=0.0, vy=0.0, vyaw=0.0, note="semantic_target_resolved")

    def _fallback_near_arrival_pose(
        self,
        semantic_goal: Any,
        result: SemanticCandidate,
        observation: NavObservation,
    ) -> GoalPose | None:
        """Approach pose inside the K0 ``near`` vicinity band when the
        support-gated :func:`safe_approach_pose` solver finds none.

        This is the search-reground fix's honest fallback, and it never widens a
        band or weakens a gate. It commits only to a point that (1) lies inside
        the SAME ``near`` vicinity band ``_inside_arrival_goal_region`` verifies
        against — ``[minimum_vicinity_radius_m, vicinity_radius_m]`` from the
        candidate's own metadata, the K0 authority — and (2) keeps the full
        footprint-to-surface collision clearance from every observed non-target
        obstacle. If no such point exists the instance is genuinely boxed in and
        this returns ``None``, leaving the existing unreachable-release to fail
        the mission honestly. Applies to the band relations ``near`` and
        ``next_to`` — both verify against a distance band around the object, and
        the ``near`` vicinity ``[minimum_vicinity_radius_m, vicinity_radius_m]``
        is a subset of the wider ``next_to`` band, so a pose this admits sits
        inside whichever band the mission then verifies. ``towards`` has its own
        stop-short waypoint and never reaches the support-gated solver.
        """

        if near_band_fallback_point is None or GoalPose is None or self.mission is None:
            return None
        if getattr(semantic_goal, "terminal_relation", "") not in {"near", "next_to"}:
            return None
        if not bool(getattr(result, "reachable", True)):
            return None
        radius = _metadata_float(
            result.metadata, "radius_m", default=0.0, minimum=0.0, maximum=5.0
        )
        inner = _metadata_float(
            result.metadata,
            "minimum_vicinity_radius_m",
            default=radius + ROBOT_FOOTPRINT_RADIUS_M + self.collision.obstacle_stop_m,
            minimum=0.1,
            maximum=4.0,
        )
        outer = _metadata_float(
            result.metadata,
            "vicinity_radius_m",
            default=inner + 0.2,
            minimum=0.5,
            maximum=4.0,
        )
        if not (0.0 < inner <= outer):
            return None
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
            if self.detection_lock_on and self._detection_lock_on is not None:
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

        self._paint_scan_observation(semantic_goal, observation, frustum)
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
            return select_search_entity_frontier(
                origin_xy=origin,
                robot_xy=robot_xy,
                query_label=query_label or "unknown",
                covered=self._frontier_viewpoints,
                rings=rings,
                bearings=bearings,
                ring_step_m=ring_step_m,
                travel_weight=travel_weight,
                value_map=self.semantic_value_map if self.value_directed_search else None,
                plan_prior=self._plan_time_prior if self.value_directed_search else None,
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
        """Paint the current look into the shared SemanticValueMap2D belief."""

        if (
            not self.value_directed_search
            or self.semantic_value_map is None
            or paint_look is None
        ):
            return
        robot_map = _pose_in(observation, MAP_FRAME)
        query = str(getattr(semantic_goal, "query", "") or "").strip().lower()
        value = 0.15
        for candidate in frustum:
            label = str(getattr(candidate, "label", "") or "").strip().lower()
            if query and (query in label or label in query):
                value = max(value, float(getattr(candidate, "confidence", 0.7)))
            else:
                value = max(value, 0.05)
        paint_look(
            self.semantic_value_map,
            origin_world_xy=robot_map.xy,
            heading_rad=robot_map.yaw,
            value=min(1.0, value),
            conf=1.0,
        )

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
        # MAP: the watchdog measures range to a world-frame goal. Bound to MAP
        # rather than ODOM deliberately -- an ODOM-frame reading of a MAP goal
        # would report drift as "no progress" and fail a mission that is in
        # fact converging.
        robot_map = _pose_in(observation, MAP_FRAME)
        distance = math.hypot(
            self.mission.goal.x - robot_map.x,
            self.mission.goal.y - robot_map.y,
        )
        if self._best_goal_distance_m is None or distance < self._best_goal_distance_m - 0.025:
            self._best_goal_distance_m = distance
            self._steps_without_progress = 0
            return None
        # Yielding to a person is not a navigation stall — person-stop is the
        # correct gate. Counting those ticks as "no progress" false-fails the
        # N11 pedestrian case before yield-advance can use clear windows.
        if (
            observation.nearest_person_m is not None
            and observation.nearest_person_m < self.collision.person_stop_m
        ):
            return None
        self._steps_without_progress += 1
        if self._steps_without_progress < self.progress_timeout_steps:
            return None

        replans = int(self.mission.metadata.get("replan_count", 0))
        if self.mission.semantic_goal is not None and replans < self.max_semantic_replans:
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

    def _unroutable_goal_recovery(self) -> MidLevelCommand | None:
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
        # ``_progress_watchdog`` has already run this tick and zeroes this
        # counter on any real closing of the gap. Unroutable *while closing the
        # gap* is a detour in progress, not a dead goal.
        if self._steps_without_progress == 0:
            self._steps_goal_unroutable = 0
            return None
        self._steps_goal_unroutable += 1
        if self._steps_goal_unroutable < self.UNROUTABLE_GOAL_STEPS:
            return None

        self.mission.metadata["unroutable_route_status"] = str(status)
        return self._release_unreachable_candidate(
            str(self.mission.metadata.get("candidate_id") or ""),
            note="semantic_replan_after_unroutable_goal",
        )

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

    def _gate_blocked_route_recovery(self) -> MidLevelCommand | None:
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
        # The counter only advances on ticks that already had zero progress,
        # but re-read it here so a tick that *did* progress cannot fire a
        # stale count.
        if self._steps_without_progress == 0:
            self._steps_gate_blocked = 0
            return None
        self.mission.metadata["blocked_route_gate"] = "obstacle_stop"
        return self._release_unreachable_candidate(
            str(self.mission.metadata.get("candidate_id") or ""),
            note="semantic_replan_after_blocked_route",
        )

    def _begin_semantic_replan(self, replans: int, *, note: str) -> MidLevelCommand:
        assert self.mission is not None and self.mission.semantic_goal is not None
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
            return self._inside_polygon_verified(
                robot_map,
                tuple((float(px), float(py)) for px, py in polygon),
                clearance,
            )
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
            expected_kind=self.mission.semantic_goal.kind,
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


def _motion_feedback_is_settled(observation: NavObservation) -> bool:
    feedback = observation.extras.get("motion_feedback")
    if not isinstance(feedback, dict):
        return False
    if feedback.get("fresh") is not True or feedback.get("stop_confirmed") is not True:
        return False
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
        return False
    linear, yaw, linear_limit, yaw_limit = (float(value) for value in values)
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
