"""Semantic adapter between the task executive and Parcel's existing runtime.

The adapter deliberately has no access to actuators, priorities, raw velocity,
or simulator coordinates.  It translates admitted semantic skills into the
runtime's existing navigation/follow/spatial boundaries and turns their
observable terminal states into typed, non-model-authored execution facts.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass, replace

from parcel_robot.models import SpatialIntent

# Terminal-state constants owned by the navigator (MissionStatus values).
# Kept as string literals so historical BARN bundles that pin an older
# navigation.base remain import-compatible with this adapter.
NAVIGATION_SUCCESS_STATES = frozenset({"arrived"})
NAVIGATION_FAILURE_STATES = frozenset({"failed", "unresolved"})
NAVIGATION_IN_PROGRESS_STATES = frozenset(
    {"running", "searching", "verifying", "paused", "waiting"}
)
SPATIAL_SUCCESS_STATES = frozenset({"completed"})
SPATIAL_FAILURE_STATES = frozenset({"failed", "cancelled"})
FOLLOW_SUCCESS_STATES = frozenset({"holding_behind"})
# Plain follow (relation="follow", controller mode "direct") is verified once
# the controller is actively tracking or holding station on the owner. It has
# no behind-staging state because it never estimates an owner heading.
DIRECT_FOLLOW_SUCCESS_STATES = frozenset({"following", "holding"})
SEARCH_SUCCESS_STATES = frozenset({"reacquired"})
SEARCH_FAILURE_STATES = frozenset({"gave_up"})

from .contracts import (
    ExecutionResult,
    IntentFrame,
    ObservationSnapshot,
    PlanIR,
    VerifiedFact,
)
from .executive import DispatchRequest
from .validator import RUNTIME_AUTHORED_SKILLS, SYSTEM_SKILL_NAMES

DispatchKey = tuple[str, int, str, int]
#: Skill → the runtime channel that can be *paused* (ResumeIntent) rather than
#: stopped. Suspend→pause reconciliation and the RESUME join must agree on this
#: table or a resumed channel drives with no running plan step behind it (N14).
#: Every other skill's controller is stopped outright by a suspend, so restoring
#: it means dispatching the step again, not re-binding to it.
PAUSABLE_SKILL_CHANNELS: dict[str, str] = {
    "NavigateTo": "navigation",
    "FollowFormation": "follow",
    "SearchOwner": "search",
}
# The camera-grounding threshold the validator and executive already use for
# ``owner_visible``; reacquisition is held to the same bar.
OWNER_TRACK_CONFIDENCE_MIN = 0.6
PLAN_IR_OUTPUT_CONTRACT = "plan_ir_v1"
PLAN_SKETCH_OUTPUT_CONTRACT = "plan_sketch_v1"
PLANNER_OUTPUT_CONTRACTS = frozenset({PLAN_IR_OUTPUT_CONTRACT, PLAN_SKETCH_OUTPUT_CONTRACT})


@dataclass(frozen=True, slots=True)
class SemanticRuntimeState:
    """Bounded controller state used to verify semantic step completion."""

    snapshot_id: str | None
    navigation_enabled: bool = False
    navigation_state: str = "idle"
    navigation_goal: str | None = None
    navigation_reason: str = ""
    spatial_enabled: bool = False
    spatial_state: str = "idle"
    spatial_reason: str = ""
    follow_enabled: bool = False
    follow_state: str = "idle"
    follow_mode: str = "direct"
    # Owner reacquisition (card W7). ``owner_track_confidence`` is the passive
    # camera owner track the follow controller consumes, reported separately so
    # SearchOwner completion is verified against perception as well as against
    # the search controller's own terminal state.
    search_enabled: bool = False
    search_state: str = "idle"
    search_reason: str = ""
    owner_track_confidence: float = 0.0
    stop_confirmed: bool = False
    control_feedback_fresh: bool = False
    robot_moving: bool = False
    # Last successfully applied posture name ("unknown" when never applied);
    # ReturnToSafePose completion verifies against this, never the request.
    posture: str = "unknown"
    # Activity-coordinator view used to verify Gesture completion: the name of
    # the most recent physical activity and its terminal status. A gesture is
    # complete only when the coordinator reports it finished, never because
    # the dispatch returned. ``activity_created_at`` (the record's monotonic
    # creation time) lets the verifier reject stale same-name records from an
    # EARLIER emote — matching by name alone falsely completed a re-dispatch
    # of the same clip (2026-08-04 sprint review).
    activity_name: str = ""
    activity_status: str = "idle"
    activity_detail: str = ""
    activity_created_at: float = 0.0


@dataclass(frozen=True, slots=True)
class ActiveSemanticDispatch:
    request: DispatchRequest
    started_at_monotonic_s: float

    @property
    def key(self) -> DispatchKey:
        return dispatch_key(self.request)


class SemanticTaskRuntimeAdapter:
    """Dispatch semantic requests and verify them from controller state.

    The callbacks are system-owned runtime boundaries.  None accepts a raw
    motion command.  Callers serialize ``dispatch`` and ``cancel`` with their
    normal command-ownership lock; polling is read-only and thread-safe.
    """

    SUPPORTED_SKILLS = frozenset(
        {
            "NavigateTo",
            "FollowFormation",
            "OrbitOwner",
            "MoveRelative",
            "Hold",
            "Vocalize",
            "AskClarification",
            "ReturnToSafePose",
            "Gesture",
        }
    )
    # Skills the runtime proposes deterministically and a language model may
    # never author. They are executed, validated, and verified exactly like any
    # other semantic skill; they are simply absent from the planner's surface,
    # so they stay out of ``SUPPORTED_SKILLS`` and out of every schema and
    # registry derived from it.
    SYSTEM_SKILLS = SYSTEM_SKILL_NAMES
    # Skills only the runtime's own deterministic sketches author (``Pose``,
    # the settle half of backlog N13). Executable and verified like any other
    # skill, but deliberately absent from SUPPORTED_SKILLS, because that set is
    # what every model-facing response schema enumerates.
    RUNTIME_AUTHORED = RUNTIME_AUTHORED_SKILLS
    EXECUTABLE_SKILLS = SUPPORTED_SKILLS | SYSTEM_SKILLS | RUNTIME_AUTHORED

    def __init__(
        self,
        *,
        navigate: Callable[[str], object],
        follow_formation: Callable[[str, float], object],
        spatial_behavior: Callable[[SpatialIntent], object],
        hold: Callable[[], object],
        vocalize: Callable[[str], object],
        return_to_safe_pose: Callable[[str], object] | None = None,
        gesture: Callable[[str, float], object] | None = None,
        search_owner: Callable[[], object] | None = None,
        scan_behavior: Callable[[], object] | None = None,
        search_entity: Callable[[str], object] | None = None,
    ):
        self._navigate = navigate
        self._follow_formation = follow_formation
        self._spatial_behavior = spatial_behavior
        self._hold = hold
        self._vocalize = vocalize
        self._return_to_safe_pose = return_to_safe_pose
        self._gesture = gesture
        self._search_owner = search_owner
        self._scan_behavior = scan_behavior
        self._search_entity = search_entity
        self._active: dict[DispatchKey, ActiveSemanticDispatch] = {}
        self._lock = threading.RLock()

    def dispatch(
        self,
        request: DispatchRequest,
        *,
        now: float | None = None,
    ) -> ExecutionResult | None:
        """Start one semantic skill; speech-only skills finish synchronously."""

        if request.skill not in self.EXECUTABLE_SKILLS:
            raise ValueError(f"runtime adapter does not support {request.skill}")
        timestamp = time.monotonic() if now is None else float(now)
        if not math.isfinite(timestamp) or timestamp < 0.0:
            raise ValueError("dispatch time must be finite and non-negative")
        key = dispatch_key(request)
        with self._lock:
            if key in self._active:
                raise RuntimeError("semantic dispatch is already active")

        args = request.arguments
        if request.recovery_action in {"safe_stop", "wait"}:
            # Recovery remains deterministic and non-blocking at control rate.
            # ``wait`` means settle before retry; it never sleeps the loop.
            self._hold()
        elif request.recovery_action == "ask_user":
            raise RuntimeError("semantic retry requires user clarification")
        # replan/alternate_candidate/rescan/reacquire_owner are implemented by
        # restarting the relevant deterministic local controller below. No LLM
        # is ever called from this adapter or from the executive tick.
        if request.skill == "NavigateTo":
            self._navigate(str(args["directive"]))
        elif request.skill == "FollowFormation":
            self._follow_formation(str(args["relation"]), float(args["distance_m"]))
        elif request.skill == "OrbitOwner":
            self._spatial_behavior(
                SpatialIntent(
                    behavior="orbit_owner",
                    direction=str(args["direction"]),
                    size=str(args["size"]),
                    revolutions=float(args["revolutions"]),
                )
            )
        elif request.skill == "MoveRelative":
            self._spatial_behavior(
                SpatialIntent(
                    behavior="move_steps",
                    direction=str(args["direction"]),
                    steps=int(args["steps"]),
                )
            )
        elif request.skill == "Hold":
            self._hold()
        elif request.skill in {"ReturnToSafePose", "Pose"}:
            if self._return_to_safe_pose is None:
                raise RuntimeError(
                    f"{request.skill} has no runtime callback on this deployment"
                )
            # One runtime door for postures: stop motion, then apply a pose from
            # the admitted catalog. ``Pose`` differs from ``ReturnToSafePose``
            # only in its admission contract (no battery_critical gate) and in
            # its argument name, never in what actually moves the robot.
            self._return_to_safe_pose(
                str(args["pose"] if request.skill == "ReturnToSafePose" else args["name"])
            )
        elif request.skill == "Gesture":
            if self._gesture is None:
                raise RuntimeError("Gesture has no runtime callback on this deployment")
            self._gesture(str(args["name"]), float(args.get("intensity", 1.0)))
        elif request.skill == "SearchOwner":
            if self._search_owner is None:
                raise RuntimeError("SearchOwner has no runtime callback on this deployment")
            self._search_owner()
        elif request.skill == "ScanBehavior":
            if self._scan_behavior is None:
                raise RuntimeError("ScanBehavior has no runtime callback on this deployment")
            self._scan_behavior()
        elif request.skill == "SearchEntity":
            if self._search_entity is None:
                raise RuntimeError("SearchEntity has no runtime callback on this deployment")
            self._search_entity(str(args["query"]))
        else:
            field = "text" if request.skill == "Vocalize" else "question"
            self._vocalize(str(args[field]))
            return _terminal_result(
                request,
                started=timestamp,
                snapshot_id=None,
                source="runtime_voice_log",
                detail="utterance_sent",
                verified_target=None,
            )

        with self._lock:
            # Command serialization in RobotRuntime prevents a cancellation
            # from crossing between the semantic callback and this record.
            self._active[key] = ActiveSemanticDispatch(request, timestamp)
        return None

    def adopt(self, request: DispatchRequest, *, now: float | None = None) -> None:
        """Track a step whose controller is *already* executing, without dispatching.

        The RESUME join uses this: the paused channel was restored from its
        stored ``ResumeIntent``, so the mission is running with all of its
        state. Calling :meth:`dispatch` here would cold-start it instead. An
        existing record for the same key is replaced so the elapsed clock
        matches the executive's restarted step clock rather than counting the
        pause.
        """

        timestamp = time.monotonic() if now is None else float(now)
        if not math.isfinite(timestamp) or timestamp < 0.0:
            raise ValueError("adopt time must be finite and non-negative")
        with self._lock:
            self._active[dispatch_key(request)] = ActiveSemanticDispatch(request, timestamp)

    def poll(
        self,
        state: SemanticRuntimeState,
        *,
        now: float | None = None,
    ) -> tuple[ExecutionResult, ...]:
        """Return controller-grounded progress/terminal results for active work."""

        timestamp = time.monotonic() if now is None else float(now)
        if not math.isfinite(timestamp) or timestamp < 0.0:
            raise ValueError("poll time must be finite and non-negative")
        with self._lock:
            active = tuple(self._active.values())

        results: list[ExecutionResult] = []
        terminal: list[DispatchKey] = []
        for item in active:
            result = self._result_for(item, state, timestamp)
            results.append(result)
            if result.status != "in_progress":
                terminal.append(item.key)
        if terminal:
            with self._lock:
                for key in terminal:
                    self._active.pop(key, None)
        return tuple(results)

    def cancel(self, task_ids: Iterable[str]) -> tuple[ActiveSemanticDispatch, ...]:
        """Forget selected work and tell the runtime which behaviors to stop."""

        selected = frozenset(str(item) for item in task_ids)
        if not selected:
            return ()
        with self._lock:
            removed = tuple(
                item for item in self._active.values() if item.request.task_id in selected
            )
            for item in removed:
                self._active.pop(item.key, None)
        return removed

    def reconcile(
        self,
        valid_keys: Iterable[DispatchKey],
    ) -> tuple[ActiveSemanticDispatch, ...]:
        """Drop executions made stale by timeout, retry, or task replacement."""

        valid = frozenset(valid_keys)
        with self._lock:
            removed = tuple(item for key, item in self._active.items() if key not in valid)
            for item in removed:
                self._active.pop(item.key, None)
        return removed

    def active(self) -> tuple[ActiveSemanticDispatch, ...]:
        with self._lock:
            return tuple(self._active.values())

    @classmethod
    def _verifier_table(cls) -> dict[str, str]:
        """Skill → verifier branch name over frozen controller sub-views."""

        return {
            "NavigateTo": "navigation",
            "OrbitOwner": "spatial",
            "MoveRelative": "spatial",
            "FollowFormation": "follow",
            "SearchOwner": "search",
            # K4: navigator recovery owns ScanBehavior/SearchEntity motion;
            # verified via the instructnav branch (not NavigateTo goal match).
            "ScanBehavior": "instructnav",
            "SearchEntity": "instructnav",
            "ReturnToSafePose": "posture",
            "Pose": "posture",
            "Gesture": "activity",
            "Hold": "hold",
        }

    @staticmethod
    def _result_for(
        item: ActiveSemanticDispatch,
        state: SemanticRuntimeState,
        now: float,
    ) -> ExecutionResult:
        request = item.request
        # Table lookup keeps paused/terminal literals from drifting per skill.
        branch = SemanticTaskRuntimeAdapter._verifier_table().get(request.skill, "hold")
        if branch == "navigation":
            if state.navigation_state in NAVIGATION_SUCCESS_STATES and not state.navigation_enabled:
                expected = request.success.target
                if (
                    expected is None
                    or state.navigation_goal is None
                    or _normalized(state.navigation_goal) != _normalized(expected)
                ):
                    return _failed_result(
                        request,
                        started=item.started_at_monotonic_s,
                        snapshot_id=state.snapshot_id,
                        detail="navigation_terminal_target_mismatch",
                        finished=now,
                    )
                return _terminal_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    source="navigation_terminal_verifier",
                    detail="navigation_goal_verified",
                    finished=now,
                    verified_target=expected,
                )
            if state.navigation_state in NAVIGATION_FAILURE_STATES or (
                state.navigation_state == "idle" and not state.navigation_enabled
            ):
                return _failed_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    detail=state.navigation_reason or "navigation_ended_without_success",
                    finished=now,
                )
            detail = state.navigation_reason or state.navigation_state
        elif branch == "spatial":
            if state.spatial_state in SPATIAL_SUCCESS_STATES and not state.spatial_enabled:
                return _terminal_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    source="spatial_controller",
                    detail=state.spatial_reason or "spatial_goal_verified",
                    finished=now,
                    verified_target=("owner" if request.skill == "OrbitOwner" else None),
                )
            if state.spatial_state in SPATIAL_FAILURE_STATES or (
                state.spatial_state == "idle" and not state.spatial_enabled
            ):
                return _failed_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    detail=state.spatial_reason or "spatial_ended_without_success",
                    finished=now,
                )
            detail = state.spatial_reason or state.spatial_state
        elif branch == "follow":
            # The dispatched relation, not the controller, decides which mode
            # counts as this task's formation: a behind plan is never verified
            # by a plain-follow controller and vice versa.
            expected_mode = (
                "behind" if request.arguments.get("relation") == "behind" else "direct"
            )
            success_states = (
                FOLLOW_SUCCESS_STATES if expected_mode == "behind" else DIRECT_FOLLOW_SUCCESS_STATES
            )
            if (
                state.follow_enabled
                and state.follow_mode == expected_mode
                and state.follow_state in success_states
            ):
                return _terminal_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    source="camera_track_formation_controller",
                    detail=(
                        "behind_formation_verified"
                        if expected_mode == "behind"
                        else "owner_follow_verified"
                    ),
                    finished=now,
                    verified_target="owner",
                )
            if not state.follow_enabled or state.follow_mode != expected_mode:
                return _failed_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    detail="formation_no_longer_active",
                    finished=now,
                )
            # Acquiring, staging, blocked, and temporarily occluded states are
            # safe checkpoints. The controller remains fail-closed and the
            # executive's timeout/recovery policy decides how long to wait.
            detail = state.follow_state
        elif branch == "search":
            if state.search_state in SEARCH_SUCCESS_STATES and not state.search_enabled:
                # Two independent witnesses: the controller says it reacquired,
                # and the owner track it reacquired against is still confident
                # enough to ground ``owner_visible``. Either alone would be an
                # assertion rather than a verification.
                if state.owner_track_confidence >= OWNER_TRACK_CONFIDENCE_MIN:
                    return _terminal_result(
                        request,
                        started=item.started_at_monotonic_s,
                        snapshot_id=state.snapshot_id,
                        source="camera_owner_track_search_controller",
                        detail="owner_reacquired_verified",
                        finished=now,
                        verified_target="owner",
                        confidence=min(1.0, state.owner_track_confidence),
                    )
                return _failed_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    detail="owner_reacquisition_not_confirmed_by_track",
                    finished=now,
                )
            if state.search_state in SEARCH_FAILURE_STATES or not state.search_enabled:
                return _failed_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    detail=state.search_reason or "owner_search_ended_without_reacquisition",
                    finished=now,
                )
            detail = state.search_reason or state.search_state
        elif branch == "instructnav":
            # ScanBehavior / SearchEntity: navigator recovery is the authority.
            # skill_completed when the navigation channel reaches a terminal
            # arrived/failed after being armed; still searching stays in progress.
            if state.navigation_enabled and state.navigation_state not in (
                NAVIGATION_SUCCESS_STATES | NAVIGATION_FAILURE_STATES
            ):
                detail = state.navigation_reason or state.navigation_state
            elif state.navigation_state in NAVIGATION_SUCCESS_STATES or (
                state.navigation_state in NAVIGATION_FAILURE_STATES
                and state.navigation_reason
            ):
                return _terminal_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    source="instructnav_recovery_verifier",
                    detail=state.navigation_reason or "instructnav_recovery_complete",
                    finished=now,
                    verified_target=request.success.target,
                )
            elif not state.navigation_enabled and state.navigation_state == "idle":
                return _failed_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    detail="instructnav_recovery_not_active",
                    finished=now,
                )
            else:
                detail = state.navigation_reason or state.navigation_state
        elif branch == "posture":
            # ReturnToSafePose names it "pose"; the Pose skill names it "name".
            requested_pose = str(
                request.arguments.get("pose") or request.arguments.get("name") or ""
            )
            posture_applied = state.posture == requested_pose and bool(requested_pose)
            if (
                posture_applied
                and state.stop_confirmed
                and state.control_feedback_fresh
                and not state.robot_moving
            ):
                return _terminal_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    source="controller_feedback",
                    detail="safe_pose_stop_verified",
                    finished=now,
                    verified_target=requested_pose,
                )
            detail = (
                "waiting_for_posture_confirmation"
                if not posture_applied
                else "waiting_for_fresh_stop_confirmation"
            )
        elif branch == "activity":
            requested = str(request.arguments.get("name", ""))
            matches = (
                bool(requested)
                and state.activity_name == requested
                # Identity check: only a record created at/after this dispatch
                # can prove it. A terminal record from an earlier same-name
                # emote must neither complete nor fail this one.
                and state.activity_created_at >= item.started_at_monotonic_s
            )
            if matches and state.activity_status in {"completed", "succeeded"}:
                return _terminal_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    source="activity_coordinator",
                    detail=state.activity_detail or "gesture_completed",
                    finished=now,
                    verified_target=requested,
                )
            if matches and state.activity_status in {
                "failed",
                "rejected",
                "expired",
                "cancelled",
                "preempted",
            }:
                return _failed_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    detail=state.activity_detail or f"gesture_{state.activity_status}",
                    finished=now,
                )
            detail = state.activity_detail or "waiting_for_gesture_completion"
        else:  # hold
            if state.stop_confirmed and state.control_feedback_fresh and not state.robot_moving:
                return _terminal_result(
                    request,
                    started=item.started_at_monotonic_s,
                    snapshot_id=state.snapshot_id,
                    source="controller_feedback",
                    detail="motion_stop_verified",
                    finished=now,
                    verified_target=None,
                )
            detail = "waiting_for_fresh_stop_confirmation"

        return ExecutionResult(
            schema_version=1,
            task_id=request.task_id,
            plan_revision=request.plan_revision,
            step_id=request.step_id,
            attempt=request.attempt,
            status="in_progress",
            feedback_code="in_progress",
            snapshot_id=state.snapshot_id,
            verified_facts=(),
            checkpoint=True,
            detail_code=_detail(detail),
            started_at_monotonic_s=item.started_at_monotonic_s,
            finished_at_monotonic_s=None,
        )


def dispatch_key(request: DispatchRequest) -> DispatchKey:
    return (
        request.task_id,
        request.plan_revision,
        request.step_id,
        request.attempt,
    )


def admitted_plan_schema(
    schema: dict[str, object],
    skills: Iterable[str],
) -> dict[str, object]:
    """Return a defensive schema copy whose skill enum matches runtime support."""

    admitted = tuple(sorted(frozenset(str(item) for item in skills)))
    if not admitted:
        raise ValueError("at least one semantic skill must be admitted")
    copied = deepcopy(schema)
    try:
        definitions = copied["$defs"]
        step = definitions["step"]  # type: ignore[index]
        properties = step["properties"]  # type: ignore[index]
        skill = properties["skill"]  # type: ignore[index]
        declared = frozenset(skill["enum"])  # type: ignore[index]
    except (KeyError, TypeError) as error:
        raise ValueError("PlanIR schema does not expose the expected skill enum") from error
    unknown = frozenset(admitted) - declared
    if unknown:
        raise ValueError(f"admitted skills are absent from PlanIR schema: {sorted(unknown)}")
    skill["enum"] = list(admitted)  # type: ignore[index]
    return copied


def admitted_plan_sketch_schema(
    schema: dict[str, object],
    skills: Iterable[str],
) -> dict[str, object]:
    """Restrict a PlanSketch schema to the runtime's executable skills."""

    if planner_output_contract(schema) != PLAN_SKETCH_OUTPUT_CONTRACT:
        raise ValueError("PlanSketch schema is missing its output-contract marker")
    return admitted_plan_schema(schema, skills)


