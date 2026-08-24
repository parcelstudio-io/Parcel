"""Run or replay the frozen live-model PlanIR boundary probe.

This evaluator deliberately ends after strict plan validation.  It performs no
semantic-skill dispatch, simulator step, controller command, or physical
navigation episode.  Its result must never be reported as navigation success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parcel_robot.brain.contracts import IntentFrame, ObservationSnapshot, PlanIR
from parcel_robot.brain.validator import PlanValidationError, PlanValidator, SkillContractRegistry
from parcel_robot.prompting.loader import PromptLibrary
from parcel_robot.providers import LlamaCppProvider, PlanningModel

SUITE_ID = "parcel-live-planner-v1"
RUNNER_VERSION = "live-planir-boundary-v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_ROOT = Path(__file__).resolve().parent / "live_planner_v1"
MANIFEST_PATH = SUITE_ROOT / "manifest.json"
RESULT_SCHEMA_PATH = SUITE_ROOT / "result.schema.json"
DEFAULT_RESULT_ROOT = SUITE_ROOT / "results"


class LivePlannerEvalError(ValueError):
    """A frozen input, result record, or replay contract is invalid."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LivePlannerEvalError(f"cannot load JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise LivePlannerEvalError(f"{path} must contain one JSON object")
    return value


def _verify_file(path: Path, expected: object, *, label: str) -> str:
    if not isinstance(expected, str) or len(expected) != 64:
        raise LivePlannerEvalError(f"manifest {label} must be a SHA-256 digest")
    try:
        actual = _sha256(path.read_bytes())
    except OSError as error:
        raise LivePlannerEvalError(f"cannot read {path}: {error}") from error
    if actual != expected:
        raise LivePlannerEvalError(f"{label} does not match its frozen SHA-256")
    return actual


def load_frozen_case(
    manifest_path: str | Path = MANIFEST_PATH,
) -> tuple[dict[str, Any], dict[str, Any], IntentFrame, ObservationSnapshot]:
    """Load and strictly parse the one frozen transcript/scene fixture."""

    path = Path(manifest_path)
    manifest = _load_object(path)
    expected_manifest = {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "frozen": True,
        "physical_navigation_episode_count": 0,
    }
    for key, expected in expected_manifest.items():
        if manifest.get(key) != expected:
            raise LivePlannerEvalError(
                f"manifest {key} must equal {expected!r}, got {manifest.get(key)!r}"
            )
    case_name = manifest.get("case_file")
    if not isinstance(case_name, str) or Path(case_name).name != case_name:
        raise LivePlannerEvalError("manifest case_file must be one local filename")
    case_path = path.parent / case_name
    _verify_file(case_path, manifest.get("case_sha256"), label="case_sha256")
    _verify_file(
        path.parent / "result.schema.json",
        manifest.get("result_schema_sha256"),
        label="result_schema_sha256",
    )

    # Prompt and grammar are part of the frozen inference input, not incidental
    # implementation files.  A changed prompt creates a new comparable corpus.
    for path_key, digest_key in (
        ("planner_prompt", "planner_prompt_sha256"),
        ("plan_schema", "plan_schema_sha256"),
    ):
        relative = manifest.get(path_key)
        if not isinstance(relative, str):
            raise LivePlannerEvalError(f"manifest {path_key} must be a repository path")
        resolved = (REPO_ROOT / relative).resolve()
        if REPO_ROOT not in resolved.parents:
            raise LivePlannerEvalError(f"manifest {path_key} escapes the repository")
        _verify_file(resolved, manifest.get(digest_key), label=digest_key)

    case = _load_object(case_path)
    transcript = case.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        raise LivePlannerEvalError("frozen case requires a transcript")
    try:
        intent = IntentFrame.from_mapping(_object(case, "intent_frame"))
        snapshot = ObservationSnapshot.from_mapping(_object(case, "observation_snapshot"))
    except (TypeError, ValueError) as error:
        raise LivePlannerEvalError(f"frozen typed input is invalid: {error}") from error
    transcript_digest = _sha256(transcript.encode("utf-8"))
    if intent.transcript_sha256 != transcript_digest:
        raise LivePlannerEvalError("IntentFrame transcript digest does not match transcript")
    return manifest, case, intent, snapshot


