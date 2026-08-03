"""Run the frozen calibrated-sensor predictive-shield v7 development gate.

There is intentionally no confirmation mode.  This runner verifies every
frozen input, executes the exact historical 0.8 m full-stop reference, verifies
the inputs again, executes the one-factor projected-speed-cap challenger, and
then verifies the inputs a third time before writing immutable evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

from .barn_native import (
    BARN_EVALUATOR_COMMIT,
    OFFICIAL_GOAL_XY,
    OFFICIAL_REFERENCE_SPEED_MPS,
    barn_navigation_metric,
    load_generated_barn_world,
)
from .barn_policy_specs import PARCEL_POLICY_SOURCE_ROOT, REPO_ROOT, _source_tree_sha256
from .compare_barn import compare_barn_reports
from .generate_predictive_shield_v7_corpus import (
    CHALLENGER_CONFIG,
    CORPUS_ID,
    DEFAULT_CONFIRMATION_ASSETS_ROOT,
    DEFAULT_MANIFEST,
    DEVELOPMENT_WORLD_IDS,
    FORBIDDEN_WORLD_IDS,
    GRID_MODEL,
    HARNESS_FILES,
    PROMOTION_GATE,
    PROTECTED_PRODUCTION_FILES,
    REFERENCE_CONFIG,
    SEALED_CONFIRMATION_WORLD_IDS,
    SEED_NAMESPACE,
    SOURCE_ROLES,
    _frozen_generation_state,
    _state_sha256,
    _strict_generator_state,
    execution_environment_preflight,
    historical_reference_preflight,
    policy_runtime_dependencies_preflight,
    runtime_calibration_preflight,
    validate_generated_development_corpus,
    verify_one_factor_configs,
)
from .generate_safe_valley_v5_corpus import (
    GENERATOR_COMMIT,
    GENERATOR_SOURCE,
    _corpus_sha256,
    _generator_inputs,
    _ids_sha256,
)
from .ledger import record_evaluation_run, sha256_file
from .predictive_shield_v7_retirement import refuse_v7_execution

EVALUATION_KIND = "barn-calibrated-sensor-predictive-shield-v7-generated-development-non-official"
COMPARISON_KIND = "barn-calibrated-sensor-paired-comparison-headless-non-official"
SENSOR_FAITHFUL_EVALUATION_KIND = (
    "barn-calibrated-sensor-faithful-native-headless-non-official"
)
BARN_SOURCE = "https://github.com/Daffan/the-barn-challenge"
BARN_SOURCE_COMMIT = BARN_EVALUATOR_COMMIT
DEFAULT_RESULTS_ROOT = DEFAULT_MANIFEST.parent / "results"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_OWNERSHIP_NONCE = re.compile(r"^[0-9a-f]{32}$")
_TERMINAL_OUTCOME_SCHEMA_VERSION = 1


def _require_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a JSON object")
    return value


def _verify_file(root: Path, record: Mapping[str, Any], name: str) -> Path:
    raw_path = record.get("path")
    digest = record.get("sha256")
    size = record.get("size_bytes")
    if not isinstance(raw_path, str) or not isinstance(digest, str):
        raise TypeError(f"{name} has invalid path/hash provenance")
    root = root.expanduser().resolve()
    unresolved = Path(raw_path)
    if not unresolved.is_absolute():
        unresolved = root / unresolved
    if unresolved.is_symlink():
        raise ValueError(f"{name} must not be a symbolic link: {unresolved}")
    path = unresolved.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{name} escapes its frozen root: {path}") from exc
    if not path.is_file():
        raise FileNotFoundError(f"{name} is missing: {path}")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise TypeError(f"{name} has invalid size provenance")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest or len(raw) != size:
        raise ValueError(f"{name} changed after the v7 manifest was frozen")
    return path


def verify_manifest(path: Path = DEFAULT_MANIFEST) -> tuple[dict[str, Any], str, Path]:
    """Verify the frozen corpus, one-factor contract, sources, and sealed split."""

    refuse_v7_execution()
    unresolved_manifest = path.expanduser()
    if unresolved_manifest.is_symlink():
        raise ValueError("predictive-shield corpus manifest must not be a symbolic link")
    path = unresolved_manifest.resolve()
    raw_manifest = path.read_bytes()
    manifest_sha256 = hashlib.sha256(raw_manifest).hexdigest()
    payload = json.loads(raw_manifest)
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported predictive-shield corpus manifest")
    if payload.get("corpus_id") != CORPUS_ID:
        raise ValueError("unexpected predictive-shield corpus identity")
    if payload.get("promotion_gate_frozen_before_development") != PROMOTION_GATE:
        raise ValueError("predictive-shield promotion gate changed after predeclaration")
    if payload.get("one_factor_preflight") != verify_one_factor_configs():
        raise ValueError("one-factor configuration preflight changed after corpus freeze")
    if payload.get("historical_reference_preflight") != historical_reference_preflight():
        raise ValueError("historical ROS reference identity changed after corpus freeze")
    if (
        payload.get("policy_runtime_dependencies_preflight")
        != policy_runtime_dependencies_preflight()
    ):
        raise ValueError("policy runtime dependency closure changed after corpus freeze")
    if payload.get("calibration_source_preflight") != runtime_calibration_preflight():
        raise ValueError("calibrated BARN runtime sources changed after corpus freeze")
    if payload.get("execution_environment_preflight") != execution_environment_preflight():
        raise ValueError("v7 execution environment changed after corpus freeze")

    benchmark = _require_mapping(payload.get("benchmark_scope"), "benchmark_scope")
    if (
        benchmark.get("source_generator") != GENERATOR_SOURCE
        or benchmark.get("source_generator_commit") != GENERATOR_COMMIT
        or benchmark.get("source_roles") != SOURCE_ROLES
    ):
        raise ValueError("v7 generator identity changed")
    generator_root = Path(str(benchmark.get("generator_root", ""))).expanduser().resolve()
    generator_state = _strict_generator_state(generator_root)
    if benchmark.get("generator_checkout") != generator_state:
        raise ValueError("v7 generator checkout state changed")
    if benchmark.get("generator_inputs") != _generator_inputs(generator_root):
        raise ValueError("v7 upstream generator inputs changed")
    isolated_generator = _require_mapping(
        benchmark.get("isolated_generator_execution"),
        "isolated_generator_execution",
    )
    if (
        isolated_generator.get("isolation") != "git-archive-plus-multiprocessing-spawn"
        or isolated_generator.get("inputs_before") != generator_state["inputs"]
        or isolated_generator.get("inputs_after") != generator_state["inputs"]
        or isolated_generator.get("worker_exit_code") != 0
        or not re.fullmatch(r"[0-9a-f]{64}", str(isolated_generator.get("archive_sha256", "")))
    ):
        raise ValueError("v7 isolated generator evidence is invalid")
    current_generation_state = _frozen_generation_state(generator_root)
    current_generation_state_sha256 = _state_sha256(current_generation_state)
    state_attestation = _require_mapping(
        payload.get("generation_state_attestation"),
        "generation_state_attestation",
    )
    if (
        state_attestation.get("pre_and_post_states_identical") is not True
        or state_attestation.get("pre_generation_sha256") != current_generation_state_sha256
        or state_attestation.get("post_generation_sha256") != current_generation_state_sha256
        or state_attestation.get("component_names") != sorted(current_generation_state)
    ):
        raise ValueError("v7 pre/post generation state attestation changed")

    status = _require_mapping(payload.get("status_at_freeze"), "status_at_freeze")
    if (
        status.get("development_policy_execution_started") is not False
        or status.get("sealed_confirmation_generated") is not False
        or status.get("sealed_confirmation_opened") is not False
        or status.get("deployment_enabled") is not False
    ):
        raise ValueError("manifest is not in the frozen pre-development state")

    identity = _require_mapping(payload.get("identity_partition"), "identity_partition")
    development_ids = tuple(int(value) for value in identity["development_world_ids"])
    sealed_ids = tuple(int(value) for value in identity["sealed_confirmation_world_ids"])
    forbidden_ids = tuple(int(value) for value in identity["forbidden_prior_ids"])
    if development_ids != DEVELOPMENT_WORLD_IDS:
        raise ValueError("v7 development identity order changed")
    if sealed_ids != SEALED_CONFIRMATION_WORLD_IDS:
        raise ValueError("v7 sealed identity order changed")
    if forbidden_ids != FORBIDDEN_WORLD_IDS:
        raise ValueError("v7 forbidden identity partition changed")
    if (
        identity.get("development_world_ids_sha256") != _ids_sha256(DEVELOPMENT_WORLD_IDS)
        or identity.get("sealed_confirmation_world_ids_sha256")
        != _ids_sha256(SEALED_CONFIRMATION_WORLD_IDS)
        or identity.get("forbidden_ids_sha256") != _ids_sha256(FORBIDDEN_WORLD_IDS)
    ):
        raise ValueError("v7 identity partition hashes changed")
    if set(development_ids) & (set(forbidden_ids) | set(sealed_ids)):
        raise ValueError("v7 development identities overlap prior or sealed evidence")

    corpus = _require_mapping(payload.get("development_corpus"), "development_corpus")
    unresolved_assets_root = Path(str(corpus["assets_root"])).expanduser()
    if unresolved_assets_root.is_symlink():
        raise ValueError("v7 development assets root must not be a symbolic link")
    assets_root = unresolved_assets_root.resolve()
    if not assets_root.is_dir():
        raise FileNotFoundError(f"v7 development assets root is missing: {assets_root}")
    episodes = corpus.get("episodes")
    if not isinstance(episodes, list) or len(episodes) != len(DEVELOPMENT_WORLD_IDS):
        raise ValueError("v7 development corpus episode count changed")
    if int(corpus.get("world_count", -1)) != len(DEVELOPMENT_WORLD_IDS):
        raise ValueError("v7 development corpus world_count changed")
    if corpus.get("corpus_sha256") != _corpus_sha256(episodes):
        raise ValueError("v7 development corpus identity hash changed")
    if corpus.get("independent_validation") != validate_generated_development_corpus(
        episodes,
        assets_root,
    ):
        raise ValueError("v7 independent corpus validation changed")
    generation_log = assets_root / "generation.log"
    if not generation_log.is_file() or sha256_file(generation_log) != corpus.get(
        "generation_log_sha256"
    ):
        raise ValueError("v7 generation log changed")
    episode_world_ids = tuple(
        int(_require_mapping(episode, "development episode")["world_id"]) for episode in episodes
    )
    if episode_world_ids != DEVELOPMENT_WORLD_IDS:
        raise ValueError("v7 development episode order or identities changed")
    verified_asset_paths: set[Path] = set()
    for episode in episodes:
        item = _require_mapping(episode, "development episode")
        world_id = int(item["world_id"])
        if world_id not in DEVELOPMENT_WORLD_IDS:
            raise ValueError(f"unexpected v7 generated world ID {world_id}")
        files = _require_mapping(item.get("files"), f"world {world_id} files")
        expected_files = {
            "world": assets_root / "world_files" / f"world_{world_id}.world",
            "path": assets_root / "path_files" / f"path_{world_id}.npy",
            "grid": assets_root / "grid_files" / f"grid_{world_id}.npy",
            "cspace": assets_root / "cspace_files" / f"cspace_{world_id}.npy",
            "metrics": assets_root / "metrics_files" / f"metrics_{world_id}.npy",
        }
        if set(files) != set(expected_files):
            raise ValueError(f"world {world_id} asset kinds changed")
        for kind, expected_path in expected_files.items():
            verified = _verify_file(
                assets_root,
                _require_mapping(files.get(kind), kind),
                f"{world_id}/{kind}",
            )
            if verified != expected_path.resolve() or verified in verified_asset_paths:
                raise ValueError(f"world {world_id}/{kind} has unexpected or duplicate path")
            verified_asset_paths.add(verified)

    if any(
        (assets_root / directory / f"{stem}_{world_id}{suffix}").exists()
        for world_id in sealed_ids
        for directory, stem, suffix in (
            ("world_files", "world", ".world"),
            ("path_files", "path", ".npy"),
            ("grid_files", "grid", ".npy"),
            ("cspace_files", "cspace", ".npy"),
            ("metrics_files", "metrics", ".npy"),
        )
    ):
        raise ValueError("v7 sealed confirmation geometry exists in the development root")

    recipe = _require_mapping(payload.get("sealed_confirmation_recipe"), "confirmation recipe")
    if (
        recipe.get("generated") is not False
        or recipe.get("opened") is not False
        or recipe.get("evaluated") is not False
        or recipe.get("root_authorization_required_even_after_development_pass") is not True
        or tuple(int(value) for value in recipe.get("world_ids", ()))
        != SEALED_CONFIRMATION_WORLD_IDS
        or recipe.get("seed_namespace") != SEED_NAMESPACE
        or recipe.get("cryptographically_sealed") is not False
        or recipe.get("operational_holdout_only") is not True
        or recipe.get("authorization_only_external_bundle_required_for_strong_confirmation")
        is not True
        or Path(str(recipe.get("canonical_assets_root", ""))).expanduser().resolve()
        != DEFAULT_CONFIRMATION_ASSETS_ROOT.resolve()
        or os.path.lexists(DEFAULT_CONFIRMATION_ASSETS_ROOT)
    ):
        raise ValueError("v7 operational confirmation holdout contract changed")

    frozen = _require_mapping(
        payload.get("frozen_policy_inputs_before_execution"),
        "frozen_policy_inputs_before_execution",
    )
    expected_primary = {
        "reference_config": REFERENCE_CONFIG,
        "challenger_config": CHALLENGER_CONFIG,
        "shared_model": GRID_MODEL,
    }
    for name, expected_path in expected_primary.items():
        verified = _verify_file(REPO_ROOT, _require_mapping(frozen.get(name), name), name)
        if verified != expected_path.resolve():
            raise ValueError(f"{name} path changed after the v7 manifest was frozen")
    source_tree = _require_mapping(frozen.get("policy_source_tree"), "policy_source_tree")
    if source_tree.get("path") != PARCEL_POLICY_SOURCE_ROOT.resolve().relative_to(
        REPO_ROOT.resolve()
    ).as_posix() or _source_tree_sha256(PARCEL_POLICY_SOURCE_ROOT) != source_tree.get("sha256"):
        raise ValueError("Parcel policy source changed after the v7 manifest was frozen")
    expected_groups = {
        "harness_files": HARNESS_FILES,
        "protected_production_files": PROTECTED_PRODUCTION_FILES,
    }
    for group_name, expected_group in expected_groups.items():
        group = _require_mapping(frozen.get(group_name), group_name)
        if set(group) != set(expected_group):
            raise ValueError(f"{group_name} membership changed after v7 freeze")
        for name, expected_path in expected_group.items():
            verified = _verify_file(
                REPO_ROOT,
                _require_mapping(group.get(name), str(name)),
                f"{group_name}/{name}",
            )
            if verified != expected_path.resolve():
                raise ValueError(f"{group_name}/{name} path changed after v7 freeze")

    protocol = _require_mapping(payload.get("protocol_frozen_before_development"), "protocol")
    if (
        protocol.get("sealed_confirmation_must_not_be_generated_opened_or_run_during_development")
        is not True
        or protocol.get("paired_reference_replay_required") is not True
        or int(protocol.get("suite_seed", -1)) != 20260803
        or int(protocol.get("trials_per_world", -1)) != 1
        or int(protocol.get("episode_workers", -1)) != 4
    ):
        raise ValueError("v7 frozen protocol guards are incomplete")
    _calibrated_config_from_protocol(protocol)
    return payload, manifest_sha256, assets_root


def _finite(
    mapping: Mapping[str, Any],
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = mapping[name]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TypeError(f"{name} must be a JSON number")
    value = float(raw)
    if (
        not math.isfinite(value)
        or (minimum is not None and value < minimum)
        or (maximum is not None and value > maximum)
    ):
        raise ValueError(f"{name} is outside its finite numeric range")
    return value


def _nonnegative_int(mapping: Mapping[str, Any], name: str) -> int:
    value = mapping[name]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError(f"{name} must be a non-negative integer")
    return value


def _strict_bool(mapping: Mapping[str, Any], name: str) -> bool:
    value = mapping[name]
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


def _episode_key(episode: Mapping[str, Any]) -> tuple[int, int]:
    world_index = episode["world_index"]
    trial = episode["trial"]
    if (
        isinstance(world_index, bool)
        or not isinstance(world_index, int)
        or isinstance(trial, bool)
        or not isinstance(trial, int)
        or trial < 0
    ):
        raise TypeError("episode world_index/trial must be non-negative integers")
    return world_index, trial


def _sensor_diagnostics(episode: Mapping[str, Any]) -> Mapping[str, Any]:
    return _require_mapping(episode.get("sensor_diagnostics"), "sensor diagnostics")


def _shield_diagnostics(episode: Mapping[str, Any]) -> Mapping[str, Any]:
    return _require_mapping(
        episode.get("shield_stall_diagnostics"),
        "shield-stall diagnostics",
    )


def _hashes_by_step(
    diagnostics: Mapping[str, Any],
    *,
    values_name: str,
    steps_name: str,
) -> dict[int, str]:
    raw_values = diagnostics[values_name]
    raw_steps = diagnostics[steps_name]
    if (
        not isinstance(raw_values, Sequence)
        or isinstance(raw_values, (str, bytes))
        or not isinstance(raw_steps, Sequence)
        or isinstance(raw_steps, (str, bytes))
    ):
        raise TypeError(f"{values_name}/{steps_name} must be arrays")
    values = list(raw_values)
    steps = list(raw_steps)
    if (
        len(steps) != len(values)
        or not values
        or any(
            isinstance(step, bool) or not isinstance(step, int) or step < 0 for step in steps
        )
        or steps != list(range(len(steps)))
        or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in values)
    ):
        raise ValueError(f"invalid causal trace alignment for {values_name}")
    return dict(zip(steps, values, strict=True))


def _action_values_by_step(
    diagnostics: Mapping[str, Any],
    action_hashes: Mapping[int, str],
) -> dict[int, tuple[float, float, bool]]:
    result: dict[int, tuple[float, float, bool]] = {}
    raw_values = diagnostics["published_action_values"]
    if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
        raise TypeError("published_action_values must be an array")
    for raw in raw_values:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 4:
            raise ValueError("invalid published_action_values causal trace")
        step, raw_forward, raw_yaw_rate, stop = raw
        if (
            isinstance(step, bool)
            or not isinstance(step, int)
            or step < 0
            or isinstance(raw_forward, bool)
            or not isinstance(raw_forward, (int, float))
            or isinstance(raw_yaw_rate, bool)
            or not isinstance(raw_yaw_rate, (int, float))
            or not isinstance(stop, bool)
        ):
            raise TypeError("published action fields have invalid types")
        forward = float(raw_forward)
        yaw_rate = float(raw_yaw_rate)
        if step in result or not math.isfinite(forward) or not math.isfinite(yaw_rate):
            raise ValueError("invalid published action value or duplicate step")
        digest = hashlib.sha256(struct.pack("<dd", forward, yaw_rate) + (b"\x01" if stop else b"\x00")).hexdigest()
        if action_hashes.get(step) != digest:
            raise ValueError("published action value does not match its motor-action digest")
        result[step] = (forward, yaw_rate, stop)
    if tuple(result) != tuple(action_hashes):
        raise ValueError("published action values and hashes must cover identical steps")
    return result


def causal_pair_diagnostics(
    reference: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Locate action divergence and prove it begins from an identical observation."""

    reference_keys = [_episode_key(item) for item in reference["episodes"]]
    candidate_keys = [_episode_key(item) for item in candidate["episodes"]]
    if len(set(reference_keys)) != len(reference_keys) or len(set(candidate_keys)) != len(
        candidate_keys
    ):
        raise ValueError("causal comparison rejects duplicate episode keys")
    reference_by_key = dict(zip(reference_keys, reference["episodes"], strict=True))
    candidate_by_key = dict(zip(candidate_keys, candidate["episodes"], strict=True))
    if reference_by_key.keys() != candidate_by_key.keys():
        raise ValueError("causal comparison requires identical episode keys")
    pairs: list[dict[str, Any]] = []
    for key in sorted(reference_by_key):
        reference_episode = reference_by_key[key]
        candidate_episode = candidate_by_key[key]
        reference_diag = _sensor_diagnostics(reference_episode)
        candidate_diag = _sensor_diagnostics(candidate_episode)
        reference_observations = _hashes_by_step(
            reference_diag,
            values_name="policy_observation_sha256",
            steps_name="policy_observation_steps",
        )
        candidate_observations = _hashes_by_step(
            candidate_diag,
            values_name="policy_observation_sha256",
            steps_name="policy_observation_steps",
        )
        reference_actions = _hashes_by_step(
            reference_diag,
            values_name="published_action_sha256",
            steps_name="published_action_steps",
        )
        candidate_actions = _hashes_by_step(
            candidate_diag,
            values_name="published_action_sha256",
            steps_name="published_action_steps",
        )
        reference_values = _action_values_by_step(reference_diag, reference_actions)
        candidate_values = _action_values_by_step(candidate_diag, candidate_actions)
        first_divergence: int | None = None
        identical_observation = False
        for step in sorted(reference_actions.keys() | candidate_actions.keys()):
            if reference_actions.get(step) != candidate_actions.get(step):
                first_divergence = step
                identical_observation = reference_observations.get(
                    step
                ) is not None and reference_observations.get(step) == candidate_observations.get(
                    step
                )
                break
        prefix_step_sets_identical = first_divergence is not None and (
            {step for step in reference_observations if step <= first_divergence}
            == {step for step in candidate_observations if step <= first_divergence}
            and {step for step in reference_actions if step <= first_divergence}
            == {step for step in candidate_actions if step <= first_divergence}
        )
        prefix_values_identical = bool(
            first_divergence is not None
            and prefix_step_sets_identical
            and all(
                reference_observations[step] == candidate_observations[step]
                for step in reference_observations
                if step <= first_divergence
            )
            and all(
                reference_actions[step] == candidate_actions[step]
                for step in reference_actions
                if step < first_divergence
            )
        )
        reference_shield = _shield_diagnostics(reference_episode)
        candidate_shield = _shield_diagnostics(candidate_episode)
        reference_value = (
            reference_values.get(first_divergence) if first_divergence is not None else None
        )
        candidate_value = (
            candidate_values.get(first_divergence) if first_divergence is not None else None
        )
        legacy_stop_replaced_by_safe_forward = bool(
            identical_observation
            and reference_value is not None
            and candidate_value is not None
            and abs(reference_value[0]) < 0.005
            and candidate_value[0] >= 0.005
            and not reference_value[2]
            and not candidate_value[2]
        )
        pairs.append(
            {
                "world_index": key[0],
                "trial": key[1],
                "affected": first_divergence is not None,
                "first_action_divergence_step": first_divergence,
                "first_divergence_observation_identical": identical_observation,
                "action_observation_prefix_identical": prefix_values_identical,
                "reference_action_at_first_divergence": reference_value,
                "candidate_action_at_first_divergence": candidate_value,
                "legacy_stop_replaced_by_safe_forward": legacy_stop_replaced_by_safe_forward,
                "reference_max_consecutive_obstacle_stop_steps": int(
                    reference_shield["max_consecutive_obstacle_stop_steps"]
                ),
                "candidate_max_consecutive_obstacle_stop_steps": int(
                    candidate_shield["max_consecutive_obstacle_stop_steps"]
                ),
            }
        )
    affected = [pair for pair in pairs if pair["affected"]]
    return {
        "mode_affected_paired_episode_count": len(affected),
        "legacy_stop_replaced_by_safe_forward_pair_count": sum(
            bool(pair["legacy_stop_replaced_by_safe_forward"]) for pair in pairs
        ),
        "all_first_divergences_share_identical_observation": bool(affected)
        and all(pair["first_divergence_observation_identical"] for pair in affected),
        "all_action_observation_prefixes_identical": bool(affected)
        and all(pair["action_observation_prefix_identical"] for pair in affected),
        "pairs": pairs,
    }


