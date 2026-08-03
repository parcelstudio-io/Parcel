"""Evaluate compact PlanSketch generation on frozen planner-quality cases.

This suite deliberately ends after trusted-envelope compilation, fresh-scene
PlanIR validation, and semantic expectation scoring. It executes no skill,
simulator step, or robot motion and therefore cannot claim navigation success.
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

from evals.companion.run_planner_quality_v2 import (
    _score_plan as score_planir_semantics,
)
from evals.companion.run_planner_quality_v2 import _snapshot as build_paired_snapshot
from parcel_robot.brain import (
    DeterministicIntentRouter,
    PlanSketch,
    PlanValidationError,
    PlanValidator,
    SemanticTaskRuntimeAdapter,
    SkillContractRegistry,
    admitted_plan_sketch_schema,
    compile_plan_sketch,
    contextual_planner_schema,
)
from parcel_robot.providers import LlamaCppProvider, PlanningModel

SUITE_ID = "parcel-planner-quality-sketch-v1"
RUNNER_VERSION = "runtime-routed-plansketch-quality-v1"
OUTPUT_CONTRACT = "plan_sketch_v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_ROOT = Path(__file__).resolve().parent / "planner_quality_sketch_v1"
MANIFEST_PATH = SUITE_ROOT / "manifest.json"


class PlanSketchQualityError(ValueError):
    """The frozen PlanSketch corpus, inference contract, or result is invalid."""


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
        raise PlanSketchQualityError(f"cannot load {path}: {error}") from error
    if not isinstance(value, dict):
        raise PlanSketchQualityError(f"{path} must contain one JSON object")
    return value


def load_frozen_suite(
    manifest_path: str | Path = MANIFEST_PATH,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Path]]:
    """Load and hash-verify the paired cases, PlanSketch prompt, and schema."""

    path = Path(manifest_path).resolve()
    manifest = _load_object(path)
    required = {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "frozen": True,
        "case_count": 5,
        "output_contract": OUTPUT_CONTRACT,
        "physical_navigation_episode_count": 0,
    }
    for key, expected in required.items():
        if manifest.get(key) != expected:
            raise PlanSketchQualityError(f"manifest {key} must equal {expected!r}")
    locked = manifest.get("locked_inputs")
    if not isinstance(locked, dict) or set(locked) != {
        "cases",
        "planner_prompt",
        "response_schema",
    }:
        raise PlanSketchQualityError("manifest locked_inputs are invalid")
    resolved: dict[str, Path] = {}
    for name, raw in locked.items():
        if not isinstance(raw, dict):
            raise PlanSketchQualityError(f"locked input {name} must be an object")
        relative = raw.get("path")
        expected_digest = raw.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected_digest, str):
            raise PlanSketchQualityError(f"locked input {name} requires path and SHA-256")
        candidate = (REPO_ROOT / relative).resolve()
        if not candidate.is_relative_to(REPO_ROOT) or not candidate.is_file():
            raise PlanSketchQualityError(f"locked input {name} is outside or missing")
        if _file_sha256(candidate) != expected_digest:
            raise PlanSketchQualityError(f"locked input {name} failed SHA-256 verification")
        resolved[name] = candidate
    try:
        cases = json.loads(resolved["cases"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PlanSketchQualityError(f"cannot load frozen cases: {error}") from error
    if not isinstance(cases, list) or not all(isinstance(item, dict) for item in cases):
        raise PlanSketchQualityError("frozen cases must be an array of objects")
    if len(cases) != manifest["case_count"]:
        raise PlanSketchQualityError("frozen case count does not match manifest")
    identifiers = [case.get("case_id") for case in cases]
    if any(not isinstance(item, str) or not item for item in identifiers):
        raise PlanSketchQualityError("every case requires a case_id")
    if len(set(identifiers)) != len(identifiers):
        raise PlanSketchQualityError("case IDs must be unique")
    return manifest, cases, resolved


def _planner_boundary(
    manifest: Mapping[str, object],
    locked: Mapping[str, Path],
) -> tuple[PlanValidator, dict[str, object], str]:
    registry = SkillContractRegistry.default(owner_heading_supported=True).restricted(
        SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS
    )
    validator = PlanValidator(registry)
    schema = admitted_plan_sketch_schema(
        _load_object(locked["response_schema"]),
        registry.names(),
    )
    prompt = locked["planner_prompt"].read_text(encoding="utf-8").strip()
    if not prompt:
        raise PlanSketchQualityError("locked planner prompt cannot be empty")
    if manifest.get("output_contract") != schema.get("x-parcel-output-contract"):
        raise PlanSketchQualityError("schema output-contract marker does not match manifest")
    return validator, schema, prompt


def run_suite(
    provider: PlanningModel,
    *,
    inference: Mapping[str, object],
    change_description: str,
    case_ids: Sequence[str] | None = None,
    run_id: str | None = None,
    recorded_at_utc: str | None = None,
    manifest_path: str | Path = MANIFEST_PATH,
) -> dict[str, object]:
    """Run selected frozen cases through the compact planner boundary."""

    manifest, all_cases, locked = load_frozen_suite(manifest_path)
    selected = set(case_ids or ())
    cases = [case for case in all_cases if not selected or case["case_id"] in selected]
    if selected and selected != {case["case_id"] for case in cases}:
        missing = sorted(selected - {case["case_id"] for case in cases})
        raise PlanSketchQualityError(f"unknown case IDs: {missing}")
    validator, response_schema, system_prompt = _planner_boundary(manifest, locked)
    router = DeterministicIntentRouter()
    results: list[dict[str, object]] = []
    for index, case in enumerate(cases):
        transcript = case.get("transcript")
        expected = case.get("expected")
        if not isinstance(transcript, str) or not isinstance(expected, dict):
            raise PlanSketchQualityError("case transcript/expected contract is invalid")
        # Keep the exact PlanIR-pair turn ID and snapshot construction so only
        # the model output contract and its instruction/schema change.
        turn_id = f"planner-v2-{case['case_id']}"
        frame = router.route(transcript, turn_id=turn_id)
        snapshot = build_paired_snapshot(case, index=index)
        contextual_schema = contextual_planner_schema(response_schema, frame, snapshot)
        started = time.monotonic()
        raw_sketch: dict[str, object] | None = None
        admitted_plan: dict[str, object] | None = None
        failures: list[str] = []
        provider_error: dict[str, str] | None = None
        validation: dict[str, object]
        compile_ms: float | None = None
        validation_ms: float | None = None
        try:
            proposed = provider.plan(
                transcript,
                intent_frame=frame,
                observation=snapshot,
                skill_contracts=validator.prompt_contract(),
                response_schema=contextual_schema,
                system_prompt=system_prompt,
            )
            if not isinstance(proposed, PlanSketch):
                raise TypeError("PlanSketch provider returned a different output contract")
            raw_sketch = proposed.as_dict()
            compile_started = time.monotonic()
            plan = compile_plan_sketch(proposed, frame, snapshot, validator.registry)
            compiled_at = time.monotonic()
            compile_ms = round((compiled_at - compile_started) * 1000.0, 3)
            admitted_plan = plan.as_dict()
            validated = validator.validate(plan, snapshot)
            validated_at = time.monotonic()
            validation_ms = round((validated_at - compiled_at) * 1000.0, 3)
            failures.extend(score_planir_semantics(plan, expected, frame=frame))
            validation = {
                "status": "accepted",
                "code": None,
                "plan_sha256": validated.plan_sha256,
                "effective_invariants": list(validated.effective_invariants),
                "validated_snapshot_id": validated.validated_against_snapshot_id,
            }
        except PlanValidationError as error:
            failures.append("validation")
            validation = {
                "status": "rejected",
                "code": error.code,
                "plan_sha256": None,
                "effective_invariants": [],
                "validated_snapshot_id": None,
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
                "validated_snapshot_id": None,
            }
        elapsed_ms = round((time.monotonic() - started) * 1000.0, 3)
        metrics = _provider_metrics(provider)
        metrics.update(
            {
                "plan_compile_ms": compile_ms,
                "plan_validation_ms": validation_ms,
                "runner_case_elapsed_ms": elapsed_ms,
            }
        )
        results.append(
            {
                "case_id": case["case_id"],
                "passed": not failures,
                "failures": failures,
                "intent_frame": frame.as_dict(),
                "snapshot_id": snapshot.snapshot_id,
                "raw_plan_sketch": raw_sketch,
                "admitted_plan_ir": admitted_plan,
                "validation": validation,
                "provider_error": provider_error,
                "provider_metrics": metrics,
            }
        )
    passed = sum(bool(item["passed"]) for item in results)
    timestamp = recorded_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    identifier = run_id or _run_id(timestamp)
    locked_metadata = manifest["locked_inputs"]
    return {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "run_id": identifier,
        "recorded_at_utc": timestamp,
        "change_description": _bounded_text(change_description, 500),
        "corpus": {
            "frozen": True,
            "output_contract": OUTPUT_CONTRACT,
            "cases_path": locked_metadata["cases"]["path"],
            "cases_sha256": locked_metadata["cases"]["sha256"],
            "planner_prompt": locked_metadata["planner_prompt"]["path"],
            "planner_prompt_sha256": locked_metadata["planner_prompt"]["sha256"],
            "response_schema": locked_metadata["response_schema"]["path"],
            "response_schema_sha256": locked_metadata["response_schema"]["sha256"],
            "paired_reference_suite": "parcel-planner-quality-v2",
            "context_binding_version": "trusted-envelope-v1",
            "contract_compiler_version": "plansketch-v1-to-semantic-planir-v1",
            "semantic_scorer": "planner-quality-v2-identical",
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
                "model_http_full": _numeric_summary(results, "model_http_ms"),
                "plan_compile": _numeric_summary(results, "plan_compile_ms"),
                "plan_validation": _numeric_summary(results, "plan_validation_ms"),
                "runner_case": _numeric_summary(results, "runner_case_elapsed_ms"),
            },
            "model_output_bytes": _numeric_summary(results, "model_output_bytes"),
            "tokens": {
                "prompt": _numeric_summary(results, "prompt_tokens"),
                "completion": _numeric_summary(results, "completion_tokens"),
                "total": _numeric_summary(results, "total_tokens"),
            },
        },
        "cases": results,
        "claims": {
            "proves": [
                "PlanSketch generation quality on the selected frozen compound cases",
                "deterministic compilation of raw PlanSketch into trusted PlanIR",
                "paired router, snapshot, registry, semantic scoring, and PlanIR validation compatibility",
                "recorded provider TTFT, full-call latency, output bytes, and token counts when supplied by the server",
            ],
            "does_not_prove": [
                "semantic skill execution or physical navigation success",
                "camera or LiDAR perception accuracy",
                "collision avoidance, Unitree locomotion, or conversation quality",
                "latency or token improvement without comparison to a separately valid paired PlanIR run",
            ],
        },
    }


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


def _json_mapping(value: Mapping[str, object]) -> dict[str, object]:
    try:
        result = json.loads(json.dumps(dict(value), sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise PlanSketchQualityError(f"inference must be JSON-compatible: {error}") from error
    if not isinstance(result, dict):  # pragma: no cover - Mapping guarantees it
        raise PlanSketchQualityError("inference must be an object")
    return result


def _bounded_text(value: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise PlanSketchQualityError(f"description must contain 1..{maximum} characters")
    return value.strip()


def _run_id(timestamp: str) -> str:
    compact = "".join(character for character in timestamp if character.isdigit())[:14]
    nonce = hashlib.sha256(f"{timestamp}:{time.monotonic_ns()}".encode()).hexdigest()[:8]
    return f"planner-sketch-v1-{compact}Z-{nonce}"


def write_report(report: Mapping[str, object], path: str | Path) -> Path:
    """Write one immutable result without replacing prior evidence."""

    target = Path(path)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite existing PlanSketch result: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return target


def _inference(args: argparse.Namespace) -> dict[str, object]:
    artifact = Path(args.model_artifact).expanduser() if args.model_artifact else None
    expected_digest = args.model_sha256.strip().lower()
    if expected_digest and re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
        raise PlanSketchQualityError("--model-sha256 must be a lowercase SHA-256")
    artifact_digest: str | None = None
    artifact_size: int | None = None
    if artifact is not None:
        if not artifact.is_file():
            raise PlanSketchQualityError(f"model artifact does not exist: {artifact}")
        artifact_size = artifact.stat().st_size
        artifact_digest = _file_sha256(artifact)
        if expected_digest and artifact_digest != expected_digest:
            raise PlanSketchQualityError("--model-sha256 does not match model artifact")
    elif expected_digest:
        raise PlanSketchQualityError("--model-sha256 requires --model-artifact")
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
    parser.add_argument("--description", default="Frozen PlanSketch compound-plan challenger")
    parser.add_argument("--run-id")
    parser.add_argument("--recorded-at-utc")
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
        run_id=args.run_id,
        recorded_at_utc=args.recorded_at_utc,
    )
    try:
        write_report(report, args.output)
    except FileExistsError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(report, indent=None if args.compact else 2, sort_keys=True))
    return 0 if report["aggregate"]["failed_case_count"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
