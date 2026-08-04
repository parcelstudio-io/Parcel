"""Run rerunnable, training-only V9 paired screens with immutable evidence.

This command is intentionally unable to address V9 development or holdout
worlds.  It verifies the already-generated, frozen training corpus and the two
content-addressed policy bundles, then calls the additive V9 traced paired
evaluator.  Every run receives its own immutable report/action evidence and an
append-only ledger entry.  These scratch results are never official,
leaderboard, promotion, or deployment evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .barn_policy_sidecar import HISTORICAL_CONFIG, verify_policy_bundle
from .barn_policy_specs import (
    BarnPolicySpec,
    IsolatedPlannerProfileAuthorization,
    parcel_isolated_bundle_candidate_spec,
    parcel_isolated_bundle_reference_spec,
    validate_isolated_policy_pair,
)
from .barn_sensor_faithful import (
    BARN_EVALUATOR_COMMIT,
    BARN_SOURCE,
    CANDIDATE_THEN_REFERENCE,
    REFERENCE_THEN_CANDIDATE,
)
from .barn_v9_paired_trace import run_sensor_faithful_paired_comparison_with_v9_traces
from .barn_v9_policy_bundle import (
    DEFAULT_DESTINATION_ROOT,
    DEFAULT_REFERENCE_ROOT,
    V8_REFERENCE_MANIFEST_SHA256,
    V8_REFERENCE_PACKAGE_SHA256,
    plan_v9_candidate_bundle,
    verify_v9_candidate_delta,
)
from .generate_sampled_predictive_tracker_v9_training import (
    CORPUS_ID,
    DEFAULT_ASSETS_ROOT,
    DEFAULT_MANIFEST,
    MANIFEST_ID,
    TRAINING_WORLD_IDS,
    verify_training_corpus,
)
from .ledger import LedgerWriteResult, record_evaluation_run

SCHEMA_VERSION = 1
EVALUATION_KIND = "barn-v9-sampled-predictive-tracker-training-paired-non-official"
SUITE_SEED = 20260803
TRIALS_PER_WORLD = 1
DEFAULT_WORKERS = 4
DEFAULT_WORLD_COUNT = 10
ALLOWED_WORLD_COUNTS = (10, 100)

EXPECTED_TRAINING_MANIFEST_SHA256 = (
    "018b2863bd699a2856e264b6f7712c91ed7561de48ba2999a4a6b020f6ef16fd"
)
EXPECTED_TRAINING_CORPUS_SHA256 = "40c260e32985123d648e4634f0c087ec3de8309494581b2a64ca1fd289d9907f"
V9_CANDIDATE_PACKAGE_SHA256 = "c68bb69c247404d0deee28f26d8000200f73aeb336fb9bb0cafd0f0c3b510833"
V9_CANDIDATE_MANIFEST_SHA256 = "540658cee91c2bdb058f54ab19b9838d731f49c7be4df6ef7332aaea631b8b08"
DEFAULT_CANDIDATE_ROOT = (
    DEFAULT_DESTINATION_ROOT / f"parcel-v9-candidate-{V9_CANDIDATE_PACKAGE_SHA256}"
)
DEFAULT_RESULTS_ROOT = DEFAULT_MANIFEST.parent / "results"
DEFAULT_DESCRIPTION = (
    "Training-only paired screen of the exact V9 sampled predictive tracker against its "
    "exact V8 189ac31f control; no development or holdout world is opened."
)

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


class V9TrainingRunnerError(RuntimeError):
    """Raised when the scratch runner's fixed training contract is violated."""


