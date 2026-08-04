from __future__ import annotations

import json

import pytest
import yaml

from evals.external.barn_profile_candidate_bundle import (
    V8_REFERENCE_MANIFEST_SHA256,
    V8_REFERENCE_PACKAGE_SHA256,
)
from evals.external.barn_v10_planner_profile_candidate import (
    PROFILE_DESTINATION,
    PROFILE_SOURCE,
    V10_PLANNER_PROFILE_SPEC,
    plan_v10_planner_profile_candidate,
)
from parcel_robot.navigation.registry import ModelRegistry


def test_real_v10_candidate_is_a_read_only_one_profile_plan() -> None:
    plan = plan_v10_planner_profile_candidate()

    assert plan.reference.package_sha256 == V8_REFERENCE_PACKAGE_SHA256
    assert plan.reference.manifest_sha256 == V8_REFERENCE_MANIFEST_SHA256
    assert plan.spec is V10_PLANNER_PROFILE_SPEC
    assert plan.profile_source == PROFILE_SOURCE.read_bytes()
    assert plan.delta["replacements"] == [PROFILE_DESTINATION]
    assert plan.delta["additions"] == []
    assert plan.delta["unchanged_reference_file_count"] == 116
    assert plan.delta["all_other_file_bytes_identical_to_reference"] is True
    assert plan.delta["training_only"] is True
    assert plan.delta["external_identity_freeze_required_before_real_materialization"] is True
    assert plan.delta["development_execution_authorized"] is False
    assert plan.delta["holdout_execution_authorized"] is False
    assert plan.delta["deployment_enabled"] is False

    manifest = json.loads(plan.manifest_payload)
    reference_manifest = json.loads(plan.reference.manifest_path.read_bytes())
    assert manifest["navigation"] == reference_manifest["navigation"]
    assert manifest["navigation"]["config"] == (
        "configs/navigation/experiments/barn_grid_v1.yaml"
    )
    assert manifest["experiment_derivation"]["active_model_id_changed"] is False
    assert manifest["experiment_derivation"]["experiment_config_changed"] is False
    changed = {
        relative
        for relative, digest in plan.reference.files_sha256.items()
        if manifest["files_sha256"][relative] != digest
    }
    assert changed == {PROFILE_DESTINATION}


def test_real_profile_keeps_grid_v1_and_declares_only_frontier_clearance_fields() -> None:
    profile = yaml.safe_load(PROFILE_SOURCE.read_text(encoding="utf-8"))
    controller = profile["controller"]

    assert profile["id"] == "grid_v1"
    assert controller["map_safety_margin_m"] == 0.10
    assert controller["map_comfort_safety_margin_m"] == 0.48
    assert controller["comfort_cost_weight"] == 8.0
    assert controller["reachable_frontier_fallback"] is True
    assert controller["frontier_search_mode"] == "observed_first"
    assert controller["frontier_band_m"] == 0.60
    assert controller["frontier_min_progress_m"] == 0.10
    assert dict(V10_PLANNER_PROFILE_SPEC.added_controller_values) == {
        "comfort_cost_weight": 8.0,
        "frontier_band_m": 0.60,
        "frontier_min_progress_m": 0.10,
        "frontier_search_mode": "observed_first",
        "map_comfort_safety_margin_m": 0.48,
        "reachable_frontier_fallback": True,
    }


def test_real_profile_resolves_to_the_frozen_planner_with_aligned_effective_radii(
    tmp_path,
) -> None:
    # The current planner/navigator bytes are checked separately by the bundle
    # derivation and are byte-identical to V8.  Loading the reviewed YAML in an
    # isolated model root proves the values reach the controller constructor,
    # rather than merely existing as inert YAML fields.
    profile = tmp_path / "grid.yaml"
    profile.write_bytes(PROFILE_SOURCE.read_bytes())

    navigator = ModelRegistry.load(tmp_path).create("grid_v1", arrive_radius_m=0.5)
    config = navigator._planner.config

    assert config.effective_hard_margin_m == 0.10
    assert config.inflation_radius_m == pytest.approx(0.42)
    assert config.effective_comfort_margin_m == 0.48
    assert config.comfort_radius_m == pytest.approx(0.80)
    assert config.comfort_cost_enabled is True
    assert config.comfort_cost_weight == 8.0
    assert config.reachable_frontier_fallback is True
    assert config.frontier_search_mode == "observed_first"
