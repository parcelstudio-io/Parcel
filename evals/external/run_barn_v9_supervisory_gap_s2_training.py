"""Run the frozen supervisory-gap S2 candidate on its 10 training worlds.

This wrapper has no development, holdout, 100-world, or candidate-path code
path.  It authenticates the S2 scratch freeze, exact content-addressed bundle,
complete V9 training corpus, and V8 experimental control before delegating to
the shared immutable V9 training runner.  Its output is rerunnable scratch
evidence only.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import run_sampled_predictive_tracker_v9_training as shared
from .barn_policy_sidecar import HISTORICAL_CONFIG, verify_policy_bundle
from .barn_policy_specs import (
    parcel_isolated_bundle_candidate_spec,
    parcel_isolated_bundle_reference_spec,
    validate_isolated_policy_pair,
)
from .barn_v9_policy_bundle import DEFAULT_DESTINATION_ROOT, verify_v9_candidate_delta
from .barn_v9_supervisory_gap_s2 import (
    CANDIDATE_MANIFEST_SHA256,
    CANDIDATE_PACKAGE_SHA256,
    SCRATCH_FREEZE_PATH,
    SCRATCH_FREEZE_SHA256,
    verify_supervisory_gap_s2,
)
from .generate_sampled_predictive_tracker_v9_training import (
    CORPUS_ID,
    DEFAULT_MANIFEST,
    TRAINING_WORLD_IDS,
    verify_training_corpus,
)

DEFAULT_WORLD_COUNT = 10
ALLOWED_WORLD_COUNTS = (10,)
DEFAULT_DESCRIPTION = (
    "Training-only 10-world screen of frozen supervisory-gap S2 68e3e666 against exact "
    "rejected V8 control 189ac31f; reaction-sweep nominal admission, corrected escape "
    "settling, persistent observation counters, and bounded detour continuity are the "
    "only candidate factor; no development or holdout access."
)
DEFAULT_CANDIDATE_ROOT = (
    DEFAULT_DESTINATION_ROOT / f"parcel-v9-candidate-{CANDIDATE_PACKAGE_SHA256}"
)
CANDIDATE_IDENTITY = shared.V9TrainingCandidateIdentity(
    package_sha256=CANDIDATE_PACKAGE_SHA256,
    manifest_sha256=CANDIDATE_MANIFEST_SHA256,
    experiment_id="barn-v9-training-supervisory-gap-s2-68e3e666",
    description="Exact deployment-disabled supervisory-gap S2 scratch candidate",
    freeze_path=str(SCRATCH_FREEZE_PATH.resolve()),
    freeze_sha256=SCRATCH_FREEZE_SHA256,
)


def _preflight_training_inputs() -> shared.V9TrainingPreflight:
    verification = verify_training_corpus(DEFAULT_MANIFEST)
    expected = {
        "corpus_id": CORPUS_ID,
        "corpus_sha256": shared.EXPECTED_TRAINING_CORPUS_SHA256,
        "manifest_sha256": shared.EXPECTED_TRAINING_MANIFEST_SHA256,
        "promotion_evidence_eligible": False,
        "world_count": len(TRAINING_WORLD_IDS),
    }
    if verification != expected:
        raise shared.V9TrainingRunnerError(
            "verified S2 training manifest/corpus identity is not exact"
        )

    frozen = verify_supervisory_gap_s2()
    candidate = verify_policy_bundle(
        DEFAULT_CANDIDATE_ROOT,
        expected_package_sha256=CANDIDATE_PACKAGE_SHA256,
        expected_manifest_sha256=CANDIDATE_MANIFEST_SHA256,
    )
    delta = verify_v9_candidate_delta(
        candidate,
        frozen.plan.reference,
        expected_source_contract=frozen.plan.source_contract.manifest_record(),
    )
    if delta != frozen.plan.delta:
        raise shared.V9TrainingRunnerError(
            "materialized supervisory-gap S2 bundle differs from its frozen plan"
        )

    reference_spec = parcel_isolated_bundle_reference_spec(
        frozen.plan.reference.root,
        package_sha256=shared.V8_REFERENCE_PACKAGE_SHA256,
        manifest_sha256=shared.V8_REFERENCE_MANIFEST_SHA256,
        navigation_config_relative=HISTORICAL_CONFIG,
        reference_id="barn-v9-training-v8-189ac31f-control",
        description="Exact rejected V8 189ac31f experimental control for S2 training",
    )
    candidate_spec = parcel_isolated_bundle_candidate_spec(
        candidate.root,
        package_sha256=CANDIDATE_PACKAGE_SHA256,
        reference_package_sha256=shared.V8_REFERENCE_PACKAGE_SHA256,
        manifest_sha256=CANDIDATE_MANIFEST_SHA256,
        navigation_config_relative=HISTORICAL_CONFIG,
        experiment_id=CANDIDATE_IDENTITY.experiment_id,
        description=CANDIDATE_IDENTITY.description,
    )
    isolated_pair = validate_isolated_policy_pair(reference_spec, candidate_spec)
    return shared.V9TrainingPreflight(
        corpus_verification=verification,
        reference_spec=reference_spec,
        candidate_spec=candidate_spec,
        one_factor_delta=delta,
        isolated_pair=isolated_pair,
    )


def run_training_screen(
    *,
    world_count: int = DEFAULT_WORLD_COUNT,
    workers: int = shared.DEFAULT_WORKERS,
    run_id: str | None = None,
    description: str = DEFAULT_DESCRIPTION,
    results_root: Path | None = None,
) -> dict[str, Any]:
    """Run the only predeclared S2 screen: training IDs 5000--5009."""

    if world_count not in ALLOWED_WORLD_COUNTS:
        raise shared.V9TrainingRunnerError(
            "supervisory-gap S2 world_count must be exactly 10"
        )
    return shared.run_training_screen_for_candidate(
        candidate_identity=CANDIDATE_IDENTITY,
        preflight_factory=_preflight_training_inputs,
        world_count=world_count,
        workers=workers,
        run_id=run_id,
        description=description,
        results_root=shared.DEFAULT_RESULTS_ROOT if results_root is None else results_root,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-count", type=int, choices=ALLOWED_WORLD_COUNTS, default=10)
    parser.add_argument("--workers", type=int, default=shared.DEFAULT_WORKERS)
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
    "CANDIDATE_IDENTITY",
    "DEFAULT_CANDIDATE_ROOT",
    "DEFAULT_DESCRIPTION",
    "DEFAULT_WORLD_COUNT",
    "main",
    "run_training_screen",
]