@dataclass(frozen=True, slots=True)
class V9TrainingCandidateIdentity:
    """Content-addressed identity for one training-only tracker challenger."""

    package_sha256: str
    manifest_sha256: str
    experiment_id: str
    description: str
    freeze_path: str | None = None
    freeze_sha256: str | None = None

    def __post_init__(self) -> None:
        for name in ("package_sha256", "manifest_sha256"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise V9TrainingRunnerError(f"candidate {name} must be a lowercase SHA-256")
        for name in ("experiment_id", "description"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise V9TrainingRunnerError(f"candidate {name} must be nonempty")
        if (self.freeze_path is None) != (self.freeze_sha256 is None):
            raise V9TrainingRunnerError(
                "candidate freeze_path and freeze_sha256 must both be present or absent"
            )
        if self.freeze_sha256 is not None and (
            len(self.freeze_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.freeze_sha256)
        ):
            raise V9TrainingRunnerError("candidate freeze_sha256 must be a lowercase SHA-256")

    def report_metadata(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "candidate_package_sha256": self.package_sha256,
            "candidate_manifest_sha256": self.manifest_sha256,
            "candidate_experiment_id": self.experiment_id,
            "candidate_description": self.description,
            "candidate_experimental": True,
            "deployment_enabled": False,
        }
        if self.freeze_path is not None:
            result["candidate_freeze"] = {
                "path": self.freeze_path,
                "sha256": self.freeze_sha256,
                "training_only": True,
                "promotion_evidence": False,
                "development_execution_authorized": False,
                "holdout_execution_authorized": False,
                "deployment_enabled": False,
            }
        return result


INITIAL_CANDIDATE_IDENTITY = V9TrainingCandidateIdentity(
    package_sha256=V9_CANDIDATE_PACKAGE_SHA256,
    manifest_sha256=V9_CANDIDATE_MANIFEST_SHA256,
    experiment_id="barn-v9-training-c68bb69c-candidate",
    description="Exact deployment-disabled V9 sampled predictive tracker candidate",
)


@dataclass(frozen=True, slots=True)
class V9TrainingPreflight:
    """Exact inputs authenticated before any policy episode starts."""

    corpus_verification: Mapping[str, Any]
    reference_spec: BarnPolicySpec
    candidate_spec: BarnPolicySpec
    one_factor_delta: Mapping[str, Any]
    isolated_pair: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "corpus_verification",
            MappingProxyType(dict(self.corpus_verification)),
        )
        object.__setattr__(
            self,
            "one_factor_delta",
            MappingProxyType(dict(self.one_factor_delta)),
        )
        object.__setattr__(
            self,
            "isolated_pair",
            MappingProxyType(dict(self.isolated_pair)),
        )


def training_world_ids(world_count: int) -> tuple[int, ...]:
    """Return the deterministic frozen training prefix selected by the CLI."""

    if isinstance(world_count, bool) or world_count not in ALLOWED_WORLD_COUNTS:
        raise V9TrainingRunnerError("world_count must be exactly 10 or 100")
    return validate_training_world_ids(TRAINING_WORLD_IDS[:world_count])


def validate_training_world_ids(world_ids: Sequence[int]) -> tuple[int, ...]:
    """Reject every identity outside the reserved 5000--5099 training namespace."""

    if isinstance(world_ids, (str, bytes)):
        raise TypeError("world_ids must be an integer sequence")
    values = tuple(world_ids)
    if not values:
        raise V9TrainingRunnerError("at least one training world is required")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise TypeError("training world IDs must be integers")
    if len(values) != len(set(values)):
        raise V9TrainingRunnerError("training world IDs must not contain duplicates")
    if any(value not in TRAINING_WORLD_IDS for value in values):
        raise V9TrainingRunnerError(
            "only V9 training world IDs 5000--5099 are permitted; development/holdout IDs "
            "5100 and above are forbidden"
        )
    return values


def candidate_first_alternating_schedule(pair_count: int) -> tuple[str, ...]:
    """Return a deterministic counterbalanced schedule beginning candidate-first."""

    if isinstance(pair_count, bool) or not isinstance(pair_count, int) or pair_count < 1:
        raise ValueError("pair_count must be a positive integer")
    return tuple(
        CANDIDATE_THEN_REFERENCE if index % 2 == 0 else REFERENCE_THEN_CANDIDATE
        for index in range(pair_count)
    )


def _preflight_training_inputs() -> V9TrainingPreflight:
    verification = verify_training_corpus(DEFAULT_MANIFEST)
    expected_verification = {
        "corpus_id": CORPUS_ID,
        "corpus_sha256": EXPECTED_TRAINING_CORPUS_SHA256,
        "manifest_sha256": EXPECTED_TRAINING_MANIFEST_SHA256,
        "promotion_evidence_eligible": False,
        "world_count": len(TRAINING_WORLD_IDS),
    }
    if verification != expected_verification:
        raise V9TrainingRunnerError("verified training manifest/corpus identity is not exact")

    plan = plan_v9_candidate_bundle()
    if (
        plan.reference.root != DEFAULT_REFERENCE_ROOT.resolve()
        or plan.reference.package_sha256 != V8_REFERENCE_PACKAGE_SHA256
        or plan.reference.manifest_sha256 != V8_REFERENCE_MANIFEST_SHA256
        or plan.package_sha256 != V9_CANDIDATE_PACKAGE_SHA256
        or plan.manifest_sha256 != V9_CANDIDATE_MANIFEST_SHA256
    ):
        raise V9TrainingRunnerError("read-only V9 derivation does not match the frozen policy pair")

    candidate = verify_policy_bundle(
        DEFAULT_CANDIDATE_ROOT,
        expected_package_sha256=V9_CANDIDATE_PACKAGE_SHA256,
        expected_manifest_sha256=V9_CANDIDATE_MANIFEST_SHA256,
    )
    delta = verify_v9_candidate_delta(
        candidate,
        plan.reference,
        expected_source_contract=plan.source_contract.manifest_record(),
    )
    if delta != plan.delta:
        raise V9TrainingRunnerError("materialized V9 candidate is not the frozen one-factor delta")

    reference_spec = parcel_isolated_bundle_reference_spec(
        plan.reference.root,
        package_sha256=V8_REFERENCE_PACKAGE_SHA256,
        manifest_sha256=V8_REFERENCE_MANIFEST_SHA256,
        navigation_config_relative=HISTORICAL_CONFIG,
        reference_id="barn-v9-training-v8-189ac31f-control",
        description="Exact V8 189ac31f nonexperimental control for V9 training screens",
    )
    candidate_spec = parcel_isolated_bundle_candidate_spec(
        candidate.root,
        package_sha256=V9_CANDIDATE_PACKAGE_SHA256,
        reference_package_sha256=V8_REFERENCE_PACKAGE_SHA256,
        manifest_sha256=V9_CANDIDATE_MANIFEST_SHA256,
        navigation_config_relative=HISTORICAL_CONFIG,
        experiment_id="barn-v9-training-c68bb69c-candidate",
        description="Exact deployment-disabled V9 sampled predictive tracker candidate",
    )
    isolated_pair = validate_isolated_policy_pair(reference_spec, candidate_spec)
    return V9TrainingPreflight(
        corpus_verification=verification,
        reference_spec=reference_spec,
        candidate_spec=candidate_spec,
        one_factor_delta=delta,
        isolated_pair=isolated_pair,
    )


def _new_run_id(now: datetime) -> str:
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"barn-v9-training-{stamp}-{uuid.uuid4().hex[:8]}"


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not _SAFE_RUN_ID.fullmatch(run_id):
        raise V9TrainingRunnerError("run_id is not a safe identifier")
    return run_id


def _run_paths(
    run_id: str,
    world_ids: Sequence[int],
    *,
    results_root: Path = DEFAULT_RESULTS_ROOT,
) -> tuple[Path, Path, dict[tuple[int, int, str], Path]]:
    identifier = _validate_run_id(run_id)
    values = validate_training_world_ids(world_ids)
    run_root = results_root / "runs" / identifier
    report_path = run_root / "report.json"
    evidence_root = run_root / "action-evidence"
    evidence_paths = {
        (world_id, 0, arm): evidence_root / f"world-{world_id}-trial-0-{arm}.v8ae"
        for world_id in values
        for arm in ("reference", "candidate")
    }
    return run_root, report_path, evidence_paths


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
        os.fchmod(stream.fileno(), 0o444)
        os.fsync(stream.fileno())


def _verify_immutable_action_evidence(paths: Mapping[tuple[int, int, str], Path]) -> None:
    for path in paths.values():
        try:
            metadata = os.lstat(path)
        except FileNotFoundError:
            raise V9TrainingRunnerError(f"paired run omitted action evidence: {path}") from None
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_mode & _WRITE_BITS
        ):
            raise V9TrainingRunnerError(f"action evidence is not immutable and unaliased: {path}")


