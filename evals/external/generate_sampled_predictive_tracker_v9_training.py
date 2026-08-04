"""Generate Parcel V9's rerunnable, evidence-ineligible BARN training corpus.

World IDs 5000--5099 are reserved only for tracker tuning and scratch runs.
They may be evaluated repeatedly, can never support a promotion claim, and are
disjoint from the single-use V9 development and unopened holdout identities.
The pinned upstream BARN generator remains responsible for geometry, C-space,
reference A*, and difficulty artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .barn_policy_specs import REPO_ROOT
from .generate_safe_valley_v5_corpus import (
    GENERATOR_COMMIT,
    GENERATOR_SOURCE,
    _corpus_sha256,
    _generate_development_assets,
    _generator_inputs,
    _verify_generator,
    _write_exclusive_json,
)
from .ledger import sha256_file

CORPUS_ID = "barn-sampled-predictive-tracker-v9-training-20260803-100"
MANIFEST_ID = "barn-sampled-predictive-tracker-v9-training-split-v1"
SEED_NAMESPACE = "parcel-barn-sampled-predictive-tracker-v9-training-20260803"
TRAINING_WORLD_IDS = tuple(range(5000, 5100))
DEVELOPMENT_WORLD_IDS = tuple(range(5100, 5130))
HOLDOUT_WORLD_IDS = tuple(range(5130, 5150))
DEFAULT_GENERATOR_ROOT = REPO_ROOT / ".cache/external-evals/repos/barn_generator"
DEFAULT_ASSETS_ROOT = (
    REPO_ROOT
    / ".cache/external-evals/generated/barn_sampled_predictive_tracker_v9/training/test_data"
)
DEFAULT_MANIFEST = (
    REPO_ROOT / "evals/external/training/barn_sampled_predictive_tracker_v9/split.json"
)
EXPERIMENT_ROOT = REPO_ROOT / "evals/external/experiments/barn_sampled_predictive_tracker_v9"
CANDIDATE_FREEZE_PATH = EXPERIMENT_ROOT / "CANDIDATE_FREEZE.json"

_EXPECTED_FILE_KINDS = frozenset({"world", "path", "grid", "cspace", "metrics"})
_EPISODE_FIELD_NAMES = frozenset(
    {
        "accepted_attempt",
        "columns",
        "corpus_episode_id",
        "files",
        "fill_percent",
        "generator_seed",
        "rows",
        "smooth_iterations",
        "world_id",
    }
)
_FILE_FIELD_NAMES = frozenset({"path", "sha256", "size_bytes"})
_MANIFEST_FIELD_NAMES = frozenset(
    {
        "benchmark_scope",
        "candidate_freeze",
        "corpus_id",
        "created_at",
        "development_or_holdout_materialized",
        "identity_partition",
        "manifest_id",
        "schema_version",
        "training_corpus",
    }
)
_SCOPE_FIELD_NAMES = frozenset(
    {
        "evaluation_kind",
        "generator_inputs",
        "leaderboard_claim",
        "official_score",
        "policy_runs_rerunnable",
        "promotion_evidence_eligible",
        "source_generator",
        "source_generator_commit",
    }
)
_PARTITION_FIELD_NAMES = frozenset(
    {
        "all_v9_world_ids_retired_after_experiment",
        "pairwise_disjoint",
        "single_use_development_world_ids_sha256",
        "training_world_ids",
        "training_world_ids_sha256",
        "unopened_holdout_world_ids_sha256",
    }
)
_TRAINING_FIELD_NAMES = frozenset(
    {"assets_root", "corpus_sha256", "episodes", "generation_log_sha256", "world_count"}
)
_EXPECTED_ASSET_DIRECTORIES = frozenset(
    {
        "cspace_files",
        "grid_files",
        "map_files",
        "metrics_files",
        "norm_metrics_files",
        "path_files",
        "world_files",
    }
)
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
_EXPECTED_CANDIDATE_FREEZE: dict[str, Any] = {
    "candidate": {
        "controller_id": "parcel-directive-navigator-grid-v1-v9-sampled-predictive-tracker",
        "manifest_sha256": "540658cee91c2bdb058f54ab19b9838d731f49c7be4df6ef7332aaea631b8b08",
        "package_sha256": "c68bb69c247404d0deee28f26d8000200f73aeb336fb9bb0cafd0f0c3b510833",
    },
    "candidate_source_contract_sha256": (
        "72062cc73753efa6d290ab020b1f89e00269314ab2854b7a58bf946b8d0be87c"
    ),
    "deployment_enabled": False,
    "development_execution_authorized": False,
    "experimental": True,
    "freeze_id": "parcel-v9-sampled-predictive-tracker-candidate-freeze-v1",
    "frozen_before_canonical_materialization": True,
    "holdout_execution_authorized": False,
    "one_factor_delta": {
        "additions": ["src/parcel_robot/navigation/experimental_sampled_predictive_tracker.py"],
        "all_other_reference_payload_bytes_identical": True,
        "replacements": ["src/parcel_robot/navigation/grid_navigator.py"],
        "unchanged_reference_file_count": 116,
    },
    "reference": {
        "development_gate_passed": False,
        "deployment_enabled": False,
        "manifest_sha256": "d3bca126041d69afb5553ac29656a0152242c00f29a7b987803e9dc536914115",
        "package_sha256": "189ac31f0f6a461da9e10fad2ac21b2bc3a485a4d5245c517b1492b2a16eb7d9",
        "role": "experimental_control_only",
    },
    "schema_version": 1,
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_json_object(raw: bytes, description: str) -> dict[str, Any]:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{description} contains duplicate field {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"{description} contains non-finite value {value}")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{description} is not valid strict JSON") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{description} must contain an object")
    return value


def _ids_sha256(world_ids: Sequence[int]) -> str:
    encoded = json.dumps(
        list(world_ids),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return _sha256_bytes(encoded)


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _reject_symlink_components(path: Path) -> None:
    requested = _lexical_absolute(path)
    for component in (requested, *requested.parents):
        if os.path.lexists(component) and stat.S_ISLNK(os.lstat(component).st_mode):
            raise ValueError(f"V9 training path contains a symbolic link: {component}")


def _require_immutable_regular_file(path: Path, description: str) -> os.stat_result:
    _reject_symlink_components(path)
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        raise FileNotFoundError(f"{description} is missing: {path}") from None
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{description} must be a regular file")
    if metadata.st_nlink != 1:
        raise ValueError(f"{description} must not be hard-linked")
    if metadata.st_mode & _WRITE_BITS:
        raise ValueError(f"{description} must be immutable")
    return metadata


def _freeze_generated_tree(root: Path) -> None:
    """Make a generated scratch corpus immutable before publishing its manifest."""

    _reject_symlink_components(root)
    entries = list(root.rglob("*"))
    for path in entries:
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"generated V9 training tree contains a symbolic link: {path}")
        if stat.S_ISREG(metadata.st_mode):
            if metadata.st_nlink != 1:
                raise ValueError(f"generated V9 training file is hard-linked: {path}")
            path.chmod(0o444)
        elif not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"generated V9 training tree contains a special file: {path}")
    for path in sorted(
        (entry for entry in entries if entry.is_dir()),
        key=lambda value: len(value.parts),
        reverse=True,
    ):
        path.chmod(0o555)
    root.chmod(0o555)


def training_seed(world_id: int, attempt: int) -> int:
    if world_id not in TRAINING_WORLD_IDS or not 1 <= attempt <= 10_000:
        raise ValueError("training seed inputs are outside the frozen V9 scratch namespace")
    payload = f"{SEED_NAMESPACE}:{world_id}:{attempt}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & 0x7FFF_FFFF


def training_parameters(world_id: int) -> tuple[float, int]:
    if world_id not in TRAINING_WORLD_IDS:
        raise ValueError("training world_id must be in [5000, 5099]")
    offset = world_id - TRAINING_WORLD_IDS[0]
    fill_percent = (0.15, 0.20, 0.25, 0.30)[(offset // 3) % 4]
    smooth_iterations = (2, 3, 4)[offset % 3]
    return fill_percent, smooth_iterations


def _strict_candidate_freeze() -> dict[str, Any]:
    path = CANDIDATE_FREEZE_PATH
    _reject_symlink_components(path)
    if not path.is_file():
        raise FileNotFoundError("V9 candidate freeze is missing or unsafe")
    value = _strict_json_object(path.read_bytes(), "V9 candidate freeze")
    if value != _EXPECTED_CANDIDATE_FREEZE:
        raise ValueError("V9 candidate freeze identity or authorization state is invalid")
    return value


def _validate_identity_partition() -> None:
    training = set(TRAINING_WORLD_IDS)
    development = set(DEVELOPMENT_WORLD_IDS)
    holdout = set(HOLDOUT_WORLD_IDS)
    if len(training) != 100 or len(development) != 30 or len(holdout) != 20:
        raise AssertionError("V9 identity partition cardinality changed")
    if training & development or training & holdout or development & holdout:
        raise AssertionError("V9 training, development, and holdout identities overlap")
    if min(training) < 5000 or max(holdout) >= 5150:
        raise AssertionError("V9 identity partition escaped its retired namespace")


def _expected_asset_path(kind: str, world_id: int) -> Path:
    if kind == "world":
        return Path("world_files") / f"world_{world_id}.world"
    if kind in {"path", "grid", "cspace", "metrics"}:
        return Path(f"{kind}_files") / f"{kind}_{world_id}.npy"
    raise AssertionError(f"unexpected V9 training asset kind: {kind}")


def generate_training_corpus(
    *,
    generator_root: Path = DEFAULT_GENERATOR_ROOT,
    assets_root: Path = DEFAULT_ASSETS_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    """Generate the fixed scratch corpus once; policy runs over it are rerunnable."""

    _validate_identity_partition()
    candidate_freeze = _strict_candidate_freeze()
    generator = _lexical_absolute(generator_root)
    assets = _lexical_absolute(assets_root)
    manifest = _lexical_absolute(manifest_path)
    for requested in (generator, assets, manifest):
        _reject_symlink_components(requested)
    if assets.exists() or manifest.exists():
        raise FileExistsError("refusing to replace an existing V9 training corpus or manifest")
    if not assets.is_relative_to(REPO_ROOT.resolve()):
        raise ValueError("V9 training assets must remain inside the Parcel workspace")
    if not manifest.is_relative_to(REPO_ROOT.resolve()):
        raise ValueError("V9 training manifest must remain inside the Parcel workspace")
    _verify_generator(generator)
    generator_inputs = _generator_inputs(generator)
    episodes, generation_log_sha256 = _generate_development_assets(
        generator_root=generator,
        assets_root=assets,
        world_ids=TRAINING_WORLD_IDS,
        corpus_id=CORPUS_ID,
        temporary_prefix=".barn-v9-training-",
        seed_for=training_seed,
        parameters_for=training_parameters,
    )
    for episode in episodes:
        world_id = int(episode["world_id"])
        episode["corpus_episode_id"] = f"{CORPUS_ID}/training/{world_id}"
    _freeze_generated_tree(assets)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": MANIFEST_ID,
        "corpus_id": CORPUS_ID,
        "created_at": created_at,
        "benchmark_scope": {
            "evaluation_kind": "barn-native-headless-v9-training-non-official",
            "official_score": False,
            "leaderboard_claim": False,
            "promotion_evidence_eligible": False,
            "policy_runs_rerunnable": True,
            "source_generator": GENERATOR_SOURCE,
            "source_generator_commit": GENERATOR_COMMIT,
            "generator_inputs": generator_inputs,
        },
        "identity_partition": {
            "training_world_ids": list(TRAINING_WORLD_IDS),
            "training_world_ids_sha256": _ids_sha256(TRAINING_WORLD_IDS),
            "single_use_development_world_ids_sha256": _ids_sha256(DEVELOPMENT_WORLD_IDS),
            "unopened_holdout_world_ids_sha256": _ids_sha256(HOLDOUT_WORLD_IDS),
            "all_v9_world_ids_retired_after_experiment": list(range(5000, 5150)),
            "pairwise_disjoint": True,
        },
        "candidate_freeze": {
            "path": CANDIDATE_FREEZE_PATH.relative_to(REPO_ROOT).as_posix(),
            "sha256": sha256_file(CANDIDATE_FREEZE_PATH),
            "package_sha256": candidate_freeze["candidate"]["package_sha256"],
            "manifest_sha256": candidate_freeze["candidate"]["manifest_sha256"],
        },
        "training_corpus": {
            "assets_root": str(assets),
            "world_count": len(episodes),
            "corpus_sha256": _corpus_sha256(episodes),
            "generation_log_sha256": generation_log_sha256,
            "episodes": episodes,
        },
        "development_or_holdout_materialized": False,
    }
    _write_exclusive_json(manifest, payload)
    manifest.chmod(0o444)
    return payload


def verify_training_corpus(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Rehash the complete training inventory and reject aliases or membership drift."""

    _validate_identity_partition()
    path = _lexical_absolute(manifest_path)
    _require_immutable_regular_file(path, "V9 training manifest")
    payload = _strict_json_object(path.read_bytes(), "V9 training manifest")
    if (
        set(payload) != _MANIFEST_FIELD_NAMES
        or payload.get("schema_version") != 1
        or payload.get("manifest_id") != MANIFEST_ID
        or payload.get("corpus_id") != CORPUS_ID
        or not isinstance(payload.get("created_at"), str)
        or not str(payload["created_at"]).endswith("Z")
        or payload.get("development_or_holdout_materialized") is not False
    ):
        raise ValueError("V9 training manifest identity is invalid")
    scope = payload.get("benchmark_scope")
    expected_scope_flags = {
        "official_score": False,
        "leaderboard_claim": False,
        "promotion_evidence_eligible": False,
        "policy_runs_rerunnable": True,
    }
    if (
        not isinstance(scope, Mapping)
        or set(scope) != _SCOPE_FIELD_NAMES
        or scope.get("evaluation_kind") != "barn-native-headless-v9-training-non-official"
        or scope.get("source_generator") != GENERATOR_SOURCE
        or scope.get("source_generator_commit") != GENERATOR_COMMIT
        or scope.get("generator_inputs") != _generator_inputs(DEFAULT_GENERATOR_ROOT)
        or any(scope.get(name) is not expected for name, expected in expected_scope_flags.items())
    ):
        raise ValueError("V9 training-only benchmark scope changed")
    partition = payload.get("identity_partition")
    if (
        not isinstance(partition, Mapping)
        or set(partition) != _PARTITION_FIELD_NAMES
        or partition.get("training_world_ids") != list(TRAINING_WORLD_IDS)
        or partition.get("training_world_ids_sha256") != _ids_sha256(TRAINING_WORLD_IDS)
        or partition.get("single_use_development_world_ids_sha256")
        != _ids_sha256(DEVELOPMENT_WORLD_IDS)
        or partition.get("unopened_holdout_world_ids_sha256") != _ids_sha256(HOLDOUT_WORLD_IDS)
        or partition.get("all_v9_world_ids_retired_after_experiment") != list(range(5000, 5150))
        or partition.get("pairwise_disjoint") is not True
    ):
        raise ValueError("V9 training identity partition changed")
    training = payload.get("training_corpus")
    if (
        not isinstance(training, Mapping)
        or set(training) != _TRAINING_FIELD_NAMES
        or training.get("world_count") != 100
    ):
        raise ValueError("V9 training corpus must contain exactly 100 worlds")
    episodes = training.get("episodes")
    if not isinstance(episodes, list) or len(episodes) != 100:
        raise ValueError("V9 training episode inventory is malformed")
    if [episode.get("world_id") for episode in episodes if isinstance(episode, Mapping)] != list(
        TRAINING_WORLD_IDS
    ):
        raise ValueError("V9 training episode order or membership changed")
    if [
        episode.get("corpus_episode_id") for episode in episodes if isinstance(episode, Mapping)
    ] != [f"{CORPUS_ID}/training/{world_id}" for world_id in TRAINING_WORLD_IDS]:
        raise ValueError("V9 training episode namespace changed")
    if training.get("corpus_sha256") != _corpus_sha256(episodes):
        raise ValueError("V9 training corpus digest changed")
    assets_value = training.get("assets_root")
    if not isinstance(assets_value, str) or not assets_value:
        raise ValueError("V9 training assets root is invalid")
    assets = _lexical_absolute(Path(assets_value))
    _reject_symlink_components(assets)
    if not assets.is_relative_to(REPO_ROOT.resolve()):
        raise ValueError("V9 training assets escaped the Parcel workspace")
    if not assets.is_dir():
        raise FileNotFoundError("V9 training assets root is missing or unsafe")
    if assets.stat().st_mode & _WRITE_BITS:
        raise ValueError("V9 training assets root must be immutable")
    expected_files = {"generation.log"}
    inventory_paths: set[str] = set()
    for episode in episodes:
        if not isinstance(episode, Mapping):
            raise TypeError("V9 training episode record is malformed")
        if set(episode) != _EPISODE_FIELD_NAMES:
            raise ValueError("V9 training episode field membership changed")
        world_id_value = episode["world_id"]
        if isinstance(world_id_value, bool) or not isinstance(world_id_value, int):
            raise TypeError("V9 training world_id must be an integer")
        world_id = world_id_value
        attempt = episode["accepted_attempt"]
        generator_seed = episode["generator_seed"]
        if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 10_000:
            raise ValueError("V9 training accepted attempt is invalid")
        if (
            isinstance(generator_seed, bool)
            or not isinstance(generator_seed, int)
            or generator_seed != training_seed(world_id, attempt)
        ):
            raise ValueError("V9 training generator seed changed")
        fill_percent, smooth_iterations = training_parameters(world_id)
        if (
            episode.get("fill_percent") != fill_percent
            or episode.get("smooth_iterations") != smooth_iterations
            or episode.get("rows") != 30
            or episode.get("columns") != 30
        ):
            raise ValueError("V9 training generation parameters changed")
        files = episode.get("files")
        if not isinstance(files, Mapping) or set(files) != _EXPECTED_FILE_KINDS:
            raise ValueError("V9 training episode file-kind membership changed")
        for kind, record in files.items():
            if not isinstance(record, Mapping) or set(record) != _FILE_FIELD_NAMES:
                raise TypeError("V9 training file record is malformed")
            if (
                isinstance(record.get("size_bytes"), bool)
                or not isinstance(record.get("size_bytes"), int)
                or int(record["size_bytes"]) < 0
            ):
                raise ValueError("V9 training file size is invalid")
            if not isinstance(record.get("sha256"), str) or len(str(record["sha256"])) != 64:
                raise ValueError("V9 training file digest is invalid")
            relative = Path(str(record.get("path")))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("V9 training file path is unsafe")
            if relative != _expected_asset_path(str(kind), world_id):
                raise ValueError("V9 training file path does not match its world and kind")
            if relative.as_posix() in inventory_paths:
                raise ValueError("V9 training file path is aliased by multiple records")
            inventory_paths.add(relative.as_posix())
            candidate = assets / relative
            metadata = _require_immutable_regular_file(candidate, f"V9 training asset {relative}")
            if metadata.st_size != record.get("size_bytes") or sha256_file(candidate) != record.get(
                "sha256"
            ):
                raise ValueError(f"V9 training asset digest changed: {relative}")
            expected_files.add(relative.as_posix())
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for candidate in assets.rglob("*"):
        metadata = os.lstat(candidate)
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("V9 training asset inventory contains a symbolic link")
        if stat.S_ISREG(metadata.st_mode):
            if metadata.st_nlink != 1 or metadata.st_mode & _WRITE_BITS:
                raise ValueError("V9 training asset inventory is mutable or hard-linked")
            actual_files.add(candidate.relative_to(assets).as_posix())
        elif stat.S_ISDIR(metadata.st_mode):
            if metadata.st_mode & _WRITE_BITS:
                raise ValueError("V9 training asset inventory contains a mutable directory")
            actual_directories.add(candidate.relative_to(assets).as_posix())
        else:
            raise ValueError("V9 training asset inventory contains a special file")
    if actual_files != expected_files:
        raise ValueError("V9 training asset membership changed")
    if actual_directories != _EXPECTED_ASSET_DIRECTORIES:
        raise ValueError("V9 training asset directory membership changed")
    _require_immutable_regular_file(assets / "generation.log", "V9 training generation log")
    if sha256_file(assets / "generation.log") != training.get("generation_log_sha256"):
        raise ValueError("V9 training generation log changed")
    accepted_lines = [
        line
        for line in (assets / "generation.log").read_text(encoding="utf-8").splitlines()
        if line.startswith("accepted world=")
    ]
    expected_accepted_lines = []
    for episode in episodes:
        expected_accepted_lines.append(
            f"accepted world={episode['world_id']} seed={episode['generator_seed']} "
            f"attempt={episode['accepted_attempt']} fill={episode['fill_percent']:.2f} "
            f"smooth={episode['smooth_iterations']}"
        )
    if accepted_lines != expected_accepted_lines:
        raise ValueError("V9 training generation log identity changed")
    candidate_freeze = _strict_candidate_freeze()
    freeze = payload.get("candidate_freeze")
    expected_freeze = {
        "path": CANDIDATE_FREEZE_PATH.relative_to(REPO_ROOT).as_posix(),
        "sha256": sha256_file(CANDIDATE_FREEZE_PATH),
        "package_sha256": candidate_freeze["candidate"]["package_sha256"],
        "manifest_sha256": candidate_freeze["candidate"]["manifest_sha256"],
    }
    if not isinstance(freeze, Mapping) or dict(freeze) != expected_freeze:
        raise ValueError("V9 training candidate freeze changed")
    return {
        "corpus_id": CORPUS_ID,
        "corpus_sha256": training["corpus_sha256"],
        "manifest_sha256": sha256_file(path),
        "promotion_evidence_eligible": False,
        "world_count": 100,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generator-root", type=Path, default=DEFAULT_GENERATOR_ROOT)
    parser.add_argument("--assets-root", type=Path, default=DEFAULT_ASSETS_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    result = generate_training_corpus(
        generator_root=args.generator_root,
        assets_root=args.assets_root,
        manifest_path=args.manifest,
    )
    print(
        json.dumps(
            {
                "corpus_id": result["corpus_id"],
                "corpus_sha256": result["training_corpus"]["corpus_sha256"],
                "manifest": str(args.manifest.resolve()),
                "promotion_evidence_eligible": False,
                "world_count": result["training_corpus"]["world_count"],
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
    "DEFAULT_MANIFEST",
    "DEVELOPMENT_WORLD_IDS",
    "HOLDOUT_WORLD_IDS",
    "MANIFEST_ID",
    "TRAINING_WORLD_IDS",
    "generate_training_corpus",
    "training_parameters",
    "training_seed",
    "verify_training_corpus",
]