def _long_stall_count(report: Mapping[str, Any], threshold_steps: int) -> int:
    return sum(
        _nonnegative_int(
            _shield_diagnostics(episode),
            "max_consecutive_obstacle_stop_steps",
        )
        >= threshold_steps
        for episode in report["episodes"]
    )


def _sum_diagnostic_value(
    report: Mapping[str, Any],
    diagnostics_for: Any,
    name: str,
) -> int:
    total = 0
    for episode in report["episodes"]:
        diagnostics = diagnostics_for(episode)
        total += _nonnegative_int(diagnostics, name)
    return total


def _require_close(actual: float, expected: float, name: str) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"{name} does not match values recomputed from episodes")


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _build_gate_expected_contract(
    *,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    calibrated_config: Any,
    reference_policy: Mapping[str, Any],
    candidate_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive the gate's exact expected report identity from the frozen manifest."""

    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise ValueError("gate contract requires the frozen manifest SHA-256")
    protocol = _require_mapping(
        manifest.get("protocol_frozen_before_development"),
        "frozen protocol",
    )
    corpus = _require_mapping(manifest.get("development_corpus"), "development corpus")
    raw_episodes = corpus.get("episodes")
    if not isinstance(raw_episodes, Sequence) or isinstance(raw_episodes, (str, bytes)):
        raise TypeError("development corpus episodes must be an array")
    asset_sha256: dict[str, dict[str, str]] = {}
    optimal_path_length_m: dict[str, float] = {}
    assets_root = Path(str(corpus["assets_root"])).expanduser().resolve()
    for raw_episode in raw_episodes:
        episode = _require_mapping(raw_episode, "development corpus episode")
        world_id = episode.get("world_id")
        if isinstance(world_id, bool) or not isinstance(world_id, int):
            raise TypeError("development corpus world_id must be an integer")
        files = _require_mapping(episode.get("files"), "development corpus files")
        world = _require_mapping(files.get("world"), "development world file")
        path = _require_mapping(files.get("path"), "development path file")
        asset_sha256[str(world_id)] = {
            "world": str(world["sha256"]),
            "path": str(path["sha256"]),
        }
        optimal_path_length_m[str(world_id)] = load_generated_barn_world(
            assets_root,
            world_id,
        ).optimal_path_length_m
    if set(asset_sha256) != {str(value) for value in DEVELOPMENT_WORLD_IDS}:
        raise ValueError("gate contract assets differ from the exact development world set")

    frozen_inputs = _require_mapping(
        manifest.get("frozen_policy_inputs_before_execution"),
        "frozen policy inputs",
    )
    harness_files = _require_mapping(frozen_inputs.get("harness_files"), "frozen harness files")
    component_sha256 = {}
    for name in ("sensor_faithful_runner", "barn_native", "barn_ros2_adapter"):
        record = _require_mapping(harness_files.get(name), f"frozen harness file {name}")
        digest = record.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"frozen harness file {name} has an invalid digest")
        component_sha256[name] = digest

    native_config = asdict(calibrated_config)
    workers = int(protocol["episode_workers"])
    contract: dict[str, Any] = {
        "manifest_sha256": manifest_sha256,
        "native_config": native_config,
        "calibrated_config_sha256": _canonical_sha256(native_config),
        "suite_seed": int(protocol["suite_seed"]),
        "reference_policy": dict(reference_policy),
        "candidate_policy": dict(candidate_policy),
        "execution": {
            "evaluator_device": "cpu",
            "lidar_raycast_device": "cpu",
            "kinematics_device": "cpu",
            "policy_declared_device": "cpu",
            "episode_workers_requested": workers,
            "episode_workers_effective": min(workers, len(DEVELOPMENT_WORLD_IDS)),
            "process_start_method": "spawn" if workers > 1 else None,
            "durable_report_writer": "caller_or_parent_process_only",
        },
        "benchmark": {
            "id": SENSOR_FAITHFUL_EVALUATION_KIND,
            "source": BARN_SOURCE,
            "source_commit": BARN_SOURCE_COMMIT,
            "public_world_indices": list(DEVELOPMENT_WORLD_IDS),
            "official_gazebo_score": False,
            "asset_scope": "generated-public-style-development",
            "asset_manifest_sha256": manifest_sha256,
        },
        "provenance_component_sha256": component_sha256,
        "asset_sha256": asset_sha256,
        "optimal_path_length_m": optimal_path_length_m,
        "historical_reference_preflight": _require_mapping(
            manifest.get("historical_reference_preflight"),
            "historical reference preflight",
        ),
    }
    return contract