def _metrics(paired: Mapping[str, Any], *, world_ids: Sequence[int]) -> dict[str, Any]:
    try:
        reference = paired["baseline"]["aggregate"]
        candidate = paired["candidate"]["aggregate"]
        comparison = paired["comparison"]
        deltas = comparison["candidate_minus_baseline"]
        outcomes = comparison["paired_outcomes"]
    except (KeyError, TypeError) as exc:
        raise V9TrainingRunnerError("paired evaluator returned a malformed metrics report") from exc
    return {
        "official_score": False,
        "leaderboard": False,
        "promotion_evidence": False,
        "world_count": len(world_ids),
        "world_ids": list(world_ids),
        "suite_seed": SUITE_SEED,
        "trials_per_world": TRIALS_PER_WORLD,
        "reference": reference,
        "candidate": candidate,
        "candidate_minus_reference": deltas,
        "paired_outcomes": outcomes,
    }


def run_training_screen_for_candidate(
    *,
    candidate_identity: V9TrainingCandidateIdentity,
    preflight_factory: Callable[[], V9TrainingPreflight],
    world_count: int = DEFAULT_WORLD_COUNT,
    workers: int = DEFAULT_WORKERS,
    run_id: str | None = None,
    description: str = DEFAULT_DESCRIPTION,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    isolated_planner_profile_authorization: (
        IsolatedPlannerProfileAuthorization | None
    ) = None,
) -> dict[str, Any]:
    """Execute one content-addressed challenger on training IDs only."""

    if not isinstance(candidate_identity, V9TrainingCandidateIdentity):
        raise TypeError("candidate_identity must be a V9TrainingCandidateIdentity")
    if not callable(preflight_factory):
        raise TypeError("preflight_factory must be callable")
    world_ids = training_world_ids(world_count)
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 128:
        raise V9TrainingRunnerError("workers must be an integer in [1, 128]")
    normalized_description = description.strip()
    if not normalized_description or len(normalized_description) > 2048:
        raise V9TrainingRunnerError("description must contain 1--2048 non-whitespace characters")
    now = datetime.now(timezone.utc)
    identifier = _validate_run_id(run_id or _new_run_id(now))
    run_root, report_path, evidence_paths = _run_paths(
        identifier,
        world_ids,
        results_root=results_root,
    )
    if os.path.lexists(run_root):
        raise FileExistsError(f"refusing to replace V9 training run: {identifier}")

    preflight = preflight_factory()
    if not isinstance(preflight, V9TrainingPreflight):
        raise TypeError("preflight_factory must return V9TrainingPreflight")
    if isolated_planner_profile_authorization is not None:
        if not isinstance(
            isolated_planner_profile_authorization,
            IsolatedPlannerProfileAuthorization,
        ):
            raise TypeError(
                "isolated_planner_profile_authorization must be an "
                "IsolatedPlannerProfileAuthorization"
            )
        isolated_planner_profile_authorization.validate_candidate_report_identity(
            package_sha256=candidate_identity.package_sha256,
            manifest_sha256=candidate_identity.manifest_sha256,
            experiment_id=candidate_identity.experiment_id,
        )
        validated_pair = isolated_planner_profile_authorization.validate_pair(
            preflight.reference_spec,
            preflight.candidate_spec,
        )
        if dict(preflight.isolated_pair) != validated_pair:
            raise V9TrainingRunnerError(
                "preflight isolated pair differs from planner-profile authorization"
            )
    schedule = candidate_first_alternating_schedule(len(world_ids) * TRIALS_PER_WORLD)
    paired = run_sensor_faithful_paired_comparison_with_v9_traces(
        assets_root=DEFAULT_ASSETS_ROOT,
        world_indices=world_ids,
        candidate_spec=preflight.candidate_spec,
        reference_spec=preflight.reference_spec,
        trials=TRIALS_PER_WORLD,
        suite_seed=SUITE_SEED,
        workers=workers,
        allow_experimental=True,
        generated_corpus=True,
        asset_manifest_sha256=EXPECTED_TRAINING_MANIFEST_SHA256,
        arm_order_schedule=schedule,
        action_evidence_paths=evidence_paths,
        isolated_planner_profile_authorization=(
            isolated_planner_profile_authorization
        ),
    )
    _verify_immutable_action_evidence(evidence_paths)
    metrics = _metrics(paired, world_ids=world_ids)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": identifier,
        "run_date_utc": now.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "evaluation_kind": EVALUATION_KIND,
        "official_score": False,
        "leaderboard": False,
        "promotion_evidence": False,
        "official_gazebo_score": False,
        "leaderboard_claim": False,
        "promotion_evidence_eligible": False,
        "policy_runs_rerunnable": True,
        "description": normalized_description,
        "corpus": {
            "id": CORPUS_ID,
            "manifest_id": MANIFEST_ID,
            "manifest_path": str(DEFAULT_MANIFEST.resolve()),
            **dict(preflight.corpus_verification),
            "assets_root": str(DEFAULT_ASSETS_ROOT.resolve()),
            "world_ids": list(world_ids),
        },
        "protocol": {
            "suite_seed": SUITE_SEED,
            "trials_per_world": TRIALS_PER_WORLD,
            "workers_requested": workers,
            "candidate_first_alternating_schedule": list(schedule),
            "arms_never_concurrent_within_pair": True,
            "action_evidence_required": True,
            "v9_step_traces_required": True,
        },
        "policy_pair": {
            "reference_package_sha256": V8_REFERENCE_PACKAGE_SHA256,
            "reference_manifest_sha256": V8_REFERENCE_MANIFEST_SHA256,
            "reference_experimental": False,
            **candidate_identity.report_metadata(),
            "one_factor_delta": dict(preflight.one_factor_delta),
            "isolated_pair": dict(preflight.isolated_pair),
        },
        "metrics": metrics,
        "paired_report": paired,
    }
    _write_immutable_json(report_path, report)

    ledger: LedgerWriteResult = record_evaluation_run(
        benchmark_id=EVALUATION_KIND,
        benchmark_source=BARN_SOURCE,
        benchmark_source_commit=BARN_EVALUATOR_COMMIT,
        change_description=normalized_description,
        aggregate_metrics=metrics,
        report_path=report_path,
        ledger_dir=results_root / "ledger",
        run_id=identifier,
        timestamp_utc=now,
        agent_id=preflight.candidate_spec.agent_id,
        adapter_id=preflight.candidate_spec.adapter_id,
        adapter_hash=preflight.candidate_spec.implementation_sha256,
        config_id=preflight.candidate_spec.config_id,
        config_hash=preflight.candidate_spec.config_sha256,
        model_id=preflight.candidate_spec.model_id,
        model_hash=preflight.candidate_spec.model_artifact_sha256,
    )
    return {
        "run_id": identifier,
        "run_date_utc": report["run_date_utc"],
        "report_path": str(report_path.resolve()),
        "ledger_record_path": str(ledger.record_path.resolve()),
        "ledger_index_path": str(ledger.index_path.resolve()),
        "world_count": len(world_ids),
        "official_score": False,
        "leaderboard": False,
        "promotion_evidence": False,
        "metrics": metrics,
    }