def planner_output_contract(schema: dict[str, object]) -> str:
    """Identify a trusted planner schema while preserving PlanIR compatibility."""

    if not isinstance(schema, dict) or not schema:
        raise TypeError("planner response schema must be a non-empty object")
    marker = schema.get("x-parcel-output-contract")
    # The frozen PlanIR v1 schema predates this marker. Absence therefore maps
    # only to the established legacy contract; unknown explicit markers fail.
    if marker is None:
        return PLAN_IR_OUTPUT_CONTRACT
    if marker not in PLANNER_OUTPUT_CONTRACTS:
        raise ValueError(f"unsupported planner output contract: {marker!r}")
    return str(marker)


def contextual_planner_schema(
    schema: dict[str, object],
    intent_frame: IntentFrame,
    observation: ObservationSnapshot,
) -> dict[str, object]:
    """Contextualize the selected planner contract without weakening trust."""

    contract = planner_output_contract(schema)
    if contract == PLAN_SKETCH_OUTPUT_CONTRACT:
        if not isinstance(intent_frame, IntentFrame):
            raise TypeError("contextual planner schema requires an IntentFrame")
        if not isinstance(observation, ObservationSnapshot):
            raise TypeError("contextual planner schema requires an ObservationSnapshot")
        # PlanSketch exposes no provenance fields for a model to author. Return
        # a defensive copy; compilation binds the trusted envelope afterward.
        return deepcopy(schema)
    return contextual_plan_schema(schema, intent_frame, observation)