def _validate_provenance_against_contract(
    report: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    provenance = _require_mapping(report.get("provenance"), "report provenance")
    if provenance.get("config_sha256") != contract["calibrated_config_sha256"]:
        raise ValueError("report calibrated-config provenance changed")
    component_hashes = _require_mapping(
        contract.get("provenance_component_sha256"),
        "expected provenance component hashes",
    )
    for report_name, expected_name in (
        ("harness", "sensor_faithful_runner"),
        ("native_geometry", "barn_native"),
        ("calibrated_adapter", "barn_ros2_adapter"),
    ):
        component = _require_mapping(provenance.get(report_name), report_name)
        if component.get("sha256") != component_hashes[expected_name]:
            raise ValueError(f"report {report_name} provenance changed")
    expected_assets = _require_mapping(contract.get("asset_sha256"), "expected asset hashes")
    assets = provenance.get("assets")
    if not isinstance(assets, Sequence) or isinstance(assets, (str, bytes)):
        raise TypeError("report asset provenance must be an array")
    if len(assets) != len(DEVELOPMENT_WORLD_IDS):
        raise ValueError("report asset provenance count changed")
    seen_worlds: set[int] = set()
    for raw in assets:
        item = _require_mapping(raw, "asset provenance")
        world_index = item.get("world_index")
        if isinstance(world_index, bool) or not isinstance(world_index, int):
            raise TypeError("asset provenance world_index must be an integer")
        if world_index in seen_worlds:
            raise ValueError(f"duplicate asset provenance for world {world_index}")
        seen_worlds.add(world_index)
        expected = _require_mapping(expected_assets.get(str(world_index)), "expected asset")
        world = _require_mapping(item.get("world"), "world provenance")
        path = _require_mapping(item.get("reference_path"), "path provenance")
        if world.get("sha256") != expected["world"] or path.get("sha256") != expected["path"]:
            raise ValueError(f"asset provenance changed for world {world_index}")
    if seen_worlds != set(DEVELOPMENT_WORLD_IDS):
        raise ValueError("asset provenance does not cover the exact development world set")


def _obstacle_stop_steps(diagnostics: Mapping[str, Any], *, step_count: int) -> tuple[int, ...]:
    raw_steps = diagnostics["obstacle_stop_command_steps"]
    if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, (str, bytes)):
        raise TypeError("obstacle_stop_command_steps must be an array")
    steps = tuple(raw_steps)
    if (
        any(isinstance(step, bool) or not isinstance(step, int) for step in steps)
        or tuple(sorted(set(steps))) != steps
        or any(step < 0 or step >= step_count for step in steps)
    ):
        raise ValueError("obstacle_stop_command_steps must be unique ordered action steps")
    return steps