def run_training_screen(
    *,
    world_count: int = DEFAULT_WORLD_COUNT,
    workers: int = DEFAULT_WORKERS,
    run_id: str | None = None,
    description: str = DEFAULT_DESCRIPTION,
) -> dict[str, Any]:
    """Execute the frozen initial challenger; never access IDs 5100 or above."""

    return run_training_screen_for_candidate(
        candidate_identity=INITIAL_CANDIDATE_IDENTITY,
        preflight_factory=_preflight_training_inputs,
        world_count=world_count,
        workers=workers,
        run_id=run_id,
        description=description,
        results_root=DEFAULT_RESULTS_ROOT,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-count", type=int, choices=ALLOWED_WORLD_COUNTS, default=10)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--run-id")
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    args = parser.parse_args(argv)
    summary = run_training_screen(
        world_count=args.world_count,
        workers=args.workers,
        run_id=args.run_id,
        description=args.description,
    )
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "ALLOWED_WORLD_COUNTS",
    "DEFAULT_WORKERS",
    "DEFAULT_WORLD_COUNT",
    "EVALUATION_KIND",
    "EXPECTED_TRAINING_CORPUS_SHA256",
    "EXPECTED_TRAINING_MANIFEST_SHA256",
    "INITIAL_CANDIDATE_IDENTITY",
    "SUITE_SEED",
    "TRIALS_PER_WORLD",
    "V9TrainingCandidateIdentity",
    "V9TrainingRunnerError",
    "candidate_first_alternating_schedule",
    "main",
    "run_training_screen",
    "run_training_screen_for_candidate",
    "training_world_ids",
    "validate_training_world_ids",
]
