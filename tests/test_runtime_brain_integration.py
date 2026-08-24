from __future__ import annotations

import time
from pathlib import Path

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain.contracts import PlanIR
from parcel_robot.brain.plan_sketch import PlanSketch
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]


class _Backend:
    name = "brain-test"

    def __init__(self) -> None:
        self.moves: list[VelocityCommand] = []
        self.stops = 0

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            backend=self.name,
        )

    def move(self, command: VelocityCommand) -> None:
        self.moves.append(command)

    def stop(self) -> None:
        self.stops += 1

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _PlanningModel:
    def __init__(self, revisions: list[tuple[str, int]] | None = None) -> None:
        self.revisions = list(revisions or [("task-compound", 1)])
        self.plan_calls: list[tuple[str, dict[str, object]]] = []
        self.decide_calls = 0
        self.last_metrics: dict[str, object] = {}

    def plan(self, transcript: str, **kwargs: object) -> PlanIR:
        self.plan_calls.append((transcript, kwargs))
        intent = kwargs["intent_frame"]
        task_id, revision = self.revisions.pop(0)
        return _hold_plan(task_id, revision, intent.turn_id)

    def decide(
        self,
        transcript: str,
        tools: list[dict[str, object]],
        context: list[dict[str, str]],
    ) -> AgentDecision:
        del transcript, tools, context
        self.decide_calls += 1
        return AgentDecision("The fast conversation path should not run.")


class _SketchPlanningModel(_PlanningModel):
    def plan(self, transcript: str, **kwargs: object) -> PlanSketch:
        self.plan_calls.append((transcript, kwargs))
        return PlanSketch.from_mapping(
            {
                "schema_version": 1,
                "goal": {"relation": "hold", "kind": "current_pose", "query": ""},
                "steps": [{"skill": "Hold", "arguments": {}, "navigation": None}],
            }
        )


def _hold_plan(task_id: str, revision: int, source_turn_id: str) -> PlanIR:
    return PlanIR.from_mapping(
        {
            "schema_version": 1,
            "task_id": task_id,
            "plan_revision": revision,
            "source_turn_id": source_turn_id,
            "goal": {
                "relation": "hold",
                "target": {"kind": "current_pose", "query": ""},
                "tolerance_m": 0.0,
            },
            "invariants": ["keep_collision_margin"],
            "steps": [
                {
                    "id": "hold",
                    "skill": "Hold",
                    "arguments": {},
                    "preconditions": ["base_available"],
                    "success": {
                        "fact": "motion_stopped",
                        "target": None,
                        "tolerance_m": None,
                        "confidence_min": None,
                    },
                    "timeout_s": 5.0,
                    "max_attempts": 1,
                    "recovery": ["safe_stop"],
                    "resources": ["base"],
                    "interruptibility": "immediate",
                }
            ],
            "requested_interrupt": "at_checkpoint",
        }
    )


def _config(tmp_path: Path, *, planner_output_contract: str | None = None) -> Path:
    path = tmp_path / "brain-runtime.yaml"
    planner_contract = (
        ""
        if planner_output_contract is None
        else f"    planner_output_contract: {planner_output_contract}\n"
    )
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
  brain:
    enabled: true
{planner_contract.rstrip()}
    skills: [NavigateTo, FollowFormation, OrbitOwner, MoveRelative, Hold, Vocalize, AskClarification]
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


def _audio() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="test",
    )


def _seed_feedback(runtime: RobotRuntime) -> None:
    observation = runtime.backend.observe()
    with runtime._lock:
        runtime._observation = observation
    if runtime._control_state_source is not None:
        runtime._control_state_source.update_observation(observation)


def test_runtime_executes_one_deliberative_call_through_verified_semantic_hold(
    tmp_path: Path,
) -> None:
    model = _PlanningModel()
    runtime = RobotRuntime(
        _config(tmp_path),
        _Backend(),
        language_model=model,
        audio_status=_audio(),
    )

    reply = runtime.handle_text("Walk to the sidewalk and then wait.")

    assert "stay here" in reply.lower() or "accepted the task" in reply.lower()
    assert len(model.plan_calls) == 1
    assert model.decide_calls == 0
    schema = model.plan_calls[0][1]["response_schema"]
    admitted = schema["$defs"]["step"]["properties"]["skill"]["enum"]
    assert "Pose" not in admitted
    # The schema admits exactly this deployment's configured skill list, which
    # must itself be a subset of the adapter-supported skills.
    assert set(admitted) == {
        "NavigateTo",
        "FollowFormation",
        "OrbitOwner",
        "MoveRelative",
        "Hold",
        "Vocalize",
        "AskClarification",
    }
    assert set(admitted) <= runtime.semantic_tasks.SUPPORTED_SKILLS
    assert schema["properties"]["source_turn_id"]["const"] == "turn-local-1"
    trusted_task_id = schema["properties"]["task_id"]["const"]
    assert trusted_task_id.startswith("parcel-task-")
    assert schema["properties"]["plan_revision"]["const"] == 1
    assert runtime.task_executive.snapshot()["tasks"][0]["state"] == "queued"
    assert runtime.task_executive.snapshot()["tasks"][0]["task_id"] == trusted_task_id

    _seed_feedback(runtime)
    runtime._step_brain()
    assert runtime.semantic_tasks.active()[0].request.skill == "Hold"
    runtime._step_brain()

    task = runtime.task_executive.snapshot()["tasks"][0]
    assert task["state"] == "succeeded"
    assert task["last_detail"] == "motion_stop_verified"
    assert runtime.semantic_tasks.active() == ()
    runtime.close()


