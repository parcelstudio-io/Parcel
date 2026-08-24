"""Execute frozen accepted PlanIR plans in the headless city.

Unlike ``planner_quality_v2``, this gate advances deterministic MuJoCo-world
kinematics through Parcel's production semantic navigation and spatial
controllers. Simulator truth is retained by the evaluator and is never passed
to the policy, PlanIR, executive, or semantic runtime adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parcel_robot.brain.contracts import ObservationSnapshot, PlanIR
from parcel_robot.brain.executive import TaskExecutive
from parcel_robot.brain.runtime_adapter import SemanticRuntimeState, SemanticTaskRuntimeAdapter
from parcel_robot.brain.validator import PlanValidator, SkillContractRegistry
from parcel_robot.models import SpatialIntent
from parcel_robot.simulation.headless_city import (
    DEFAULT_CITY_SCENE,
    DEFAULT_ROBOT_CONFIG,
    HeadlessCityQualityHarness,
    HeadlessCityWorld,
    HeadlessTaskResult,
)

SUITE_ID = "parcel-embodied-plan-v1"
RUNNER_VERSION = "headless-executive-adapter-v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_ROOT = Path(__file__).resolve().parent / "embodied_plan_v1"
MANIFEST_PATH = SUITE_ROOT / "manifest.json"

_SIDEWALK_REGIONS = ("sidewalk", "sidewalk_south")
_SUPPORTED_PHYSICAL_SKILLS = frozenset({"NavigateTo", "OrbitOwner", "MoveRelative", "Hold"})
_UNSUPPORTED_SKILLS = {
    "FollowFormation": (
        "fixed-owner HeadlessCityWorld has no moving-owner heading stream or "
        "formation controller integration"
    )
}


class EmbodiedPlanError(ValueError):
    """The frozen embodied corpus or execution request is invalid."""


@dataclass
class _PhysicalExecution:
    skill: str
    target: str | None
    supported: bool
    result: HeadlessTaskResult | None
    collision_delta: int
    path_start_index: int
    unsupported_reason: str | None = None


class _HeadlessRuntimeBridge:
    """Runtime callbacks backed by real closed-loop headless skill episodes."""

    def __init__(
        self,
        harness: HeadlessCityQualityHarness,
        *,
        max_steps_per_skill: int,
    ):
        self.harness = harness
        self.world = harness.world
        self.max_steps_per_skill = max_steps_per_skill
        self.executions: list[_PhysicalExecution] = []
        self.last_state = SemanticRuntimeState(snapshot_id="embodied-initial")
        self.defer_next_navigation = False
        self.unsupported_skills: dict[str, str] = {}
        self._snapshot_sequence = 0

    def navigate(self, directive: str) -> None:
        if self.defer_next_navigation:
            self.defer_next_navigation = False
            self.last_state = SemanticRuntimeState(
                snapshot_id=self._snapshot_id(),
                navigation_enabled=True,
                navigation_state="planning",
                navigation_goal=_navigation_target(directive),
                navigation_reason="checkpoint_available_before_motion",
                stop_confirmed=True,
                control_feedback_fresh=True,
                robot_moving=False,
            )
            return
        text = _navigation_text(directive)
        self._execute_headless("NavigateTo", _navigation_target(directive), text)

    def spatial_behavior(self, intent: SpatialIntent) -> None:
        if intent.behavior == "orbit_owner":
            size = "" if intent.size == "normal" else f"{intent.size} "
            text = (
                f"walk in a {size}{intent.direction} circle around owner "
                f"{_count_text(intent.revolutions)}"
            )
            self._execute_headless("OrbitOwner", "owner", text)
            return
        text = f"move {intent.direction.replace('_', ' ')} {intent.steps} steps"
        if intent.direction == "away_from_owner":
            text = f"move away from owner {intent.steps} steps"
        self._execute_headless("MoveRelative", None, text)

    def follow_formation(self, relation: str, distance_m: float) -> None:
        del relation, distance_m
        reason = _UNSUPPORTED_SKILLS["FollowFormation"]
        self.unsupported_skills["FollowFormation"] = reason
        self.executions.append(
            _PhysicalExecution(
                skill="FollowFormation",
                target="owner",
                supported=False,
                result=None,
                collision_delta=0,
                path_start_index=max(0, len(self.world.path) - 1),
                unsupported_reason=reason,
            )
        )
        self.last_state = SemanticRuntimeState(
            snapshot_id=self._snapshot_id(),
            follow_enabled=False,
            follow_state="unsupported",
            follow_mode="behind",
            stop_confirmed=self.world.stopped,
            control_feedback_fresh=True,
            robot_moving=not self.world.stopped,
        )

    def hold(self) -> None:
        self.world.stop()
        self.executions.append(
            _PhysicalExecution(
                skill="Hold",
                target=None,
                supported=True,
                result=None,
                collision_delta=0,
                path_start_index=max(0, len(self.world.path) - 1),
            )
        )
        self.last_state = SemanticRuntimeState(
            snapshot_id=self._snapshot_id(),
            stop_confirmed=True,
            control_feedback_fresh=True,
            robot_moving=False,
        )

    @staticmethod
    def vocalize(text: str) -> None:
        del text

    def _execute_headless(self, skill: str, target: str | None, text: str) -> None:
        path_start = max(0, len(self.world.path) - 1)
        collisions_before = self.world.collision_count
        result = self.harness.run(text, max_steps=self.max_steps_per_skill)
        self.executions.append(
            _PhysicalExecution(
                skill=skill,
                target=target,
                supported=True,
                result=result,
                collision_delta=self.world.collision_count - collisions_before,
                path_start_index=path_start,
            )
        )
        succeeded = result.succeeded
        common = {
            "snapshot_id": self._snapshot_id(),
            "stop_confirmed": result.stopped,
            "control_feedback_fresh": True,
            "robot_moving": not result.stopped,
        }
        if skill == "NavigateTo":
            self.last_state = SemanticRuntimeState(
                **common,
                navigation_enabled=not succeeded and not result.timed_out,
                navigation_state=("arrived" if succeeded else "failed"),
                navigation_goal=target,
                navigation_reason=result.reason,
            )
        else:
            self.last_state = SemanticRuntimeState(
                **common,
                spatial_enabled=not succeeded and not result.timed_out,
                spatial_state=("completed" if succeeded else "failed"),
                spatial_reason=result.reason,
            )

    def _snapshot_id(self) -> str:
        self._snapshot_sequence += 1
        return f"embodied-controller-{self._snapshot_sequence}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EmbodiedPlanError(f"cannot load {path}: {error}") from error


def load_frozen_suite(
    manifest_path: str | Path = MANIFEST_PATH,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load and hash-verify episodes, planner cases, and admitted plans."""

    path = Path(manifest_path).resolve()
    manifest = _load_json(path)
    if not isinstance(manifest, dict):
        raise EmbodiedPlanError("manifest must be one JSON object")
    required = {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "frozen": True,
        "case_count": 5,
        "base_motion": "deterministic_kinematic_mujoco_geometry",
        "evaluator_truth_available_to_policy": False,
    }
    for key, expected in required.items():
        if manifest.get(key) != expected:
            raise EmbodiedPlanError(f"manifest {key} must equal {expected!r}")

    locked = manifest.get("locked_inputs")
    if not isinstance(locked, dict) or not locked:
        raise EmbodiedPlanError("manifest locked_inputs must be a non-empty object")
    resolved: dict[str, Path] = {}
    for name, item in locked.items():
        if not isinstance(name, str) or not isinstance(item, dict):
            raise EmbodiedPlanError("locked input entries must be named objects")
        relative = item.get("path")
        expected_digest = item.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected_digest, str):
            raise EmbodiedPlanError(f"locked input {name} requires path and sha256")
        candidate = (REPO_ROOT / relative).resolve()
        if not candidate.is_relative_to(REPO_ROOT) or not candidate.is_file():
            raise EmbodiedPlanError(f"locked input {name} is outside or missing from repository")
        if _sha256(candidate) != expected_digest:
            raise EmbodiedPlanError(f"locked input {name} failed SHA-256 verification")
        resolved[name] = candidate

    expected_names = {
        "episodes",
        "planner_cases",
        "accepted_plans",
        "city_scene",
        "robot_config",
        "result_schema",
    }
    if set(resolved) != expected_names:
        raise EmbodiedPlanError("manifest locked inputs do not match the v1 contract")

    episodes_raw = _load_json(resolved["episodes"])
    planner_cases_raw = _load_json(resolved["planner_cases"])
    accepted_raw = _load_json(resolved["accepted_plans"])
    if not isinstance(episodes_raw, list) or not all(
        isinstance(item, dict) for item in episodes_raw
    ):
        raise EmbodiedPlanError("episodes must be an array of objects")
    if not isinstance(planner_cases_raw, list) or not all(
        isinstance(item, dict) for item in planner_cases_raw
    ):
        raise EmbodiedPlanError("planner cases must be an array of objects")
    if not isinstance(accepted_raw, dict) or not isinstance(accepted_raw.get("cases"), list):
        raise EmbodiedPlanError("accepted plan result has no cases array")

    case_ids = [item.get("case_id") for item in planner_cases_raw]
    episode_ids = [item.get("case_id") for item in episodes_raw]
    if len(case_ids) != manifest["case_count"] or episode_ids != case_ids:
        raise EmbodiedPlanError("episode order must exactly match the frozen planner cases")
    seeds = [item.get("seed") for item in episodes_raw]
    if any(isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds):
        raise EmbodiedPlanError("every episode seed must be an integer")
    if len(set(seeds)) != len(seeds):
        raise EmbodiedPlanError("episode seeds must be unique")

    accepted_by_id: dict[str, dict[str, Any]] = {}
    for item in accepted_raw["cases"]:
        if not isinstance(item, dict) or not isinstance(item.get("case_id"), str):
            raise EmbodiedPlanError("accepted plan cases must be named objects")
        if item.get("passed") is not True or not isinstance(item.get("admitted_plan"), dict):
            raise EmbodiedPlanError(f"accepted plan {item.get('case_id')} is not admitted")
        accepted_by_id[str(item["case_id"])] = item
    if set(accepted_by_id) != set(case_ids):
        raise EmbodiedPlanError("accepted-plan case IDs do not match frozen planner cases")

    merged: list[dict[str, Any]] = []
    for episode, planner_case in zip(episodes_raw, planner_cases_raw, strict=True):
        merged.append({**episode, "planner_case": planner_case})
    return manifest, merged, accepted_by_id