def contextual_plan_schema(
    schema: dict[str, object],
    intent_frame: IntentFrame,
    observation: ObservationSnapshot,
) -> dict[str, object]:
    """Bind system-owned turn and correction fields before constrained decode.

    A language model may decompose the task, but it must not invent provenance,
    race an active task under a new identity, or request an immediate correction
    interrupt.  The executive remains the authority on when a replacement can
    activate.
    """

    if not isinstance(intent_frame, IntentFrame):
        raise TypeError("contextual PlanIR schema requires an IntentFrame")
    if not isinstance(observation, ObservationSnapshot):
        raise TypeError("contextual PlanIR schema requires an ObservationSnapshot")
    copied = deepcopy(schema)
    properties = copied.get("properties")
    if not isinstance(properties, dict):
        # Custom/fake providers may expose only a generic object schema.  The
        # post-decode binding below remains the authoritative enforcement.
        return copied
    source_turn = properties.get("source_turn_id")
    task_id = properties.get("task_id")
    plan_revision = properties.get("plan_revision")
    requested_interrupt = properties.get("requested_interrupt")
    for field, name in (
        (source_turn, "source_turn_id"),
        (task_id, "task_id"),
        (plan_revision, "plan_revision"),
        (requested_interrupt, "requested_interrupt"),
    ):
        if not isinstance(field, dict):
            raise TypeError(f"PlanIR schema field {name} must be an object")

    source_turn["const"] = intent_frame.turn_id
    trusted_task_id, trusted_revision = _trusted_plan_envelope(
        intent_frame,
        observation,
    )
    task_id["const"] = trusted_task_id
    plan_revision["const"] = trusted_revision
    requested_interrupt["const"] = "at_checkpoint"
    return copied


