from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from evals.external import generate_sampled_predictive_tracker_v9_training as corpus

_GENERATOR_INPUTS = {
    "fixture-generator.py": {
        "sha256": hashlib.sha256(b"fixture generator\n").hexdigest(),
        "size_bytes": len(b"fixture generator\n"),
    }
}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _ids_sha256(values: tuple[int, ...]) -> str:
    encoded = json.dumps(
        list(values),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return _sha256(encoded)


def _corpus_sha256(episodes: list[dict[str, Any]]) -> str:
    encoded = json.dumps(episodes, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(encoded)


def _write_json(path: Path, value: object, *, immutable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not path.is_symlink():
        path.chmod(0o644)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if immutable:
        path.chmod(0o444)


def _freeze_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in directories:
        path.chmod(0o555)
    root.chmod(0o555)


def _asset_relative(kind: str, world_id: int) -> Path:
    if kind == "world":
        return Path("world_files") / f"world_{world_id}.world"
    return Path(f"{kind}_files") / f"{kind}_{world_id}.npy"


@dataclass(slots=True)
class _SyntheticCorpus:
    workspace: Path
    assets: Path
    manifest: Path
    freeze: Path
    payload: dict[str, Any]


def _synthetic_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _SyntheticCorpus:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    freeze = workspace / "evals/external/experiments/v9/CANDIDATE_FREEZE.json"
    _write_json(freeze, copy.deepcopy(corpus._EXPECTED_CANDIDATE_FREEZE))
    monkeypatch.setattr(corpus, "REPO_ROOT", workspace)
    monkeypatch.setattr(corpus, "CANDIDATE_FREEZE_PATH", freeze)
    monkeypatch.setattr(
        corpus,
        "_generator_inputs",
        lambda _root: copy.deepcopy(_GENERATOR_INPUTS),
    )

    assets = workspace / "generated/training/test_data"
    assets.mkdir(parents=True)
    for directory in (
        "cspace_files",
        "grid_files",
        "map_files",
        "metrics_files",
        "norm_metrics_files",
        "path_files",
        "world_files",
    ):
        (assets / directory).mkdir()
    episodes: list[dict[str, Any]] = []
    accepted_lines: list[str] = []
    kinds = ("world", "path", "grid", "cspace", "metrics")
    for offset, world_id in enumerate(corpus.TRAINING_WORLD_IDS):
        attempt = offset % 3 + 1
        seed = corpus.training_seed(world_id, attempt)
        fill_percent, smooth_iterations = corpus.training_parameters(world_id)
        files: dict[str, dict[str, Any]] = {}
        for kind in kinds:
            relative = _asset_relative(kind, world_id)
            output = assets / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            content = f"{kind}:{world_id}\n".encode()
            output.write_bytes(content)
            files[kind] = {
                "path": relative.as_posix(),
                "sha256": _sha256(content),
                "size_bytes": len(content),
            }
        episodes.append(
            {
                "corpus_episode_id": f"{corpus.CORPUS_ID}/training/{world_id}",
                "world_id": world_id,
                "generator_seed": seed,
                "accepted_attempt": attempt,
                "fill_percent": fill_percent,
                "smooth_iterations": smooth_iterations,
                "rows": 30,
                "columns": 30,
                "files": files,
            }
        )
        accepted_lines.append(
            f"accepted world={world_id} seed={seed} attempt={attempt} "
            f"fill={fill_percent:.2f} smooth={smooth_iterations}"
        )
    generation_log = ("\n".join(accepted_lines) + "\n").encode()
    (assets / "generation.log").write_bytes(generation_log)
    _freeze_tree(assets)

    expected_freeze = corpus._EXPECTED_CANDIDATE_FREEZE
    payload: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": corpus.MANIFEST_ID,
        "corpus_id": corpus.CORPUS_ID,
        "created_at": "2026-08-03T00:00:00Z",
        "benchmark_scope": {
            "evaluation_kind": "barn-native-headless-v9-training-non-official",
            "official_score": False,
            "leaderboard_claim": False,
            "promotion_evidence_eligible": False,
            "policy_runs_rerunnable": True,
            "source_generator": corpus.GENERATOR_SOURCE,
            "source_generator_commit": corpus.GENERATOR_COMMIT,
            "generator_inputs": copy.deepcopy(_GENERATOR_INPUTS),
        },
        "identity_partition": {
            "training_world_ids": list(corpus.TRAINING_WORLD_IDS),
            "training_world_ids_sha256": _ids_sha256(corpus.TRAINING_WORLD_IDS),
            "single_use_development_world_ids_sha256": _ids_sha256(corpus.DEVELOPMENT_WORLD_IDS),
            "unopened_holdout_world_ids_sha256": _ids_sha256(corpus.HOLDOUT_WORLD_IDS),
            "all_v9_world_ids_retired_after_experiment": list(range(5000, 5150)),
            "pairwise_disjoint": True,
        },
        "candidate_freeze": {
            "path": freeze.relative_to(workspace).as_posix(),
            "sha256": _sha256(freeze.read_bytes()),
            "package_sha256": expected_freeze["candidate"]["package_sha256"],
            "manifest_sha256": expected_freeze["candidate"]["manifest_sha256"],
        },
        "training_corpus": {
            "assets_root": str(assets),
            "world_count": 100,
            "corpus_sha256": _corpus_sha256(episodes),
            "generation_log_sha256": _sha256(generation_log),
            "episodes": episodes,
        },
        "development_or_holdout_materialized": False,
    }
    manifest = workspace / "evals/external/training/v9/split.json"
    _write_json(manifest, payload, immutable=True)
    return _SyntheticCorpus(workspace, assets, manifest, freeze, payload)


def _rewrite_manifest(fixture: _SyntheticCorpus, payload: dict[str, Any]) -> None:
    _write_json(fixture.manifest, payload, immutable=True)


def test_identity_partition_seed_and_parameter_recipe_is_exact() -> None:
    assert corpus.TRAINING_WORLD_IDS == tuple(range(5000, 5100))
    assert corpus.DEVELOPMENT_WORLD_IDS == tuple(range(5100, 5130))
    assert corpus.HOLDOUT_WORLD_IDS == tuple(range(5130, 5150))
    assert not (
        set(corpus.TRAINING_WORLD_IDS) & set(corpus.DEVELOPMENT_WORLD_IDS)
        or set(corpus.TRAINING_WORLD_IDS) & set(corpus.HOLDOUT_WORLD_IDS)
        or set(corpus.DEVELOPMENT_WORLD_IDS) & set(corpus.HOLDOUT_WORLD_IDS)
    )
    assert _ids_sha256(corpus.TRAINING_WORLD_IDS) == (
        "61b8b2769406e8f4e030fdd0a6c221f0023f2d5a1d9fe871c5bb39dcaaf2ea3e"
    )
    assert _ids_sha256(corpus.DEVELOPMENT_WORLD_IDS) == (
        "ae25a4e10bb1527416b045a73e5e2740f5dbd8370fd57be4f11ff748e59a0b7a"
    )
    assert _ids_sha256(corpus.HOLDOUT_WORLD_IDS) == (
        "7834ee138d61e040abd91fe560642be49dfcea86f7b7a69cd13dede3250f85ae"
    )
    assert corpus.training_seed(5000, 1) == 556403905
    assert corpus.training_seed(5000, 2) == 1254588607
    assert corpus.training_seed(5001, 1) == 1876869805
    assert corpus.training_seed(5099, 10_000) == 1982895061
    assert [corpus.training_parameters(world_id) for world_id in range(5000, 5013)] == [
        (0.15, 2),
        (0.15, 3),
        (0.15, 4),
        (0.20, 2),
        (0.20, 3),
        (0.20, 4),
        (0.25, 2),
        (0.25, 3),
        (0.25, 4),
        (0.30, 2),
        (0.30, 3),
        (0.30, 4),
        (0.15, 2),
    ]
    for world_id, attempt in ((4999, 1), (5100, 1), (5000, 0), (5000, 10_001)):
        with pytest.raises(ValueError, match="outside the frozen"):
            corpus.training_seed(world_id, attempt)


def test_candidate_freeze_requires_the_complete_exact_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze = tmp_path / "CANDIDATE_FREEZE.json"
    monkeypatch.setattr(corpus, "CANDIDATE_FREEZE_PATH", freeze)
    exact = copy.deepcopy(corpus._EXPECTED_CANDIDATE_FREEZE)
    _write_json(freeze, exact)
    assert corpus._strict_candidate_freeze() == exact

    mutations = []
    changed_candidate = copy.deepcopy(exact)
    changed_candidate["candidate"]["package_sha256"] = "0" * 64
    mutations.append(changed_candidate)
    changed_authority = copy.deepcopy(exact)
    changed_authority["development_execution_authorized"] = True
    mutations.append(changed_authority)
    extra_field = copy.deepcopy(exact)
    extra_field["unreviewed"] = True
    mutations.append(extra_field)
    for mutation in mutations:
        _write_json(freeze, mutation)
        with pytest.raises(ValueError, match="identity or authorization"):
            corpus._strict_candidate_freeze()

    real = tmp_path / "real-freeze.json"
    _write_json(real, exact)
    alias = tmp_path / "freeze-alias.json"
    alias.symlink_to(real)
    monkeypatch.setattr(corpus, "CANDIDATE_FREEZE_PATH", alias)
    with pytest.raises(ValueError, match="symbolic link"):
        corpus._strict_candidate_freeze()


def test_synthetic_immutable_100_world_manifest_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _synthetic_corpus(tmp_path, monkeypatch)

    report = corpus.verify_training_corpus(fixture.manifest)

    assert report == {
        "corpus_id": corpus.CORPUS_ID,
        "corpus_sha256": fixture.payload["training_corpus"]["corpus_sha256"],
        "manifest_sha256": _sha256(fixture.manifest.read_bytes()),
        "promotion_evidence_eligible": False,
        "world_count": 100,
    }
    assert fixture.assets.stat().st_mode & 0o222 == 0
    assert fixture.manifest.stat().st_mode & 0o222 == 0
    assert len([path for path in fixture.assets.rglob("*") if path.is_file()]) == 501


def test_manifest_and_episode_tampering_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _synthetic_corpus(tmp_path, monkeypatch)
    mutations: list[tuple[dict[str, Any], str]] = []

    partition = copy.deepcopy(fixture.payload)
    partition["identity_partition"]["unopened_holdout_world_ids_sha256"] = "0" * 64
    mutations.append((partition, "identity partition"))
    frozen_candidate = copy.deepcopy(fixture.payload)
    frozen_candidate["candidate_freeze"]["manifest_sha256"] = "0" * 64
    mutations.append((frozen_candidate, "candidate freeze"))
    episode = copy.deepcopy(fixture.payload)
    episode["training_corpus"]["episodes"][0]["generator_seed"] += 1
    episode["training_corpus"]["corpus_sha256"] = _corpus_sha256(
        episode["training_corpus"]["episodes"]
    )
    mutations.append((episode, "generator seed"))

    for payload, message in mutations:
        _rewrite_manifest(fixture, payload)
        with pytest.raises(ValueError, match=message):
            corpus.verify_training_corpus(fixture.manifest)


def test_file_tamper_symlink_and_hardlink_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _synthetic_corpus(tmp_path, monkeypatch)
    target = fixture.assets / "world_files/world_5000.world"
    original = target.read_bytes()

    target.chmod(0o644)
    target.write_bytes(b"tampered\n")
    target.chmod(0o444)
    with pytest.raises(ValueError, match="asset digest changed"):
        corpus.verify_training_corpus(fixture.manifest)

    target.chmod(0o644)
    target.write_bytes(original)
    target.chmod(0o444)
    parent = target.parent
    parent.chmod(0o755)
    target.unlink()
    backing = fixture.workspace / "symlink-backing.world"
    backing.write_bytes(original)
    target.symlink_to(backing)
    parent.chmod(0o555)
    with pytest.raises(ValueError, match="symbolic link"):
        corpus.verify_training_corpus(fixture.manifest)

    parent.chmod(0o755)
    target.unlink()
    target.write_bytes(original)
    target.chmod(0o444)
    alias = parent / "hardlink-alias.world"
    os.link(target, alias)
    parent.chmod(0o555)
    with pytest.raises(ValueError, match="hard-linked"):
        corpus.verify_training_corpus(fixture.manifest)


def test_generation_refuses_to_overwrite_either_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    freeze = workspace / "CANDIDATE_FREEZE.json"
    _write_json(freeze, copy.deepcopy(corpus._EXPECTED_CANDIDATE_FREEZE))
    monkeypatch.setattr(corpus, "REPO_ROOT", workspace)
    monkeypatch.setattr(corpus, "CANDIDATE_FREEZE_PATH", freeze)

    def generation_must_not_start(_root: Path) -> None:
        raise AssertionError("generator verification must not run on no-overwrite failure")

    monkeypatch.setattr(corpus, "_verify_generator", generation_must_not_start)
    assets = workspace / "assets"
    assets.mkdir()
    sentinel = assets / "foreign"
    sentinel.write_bytes(b"preserve assets\n")
    with pytest.raises(FileExistsError, match="refusing to replace"):
        corpus.generate_training_corpus(
            generator_root=workspace / "generator",
            assets_root=assets,
            manifest_path=workspace / "first-manifest.json",
        )
    assert sentinel.read_bytes() == b"preserve assets\n"

    manifest = workspace / "foreign-manifest.json"
    manifest.write_bytes(b"preserve manifest\n")
    with pytest.raises(FileExistsError, match="refusing to replace"):
        corpus.generate_training_corpus(
            generator_root=workspace / "generator",
            assets_root=workspace / "second-assets",
            manifest_path=manifest,
        )
    assert manifest.read_bytes() == b"preserve manifest\n"
    assert not (workspace / "second-assets").exists()