def _validation_snapshot(case: Mapping[str, object], *, index: int) -> ObservationSnapshot:
    """Recreate the frozen camera/LiDAR admission snapshot without simulator truth."""

    del index
    planner_case = case.get("planner_case")
    if not isinstance(planner_case, Mapping):
        raise EmbodiedPlanError("episode has no planner case")
    fixture = planner_case.get("snapshot")
    if not isinstance(fixture, Mapping):
        raise EmbodiedPlanError("planner case snapshot must be an object")
    raw_entities = fixture.get("entities", [])
    if not isinstance(raw_entities, list):
        raise EmbodiedPlanError("planner case entities must be a list")
    entities: list[dict[str, object]] = []
    for entity_index, item in enumerate(raw_entities):
        if not isinstance(item, Mapping):
            raise EmbodiedPlanError("planner entities must contain objects")
        attributes = item.get("attributes", {})
        if not isinstance(attributes, Mapping):
            raise EmbodiedPlanError("entity attributes must be an object")
        entities.append(
            {
                "entity_id": f"{item['kind']}-{item['label']}-{entity_index + 1}",
                "kind": item["kind"],
                "label": item["label"],
                "confidence": float(item.get("confidence", 0.95)),
                "source": "camera_semantic_fixture",
                "observed_at_monotonic_s": 99.95,
                "attributes": dict(attributes),
            }
        )
    task = fixture.get(
        "task",
        {
            "state": "idle",
            "task_id": None,
            "plan_revision": None,
            "step_id": None,
            "at_checkpoint": True,
        },
    )
    return ObservationSnapshot.from_mapping(
        {
            "schema_version": 1,
            "snapshot_id": f"embodied-admission-{planner_case['case_id']}",
            "captured_at_monotonic_s": 100.0,
            "camera": {
                "name": "camera",
                "available": True,
                "fresh": True,
                "source": "camera_semantic_fixture",
                "observed_at_monotonic_s": 99.95,
                "age_ms": 50.0,
            },
            "lidar": {
                "name": "lidar",
                "available": True,
                "fresh": True,
                "source": "lidar_fixture",
                "observed_at_monotonic_s": 99.98,
                "age_ms": 20.0,
            },
            "robot": {
                "moving": False,
                "controller_state": "ready",
                "x": None,
                "y": None,
                "z": None,
                "yaw_rad": None,
            },
            "safety": {
                "emergency_stopped": False,
                "collision_imminent": False,
                "telemetry_fresh": True,
                "nearest_obstacle_m": 2.5,
                "nearest_person_m": None,
            },
            "battery": {
                "state": "normal",
                "percent": 80.0,
                "source": "controller_telemetry",
            },
            "task": dict(task),
            "resource_leases": [],
            "entities": entities,
        }
    )


