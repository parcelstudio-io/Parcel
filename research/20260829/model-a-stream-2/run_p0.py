"""Run the frozen MA-2-P0 teacher/causality qualification probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

EXPERIMENT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = EXPERIMENT_DIR.parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from p0_contracts import (
    DT_S,
    POLICY_TOP_LEVEL,
    ROLES,
    ROOT_SEED,
    TASK_FAMILIES,
    NarrativeConsumer,
    NarrativeSigner,
    ReceiptExpectation,
    canonical_bytes,
    derive_u64,
    digest,
    mint_narrative_event,
    quantize,
    stable_token,
    validate_action,
)
from p0_observation import build_policy_payload
from p0_teacher import champion_executive_proposal, propose

from parcel_robot.brain.contracts import (
    BatteryStateSnapshot,
    ExecutionResult,
    GoalSpec,
    GoalTarget,
    ObservationSnapshot,
    PlanIR,
    PlanStep,
    RobotStateSnapshot,
    SafetyStateSnapshot,
    SensorSnapshot,
    SuccessCondition,
    TaskStateSnapshot,
    VerifiedFact,
)
from parcel_robot.brain.executive import InterruptRequest, TaskExecutive
from parcel_robot.brain.validator import PlanValidator

HERE = EXPERIMENT_DIR
REPO = REPOSITORY_ROOT
SCRATCH = Path(os.environ.get("MA2_P0_SCRATCH", Path.home() / ".cache/parcel-0e/ma2-p0"))
TRACE_DIR = HERE / "traces" / "teacher" / "qualify"
MANIFEST_DIR = HERE / "manifests"
SCHEMA_DIR = HERE / "schemas"
LOG_DIR = HERE / "logs"
SIGNER = NarrativeSigner(
    authenticator_id="ma2-p0-experiment-bridge-v1",
    key=b"ma2-p0-research-only-hmac-key-20260829-do-not-deploy",
)
ZERO_HASH = "0" * 64


def file_sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_bytes(value) + b"\n")
    temporary.replace(path)


def command_output(command: list[str]) -> str:
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=60, check=True
        ).stdout.strip()
    except Exception as error:  # noqa: BLE001 - provenance must record absence
        return f"UNAVAILABLE:{type(error).__name__}:{error}"


def source_scan() -> dict[str, object]:
    files = (HERE / "p0_teacher.py", HERE / "p0_observation.py")
    forbidden = (
        "parcel_robot.sim",
        "HeadlessCityWorld",
        "WorldTruth",
        "target_truth",
        "scorer_only",
        "actual_pose",
    )
    findings: list[dict[str, str]] = []
    for path in files:
        text = path.read_text()
        for token in forbidden:
            if token in text:
                findings.append({"file": path.name, "token": token})
    return {"files": [path.name for path in files], "findings": findings, "pass": not findings}


def build_inventory() -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    for scene_index in range(10):
        for role in ROLES:
            for family in TASK_FAMILIES:
                for repeat in range(2):
                    episode_id = f"ep-scene-{scene_index:02d}-{role}-{family}-r{repeat}"
                    inventory.append(
                        {
                            "episode_id": episode_id,
                            "scene_id": f"scene-{scene_index:02d}",
                            "scene_index": scene_index,
                            "target_role": role,
                            "task_family": family,
                            "repeat": repeat,
                            "seeds": {
                                namespace: derive_u64(namespace, episode_id)
                                for namespace in (
                                    "scene",
                                    "task",
                                    "uuid",
                                    "candidate_order",
                                    "sensor",
                                    "event",
                                )
                            },
                        }
                    )
    return inventory


def mutual_information(rows: list[dict[str, object]], x: str, y: str) -> float:
    n = len(rows)
    cx = Counter(str(row[x]) for row in rows)
    cy = Counter(str(row[y]) for row in rows)
    joint = Counter((str(row[x]), str(row[y])) for row in rows)
    value = 0.0
    for (xv, yv), count in joint.items():
        pxy = count / n
        value += pxy * math.log2(pxy / ((cx[xv] / n) * (cy[yv] / n)))
    return value


def write_schemas() -> None:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    policy_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "parcel-research-ma2-p0-embodied-frame-v1",
        "type": "object",
        "additionalProperties": False,
        "required": sorted(POLICY_TOP_LEVEL),
        "properties": {key: {} for key in sorted(POLICY_TOP_LEVEL)},
    }
    trace_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "parcel-research-ma2-p0-trace-row-v1",
        "type": "object",
        "required": [
            "episode_id",
            "frame",
            "policy_input",
            "actions",
            "scorer_only",
            "previous_row_hash",
            "row_hash",
        ],
    }
    atomic_json(SCHEMA_DIR / "embodied_frame_p0.schema.json", policy_schema)
    atomic_json(SCHEMA_DIR / "trace_row_p0.schema.json", trace_schema)


def write_prerun_manifest(inventory: list[dict[str, object]]) -> dict[str, object]:
    tracked_sources = [
        HERE / "DESIGN.md",
        HERE / "P0_PROTOCOL.md",
        HERE / "P0_AMENDMENTS.md",
        HERE / "p0_contracts.py",
        HERE / "p0_observation.py",
        HERE / "p0_teacher.py",
        HERE / "run_p0.py",
        HERE / "verify_p0.py",
        SCHEMA_DIR / "embodied_frame_p0.schema.json",
        SCHEMA_DIR / "trace_row_p0.schema.json",
        REPO / "src/parcel_robot/brain/contracts.py",
        REPO / "src/parcel_robot/brain/executive.py",
        REPO / "src/parcel_robot/brain/validator.py",
    ]
    source_hashes = {str(path.relative_to(REPO)): file_sha256(path) for path in tracked_sources}
    manifest = {
        "schema_version": 1,
        "experiment": "MA-2-P0",
        "status": "PRERUN_FROZEN",
        "root_seed": ROOT_SEED,
        "population": {
            "episodes": len(inventory),
            "scene_ids": [f"scene-{index:02d}" for index in range(10)],
            "target_roles": list(ROLES),
            "task_families": list(TASK_FAMILIES),
            "repeats": 2,
            "max_frames": {"plain": 240, "interrupt_now": 500, "queue_resume": 500},
        },
        "thresholds": {
            "teacher_success_overall": 0.80,
            "teacher_success_per_stratum": 0.70,
            "terminal_precision": 1.0,
            "label_apply_equality": 1.0,
            "transaction_exact": 1.0,
            "corruption_rejection": 1.0,
            "max_mutual_information_bits": 0.01,
        },
        "source_hashes": source_hashes,
        "inventory_sha256": digest(inventory),
        "environment": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "kernel": platform.release(),
            "machine": platform.machine(),
            "numpy": np.__version__,
            "torch_environment": command_output(
                [sys.executable, "-c", "import torch; print(torch.__version__)"]
            ),
            "pip_freeze_sha256": hashlib.sha256(
                command_output([sys.executable, "-m", "pip", "freeze"]).encode("utf-8")
            ).hexdigest(),
            "nvidia_smi": command_output(
                [
                    "nvidia-smi",
                    "--query-gpu=name,driver_version,memory.total,memory.free,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ]
            ),
            "timezone": os.environ.get("TZ", "system-default"),
            "locale": command_output(["locale"]),
        },
        "working_tree": {
            "head": command_output(["git", "rev-parse", "HEAD"]),
            "diff_sha256": hashlib.sha256(
                subprocess.run(
                    ["git", "diff", "--binary", "--no-ext-diff", "HEAD"],
                    cwd=REPO,
                    capture_output=True,
                    timeout=60,
                    check=True,
                ).stdout
            ).hexdigest(),
            "status": command_output(["git", "status", "--porcelain=v1"]),
        },
        "determinism": {
            "python_hash_seed": os.environ.get("PYTHONHASHSEED", "not-set"),
            "numpy_rng": "Generator(PCG64) with per-namespace derived seeds",
            "global_rng_shared": False,
        },
        "authority": "desktop-sim-only-no-hardware-no-sockets",
    }
    atomic_json(HERE / "manifest.prerun.json", manifest)
    return manifest


@dataclass(slots=True)
class Entity:
    entity_uuid: str
    role: str
    instance: int
    x: float
    y: float
    bias_x: float
    bias_y: float


@dataclass(slots=True)
class World:
    x: float
    y: float
    yaw: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    contacts: int = 0
    last_apply_bytes: bytes = b""

    def apply(self, command: dict[str, float]) -> None:
        admitted = validate_action(command)
        self.last_apply_bytes = canonical_bytes(admitted)
        self.vx = admitted["vx"]
        self.vy = admitted["vy"]
        self.x = quantize(self.x + self.vx * DT_S)
        self.y = quantize(self.y + self.vy * DT_S)
        self.yaw = quantize(self.yaw + admitted["vyaw"] * DT_S)
        if abs(self.x) > 5.5 or abs(self.y) > 5.5:
            self.contacts += 1


def scene_entities(scene_index: int) -> list[Entity]:
    rng = random.Random(derive_u64("scene", f"scene-{scene_index:02d}"))
    points = [
        (x, y)
        for x in (-4.0, -2.0, 0.0, 2.0, 4.0)
        for y in (-4.0, -2.0, 0.0, 2.0, 4.0)
        if (x, y) != (0.0, 0.0)
    ]
    rng.shuffle(points)
    values: list[Entity] = []
    index = 0
    for role in ROLES:
        for instance in range(3):
            x, y = points[index]
            index += 1
            stable = f"scene-{scene_index:02d}:{role}:{instance}"
            noise_rng = random.Random(derive_u64("semantic-bias", stable))
            values.append(
                Entity(
                    entity_uuid=f"entity-{stable_token('uuid', stable)}",
                    role=role,
                    instance=instance,
                    x=x,
                    y=y,
                    bias_x=noise_rng.uniform(-0.02, 0.02),
                    bias_y=noise_rng.uniform(-0.02, 0.02),
                )
            )
    return values


def make_sensor_packet(
    world: World,
    entities: list[Entity],
    *,
    episode_id: str,
    frame: int,
    now_ns: int,
) -> dict[str, Any]:
    pose_rng = random.Random(derive_u64("localization-bias", episode_id))
    bias_x = pose_rng.uniform(-0.02, 0.02)
    bias_y = pose_rng.uniform(-0.02, 0.02)
    estimate_x = quantize(world.x + bias_x)
    estimate_y = quantize(world.y + bias_y)
    candidates = [
        {
            "entity_uuid": entity.entity_uuid,
            "role": entity.role,
            "confidence": 0.97,
            "relative_x_m": quantize(entity.x + entity.bias_x - estimate_x),
            "relative_y_m": quantize(entity.y + entity.bias_y - estimate_y),
            "observed_at_ns": now_ns,
        }
        for entity in entities
    ]
    order_rng = random.Random(derive_u64("candidate-order", f"{episode_id}:{frame}"))
    order_rng.shuffle(candidates)
    return {
        "observed_at_ns": now_ns,
        "pose_estimate": {"x_m": estimate_x, "y_m": estimate_y, "yaw_rad": world.yaw},
        "velocity_estimate": {"vx_mps": world.vx, "vy_mps": world.vy},
        "sector_ranges_m": [
            quantize(5.5 - world.x),
            quantize(5.5 - world.y),
            quantize(5.5 + world.x),
            quantize(5.5 + world.y),
            5.5,
            5.5,
            5.5,
            5.5,
        ],
        "semantic_candidates": candidates,
        "localization_covariance": [0.0004, 0.0, 0.0, 0.0004],
    }


def plan_for(episode_id: str, suffix: str, target: Entity) -> PlanIR:
    task_id = f"task-{stable_token('task', episode_id + ':' + suffix)}"
    step_id = f"step-{stable_token('step', episode_id + ':' + suffix)}"
    return PlanIR(
        schema_version=1,
        task_id=task_id,
        plan_revision=1,
        source_turn_id=f"turn-{stable_token('turn', episode_id + ':' + suffix)}",
        goal=GoalSpec("near", GoalTarget("semantic_object", target.entity_uuid), 0.30),
        invariants=("keep_collision_margin", "stop_on_stale_perception"),
        steps=(
            PlanStep(
                step_id,
                "NavigateTo",
                {"directive": f"go to exact target {target.entity_uuid}"},
                ("camera_fresh", "lidar_fresh", "base_available"),
                SuccessCondition("near", target.entity_uuid),
                240.0,
                1,
                (),
                ("base", "attention"),
                "checkpoint",
            ),
        ),
    )


def executive_observation(
    now_s: float, world: World, episode_id: str, frame: int
) -> ObservationSnapshot:
    return ObservationSnapshot(
        schema_version=1,
        snapshot_id=f"snapshot-{stable_token('executive-observation', episode_id + ':' + str(frame))}",
        captured_at_monotonic_s=now_s,
        camera=SensorSnapshot("camera", True, True, "p0_camera_adapter", now_s, 0.0),
        lidar=SensorSnapshot("lidar", True, True, "p0_lidar_adapter", now_s, 0.0),
        robot=RobotStateSnapshot(
            abs(world.vx) > 0.03 or abs(world.vy) > 0.03,
            "p0_kinematic",
            world.x,
            world.y,
            0.0,
            world.yaw,
        ),
        safety=SafetyStateSnapshot(False, False, True, 5.5, None),
        battery=BatteryStateSnapshot("normal", 100.0, "p0_fixture"),
        task=TaskStateSnapshot(),
    )


def task_row(snapshot: dict[str, object], task_id: str) -> dict[str, Any]:
    rows = [row for row in snapshot["tasks"] if row["task_id"] == task_id]
    if len(rows) != 1:
        raise RuntimeError(f"task snapshot missing {task_id}")
    return dict(rows[0])


def mission_packet(
    request: Any,
    target: Entity,
    *,
    parent_task_id: str | None,
    snapshot: dict[str, object],
) -> dict[str, Any]:
    queued = [
        str(row["task_id"])
        for row in snapshot["tasks"]
        if row["state"] in {"queued", "waiting_resource", "suspended"}
        and row["task_id"] != request.task_id
    ]
    return {
        "task_id": request.task_id,
        "revision": request.plan_revision,
        "step_id": request.step_id,
        "attempt": request.attempt,
        "target_ref": target.entity_uuid,
        "parent_task_id": parent_task_id,
        "queued_task_ids": sorted(queued),
    }


def track_and_gate(
    requested: dict[str, float], previous: dict[str, float], world: World
) -> tuple[dict[str, float], dict[str, float], str, bool]:
    selected = {
        "vx": quantize(previous["vx"] + max(-0.12, min(0.12, requested["vx"] - previous["vx"]))),
        "vy": quantize(previous["vy"] + max(-0.12, min(0.12, requested["vy"] - previous["vy"]))),
        "vyaw": quantize(
            previous["vyaw"] + max(-0.20, min(0.20, requested["vyaw"] - previous["vyaw"]))
        ),
    }
    admitted = dict(selected)
    intervention = False
    if abs(world.x + admitted["vx"] * DT_S) > 5.25:
        admitted["vx"] = 0.0
        intervention = True
    if abs(world.y + admitted["vy"] * DT_S) > 5.25:
        admitted["vy"] = 0.0
        intervention = True
    admitted = validate_action(admitted)
    return selected, admitted, "boundary_stop" if intervention else "admit", intervention


def exact_success(world: World, target: Entity, settle_count: int) -> tuple[bool, float, int]:
    distance = math.hypot(world.x - target.x, world.y - target.y)
    stopped = abs(world.vx) <= 0.03 and abs(world.vy) <= 0.03
    new_count = settle_count + 1 if distance <= 0.30 and stopped else 0
    return new_count >= 3, distance, new_count


def result_for(request: Any, target: Entity, *, now_s: float, started_s: float) -> ExecutionResult:
    return ExecutionResult(
        schema_version=1,
        task_id=request.task_id,
        plan_revision=request.plan_revision,
        step_id=request.step_id,
        attempt=request.attempt,
        status="succeeded",
        feedback_code="succeeded",
        snapshot_id=f"snapshot-{stable_token('evidence', request.task_id + ':' + str(now_s))}",
        verified_facts=(VerifiedFact("near", target.entity_uuid, "p0_exact_evaluator", 1.0),),
        checkpoint=True,
        detail_code="exact_target_settled",
        started_at_monotonic_s=started_s,
        finished_at_monotonic_s=now_s,
    )


def append_hashed_row(handle: Any, row: dict[str, Any], previous: str) -> str:
    row["previous_row_hash"] = previous
    row["row_hash"] = digest(row)
    handle.write(canonical_bytes(row) + b"\n")
    return str(row["row_hash"])


def run_episode(
    spec: dict[str, object], *, trace_path: Path | None, collect_rows: bool = False
) -> dict[str, Any]:
    episode_id = str(spec["episode_id"])
    scene_index = int(spec["scene_index"])
    role = str(spec["target_role"])
    family = str(spec["task_family"])
    entities = scene_entities(scene_index)
    parent_target = next(row for row in entities if row.role == role and row.instance == 0)
    child_role = ROLES[(ROLES.index(role) + 1) % len(ROLES)]
    child_target = next(row for row in entities if row.role == child_role and row.instance == 1)
    start_rng = random.Random(derive_u64("start-pose", episode_id))
    world = World(start_rng.uniform(-0.40, 0.40), start_rng.uniform(-0.40, 0.40))
    executive = TaskExecutive()
    validator = PlanValidator()
    parent_plan = plan_for(episode_id, "parent", parent_target)
    parent_submission = executive.submit(validator.validate(parent_plan), task_class="active_task")
    if not parent_submission.accepted:
        raise RuntimeError("parent plan was not accepted")
    base_s = 10_000.0 + int(digest(episode_id)[:8], 16) / 1000.0
    active_request = executive.tick(
        executive_observation(base_s, world, episode_id, 0), now=base_s
    )[0]
    started = {active_request.task_id: base_s}
    target_by_task = {parent_plan.task_id: parent_target}
    parent_by_task: dict[str, str | None] = {parent_plan.task_id: None}
    child_plan: PlanIR | None = None
    child_terminal_receipt = False
    owner_resume_accepted = False
    resume_admitted = False
    queue_wait_observed = family != "queue_resume"
    accepted_steering: dict[str, Any] | None = None
    accepted_history: list[dict[str, Any]] = []
    previous = {"vx": 0.0, "vy": 0.0, "vyaw": 0.0}
    previous_gate = "initial"
    settle: defaultdict[str, int] = defaultdict(int)
    narrative = NarrativeConsumer(SIGNER)
    receipt_sequence = 0
    terminal_receipts: list[dict[str, Any]] = []
    initial_transaction_events = ["parent_submitted", "parent_dispatched"]
    transaction_log: list[str] = []
    terminal_claims = 0
    wrong_target_claims = 0
    unsafe = 0
    interventions = 0
    label_equal = 0
    action_frames = 0
    last_hash = ZERO_HASH
    captured_rows: list[dict[str, Any]] = []
    raw_handle = trace_path.open("wb") if trace_path is not None else None
    cue_frame = 12
    interrupt_frame = 18
    max_frames = 240 if family == "plain" else 500
    complete = False

    try:
        for frame in range(max_frames):
            now_s = base_s + frame * DT_S
            now_ns = int(now_s * 1_000_000_000)
            frame_events: list[str] = list(initial_transaction_events) if frame == 0 else []

            if family in {"interrupt_now", "queue_resume"} and frame == cue_frame:
                child_plan = plan_for(episode_id, "child", child_target)
                target_by_task[child_plan.task_id] = child_target
                parent_by_task[child_plan.task_id] = parent_plan.task_id
                accepted_steering = {
                    "event_id": f"steer-{stable_token('steer', episode_id)}",
                    "type": "queue" if family == "queue_resume" else "interrupt_now",
                    "target_ref": child_target.entity_uuid,
                    "accepted_at_ns": now_ns,
                }
                accepted_history.append(dict(accepted_steering))
                frame_events.append("steering_accepted")
                if family == "interrupt_now":
                    decision = executive.request_interrupt(
                        InterruptRequest(
                            source="voice",
                            reason="summons",
                            requested="interrupt_now",
                            target_task_id=parent_plan.task_id,
                        )
                    )
                    if decision.action != "suspend":
                        raise RuntimeError(f"product did not suspend parent: {decision}")
                    frame_events.append("parent_suspended")
                child_submission = executive.submit(
                    validator.validate(child_plan), task_class="explicit_action"
                )
                if not child_submission.accepted:
                    raise RuntimeError("child plan was not accepted")
                frame_events.append("child_submitted")
                maybe_dispatch = executive.tick(
                    executive_observation(now_s, world, episode_id, frame), now=now_s
                )
                if family == "queue_resume":
                    child_state = task_row(executive.snapshot(), child_plan.task_id)["state"]
                    queue_wait_observed = child_state == "waiting_resource" and not maybe_dispatch
                    if not queue_wait_observed:
                        raise RuntimeError("queued child did not wait on the product base lock")
                    frame_events.append("child_waiting_resource")
                else:
                    if len(maybe_dispatch) != 1:
                        raise RuntimeError("interrupted child was not dispatched")
                    active_request = maybe_dispatch[0]
                    started[active_request.task_id] = now_s
                    frame_events.append("child_dispatched")

            if family == "queue_resume" and frame == interrupt_frame:
                if child_plan is None:
                    raise RuntimeError("queue interrupt has no child")
                accepted_steering = {
                    "event_id": f"steer-{stable_token('steer-interrupt', episode_id)}",
                    "type": "interrupt_now",
                    "target_ref": child_target.entity_uuid,
                    "accepted_at_ns": now_ns,
                }
                accepted_history.append(dict(accepted_steering))
                frame_events.append("interrupt_steering_accepted")
                decision = executive.request_interrupt(
                    InterruptRequest(
                        source="voice",
                        reason="summons",
                        requested="interrupt_now",
                        target_task_id=parent_plan.task_id,
                    )
                )
                if decision.action != "suspend":
                    raise RuntimeError("queued parent did not suspend")
                frame_events.append("parent_suspended")
                dispatched = executive.tick(
                    executive_observation(now_s, world, episode_id, frame), now=now_s
                )
                if len(dispatched) != 1 or dispatched[0].task_id != child_plan.task_id:
                    raise RuntimeError("queued child did not dispatch after parent suspension")
                active_request = dispatched[0]
                started[active_request.task_id] = now_s
                frame_events.append("child_dispatched")

            snapshot_before = executive.snapshot()
            active_target = target_by_task[active_request.task_id]
            packet = make_sensor_packet(
                world, entities, episode_id=episode_id, frame=frame, now_ns=now_ns
            )
            payload = build_policy_payload(
                sequence=frame,
                monotonic_ns=now_ns,
                boot_epoch=f"epoch-{stable_token('epoch', episode_id)}",
                sensor_packet=packet,
                mission=mission_packet(
                    active_request,
                    active_target,
                    parent_task_id=parent_by_task[active_request.task_id],
                    snapshot=snapshot_before,
                ),
                accepted_steering=accepted_steering,
                previous_applied=previous,
                previous_gate_disposition=previous_gate,
                accepted_history=accepted_history,
            )
            requested = propose(payload)
            selected, admitted, gate_disposition, intervened = track_and_gate(
                requested, previous, world
            )
            applied = dict(admitted)
            apply_argument_bytes = canonical_bytes(applied)
            world.apply(applied)
            equality = world.last_apply_bytes == apply_argument_bytes == canonical_bytes(applied)
            action_frames += 1
            label_equal += int(equality)
            interventions += int(intervened)
            unsafe_now = abs(world.x) > 5.5 or abs(world.y) > 5.5
            unsafe += int(unsafe_now)
            success, distance, settle[active_request.task_id] = exact_success(
                world, active_target, settle[active_request.task_id]
            )
            receipt: dict[str, Any] | None = None

            if success:
                result = result_for(
                    active_request,
                    active_target,
                    now_s=now_s,
                    started_s=started[active_request.task_id],
                )
                disposition = executive.report(result)
                if not (
                    disposition.accepted
                    and disposition.action == "task_succeeded"
                    and disposition.state == "succeeded"
                ):
                    raise RuntimeError(f"valid terminal report refused: {disposition}")
                receipt_sequence += 1
                expectation = ReceiptExpectation(
                    task_id=active_request.task_id,
                    plan_revision=active_request.plan_revision,
                    step_id=active_request.step_id,
                    attempt=active_request.attempt,
                    target_entity_uuid=active_target.entity_uuid,
                    source_epoch=str(payload["header"]["boot_epoch"]),
                    speech_generation=1,
                    evidence_ref=str(result.snapshot_id),
                )
                receipt = mint_narrative_event(
                    SIGNER,
                    expectation=expectation,
                    sequence=receipt_sequence,
                    issued_at_ns=now_ns,
                    parent_task_id=parent_by_task[active_request.task_id],
                )
                licensed, reason = narrative.accept(receipt, expected=expectation, now_ns=now_ns)
                if not licensed or reason != "accepted":
                    raise RuntimeError(f"valid narrative receipt refused: {reason}")
                terminal_receipts.append(receipt)
                terminal_claims += 1
                wrong_target_claims += int(
                    receipt["target_entity_uuid"] != active_target.entity_uuid
                )
                if active_request.task_id != parent_plan.task_id:
                    child_terminal_receipt = True
                    frame_events.extend(["child_terminal_receipt", "resume_offer"])
                    accepted_steering = {
                        "event_id": f"steer-{stable_token('owner-resume', episode_id)}",
                        "type": "resume",
                        "target_ref": parent_plan.task_id,
                        "accepted_at_ns": now_ns + 1,
                    }
                    accepted_history.append(dict(accepted_steering))
                    owner_resume_accepted = True
                    frame_events.append("owner_resume_accepted")
                    proposal = champion_executive_proposal(
                        payload,
                        operation="request_resume_queued",
                        parent_task_id=parent_plan.task_id,
                    )
                    if not (child_terminal_receipt and owner_resume_accepted):
                        raise RuntimeError("resume eligibility predicate false")
                    resumed = executive.resume_task(
                        parent_plan.task_id, reason=str(proposal["reason_code"])
                    )
                    if not resumed.accepted or resumed.action != "task_resumed":
                        raise RuntimeError("product executive refused eligible resume")
                    resume_admitted = True
                    frame_events.extend(["resume_proposal_admitted", "parent_resumed"])
                    dispatched = executive.tick(
                        executive_observation(now_s + 0.001, world, episode_id, frame),
                        now=now_s + 0.001,
                    )
                    if len(dispatched) != 1 or dispatched[0].task_id != parent_plan.task_id:
                        raise RuntimeError("resumed parent did not dispatch")
                    active_request = dispatched[0]
                    started[active_request.task_id] = now_s + 0.001
                    settle[active_request.task_id] = 0
                    frame_events.append("parent_redispatched")
                else:
                    frame_events.append("parent_terminal_receipt")
                    complete = True

            snapshot_after = executive.snapshot()
            transaction_log.extend(frame_events)
            row = {
                "schema_version": 1,
                "run": "MA-2-P0",
                "split": "qualify",
                "episode_id": episode_id,
                "scene_id": spec["scene_id"],
                "target_role": role,
                "task_family": family,
                "repeat": spec["repeat"],
                "frame": frame,
                "derived_seeds": spec["seeds"],
                "policy_input": payload,
                "policy_input_sha256": digest(payload),
                "source_records": {
                    "sensor": "p0_sensor_adapter_v1",
                    "localization": "p0_estimator_v1",
                    "mission": "product_task_executive_snapshot",
                    "steering": "accepted_scripted_model_b_event",
                },
                "task_snapshot_before": snapshot_before,
                "task_snapshot_after": snapshot_after,
                "transaction_events": frame_events,
                "actions": {
                    "teacher_requested": requested,
                    "tracker_selected": selected,
                    "safety_admitted": admitted,
                    "actuator_applied": applied,
                    "world_apply_argument_sha256": hashlib.sha256(apply_argument_bytes).hexdigest(),
                    "label_apply_equal": equality,
                    "gate_disposition": gate_disposition,
                },
                "narrative_receipt": receipt,
                "scorer_only": {
                    "actual_pose": {"x_m": world.x, "y_m": world.y, "yaw_rad": world.yaw},
                    "exact_target_entity_uuid": active_target.entity_uuid,
                    "exact_target_role": active_target.role,
                    "exact_target_instance": active_target.instance,
                    "distance_to_exact_target_m": quantize(distance),
                    "settle_count": settle[
                        receipt["task_id"] if receipt is not None else active_request.task_id
                    ]
                    if receipt is not None
                    else settle[active_request.task_id],
                    "exact_success_rising_edge": success,
                    "unsafe_after_gate": unsafe_now,
                    "contact_count": world.contacts,
                },
                "episode_terminal": complete,
            }
            if raw_handle is not None:
                last_hash = append_hashed_row(raw_handle, row, last_hash)
            else:
                row["previous_row_hash"] = last_hash
                row["row_hash"] = digest(row)
                last_hash = str(row["row_hash"])
            if collect_rows:
                captured_rows.append(row)
            previous = applied
            previous_gate = gate_disposition
            if complete:
                break
    finally:
        if raw_handle is not None:
            raw_handle.close()

    expected_sequence = (
        ["parent_submitted", "parent_dispatched", "parent_terminal_receipt"]
        if family == "plain"
        else (
            [
                "parent_submitted",
                "parent_dispatched",
                "steering_accepted",
                "parent_suspended",
                "child_submitted",
                "child_dispatched",
                "child_terminal_receipt",
                "resume_offer",
                "owner_resume_accepted",
                "resume_proposal_admitted",
                "parent_resumed",
                "parent_redispatched",
                "parent_terminal_receipt",
            ]
            if family == "interrupt_now"
            else [
                "parent_submitted",
                "parent_dispatched",
                "steering_accepted",
                "child_submitted",
                "child_waiting_resource",
                "interrupt_steering_accepted",
                "parent_suspended",
                "child_dispatched",
                "child_terminal_receipt",
                "resume_offer",
                "owner_resume_accepted",
                "resume_proposal_admitted",
                "parent_resumed",
                "parent_redispatched",
                "parent_terminal_receipt",
            ]
        )
    )
    return {
        "episode_id": episode_id,
        "scene_id": spec["scene_id"],
        "scene_index": scene_index,
        "target_role": role,
        "task_family": family,
        "repeat": spec["repeat"],
        "success": complete,
        "frames": action_frames,
        "contacts": world.contacts,
        "unsafe_after_gate": unsafe,
        "gate_interventions": interventions,
        "label_apply_equal": label_equal,
        "terminal_claims": terminal_claims,
        "wrong_target_claims": wrong_target_claims,
        "transaction_sequence": transaction_log,
        "expected_transaction_sequence": expected_sequence,
        "transaction_exact": transaction_log == expected_sequence,
        "queue_wait_observed": queue_wait_observed,
        "child_terminal_receipt": child_terminal_receipt,
        "owner_resume_accepted": owner_resume_accepted,
        "resume_admitted": resume_admitted,
        "terminal_receipts": terminal_receipts,
        "episode_root": last_hash,
        "rows": captured_rows,
    }


def compress_trace(raw_path: Path) -> Path:
    output = raw_path.with_suffix(raw_path.suffix + ".zst")
    subprocess.run(
        ["zstd", "-q", "-f", "-19", str(raw_path), "-o", str(output)],
        check=True,
        timeout=120,
    )
    raw_path.unlink()
    return output


def wilson(successes: int, total: int) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    p = successes / total
    denominator = 1.0 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [round(max(0.0, centre - radius), 6), round(min(1.0, centre + radius), 6)]


def run_corruption_suite() -> dict[str, Any]:
    base = 2_000_000_000_000
    expectation = ReceiptExpectation(
        task_id="task-corruption-control",
        plan_revision=2,
        step_id="step-corruption-control",
        attempt=1,
        target_entity_uuid="entity-corruption-control",
        source_epoch="epoch-corruption-control",
        speech_generation=7,
        evidence_ref="snapshot-corruption-control",
    )
    base_event = mint_narrative_event(
        SIGNER, expectation=expectation, sequence=1, issued_at_ns=base, parent_task_id=None
    )
    cases: list[dict[str, Any]] = []
    for corruption in (
        "valid",
        "wrong_task",
        "wrong_revision",
        "wrong_step",
        "wrong_attempt",
        "duplicate",
        "sequence_regression",
        "wrong_epoch",
        "expiry",
        "post_terminal",
        "unrelated_evidence",
        "stale_speech_generation",
    ):
        consumer = NarrativeConsumer(SIGNER)
        event = dict(base_event)
        setup: list[dict[str, object]] = []
        now_ns = base + 100
        if corruption in {"duplicate", "post_terminal"}:
            accepted, reason = consumer.accept(
                dict(base_event), expected=expectation, now_ns=now_ns
            )
            setup.append({"accepted": accepted, "reason": reason})
            event = dict(base_event)
            event["event_id"] = f"event-{corruption}-second"
            event["sequence"] = 2
            event = SIGNER.sign({key: value for key, value in event.items() if key != "tag"})
            if corruption == "duplicate":
                event = dict(base_event)
        elif corruption == "sequence_regression":
            first = dict(base_event)
            first["sequence"] = 2
            first["event_id"] = "event-sequence-first"
            first = SIGNER.sign({key: value for key, value in first.items() if key != "tag"})
            accepted, reason = consumer.accept(first, expected=expectation, now_ns=now_ns)
            setup.append({"accepted": accepted, "reason": reason})
            event["event_id"] = "event-sequence-regressed"
            event = SIGNER.sign({key: value for key, value in event.items() if key != "tag"})
        else:
            changes: dict[str, object] = {}
            if corruption == "wrong_task":
                changes["task_id"] = "task-wrong"
            elif corruption == "wrong_revision":
                changes["plan_revision"] = 3
            elif corruption == "wrong_step":
                changes["step_id"] = "step-wrong"
            elif corruption == "wrong_attempt":
                changes["attempt"] = 2
            elif corruption == "wrong_epoch":
                changes["source_epoch"] = "epoch-wrong"
            elif corruption == "expiry":
                changes["expires_at_ns"] = base - 1
            elif corruption == "unrelated_evidence":
                changes["evidence_refs"] = ["snapshot-unrelated"]
            elif corruption == "stale_speech_generation":
                changes["speech_generation"] = 6
            if changes:
                clean = {key: value for key, value in event.items() if key != "tag"}
                clean.update(changes)
                event = SIGNER.sign(clean)
        pre = consumer.snapshot()
        accepted, reason = consumer.accept(event, expected=expectation, now_ns=now_ns)
        post = consumer.snapshot()
        expected_accept = corruption == "valid"
        cases.append(
            {
                "corruption": corruption,
                "setup": setup,
                "accepted": accepted,
                "reason": reason,
                "expected_accept": expected_accept,
                "state_unchanged_on_reject": accepted or pre == post,
                "pass": accepted == expected_accept and (accepted or pre == post),
                "pre_state_sha256": digest(pre),
                "post_state_sha256": digest(post),
            }
        )
    return {
        "cases": cases,
        "accepted_valid": sum(row["accepted"] for row in cases if row["corruption"] == "valid"),
        "valid_total": 1,
        "rejected_corruptions": sum(
            not row["accepted"] for row in cases if row["corruption"] != "valid"
        ),
        "corruption_total": len(cases) - 1,
        "all_pass": all(row["pass"] for row in cases),
    }


def run_oracle_firewall_fixture(inventory: list[dict[str, object]]) -> dict[str, Any]:
    spec = inventory[0]
    entities = scene_entities(int(spec["scene_index"]))
    target = next(row for row in entities if row.role == spec["target_role"] and row.instance == 0)
    world = World(0.1, -0.1)
    packet = make_sensor_packet(
        world, entities, episode_id=str(spec["episode_id"]), frame=0, now_ns=1_000
    )
    mission = {
        "task_id": "task-firewall",
        "revision": 1,
        "step_id": "step-firewall",
        "attempt": 1,
        "target_ref": target.entity_uuid,
        "parent_task_id": None,
        "queued_task_ids": [],
    }
    before = build_policy_payload(
        sequence=0,
        monotonic_ns=1_000,
        boot_epoch="epoch-firewall",
        sensor_packet=packet,
        mission=mission,
        accepted_steering=None,
        previous_applied={"vx": 0.0, "vy": 0.0, "vyaw": 0.0},
        previous_gate_disposition="initial",
        accepted_history=[],
    )
    scorer_annotations = {
        "target_x": target.x,
        "target_y": target.y,
        "arrived": False,
        "collision_clearance": 999.0,
    }
    scorer_annotations.update(
        {"target_x": 1.0e12, "target_y": -1.0e12, "arrived": True, "collision_clearance": -9.0}
    )
    after = build_policy_payload(
        sequence=0,
        monotonic_ns=1_000,
        boot_epoch="epoch-firewall",
        sensor_packet=packet,
        mission=mission,
        accepted_steering=None,
        previous_applied={"vx": 0.0, "vy": 0.0, "vyaw": 0.0},
        previous_gate_disposition="initial",
        accepted_history=[],
    )
    extra_rejected = False
    poisoned = dict(packet)
    poisoned["actual_pose"] = scorer_annotations
    try:
        build_policy_payload(
            sequence=0,
            monotonic_ns=1_000,
            boot_epoch="epoch-firewall",
            sensor_packet=poisoned,
            mission=mission,
            accepted_steering=None,
            previous_applied={"vx": 0.0, "vy": 0.0, "vyaw": 0.0},
            previous_gate_disposition="initial",
            accepted_history=[],
        )
    except ValueError:
        extra_rejected = True
    source = source_scan()
    return {
        "payload_sha256_before": digest(before),
        "payload_sha256_after_sentinel_truth_change": digest(after),
        "byte_identical": canonical_bytes(before) == canonical_bytes(after),
        "extra_private_field_rejected": extra_rejected,
        "source_scan": source,
        "pass": canonical_bytes(before) == canonical_bytes(after)
        and extra_rejected
        and bool(source["pass"]),
    }


def exact_target_fixture() -> dict[str, Any]:
    entities = scene_entities(0)
    intended = next(row for row in entities if row.role == "bench" and row.instance == 0)
    distractor = next(row for row in entities if row.role == "bench" and row.instance == 1)
    world = World(distractor.x, distractor.y)
    wrong_distance = math.hypot(world.x - intended.x, world.y - intended.y)
    intended_success = wrong_distance <= 0.30
    distractor_distance = math.hypot(world.x - distractor.x, world.y - distractor.y)
    return {
        "intended_uuid": intended.entity_uuid,
        "same_class_distractor_uuid": distractor.entity_uuid,
        "semantic_role_equal": intended.role == distractor.role,
        "distance_to_intended_m": quantize(wrong_distance),
        "distance_to_distractor_m": quantize(distractor_distance),
        "wrong_instance_rejected": not intended_success,
        "pass": intended.role == distractor.role and not intended_success,
    }


def read_trace_rows(path: Path):
    process = subprocess.Popen(["zstd", "-q", "-dc", str(path)], stdout=subprocess.PIPE)
    assert process.stdout is not None
    try:
        for line in process.stdout:
            yield json.loads(line)
    finally:
        process.stdout.close()
        code = process.wait(timeout=30)
        if code != 0:
            raise RuntimeError(f"zstd failed for {path}")


def learnability_diagnostic(paths: list[Path]) -> dict[str, Any]:
    xtx = np.zeros((7, 7), dtype=np.float64)
    xty = np.zeros((7, 2), dtype=np.float64)
    train_rows = 0
    for path in paths:
        scene = int(path.name.split("scene-")[1][:2])
        if scene >= 8:
            continue
        for row in read_trace_rows(path):
            payload = row["policy_input"]
            target_ref = payload["mission"]["target_ref"]
            target = next(
                value
                for value in payload["semantic_map"]["candidates"]
                if value["entity_uuid"] == target_ref
            )
            dx, dy = float(target["relative_x_m"]), float(target["relative_y_m"])
            previous = payload["history"]["previous_applied"]
            x = np.asarray(
                [
                    dx,
                    dy,
                    np.clip(dx, -0.875, 0.875),
                    np.clip(dy, -0.875, 0.875),
                    previous["vx"],
                    previous["vy"],
                    1.0,
                ]
            )
            y = np.asarray(
                [row["actions"]["actuator_applied"]["vx"], row["actions"]["actuator_applied"]["vy"]]
            )
            xtx += np.outer(x, x)
            xty += np.outer(x, y)
            train_rows += 1
    weights = np.linalg.solve(xtx + np.eye(7) * 1.0e-6, xty)
    squared_error = np.zeros(2)
    sum_y = np.zeros(2)
    sum_y2 = np.zeros(2)
    direction_hits = 0
    direction_total = 0
    test_rows = 0
    per_episode: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for path in paths:
        scene = int(path.name.split("scene-")[1][:2])
        if scene < 8:
            continue
        for row in read_trace_rows(path):
            payload = row["policy_input"]
            target_ref = payload["mission"]["target_ref"]
            target = next(
                value
                for value in payload["semantic_map"]["candidates"]
                if value["entity_uuid"] == target_ref
            )
            dx, dy = float(target["relative_x_m"]), float(target["relative_y_m"])
            previous = payload["history"]["previous_applied"]
            x = np.asarray(
                [
                    dx,
                    dy,
                    np.clip(dx, -0.875, 0.875),
                    np.clip(dy, -0.875, 0.875),
                    previous["vx"],
                    previous["vy"],
                    1.0,
                ]
            )
            y = np.asarray(
                [row["actions"]["actuator_applied"]["vx"], row["actions"]["actuator_applied"]["vy"]]
            )
            prediction = x @ weights
            squared_error += (prediction - y) ** 2
            sum_y += y
            sum_y2 += y * y
            if np.linalg.norm(y) > 0.03:
                hit = int(float(np.dot(prediction, y)) > 0.0)
                direction_hits += hit
                direction_total += 1
                per_episode[str(row["episode_id"])][0] += hit
                per_episode[str(row["episode_id"])][1] += 1
            test_rows += 1
    mean = sum_y / test_rows
    total_variance = sum_y2 - test_rows * mean * mean
    r2_axes = 1.0 - squared_error / np.maximum(total_variance, 1.0e-12)
    weighted_r2 = 1.0 - squared_error.sum() / max(total_variance.sum(), 1.0e-12)
    episode_direction = [hits / total for hits, total in per_episode.values() if total]
    return {
        "status": "NON_CONTROLLING_OPEN_LOOP_DIAGNOSTIC",
        "fit_scenes": list(range(8)),
        "held_scenes": [8, 9],
        "train_rows": train_rows,
        "held_rows": test_rows,
        "mse_vx_vy": [round(float(v / test_rows), 9) for v in squared_error],
        "r2_vx_vy": [round(float(v), 6) for v in r2_axes],
        "variance_weighted_r2": round(float(weighted_r2), 6),
        "direction_agreement": round(direction_hits / direction_total, 6),
        "direction_denominator": direction_total,
        "episode_mean_direction_agreement": round(float(np.mean(episode_direction)), 6),
        "weights_sha256": hashlib.sha256(weights.tobytes()).hexdigest(),
        "claim_limit": "label predictability only; no closed-loop learned-policy claim",
    }


def aggregate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(episodes)
    successes = sum(row["success"] for row in episodes)
    by_stratum: dict[str, Any] = {}
    for role in ROLES:
        for family in TASK_FAMILIES:
            rows = [
                row
                for row in episodes
                if row["target_role"] == role and row["task_family"] == family
            ]
            count = sum(row["success"] for row in rows)
            by_stratum[f"{role}|{family}"] = {
                "successes": count,
                "episodes": len(rows),
                "rate": round(count / len(rows), 6),
                "wilson95": wilson(count, len(rows)),
            }
    claims = sum(row["terminal_claims"] for row in episodes)
    correct_claims = claims - sum(row["wrong_target_claims"] for row in episodes)
    frames = sum(row["frames"] for row in episodes)
    equal = sum(row["label_apply_equal"] for row in episodes)
    return {
        "teacher": {
            "successes": successes,
            "episodes": total,
            "exact_success_rate": round(successes / total, 6),
            "wilson95": wilson(successes, total),
            "by_target_task_stratum": by_stratum,
        },
        "terminal_precision": {
            "correct_exact_target_claims": correct_claims,
            "claims": claims,
            "rate": round(correct_claims / claims, 6) if claims else 0.0,
        },
        "action_ledger": {
            "equal_frames": equal,
            "frames": frames,
            "rate": round(equal / frames, 9) if frames else 0.0,
        },
        "transactions": {
            "exact_episodes": sum(row["transaction_exact"] for row in episodes),
            "episodes": total,
            "rate": round(sum(row["transaction_exact"] for row in episodes) / total, 6),
            "queue_wait_controls": sum(
                row["queue_wait_observed"]
                for row in episodes
                if row["task_family"] == "queue_resume"
            ),
            "queue_wait_total": sum(row["task_family"] == "queue_resume" for row in episodes),
            "ineligible_resume_admissions": sum(
                row["resume_admitted"]
                and not (row["child_terminal_receipt"] and row["owner_resume_accepted"])
                for row in episodes
            ),
        },
        "safety": {
            "contacts": sum(row["contacts"] for row in episodes),
            "unsafe_after_gate": sum(row["unsafe_after_gate"] for row in episodes),
            "gate_interventions": sum(row["gate_interventions"] for row in episodes),
        },
        "frames": frames,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=300)
    parser.add_argument("--replay-count", type=int, default=30)
    args = parser.parse_args()
    if args.episodes != 300 or args.replay_count != 30:
        raise SystemExit("the frozen P0 requires exactly 300 episodes and 30 deterministic replays")
    if shutil.which("zstd") is None:
        raise SystemExit("zstd binary is required for frozen trace persistence")
    started_wall = time.time()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    write_schemas()
    inventory = build_inventory()
    mi = {
        "scene_target_role_bits": mutual_information(inventory, "scene_id", "target_role"),
        "scene_task_family_bits": mutual_information(inventory, "scene_id", "task_family"),
    }
    atomic_json(MANIFEST_DIR / "qualify.json", inventory)
    prerun = write_prerun_manifest(inventory)
    prerun_hash = file_sha256(HERE / "manifest.prerun.json")
    firewall = run_oracle_firewall_fixture(inventory)
    target_fixture = exact_target_fixture()
    corruption = run_corruption_suite()
    if not (firewall["pass"] and target_fixture["pass"] and corruption["all_pass"]):
        atomic_json(
            HERE / "results.json",
            {
                "status": "INVALID_PRECONDITION",
                "oracle_firewall": firewall,
                "exact_target_fixture": target_fixture,
                "corruption_suite": corruption,
            },
        )
        return 2

    episodes: list[dict[str, Any]] = []
    trace_paths: list[Path] = []
    generation_log = LOG_DIR / "generation.jsonl"
    with generation_log.open("wb") as log:
        for index, spec in enumerate(inventory):
            raw = TRACE_DIR / f"{spec['episode_id']}.jsonl"
            outcome = run_episode(spec, trace_path=raw)
            trace = compress_trace(raw)
            outcome["trace_path"] = str(trace.relative_to(HERE))
            outcome["trace_sha256"] = file_sha256(trace)
            outcome.pop("terminal_receipts", None)
            outcome.pop("rows", None)
            episodes.append(outcome)
            trace_paths.append(trace)
            log.write(canonical_bytes(outcome) + b"\n")
            if (index + 1) % 25 == 0:
                print(f"generated {index + 1}/300", flush=True)

    replay_rows = inventory[: args.replay_count]
    replay: list[dict[str, Any]] = []
    for index, spec in enumerate(replay_rows):
        first = run_episode(spec, trace_path=None)
        second = run_episode(spec, trace_path=None)
        replay.append(
            {
                "episode_id": spec["episode_id"],
                "persisted_root": episodes[index]["episode_root"],
                "replay_a_root": first["episode_root"],
                "replay_b_root": second["episode_root"],
                "identical": episodes[index]["episode_root"]
                == first["episode_root"]
                == second["episode_root"],
            }
        )
    learnability = learnability_diagnostic(trace_paths)
    aggregates = aggregate(episodes)
    stratum_pass = all(
        row["rate"] >= 0.70 for row in aggregates["teacher"]["by_target_task_stratum"].values()
    )
    gates = {
        "teacher_overall": aggregates["teacher"]["exact_success_rate"] >= 0.80,
        "teacher_each_stratum": stratum_pass,
        "terminal_precision": aggregates["terminal_precision"]["rate"] == 1.0,
        "zero_contacts": aggregates["safety"]["contacts"] == 0,
        "zero_post_gate_unsafe": aggregates["safety"]["unsafe_after_gate"] == 0,
        "applied_label_exact": aggregates["action_ledger"]["rate"] == 1.0,
        "oracle_firewall": firewall["pass"],
        "exact_target_fixture": target_fixture["pass"],
        "transactions_exact": aggregates["transactions"]["rate"] == 1.0,
        "zero_ineligible_resume": aggregates["transactions"]["ineligible_resume_admissions"] == 0,
        "corruptions_rejected": corruption["all_pass"],
        "deterministic_replay": all(row["identical"] for row in replay),
        "deconfounded": max(mi.values()) <= 0.01,
        "source_scan": firewall["source_scan"]["pass"],
    }
    results = {
        "schema_version": 1,
        "experiment": "MA-2-P0",
        "status": "PASS_TO_CORPUS_DESIGN" if all(gates.values()) else "INVALID_PRECONDITION",
        "claim": "teacher/causal data substrate only; Model A remains unestablished",
        "prerun_manifest_sha256": prerun_hash,
        "inventory_sha256": prerun["inventory_sha256"],
        "aggregates": aggregates,
        "oracle_firewall": firewall,
        "exact_target_fixture": target_fixture,
        "corruption_suite": corruption,
        "deconfounding": mi,
        "replay": {
            "episodes": len(replay),
            "identical": sum(row["identical"] for row in replay),
            "rows": replay,
            "normalized_root": digest(replay),
        },
        "learnability_diagnostic": learnability,
        "gates": gates,
        "episodes": episodes,
        "trace_inventory_root": digest(
            [
                {
                    "episode_id": row["episode_id"],
                    "episode_root": row["episode_root"],
                    "trace_sha256": row["trace_sha256"],
                }
                for row in episodes
            ]
        ),
        "resource_use": {
            "wall_seconds": round(time.time() - started_wall, 3),
            "trace_compressed_bytes": sum(path.stat().st_size for path in trace_paths),
            "episode_count": len(episodes),
            "action_frames": aggregates["frames"],
            "gpu_training_hours": 0.0,
            "neural_models_trained": 0,
        },
    }
    atomic_json(HERE / "results.json", results)
    final_manifest = {
        "schema_version": 1,
        "experiment": "MA-2-P0",
        "prerun_manifest_sha256": prerun_hash,
        "inventory_sha256": prerun["inventory_sha256"],
        "results_sha256": file_sha256(HERE / "results.json"),
        "trace_inventory_root": results["trace_inventory_root"],
        "episode_traces": [
            {
                "episode_id": row["episode_id"],
                "path": row["trace_path"],
                "sha256": row["trace_sha256"],
                "episode_root": row["episode_root"],
                "frames": row["frames"],
            }
            for row in episodes
        ],
    }
    atomic_json(HERE / "manifest.json", final_manifest)
    print(
        json.dumps(
            {
                "status": results["status"],
                "gates": gates,
                "aggregates": aggregates,
                "learnability": learnability,
            },
            indent=2,
        )
    )
    return 0 if all(gates.values()) else 3


if __name__ == "__main__":
    raise SystemExit(main())
