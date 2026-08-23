from __future__ import annotations

import json
import math
from pathlib import Path

from _external_roots import skip_unless

from evals.external.barn_native import BarnObservation
from evals.external.barn_policy_sidecar import HISTORICAL_CONFIG
from evals.external.barn_policy_specs import parcel_isolated_bundle_candidate_spec
from evals.external.barn_v9_policy_bundle import (
    V8_REFERENCE_PACKAGE_SHA256,
    plan_v9_candidate_bundle,
    prepare_v9_candidate_bundle,
)

EXPECTED_CANDIDATE_PACKAGE_SHA256 = (
    "c68bb69c247404d0deee28f26d8000200f73aeb336fb9bb0cafd0f0c3b510833"
)
EXPECTED_CANDIDATE_MANIFEST_SHA256 = (
    "540658cee91c2bdb058f54ab19b9838d731f49c7be4df6ef7332aaea631b8b08"
)
EXPERIMENT_ROOT = (
    Path(__file__).resolve().parents[1]
    / "evals/external/experiments/barn_sampled_predictive_tracker_v9"
)


@skip_unless("barn-policy-bundles")
def test_exact_candidate_bundle_runs_through_the_isolated_policy_sidecar(tmp_path) -> None:
    plan = plan_v9_candidate_bundle()
    freeze = json.loads((EXPERIMENT_ROOT / "CANDIDATE_FREEZE.json").read_bytes())
    assert plan.package_sha256 == EXPECTED_CANDIDATE_PACKAGE_SHA256
    assert plan.manifest_sha256 == EXPECTED_CANDIDATE_MANIFEST_SHA256
    assert freeze["candidate"] == {
        "controller_id": "parcel-directive-navigator-grid-v1-v9-sampled-predictive-tracker",
        "manifest_sha256": plan.manifest_sha256,
        "package_sha256": plan.package_sha256,
    }
    assert freeze["candidate_source_contract_sha256"] == plan.source_contract.contract_sha256
    assert freeze["development_execution_authorized"] is False
    assert freeze["holdout_execution_authorized"] is False
    candidate = prepare_v9_candidate_bundle(
        expected_candidate_package_sha256=EXPECTED_CANDIDATE_PACKAGE_SHA256,
        expected_candidate_manifest_sha256=EXPECTED_CANDIDATE_MANIFEST_SHA256,
        destination_root=tmp_path / "bundles",
    )
    assert candidate.delta["one_factor_tracker_subsystem_delta"] is True
    assert candidate.delta["adapter_or_evaluator_source_changed"] is False
    assert candidate.delta["all_ray_safety_shield_changed"] is False

    spec = parcel_isolated_bundle_candidate_spec(
        candidate.root,
        package_sha256=candidate.package_sha256,
        reference_package_sha256=V8_REFERENCE_PACKAGE_SHA256,
        manifest_sha256=candidate.manifest_sha256,
        navigation_config_relative=HISTORICAL_CONFIG,
        experiment_id="barn-v9-candidate-integration",
        description="Exact V9 candidate isolated sidecar integration smoke",
    )
    policy = spec.create(episode_seed=20260803, allow_experimental=True)
    try:
        policy.reset((0.0, 0.0), 0.0, (4.0, 0.0))
        ray_count = 720
        normalized_ranges = [math.inf] * ray_count
        normalized_ranges[0] = math.nan
        action = policy.act(
            BarnObservation(
                position_xy=(0.0, 0.0),
                heading_rad=0.0,
                lidar_ranges_m=tuple(normalized_ranges),
                lidar_angle_min_rad=-math.pi,
                lidar_angle_increment_rad=(2.0 * math.pi) / (ray_count - 1),
                time_s=0.0,
            )
        )
    finally:
        policy.close()

    assert action.stop is False
    assert 0.0 < action.vx_mps <= 0.09 + 1e-12
    assert abs(action.yaw_rate_rps) <= 0.18 + 1e-12
    assert "v9_sampled_track" in action.note
    assert "all_ray_observed_returns_only_incomplete_scan" in action.note