def _incumbent_plan() -> PlanIR:
    return PlanIR.from_mapping(
        {
            "schema_version": 1,
            "task_id": "active-navigation",
            "plan_revision": 1,
            "source_turn_id": "embodied-incumbent-navigation",
            "goal": {
                "relation": "inside",
                "target": {"kind": "semantic_region", "query": "sidewalk"},
                "tolerance_m": 0.0,
            },
            "invariants": [],
            "steps": [
                {
                    "id": "old-navigation",
                    "skill": "NavigateTo",
                    "arguments": {"directive": "sidewalk"},
                    "preconditions": [
                        "base_available",
                        "camera_fresh",
                        "lidar_fresh",
                        "target_grounded",
                    ],
                    "success": {
                        "fact": "inside",
                        "target": "sidewalk",
                        "tolerance_m": None,
                        "confidence_min": None,
                    },
                    "timeout_s": 120.0,
                    "max_attempts": 1,
                    "recovery": ["safe_stop"],
                    "resources": ["base", "attention"],
                    "interruptibility": "checkpoint",
                }
            ],
            "requested_interrupt": "at_checkpoint",
        }
    )


def _incumbent_snapshot() -> ObservationSnapshot:
    return ObservationSnapshot.from_mapping(
        {
            "schema_version": 1,
            "snapshot_id": "embodied-incumbent-admission",
            "captured_at_monotonic_s": 100.0,
            "camera": {
                "name": "camera",
                "available": True,
                "fresh": True,
                "source": "camera_semantic_fixture",
                "observed_at_monotonic_s": 99.95,
                "age_ms": 50.0,
            },
            "lidar": {
                "name": "lidar",
                "available": True,
                "fresh": True,
                "source": "lidar_fixture",
                "observed_at_monotonic_s": 99.98,
                "age_ms": 20.0,
            },
            "robot": {
                "moving": False,
                "controller_state": "ready",
                "x": None,
                "y": None,
                "z": None,
                "yaw_rad": None,
            },
            "safety": {
                "emergency_stopped": False,
                "collision_imminent": False,
                "telemetry_fresh": True,
                "nearest_obstacle_m": 2.5,
                "nearest_person_m": None,
            },
            "battery": {"state": "normal", "percent": 80.0, "source": "telemetry"},
            "task": {
                "state": "idle",
                "task_id": None,
                "plan_revision": None,
                "step_id": None,
                "at_checkpoint": True,
            },
            "resource_leases": [],
            "entities": [
                {
                    "entity_id": "semantic-region-sidewalk-incumbent",
                    "kind": "semantic_region",
                    "label": "sidewalk",
                    "confidence": 0.96,
                    "source": "camera_semantic_fixture",
                    "observed_at_monotonic_s": 99.95,
                    "attributes": {},
                }
            ],
        }
    )