def _maximum_consecutive_steps(steps: Sequence[int]) -> int:
    maximum = 0
    current = 0
    previous: int | None = None
    for step in steps:
        current = current + 1 if previous is not None and step == previous + 1 else 1
        maximum = max(maximum, current)
        previous = step
    return maximum


def _validate_report_against_contract(
    report: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    arm: str,
) -> dict[str, float | int]:
    if report.get("native_config") != contract["native_config"]:
        raise ValueError(f"{arm} native config differs from the frozen contract")
    if report.get("suite_seed") != contract["suite_seed"]:
        raise ValueError(f"{arm} suite seed differs from the frozen contract")
    if report.get("policy") != contract[f"{arm}_policy"]:
        raise ValueError(f"{arm} policy identity differs from the frozen contract")
    if report.get("execution") != contract["execution"]:
        raise ValueError(f"{arm} execution contract differs from the frozen contract")
    benchmark = _require_mapping(report.get("benchmark"), f"{arm} benchmark")
    expected_benchmark = _require_mapping(contract.get("benchmark"), "expected benchmark")
    for key, expected in expected_benchmark.items():
        if benchmark.get(key) != expected:
            raise ValueError(f"{arm} benchmark field {key!r} differs from the frozen contract")
    _validate_provenance_against_contract(report, contract)

    episodes = report.get("episodes")
    if not isinstance(episodes, Sequence) or isinstance(episodes, (str, bytes)):
        raise TypeError(f"{arm} episodes must be an array")
    by_key: dict[tuple[int, int], Mapping[str, Any]] = {}
    for raw_episode in episodes:
        episode = _require_mapping(raw_episode, f"{arm} episode")
        key = _episode_key(episode)
        if key in by_key:
            raise ValueError(f"{arm} contains duplicate episode key {key}")
        by_key[key] = episode
    expected_keys = {(world_id, 0) for world_id in DEVELOPMENT_WORLD_IDS}
    if set(by_key) != expected_keys:
        raise ValueError(f"{arm} episode keys differ from the exact 30-world contract")

    successes = 0
    collisions = 0
    trial_timeouts = 0
    startup_failures = 0
    stopped_episodes = 0
    normalization_failures = 0
    reverse_steps_total = 0
    obstacle_stop_steps_total = 0
    maximum_obstacle_stall = 0
    long_stall_episodes = 0
    outcomes: Counter[str] = Counter()
    navigation_metrics: list[float] = []
    clearances: list[float] = []
    for (world_index, trial), episode in sorted(by_key.items()):
        seed = episode["episode_seed"]
        expected_seed = int(contract["suite_seed"]) + world_index * 1_009 + trial
        if isinstance(seed, bool) or not isinstance(seed, int) or seed != expected_seed:
            raise ValueError(f"{arm} episode {world_index}/{trial} has the wrong seed")
        success = _strict_bool(episode, "success")
        collided = _strict_bool(episode, "collided")
        timed_out = _strict_bool(episode, "timed_out")
        startup_timed_out = _strict_bool(episode, "startup_timed_out")
        trial_started = _strict_bool(episode, "trial_started")
        _strict_bool(episode, "stopped")
        status = episode["status"]
        if status not in {"succeeded", "collided", "timeout", "startup_timeout"}:
            raise ValueError(f"{arm} episode {world_index}/{trial} has an invalid status")
        expected_flags = {
            "succeeded": (True, False, False, False),
            "collided": (False, True, False, False),
            "timeout": (False, False, True, False),
            "startup_timeout": (False, False, True, True),
        }[str(status)]
        if (success, collided, timed_out, startup_timed_out) != expected_flags:
            raise ValueError(f"{arm} episode {world_index}/{trial} outcome flags disagree")
        if status == "startup_timeout" and trial_started:
            raise ValueError(f"{arm} episode {world_index}/{trial} trial-start state disagrees")
        if status in {"succeeded", "timeout"} and not trial_started:
            raise ValueError(f"{arm} episode {world_index}/{trial} trial-start state disagrees")
        elapsed = _finite(episode, "elapsed_time_s", minimum=0.0, maximum=100.0)
        simulation_elapsed = _finite(
            episode,
            "simulation_elapsed_time_s",
            minimum=0.0,
            maximum=110.0,
        )
        if simulation_elapsed + 1e-12 < elapsed:
            raise ValueError("simulation elapsed time cannot be shorter than scored time")
        startup_time = episode["startup_time_s"]
        if trial_started:
            if (
                isinstance(startup_time, bool)
                or not isinstance(startup_time, (int, float))
                or not math.isfinite(float(startup_time))
                or float(startup_time) < 0.0
            ):
                raise TypeError("started trials require a finite non-negative startup_time_s")
            _require_close(
                simulation_elapsed,
                elapsed + float(startup_time),
                "simulation_elapsed_time_s",
            )
        elif startup_time is not None:
            raise ValueError("unstarted trials must have null startup_time_s")
        if status == "timeout":
            _require_close(elapsed, 100.0, "elapsed_time_s")
        if status == "startup_timeout":
            _require_close(elapsed, 0.0, "elapsed_time_s")
            _require_close(simulation_elapsed, 10.0, "simulation_elapsed_time_s")
        steps = _nonnegative_int(episode, "steps")
        final_distance = _finite(episode, "final_distance_to_goal_m", minimum=0.0)
        final_position = episode["final_position_xy"]
        if (
            not isinstance(final_position, Sequence)
            or isinstance(final_position, (str, bytes))
            or len(final_position) != 2
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in final_position
            )
        ):
            raise TypeError("final_position_xy must contain exactly two finite numbers")
        _require_close(
            final_distance,
            math.dist(tuple(float(value) for value in final_position), OFFICIAL_GOAL_XY),
            "final_distance_to_goal_m",
        )
        success_radius = _finite(
            _require_mapping(contract.get("native_config"), "expected native config"),
            "success_radius_m",
            minimum=0.0,
        )
        if success is not (not collided and final_distance <= success_radius + 1e-12):
            raise ValueError(f"{arm} episode {world_index}/{trial} goal outcome disagrees")
        optimal_path_length = _finite(episode, "optimal_path_length_m", minimum=1e-12)
        expected_lengths = _require_mapping(
            contract.get("optimal_path_length_m"),
            "expected optimal path lengths",
        )
        _require_close(
            optimal_path_length,
            _finite(expected_lengths, str(world_index), minimum=1e-12),
            "optimal_path_length_m",
        )
        _require_close(
            _finite(episode, "optimal_time_s", minimum=0.0),
            optimal_path_length / OFFICIAL_REFERENCE_SPEED_MPS,
            "optimal_time_s",
        )
        metric = _finite(episode, "navigation_metric", minimum=0.0, maximum=0.5)
        _require_close(
            metric,
            barn_navigation_metric(success, elapsed, optimal_path_length),
            "navigation_metric",
        )
        evaluator = _require_mapping(
            episode.get("evaluator_diagnostics"),
            "episode evaluator diagnostics",
        )
        if _strict_bool(evaluator, "evaluator_private_state") is not True:
            raise ValueError("evaluator-private state flag must remain true")
        clearance = _finite(
            evaluator,
            "minimum_signed_obstacle_clearance_m",
        )
        sensor = _sensor_diagnostics(episode)
        shield = _shield_diagnostics(episode)
        _nonnegative_int(sensor, "normalization_failures")
        reverse_command_steps = _nonnegative_int(shield, "reverse_command_steps")
        maximum_stall = _nonnegative_int(shield, "max_consecutive_obstacle_stop_steps")
        issued_steps = _nonnegative_int(shield, "issued_policy_command_steps")
        obstacle_stop_count = _nonnegative_int(shield, "obstacle_stop_steps")
        policy_stop_latched = _strict_bool(shield, "policy_stop_latched")
        latch_step = shield["policy_stop_latch_step"]
        if latch_step is not None and (
            isinstance(latch_step, bool)
            or not isinstance(latch_step, int)
            or not 0 <= latch_step < steps
        ):
            raise TypeError("policy_stop_latch_step must be null or a valid action step")
        if policy_stop_latched is not (latch_step is not None) or policy_stop_latched is not bool(
            episode["stopped"]
        ):
            raise ValueError("policy-stop latch diagnostics disagree")
        action_hashes = _hashes_by_step(
            sensor,
            values_name="published_action_sha256",
            steps_name="published_action_steps",
        )
        observation_hashes = _hashes_by_step(
            sensor,
            values_name="policy_observation_sha256",
            steps_name="policy_observation_steps",
        )
        action_values = _action_values_by_step(sensor, action_hashes)
        if len(action_hashes) != steps or len(observation_hashes) != issued_steps:
            raise ValueError("action/observation traces disagree with episode step counts")
        if policy_stop_latched and issued_steps != int(latch_step) + 1:
            raise ValueError("policy-stop latch step disagrees with issued policy calls")
        if not policy_stop_latched and issued_steps != steps:
            raise ValueError("unlatched episode must issue one policy command per action step")
        recomputed_reverse = sum(
            forward <= -0.005
            for step, (forward, _yaw_rate, _stop) in action_values.items()
            if step < issued_steps
        )
        if reverse_command_steps != recomputed_reverse:
            raise ValueError("reverse-command diagnostics disagree with published actions")
        stop_steps = _obstacle_stop_steps(shield, step_count=steps)
        if (
            obstacle_stop_count != len(stop_steps)
            or maximum_stall != _maximum_consecutive_steps(stop_steps)
            or any(step >= issued_steps for step in stop_steps)
        ):
            raise ValueError("obstacle-stop diagnostics disagree with their exact step trace")
        successes += int(success)
        collisions += int(collided)
        trial_timeouts += int(status == "timeout")
        startup_failures += int(status == "startup_timeout")
        stopped_episodes += int(bool(episode["stopped"]))
        normalization_failures += int(sensor["normalization_failures"])
        reverse_steps_total += reverse_command_steps
        obstacle_stop_steps_total += obstacle_stop_count
        maximum_obstacle_stall = max(maximum_obstacle_stall, maximum_stall)
        long_stall_episodes += int(maximum_stall >= int(PROMOTION_GATE["long_shield_stall_steps"]))
        outcomes[str(status)] += 1
        navigation_metrics.append(metric)
        clearances.append(clearance)

    count = len(by_key)
    recomputed: dict[str, float | int] = {
        "episode_count": count,
        "success_rate": successes / count,
        "collision_rate": collisions / count,
        "timeout_rate": trial_timeouts / count,
        "startup_failure_rate": startup_failures / count,
        "navigation_metric": fmean(navigation_metrics),
        "minimum_signed_obstacle_clearance_m": min(clearances),
    }
    aggregate = _require_mapping(report.get("aggregate"), f"{arm} aggregate")
    _require_close(_finite(aggregate, "episodes", minimum=0.0), float(count), "episodes")
    _require_close(
        _finite(aggregate, "worlds", minimum=0.0),
        float(len(DEVELOPMENT_WORLD_IDS)),
        "worlds",
    )
    _require_close(_finite(aggregate, "trials_per_world", minimum=0.0), 1.0, "trials")
    for name in (
        "success_rate",
        "collision_rate",
        "timeout_rate",
        "startup_failure_rate",
    ):
        _require_close(
            _finite(aggregate, name, minimum=0.0, maximum=1.0),
            float(recomputed[name]),
            name,
        )
    _require_close(
        _finite(aggregate, "navigation_metric", minimum=0.0, maximum=0.5),
        float(recomputed["navigation_metric"]),
        "navigation_metric",
    )
    _require_close(
        _finite(aggregate, "stopped_outside_goal_rate", minimum=0.0, maximum=1.0),
        0.0,
        "stopped_outside_goal_rate",
    )
    _require_close(
        _finite(aggregate, "policy_stop_latch_rate", minimum=0.0, maximum=1.0),
        stopped_episodes / count,
        "policy_stop_latch_rate",
    )
    _finite(aggregate, "adapter_act_p99_ms", minimum=0.0)
    _finite(aggregate, "controller_step_p99_ms", minimum=0.0)
    evaluator_aggregate = _require_mapping(
        aggregate.get("evaluator_diagnostics"),
        f"{arm} aggregate evaluator diagnostics",
    )
    if _strict_bool(evaluator_aggregate, "private_state_not_exposed_to_policy") is not True:
        raise ValueError("aggregate evaluator-private state flag must remain true")
    if evaluator_aggregate.get("outcome_counts") != dict(sorted(outcomes.items())):
        raise ValueError("aggregate outcome counts disagree with episode outcomes")
    if evaluator_aggregate.get("failure_counts") != {
        key: value for key, value in sorted(outcomes.items()) if key != "succeeded"
    }:
        raise ValueError("aggregate failure counts disagree with episode outcomes")
    _require_close(
        _finite(evaluator_aggregate, "minimum_signed_obstacle_clearance_m"),
        float(recomputed["minimum_signed_obstacle_clearance_m"]),
        "minimum_signed_obstacle_clearance_m",
    )
    sensor_aggregate = _require_mapping(
        aggregate.get("sensor_diagnostics"),
        f"{arm} aggregate sensor diagnostics",
    )
    expected_sensor_counts = {
        "long_shield_stall_threshold_steps": int(PROMOTION_GATE["long_shield_stall_steps"]),
        "long_shield_stall_episode_count": long_stall_episodes,
        "sensor_normalization_failures": normalization_failures,
        "reverse_command_steps": reverse_steps_total,
        "obstacle_stop_steps": obstacle_stop_steps_total,
        "max_consecutive_obstacle_stop_steps": maximum_obstacle_stall,
    }
    for name, expected_value in expected_sensor_counts.items():
        if _nonnegative_int(sensor_aggregate, name) != expected_value:
            raise ValueError(f"aggregate sensor diagnostic {name} disagrees with episodes")
    return recomputed


