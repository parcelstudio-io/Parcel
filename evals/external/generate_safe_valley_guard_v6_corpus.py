"""Generate and freeze the disjoint BARN-style safe-valley-guard v6 corpus.

This is a one-shot development corpus for one narrow ablation: relative to v5,
add half an occupancy-cell diagonal to raw-valley admission and the swept body
envelope.  IDs and seeds are disjoint from public BARN, v4, and every v5
development/confirmation identity.  Confirmation is a recipe only: this module
has no code path that generates its geometry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .barn_policy_specs import PARCEL_POLICY_SOURCE_ROOT, REPO_ROOT, _source_tree_sha256
from .generate_safe_valley_v5_corpus import (
    GENERATOR_COMMIT,
    GENERATOR_SOURCE,
    _corpus_sha256,
    _frozen_file,
    _generate_development_assets,
    _generator_inputs,
    _ids_sha256,
    _verify_generator,
    _write_exclusive_json,
)

CORPUS_ID = "barn-safe-valley-guard-v6-generated-20260803-dev30-sealed20"
DEVELOPMENT_WORLD_IDS = tuple(range(2000, 2030))
SEALED_CONFIRMATION_WORLD_IDS = tuple(range(2030, 2050))
SEED_NAMESPACE = "parcel-safe-valley-guard-v6-generated-corpus-20260803"
DEFAULT_GENERATOR_ROOT = REPO_ROOT / ".cache" / "external-evals" / "repos" / "barn_generator"
DEFAULT_ASSETS_ROOT = (
    REPO_ROOT
    / ".cache"
    / "external-evals"
    / "generated"
    / "barn_safe_valley_guard_v6"
    / "development"
    / "test_data"
)
DEFAULT_MANIFEST = (
    REPO_ROOT / "evals" / "external" / "development" / "barn_safe_valley_guard_v6" / "split.json"
)

REFERENCE_CONFIG = (
    REPO_ROOT / "configs" / "navigation" / "experiments" / "barn_grid_safe_valley_v5.yaml"
)
REFERENCE_MODEL = REPO_ROOT / "configs" / "navigation" / "models" / "grid_safe_valley_v5.yaml"
CHALLENGER_CONFIG = (
    REPO_ROOT / "configs" / "navigation" / "experiments" / "barn_grid_safe_valley_guard_v6.yaml"
)
CHALLENGER_MODEL = (
    REPO_ROOT / "configs" / "navigation" / "models" / "grid_safe_valley_guard_v6.yaml"
)

# Frozen before either arm executes. This is a safety/liveness ablation, so a
# success gain is not required, but every quality/safety/latency condition and
# at least one deterministic trajectory effect are required together.
PROMOTION_GATE: dict[str, Any] = {
    "reference_policy": "grid_safe_valley_v5",
    "candidate_policy": "grid_safe_valley_guard_v6",
    "same_world_trial_seed_native_config_and_manifest": True,
    "guarded_safe_valley_advance_phase_must_be_exercised": True,
    "minimum_guard_affected_paired_episodes": 1,
    "maximum_paired_success_regressions": 0,
    "navigation_metric_delta_must_be_nonnegative": True,
    "candidate_collision_rate_must_equal": 0.0,
    "candidate_timeout_rate_must_equal": 0.0,
    "candidate_timeout_rate_must_not_exceed_reference": True,
    "minimum_signed_clearance_must_be_at_least": 0.075,
    "maximum_clearance_floor_regression_m": 0.0,
    "maximum_controller_p99_latency_ms": 100.0,
    "maximum_controller_p99_latency_ratio": 1.20,
    "all_conditions_required_for_single_sealed_confirmation": True,
}


def _seed(world_id: int, attempt: int) -> int:
    payload = f"{SEED_NAMESPACE}:{world_id}:{attempt}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & 0x7FFF_FFFF


def _parameters(world_id: int) -> tuple[float, int]:
    offset = world_id - DEVELOPMENT_WORLD_IDS[0]
    fill_percent = (0.15, 0.20, 0.25, 0.30)[(offset // 3) % 4]
    smooth_iterations = (2, 3, 4)[offset % 3]
    return fill_percent, smooth_iterations


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def generate_corpus(
    *,
    generator_root: Path = DEFAULT_GENERATOR_ROOT,
    assets_root: Path = DEFAULT_ASSETS_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    """Generate development only, then freeze all policy/harness inputs."""

    generator_root = generator_root.expanduser().resolve()
    assets_root = assets_root.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve()
    if manifest_path.exists():
        raise FileExistsError(f"refusing to replace frozen manifest: {manifest_path}")
    if assets_root.exists():
        raise FileExistsError(f"refusing to replace generated assets: {assets_root}")
    _verify_generator(generator_root)
    episodes, generation_log_sha256 = _generate_development_assets(
        generator_root=generator_root,
        assets_root=assets_root,
        world_ids=DEVELOPMENT_WORLD_IDS,
        corpus_id=CORPUS_ID,
        temporary_prefix=".safe-valley-guard-v6-",
        seed_for=_seed,
        parameters_for=_parameters,
    )

    # Public/static identities and all v5 development/confirmation identities
    # are forbidden. V4 uses public IDs and is covered by 0--299.
    forbidden_ids = tuple(range(300)) + tuple(range(1000, 1050))
    if set(DEVELOPMENT_WORLD_IDS) & set(forbidden_ids):
        raise AssertionError("v6 development IDs overlap prior evidence")
    if set(DEVELOPMENT_WORLD_IDS) & set(SEALED_CONFIRMATION_WORLD_IDS):
        raise AssertionError("v6 development and confirmation IDs overlap")

    source_files = {
        "evals_package": REPO_ROOT / "evals" / "__init__.py",
        "external_package": REPO_ROOT / "evals" / "external" / "__init__.py",
        "adapter": REPO_ROOT / "evals" / "external" / "parcel_barn_adapter.py",
        "barn_native": REPO_ROOT / "evals" / "external" / "barn_native.py",
        "barn_targets": REPO_ROOT / "evals" / "external" / "barn_targets.py",
        "policy_specs": REPO_ROOT / "evals" / "external" / "barn_policy_specs.py",
        "run_barn": REPO_ROOT / "evals" / "external" / "run_barn.py",
        "compare_barn": REPO_ROOT / "evals" / "external" / "compare_barn.py",
        "ledger": REPO_ROOT / "evals" / "external" / "ledger.py",
        "compatibility": REPO_ROOT / "evals" / "external" / "compatibility.py",
        "metrics": REPO_ROOT / "evals" / "external" / "metrics.py",
        "runner": REPO_ROOT / "evals" / "external" / "runner.py",
        "agents": REPO_ROOT / "evals" / "external" / "agents.py",
        "episodes": REPO_ROOT / "evals" / "external" / "episodes.py",
        "generator_engine": REPO_ROOT / "evals" / "external" / "generate_safe_valley_v5_corpus.py",
        "gate_helper": REPO_ROOT / "evals" / "external" / "run_safe_valley_v5.py",
        "generator_wrapper": Path(__file__),
        "experiment_runner": Path(__file__).with_name("run_safe_valley_guard_v6.py"),
    }
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "corpus_id": CORPUS_ID,
        "created_at": created_at,
        "purpose": (
            "One-shot disjoint generated development corpus and unopened confirmation recipe "
            "for the deployment-disabled safe-valley half-cell guard v6 ablation"
        ),
        "predeclared_hypothesis": {
            "single_behavioral_change": (
                "Add exactly resolution/sqrt(2) to v5 raw-valley admission and swept-envelope "
                "radius; make no scan-sweep, attempt-count, velocity, planner, or shield change."
            ),
            "targeted_v5_failures": {
                "clearance_floor_m": 0.07203440034836457,
                "timeout_count": 2,
            },
            "causal_prediction": (
                "Rejecting raster-edge advances will keep signed clearance at or above 0.075 m "
                "and stop marginal advances from delaying the existing progress watchdog into "
                "an episode timeout, without success, metric, collision, or CPU regression."
            ),
        },
        "benchmark_scope": {
            "evaluation_kind": "barn-native-headless-non-official-generated-development",
            "official_gazebo_score": False,
            "leaderboard_claim": False,
            "source_generator": GENERATOR_SOURCE,
            "source_generator_commit": GENERATOR_COMMIT,
            "source_generator_license": "NOASSERTION",
            "generator_inputs": _generator_inputs(generator_root),
        },
        "identity_partition": {
            "forbidden_static_public_and_v5_ids": list(forbidden_ids),
            "forbidden_ids_sha256": _ids_sha256(forbidden_ids),
            "development_world_ids": list(DEVELOPMENT_WORLD_IDS),
            "development_world_ids_sha256": _ids_sha256(DEVELOPMENT_WORLD_IDS),
            "sealed_confirmation_world_ids": list(SEALED_CONFIRMATION_WORLD_IDS),
            "sealed_confirmation_world_ids_sha256": _ids_sha256(SEALED_CONFIRMATION_WORLD_IDS),
            "development_disjoint_from_forbidden": True,
            "development_disjoint_from_confirmation": True,
            "namespace_note": (
                "IDs 2000+ are native-proxy corpus identifiers, never official/public BARN "
                "IDs 0-299; v5 IDs 1000-1049 are forbidden."
            ),
        },
        "development_corpus": {
            "assets_root": str(assets_root),
            "world_count": len(episodes),
            "corpus_sha256": _corpus_sha256(episodes),
            "generation_log_sha256": generation_log_sha256,
            "episodes": episodes,
        },
        "sealed_confirmation_recipe": {
            "generated": False,
            "opened": False,
            "evaluated": False,
            "seed_namespace": SEED_NAMESPACE,
            "seed_algorithm": (
                "uint64_be(sha256(namespace + ':' + world_id + ':' + attempt)[0:8]) "
                "bitwise-and 0x7fffffff; accept first connected map"
            ),
            "parameter_algorithm": (
                "same fixed 30x30 BARN fill/smoothing schedule as development, offset by "
                "world_id - 2000"
            ),
            "world_ids": list(SEALED_CONFIRMATION_WORLD_IDS),
            "single_use_only_after_all_development_gates_pass": True,
            "root_authorization_required_even_after_development_pass": True,
        },
        "frozen_policy_inputs_before_execution": {
            "reference_config": _frozen_file(REFERENCE_CONFIG),
            "reference_model": _frozen_file(REFERENCE_MODEL),
            "challenger_config": _frozen_file(CHALLENGER_CONFIG),
            "challenger_model": _frozen_file(CHALLENGER_MODEL),
            "policy_source_tree": {
                "path": _relative(PARCEL_POLICY_SOURCE_ROOT),
                "sha256": _source_tree_sha256(PARCEL_POLICY_SOURCE_ROOT),
            },
            "harness_files": {name: _frozen_file(path) for name, path in source_files.items()},
        },
        "protocol_frozen_before_development": {
            "suite_seed": 20260803,
            "trials_per_world": 1,
            "lidar_rays": 720,
            "episode_workers": 4,
            "paired_reference_replay_required": True,
            "reference_and_candidate_use_identical_assets_trials_seeds_native_config": True,
            "policy_inputs": ["goal", "odometry", "270_degree_lidar", "clock"],
            "evaluator_private_geometry_never_enters_policy": True,
            "sealed_confirmation_must_not_be_generated_opened_or_run_during_development": True,
        },
        "promotion_gate_frozen_before_development": PROMOTION_GATE,
        "status_at_freeze": {
            "development_assets_generated_and_hashed": True,
            "development_policy_execution_started": False,
            "sealed_confirmation_generated": False,
            "sealed_confirmation_opened": False,
            "sealed_confirmation_run_id": None,
            "deployment_enabled": False,
        },
    }
    _write_exclusive_json(manifest_path, manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generator-root", type=Path, default=DEFAULT_GENERATOR_ROOT)
    parser.add_argument("--assets-root", type=Path, default=DEFAULT_ASSETS_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    manifest = generate_corpus(
        generator_root=args.generator_root,
        assets_root=args.assets_root,
        manifest_path=args.manifest,
    )
    print(
        json.dumps(
            {
                "manifest": str(args.manifest.resolve()),
                "corpus_id": manifest["corpus_id"],
                "development_world_count": manifest["development_corpus"]["world_count"],
                "development_corpus_sha256": manifest["development_corpus"]["corpus_sha256"],
                "sealed_confirmation_generated": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "CHALLENGER_CONFIG",
    "CHALLENGER_MODEL",
    "CORPUS_ID",
    "DEFAULT_ASSETS_ROOT",
    "DEFAULT_MANIFEST",
    "DEVELOPMENT_WORLD_IDS",
    "GENERATOR_COMMIT",
    "PROMOTION_GATE",
    "REFERENCE_CONFIG",
    "REFERENCE_MODEL",
    "SEALED_CONFIRMATION_WORLD_IDS",
    "generate_corpus",
]
