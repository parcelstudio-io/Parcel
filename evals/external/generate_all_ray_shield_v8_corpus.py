"""Freeze the V8 all-ray-shield paired BARN development corpus.

This module has exactly one materialization path: 30 development worlds with
IDs 4000--4029.  IDs 4030--4049 are an operational holdout recipe only; there
is deliberately no function or command-line option that creates those assets.

World geometry still comes from the pinned upstream BARN generator.  The
development split adds an evaluator-private, policy-free geometry audit over
the generated reference paths.  It requires examples where the globally
nearest normalized LiDAR return is not the closing-speed limit and examples
where the reaction-horizon yaw sweep tightens that limit.  This targets the V8
hypothesis without executing either robot policy or exposing map geometry to a
policy.

Generation is single use and fail closed.  Inputs are snapshotted before and
after staging, an exclusive development directory claim precedes publication,
and the manifest is written exclusively.  A crash during either final operation
leaves an intentionally consumed, partial namespace that this module refuses
to retry.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .barn_native import BarnWorld, load_generated_barn_world
from .barn_policy_sidecar import (
    HISTORICAL_CONFIG,
    IsolatedPolicyDescriptor,
    verify_policy_bundle,
)
from .barn_policy_specs import (
    PARCEL_POLICY_SOURCE_ROOT,
    REPO_ROOT,
    parcel_isolated_bundle_candidate_spec,
    parcel_isolated_bundle_reference_spec,
    validate_isolated_policy_pair,
)
from .barn_ros2_adapter import BarnRos2SensorFrame, normalize_planar_lidar_frame
from .barn_sensor_faithful import (
    BARN_ROS2_BASE_FRAME_ID,
    BARN_ROS2_LIDAR_CALIBRATION,
    BARN_ROS2_LIDAR_FRAME_ID,
    CANDIDATE_THEN_REFERENCE,
    REFERENCE_THEN_CANDIDATE,
    CalibratedBarnConfig,
    cast_sensor_faithful_lidar,
    validate_paired_arm_order_schedule,
)
from .barn_v8_action_certifier import (
    FROZEN_V8_BARN_EVALUATOR_PROFILE,
    certify_v8_published_barn_action,
)
from .barn_v8_policy_bundle import (
    V8CandidateBundle,
    prepare_v8_candidate_bundle,
    verify_v8_candidate_delta,
)
from .generate_safe_valley_v5_corpus import (
    GENERATOR_COMMIT,
    GENERATOR_SOURCE,
    _asset_directories,
    _corpus_sha256,
    _generator_inputs,
    _ids_sha256,
    _load_upstream_generator,
    _verify_generator,
)
from .ledger import sha256_file

SCHEMA_VERSION = 2
PROTOCOL_ID = "parcel-barn-v8-all-ray-paired-development-v1"
CORPUS_ID = "barn-all-ray-shield-v8-generated-20260803-dev30-holdout20"
MANIFEST_ID = "barn-all-ray-shield-v8-development-split-v1"

DEVELOPMENT_WORLD_IDS = tuple(range(4000, 4030))
OPERATIONAL_HOLDOUT_WORLD_IDS = tuple(range(4030, 4050))
# Compatibility with earlier corpus vocabulary.  The split is operationally
# withheld, not cryptographically sealed, so new code should prefer the name
# above.
SEALED_CONFIRMATION_WORLD_IDS = OPERATIONAL_HOLDOUT_WORLD_IDS
FORBIDDEN_WORLD_ID_RANGES = ((0, 299), (1000, 1049), (2000, 2049), (3000, 3049))
FORBIDDEN_WORLD_IDS = tuple(
    world_id
    for lower, upper in FORBIDDEN_WORLD_ID_RANGES
    for world_id in range(lower, upper + 1)
)

SEED_NAMESPACE = "parcel-barn-all-ray-shield-v8-generated-corpus-20260803"
SUITE_SEED = 20260803
TRIALS_PER_WORLD = 1
EPISODE_WORKERS = 4

PAIRED_ARM_ORDER_SCHEDULE = tuple(
    REFERENCE_THEN_CANDIDATE if index % 2 == 0 else CANDIDATE_THEN_REFERENCE
    for index in range(len(DEVELOPMENT_WORLD_IDS))
)

DEFAULT_GENERATOR_ROOT = REPO_ROOT / ".cache/external-evals/repos/barn_generator"
DEFAULT_ASSETS_ROOT = (
    REPO_ROOT
    / ".cache/external-evals/generated/barn_all_ray_shield_v8/development/test_data"
)
DEFAULT_HOLDOUT_ASSETS_ROOT = (
    REPO_ROOT / ".cache/external-evals/generated/barn_all_ray_shield_v8/holdout/test_data"
)
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "evals/external/development/barn_all_ray_shield_v8/split.json"
)
PROTOCOL_PATH = (
    REPO_ROOT
    / "evals/external/development/barn_all_ray_shield_v8/PROTOCOL.json"
)

_PROBE_FORWARD_MPS = 0.45
_PROBE_YAW_RATE_RPS = 0.8
_PROBE_CONTROL_PERIOD_S = 0.1
_PROBE_REACTION_HORIZON_S = 0.12
_PROBE_STRICT_EPSILON = 1e-4
_TARGET_GLOBAL_NEAREST = "global_nearest_not_limiting"
_TARGET_ROTATION_LIMITED = "yaw_sweep_rotation_limited"
TARGET_ASSIGNMENTS = {
    world_id: (
        _TARGET_GLOBAL_NEAREST
        if offset < len(DEVELOPMENT_WORLD_IDS) // 2
        else _TARGET_ROTATION_LIMITED
    )
    for offset, world_id in enumerate(DEVELOPMENT_WORLD_IDS)
}

# Frozen before development generation or policy execution.  The runner must
# consume this exact declaration rather than quietly defining a second gate.
PROMOTION_GATE: dict[str, Any] = {
    "reference_policy": "historical-world0-75f7ff4d-exact-bundle",
    "candidate_policy": "historical-bundle-plus-reviewed-v8-all-ray-delta",
    "exact_one_factor_source_delta": True,
    "same_world_trial_seed_calibration_runtime_and_schedule": True,
    "maximum_candidate_observed_return_certificate_violations": 0,
    "no_perception_requires_zero_translation": True,
    "required_classified_rays_per_policy_issued_action": 720,
    "maximum_candidate_collisions": 0,
    "minimum_candidate_signed_body_clearance_m": 0.475,
    "maximum_paired_success_regressions": 0,
    "candidate_timeout_rate_must_not_exceed_reference": True,
    "minimum_mode_affected_paired_episodes": 1,
    "all_first_divergences_must_share_identical_observation": True,
    "minimum_global_nearest_not_limiting_cases": 1,
    "minimum_paired_success_gains": 3,
    "minimum_success_rate_delta": 0.10,
    "minimum_navigation_metric_delta": 0.01,
    "maximum_controller_p99_latency_ms": 100.0,
    "maximum_controller_p99_latency_ratio": 1.20,
    "evidence_and_certification_latency_excluded_from_controller_latency": True,
    "all_conditions_required_before_any_holdout_authorization": True,
}

FROZEN_CALIBRATED_CONFIG: dict[str, Any] = {
    "dt_s": 0.1,
    "lidar_angle_max_rad": math.pi,
    "lidar_angle_min_rad": -math.pi,
    "lidar_forward_m": 0.12,
    "lidar_range_max_m": 25.0,
    "lidar_range_min_m": 0.05,
    "lidar_ray_count": 720,
    "max_forward_speed_mps": 2.0,
    "max_reverse_speed_mps": 2.0,
    "max_sensor_skew_s": 0.05,
    "max_yaw_rate_rps": 4.0,
    "odometry_lag_s": 0.005,
    "robot_radius_m": 0.32,
    "sensor_stamp_origin_s": 1.0,
    "start_heading_rad": 1.57,
    "startup_timeout_s": 10.0,
    "success_radius_m": 1.0,
    "timeout_s": 100.0,
    "trace_max_samples": 256,
    "trace_stride_steps": 10,
    "trial_start_translation_m": 0.1,
}

SOURCE_FILES: dict[str, Path] = {
    "requirements_lock": REPO_ROOT / "requirements-lock.txt",
    "project_metadata": REPO_ROOT / "pyproject.toml",
    "evals_package": REPO_ROOT / "evals/__init__.py",
    "external_package": REPO_ROOT / "evals/external/__init__.py",
    "barn_native": REPO_ROOT / "evals/external/barn_native.py",
    "barn_ros2_adapter": REPO_ROOT / "evals/external/barn_ros2_adapter.py",
    "parcel_barn_adapter": REPO_ROOT / "evals/external/parcel_barn_adapter.py",
    "paired_sensor_faithful_harness": REPO_ROOT / "evals/external/barn_sensor_faithful.py",
    "comparison": REPO_ROOT / "evals/external/compare_barn.py",
    "compatibility": REPO_ROOT / "evals/external/compatibility.py",
    "evaluation_agents": REPO_ROOT / "evals/external/agents.py",
    "evaluation_episodes": REPO_ROOT / "evals/external/episodes.py",
    "evaluation_metrics": REPO_ROOT / "evals/external/metrics.py",
    "evaluation_runner": REPO_ROOT / "evals/external/runner.py",
    "run_barn": REPO_ROOT / "evals/external/run_barn.py",
    "policy_specs": REPO_ROOT / "evals/external/barn_policy_specs.py",
    "policy_sidecar": REPO_ROOT / "evals/external/barn_policy_sidecar.py",
    "policy_sidecar_worker": REPO_ROOT / "evals/external/barn_policy_sidecar_worker.py",
    "v8_policy_bundle": REPO_ROOT / "evals/external/barn_v8_policy_bundle.py",
    "v8_action_certifier": REPO_ROOT / "evals/external/barn_v8_action_certifier.py",
    "v8_action_evidence": REPO_ROOT / "evals/external/barn_v8_action_evidence.py",
    "v8_transaction": REPO_ROOT / "evals/external/barn_v8_transaction.py",
    "v8_promotion_gate": REPO_ROOT / "evals/external/barn_v8_promotion_gate.py",
    "v8_experiment_runner": REPO_ROOT / "evals/external/run_all_ray_shield_v8.py",
    "generator_engine_v5_generic_helpers_only": (
        REPO_ROOT / "evals/external/generate_safe_valley_v5_corpus.py"
    ),
    "v8_corpus_generator": Path(__file__),
    "v8_protocol": PROTOCOL_PATH,
    "ledger": REPO_ROOT / "evals/external/ledger.py",
}


class PartialV8CorpusMaterializationError(RuntimeError):
    """Raised when a single-use output namespace has already been consumed."""


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _pair_execution_schedule() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "arm_order": arm_order,
            "episode_seed": SUITE_SEED + world_id * 1_009,
            "trial": 0,
            "world_id": world_id,
        }
        for world_id, arm_order in zip(
            DEVELOPMENT_WORLD_IDS,
            PAIRED_ARM_ORDER_SCHEDULE,
            strict=True,
        )
    )


PAIR_EXECUTION_SCHEDULE = _pair_execution_schedule()
PAIRED_ARM_ORDER_SCHEDULE_SHA256 = _canonical_sha256(list(PAIRED_ARM_ORDER_SCHEDULE))
PAIR_EXECUTION_SCHEDULE_SHA256 = _canonical_sha256(list(PAIR_EXECUTION_SCHEDULE))


def _holdout_recipe() -> dict[str, Any]:
    return {
        "acceptance": (
            "first connected upstream BARN map; no policy execution; post-generation "
            "evaluator-private geometric targeting audit must pass"
        ),
        "generator_commit": GENERATOR_COMMIT,
        "parameter_algorithm": (
            "offset=world_id-4000; fill=(0.15,0.20,0.25,0.30)[(offset//3)%4]; "
            "smooth=(2,3,4)[offset%3]; rows=30; columns=30"
        ),
        "seed_algorithm": (
            "uint64_be(sha256(namespace + ':' + world_id + ':' + attempt)[0:8]) "
            "bitwise-and 0x7fffffff"
        ),
        "seed_namespace": SEED_NAMESPACE,
        "world_ids": list(OPERATIONAL_HOLDOUT_WORLD_IDS),
    }


HOLDOUT_RECIPE = _holdout_recipe()
HOLDOUT_RECIPE_COMMITMENT_SHA256 = _canonical_sha256(HOLDOUT_RECIPE)


def protocol_document() -> dict[str, Any]:
    """Return the checked-in, pre-execution V8 protocol declaration."""

    return {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "corpus_id": CORPUS_ID,
        "development_world_ids": list(DEVELOPMENT_WORLD_IDS),
        "forbidden_world_id_ranges_inclusive": [
            [lower, upper] for lower, upper in FORBIDDEN_WORLD_ID_RANGES
        ],
        "operational_holdout": {
            "assets_materialized": False,
            "cryptographically_sealed": False,
            "recipe": HOLDOUT_RECIPE,
            "recipe_commitment_sha256": HOLDOUT_RECIPE_COMMITMENT_SHA256,
        },
        "paired_protocol": {
            "episode_workers": EPISODE_WORKERS,
            "execution_schedule": list(PAIR_EXECUTION_SCHEDULE),
            "execution_schedule_sha256": PAIR_EXECUTION_SCHEDULE_SHA256,
            "order_schedule": list(PAIRED_ARM_ORDER_SCHEDULE),
            "order_schedule_sha256": PAIRED_ARM_ORDER_SCHEDULE_SHA256,
            "suite_seed": SUITE_SEED,
            "trials_per_world": TRIALS_PER_WORLD,
        },
        "promotion_gate": PROMOTION_GATE,
        "targeting_contract": {
            "assignment": {str(key): value for key, value in TARGET_ASSIGNMENTS.items()},
            "control_period_s": _PROBE_CONTROL_PERIOD_S,
            "forward_mps": _PROBE_FORWARD_MPS,
            "policy_executed_during_targeting": False,
            "reaction_horizon_s": _PROBE_REACTION_HORIZON_S,
            "strict_epsilon": _PROBE_STRICT_EPSILON,
            "yaw_rates_rps": [-_PROBE_YAW_RATE_RPS, _PROBE_YAW_RATE_RPS],
        },
    }


def _benchmark_scope_manifest() -> dict[str, Any]:
    return {
        "evaluation_kind": (
            "barn-calibrated-sensor-faithful-headless-generated-development-non-official"
        ),
        "official_gazebo_score": False,
        "leaderboard_claim": False,
        "policy_executed_during_corpus_targeting": False,
        "source_generator": GENERATOR_SOURCE,
        "source_generator_commit": GENERATOR_COMMIT,
    }


def _identity_partition_manifest() -> dict[str, Any]:
    return {
        **validate_identity_partition(),
        "development_world_ids": list(DEVELOPMENT_WORLD_IDS),
        "development_world_ids_sha256": _ids_sha256(DEVELOPMENT_WORLD_IDS),
        "forbidden_world_id_ranges_inclusive": [
            [lower, upper] for lower, upper in FORBIDDEN_WORLD_ID_RANGES
        ],
        "forbidden_world_ids_sha256": _ids_sha256(FORBIDDEN_WORLD_IDS),
        "operational_holdout_world_ids": list(OPERATIONAL_HOLDOUT_WORLD_IDS),
        "operational_holdout_world_ids_sha256": _ids_sha256(OPERATIONAL_HOLDOUT_WORLD_IDS),
    }


def _paired_protocol_manifest() -> dict[str, Any]:
    return {
        "arms_never_concurrent_within_pair": True,
        "episode_workers": EPISODE_WORKERS,
        "execution_schedule": list(PAIR_EXECUTION_SCHEDULE),
        "execution_schedule_sha256": PAIR_EXECUTION_SCHEDULE_SHA256,
        "one_trial_per_world": True,
        "order_schedule": list(PAIRED_ARM_ORDER_SCHEDULE),
        "order_schedule_sha256": PAIRED_ARM_ORDER_SCHEDULE_SHA256,
        "same_world_config_trial_and_seed_within_pair": True,
        "suite_seed": SUITE_SEED,
        "trials_per_world": TRIALS_PER_WORLD,
    }


def _holdout_manifest(assets_root: Path) -> dict[str, Any]:
    return {
        "assets_root": str(assets_root),
        "assets_root_absent_at_freeze": True,
        "cryptographically_sealed": False,
        "evaluated": False,
        "generated": False,
        "limitation": (
            "The deterministic recipe is visible in source and is therefore only an "
            "operational holdout. Materialization requires separate root authorization "
            "after every development gate passes."
        ),
        "opened": False,
        "recipe": HOLDOUT_RECIPE,
        "recipe_commitment_sha256": HOLDOUT_RECIPE_COMMITMENT_SHA256,
        "root_authorization_required": True,
    }


def _status_at_freeze_manifest() -> dict[str, Any]:
    return {
        "deployment_enabled": False,
        "development_assets_generated_and_hashed": True,
        "development_policy_execution_started": False,
        "holdout_generated": False,
        "holdout_opened": False,
        "holdout_run_id": None,
    }


def _verify_protocol_file() -> dict[str, Any]:
    if PROTOCOL_PATH.is_symlink() or not PROTOCOL_PATH.is_file():
        raise FileNotFoundError(f"V8 protocol declaration is missing or unsafe: {PROTOCOL_PATH}")
    try:
        observed = json.loads(PROTOCOL_PATH.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("V8 protocol declaration is not valid JSON") from exc
    expected = protocol_document()
    if observed != expected:
        raise ValueError("checked-in V8 protocol declaration differs from code constants")
    return {
        "path": PROTOCOL_PATH.relative_to(REPO_ROOT).as_posix(),
        "sha256": sha256_file(PROTOCOL_PATH),
        "semantic_sha256": _canonical_sha256(expected),
        "size_bytes": PROTOCOL_PATH.stat().st_size,
    }


def _seed(world_id: int, attempt: int) -> int:
    payload = f"{SEED_NAMESPACE}:{world_id}:{attempt}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & 0x7FFF_FFFF


def _parameters(world_id: int) -> tuple[float, int]:
    if world_id not in DEVELOPMENT_WORLD_IDS and world_id not in OPERATIONAL_HOLDOUT_WORLD_IDS:
        raise ValueError("V8 generator parameters are restricted to IDs 4000--4049")
    offset = world_id - DEVELOPMENT_WORLD_IDS[0]
    fill_percent = (0.15, 0.20, 0.25, 0.30)[(offset // 3) % 4]
    smooth_iterations = (2, 3, 4)[offset % 3]
    return fill_percent, smooth_iterations


def validate_identity_partition() -> dict[str, Any]:
    """Reject any namespace collision, including every retired V7 ID."""

    development = set(DEVELOPMENT_WORLD_IDS)
    holdout = set(OPERATIONAL_HOLDOUT_WORLD_IDS)
    forbidden = set(FORBIDDEN_WORLD_IDS)
    if len(development) != 30 or len(holdout) != 20:
        raise ValueError("V8 identity partition must contain exactly 30+20 IDs")
    if development & forbidden or holdout & forbidden or development & holdout:
        raise ValueError("V8 world IDs overlap prior evidence or the operational holdout")
    if DEVELOPMENT_WORLD_IDS != tuple(range(4000, 4030)):
        raise ValueError("V8 development identity range changed")
    if OPERATIONAL_HOLDOUT_WORLD_IDS != tuple(range(4030, 4050)):
        raise ValueError("V8 holdout identity range changed")
    return {
        "development_disjoint_from_forbidden": True,
        "development_disjoint_from_holdout": True,
        "holdout_disjoint_from_forbidden": True,
    }


def validate_frozen_schedule() -> tuple[dict[str, Any], ...]:
    """Validate the complete 30-pair schedule and both commitments."""

    validated = validate_paired_arm_order_schedule(
        PAIRED_ARM_ORDER_SCHEDULE,
        pair_count=len(DEVELOPMENT_WORLD_IDS),
    )
    if validated != PAIRED_ARM_ORDER_SCHEDULE:
        raise ValueError("paired runner changed the V8 order schedule")
    if PAIRED_ARM_ORDER_SCHEDULE.count(REFERENCE_THEN_CANDIDATE) != 15:
        raise ValueError("V8 schedule must contain 15 reference-first pairs")
    if PAIRED_ARM_ORDER_SCHEDULE.count(CANDIDATE_THEN_REFERENCE) != 15:
        raise ValueError("V8 schedule must contain 15 candidate-first pairs")
    if _canonical_sha256(list(PAIRED_ARM_ORDER_SCHEDULE)) != (
        PAIRED_ARM_ORDER_SCHEDULE_SHA256
    ):
        raise ValueError("V8 arm-order schedule commitment changed")
    schedule = _pair_execution_schedule()
    if schedule != PAIR_EXECUTION_SCHEDULE:
        raise ValueError("V8 execution schedule changed")
    if _canonical_sha256(list(schedule)) != PAIR_EXECUTION_SCHEDULE_SHA256:
        raise ValueError("V8 execution schedule commitment changed")
    return schedule


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _reject_symlink_ancestors(path: Path) -> None:
    candidate = _lexical_absolute(path)
    for ancestor in (candidate, *candidate.parents):
        if os.path.lexists(ancestor) and ancestor.is_symlink():
            raise ValueError(f"V8 output path contains a symbolic-link component: {ancestor}")


def _assert_output_namespace_pristine(
    *,
    assets_root: Path,
    manifest_path: Path,
    holdout_assets_root: Path,
) -> None:
    """Refuse complete, partial, aliased, or holdout-materialized namespaces."""

    assets = _lexical_absolute(assets_root)
    manifest = _lexical_absolute(manifest_path)
    holdout = _lexical_absolute(holdout_assets_root)
    for path in (assets, manifest, holdout):
        _reject_symlink_ancestors(path)
    if len({assets, manifest, holdout}) != 3:
        raise ValueError("V8 development, manifest, and holdout paths must be distinct")
    if assets in manifest.parents or manifest in assets.parents:
        raise ValueError("V8 assets and manifest may not contain one another")
    if holdout in assets.parents or assets in holdout.parents:
        raise ValueError("V8 development and holdout paths may not contain one another")
    if os.path.lexists(holdout):
        raise FileExistsError(
            f"operational V8 holdout assets already exist; refusing development: {holdout}"
        )
    assets_exist = os.path.lexists(assets)
    manifest_exists = os.path.lexists(manifest)
    if assets_exist != manifest_exists:
        raise PartialV8CorpusMaterializationError(
            "V8 output namespace is partially materialized and permanently consumed"
        )
    if assets_exist:
        raise FileExistsError("V8 development corpus and manifest already exist; refusing replay")


def _relative_repo_path(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def _strict_frozen_file(path: Path) -> dict[str, Any]:
    lexical = _lexical_absolute(path)
    _reject_symlink_ancestors(lexical)
    if lexical.is_symlink() or not lexical.is_file():
        raise FileNotFoundError(f"frozen V8 input is missing or unsafe: {lexical}")
    lexical.resolve().relative_to(REPO_ROOT.resolve())
    return {
        "path": _relative_repo_path(lexical),
        "sha256": sha256_file(lexical),
        "size_bytes": lexical.stat().st_size,
    }


def _strict_policy_source_tree(root: Path = PARCEL_POLICY_SOURCE_ROOT) -> dict[str, Any]:
    lexical = _lexical_absolute(root)
    _reject_symlink_ancestors(lexical)
    if lexical.is_symlink() or not lexical.is_dir():
        raise FileNotFoundError(f"production policy source tree is missing or unsafe: {lexical}")
    members: list[dict[str, Any]] = []
    for candidate in sorted(lexical.rglob("*.py")):
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError(f"production policy source member is unsafe: {candidate}")
        members.append(
            {
                "path": candidate.relative_to(lexical).as_posix(),
                "sha256": sha256_file(candidate),
                "size_bytes": candidate.stat().st_size,
            }
        )
    if not members:
        raise ValueError("production policy source tree contains no Python files")
    return {
        "path": _relative_repo_path(lexical),
        "file_count": len(members),
        "membership_and_content_sha256": _canonical_sha256(members),
    }


def _strict_generator_state(generator_root: Path) -> dict[str, Any]:
    _verify_generator(generator_root)
    dirty = subprocess.run(
        [
            "git",
            "-C",
            str(generator_root),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("BARN generator checkout contains tracked or untracked changes")
    inputs = _generator_inputs(generator_root)
    root = generator_root.resolve()
    for relative in inputs:
        candidate = generator_root / relative
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError(f"unsafe or missing BARN generator input: {candidate}")
        candidate.resolve().relative_to(root)
    return {
        "commit": GENERATOR_COMMIT,
        "inputs": inputs,
        "repository": GENERATOR_SOURCE,
        "root": str(generator_root.resolve()),
        "tracked_and_untracked_status_clean": True,
    }


def _execution_environment() -> dict[str, Any]:
    executable = Path(sys.executable).absolute()
    realpath = executable.resolve()
    if realpath.is_symlink() or not realpath.is_file():
        raise ValueError("Python interpreter identity is unsafe")
    return {
        "numpy_version": np.__version__,
        "python": {
            "binary_sha256": sha256_file(realpath),
            "byteorder": sys.byteorder,
            "executable": str(executable),
            "implementation": platform.python_implementation(),
            "realpath": str(realpath),
            "version": platform.python_version(),
        },
        "thread_environment": {
            name: os.environ.get(name)
            for name in (
                "MKL_NUM_THREADS",
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "PYTHONHASHSEED",
            )
        },
    }


def _frozen_generation_state(generator_root: Path) -> dict[str, Any]:
    calibrated = asdict(CalibratedBarnConfig())
    if calibrated != FROZEN_CALIBRATED_CONFIG:
        raise ValueError("calibrated paired BARN configuration changed before V8 freeze")
    return {
        "calibrated_config": calibrated,
        "evaluator_profile": FROZEN_V8_BARN_EVALUATOR_PROFILE.identity_payload(),
        "execution_environment": _execution_environment(),
        "generator": _strict_generator_state(generator_root),
        "production_policy_source_tree": _strict_policy_source_tree(),
        "protocol": _verify_protocol_file(),
        "source_files": {
            name: _strict_frozen_file(path) for name, path in sorted(SOURCE_FILES.items())
        },
    }


def _freeze_policy_pair(candidate: V8CandidateBundle) -> dict[str, Any]:
    reference_spec = parcel_isolated_bundle_reference_spec(
        candidate.reference.root,
        package_sha256=candidate.reference.package_sha256,
        manifest_sha256=candidate.reference.manifest_sha256,
        navigation_config_relative=HISTORICAL_CONFIG,
        reference_id="barn-v8-historical-reference",
        description="Byte-exact historical Parcel reference for the V8 paired experiment",
    )
    candidate_spec = parcel_isolated_bundle_candidate_spec(
        candidate.root,
        package_sha256=candidate.package_sha256,
        reference_package_sha256=candidate.reference.package_sha256,
        manifest_sha256=candidate.manifest_sha256,
        navigation_config_relative=HISTORICAL_CONFIG,
        experiment_id="barn-v8-all-ray-candidate",
        description="Deployment-disabled V8 all-ray yaw-swept candidate",
    )
    pair_metadata = validate_isolated_policy_pair(reference_spec, candidate_spec)
    reference_descriptor = reference_spec.process_descriptor
    candidate_descriptor = candidate_spec.process_descriptor
    if not isinstance(reference_descriptor, IsolatedPolicyDescriptor) or not isinstance(
        candidate_descriptor, IsolatedPolicyDescriptor
    ):
        raise TypeError("V8 isolated policy factories omitted their process descriptors")
    return {
        "candidate": {
            "bundle_root": str(candidate.root),
            "descriptor": candidate_descriptor.report_metadata(),
            "manifest_path": str(candidate.bundle.manifest_path),
        },
        "exact_allowlisted_delta": candidate.delta,
        "pair_contract": pair_metadata,
        "reference": {
            "bundle_root": str(candidate.reference.root),
            "descriptor": reference_descriptor.report_metadata(),
            "manifest_path": str(candidate.reference.manifest_path),
        },
        "validated_isolated_pair": True,
    }


def _float32(value: float) -> float:
    return float(np.float32(value))


def _normalized_probe_scan(
    world: BarnWorld,
    *,
    position_xy: tuple[float, float],
    heading_rad: float,
) -> tuple[tuple[float, ...], float, float]:
    config = CalibratedBarnConfig()
    raw = tuple(
        _float32(value)
        for value in cast_sensor_faithful_lidar(
            position_xy,
            heading_rad,
            world.cylinders,
            config=config,
        )
    )
    angle_min = _float32(config.lidar_angle_min_rad)
    angle_increment = _float32(
        (config.lidar_angle_max_rad - config.lidar_angle_min_rad)
        / (config.lidar_ray_count - 1)
    )
    normalized = normalize_planar_lidar_frame(
        BarnRos2SensorFrame(
            stamp_s=1.0,
            position_xy=(0.0, 0.0),
            heading_rad=0.0,
            lidar_ranges_m=raw,
            lidar_angle_min_rad=angle_min,
            lidar_angle_increment_rad=angle_increment,
            lidar_range_min_m=_float32(config.lidar_range_min_m),
            lidar_range_max_m=_float32(config.lidar_range_max_m),
            odometry_stamp_s=1.0 - config.odometry_lag_s,
            lidar_frame_id=BARN_ROS2_LIDAR_FRAME_ID,
            odometry_child_frame_id=BARN_ROS2_BASE_FRAME_ID,
        ),
        BARN_ROS2_LIDAR_CALIBRATION,
    )
    return normalized.ranges_m, normalized.angle_min_rad, normalized.angle_increment_rad


def _maximum_swept_closing_speed(bearing_rad: float, yaw_rate_rps: float) -> float:
    start = 0.0
    end = yaw_rate_rps * _PROBE_REACTION_HORIZON_S
    lower, upper = sorted((start, end))
    first_alignment = bearing_rad + math.ceil((lower - bearing_rad) / (2.0 * math.pi)) * (
        2.0 * math.pi
    )
    if first_alignment <= upper + 1e-15:
        return _PROBE_FORWARD_MPS
    return _PROBE_FORWARD_MPS * max(
        0.0,
        math.cos(start - bearing_rad),
        math.cos(end - bearing_rad),
    )


def _classify_normalized_probe(
    ranges_m: Sequence[float],
    *,
    angle_min_rad: float,
    angle_increment_rad: float,
    waypoint_index: int,
    position_xy: tuple[float, float],
    heading_rad: float,
) -> dict[str, dict[str, Any] | None]:
    finite = [
        (float(distance), index)
        for index, distance in enumerate(ranges_m)
        if math.isfinite(float(distance))
    ]
    if not finite:
        return {_TARGET_GLOBAL_NEAREST: None, _TARGET_ROTATION_LIMITED: None}
    nearest_range, nearest_index = min(finite)
    zero_yaw = certify_v8_published_barn_action(
        _PROBE_FORWARD_MPS,
        0.0,
        ranges_m,
        angle_min_rad=angle_min_rad,
        angle_increment_rad=angle_increment_rad,
        control_period_s=_PROBE_CONTROL_PERIOD_S,
    )
    global_witness: dict[str, Any] | None = None
    rotation_witness: dict[str, Any] | None = None
    for yaw_rate in (-_PROBE_YAW_RATE_RPS, _PROBE_YAW_RATE_RPS):
        swept = certify_v8_published_barn_action(
            _PROBE_FORWARD_MPS,
            yaw_rate,
            ranges_m,
            angle_min_rad=angle_min_rad,
            angle_increment_rad=angle_increment_rad,
            control_period_s=_PROBE_CONTROL_PERIOD_S,
        )
        limiting_index = swept.limiting_ray_index
        if limiting_index is None or swept.limiting_range_m is None:
            continue
        nearest_bearing = angle_min_rad + nearest_index * angle_increment_rad
        nearest_closing = _maximum_swept_closing_speed(nearest_bearing, yaw_rate)
        common = {
            "angle_increment_rad": angle_increment_rad,
            "angle_min_rad": angle_min_rad,
            "heading_rad": heading_rad,
            "limiting_bearing_rad": swept.limiting_bearing_rad,
            "limiting_range_m": swept.limiting_range_m,
            "limiting_ray_index": limiting_index,
            "minimum_projected_margin_m": swept.minimum_projected_margin_m,
            "position_xy": list(position_xy),
            "probe_forward_mps": _PROBE_FORWARD_MPS,
            "probe_yaw_rate_rps": yaw_rate,
            "scan_sha256": swept.scan_sha256,
            "waypoint_index": waypoint_index,
        }
        if (
            global_witness is None
            and limiting_index != nearest_index
            and swept.limiting_range_m > nearest_range + _PROBE_STRICT_EPSILON
            and nearest_closing <= FROZEN_V8_BARN_EVALUATOR_PROFILE.closing_epsilon_mps
        ):
            global_witness = {
                **common,
                "nearest_maximum_closing_speed_mps": nearest_closing,
                "nearest_range_m": nearest_range,
                "nearest_ray_index": nearest_index,
                "strictly_farther_limiting_return": True,
            }

        if (
            rotation_witness is None
            and swept.minimum_projected_margin_m is not None
            and zero_yaw.minimum_projected_margin_m is not None
            and swept.limiting_bearing_rad is not None
        ):
            translation_closing = _maximum_swept_closing_speed(
                swept.limiting_bearing_rad,
                0.0,
            )
            swept_closing = _maximum_swept_closing_speed(
                swept.limiting_bearing_rad,
                yaw_rate,
            )
            if (
                swept_closing > translation_closing + _PROBE_STRICT_EPSILON
                and swept.minimum_projected_margin_m
                < zero_yaw.minimum_projected_margin_m - _PROBE_STRICT_EPSILON
            ):
                rotation_witness = {
                    **common,
                    "limiting_closing_speed_without_yaw_mps": translation_closing,
                    "limiting_closing_speed_with_yaw_mps": swept_closing,
                    "zero_yaw_limiting_ray_index": zero_yaw.limiting_ray_index,
                    "zero_yaw_minimum_projected_margin_m": (
                        zero_yaw.minimum_projected_margin_m
                    ),
                    "yaw_sweep_strictly_tightens_limit": True,
                }
    return {
        _TARGET_GLOBAL_NEAREST: global_witness,
        _TARGET_ROTATION_LIMITED: rotation_witness,
    }


def analyze_world_v8_targeting(world: BarnWorld) -> dict[str, Any]:
    """Find deterministic evaluator-private target witnesses on a BARN path."""

    witnesses: dict[str, dict[str, Any] | None] = {
        _TARGET_GLOBAL_NEAREST: None,
        _TARGET_ROTATION_LIMITED: None,
    }
    path = world.reference_path_world
    for waypoint_index in range(1, len(path) - 1):
        previous, current = path[waypoint_index - 1], path[waypoint_index]
        following = path[waypoint_index + 1]
        if current == previous or following == current:
            continue
        heading = math.atan2(current[1] - previous[1], current[0] - previous[0])
        ranges, angle_min, angle_increment = _normalized_probe_scan(
            world,
            position_xy=current,
            heading_rad=heading,
        )
        probe = _classify_normalized_probe(
            ranges,
            angle_min_rad=angle_min,
            angle_increment_rad=angle_increment,
            waypoint_index=waypoint_index,
            position_xy=current,
            heading_rad=heading,
        )
        for name, witness in witnesses.items():
            if witness is None and probe[name] is not None:
                witnesses[name] = probe[name]
        if all(value is not None for value in witnesses.values()):
            break
    return {
        "global_nearest_not_limiting": witnesses[_TARGET_GLOBAL_NEAREST],
        "policy_executed": False,
        "probe_profile_id": FROZEN_V8_BARN_EVALUATOR_PROFILE.profile_id,
        "yaw_sweep_rotation_limited": witnesses[_TARGET_ROTATION_LIMITED],
    }


def _validate_target_assignments(
    analyses: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    if set(analyses) != set(DEVELOPMENT_WORLD_IDS):
        raise ValueError("V8 targeting analyses do not cover the exact development split")
    counts = {_TARGET_GLOBAL_NEAREST: 0, _TARGET_ROTATION_LIMITED: 0}
    for world_id in DEVELOPMENT_WORLD_IDS:
        analysis = analyses[world_id]
        if analysis.get("policy_executed") is not False:
            raise ValueError("V8 corpus targeting must never execute a robot policy")
        for target in counts:
            if analysis.get(target) is not None:
                counts[target] += 1
        assigned = TARGET_ASSIGNMENTS[world_id]
        if analysis.get(assigned) is None:
            raise ValueError(f"V8 world {world_id} lacks its assigned {assigned} witness")
    if min(counts.values()) < 15:
        raise ValueError("V8 corpus does not contain enough examples of both target geometries")
    return {
        "assignment_satisfied_for_every_world": True,
        "global_nearest_not_limiting_world_count": counts[_TARGET_GLOBAL_NEAREST],
        "policy_executed_during_targeting": False,
        "yaw_sweep_rotation_limited_world_count": counts[_TARGET_ROTATION_LIMITED],
    }


def validate_generated_development_corpus(
    episodes: Sequence[Mapping[str, Any]],
    assets_root: Path,
) -> dict[str, Any]:
    """Validate exact BARN assets, recipes, inventory, and V8 target witnesses."""

    if len(episodes) != len(DEVELOPMENT_WORLD_IDS):
        raise ValueError("V8 generated corpus must contain exactly 30 worlds")
    if assets_root.is_symlink() or not assets_root.is_dir():
        raise ValueError("V8 generated assets root must be a real directory")
    expected_inventory = {Path("generation.log")}
    seeds: list[int] = []
    analyses: dict[int, dict[str, Any]] = {}
    for expected_world_id, episode in zip(DEVELOPMENT_WORLD_IDS, episodes, strict=True):
        if not isinstance(episode, Mapping):
            raise TypeError("V8 generated episode metadata must be an object")
        world_id = episode.get("world_id")
        attempt = episode.get("accepted_attempt")
        seed = episode.get("generator_seed")
        if (
            isinstance(world_id, bool)
            or not isinstance(world_id, int)
            or world_id != expected_world_id
            or isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or not 1 <= attempt <= 10_000
            or isinstance(seed, bool)
            or not isinstance(seed, int)
            or seed != _seed(world_id, attempt)
        ):
            raise ValueError(f"invalid V8 generation recipe for world {expected_world_id}")
        fill_percent, smooth_iterations = _parameters(world_id)
        if (
            episode.get("corpus_episode_id") != f"{CORPUS_ID}/development/{world_id}"
            or episode.get("fill_percent") != fill_percent
            or episode.get("smooth_iterations") != smooth_iterations
            or episode.get("rows") != 30
            or episode.get("columns") != 30
            or episode.get("assigned_target") != TARGET_ASSIGNMENTS[world_id]
        ):
            raise ValueError(f"invalid V8 episode parameters for world {world_id}")
        seeds.append(seed)
        files = episode.get("files")
        if not isinstance(files, Mapping) or set(files) != {
            "world",
            "path",
            "grid",
            "cspace",
            "metrics",
        }:
            raise ValueError(f"invalid V8 file manifest for world {world_id}")
        expected_relatives = {
            "world": Path("world_files") / f"world_{world_id}.world",
            "path": Path("path_files") / f"path_{world_id}.npy",
            "grid": Path("grid_files") / f"grid_{world_id}.npy",
            "cspace": Path("cspace_files") / f"cspace_{world_id}.npy",
            "metrics": Path("metrics_files") / f"metrics_{world_id}.npy",
        }
        paths: dict[str, Path] = {}
        for kind, relative in expected_relatives.items():
            record = files[kind]
            if not isinstance(record, Mapping) or record.get("path") != relative.as_posix():
                raise ValueError(f"invalid V8 {kind} path for world {world_id}")
            path = assets_root / relative
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"unsafe or missing V8 {kind} for world {world_id}")
            if (
                record.get("sha256") != sha256_file(path)
                or isinstance(record.get("size_bytes"), bool)
                or record.get("size_bytes") != path.stat().st_size
            ):
                raise ValueError(f"V8 {kind} identity changed for world {world_id}")
            expected_inventory.add(relative)
            paths[kind] = path
        ET.parse(paths["world"])
        grid = np.load(paths["grid"], allow_pickle=False)
        cspace = np.load(paths["cspace"], allow_pickle=False)
        path_array = np.load(paths["path"], allow_pickle=False)
        metrics = np.load(paths["metrics"], allow_pickle=False)
        if grid.shape != (30, 30) or cspace.shape != (30, 30):
            raise ValueError(f"V8 world {world_id} does not use a 30x30 BARN grid")
        if path_array.ndim != 2 or path_array.shape[0] < 2 or path_array.shape[1] != 2:
            raise ValueError(f"V8 world {world_id} has an invalid reference path")
        if metrics.shape != (5,) or not np.isfinite(metrics).all():
            raise ValueError(f"V8 world {world_id} has invalid difficulty metrics")
        analysis = analyze_world_v8_targeting(
            load_generated_barn_world(assets_root, world_id)
        )
        if analysis != episode.get("targeting_analysis"):
            raise ValueError(f"V8 targeting witness changed for world {world_id}")
        analyses[world_id] = analysis

    if len(seeds) != len(set(seeds)):
        raise ValueError("V8 generator seeds must be unique")
    actual_inventory = {
        path.relative_to(assets_root) for path in assets_root.rglob("*") if path.is_file()
    }
    if actual_inventory != expected_inventory:
        raise ValueError("V8 generated asset inventory contains missing or unexpected files")
    if any(path.is_symlink() for path in assets_root.rglob("*")):
        raise ValueError("V8 generated asset tree must not contain symbolic links")
    target_summary = _validate_target_assignments(analyses)
    return {
        "arrays_loaded_without_pickle": True,
        "columns": 30,
        "exact_file_inventory": True,
        "rows": 30,
        "targeting": target_summary,
        "targeting_analyses": {str(key): value for key, value in analyses.items()},
        "unique_generator_seeds": True,
        "world_count": len(episodes),
    }


def _write_exclusive_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_ancestors(path.parent)
    encoded = json.dumps(
        payload,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o444)
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise FileExistsError(f"refusing to replace frozen V8 manifest: {path}") from exc
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _commit_staged_assets(staged_assets: Path, assets_root: Path) -> None:
    """Claim the destination without replacement, then publish staged children.

    The exclusive directory creation is the consumption point.  Publication
    happens while that directory is owner-only, so a concurrent process cannot
    inject a destination child that ``rename`` could replace.  Any interruption
    leaves a partial directory, which preflight permanently refuses.
    """

    if staged_assets.is_symlink() or not staged_assets.is_dir():
        raise ValueError("staged V8 assets root is missing or unsafe")
    assets_root.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_ancestors(assets_root.parent)
    try:
        assets_root.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError as exc:
        raise FileExistsError(f"refusing to replace V8 assets: {assets_root}") from exc
    for child in sorted(staged_assets.iterdir(), key=lambda value: value.name):
        if child.is_symlink():
            raise ValueError(f"staged V8 assets contain a symbolic link: {child}")
        os.rename(child, assets_root / child.name)
    for path in sorted(assets_root.rglob("*"), reverse=True):
        if path.is_symlink():
            raise ValueError(f"published V8 assets contain a symbolic link: {path}")
        path.chmod(0o555 if path.is_dir() else 0o444)
    assets_root.chmod(0o555)
    directory_fd = os.open(assets_root.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _target_analysis_satisfies(world_id: int, analysis: Mapping[str, Any]) -> bool:
    if world_id not in TARGET_ASSIGNMENTS:
        raise ValueError("target acceptance is restricted to V8 development IDs")
    if analysis.get("policy_executed") is not False:
        raise ValueError("V8 target acceptance may not execute a robot policy")
    return analysis.get(TARGET_ASSIGNMENTS[world_id]) is not None


def _known_upstream_disconnected_index_error(exc: IndexError) -> bool:
    traceback = exc.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code.co_name == "regions_connected":
            return True
        traceback = traceback.tb_next
    return False


def _generate_one_targeted_world(
    *,
    generator: Any,
    assets_root: Path,
    world_id: int,
    log: io.StringIO,
    maximum_attempts: int = 10_000,
    world_loader: Callable[[Path, int], BarnWorld] = load_generated_barn_world,
    analyzer: Callable[[BarnWorld], Mapping[str, Any]] = analyze_world_v8_targeting,
) -> tuple[int, int, dict[str, Any]]:
    """Accept the first connected map that satisfies its frozen V8 target.

    Seeds are a pure function of ``(namespace, world_id, attempt)``.  Rejected
    connected worlds are overwritten only inside the private staging tree.
    Neither reference nor candidate policy is constructed here.
    """

    if isinstance(maximum_attempts, bool) or not isinstance(maximum_attempts, int):
        raise TypeError("maximum_attempts must be an integer")
    if maximum_attempts < 1 or maximum_attempts > 10_000:
        raise ValueError("maximum_attempts must be in [1, 10000]")
    fill_percent, smooth_iterations = _parameters(world_id)
    for attempt in range(1, maximum_attempts + 1):
        seed = _seed(world_id, attempt)
        try:
            with contextlib.redirect_stdout(log):
                generated = generator.main(
                    iteration=world_id,
                    seed=seed,
                    smooth_iter=smooth_iterations,
                    fill_pct=fill_percent,
                    rows=30,
                    cols=30,
                    show_metrics=0,
                )
        except IndexError as exc:
            if not _known_upstream_disconnected_index_error(exc):
                raise
            log.write(
                f"rejected world={world_id} seed={seed} attempt={attempt} "
                "reason=missing_side_region\n"
            )
            continue
        if not generated:
            log.write(
                f"rejected world={world_id} seed={seed} attempt={attempt} "
                "reason=disconnected\n"
            )
            continue
        analysis = dict(analyzer(world_loader(assets_root, world_id)))
        if _target_analysis_satisfies(world_id, analysis):
            log.write(
                f"accepted world={world_id} seed={seed} attempt={attempt} "
                f"fill={fill_percent:.2f} smooth={smooth_iterations} "
                f"target={TARGET_ASSIGNMENTS[world_id]}\n"
            )
            return seed, attempt, analysis
        log.write(
            f"rejected world={world_id} seed={seed} attempt={attempt} "
            f"reason=missing_{TARGET_ASSIGNMENTS[world_id]}\n"
        )
    raise RuntimeError(
        f"upstream generator found no connected target-bearing V8 world for ID {world_id}"
    )


def _episode_file_inventory(assets_root: Path, world_id: int) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for kind, relative in (
        ("world", Path("world_files") / f"world_{world_id}.world"),
        ("path", Path("path_files") / f"path_{world_id}.npy"),
        ("grid", Path("grid_files") / f"grid_{world_id}.npy"),
        ("cspace", Path("cspace_files") / f"cspace_{world_id}.npy"),
        ("metrics", Path("metrics_files") / f"metrics_{world_id}.npy"),
    ):
        path = assets_root / relative
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"upstream generator omitted or aliased {path}")
        files[kind] = {
            "path": relative.as_posix(),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    return files


def _generate_staged_assets(
    *,
    generator_root: Path,
    assets_parent: Path,
) -> tuple[Path, list[dict[str, Any]], str, Path]:
    staging_parent = Path(tempfile.mkdtemp(prefix=".barn-all-ray-v8-stage-", dir=assets_parent))
    staged_assets = staging_parent / "test_data"
    try:
        staged_assets.mkdir()
        _asset_directories(staged_assets)
        generator = _load_upstream_generator(generator_root)
        log = io.StringIO()
        accepted: dict[int, tuple[int, int, dict[str, Any]]] = {}
        original_cwd = Path.cwd()
        try:
            os.chdir(staging_parent)
            for world_id in DEVELOPMENT_WORLD_IDS:
                accepted[world_id] = _generate_one_targeted_world(
                    generator=generator,
                    assets_root=staged_assets,
                    world_id=world_id,
                    log=log,
                )
        finally:
            os.chdir(original_cwd)
        generation_log = staged_assets / "generation.log"
        generation_log.write_text(log.getvalue(), encoding="utf-8")
        episodes: list[dict[str, Any]] = []
        for world_id in DEVELOPMENT_WORLD_IDS:
            seed, attempt, analysis = accepted[world_id]
            fill_percent, smooth_iterations = _parameters(world_id)
            episodes.append(
                {
                    "accepted_attempt": attempt,
                    "assigned_target": TARGET_ASSIGNMENTS[world_id],
                    "columns": 30,
                    "corpus_episode_id": f"{CORPUS_ID}/development/{world_id}",
                    "files": _episode_file_inventory(staged_assets, world_id),
                    "fill_percent": fill_percent,
                    "generator_seed": seed,
                    "rows": 30,
                    "smooth_iterations": smooth_iterations,
                    "targeting_analysis": analysis,
                    "world_id": world_id,
                }
            )
        log_sha256 = sha256_file(generation_log)
    except BaseException:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise
    return staged_assets, episodes, log_sha256, staging_parent


def _verify_policy_identity(policy_identity: Mapping[str, Any]) -> None:
    reference = policy_identity.get("reference")
    candidate = policy_identity.get("candidate")
    delta = policy_identity.get("exact_allowlisted_delta")
    if not isinstance(reference, Mapping) or not isinstance(candidate, Mapping):
        raise TypeError("V8 manifest policy-pair identity is malformed")
    reference_descriptor = reference.get("descriptor")
    candidate_descriptor = candidate.get("descriptor")
    if not isinstance(reference_descriptor, Mapping) or not isinstance(
        candidate_descriptor, Mapping
    ):
        raise TypeError("V8 policy descriptors are malformed")
    verified_reference = verify_policy_bundle(
        str(reference["bundle_root"]),
        expected_package_sha256=str(reference_descriptor["package_sha256"]),
        expected_manifest_sha256=str(reference_descriptor["manifest_sha256"]),
    )
    verified_candidate = verify_policy_bundle(
        str(candidate["bundle_root"]),
        expected_package_sha256=str(candidate_descriptor["package_sha256"]),
        expected_manifest_sha256=str(candidate_descriptor["manifest_sha256"]),
    )
    if not isinstance(delta, Mapping):
        raise TypeError("V8 candidate delta identity is malformed")
    reviewed = delta.get("reviewed_sources")
    if not isinstance(reviewed, Mapping):
        raise TypeError("V8 reviewed-source identity is malformed")
    verify_v8_candidate_delta(
        verified_candidate,
        verified_reference,
        repo_root=None,
        expected_reviewed_sources=reviewed,
    )


def generate_corpus(
    *,
    generator_root: Path = DEFAULT_GENERATOR_ROOT,
    assets_root: Path = DEFAULT_ASSETS_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
    holdout_assets_root: Path = DEFAULT_HOLDOUT_ASSETS_ROOT,
) -> dict[str, Any]:
    """Generate and freeze development only; never materialize the holdout."""

    generator_root = _lexical_absolute(generator_root)
    assets_root = _lexical_absolute(assets_root)
    manifest_path = _lexical_absolute(manifest_path)
    holdout_assets_root = _lexical_absolute(holdout_assets_root)
    _assert_output_namespace_pristine(
        assets_root=assets_root,
        manifest_path=manifest_path,
        holdout_assets_root=holdout_assets_root,
    )
    validate_identity_partition()
    validate_frozen_schedule()
    if _canonical_sha256(HOLDOUT_RECIPE) != HOLDOUT_RECIPE_COMMITMENT_SHA256:
        raise ValueError("operational holdout recipe commitment changed")

    pre_generation_state = _frozen_generation_state(generator_root)
    candidate_bundle = prepare_v8_candidate_bundle()
    policy_identity = _freeze_policy_pair(candidate_bundle)
    assets_root.parent.mkdir(parents=True, exist_ok=True)
    staged_assets, episodes, generation_log_sha256, staging_parent = _generate_staged_assets(
        generator_root=generator_root,
        assets_parent=assets_root.parent,
    )
    try:
        validation = validate_generated_development_corpus(episodes, staged_assets)
        post_generation_state = _frozen_generation_state(generator_root)
        if post_generation_state != pre_generation_state:
            raise ValueError(
                "a frozen V8 source, runtime, calibration, protocol, or generator input "
                "changed during staging"
            )
        post_policy_identity = _freeze_policy_pair(candidate_bundle)
        if post_policy_identity != policy_identity:
            raise ValueError("the exact V8 reference/candidate policy pair changed during staging")
        _verify_policy_identity(policy_identity)
        state_sha256 = _canonical_sha256(pre_generation_state)
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "manifest_id": MANIFEST_ID,
            "corpus_id": CORPUS_ID,
            "created_at": created_at,
            "purpose": (
                "Single-use, paired, calibrated-sensor BARN proxy development corpus for "
                "the deployment-disabled V8 all-ray yaw-swept projected-speed shield"
            ),
            "benchmark_scope": _benchmark_scope_manifest(),
            "identity_partition": _identity_partition_manifest(),
            "development_corpus": {
                "assets_root": str(assets_root),
                "corpus_sha256": _corpus_sha256(episodes),
                "episodes": episodes,
                "generation_log_sha256": generation_log_sha256,
                "independent_validation": validation,
                "world_count": len(episodes),
            },
            "operational_holdout_recipe": _holdout_manifest(holdout_assets_root),
            "paired_protocol_frozen_before_execution": _paired_protocol_manifest(),
            "policy_pair_identity": policy_identity,
            "frozen_generation_state": {
                "content": pre_generation_state,
                "post_generation_sha256": _canonical_sha256(post_generation_state),
                "pre_and_post_identical": True,
                "pre_generation_sha256": state_sha256,
            },
            "promotion_gate_frozen_before_development": PROMOTION_GATE,
            "status_at_freeze": _status_at_freeze_manifest(),
        }
        _commit_staged_assets(staged_assets, assets_root)
        _write_exclusive_manifest(manifest_path, manifest)
        return manifest
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def verify_frozen_corpus(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Revalidate a completed corpus and reject any identity/source drift."""

    manifest_path = _lexical_absolute(manifest_path)
    _reject_symlink_ancestors(manifest_path)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise FileNotFoundError(f"frozen V8 manifest is missing or unsafe: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("frozen V8 manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise TypeError("frozen V8 manifest must contain an object")
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("manifest_id") != MANIFEST_ID
        or manifest.get("corpus_id") != CORPUS_ID
    ):
        raise ValueError("frozen V8 manifest identity changed")
    if manifest.get("benchmark_scope") != _benchmark_scope_manifest():
        raise ValueError("frozen V8 non-official benchmark scope changed")
    if manifest.get("promotion_gate_frozen_before_development") != PROMOTION_GATE:
        raise ValueError("frozen V8 promotion gate changed")
    if manifest.get("status_at_freeze") != _status_at_freeze_manifest():
        raise ValueError("frozen V8 pre-execution status changed")
    validate_identity_partition()
    if manifest.get("identity_partition") != _identity_partition_manifest():
        raise ValueError("frozen V8 world identity partition changed")
    schedule = validate_frozen_schedule()
    protocol = manifest.get("paired_protocol_frozen_before_execution")
    if protocol != _paired_protocol_manifest() or protocol.get("execution_schedule") != list(
        schedule
    ):
        raise ValueError("frozen V8 paired schedule changed")
    holdout = manifest.get("operational_holdout_recipe")
    if not isinstance(holdout, Mapping):
        raise TypeError("frozen V8 holdout declaration is malformed")
    holdout_root = _lexical_absolute(Path(str(holdout.get("assets_root"))))
    if holdout != _holdout_manifest(holdout_root):
        raise ValueError("frozen V8 holdout commitment changed")
    if os.path.lexists(holdout_root):
        raise ValueError("operational V8 holdout was materialized")
    development = manifest.get("development_corpus")
    if not isinstance(development, Mapping) or not isinstance(development.get("episodes"), list):
        raise TypeError("frozen V8 development corpus metadata is malformed")
    assets_root = _lexical_absolute(Path(str(development["assets_root"])))
    validation = validate_generated_development_corpus(development["episodes"], assets_root)
    if validation != development.get("independent_validation"):
        raise ValueError("frozen V8 independent validation evidence changed")
    if _corpus_sha256(development["episodes"]) != development.get("corpus_sha256"):
        raise ValueError("frozen V8 corpus identity changed")
    state = manifest.get("frozen_generation_state")
    if not isinstance(state, Mapping) or not isinstance(state.get("content"), Mapping):
        raise TypeError("frozen V8 generation-state identity is malformed")
    frozen_state = dict(state["content"])
    generator_state = frozen_state.get("generator")
    if not isinstance(generator_state, Mapping):
        raise TypeError("frozen V8 generator identity is malformed")
    generator_root = Path(str(generator_state.get("root")))
    current_state = _frozen_generation_state(generator_root)
    if current_state != frozen_state:
        raise ValueError("frozen V8 source or runtime identity changed")
    if _canonical_sha256(frozen_state) != state.get("pre_generation_sha256"):
        raise ValueError("frozen V8 generation-state commitment changed")
    policy_identity = manifest.get("policy_pair_identity")
    if not isinstance(policy_identity, Mapping):
        raise TypeError("frozen V8 policy identity is malformed")
    _verify_policy_identity(policy_identity)
    return {
        "corpus_id": CORPUS_ID,
        "corpus_sha256": development["corpus_sha256"],
        "holdout_absent": True,
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "policy_pair_verified": True,
        "world_count": len(development["episodes"]),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generator-root", type=Path, default=DEFAULT_GENERATOR_ROOT)
    parser.add_argument("--assets-root", type=Path, default=DEFAULT_ASSETS_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--authorize-development-freeze",
        action="store_true",
        help="required single-use acknowledgement; this still cannot generate holdout assets",
    )
    args = parser.parse_args(argv)
    if not args.authorize_development_freeze:
        parser.error("--authorize-development-freeze is required")
    manifest = generate_corpus(
        generator_root=args.generator_root,
        assets_root=args.assets_root,
        manifest_path=args.manifest,
    )
    print(
        json.dumps(
            {
                "corpus_id": manifest["corpus_id"],
                "development_corpus_sha256": manifest["development_corpus"]["corpus_sha256"],
                "development_world_count": manifest["development_corpus"]["world_count"],
                "holdout_generated": False,
                "manifest": str(args.manifest.resolve()),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "CORPUS_ID",
    "DEFAULT_ASSETS_ROOT",
    "DEFAULT_GENERATOR_ROOT",
    "DEFAULT_HOLDOUT_ASSETS_ROOT",
    "DEFAULT_MANIFEST",
    "DEVELOPMENT_WORLD_IDS",
    "EPISODE_WORKERS",
    "FORBIDDEN_WORLD_IDS",
    "FORBIDDEN_WORLD_ID_RANGES",
    "HOLDOUT_RECIPE",
    "HOLDOUT_RECIPE_COMMITMENT_SHA256",
    "MANIFEST_ID",
    "OPERATIONAL_HOLDOUT_WORLD_IDS",
    "PAIRED_ARM_ORDER_SCHEDULE",
    "PAIRED_ARM_ORDER_SCHEDULE_SHA256",
    "PAIR_EXECUTION_SCHEDULE",
    "PAIR_EXECUTION_SCHEDULE_SHA256",
    "PROMOTION_GATE",
    "PROTOCOL_ID",
    "SCHEMA_VERSION",
    "SEALED_CONFIRMATION_WORLD_IDS",
    "SUITE_SEED",
    "TARGET_ASSIGNMENTS",
    "TRIALS_PER_WORLD",
    "PartialV8CorpusMaterializationError",
    "analyze_world_v8_targeting",
    "generate_corpus",
    "protocol_document",
    "validate_frozen_schedule",
    "validate_generated_development_corpus",
    "validate_identity_partition",
    "verify_frozen_corpus",
]