def _policy_equivalence(reference: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    reference_policy = _require_mapping(reference.get("policy"), "reference policy")
    candidate_policy = _require_mapping(candidate.get("policy"), "candidate policy")
    for key in (
        "agent_id",
        "adapter_id",
        "model_id",
        "execution_device",
        "policy_inputs",
        "underlying_policy_adapter_id",
        "sensor_transport",
    ):
        if (
            key not in reference_policy
            or key not in candidate_policy
            or reference_policy[key] is None
            or reference_policy[key] != candidate_policy[key]
        ):
            return False
    reference_provenance = _require_mapping(reference_policy.get("provenance"), "provenance")
    candidate_provenance = _require_mapping(candidate_policy.get("provenance"), "provenance")
    for key in (
        "implementation",
        "policy_source_tree",
        "model_artifact",
        "runtime_dependencies",
        "calibrated_sensor_transport",
    ):
        if (
            key not in reference_provenance
            or key not in candidate_provenance
            or reference_provenance[key] is None
            or reference_provenance[key] != candidate_provenance[key]
        ):
            return False
    return True


def _exact_development_episode_contract(
    reference: Mapping[str, Any],
    candidate: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> bool:
    expected_keys = {(world_id, 0) for world_id in DEVELOPMENT_WORLD_IDS}
    for report in (reference, candidate):
        episodes = report.get("episodes")
        if not isinstance(episodes, Sequence) or isinstance(episodes, (str, bytes)):
            return False
        keys = [_episode_key(item) for item in episodes]
        if len(keys) != len(expected_keys) or len(set(keys)) != len(keys):
            return False
        if set(keys) != expected_keys:
            return False
        benchmark = report.get("benchmark")
        aggregate = report.get("aggregate")
        if not isinstance(benchmark, Mapping) or not isinstance(aggregate, Mapping):
            return False
        if tuple(int(value) for value in benchmark.get("public_world_indices", ())) != (
            DEVELOPMENT_WORLD_IDS
        ):
            return False
        if (
            float(aggregate.get("episodes", math.nan)) != len(expected_keys)
            or float(aggregate.get("worlds", math.nan)) != len(DEVELOPMENT_WORLD_IDS)
            or float(aggregate.get("trials_per_world", math.nan)) != 1.0
        ):
            return False
    return int(comparison.get("paired_episode_count", -1)) == len(expected_keys)


def evaluate_gate(
    report: Mapping[str, Any],
    *,
    expected_contract: Mapping[str, Any],
) -> tuple[dict[str, bool], dict[str, Any]]:
    """Evaluate only the conditions frozen before v7 development execution."""

    reference = _require_mapping(report.get("baseline"), "reference")
    candidate = _require_mapping(report.get("candidate"), "candidate")
    comparison = _require_mapping(report.get("comparison"), "comparison")
    paired = _require_mapping(comparison.get("paired_outcomes"), "paired outcomes")
    deltas = _require_mapping(comparison.get("candidate_minus_baseline"), "paired deltas")
    reference_aggregate = _require_mapping(reference.get("aggregate"), "reference aggregate")
    candidate_aggregate = _require_mapping(candidate.get("aggregate"), "candidate aggregate")
    expected = _require_mapping(expected_contract, "expected gate contract")
    reference_recomputed = _validate_report_against_contract(
        reference,
        expected,
        arm="reference",
    )
    candidate_recomputed = _validate_report_against_contract(
        candidate,
        expected,
        arm="candidate",
    )
    recomputed_comparison = compare_barn_reports(reference, candidate)
    if comparison != recomputed_comparison:
        raise ValueError("paired comparison differs from values recomputed from episodes")
    causal = causal_pair_diagnostics(reference, candidate)

    reference_by_key = {_episode_key(item): item for item in reference["episodes"]}
    candidate_by_key = {_episode_key(item): item for item in candidate["episodes"]}
    success_gains = sum(
        _strict_bool(candidate_by_key[key], "success")
        and not _strict_bool(reference_by_key[key], "success")
        for key in reference_by_key
    )
    success_regressions = sum(
        _strict_bool(reference_by_key[key], "success")
        and not _strict_bool(candidate_by_key[key], "success")
        for key in reference_by_key
    )
    if (
        _nonnegative_int(paired, "success_gains") != success_gains
        or _nonnegative_int(paired, "success_regressions") != success_regressions
    ):
        raise ValueError("paired success outcomes do not match episode records")
    recomputed_success_delta = float(candidate_recomputed["success_rate"]) - float(
        reference_recomputed["success_rate"]
    )
    recomputed_metric_delta = float(candidate_recomputed["navigation_metric"]) - float(
        reference_recomputed["navigation_metric"]
    )
    _require_close(
        _finite(deltas, "success_rate", minimum=-1.0, maximum=1.0),
        recomputed_success_delta,
        "candidate_minus_baseline.success_rate",
    )
    _require_close(
        _finite(deltas, "navigation_metric", minimum=-0.5, maximum=0.5),
        recomputed_metric_delta,
        "candidate_minus_baseline.navigation_metric",
    )

    threshold = int(PROMOTION_GATE["long_shield_stall_steps"])
    reference_long_stalls = _long_stall_count(reference, threshold)
    candidate_long_stalls = _long_stall_count(candidate, threshold)
    reference_failure_rate = float(reference_recomputed["timeout_rate"])
    candidate_failure_rate = float(candidate_recomputed["timeout_rate"])
    reference_clearance = float(reference_recomputed["minimum_signed_obstacle_clearance_m"])
    candidate_clearance = float(candidate_recomputed["minimum_signed_obstacle_clearance_m"])

    candidate_p99 = max(
        _finite(candidate_aggregate, "adapter_act_p99_ms", minimum=0.0),
        _finite(candidate_aggregate, "controller_step_p99_ms", minimum=0.0),
    )
    reference_p99 = max(
        _finite(reference_aggregate, "adapter_act_p99_ms", minimum=0.0),
        _finite(reference_aggregate, "controller_step_p99_ms", minimum=0.0),
    )
    latency_ratio = candidate_p99 / reference_p99 if reference_p99 > 0.0 else math.inf
    one_factor = verify_one_factor_configs()
    historical_reference = _require_mapping(
        expected.get("historical_reference_preflight"),
        "expected historical reference",
    )
    reference_execution = reference.get("execution")
    candidate_execution = candidate.get("execution")
    reference_provenance = reference.get("provenance")
    candidate_provenance = candidate.get("provenance")
    same_execution = bool(
        comparison.get("same_worlds_trials_config_and_seeds") is True
        and _exact_development_episode_contract(reference, candidate, comparison)
        and reference["benchmark"]["asset_manifest_sha256"]
        == candidate["benchmark"]["asset_manifest_sha256"]
        and reference["native_config"] == candidate["native_config"]
        and reference["suite_seed"] == candidate["suite_seed"]
        and isinstance(reference_execution, Mapping)
        and isinstance(candidate_execution, Mapping)
        and bool(reference_execution)
        and reference_execution == candidate_execution
        and isinstance(reference_provenance, Mapping)
        and isinstance(candidate_provenance, Mapping)
        and bool(reference_provenance)
        and reference_provenance == candidate_provenance
        and _policy_equivalence(reference, candidate)
        and reference.get("policy") == expected.get("reference_policy")
        and candidate.get("policy") == expected.get("candidate_policy")
    )
    sensor_failures = _sum_diagnostic_value(
        candidate,
        _sensor_diagnostics,
        "normalization_failures",
    )
    reverse_steps = _sum_diagnostic_value(
        candidate,
        _shield_diagnostics,
        "reverse_command_steps",
    )

    gates = {
        "single_effective_config_difference": (
            one_factor["effective_leaf_differences"]
            == {
                "safety.predictive_mode": {
                    "reference": "stop",
                    "challenger": "projected_speed_cap",
                }
            }
        ),
        "exact_immutable_ros_reference": (
            one_factor["reference_config_sha256"]
            == "807909c4e58868e3e6023fea0113a71b00d7036276e29fb1ed5caa6d848df0c1"
            and historical_reference["claims"]["reference_implementation_matches_exercised_package"]
            is True
        ),
        "same_worlds_trials_seeds_dynamics_manifest_sources": same_execution,
        "reference_long_shield_stall_exercised": reference_long_stalls
        >= int(PROMOTION_GATE["minimum_reference_long_shield_stall_episodes"]),
        "candidate_has_no_long_shield_stall": candidate_long_stalls
        <= int(PROMOTION_GATE["maximum_candidate_long_shield_stall_episodes"]),
        "minimum_mode_affected_paired_episodes": int(causal["mode_affected_paired_episode_count"])
        >= int(PROMOTION_GATE["minimum_mode_affected_paired_episodes"]),
        "first_divergence_observation_identity": bool(
            causal["all_first_divergences_share_identical_observation"]
        )
        is bool(PROMOTION_GATE["all_first_divergences_must_share_identical_observation"]),
        "action_observation_prefix_identity": bool(
            causal["all_action_observation_prefixes_identical"]
        )
        is bool(PROMOTION_GATE["all_action_observation_prefixes_must_match_before_divergence"]),
        "legacy_stop_replaced_by_safe_forward": int(
            causal["legacy_stop_replaced_by_safe_forward_pair_count"]
        )
        >= int(PROMOTION_GATE["minimum_legacy_stop_replaced_by_safe_forward_pairs"]),
        "minimum_paired_success_gains": success_gains
        >= int(PROMOTION_GATE["minimum_paired_success_gains"]),
        "maximum_paired_success_regressions": success_regressions
        <= int(PROMOTION_GATE["maximum_paired_success_regressions"]),
        "minimum_success_rate_delta": recomputed_success_delta + 1e-12
        >= float(PROMOTION_GATE["minimum_success_rate_delta"]),
        "minimum_navigation_metric_delta": recomputed_metric_delta + 1e-12
        >= float(PROMOTION_GATE["minimum_navigation_metric_delta"]),
        "minimum_timeout_or_stop_rate_reduction": reference_failure_rate
        - candidate_failure_rate
        + 1e-12
        >= float(PROMOTION_GATE["minimum_timeout_or_stop_rate_reduction"]),
        "zero_candidate_collision_rate": float(candidate_recomputed["collision_rate"])
        == float(PROMOTION_GATE["candidate_collision_rate_must_equal"]),
        "candidate_timeout_rate_not_increased": float(candidate_recomputed["timeout_rate"])
        <= float(reference_recomputed["timeout_rate"]) + 1e-12,
        "zero_startup_failures": max(
            float(reference_recomputed["startup_failure_rate"]),
            float(candidate_recomputed["startup_failure_rate"]),
        )
        <= float(PROMOTION_GATE["maximum_startup_failure_rate"]),
        "minimum_signed_body_clearance": candidate_clearance
        >= float(PROMOTION_GATE["minimum_signed_body_clearance_m"]),
        "maximum_clearance_floor_regression": candidate_clearance
        >= reference_clearance
        - float(PROMOTION_GATE["maximum_clearance_floor_regression_m"])
        - 1e-12,
        "controller_p99_latency_absolute": candidate_p99
        <= float(PROMOTION_GATE["maximum_controller_p99_latency_ms"]),
        "controller_p99_latency_ratio": latency_ratio
        <= float(PROMOTION_GATE["maximum_controller_p99_latency_ratio"]),
        "zero_sensor_normalization_failures": sensor_failures
        <= int(PROMOTION_GATE["maximum_sensor_normalization_failures"]),
        "zero_reverse_command_steps": reverse_steps
        <= int(PROMOTION_GATE["maximum_reverse_command_steps"]),
    }
    diagnostics = {
        "reference_long_shield_stall_episodes": reference_long_stalls,
        "candidate_long_shield_stall_episodes": candidate_long_stalls,
        "mode_affected_paired_episode_count": causal["mode_affected_paired_episode_count"],
        "legacy_stop_replaced_by_safe_forward_pair_count": causal[
            "legacy_stop_replaced_by_safe_forward_pair_count"
        ],
        "all_action_observation_prefixes_identical": causal[
            "all_action_observation_prefixes_identical"
        ],
        "causal_pairs": causal["pairs"],
        "reference_timeout_or_stop_rate": reference_failure_rate,
        "candidate_timeout_or_stop_rate": candidate_failure_rate,
        "timeout_or_stop_rate_reduction": reference_failure_rate - candidate_failure_rate,
        "reference_minimum_signed_clearance_m": reference_clearance,
        "candidate_minimum_signed_clearance_m": candidate_clearance,
        "clearance_floor_delta_m": candidate_clearance - reference_clearance,
        "reference_adapter_or_controller_p99_ms": reference_p99,
        "candidate_adapter_or_controller_p99_ms": candidate_p99,
        "controller_p99_latency_ratio": latency_ratio,
        "candidate_sensor_normalization_failures": sensor_failures,
        "candidate_reverse_command_steps": reverse_steps,
        "all_conditions_passed": all(gates.values()),
    }
    return gates, diagnostics


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    temporary = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o444)
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise FileExistsError(f"refusing to replace immutable evidence: {path}") from exc
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError:
                pass
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact_evidence(path: Path) -> dict[str, Any] | None:
    """Describe one atomically installed artifact from a single byte snapshot."""

    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def _claim_is_owned(
    path: Path,
    *,
    run_id: str,
    ownership_nonce: str,
    expected_sha256: str,
) -> bool:
    """Return whether the installed no-clobber claim is exactly this process's claim."""

    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(payload, Mapping)
        and payload.get("run_id") == run_id
        and payload.get("ownership_nonce") == ownership_nonce
        and hashlib.sha256(raw).hexdigest() == expected_sha256
    )