def bind_plan_context(
    plan: PlanIR,
    intent_frame: IntentFrame,
    observation: ObservationSnapshot,
) -> PlanIR:
    """Overwrite model-authored envelope metadata with trusted runtime facts.

    Some constrained-decoding backends treat JSON Schema ``const`` as a hint
    rather than an enforced grammar.  Rebinding after parsing therefore forms
    the actual trust boundary while retaining semantic plan content for normal
    validation and scoring.
    """

    if not isinstance(plan, PlanIR):
        raise TypeError("context binding requires a PlanIR")
    if not isinstance(intent_frame, IntentFrame):
        raise TypeError("context binding requires an IntentFrame")
    if not isinstance(observation, ObservationSnapshot):
        raise TypeError("context binding requires an ObservationSnapshot")
    task_id, next_revision = _trusted_plan_envelope(intent_frame, observation)
    updates: dict[str, object] = {
        "source_turn_id": intent_frame.turn_id,
        "task_id": task_id,
        "plan_revision": next_revision,
        "requested_interrupt": "at_checkpoint",
    }
    return replace(plan, **updates)


def _correction_envelope(
    intent_frame: IntentFrame,
    observation: ObservationSnapshot,
) -> tuple[str, int] | None:
    active_task_id = observation.task.task_id
    if intent_frame.speech_act != "correction" or active_task_id is None:
        return None
    active_revision = observation.task.plan_revision
    if active_revision is None:
        raise ValueError("active correction task is missing a plan revision")
    if active_revision >= 1_000_000:
        raise ValueError("active correction task exhausted the PlanIR revision range")
    return active_task_id, active_revision + 1