def test_runtime_opt_in_plansketch_uses_same_trusted_planir_executive(
    tmp_path: Path,
) -> None:
    model = _SketchPlanningModel()
    runtime = RobotRuntime(
        _config(tmp_path, planner_output_contract="plan_sketch_v1"),
        _Backend(),
        language_model=model,
        audio_status=_audio(),
    )

    reply = runtime.handle_text("Walk to the sidewalk and then wait.")

    assert "stay here" in reply.lower() or "accepted the task" in reply.lower()
    schema = model.plan_calls[0][1]["response_schema"]
    assert schema["x-parcel-output-contract"] == "plan_sketch_v1"
    assert set(schema["properties"]) == {"schema_version", "goal", "steps"}
    assert schema["$defs"]["step"]["properties"]["skill"]["enum"] == [
        "AskClarification",
        "FollowFormation",
        "Hold",
        "MoveRelative",
        "NavigateTo",
        "OrbitOwner",
        "Vocalize",
    ]
    task = runtime.task_executive.snapshot()["tasks"][0]
    assert task["task_id"].startswith("parcel-task-")
    assert task["plan_revision"] == 1
    status = runtime.snapshot()["brain"]
    assert status["planner_output_contract"] == "plan_sketch_v1"
    assert status["last_plan"]["steps"] == ["Hold"]
    runtime.close()


def test_correction_must_revision_the_current_task_instead_of_starting_a_race(
    tmp_path: Path,
) -> None:
    model = _PlanningModel([("task-compound", 1), ("task-compound", 2)])
    runtime = RobotRuntime(
        _config(tmp_path),
        _Backend(),
        language_model=model,
        audio_status=_audio(),
    )

    runtime.handle_text("Walk to the sidewalk and then wait.")
    trusted_task_id = model.plan_calls[0][1]["response_schema"]["properties"]["task_id"]["const"]
    reply = runtime.handle_text("Actually, wait here instead.")

    task = runtime.task_executive.snapshot()["tasks"][0]
    correction_schema = model.plan_calls[1][1]["response_schema"]
    assert correction_schema["properties"]["source_turn_id"]["const"] == ("turn-local-2")
    assert correction_schema["properties"]["task_id"]["const"] == trusted_task_id
    assert correction_schema["properties"]["plan_revision"]["const"] == 2
    assert correction_schema["properties"]["requested_interrupt"]["const"] == ("at_checkpoint")
    assert task["plan_revision"] == 2
    assert task["state"] == "queued"
    assert "stay here" in reply.lower() or "accepted the task" in reply.lower()
    assert model.decide_calls == 0
    runtime.close()


def test_manual_control_cancels_dispatched_plan_and_releases_base(
    tmp_path: Path,
) -> None:
    runtime = RobotRuntime(
        _config(tmp_path),
        _Backend(),
        language_model=_PlanningModel(),
        audio_status=_audio(),
    )
    runtime.handle_text("Walk to the sidewalk and then wait.")
    runtime._step_brain()

    runtime.manual_motion(0.1, 0.0, 0.0)

    task = runtime.task_executive.snapshot()["tasks"][0]
    assert task["state"] == "cancelled"
    assert runtime.semantic_tasks.active() == ()
    assert runtime.task_executive.resources.leases() == ()
    runtime.close()


def test_production_registry_admits_safe_pose_catalog(tmp_path: Path) -> None:
    """2026-08-04 review fix: the runtime built its registry without
    pose_names, so PlanValidator rejected every ReturnToSafePose plan and the
    battery-critical safe-pose procedure was unreachable in production. The
    registry must share the runtime's actual pose vocabulary."""

    from parcel_robot.brain.compiler import compile_plan_contracts
    from parcel_robot.brain.contracts import (
        FrozenDict,
        GoalSpec,
        GoalTarget,
        PlanStep,
        SuccessCondition,
    )

    path = tmp_path / "brain-safe-pose.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
  brain:
    enabled: true
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    runtime = RobotRuntime(
        path,
        _Backend(),
        language_model=_PlanningModel(),
        audio_status=_audio(),
    )
    try:
        assert "sit" in runtime.brain_registry.pose_names
        plan = compile_plan_contracts(
            PlanIR(
                schema_version=1,
                task_id="task-safe-pose-prod",
                plan_revision=1,
                source_turn_id="turn-safe-pose",
                goal=GoalSpec(
                    relation="safe_pose",
                    target=GoalTarget(kind="safe_region"),
                ),
                invariants=(),
                steps=(
                    PlanStep(
                        step_id="s1",
                        skill="ReturnToSafePose",
                        arguments=FrozenDict({"pose": "sit"}),
                        success=SuccessCondition(fact="safe_pose", target="sit"),
                    ),
                ),
            ),
            runtime.brain_registry,
        )
        validated = runtime.plan_validator.validate(plan)
        assert validated.steps[0].step.skill == "ReturnToSafePose"
    finally:
        runtime.close()
