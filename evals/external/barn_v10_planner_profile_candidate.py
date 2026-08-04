"""V10 training-only planner-profile candidate declaration.

This internal declaration contains no canonical package or manifest constants
and exposes only read-only planning.  The authenticated public materialization
entry point lives in :mod:`evals.external.barn_v10_planner_profile`.
"""

from __future__ import annotations

from pathlib import Path

from .barn_profile_candidate_bundle import (
    DEFAULT_REFERENCE_ROOT,
    V8_REFERENCE_MANIFEST_SHA256,
    V8_REFERENCE_PACKAGE_SHA256,
    PlannerProfileCandidatePlan,
    PlannerProfileSpec,
    plan_planner_profile_candidate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_SOURCE = (
    REPO_ROOT
    / "evals/external/experiments/barn_planner_profile_v10/candidate/grid.yaml"
)
PROFILE_DESTINATION = "configs/navigation/models/grid.yaml"

V10_PLANNER_PROFILE_SPEC = PlannerProfileSpec(
    derivation_id="parcel-v10-planner-profile-from-v8-189ac31f-unfrozen-v1",
    candidate_label="frontier-comfort-grid-v1",
    source_id="experiment:barn_planner_profile_v10/candidate/grid.yaml",
    replacement_destination=PROFILE_DESTINATION,
    active_model="grid_v1",
    retained_controller_values=(("map_safety_margin_m", 0.10),),
    added_controller_values=(
        ("comfort_cost_weight", 8.0),
        ("frontier_band_m", 0.60),
        ("frontier_min_progress_m", 0.10),
        ("frontier_search_mode", "observed_first"),
        ("map_comfort_safety_margin_m", 0.48),
        ("reachable_frontier_fallback", True),
    ),
)


def plan_v10_planner_profile_candidate(
    *,
    profile_source_path: str | Path = PROFILE_SOURCE,
    reference_root: str | Path = DEFAULT_REFERENCE_ROOT,
    expected_reference_package_sha256: str = V8_REFERENCE_PACKAGE_SHA256,
    expected_reference_manifest_sha256: str = V8_REFERENCE_MANIFEST_SHA256,
) -> PlannerProfileCandidatePlan:
    """Plan the candidate without materializing or authorizing it."""

    return plan_planner_profile_candidate(
        spec=V10_PLANNER_PROFILE_SPEC,
        profile_source_path=profile_source_path,
        reference_root=reference_root,
        expected_reference_package_sha256=expected_reference_package_sha256,
        expected_reference_manifest_sha256=expected_reference_manifest_sha256,
    )
__all__ = [
    "PROFILE_DESTINATION",
    "PROFILE_SOURCE",
    "V10_PLANNER_PROFILE_SPEC",
    "plan_v10_planner_profile_candidate",
]