def _validator() -> PlanValidator:
    registry = SkillContractRegistry.default(owner_heading_supported=True).restricted(
        SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS
    )
    return PlanValidator(registry)


def _runtime_adapter(bridge: _HeadlessRuntimeBridge) -> SemanticTaskRuntimeAdapter:
    return SemanticTaskRuntimeAdapter(
        navigate=bridge.navigate,
        follow_formation=bridge.follow_formation,
        spatial_behavior=bridge.spatial_behavior,
        hold=bridge.hold,
        vocalize=bridge.vocalize,
    )


def _run_executive(
    validated,
    snapshot: ObservationSnapshot,
    bridge: _HeadlessRuntimeBridge,
    *,
    correction: bool,
) -> dict[str, object]:
    executive = TaskExecutive()
    adapter = _runtime_adapter(bridge)
    events: list[dict[str, object]] = []
    checkpoint: dict[str, object] = {
        "replacement_deferred": False,
        "replacement_activated_at_checkpoint": False,
        "stale_incumbent_dispatch_reconciled": False,
        "incumbent_simulator_steps": 0,
    }

    if correction:
        incumbent = _validator().validate(_incumbent_plan(), _incumbent_snapshot())
        submission = executive.submit(incumbent)
        events.append({"event": "submit_incumbent", **asdict(submission)})
        dispatched = executive.tick(_incumbent_snapshot(), now=0.0)
        if len(dispatched) != 1:
            raise EmbodiedPlanError("incumbent correction task did not dispatch exactly once")
        bridge.defer_next_navigation = True
        adapter.dispatch(dispatched[0], now=0.0)
        events.append(
            {
                "event": "dispatch_incumbent",
                "step_id": dispatched[0].step_id,
                "skill": dispatched[0].skill,
            }
        )
        replacement = executive.replace(validated)
        events.append({"event": "replace_requested", **asdict(replacement)})
        checkpoint["replacement_deferred"] = replacement.disposition == "defer"
        progress = adapter.poll(bridge.last_state, now=0.0)
        if len(progress) != 1 or progress[0].status != "in_progress":
            raise EmbodiedPlanError("incumbent did not expose an in-progress checkpoint")
        disposition = executive.report(progress[0])
        events.append({"event": "checkpoint_report", **asdict(disposition)})
        checkpoint["replacement_activated_at_checkpoint"] = (
            disposition.action == "replacement_activated_at_checkpoint"
        )
        removed = adapter.reconcile(())
        checkpoint["stale_incumbent_dispatch_reconciled"] = len(removed) == 1
    else:
        submission = executive.submit(validated)
        events.append({"event": "submit", **asdict(submission)})
        if not submission.accepted:
            raise EmbodiedPlanError(f"executive rejected validated task: {submission.reason}")

    for _ in range(32):
        final = _task_snapshot(executive, validated.plan.task_id)
        if final is not None and final["state"] in {"succeeded", "failed", "cancelled"}:
            break
        requests = executive.tick(snapshot, now=float(bridge.world.data.time))
        if not requests:
            final = _task_snapshot(executive, validated.plan.task_id)
            if final is not None and final["state"] == "waiting_precondition":
                break
            continue
        if len(requests) != 1:
            raise EmbodiedPlanError("executive emitted more than one semantic dispatch")
        request = requests[0]
        events.append(
            {
                "event": "dispatch",
                "step_id": request.step_id,
                "skill": request.skill,
                "attempt": request.attempt,
            }
        )
        immediate = adapter.dispatch(request, now=float(bridge.world.data.time))
        results = (
            (immediate,)
            if immediate is not None
            else adapter.poll(
                bridge.last_state,
                now=float(bridge.world.data.time),
            )
        )
        if len(results) != 1:
            raise EmbodiedPlanError("runtime adapter produced an invalid result count")
        result = results[0]
        disposition = executive.report(result)
        events.append(
            {
                "event": "result",
                "step_id": request.step_id,
                "skill": request.skill,
                "result_status": result.status,
                "feedback_code": result.feedback_code,
                "detail_code": result.detail_code,
                "report_action": disposition.action,
            }
        )
    else:
        raise EmbodiedPlanError("executive exceeded the bounded dispatch loop")

    final = _task_snapshot(executive, validated.plan.task_id)
    if final is None:
        raise EmbodiedPlanError("executive lost the evaluated task")
    return {
        "submission": events[0],
        "final_task": final,
        "events": events,
        "checkpoint_correction": checkpoint if correction else None,
    }