def _object(value: Mapping[str, object], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise LivePlannerEvalError(f"{key} must be an object")
    return item


def _planner_boundary(
    manifest: Mapping[str, object] | None = None,
) -> tuple[PlanValidator, dict[str, object], str]:
    # This intentionally reproduces the standalone v5 probe.  It is not the
    # runtime-restricted registry/schema profile used by RobotRuntime._accept_plan.
    registry = SkillContractRegistry.default(owner_heading_supported=True)
    validator = PlanValidator(registry)
    prompts = PromptLibrary(REPO_ROOT / "prompts")
    schema = prompts.schema("plan_ir_v1.schema.json")
    frozen_manifest = _load_object(MANIFEST_PATH) if manifest is None else manifest
    prompt_relative = frozen_manifest.get("planner_prompt")
    if not isinstance(prompt_relative, str):
        raise LivePlannerEvalError("manifest planner_prompt must be a repository path")
    prompt_path = (REPO_ROOT / prompt_relative).resolve()
    if REPO_ROOT not in prompt_path.parents:
        raise LivePlannerEvalError("manifest planner_prompt escapes the repository")
    try:
        system_prompt = prompt_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise LivePlannerEvalError(f"cannot read frozen planner prompt: {error}") from error
    if not system_prompt:
        raise LivePlannerEvalError("frozen planner prompt is empty")
    return validator, schema, system_prompt


def _validate_plan(
    plan: PlanIR,
    *,
    intent: IntentFrame,
    snapshot: ObservationSnapshot,
    validator: PlanValidator,
) -> dict[str, object]:
    if plan.source_turn_id != intent.turn_id:
        return {
            "status": "rejected",
            "code": "source_turn_mismatch",
            "message": "PlanIR source_turn_id does not match the frozen IntentFrame",
            "plan_sha256": None,
            "effective_invariants": [],
            "validated_against_snapshot_id": None,
        }
    try:
        validated = validator.validate(plan, snapshot)
    except PlanValidationError as error:
        return {
            "status": "rejected",
            "code": error.code,
            "message": str(error),
            "plan_sha256": None,
            "effective_invariants": [],
            "validated_against_snapshot_id": snapshot.snapshot_id,
        }
    return {
        "status": "accepted",
        "code": None,
        "message": None,
        "plan_sha256": validated.plan_sha256,
        "effective_invariants": list(validated.effective_invariants),
        "validated_against_snapshot_id": validated.validated_against_snapshot_id,
    }


def run_live_evaluation(
    provider: PlanningModel,
    *,
    inference: Mapping[str, object],
    change_description: str,
    run_id: str | None = None,
    recorded_at_utc: str | None = None,
    overall_elapsed_ms: float | None = None,
    capture_method: str = "live_runner",
) -> dict[str, object]:
    """Call one planning provider and return a self-contained ledger record.

    ``overall_elapsed_ms`` is injectable only so a manually captured historical
    run can preserve the original outer measurement.  Normal live calls leave
    it unset and use this runner's monotonic measurement.
    """

    manifest, case, intent, snapshot = load_frozen_case()
    validator, response_schema, system_prompt = _planner_boundary(manifest)
    started = time.monotonic()
    raw_plan: dict[str, object] | None = None
    provider_error: dict[str, str] | None = None
    try:
        plan = provider.plan(
            str(case["transcript"]),
            intent_frame=intent,
            observation=snapshot,
            skill_contracts=validator.prompt_contract(),
            response_schema=response_schema,
            system_prompt=system_prompt,
        )
        if not isinstance(plan, PlanIR):
            raise TypeError("planning provider returned a non-PlanIR value")
        raw_plan = plan.as_dict()
        validation = _validate_plan(
            plan,
            intent=intent,
            snapshot=snapshot,
            validator=validator,
        )
        parse_status = "parsed"
    except Exception as error:  # The ledger must retain failed model calls too.
        if isinstance(error, (KeyboardInterrupt, SystemExit)):  # pragma: no cover
            raise
        parse_status = "provider_error"
        validation = {
            "status": "not_run",
            "code": None,
            "message": None,
            "plan_sha256": None,
            "effective_invariants": [],
            "validated_against_snapshot_id": None,
        }
        provider_error = {"type": type(error).__name__, "message": str(error)[:1000]}
    measured_elapsed = round((time.monotonic() - started) * 1000.0, 3)

    timestamp = recorded_at_utc or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    identifier = run_id or _run_id(timestamp)
    metrics = _provider_metrics(provider)
    metrics["overall_elapsed_ms"] = (
        measured_elapsed if overall_elapsed_ms is None else round(float(overall_elapsed_ms), 3)
    )
    return {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "run_id": identifier,
        "recorded_at_utc": timestamp,
        "change_description": _bounded_text(change_description, "change_description", 500),
        "capture_method": _bounded_text(capture_method, "capture_method", 80),
        "corpus": {
            "case_id": case["case_id"],
            "case_sha256": manifest["case_sha256"],
            "planner_prompt_sha256": manifest["planner_prompt_sha256"],
            "plan_schema_sha256": manifest["plan_schema_sha256"],
            "turn_id": intent.turn_id,
            "snapshot_id": snapshot.snapshot_id,
            "transcript": case["transcript"],
        },
        "inference": _json_mapping(inference, "inference"),
        "provider_metrics": metrics,
        "output": {
            "parse_status": parse_status,
            "provider_error": provider_error,
            "raw_plan": raw_plan,
            "validation": validation,
        },
        "claims": _scope_claims(),
    }


def record_captured_run(
    *,
    raw_plan: Mapping[str, object],
    inference: Mapping[str, object],
    provider_metrics: Mapping[str, object],
    run_id: str,
    recorded_at_utc: str,
    change_description: str,
) -> dict[str, object]:
    """Turn an already captured provider response into a replayable record."""

    class _CapturedProvider:
        def __init__(self) -> None:
            self.last_metrics = dict(provider_metrics)

        def plan(self, *_args: object, **_kwargs: object) -> PlanIR:
            return PlanIR.from_mapping(raw_plan)

    metrics = dict(provider_metrics)
    outer = metrics.pop("overall_elapsed_ms", None)
    return run_live_evaluation(
        _CapturedProvider(),
        inference=inference,
        change_description=change_description,
        run_id=run_id,
        recorded_at_utc=recorded_at_utc,
        overall_elapsed_ms=(None if outer is None else float(outer)),
        capture_method="manual_capture_from_live_session",
    )


def replay_record(record_or_path: Mapping[str, object] | str | Path) -> dict[str, object]:
    """Re-parse and revalidate a ledger artifact without contacting a model."""

    record = (
        _load_object(Path(record_or_path))
        if isinstance(record_or_path, (str, Path))
        else dict(record_or_path)
    )
    _validate_record_envelope(record)
    manifest, _case, intent, snapshot = load_frozen_case()
    mismatches: list[str] = []
    corpus = _object(record, "corpus")
    for key in ("case_sha256", "planner_prompt_sha256", "plan_schema_sha256"):
        if corpus.get(key) != manifest.get(key):
            mismatches.append(f"corpus.{key}")
    if corpus.get("turn_id") != intent.turn_id:
        mismatches.append("corpus.turn_id")
    if corpus.get("snapshot_id") != snapshot.snapshot_id:
        mismatches.append("corpus.snapshot_id")

    output = _object(record, "output")
    raw_plan = output.get("raw_plan")
    recorded_validation = output.get("validation")
    if not isinstance(recorded_validation, dict):
        raise LivePlannerEvalError("output.validation must be an object")
    if raw_plan is None:
        current_validation = {
            "status": "not_run",
            "code": None,
            "message": None,
            "plan_sha256": None,
            "effective_invariants": [],
            "validated_against_snapshot_id": None,
        }
        if output.get("parse_status") != "provider_error":
            mismatches.append("output.raw_plan")
    elif not isinstance(raw_plan, dict):
        raise LivePlannerEvalError("output.raw_plan must be an object or null")
    else:
        try:
            plan = PlanIR.from_mapping(raw_plan)
        except (TypeError, ValueError) as error:
            raise LivePlannerEvalError(f"recorded raw PlanIR cannot be parsed: {error}") from error
        validator, _schema, _prompt = _planner_boundary(manifest)
        current_validation = _validate_plan(
            plan,
            intent=intent,
            snapshot=snapshot,
            validator=validator,
        )
    for key in (
        "status",
        "code",
        "plan_sha256",
        "effective_invariants",
        "validated_against_snapshot_id",
    ):
        if current_validation.get(key) != recorded_validation.get(key):
            mismatches.append(f"output.validation.{key}")
    return {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "run_id": record["run_id"],
        "replay_matched": not mismatches,
        "mismatches": mismatches,
        "current_validation": current_validation,
        "claims": _scope_claims(),
    }


def write_result(
    result: Mapping[str, object],
    path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Write one immutable-by-default JSON result artifact."""

    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing planner result: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return target


def _validate_record_envelope(record: Mapping[str, object]) -> None:
    if record.get("schema_version") != 1:
        raise LivePlannerEvalError("result schema_version must equal 1")
    if record.get("suite_id") != SUITE_ID or record.get("runner_version") != RUNNER_VERSION:
        raise LivePlannerEvalError("result suite or runner version does not match")
    for key in ("run_id", "recorded_at_utc", "change_description", "capture_method"):
        if not isinstance(record.get(key), str) or not str(record[key]).strip():
            raise LivePlannerEvalError(f"result {key} must be non-empty text")
    claims = _object(record, "claims")
    if claims.get("physical_navigation_episode_count") != 0:
        raise LivePlannerEvalError("planner records must contain zero physical episodes")
    if claims.get("physical_navigation_success_rate") is not None:
        raise LivePlannerEvalError("planner records cannot claim physical navigation success")
    _object(record, "inference")
    _object(record, "provider_metrics")


def _provider_metrics(provider: object) -> dict[str, object]:
    value = getattr(provider, "last_metrics", {})
    if not isinstance(value, Mapping):
        return {}
    # Monotonic process-local timestamps are useful while a turn is live but
    # meaningless in a portable ledger artifact.
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(key, str) and not key.startswith("_") and _json_scalar(item)
    }


def _json_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _json_mapping(value: Mapping[str, object], label: str) -> dict[str, object]:
    try:
        serialized = json.dumps(dict(value), sort_keys=True, allow_nan=False)
        result = json.loads(serialized)
    except (TypeError, ValueError) as error:
        raise LivePlannerEvalError(f"{label} must be JSON-compatible: {error}") from error
    if not isinstance(result, dict):  # pragma: no cover - guarded by Mapping input
        raise LivePlannerEvalError(f"{label} must be an object")
    return result


def _bounded_text(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise LivePlannerEvalError(f"{label} must contain 1..{maximum} characters")
    return value.strip()


def _run_id(timestamp: str) -> str:
    compact = "".join(character for character in timestamp if character.isdigit())[:14]
    nonce = hashlib.sha256(f"{timestamp}:{time.monotonic_ns()}".encode()).hexdigest()[:8]
    return f"live-planner-{compact}Z-{nonce}"


def _scope_claims() -> dict[str, object]:
    return {
        "evaluation_scope": "standalone semantic PlanIR generation and validation only",
        "physical_navigation_episode_count": 0,
        "physical_navigation_success_rate": None,
        "does_not_prove": [
            "normal runtime planner routing (the frozen utterance routes through direct_skill)",
            "runtime-restricted skill-registry or response-schema admission",
            "physical or simulated sidewalk arrival",
            "collision avoidance or trajectory quality",
            "camera or LiDAR perception accuracy",
            "planner generalization beyond the frozen request",
            "conversation quality or speech latency",
        ],
    }


def _inference_metadata(args: argparse.Namespace) -> dict[str, object]:
    artifact = Path(args.model_artifact).expanduser() if args.model_artifact else None
    supplied_digest = args.model_sha256.strip().lower()
    if supplied_digest and not re.fullmatch(r"[0-9a-f]{64}", supplied_digest):
        raise LivePlannerEvalError("--model-sha256 must be a lowercase SHA-256 digest")
    artifact_digest: str | None = None
    artifact_size: int | None = None
    if artifact is not None:
        if not artifact.is_file():
            raise LivePlannerEvalError(f"model artifact does not exist: {artifact}")
        artifact_size = artifact.stat().st_size
        # Hashing is intentionally outside run_live_evaluation's timed model
        # boundary, so provenance work cannot inflate provider latency.
        artifact_digest = _file_sha256(artifact)
        if supplied_digest and supplied_digest != artifact_digest:
            raise LivePlannerEvalError("--model-sha256 does not match the model artifact")
    elif supplied_digest:
        raise LivePlannerEvalError("--model-sha256 requires --model-artifact")
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
            "health": {"status": args.health_status},
        },
        "device": {
            "host": platform.machine(),
            "profile": args.device_profile,
            "generation_threads": args.threads,
            "gpu_layers": args.gpu_layers,
            "gpu_available_but_unused": args.gpu_available_but_unused,
        },
        "generation_config": {
            "streaming": True,
            "plan_temperature": args.plan_temperature,
            "top_p": args.top_p,
            "plan_max_tokens": args.plan_max_tokens,
            "plan_enable_thinking": args.plan_enable_thinking,
            "plan_timeout_s": args.plan_timeout,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, help="revalidate one existing result offline")
    parser.add_argument("--output", type=Path, help="write live result without overwriting")
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--description",
        default="Live frozen sidewalk PlanIR boundary probe; no robot behavior changed.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="gemma-4-26b-a4b")
    parser.add_argument("--model-artifact", default="")
    parser.add_argument(
        "--model-sha256",
        default="",
        help="optional expected digest; the artifact is always hashed before inference",
    )
    parser.add_argument("--quantization", default="Q4_0 QAT")
    parser.add_argument("--backend-version", default="unknown")
    parser.add_argument("--health-status", choices=("ok", "unknown"), default="unknown")
    parser.add_argument("--device-profile", default="unspecified")
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--gpu-layers", type=int, default=None)
    parser.add_argument("--gpu-available-but-unused", action="store_true")
    parser.add_argument("--plan-timeout", type=float, default=90.0)
    parser.add_argument("--plan-max-tokens", type=int, default=1024)
    parser.add_argument("--plan-temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--plan-enable-thinking", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.replay is not None:
        if args.output is not None:
            raise SystemExit("--output cannot be combined with --replay")
        report = replay_record(args.replay)
        print(json.dumps(report, indent=None if args.compact else 2, sort_keys=True))
        return 0 if report["replay_matched"] else 1
    if args.output is None:
        raise SystemExit("live evaluation requires --output to preserve the result ledger")
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
    result = run_live_evaluation(
        provider,
        inference=_inference_metadata(args),
        change_description=args.description,
        run_id=args.run_id,
    )
    write_result(result, args.output)
    print(json.dumps(result, indent=None if args.compact else 2, sort_keys=True))
    return 0 if result["output"]["validation"]["status"] == "accepted" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