def _preflight_canonical_output_paths(
    *,
    canonical_results_root: Path,
    claim_path: Path,
    outcome_path: Path,
    full_report_path: Path,
    ledger_path: Path,
    summary_path: Path,
) -> None:
    """Create output parents and reject aliases or prior one-shot evidence."""

    root = canonical_results_root.expanduser().resolve()
    paths = {
        "single-use claim": claim_path,
        "terminal outcome": outcome_path,
        "full report": full_report_path,
        "ledger record": ledger_path,
        "summary": summary_path,
    }
    resolved: dict[str, Path] = {}
    for name, raw_path in paths.items():
        path = raw_path.expanduser().resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"canonical {name} escapes the v7 results root: {path}") from exc
        resolved[name] = path
    if len(set(resolved.values())) != len(resolved):
        raise ValueError("canonical v7 output paths must be distinct")

    # Create every directory that a post-claim write can need before consuming
    # the corpus.  A filesystem/permission error therefore leaves it unclaimed.
    for path in resolved.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.parent.is_dir():  # pragma: no cover - defensive race guard.
            raise NotADirectoryError(f"canonical output parent is not a directory: {path.parent}")

    # Check the corpus-wide terminal markers first.  The outcome check is what
    # still blocks a rerun if an operator improperly removes only the claim.
    for name in ("terminal outcome", "single-use claim", "full report", "ledger record", "summary"):
        path = resolved[name]
        if path.exists():
            raise FileExistsError(f"v7 {name} already exists; this corpus cannot be rerun: {path}")