def _task_snapshot(executive: TaskExecutive, task_id: str) -> dict[str, object] | None:
    tasks = executive.snapshot()["tasks"]
    return next((item for item in tasks if item["task_id"] == task_id), None)


def _execute_case(
    case: Mapping[str, object],
    accepted: Mapping[str, object],
    *,
    index: int,
) -> dict[str, object]:
    case_id = str(case["case_id"])
    plan = PlanIR.from_mapping(accepted["admitted_plan"])
    snapshot = _validation_snapshot(case, index=index)
    validated = _validator().validate(plan, snapshot)
    start = _float_tuple(case.get("robot_start"), 3, "robot_start")
    owner = _float_tuple(case.get("owner_start"), 2, "owner_start")
    max_steps = case.get("max_steps_per_skill")
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps <= 0:
        raise EmbodiedPlanError("max_steps_per_skill must be a positive integer")

    world = HeadlessCityWorld(DEFAULT_CITY_SCENE)
    world.reset(robot=start, owner=owner)
    harness = HeadlessCityQualityHarness(world, robot_config=DEFAULT_ROBOT_CONFIG)
    bridge = _HeadlessRuntimeBridge(harness, max_steps_per_skill=max_steps)
    initial_pose = _pose(world.observe())
    correction = case_id == "correct_active_task_to_lamppost"
    executive_result = _run_executive(
        validated,
        snapshot,
        bridge,
        correction=correction,
    )
    semantic = _score_case(case, bridge, initial_pose, owner, executive_result)
    unsupported = sorted(bridge.unsupported_skills)
    final_state = str(executive_result["final_task"]["state"])
    if unsupported:
        status = "unsupported"
        reason = "unsupported_skills:" + ",".join(unsupported)
    elif final_state == "succeeded" and semantic["passed"] is True:
        status = "passed"
        reason = "executive_and_evaluator_semantics_satisfied"
    else:
        status = "failed"
        reason = (
            "executive_" + final_state
            if final_state != "succeeded"
            else "evaluator_semantics_failed"
        )
    physical = _physical_report(bridge, initial_pose)
    return {
        "case_id": case_id,
        "seed": int(case["seed"]),
        "status": status,
        "reason": reason,
        "support": {
            "status": "unsupported" if unsupported else "supported",
            "supported_physical_skills": sorted(_SUPPORTED_PHYSICAL_SKILLS),
            "unsupported_skills": [
                {"skill": skill, "reason": bridge.unsupported_skills[skill]}
                for skill in unsupported
            ],
        },
        "plan": {
            "task_id": plan.task_id,
            "plan_revision": plan.plan_revision,
            "source_turn_id": plan.source_turn_id,
            "validated_plan_sha256": validated.plan_sha256,
            "validated_against_snapshot_id": validated.validated_against_snapshot_id,
            "skills": [step.skill for step in plan.steps],
        },
        "executive": executive_result,
        "physical": physical,
        "semantic": semantic,
    }


