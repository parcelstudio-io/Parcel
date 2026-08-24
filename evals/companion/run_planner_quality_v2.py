"""Evaluate live PlanIR generation on frozen, runtime-routed compound tasks.

This suite ends at fresh-snapshot plan validation and semantic expectation
checking. It executes no skill, simulator step, or robot motion, so it cannot
claim navigation success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parcel_robot.brain.compiler import compile_plan_contracts
from parcel_robot.brain.contracts import ObservationSnapshot, PlanIR
from parcel_robot.brain.router import DeterministicIntentRouter
from parcel_robot.brain.runtime_adapter import (
    SemanticTaskRuntimeAdapter,
    admitted_plan_schema,
    bind_plan_context,
    contextual_plan_schema,
)
from parcel_robot.brain.validator import PlanValidationError, PlanValidator, SkillContractRegistry
from parcel_robot.prompting.loader import PromptLibrary
from parcel_robot.providers import LlamaCppProvider, PlanningModel

SUITE_ID = "parcel-planner-quality-v2"
RUNNER_VERSION = "runtime-routed-plan-quality-v4"
REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_ROOT = Path(__file__).resolve().parent / "planner_quality_v2"
MANIFEST_PATH = SUITE_ROOT / "manifest.json"


class PlannerQualityError(ValueError):
    """The frozen planner-quality corpus or one result is invalid."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PlannerQualityError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise PlannerQualityError(f"{path} must contain one JSON object")
    return value