def _terminal_outcome_payload(
    *,
    status: str,
    stage: str,
    run_id: str,
    manifest_path: Path,
    manifest_sha256: str,
    claim_ownership_nonce: str,
    claim_path: Path,
    full_report_path: Path,
    ledger_path: Path,
    summary_path: Path,
    error: BaseException | None,
) -> dict[str, Any]:
    """Build the sole corpus-level terminal record from installed artifacts."""

    if status not in {"completed", "aborted"}:
        raise ValueError(f"unsupported terminal status: {status}")
    if (status == "aborted") is (error is None):
        raise ValueError("aborted outcomes require an exception and completed outcomes forbid one")

    claim = _artifact_evidence(claim_path)
    if claim is None:
        raise FileNotFoundError("cannot terminalize a v7 execution without its immutable claim")
    artifacts = {
        "full_report": _artifact_evidence(full_report_path),
        "ledger_record": _artifact_evidence(ledger_path),
        "summary": _artifact_evidence(summary_path),
    }
    if status == "completed" and any(value is None for value in artifacts.values()):
        raise RuntimeError(
            "completed terminal evidence requires report, ledger record, and summary artifacts"
        )

    exception: dict[str, str] | None = None
    if error is not None:
        error_type = type(error)
        exception = {
            "class": f"{error_type.__module__}.{error_type.__qualname__}",
            "message": str(error),
        }
    return {
        "schema_version": _TERMINAL_OUTCOME_SCHEMA_VERSION,
        "corpus_id": CORPUS_ID,
        "run_id": run_id,
        "status": status,
        "stage": stage,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "manifest": {
            "path": str(manifest_path.resolve()),
            "sha256": manifest_sha256,
        },
        "single_use_claim": claim,
        "claim_ownership_nonce": claim_ownership_nonce,
        "artifacts": artifacts,
        "exception": exception,
    }