def _trusted_plan_envelope(
    intent_frame: IntentFrame,
    observation: ObservationSnapshot,
) -> tuple[str, int]:
    correction = _correction_envelope(intent_frame, observation)
    if correction is not None:
        return correction
    digest = hashlib.sha256(intent_frame.turn_id.encode("utf-8")).hexdigest()[:24]
    return f"parcel-task-{digest}", 1


def _terminal_result(
    request: DispatchRequest,
    *,
    started: float,
    snapshot_id: str | None,
    source: str,
    detail: str,
    verified_target: str | None,
    finished: float | None = None,
    confidence: float = 1.0,
) -> ExecutionResult:
    fact = VerifiedFact(
        fact=request.success.fact,
        target=verified_target,
        source=source,
        confidence=confidence,
    )
    return ExecutionResult(
        schema_version=1,
        task_id=request.task_id,
        plan_revision=request.plan_revision,
        step_id=request.step_id,
        attempt=request.attempt,
        status="succeeded",
        feedback_code="succeeded",
        snapshot_id=snapshot_id,
        verified_facts=(fact,),
        checkpoint=True,
        detail_code=_detail(detail),
        started_at_monotonic_s=started,
        finished_at_monotonic_s=started if finished is None else finished,
    )


def _failed_result(
    request: DispatchRequest,
    *,
    started: float,
    snapshot_id: str | None,
    detail: str,
    finished: float,
) -> ExecutionResult:
    return ExecutionResult(
        schema_version=1,
        task_id=request.task_id,
        plan_revision=request.plan_revision,
        step_id=request.step_id,
        attempt=request.attempt,
        status="failed",
        feedback_code="failed",
        snapshot_id=snapshot_id,
        verified_facts=(),
        checkpoint=True,
        detail_code=_detail(detail),
        started_at_monotonic_s=started,
        finished_at_monotonic_s=finished,
    )


def _detail(value: object) -> str:
    clean = "_".join(str(value).strip().lower().split())
    return (clean or "unknown")[:120]


def _normalized(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


__all__ = [
    "OWNER_TRACK_CONFIDENCE_MIN",
    "PLANNER_OUTPUT_CONTRACTS",
    "PLAN_IR_OUTPUT_CONTRACT",
    "PLAN_SKETCH_OUTPUT_CONTRACT",
    "ActiveSemanticDispatch",
    "DispatchKey",
    "SemanticRuntimeState",
    "SemanticTaskRuntimeAdapter",
    "admitted_plan_schema",
    "admitted_plan_sketch_schema",
    "bind_plan_context",
    "contextual_plan_schema",
    "contextual_planner_schema",
    "dispatch_key",
    "planner_output_contract",
]