def _physical_report(
    bridge: _HeadlessRuntimeBridge,
    initial_pose: Mapping[str, float],
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    simulator_steps = 0
    timeout_count = 0
    collision_count = 0
    for execution in bridge.executions:
        result = execution.result
        steps = len(result.trace) if result is not None else 0
        simulator_steps += steps
        collision_count += execution.collision_delta
        timeout_count += int(result.timed_out) if result is not None else 0
        records.append(
            {
                "skill": execution.skill,
                "target": execution.target,
                "supported": execution.supported,
                "unsupported_reason": execution.unsupported_reason,
                "controller_status": result.status if result is not None else None,
                "controller_reason": result.reason if result is not None else None,
                "simulator_step_count": steps,
                "collision_count": execution.collision_delta,
                "minimum_clearance_m": (
                    _finite_round(result.minimum_clearance_m) if result is not None else None
                ),
                "required_clearance_m": (
                    _finite_round(result.required_obstacle_clearance_m)
                    if result is not None
                    else None
                ),
                "terminal_stopped": result.stopped if result is not None else bridge.world.stopped,
                "timed_out": result.timed_out if result is not None else False,
            }
        )
    final = bridge.world.observe()
    return {
        "backend": final.backend,
        "base_motion": "deterministic_kinematic_mujoco_geometry",
        "policy_observation_contract": ["camera", "lidar", "owner_track", "odometry"],
        "evaluator_truth_available_to_policy": False,
        "physical_skill_episode_count": sum(
            item.supported and item.result is not None for item in bridge.executions
        ),
        "simulator_step_count": simulator_steps,
        "collision_count": collision_count,
        "timeout_count": timeout_count,
        "minimum_clearance_m": _finite_round(bridge.world.minimum_clearance_m),
        "initial_pose": dict(initial_pose),
        "final_pose": _pose(final),
        "terminal_stopped": bridge.world.stopped,
        "executions": records,
    }


def _score_case(
    case: Mapping[str, object],
    bridge: _HeadlessRuntimeBridge,
    initial_pose: Mapping[str, float],
    owner: tuple[float, float],
    executive_result: Mapping[str, object],
) -> dict[str, object]:
    evaluator = str(case["evaluator"])
    if evaluator == "sidewalk_inside_off_road":
        checks, metrics = _score_sidewalk(bridge, occurrence=0)
    elif evaluator == "sidewalk_then_lamppost_vicinity":
        sidewalk_checks, sidewalk_metrics = _score_sidewalk(bridge, occurrence=0)
        lamp_checks, lamp_metrics = _score_lamppost(bridge)
        checks = {f"sidewalk_{key}": value for key, value in sidewalk_checks.items()}
        checks.update({f"lamppost_{key}": value for key, value in lamp_checks.items()})
        metrics = {"sidewalk": sidewalk_metrics, "lamppost": lamp_metrics}
    elif evaluator == "away_five_steps":
        checks, metrics = _score_away(bridge, initial_pose, owner)
    elif evaluator == "orbit_then_follow_behind":
        checks, metrics = _score_orbit(bridge, owner)
        checks["follow_behind_supported"] = False
    elif evaluator == "checkpoint_correction_to_lamppost":
        checks, metrics = _score_lamppost(bridge)
        checkpoint = executive_result.get("checkpoint_correction")
        if not isinstance(checkpoint, Mapping):
            raise EmbodiedPlanError("correction case is missing checkpoint evidence")
        checks.update(
            {
                "replacement_deferred": checkpoint["replacement_deferred"] is True,
                "replacement_activated_at_checkpoint": (
                    checkpoint["replacement_activated_at_checkpoint"] is True
                ),
                "stale_incumbent_dispatch_reconciled": (
                    checkpoint["stale_incumbent_dispatch_reconciled"] is True
                ),
                "incumbent_did_not_move_before_checkpoint": (
                    checkpoint["incumbent_simulator_steps"] == 0
                ),
            }
        )
    else:
        raise EmbodiedPlanError(f"unknown evaluator: {evaluator}")

    safety = _safety_checks(bridge)
    checks.update(safety)
    unsupported = bool(bridge.unsupported_skills)
    return {
        "evaluator": evaluator,
        "passed": None if unsupported else all(checks.values()),
        "checks": checks,
        "metrics": metrics,
    }


def _score_sidewalk(
    bridge: _HeadlessRuntimeBridge,
    *,
    occurrence: int,
) -> tuple[dict[str, bool], dict[str, object]]:
    navigations = [
        item for item in bridge.executions if item.skill == "NavigateTo" and item.result is not None
    ]
    if occurrence >= len(navigations):
        return {"controller_arrived": False, "inside": False, "off_road": False}, {}
    result = navigations[occurrence].result
    assert result is not None
    final = (result.final_observation.robot.x, result.final_observation.robot.y)
    region_id = result.target_id if result.target_id in _SIDEWALK_REGIONS else "sidewalk"
    metadata = bridge.world.truth_region_metadata(region_id)
    required = float(metadata["terminal_clearance_m"])
    inside = bridge.world.truth_inside_region(final, region_id, clearance_m=required)
    off_road = any(bridge.world.truth_inside_region(final, item) for item in _SIDEWALK_REGIONS)
    return (
        {
            "controller_arrived": result.succeeded,
            "inside": inside,
            "off_road": off_road,
            "terminal_stopped": result.stopped,
        },
        {
            "region_id": region_id,
            "required_interior_clearance_m": required,
            "final_xy": [_finite_round(value) for value in final],
        },
    )


def _score_lamppost(
    bridge: _HeadlessRuntimeBridge,
) -> tuple[dict[str, bool], dict[str, object]]:
    candidates = [
        item
        for item in bridge.executions
        if item.skill == "NavigateTo"
        and item.result is not None
        and item.result.terminal_relation == "near"
    ]
    if not candidates:
        return {
            "controller_arrived": False,
            "near_surface_le_1m": False,
            "on_sidewalk": False,
        }, {}
    result = candidates[-1].result
    assert result is not None
    object_id = result.target_id or "lamp_post_1"
    final = (result.final_observation.robot.x, result.final_observation.robot.y)
    center_x, center_y, _ = bridge.world.truth_object(object_id)
    metadata = bridge.world.truth_object_metadata(object_id)
    center_distance = math.hypot(final[0] - center_x, final[1] - center_y)
    surface_distance = bridge.world.truth_object_surface_distance(final, object_id)
    support_region = str(metadata.get("support_region_id") or metadata["support_label"])
    support_clearance = float(metadata["terminal_support_clearance_m"])
    on_sidewalk = bridge.world.truth_inside_region(
        final,
        support_region,
        clearance_m=support_clearance,
    )
    return (
        {
            "controller_arrived": result.succeeded,
            "near_surface_le_1m": 0.0 <= surface_distance <= 1.0,
            "common_sense_center_vicinity": (
                float(metadata["minimum_vicinity_radius_m"])
                <= center_distance
                <= float(metadata["vicinity_radius_m"])
            ),
            "on_sidewalk": on_sidewalk,
            "off_road": on_sidewalk,
            "terminal_stopped": result.stopped,
        },
        {
            "object_id": object_id,
            "surface_distance_m": _finite_round(surface_distance),
            "center_distance_m": _finite_round(center_distance),
            "maximum_surface_distance_m": 1.0,
            "support_region_id": support_region,
            "support_clearance_m": support_clearance,
            "final_xy": [_finite_round(value) for value in final],
        },
    )


def _score_away(
    bridge: _HeadlessRuntimeBridge,
    initial_pose: Mapping[str, float],
    owner: tuple[float, float],
) -> tuple[dict[str, bool], dict[str, object]]:
    spatial = next(
        (
            item
            for item in bridge.executions
            if item.skill == "MoveRelative" and item.result is not None
        ),
        None,
    )
    if spatial is None:
        return {"controller_completed": False, "five_step_distance": False}, {}
    result = spatial.result
    assert result is not None
    start = (float(initial_pose["x"]), float(initial_pose["y"]))
    final = (result.final_observation.robot.x, result.final_observation.robot.y)
    away = (start[0] - owner[0], start[1] - owner[1])
    norm = math.hypot(*away)
    projected = ((final[0] - start[0]) * away[0] + (final[1] - start[1]) * away[1]) / norm
    target = 5 * bridge.harness.spatial_config.step_length_m
    lower = target - 0.06
    upper = target + 0.15
    owner_distance_before = math.hypot(start[0] - owner[0], start[1] - owner[1])
    owner_distance_after = math.hypot(final[0] - owner[0], final[1] - owner[1])
    return (
        {
            "controller_completed": result.succeeded,
            "five_step_distance": lower <= projected <= upper,
            "owner_distance_increased": owner_distance_after > owner_distance_before,
            "terminal_stopped": result.stopped,
        },
        {
            "step_length_m": bridge.harness.spatial_config.step_length_m,
            "target_distance_m": target,
            "accepted_projected_range_m": [lower, upper],
            "projected_away_distance_m": _finite_round(projected),
            "owner_distance_before_m": _finite_round(owner_distance_before),
            "owner_distance_after_m": _finite_round(owner_distance_after),
        },
    )


def _score_orbit(
    bridge: _HeadlessRuntimeBridge,
    owner: tuple[float, float],
) -> tuple[dict[str, bool], dict[str, object]]:
    spatial = next(
        (item for item in bridge.executions if item.skill == "OrbitOwner" and item.result),
        None,
    )
    if spatial is None or spatial.result is None:
        return {"controller_completed": False, "winding": False}, {}
    result = spatial.result
    try:
        orbit_start = next(
            index for index, sample in enumerate(result.trace) if sample.note == "orbit_owner"
        )
    except StopIteration:
        return {"controller_completed": result.succeeded, "winding": False}, {}
    points = [(sample.robot.x, sample.robot.y) for sample in result.trace[orbit_start:]]
    angles = [math.atan2(y - owner[1], x - owner[0]) for x, y in points]
    unwrapped = [angles[0]]
    for angle in angles[1:]:
        delta = (angle - unwrapped[-1] + math.pi) % (2.0 * math.pi) - math.pi
        unwrapped.append(unwrapped[-1] + delta)
    winding = unwrapped[-1] - unwrapped[0]
    bins = {int(((angle % (2.0 * math.pi)) / (2.0 * math.pi)) * 12) % 12 for angle in angles}
    radii = [math.hypot(x - owner[0], y - owner[1]) for x, y in points]
    endpoint_error = math.hypot(points[-1][0] - points[0][0], points[-1][1] - points[0][1])
    config = bridge.harness.spatial_config
    angle_tolerance = 2.0 * math.asin(
        config.waypoint_tolerance_m / (2.0 * config.default_orbit_radius_m)
    )
    return (
        {
            "controller_completed": result.succeeded,
            "clockwise_winding": winding <= -(2.0 * math.pi - angle_tolerance),
            "full_angular_coverage": len(bins) == 12,
            "radial_corridor": (
                min(radii) >= config.default_orbit_radius_m - config.waypoint_tolerance_m
                and max(radii) <= config.default_orbit_radius_m + config.waypoint_tolerance_m
            ),
            "endpoint_closed": endpoint_error <= 2.0 * config.waypoint_tolerance_m,
            "terminal_stopped": result.stopped,
        },
        {
            "signed_winding_rad": _finite_round(winding),
            "required_clockwise_winding_rad": _finite_round(-(2.0 * math.pi - angle_tolerance)),
            "occupied_angular_bins": len(bins),
            "minimum_radius_m": _finite_round(min(radii)),
            "maximum_radius_m": _finite_round(max(radii)),
            "endpoint_error_m": _finite_round(endpoint_error),
        },
    )


def _safety_checks(bridge: _HeadlessRuntimeBridge) -> dict[str, bool]:
    results = [item.result for item in bridge.executions if item.result is not None]
    return {
        "collision_free": bridge.world.collision_count == 0,
        "clearance_respected": all(
            result.minimum_clearance_m + 1e-9 >= result.required_obstacle_clearance_m
            for result in results
        ),
        "no_timeout": all(not result.timed_out for result in results),
        "final_stop_confirmed": bridge.world.stopped,
        "simulator_steps_executed": sum(len(result.trace) for result in results) > 0,
    }


def run_suite(
    *,
    manifest_path: str | Path = MANIFEST_PATH,
    case_ids: Sequence[str] = (),
    change_description: str = "Frozen admitted PlanIR embodied baseline",
    run_id: str | None = None,
    recorded_at_utc: str | None = None,
) -> dict[str, object]:
    manifest, cases, accepted = load_frozen_suite(manifest_path)
    selected = set(case_ids)
    known = {str(case["case_id"]) for case in cases}
    unknown = selected - known
    if unknown:
        raise EmbodiedPlanError(f"unknown case IDs: {', '.join(sorted(unknown))}")
    selected_cases = [case for case in cases if not selected or case["case_id"] in selected]
    if not selected_cases:
        raise EmbodiedPlanError("no embodied cases selected")
    description = change_description.strip()
    if not description or len(description) > 500:
        raise EmbodiedPlanError("change description must contain 1..500 characters")

    results = [
        _execute_case(case, accepted[str(case["case_id"])], index=index)
        for index, case in enumerate(selected_cases)
    ]
    passed = sum(item["status"] == "passed" for item in results)
    failed = sum(item["status"] == "failed" for item in results)
    unsupported = sum(item["status"] == "unsupported" for item in results)
    supported = passed + failed
    clearances = [float(item["physical"]["minimum_clearance_m"]) for item in results]
    timestamp = recorded_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    identifier = run_id or _run_id(timestamp)
    return {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "run_id": identifier,
        "recorded_at_utc": timestamp,
        "change_description": description,
        "corpus": {
            "frozen": True,
            "manifest_sha256": _sha256(Path(manifest_path).resolve()),
            "locked_inputs": manifest["locked_inputs"],
            "selected_case_ids": [item["case_id"] for item in results],
            "seeds": [item["seed"] for item in results],
        },
        "aggregate": {
            "case_count": len(results),
            "passed_case_count": passed,
            "failed_case_count": failed,
            "unsupported_case_count": unsupported,
            "supported_case_count": supported,
            "supported_case_success_rate": passed / supported if supported else None,
            "physical_skill_episode_count": sum(
                int(item["physical"]["physical_skill_episode_count"]) for item in results
            ),
            "simulator_step_count": sum(
                int(item["physical"]["simulator_step_count"]) for item in results
            ),
            "collision_count": sum(int(item["physical"]["collision_count"]) for item in results),
            "timeout_count": sum(int(item["physical"]["timeout_count"]) for item in results),
            "minimum_clearance_m": _finite_round(min(clearances)),
            "simulator_steps_per_case": _summary(
                [float(item["physical"]["simulator_step_count"]) for item in results]
            ),
        },
        "cases": results,
        "claims": {
            "proves": [
                "accepted PlanIR dispatch through TaskExecutive and SemanticTaskRuntimeAdapter",
                "deterministic kinematic execution by production semantic navigation and spatial controllers",
                "evaluator-truth sidewalk, lamppost, away-distance, orbit, collision, clearance, timeout, and stop scoring",
                "checkpoint-gated correction activation for the frozen correction case",
            ],
            "does_not_prove": [
                "Unitree contact dynamics, hardware locomotion, actuator safety, or real sensor accuracy",
                "moving-owner FollowFormation, which is explicitly unsupported in v1",
                "planner generalization beyond the five frozen cases",
                "top-percentile performance on any external navigation benchmark",
            ],
        },
    }


def write_report(report: Mapping[str, object], path: str | Path) -> Path:
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing embodied result: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return target


def _navigation_target(directive: str) -> str:
    normalized = " ".join(str(directive).lower().split())
    return "lamppost" if "lamp" in normalized else "sidewalk"


def _navigation_text(directive: str) -> str:
    target = _navigation_target(directive)
    return "wait by the lamppost" if target == "lamppost" else "walk to the sidewalk"


def _count_text(revolutions: float) -> str:
    return "one" if abs(revolutions - 1.0) <= 1e-9 else str(revolutions)


def _float_tuple(value: object, length: int, field: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise EmbodiedPlanError(f"{field} must contain {length} numbers")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise EmbodiedPlanError(f"{field} values must be finite")
    return result


def _pose(observation) -> dict[str, float]:
    return {
        "x": _finite_round(observation.robot.x),
        "y": _finite_round(observation.robot.y),
        "yaw_rad": _finite_round(observation.robot.yaw),
    }


def _finite_round(value: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise EmbodiedPlanError("result metric is non-finite")
    return round(numeric, 6)


def _summary(values: Sequence[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "minimum": round(ordered[0], 3),
        "median": round(statistics.median(ordered), 3),
        "mean": round(statistics.fmean(ordered), 3),
        "maximum": round(ordered[-1], 3),
    }


def _run_id(timestamp: str) -> str:
    compact = "".join(character for character in timestamp if character.isdigit())[:14]
    nonce = hashlib.sha256(f"{timestamp}:{time.monotonic_ns()}".encode()).hexdigest()[:8]
    return f"embodied-plan-v1-{compact}Z-{nonce}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--description", default="Frozen admitted PlanIR embodied baseline")
    parser.add_argument("--run-id")
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_suite(
        case_ids=args.case_id,
        change_description=args.description,
        run_id=args.run_id,
    )
    try:
        write_report(report, args.output)
    except FileExistsError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(report, indent=None if args.compact else 2, sort_keys=True))
    return 1 if report["aggregate"]["failed_case_count"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