def _run_single_use_claimed_execution(
    *,
    canonical_results_root: Path,
    claim_path: Path,
    outcome_path: Path,
    full_report_path: Path,
    ledger_path: Path,
    summary_path: Path,
    manifest_path: Path,
    manifest_sha256: str,
    run_id: str,
    claim: Mapping[str, Any],
    execute: Callable[[Callable[[str], None], str], dict[str, Any]],
) -> dict[str, Any]:
    """Claim once, execute, and leave one completed or aborted terminal record."""

    _preflight_canonical_output_paths(
        canonical_results_root=canonical_results_root,
        claim_path=claim_path,
        outcome_path=outcome_path,
        full_report_path=full_report_path,
        ledger_path=ledger_path,
        summary_path=summary_path,
    )
    ownership_nonce = claim.get("ownership_nonce")
    if not isinstance(ownership_nonce, str) or not _SAFE_OWNERSHIP_NONCE.fullmatch(ownership_nonce):
        raise ValueError("v7 claim requires a unique 32-character lowercase hex ownership nonce")
    if claim.get("run_id") != run_id:
        raise ValueError("v7 claim run_id differs from the claimed execution run_id")
    expected_claim_bytes = (
        json.dumps(claim, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    expected_claim_sha256 = hashlib.sha256(expected_claim_bytes).hexdigest()
    claim_installed = False
    stage = "single_use_claim_write"

    def set_stage(value: str) -> None:
        nonlocal stage
        stage = value

    try:
        _write_immutable_json(claim_path, claim)
        stage = "single_use_claim_hash"
        claim_evidence = _artifact_evidence(claim_path)
        if claim_evidence is None:  # pragma: no cover - writer/path race guard.
            raise FileNotFoundError("immutable v7 claim disappeared after installation")
        claim_sha256 = str(claim_evidence["sha256"])
        if claim_sha256 != expected_claim_sha256 or not _claim_is_owned(
            claim_path,
            run_id=run_id,
            ownership_nonce=ownership_nonce,
            expected_sha256=expected_claim_sha256,
        ):
            raise RuntimeError("installed v7 claim does not belong to this execution")
        claim_installed = True
        stage = "claimed_execution"
        summary = execute(set_stage, claim_sha256)
        stage = "completed_terminal_outcome_write"
        completed = _terminal_outcome_payload(
            status="completed",
            stage="all_required_evidence_written",
            run_id=run_id,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            claim_ownership_nonce=ownership_nonce,
            claim_path=claim_path,
            full_report_path=full_report_path,
            ledger_path=ledger_path,
            summary_path=summary_path,
            error=None,
        )
        _write_immutable_json(outcome_path, completed)
        return summary
    except BaseException as error:
        # A writer can fail after its atomic hard-link succeeded (for example,
        # during chmod/fsync).  In that case the complete terminal file already
        # wins and must never be replaced by a second outcome.
        owns_claim = claim_installed or _claim_is_owned(
            claim_path,
            run_id=run_id,
            ownership_nonce=ownership_nonce,
            expected_sha256=expected_claim_sha256,
        )
        if owns_claim and not outcome_path.exists():
            aborted = _terminal_outcome_payload(
                status="aborted",
                stage=stage,
                run_id=run_id,
                manifest_path=manifest_path,
                manifest_sha256=manifest_sha256,
                claim_ownership_nonce=ownership_nonce,
                claim_path=claim_path,
                full_report_path=full_report_path,
                ledger_path=ledger_path,
                summary_path=summary_path,
                error=error,
            )
            try:
                _write_immutable_json(outcome_path, aborted)
            except BaseException as terminal_error:
                if not outcome_path.is_file():
                    raise terminal_error from error
        raise


def _run_id() -> str:
    return "barn-predictive-shield-v7-dev-" + datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )


def _validated_run_id(value: str) -> str:
    if not _SAFE_RUN_ID.fullmatch(value):
        raise ValueError(
            "run_id must contain only letters, numbers, '.', '_' or '-' and be at most 128 chars"
        )
    return value


def _calibrated_config_from_protocol(protocol: Mapping[str, Any]) -> Any:
    from .barn_ros2_adapter import (
        BARN_ROS2_LIDAR_CALIBRATION,
        BARN_ROS2_LIDAR_RANGE_RESOLUTION_M,
    )
    from .barn_sensor_faithful import CALIBRATED_POLICY_INPUTS, CalibratedBarnConfig

    sensor = _require_mapping(protocol.get("sensor_contract"), "sensor contract")
    dynamics = _require_mapping(protocol.get("dynamics_contract"), "dynamics contract")
    trace = _require_mapping(protocol.get("diagnostic_trace_contract"), "trace contract")
    config = CalibratedBarnConfig(
        dt_s=float(dynamics["control_period_s"]),
        timeout_s=float(dynamics["timeout_s"]),
        success_radius_m=float(dynamics["success_radius_m"]),
        robot_radius_m=float(dynamics["robot_radius_m"]),
        max_forward_speed_mps=float(dynamics["maximum_forward_speed_mps"]),
        max_reverse_speed_mps=float(dynamics["maximum_reverse_speed_mps"]),
        max_yaw_rate_rps=float(dynamics["maximum_yaw_rate_rps"]),
        start_heading_rad=float(dynamics["initial_heading_rad"]),
        trial_start_translation_m=float(dynamics["trial_start_translation_m"]),
        startup_timeout_s=float(dynamics["startup_timeout_s"]),
        lidar_ray_count=int(sensor["rays"]),
        lidar_range_min_m=float(sensor["range_min_m"]),
        lidar_range_max_m=float(sensor["range_max_m"]),
        lidar_forward_m=float(sensor["base_to_lidar_forward_m"]),
        odometry_lag_s=float(sensor["scan_odometry_skew_s"]),
        sensor_stamp_origin_s=float(sensor["sensor_stamp_origin_s"]),
        max_sensor_skew_s=float(sensor["maximum_accepted_sensor_skew_s"]),
        trace_stride_steps=int(trace["stride_steps"]),
        trace_max_samples=int(trace["maximum_samples_per_episode"]),
    )
    calibration = BARN_ROS2_LIDAR_CALIBRATION
    exact_contract = {
        "field_of_view_rad": float(sensor["field_of_view_rad"]),
        "base_to_lidar_left_m": float(sensor["base_to_lidar_left_m"]),
        "base_to_lidar_yaw_rad": float(sensor["base_to_lidar_yaw_rad"]),
        "self_mask_radius_m": float(sensor["self_mask_radius_m"]),
        "self_mask_margin_m": float(sensor["self_mask_margin_m"]),
        "range_resolution_m": float(sensor["range_resolution_m"]),
    }
    expected_contract = {
        "field_of_view_rad": 2.0 * math.pi,
        "base_to_lidar_left_m": calibration.lidar_left_m,
        "base_to_lidar_yaw_rad": calibration.lidar_yaw_rad,
        "self_mask_radius_m": calibration.self_masks[0].radius_m,
        "self_mask_margin_m": calibration.self_masks[0].measurement_margin_m,
        "range_resolution_m": BARN_ROS2_LIDAR_RANGE_RESOLUTION_M,
    }
    if any(
        not math.isclose(exact_contract[name], expected, rel_tol=0.0, abs_tol=1e-12)
        for name, expected in expected_contract.items()
    ):
        raise ValueError("frozen sensor contract differs from the calibrated ROS adapter")
    if tuple(protocol.get("policy_inputs", ())) != CALIBRATED_POLICY_INPUTS:
        raise ValueError("frozen policy input contract differs from the calibrated harness")
    if dynamics.get("actuation") != "ideal_no_slip_unicycle_with_swept_collision":
        raise ValueError("unexpected frozen v7 actuation contract")
    if dynamics.get(
        "scoring_clock"
    ) != "interpolated_first_0p1m_translation_within_control_tick" or dynamics.get(
        "startup_failure_semantics"
    ) != (
        "non-official bounded liveness guard after 10s; the official scorer can wait "
        "indefinitely below 0.1m"
    ):
        raise ValueError("unexpected frozen v7 scoring-clock contract")
    if dynamics.get("policy_stop_semantics") != "latch_zero_until_evaluator_timeout":
        raise ValueError("unexpected frozen v7 policy-stop semantics")
    if int(trace["long_shield_stall_steps"]) != int(PROMOTION_GATE["long_shield_stall_steps"]):
        raise ValueError("trace and promotion-gate stall thresholds differ")
    return config


def run_development(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    results_root: Path = DEFAULT_RESULTS_ROOT,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Execute the reference and challenger exactly once on frozen development."""

    refuse_v7_execution()
    manifest_path = manifest_path.expanduser().resolve()
    if manifest_path != DEFAULT_MANIFEST.resolve():
        raise ValueError("v7 one-shot execution accepts only the canonical manifest path")
    results_root = results_root.expanduser().resolve()
    canonical_results_root = DEFAULT_RESULTS_ROOT.expanduser().resolve()
    if results_root != canonical_results_root:
        raise ValueError("v7 one-shot execution accepts only the canonical results root")

    # Imported lazily so manifest/gate unit tests can inspect this module while
    # the separate calibrated-native harness is being developed.
    from .barn_sensor_faithful import (
        calibrated_experimental_config_spec,
        calibrated_reference_config_spec,
        run_sensor_faithful_suite,
    )

    manifest, manifest_sha256, assets_root = verify_manifest(manifest_path)
    protocol = _require_mapping(manifest["protocol_frozen_before_development"], "protocol")
    identifier = _validated_run_id(run_id or _run_id())
    full_report_path = results_root / "runs" / f"{identifier}.json"
    summary_path = results_root / f"{identifier}-summary.json"
    ledger_path = results_root / "ledger" / "runs" / f"{identifier}.json"
    claim_path = results_root / "claims" / f"{CORPUS_ID}.json"
    outcome_path = results_root / "terminal-outcomes" / f"{CORPUS_ID}.json"

    reference_spec = calibrated_reference_config_spec(
        REFERENCE_CONFIG,
        reference_id="barn-predictive-shield-v7-reference-stop",
        description="Exact calibrated world-0 0.8 m full-stop reference",
    )
    candidate_spec = calibrated_experimental_config_spec(
        CHALLENGER_CONFIG,
        experiment_id="barn-predictive-shield-v7-candidate-projected-cap",
        description="One-factor 0.8 m projected-closing-speed-cap challenger",
    )
    calibrated_config = _calibrated_config_from_protocol(protocol)
    gate_expected_contract = _build_gate_expected_contract(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        calibrated_config=calibrated_config,
        reference_policy=reference_spec.report_metadata(),
        candidate_policy=candidate_spec.report_metadata(),
    )
    gate_expected_contract_sha256 = _canonical_sha256(gate_expected_contract)
    common = {
        "assets_root": assets_root,
        "world_indices": DEVELOPMENT_WORLD_IDS,
        "trials": int(protocol["trials_per_world"]),
        "suite_seed": int(protocol["suite_seed"]),
        "workers": int(protocol["episode_workers"]),
        "config": calibrated_config,
        "generated_corpus": True,
        "asset_manifest_sha256": manifest_sha256,
        "long_shield_stall_steps": int(PROMOTION_GATE["long_shield_stall_steps"]),
    }

    def reverify_frozen_inputs() -> None:
        _, current_sha256, current_assets_root = verify_manifest(manifest_path)
        if current_sha256 != manifest_sha256 or current_assets_root != assets_root:
            raise ValueError("canonical v7 manifest changed during execution")

    reverify_frozen_inputs()
    claim = {
        "schema_version": 1,
        "run_id": identifier,
        "ownership_nonce": uuid.uuid4().hex,
        "claimed_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "single-use predictive-shield-v7 development execution claim",
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": manifest_sha256,
        "world_ids": list(DEVELOPMENT_WORLD_IDS),
        "reference_config_sha256": reference_spec.config_sha256,
        "candidate_config_sha256": candidate_spec.config_sha256,
        "calibrated_config": asdict(calibrated_config),
        "gate_expected_contract_sha256": gate_expected_contract_sha256,
        "sealed_confirmation_generated": False,
        "sealed_confirmation_opened": False,
        "sealed_confirmation_evaluated": False,
    }

    def execute_claimed(set_stage: Callable[[str], None], claim_sha256: str) -> dict[str, Any]:
        set_stage("reference_execution")
        reference = run_sensor_faithful_suite(policy_spec=reference_spec, **common)
        set_stage("post_reference_input_verification")
        reverify_frozen_inputs()
        set_stage("candidate_execution")
        candidate = run_sensor_faithful_suite(
            policy_spec=candidate_spec,
            allow_experimental=True,
            **common,
        )
        set_stage("post_candidate_input_verification")
        reverify_frozen_inputs()
        set_stage("comparison")
        comparison = compare_barn_reports(reference, candidate)
        paired = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "evaluation_kind": COMPARISON_KIND,
            "official_gazebo_score": False,
            "baseline": reference,
            "candidate": candidate,
            "comparison": comparison,
        }
        set_stage("gate_evaluation")
        gates, gate_diagnostics = evaluate_gate(
            paired,
            expected_contract=gate_expected_contract,
        )
        passed = bool(gate_diagnostics["all_conditions_passed"])
        set_stage("report_assembly")
        result: dict[str, Any] = {
            "schema_version": 1,
            "run_id": identifier,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "evaluation_kind": EVALUATION_KIND,
            "comparison_kind": COMPARISON_KIND,
            "official_gazebo_score": False,
            "leaderboard_claim": False,
            "corpus": {
                "id": CORPUS_ID,
                "manifest_path": str(manifest_path.resolve()),
                "manifest_sha256": manifest_sha256,
                "single_use_claim_path": str(claim_path.resolve()),
                "single_use_claim_sha256": claim_sha256,
                "world_ids": list(DEVELOPMENT_WORLD_IDS),
                "sealed_confirmation_generated": False,
                "sealed_confirmation_opened": False,
                "sealed_confirmation_evaluated": False,
            },
            "one_factor_preflight": manifest["one_factor_preflight"],
            "source_roles": manifest["benchmark_scope"]["source_roles"],
            "frozen_promotion_gate": PROMOTION_GATE,
            "gate_expected_contract": gate_expected_contract,
            "gate_expected_contract_sha256": gate_expected_contract_sha256,
            "gate_results": gates,
            "gate_diagnostics": gate_diagnostics,
            "decision": {
                "selected_for_single_sealed_confirmation": passed,
                "confirmation_execution_implemented": False,
                "confirmation_command_authorized": False,
                "root_authorization_required": True,
                "deployment_enabled": False,
                "reason": (
                    "All development gates passed; a separately reviewed one-shot confirmation "
                    "is still required before any promotion."
                    if passed
                    else "One or more predeclared gates failed; confirmation remains "
                    "ungenerated, unopened, and unauthorized."
                ),
            },
            "paired_report": paired,
        }
        set_stage("report_write")
        _write_immutable_json(full_report_path, result)

        reference_aggregate = reference["aggregate"]
        candidate_aggregate = candidate["aggregate"]
        set_stage("ledger_write")
        ledger = record_evaluation_run(
            benchmark_id=EVALUATION_KIND,
            benchmark_source=BARN_SOURCE,
            benchmark_source_commit=BARN_SOURCE_COMMIT,
            change_description=(
                "Paired exact calibrated 0.8 m full-stop reference versus the one-factor "
                "projected-closing-speed-cap challenger on a fresh frozen sensor-faithful "
                "corpus."
            ),
            aggregate_metrics={
                "reference": reference_aggregate,
                "candidate": candidate_aggregate,
                "paired_outcomes": comparison["paired_outcomes"],
                "candidate_minus_reference": comparison["candidate_minus_baseline"],
                "promotion_gate": gates,
                "gate_diagnostics": gate_diagnostics,
                "decision": result["decision"],
                "corpus_manifest_sha256": manifest_sha256,
                "source_roles": result["source_roles"],
            },
            report_path=full_report_path,
            ledger_dir=results_root / "ledger",
            run_id=identifier,
            agent_id=candidate_spec.agent_id,
            adapter_id=candidate_spec.adapter_id,
            adapter_hash=candidate_spec.implementation_sha256,
            config_id=candidate_spec.config_id,
            config_hash=candidate_spec.config_sha256,
            model_id=candidate_spec.model_id,
            model_hash=candidate_spec.model_artifact_sha256,
        )
        if ledger.record_path.resolve() != ledger_path.resolve():
            raise ValueError("ledger writer returned a non-canonical v7 record path")
        set_stage("summary_assembly")
        summary = {
            "schema_version": 1,
            "run_id": identifier,
            "timestamp_utc": ledger.record["timestamp_utc"],
            "evaluation_kind": EVALUATION_KIND,
            "official_gazebo_score": False,
            "corpus_id": CORPUS_ID,
            "corpus_manifest_sha256": manifest_sha256,
            "source_roles": result["source_roles"],
            "single_use_claim_path": str(claim_path.resolve()),
            "single_use_claim_sha256": claim_sha256,
            "development_world_count": len(DEVELOPMENT_WORLD_IDS),
            "sealed_confirmation_generated": False,
            "sealed_confirmation_opened": False,
            "sealed_confirmation_evaluated": False,
            "reference": reference_aggregate,
            "candidate": candidate_aggregate,
            "paired": {
                "outcomes": comparison["paired_outcomes"],
                "candidate_minus_reference": comparison["candidate_minus_baseline"],
            },
            "promotion_gate": gates,
            "gate_diagnostics": gate_diagnostics,
            "decision": result["decision"],
            "full_report": ledger.record["report"],
            "ledger_record_path": str(ledger.record_path),
            "limitations": [
                "Generated calibrated-sensor CPU proxy; not official Gazebo BARN or a rank.",
                "Ideal unicycle actuation omits Gazebo/Go2 dynamics and LiDAR noise.",
                "Production defaults and Unitree behavior remain unchanged.",
                "No earlier or v7 confirmation geometry was generated, opened, or evaluated.",
            ],
        }
        set_stage("summary_write")
        _write_immutable_json(summary_path, summary)
        return summary

    return _run_single_use_claimed_execution(
        canonical_results_root=canonical_results_root,
        claim_path=claim_path,
        outcome_path=outcome_path,
        full_report_path=full_report_path,
        ledger_path=ledger_path,
        summary_path=summary_path,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        run_id=identifier,
        claim=claim,
        execute=execute_claimed,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute-development",
        action="store_true",
        help="required acknowledgement for the one-shot frozen development run",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    if not args.execute_development:
        parser.error("development execution requires --execute-development")
    summary = run_development(
        manifest_path=args.manifest,
        results_root=args.results_root,
        run_id=args.run_id,
    )
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "COMPARISON_KIND",
    "EVALUATION_KIND",
    "causal_pair_diagnostics",
    "evaluate_gate",
    "run_development",
    "verify_manifest",
]
