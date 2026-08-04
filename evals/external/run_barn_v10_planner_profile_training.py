"""Run the frozen V10 planner-profile candidate on training worlds 5000--5009.

This wrapper exposes no development, holdout, deployment, 100-world, world-ID,
or candidate-path option.  Before delegating to the unchanged shared V9
training evaluator, it authenticates the V10 freeze, exact materialized
one-file bundle delta, complete shared training corpus, and isolated V8/V10
runtime pair.  Any resulting evidence remains non-official training evidence.
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
    IsolatedPlannerProfileAuthorization,
    parcel_isolated_bundle_candidate_spec,
    parcel_isolated_bundle_reference_spec,
)
from .barn_profile_candidate_bundle import (
    DEFAULT_DESTINATION_ROOT,
    verify_planner_profile_candidate_delta,
)
from .barn_v10_planner_profile import (
    CANDIDATE_FREEZE_PATH,
    CANDIDATE_FREEZE_SHA256,
    CANDIDATE_MANIFEST_SHA256,
    CANDIDATE_PACKAGE_SHA256,
    NAVIGATION_CONFIG_SHA256,
    PROFILE_SHA256,
    REFERENCE_MANIFEST_SHA256,
    REFERENCE_PACKAGE_SHA256,
    REFERENCE_PROFILE_SHA256,
    verify_v10_planner_profile,
)
from .barn_v10_planner_profile import TRAINING_WORLD_IDS as FROZEN_SCREEN_WORLD_IDS
from .barn_v10_planner_profile_candidate import V10_PLANNER_PROFILE_SPEC
from .generate_sampled_predictive_tracker_v9_training import (
    CORPUS_ID,
    DEFAULT_MANIFEST,
    TRAINING_WORLD_IDS,
    verify_training_corpus,
)

DEFAULT_WORLD_COUNT = 10
ALLOWED_WORLD_COUNTS = (10,)
DEFAULT_DESCRIPTION = (
    "Training-only 10-world screen of frozen V10 planner-profile f0b3c157 against exact "
    "rejected V8 control 189ac31f; the grid_v1 comfort-cost and observed-first reachable-"
    "frontier profile is the sole candidate payload factor; no development, holdout, or "
    "deployment access."
)
DEFAULT_CANDIDATE_ROOT = (
    DEFAULT_DESTINATION_ROOT / f"parcel-profile-candidate-{CANDIDATE_PACKAGE_SHA256}"
)
CANDIDATE_IDENTITY = shared.V9TrainingCandidateIdentity(
    package_sha256=CANDIDATE_PACKAGE_SHA256,
    manifest_sha256=CANDIDATE_MANIFEST_SHA256,
    experiment_id="barn-v10-training-planner-profile-f0b3c157",
    description="Exact deployment-disabled V10 one-file planner-profile candidate",
    freeze_path=str(CANDIDATE_FREEZE_PATH.resolve()),
    freeze_sha256=CANDIDATE_FREEZE_SHA256,
)
PLANNER_PROFILE_AUTHORIZATION = IsolatedPlannerProfileAuthorization(
    reference_package_sha256=REFERENCE_PACKAGE_SHA256,
    reference_manifest_sha256=REFERENCE_MANIFEST_SHA256,
    candidate_package_sha256=CANDIDATE_PACKAGE_SHA256,
    candidate_manifest_sha256=CANDIDATE_MANIFEST_SHA256,
    reference_model_artifact_sha256=REFERENCE_PROFILE_SHA256,
    candidate_model_artifact_sha256=PROFILE_SHA256,
    navigation_config_sha256=NAVIGATION_CONFIG_SHA256,
    model_id="grid_v1",
    reference_policy_id="barn-v10-training-v8-189ac31f-control",
    candidate_policy_id=CANDIDATE_IDENTITY.experiment_id,
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
            "verified V10 training manifest/corpus identity is not exact"
        )
    if tuple(TRAINING_WORLD_IDS[:DEFAULT_WORLD_COUNT]) != FROZEN_SCREEN_WORLD_IDS:
        raise shared.V9TrainingRunnerError(
            "shared training prefix differs from frozen V10 worlds 5000--5009"
        )

    frozen = verify_v10_planner_profile()
    candidate = verify_policy_bundle(
        DEFAULT_CANDIDATE_ROOT,
        expected_package_sha256=CANDIDATE_PACKAGE_SHA256,
        expected_manifest_sha256=CANDIDATE_MANIFEST_SHA256,
    )
    delta = verify_planner_profile_candidate_delta(
        candidate,
        frozen.plan.reference,
        spec=V10_PLANNER_PROFILE_SPEC,
        expected_profile_sha256=PROFILE_SHA256,
    )
    if delta != frozen.plan.delta:
        raise shared.V9TrainingRunnerError(
            "materialized V10 planner-profile bundle differs from its frozen plan"
        )

    reference_spec = parcel_isolated_bundle_reference_spec(
        frozen.plan.reference.root,
        package_sha256=REFERENCE_PACKAGE_SHA256,
        manifest_sha256=REFERENCE_MANIFEST_SHA256,
        navigation_config_relative=HISTORICAL_CONFIG,
        reference_id="barn-v10-training-v8-189ac31f-control",
        description="Exact rejected V8 189ac31f experimental control for V10 training",
    )
    candidate_spec = parcel_isolated_bundle_candidate_spec(
        candidate.root,
        package_sha256=CANDIDATE_PACKAGE_SHA256,
        reference_package_sha256=REFERENCE_PACKAGE_SHA256,
        manifest_sha256=CANDIDATE_MANIFEST_SHA256,
        navigation_config_relative=HISTORICAL_CONFIG,
        experiment_id=CANDIDATE_IDENTITY.experiment_id,
        description=CANDIDATE_IDENTITY.description,
    )
    isolated_pair = PLANNER_PROFILE_AUTHORIZATION.validate_pair(
        reference_spec,
        candidate_spec,
    )
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
    """Run the only frozen V10 screen: training IDs 5000--5009."""

    if isinstance(world_count, bool) or world_count not in ALLOWED_WORLD_COUNTS:
        raise shared.V9TrainingRunnerError(
            "V10 planner-profile world_count must be exactly 10"
        )
    return shared.run_training_screen_for_candidate(
        candidate_identity=CANDIDATE_IDENTITY,
        preflight_factory=_preflight_training_inputs,
        world_count=world_count,
        workers=workers,
        run_id=run_id,
        description=description,
        results_root=shared.DEFAULT_RESULTS_ROOT if results_root is None else results_root,
        isolated_planner_profile_authorization=PLANNER_PROFILE_AUTHORIZATION,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--world-count",
        type=int,
        choices=ALLOWED_WORLD_COUNTS,
        default=DEFAULT_WORLD_COUNT,
    )
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
    "PLANNER_PROFILE_AUTHORIZATION",
    "main",
    "run_training_screen",
]