def load_frozen_suite(
    manifest_path: str | Path = MANIFEST_PATH,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load the frozen cases and verify every inference-contract digest."""

    path = Path(manifest_path)
    manifest = _load_object(path)
    required = {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "frozen": True,
        "physical_navigation_episode_count": 0,
    }
    for key, expected in required.items():
        if manifest.get(key) != expected:
            raise PlannerQualityError(f"manifest {key} must equal {expected!r}")

    locked_paths = (
        (path.parent / str(manifest.get("cases_file")), "cases_sha256"),
        (REPO_ROOT / str(manifest.get("planner_prompt")), "planner_prompt_sha256"),
        (REPO_ROOT / str(manifest.get("plan_schema")), "plan_schema_sha256"),
    )
    for locked_path, digest_key in locked_paths:
        expected = manifest.get(digest_key)
        if not isinstance(expected, str) or len(expected) != 64:
            raise PlannerQualityError(f"manifest {digest_key} must be a SHA-256")
        try:
            actual = _file_sha256(locked_path)
        except OSError as error:
            raise PlannerQualityError(f"cannot read frozen input {locked_path}: {error}") from error
        if actual != expected:
            raise PlannerQualityError(f"{locked_path.name} does not match {digest_key}")

    cases_path = locked_paths[0][0]
    try:
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PlannerQualityError(f"cannot load frozen cases: {error}") from error
    if not isinstance(cases, list) or not all(isinstance(item, dict) for item in cases):
        raise PlannerQualityError("frozen cases must be a JSON array of objects")
    if len(cases) != manifest.get("case_count"):
        raise PlannerQualityError("frozen case count does not match manifest")
    identifiers = [case.get("case_id") for case in cases]
    if any(not isinstance(item, str) or not item for item in identifiers):
        raise PlannerQualityError("every case requires a case_id")
    if len(set(identifiers)) != len(identifiers):
        raise PlannerQualityError("case IDs must be unique")
    return manifest, cases


def _snapshot(case: Mapping[str, object], *, index: int) -> ObservationSnapshot:
    fixture = case.get("snapshot", {})
    if not isinstance(fixture, dict):
        raise PlannerQualityError("case snapshot must be an object")
    raw_entities = fixture.get("entities", [])
    if not isinstance(raw_entities, list):
        raise PlannerQualityError("snapshot entities must be a list")
    entities: list[dict[str, object]] = []
    for entity_index, item in enumerate(raw_entities):
        if not isinstance(item, dict):
            raise PlannerQualityError("snapshot entities must contain objects")
        kind = item.get("kind")
        label = item.get("label")
        if not isinstance(kind, str) or not isinstance(label, str):
            raise PlannerQualityError("snapshot entity kind and label must be text")
        attributes = item.get("attributes", {})
        if not isinstance(attributes, dict):
            raise PlannerQualityError("snapshot entity attributes must be an object")
        entities.append(
            {
                "entity_id": f"{kind}-{label}-{entity_index + 1}",
                "kind": kind,
                "label": label,
                "confidence": float(item.get("confidence", 0.95)),
                "source": "camera_semantic_fixture",
                "observed_at_monotonic_s": 99.95,
                "attributes": attributes,
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
    if not isinstance(task, dict):
        raise PlannerQualityError("snapshot task must be an object")
    return ObservationSnapshot.from_mapping(
        {
            "schema_version": 1,
            "snapshot_id": f"planner-v2-snapshot-{index + 1}",
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
            "task": task,
            "resource_leases": [],
            "entities": entities,
        }
    )


def _planner_boundary(
    manifest: Mapping[str, object],
    planner_prompt: str | Path | None = None,
) -> tuple[PlanValidator, dict[str, object], str, dict[str, object]]:
    registry = SkillContractRegistry.default(owner_heading_supported=True).restricted(
        SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS
    )
    validator = PlanValidator(registry)
    prompts = PromptLibrary(REPO_ROOT / "prompts")
    schema = admitted_plan_schema(
        prompts.schema("plan_ir_v1.schema.json"),
        registry.names(),
    )
    if planner_prompt is None:
        prompt_path = REPO_ROOT / str(manifest["planner_prompt"])
    else:
        candidate = Path(planner_prompt).expanduser()
        prompt_path = candidate if candidate.is_absolute() else REPO_ROOT / candidate
    prompt_path = prompt_path.resolve()
    if not prompt_path.is_relative_to(REPO_ROOT) or not prompt_path.is_file():
        raise PlannerQualityError("planner prompt must be a file inside the repository")
    system_prompt = prompt_path.read_text(encoding="utf-8").strip()
    prompt_digest = _file_sha256(prompt_path)
    return (
        validator,
        schema,
        system_prompt,
        {
            "path": prompt_path.relative_to(REPO_ROOT).as_posix(),
            "sha256": prompt_digest,
            "manifest_default": prompt_digest == manifest["planner_prompt_sha256"],
        },
    )


def _score_plan(
    plan: PlanIR,
    expected: Mapping[str, object],
    *,
    frame: object,
) -> list[str]:
    failures: list[str] = []
    route = getattr(frame, "route", None)
    speech_act = getattr(frame, "speech_act", None)
    if route != expected.get("route"):
        failures.append("route")
    if expected.get("speech_act") is not None and speech_act != expected.get("speech_act"):
        failures.append("speech_act")
    allowed_sequences = expected.get("skill_sequences")
    skills = [step.skill for step in plan.steps]
    if not isinstance(allowed_sequences, list) or skills not in allowed_sequences:
        failures.append("skill_sequence")
    goal = expected.get("goal")
    if not isinstance(goal, dict):
        failures.append("expected_goal_contract")
    else:
        actual_goal = {
            "relation": plan.goal.relation,
            "kind": plan.goal.target.kind,
            "query": plan.goal.target.query,
        }
        if actual_goal != goal:
            failures.append("goal")
    expected_targets = expected.get("navigate_targets")
    if expected_targets is not None:
        actual_targets = [step.success.target for step in plan.steps if step.skill == "NavigateTo"]
        if actual_targets != expected_targets:
            failures.append("navigate_targets")
    argument_expectations = expected.get("step_arguments", {})
    if not isinstance(argument_expectations, dict):
        failures.append("expected_step_arguments_contract")
    else:
        for skill, required in argument_expectations.items():
            matching = [step for step in plan.steps if step.skill == skill]
            if len(matching) != 1 or not isinstance(required, dict):
                failures.append(f"step_arguments:{skill}")
                continue
            actual = matching[0].arguments
            if any(actual.get(key) != value for key, value in required.items()):
                failures.append(f"step_arguments:{skill}")
    if expected.get("task_id") is not None and plan.task_id != expected.get("task_id"):
        failures.append("task_id")
    minimum_revision = expected.get("minimum_plan_revision")
    if isinstance(minimum_revision, int) and plan.plan_revision < minimum_revision:
        failures.append("plan_revision")
    requested_interrupt = expected.get("requested_interrupt")
    if requested_interrupt is not None and plan.requested_interrupt != requested_interrupt:
        failures.append("requested_interrupt")
    return failures


def run_suite(
    provider: PlanningModel,
    *,
    inference: Mapping[str, object],
    change_description: str,
    case_ids: Sequence[str] | None = None,
    planner_prompt: str | Path | None = None,
    run_id: str | None = None,
    recorded_at_utc: str | None = None,
) -> dict[str, object]:
    """Run the selected frozen compound tasks through one planning provider."""

    manifest, all_cases = load_frozen_suite()
    selected = set(case_ids or ())
    cases = [case for case in all_cases if not selected or case["case_id"] in selected]
    if selected != {case["case_id"] for case in cases} and selected:
        missing = sorted(selected - {case["case_id"] for case in cases})
        raise PlannerQualityError(f"unknown case IDs: {missing}")
    validator, response_schema, system_prompt, prompt_metadata = _planner_boundary(
        manifest,
        planner_prompt,
    )
    router = DeterministicIntentRouter()
    results: list[dict[str, object]] = []
    for index, case in enumerate(cases):
        transcript = case.get("transcript")
        expected = case.get("expected")
        if not isinstance(transcript, str) or not isinstance(expected, dict):
            raise PlannerQualityError("case transcript/expected contract is invalid")
        turn_id = f"planner-v2-{case['case_id']}"
        frame = router.route(transcript, turn_id=turn_id)
        snapshot = _snapshot(case, index=index)
        contextual_schema = contextual_plan_schema(response_schema, frame, snapshot)
        started = time.monotonic()
        raw_plan: dict[str, object] | None = None
        admitted_plan: dict[str, object] | None = None
        validation: dict[str, object]
        failures: list[str] = []
        provider_error: dict[str, str] | None = None
        try:
            proposed_plan = provider.plan(
                transcript,
                intent_frame=frame,
                observation=snapshot,
                skill_contracts=validator.prompt_contract(),
                response_schema=contextual_schema,
                system_prompt=system_prompt,
            )
            if not isinstance(proposed_plan, PlanIR):
                raise TypeError("provider returned a non-PlanIR value")
            raw_plan = proposed_plan.as_dict()
            plan = compile_plan_contracts(
                bind_plan_context(proposed_plan, frame, snapshot),
                validator.registry,
            )
            admitted_plan = plan.as_dict()
            validated = validator.validate(plan, snapshot)
            failures.extend(_score_plan(plan, expected, frame=frame))
            validation = {
                "status": "accepted",
                "code": None,
                "plan_sha256": validated.plan_sha256,
                "effective_invariants": list(validated.effective_invariants),
            }
        except PlanValidationError as error:
            failures.append("validation")
            validation = {
                "status": "rejected",
                "code": error.code,
                "plan_sha256": None,
                "effective_invariants": [],
            }
        except Exception as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):  # pragma: no cover
                raise
            failures.append("provider")
            provider_error = {
                "type": type(error).__name__,
                "message": str(error)[:1000],
            }
            validation = {
                "status": "not_run",
                "code": None,
                "plan_sha256": None,
                "effective_invariants": [],
            }
        elapsed_ms = round((time.monotonic() - started) * 1000.0, 3)
        metrics = _provider_metrics(provider)
        metrics["runner_case_elapsed_ms"] = elapsed_ms
        results.append(
            {
                "case_id": case["case_id"],
                "passed": not failures,
                "failures": failures,
                "intent_frame": frame.as_dict(),
                "snapshot_id": snapshot.snapshot_id,
                "raw_plan": raw_plan,
                "admitted_plan": admitted_plan,
                "validation": validation,
                "provider_error": provider_error,
                "provider_metrics": metrics,
            }
        )

    passed = sum(bool(item["passed"]) for item in results)
    timestamp = recorded_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    identifier = run_id or _run_id(timestamp)
    return {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "run_id": identifier,
        "recorded_at_utc": timestamp,
        "change_description": _bounded_text(change_description, 500),
        "corpus": {
            "frozen": True,
            "cases_sha256": manifest["cases_sha256"],
            "baseline_planner_prompt_sha256": manifest["planner_prompt_sha256"],
            "planner_prompt": prompt_metadata["path"],
            "planner_prompt_sha256": prompt_metadata["sha256"],
            "planner_prompt_is_manifest_default": prompt_metadata["manifest_default"],
            "plan_schema_sha256": manifest["plan_schema_sha256"],
            "context_binding_version": "trusted-envelope-v1",
            "contract_compiler_version": "semantic-planir-compiler-v1",
            "selected_case_ids": [item["case_id"] for item in results],
        },
        "inference": _json_mapping(inference),
        "aggregate": {
            "case_count": len(results),
            "passed_case_count": passed,
            "failed_case_count": len(results) - passed,
            "plan_quality_accuracy": passed / len(results) if results else None,
            "physical_navigation_episode_count": 0,
            "physical_navigation_success_rate": None,
            "latency_ms": {
                "model_ttft": _numeric_summary(results, "model_ttft_ms"),
                "model_http": _numeric_summary(results, "model_http_ms"),
                "runner_case": _numeric_summary(results, "runner_case_elapsed_ms"),
            },
            "tokens": {
                "prompt": _numeric_summary(results, "prompt_tokens"),
                "completion": _numeric_summary(results, "completion_tokens"),
                "total": _numeric_summary(results, "total_tokens"),
            },
        },
        "cases": results,
        "claims": {
            "proves": [
                "live or fake provider PlanIR quality on the selected frozen compound cases",
                "runtime-router, admitted-schema, fresh-snapshot, and validator compatibility",
                "system compilation of PlanIR controller boilerplate",
            ],
            "does_not_prove": [
                "semantic skill execution or physical navigation success",
                "camera or LiDAR perception accuracy",
                "collision avoidance, Unitree locomotion, or conversation quality",
            ],
        },
    }


def _numeric_summary(
    results: Sequence[Mapping[str, object]],
    metric: str,
) -> dict[str, float | int] | None:
    values: list[float] = []
    for result in results:
        metrics = result.get("provider_metrics")
        if not isinstance(metrics, Mapping):
            continue
        value = metrics.get(metric)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        numeric = float(value)
        if math.isfinite(numeric):
            values.append(numeric)
    if not values:
        return None
    ordered = sorted(values)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "count": len(ordered),
        "minimum": round(ordered[0], 3),
        "median": round(statistics.median(ordered), 3),
        "mean": round(statistics.fmean(ordered), 3),
        "p95_nearest_rank": round(ordered[p95_index], 3),
        "maximum": round(ordered[-1], 3),
    }


def write_report(report: Mapping[str, object], path: str | Path) -> Path:
    """Write one result artifact without silently replacing prior evidence."""

    target = Path(path)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing planner result: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return target


def _provider_metrics(provider: object) -> dict[str, object]:
    metrics = getattr(provider, "last_metrics", {})
    if not isinstance(metrics, Mapping):
        return {}
    return {
        str(key): value
        for key, value in metrics.items()
        if isinstance(key, str)
        and not key.startswith("_")
        and (value is None or isinstance(value, (str, int, float, bool)))
    }


def _json_mapping(value: Mapping[str, object]) -> dict[str, object]:
    try:
        result = json.loads(json.dumps(dict(value), sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise PlannerQualityError(f"inference must be JSON-compatible: {error}") from error
    if not isinstance(result, dict):  # pragma: no cover - Mapping guarantees it
        raise PlannerQualityError("inference must be an object")
    return result


def _bounded_text(value: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise PlannerQualityError(f"description must contain 1..{maximum} characters")
    return value.strip()


def _run_id(timestamp: str) -> str:
    compact = "".join(character for character in timestamp if character.isdigit())[:14]
    nonce = hashlib.sha256(f"{timestamp}:{time.monotonic_ns()}".encode()).hexdigest()[:8]
    return f"planner-v2-{compact}Z-{nonce}"


def _inference(args: argparse.Namespace) -> dict[str, object]:
    artifact = Path(args.model_artifact).expanduser() if args.model_artifact else None
    expected_digest = args.model_sha256.strip().lower()
    if expected_digest and re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
        raise PlannerQualityError("--model-sha256 must be a lowercase SHA-256")
    artifact_digest: str | None = None
    artifact_size: int | None = None
    if artifact is not None:
        if not artifact.is_file():
            raise PlannerQualityError(f"model artifact does not exist: {artifact}")
        artifact_size = artifact.stat().st_size
        artifact_digest = _file_sha256(artifact)
        if expected_digest and artifact_digest != expected_digest:
            raise PlannerQualityError("--model-sha256 does not match model artifact")
    elif expected_digest:
        raise PlannerQualityError("--model-sha256 requires --model-artifact")
    return {
        "model": {
            "id": args.model,
            "artifact": str(artifact) if artifact is not None else None,
            "artifact_size_bytes": artifact_size,
            "artifact_sha256": artifact_digest,
            "quantization": args.quantization,
        },
        "server": {
            "backend": "llama.cpp",
            "version": args.backend_version,
            "base_url": args.base_url,
            "cache_state": args.cache_state,
        },
        "device": {
            "profile": args.device_profile,
            "threads": args.threads,
            "gpu_layers": args.gpu_layers,
        },
        "generation": {
            "plan_temperature": args.plan_temperature,
            "top_p": args.top_p,
            "plan_max_tokens": args.plan_max_tokens,
            "plan_enable_thinking": args.plan_enable_thinking,
            "plan_timeout_s": args.plan_timeout,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--description", default="Frozen compound-plan baseline")
    parser.add_argument("--run-id")
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="gemma-4-26b-a4b")
    parser.add_argument("--model-artifact", default="")
    parser.add_argument("--model-sha256", default="")
    parser.add_argument("--quantization", default="Q4_0 QAT")
    parser.add_argument("--backend-version", default="unknown")
    parser.add_argument(
        "--cache-state",
        choices=("unknown", "cold", "warm", "mixed"),
        default="unknown",
    )
    parser.add_argument(
        "--planner-prompt",
        type=Path,
        help="Repository-local prompt challenger; the frozen manifest default is used otherwise.",
    )
    parser.add_argument("--device-profile", default="unspecified")
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--gpu-layers", type=int, default=None)
    parser.add_argument("--plan-timeout", type=float, default=90.0)
    parser.add_argument("--plan-max-tokens", type=int, default=1024)
    parser.add_argument("--plan-temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--plan-enable-thinking", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    inference = _inference(args)
    provider = LlamaCppProvider(
        base_url=args.base_url,
        model=args.model,
        streaming=True,
        top_p=args.top_p,
        plan_timeout=args.plan_timeout,
        plan_max_tokens=args.plan_max_tokens,
        plan_enable_thinking=args.plan_enable_thinking,
        plan_temperature=args.plan_temperature,
    )
    report = run_suite(
        provider,
        inference=inference,
        change_description=args.description,
        case_ids=args.case_id,
        planner_prompt=args.planner_prompt,
        run_id=args.run_id,
    )
    try:
        write_report(report, args.output)
    except FileExistsError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(report, indent=None if args.compact else 2, sort_keys=True))
    return 0 if report["aggregate"]["failed_case_count"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
