"""Generate and freeze the disjoint BARN-style safe-valley v5 corpus.

The exact pinned upstream generator is executed with Python-3 import shims for
its Python-2-only GUI/PGM modules.  Map generation, C-space construction,
reference A*, world writing, and difficulty calculations remain upstream code.
Development assets use namespaced IDs above the immutable public 0--299 range.
The confirmation seed recipe is frozen here but its assets are not generated or
opened during development.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import io
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import types
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .barn_policy_specs import PARCEL_POLICY_SOURCE_ROOT, REPO_ROOT, _source_tree_sha256
from .ledger import sha256_file

GENERATOR_COMMIT = "295ca5cc7b9b0ecea93013f0c49c5a1ca4352151"
GENERATOR_SOURCE = "https://github.com/dperille/jackal-map-creation.git"
CORPUS_ID = "barn-safe-valley-v5-generated-20260803-dev30-sealed20"
DEVELOPMENT_WORLD_IDS = tuple(range(1000, 1030))
SEALED_CONFIRMATION_WORLD_IDS = tuple(range(1030, 1050))
SEED_NAMESPACE = "parcel-safe-valley-v5-generated-corpus-20260803"
DEFAULT_GENERATOR_ROOT = REPO_ROOT / ".cache" / "external-evals" / "repos" / "barn_generator"
DEFAULT_ASSETS_ROOT = (
    REPO_ROOT
    / ".cache"
    / "external-evals"
    / "generated"
    / "barn_safe_valley_v5"
    / "development"
    / "test_data"
)
DEFAULT_MANIFEST = (
    REPO_ROOT / "evals" / "external" / "development" / "barn_safe_valley_v5" / "split.json"
)

REFERENCE_CONFIG = (
    REPO_ROOT / "configs" / "navigation" / "experiments" / "barn_grid_frontier_cached_v3.yaml"
)
REFERENCE_MODEL = REPO_ROOT / "configs" / "navigation" / "models" / "grid_frontier_cached_v3.yaml"
CHALLENGER_CONFIG = (
    REPO_ROOT / "configs" / "navigation" / "experiments" / "barn_grid_safe_valley_v5.yaml"
)
CHALLENGER_MODEL = REPO_ROOT / "configs" / "navigation" / "models" / "grid_safe_valley_v5.yaml"

PROMOTION_GATE: dict[str, Any] = {
    "reference_policy": "grid_frontier_cached_v3",
    "candidate_policy": "grid_safe_valley_v5",
    "same_world_trial_seed_native_config_and_manifest": True,
    "safe_valley_advance_phase_must_be_exercised": True,
    "minimum_paired_success_gains": 2,
    "maximum_paired_success_regressions": 0,
    "navigation_metric_delta_must_be_positive": True,
    "candidate_collision_rate_must_equal": 0.0,
    "candidate_timeout_rate_must_not_exceed_reference": True,
    "minimum_signed_clearance_must_be_at_least": 0.075,
    "maximum_clearance_floor_regression_m": 0.005,
    "maximum_controller_p99_latency_ms": 100.0,
    "maximum_controller_p99_latency_ratio": 1.20,
    "all_conditions_required_for_single_sealed_confirmation": True,
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _ids_sha256(world_ids: Sequence[int]) -> str:
    return _sha256_bytes(",".join(str(value) for value in world_ids).encode("ascii"))


def _seed(world_id: int, attempt: int) -> int:
    payload = f"{SEED_NAMESPACE}:{world_id}:{attempt}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & 0x7FFF_FFFF


def _parameters(world_id: int) -> tuple[float, int]:
    offset = world_id - DEVELOPMENT_WORLD_IDS[0]
    fill_percent = (0.15, 0.20, 0.25, 0.30)[(offset // 3) % 4]
    smooth_iterations = (2, 3, 4)[offset % 3]
    return fill_percent, smooth_iterations


def _git_output(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def _verify_generator(root: Path) -> None:
    if _git_output(root, "rev-parse", "HEAD") != GENERATOR_COMMIT:
        raise ValueError("BARN generator checkout does not match the frozen commit")
    if _git_output(root, "status", "--porcelain=v1", "--untracked-files=no"):
        raise ValueError("BARN generator checkout has tracked modifications")


def _install_python3_import_shims() -> None:
    sys.modules["Queue"] = queue
    tkinter = types.ModuleType("Tkinter")
    sys.modules["Tkinter"] = tkinter
    matplotlib = types.ModuleType("matplotlib")
    pyplot = types.ModuleType("matplotlib.pyplot")
    matplotlib.pyplot = pyplot  # type: ignore[attr-defined]
    sys.modules["matplotlib"] = matplotlib
    sys.modules["matplotlib.pyplot"] = pyplot

    class _NoOpWriter:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def __call__(self) -> None:
            return None

        def write(self) -> None:
            return None

    pgm_writer = types.ModuleType("pgm_writer")
    pgm_writer.PGMWriter = _NoOpWriter  # type: ignore[attr-defined]
    yaml_writer = types.ModuleType("yaml_writer")
    yaml_writer.YamlWriter = _NoOpWriter  # type: ignore[attr-defined]
    sys.modules["pgm_writer"] = pgm_writer
    sys.modules["yaml_writer"] = yaml_writer


def _load_upstream_generator(generator_root: Path) -> Any:
    _install_python3_import_shims()
    original_cwd = Path.cwd()
    original_path = tuple(sys.path)
    try:
        os.chdir(generator_root)
        sys.path.insert(0, str(generator_root))
        generator = importlib.import_module("gen_world_ca")
        # Python 2's ``node != None`` did not dereference ``None`` through the
        # repository's narrow ``Node.__eq__`` implementation. Python 3 does;
        # make only that compatibility case explicit while preserving the
        # upstream row/column equality used by A*.
        node_type = generator.Node
        original_eq = node_type.__eq__

        def python3_compatible_eq(self: object, other: object) -> bool:
            return False if other is None else bool(original_eq(self, other))

        node_type.__eq__ = python3_compatible_eq
        return generator
    finally:
        os.chdir(original_cwd)
        sys.path[:] = original_path


def _asset_directories(root: Path) -> None:
    for name in (
        "cspace_files",
        "grid_files",
        "map_files",
        "world_files",
        "metrics_files",
        "norm_metrics_files",
        "path_files",
    ):
        (root / name).mkdir(parents=True, exist_ok=False)


def _generate_development_assets(
    *,
    generator_root: Path,
    assets_root: Path,
    world_ids: Sequence[int] = DEVELOPMENT_WORLD_IDS,
    corpus_id: str = CORPUS_ID,
    temporary_prefix: str = ".safe-valley-v5-",
    seed_for: Callable[[int, int], int] = _seed,
    parameters_for: Callable[[int], tuple[float, int]] = _parameters,
) -> tuple[list[dict[str, Any]], str]:
    assets_parent = assets_root.parent
    assets_parent.mkdir(parents=True, exist_ok=True)
    temporary_parent = Path(tempfile.mkdtemp(prefix=temporary_prefix, dir=assets_parent))
    temporary_assets = temporary_parent / "test_data"
    temporary_assets.mkdir()
    _asset_directories(temporary_assets)
    log = io.StringIO()
    try:
        generator = _load_upstream_generator(generator_root)
        original_cwd = Path.cwd()
        try:
            os.chdir(temporary_parent)
            for world_id in world_ids:
                fill_percent, smooth_iterations = parameters_for(world_id)
                accepted_seed: int | None = None
                accepted_attempt: int | None = None
                for attempt in range(1, 10_001):
                    seed = seed_for(world_id, attempt)
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
                        # Some disconnected maps have no open left/right side
                        # region. The upstream dataset loop intends to reject
                        # maps with no path, but ``regions_connected`` indexes
                        # the empty region first. Treat only this known source
                        # location as the same rejected-map outcome.
                        if exc.__traceback__ is None:
                            raise
                        frames = []
                        traceback = exc.__traceback__
                        while traceback is not None:
                            frames.append(traceback.tb_frame.f_code.co_name)
                            traceback = traceback.tb_next
                        if "regions_connected" not in frames:
                            raise
                        log.write(
                            f"rejected world={world_id} seed={seed} attempt={attempt} "
                            "reason=missing_side_region\n"
                        )
                        generated = None
                    if generated:
                        accepted_seed = seed
                        accepted_attempt = attempt
                        break
                if accepted_seed is None or accepted_attempt is None:
                    raise RuntimeError(f"generator found no connected world for ID {world_id}")
                log.write(
                    f"accepted world={world_id} seed={accepted_seed} attempt={accepted_attempt} "
                    f"fill={fill_percent:.2f} smooth={smooth_iterations}\n"
                )
        finally:
            os.chdir(original_cwd)

        generation_log = temporary_assets / "generation.log"
        generation_log.write_text(log.getvalue(), encoding="utf-8")
        episodes: list[dict[str, Any]] = []
        for world_id in world_ids:
            fill_percent, smooth_iterations = parameters_for(world_id)
            accepted_line = next(
                line
                for line in log.getvalue().splitlines()
                if line.startswith(f"accepted world={world_id} ")
            )
            fields = dict(part.split("=", 1) for part in accepted_line.split()[1:])
            files: dict[str, dict[str, Any]] = {}
            for kind, relative in (
                ("world", Path("world_files") / f"world_{world_id}.world"),
                ("path", Path("path_files") / f"path_{world_id}.npy"),
                ("grid", Path("grid_files") / f"grid_{world_id}.npy"),
                ("cspace", Path("cspace_files") / f"cspace_{world_id}.npy"),
                ("metrics", Path("metrics_files") / f"metrics_{world_id}.npy"),
            ):
                path = temporary_assets / relative
                if not path.is_file():
                    raise FileNotFoundError(f"upstream generator omitted {path}")
                files[kind] = {
                    "path": relative.as_posix(),
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
            episodes.append(
                {
                    "corpus_episode_id": f"{corpus_id}/development/{world_id}",
                    "world_id": world_id,
                    "generator_seed": int(fields["seed"]),
                    "accepted_attempt": int(fields["attempt"]),
                    "fill_percent": fill_percent,
                    "smooth_iterations": smooth_iterations,
                    "rows": 30,
                    "columns": 30,
                    "files": files,
                }
            )

        if assets_root.exists():
            raise FileExistsError(f"refusing to replace generated corpus: {assets_root}")
        os.rename(temporary_assets, assets_root)
        temporary_parent.rmdir()
        return episodes, sha256_file(assets_root / "generation.log")
    except BaseException:
        shutil.rmtree(temporary_parent, ignore_errors=True)
        raise


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def _frozen_file(path: Path) -> dict[str, Any]:
    return {
        "path": _relative(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _generator_inputs(generator_root: Path) -> dict[str, dict[str, Any]]:
    relative_paths = (
        "gen_world_ca.py",
        "difficulty_quant.py",
        "world_writer.py",
        "world-boilerplate/cylinder_define.txt",
        "world-boilerplate/cylinder_place.txt",
        "world-boilerplate/world_boiler_start.txt",
        "world-boilerplate/world_boiler_mid.txt",
        "world-boilerplate/world_boiler_end.txt",
    )
    return {
        relative: {
            "sha256": sha256_file(generator_root / relative),
            "size_bytes": (generator_root / relative).stat().st_size,
        }
        for relative in relative_paths
    }


def _corpus_sha256(episodes: Sequence[dict[str, Any]]) -> str:
    canonical = json.dumps(episodes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(canonical)


def _write_exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def generate_corpus(
    *,
    generator_root: Path = DEFAULT_GENERATOR_ROOT,
    assets_root: Path = DEFAULT_ASSETS_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    """Generate development assets and atomically freeze every eval input."""

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
    )
    forbidden_ids = tuple(range(300))
    if set(DEVELOPMENT_WORLD_IDS) & set(forbidden_ids):
        raise AssertionError("generated development IDs overlap the public/frozen namespace")
    if set(DEVELOPMENT_WORLD_IDS) & set(SEALED_CONFIRMATION_WORLD_IDS):
        raise AssertionError("development and confirmation IDs overlap")

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
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
        "generator_wrapper": Path(__file__),
        "experiment_runner": Path(__file__).with_name("run_safe_valley_v5.py"),
    }
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "corpus_id": CORPUS_ID,
        "created_at": generated_at,
        "purpose": (
            "One-shot disjoint generated development corpus and unopened confirmation recipe "
            "for the deployment-disabled safe-valley v5 challenger"
        ),
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
            "forbidden_static_public_consumed_frozen_sealed_ids": list(forbidden_ids),
            "forbidden_ids_sha256": _ids_sha256(forbidden_ids),
            "development_world_ids": list(DEVELOPMENT_WORLD_IDS),
            "development_world_ids_sha256": _ids_sha256(DEVELOPMENT_WORLD_IDS),
            "sealed_confirmation_world_ids": list(SEALED_CONFIRMATION_WORLD_IDS),
            "sealed_confirmation_world_ids_sha256": _ids_sha256(SEALED_CONFIRMATION_WORLD_IDS),
            "development_disjoint_from_forbidden": True,
            "development_disjoint_from_confirmation": True,
            "namespace_note": (
                "IDs 1000+ are native-proxy corpus identifiers and can never be interpreted as "
                "the official/public BARN IDs 0-299."
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
                "world_id - 1000"
            ),
            "world_ids": list(SEALED_CONFIRMATION_WORLD_IDS),
            "single_use_only_after_all_development_gates_pass": True,
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


if __name__ == "__main__":  # pragma: no cover - command-line entry point
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
