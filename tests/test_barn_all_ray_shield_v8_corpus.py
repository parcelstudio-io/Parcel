from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import os
import stat
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.external import generate_all_ray_shield_v8_corpus as corpus


def _strict_json_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _empty_analysis() -> dict[str, object]:
    return {
        "global_nearest_not_limiting": None,
        "policy_executed": False,
        "probe_profile_id": "test-profile",
        "yaw_sweep_rotation_limited": None,
    }


def _empty_staging_tree(root: Path) -> Path:
    root.mkdir()
    for name in ("world_files", "path_files", "grid_files", "cspace_files", "metrics_files"):
        (root / name).mkdir()
    return root


def test_v8_identity_partition_explicitly_excludes_every_prior_namespace() -> None:
    assert corpus.DEVELOPMENT_WORLD_IDS == tuple(range(4000, 4030))
    assert corpus.OPERATIONAL_HOLDOUT_WORLD_IDS == tuple(range(4030, 4050))
    assert corpus.SEALED_CONFIRMATION_WORLD_IDS == corpus.OPERATIONAL_HOLDOUT_WORLD_IDS
    assert corpus.FORBIDDEN_WORLD_ID_RANGES == (
        (0, 299),
        (1000, 1049),
        (2000, 2049),
        (3000, 3049),
    )
    assert set(corpus.DEVELOPMENT_WORLD_IDS).isdisjoint(corpus.FORBIDDEN_WORLD_IDS)
    assert set(corpus.OPERATIONAL_HOLDOUT_WORLD_IDS).isdisjoint(corpus.FORBIDDEN_WORLD_IDS)
    assert set(corpus.DEVELOPMENT_WORLD_IDS).isdisjoint(corpus.OPERATIONAL_HOLDOUT_WORLD_IDS)
    assert corpus.validate_identity_partition() == {
        "development_disjoint_from_forbidden": True,
        "development_disjoint_from_holdout": True,
        "holdout_disjoint_from_forbidden": True,
    }


def test_v8_schedule_is_exactly_30_pairs_and_counterbalanced_15_15() -> None:
    schedule = corpus.validate_frozen_schedule()
    assert len(schedule) == 30
    assert len(corpus.PAIRED_ARM_ORDER_SCHEDULE) == 30
    assert corpus.PAIRED_ARM_ORDER_SCHEDULE[::2] == ("reference_then_candidate",) * 15
    assert corpus.PAIRED_ARM_ORDER_SCHEDULE[1::2] == ("candidate_then_reference",) * 15
    assert corpus.PAIRED_ARM_ORDER_SCHEDULE_SHA256 == (
        "6277cb0978592c80e883d8301792425dc4f43d41c70e823da667a8b18951abcc"
    )
    assert corpus.PAIR_EXECUTION_SCHEDULE_SHA256 == (
        "7d0aade4251b8228e2ca1f4c5c85f71fac583adacb79150c161cc99bcaa1b1f8"
    )
    assert _strict_json_sha(list(corpus.PAIRED_ARM_ORDER_SCHEDULE)) == (
        corpus.PAIRED_ARM_ORDER_SCHEDULE_SHA256
    )
    assert _strict_json_sha(list(schedule)) == corpus.PAIR_EXECUTION_SCHEDULE_SHA256
    assert [item["world_id"] for item in schedule] == list(range(4000, 4030))
    assert [item["trial"] for item in schedule] == [0] * 30
    assert [item["episode_seed"] for item in schedule] == [
        corpus.SUITE_SEED + world_id * 1_009 for world_id in range(4000, 4030)
    ]
    assert corpus.TRIALS_PER_WORLD == 1
    assert corpus.EPISODE_WORKERS == 4


def test_checked_in_protocol_is_exact_and_holdout_is_only_a_public_commitment() -> None:
    observed = json.loads(corpus.PROTOCOL_PATH.read_text(encoding="utf-8"))
    assert observed == corpus.protocol_document()
    assert corpus.HOLDOUT_RECIPE_COMMITMENT_SHA256 == (
        "31eb5659693812bda2eee18629d591c9576ab150fb98335e0a486c57d120bc9c"
    )
    assert _strict_json_sha(corpus.HOLDOUT_RECIPE) == (corpus.HOLDOUT_RECIPE_COMMITMENT_SHA256)
    holdout = observed["operational_holdout"]
    assert holdout["assets_materialized"] is False
    assert holdout["cryptographically_sealed"] is False
    assert holdout["recipe"]["world_ids"] == list(range(4030, 4050))
    assert holdout["recipe"]["acceptance"] == (
        "first connected upstream BARN map; no policy execution; any evaluator-private "
        "geometry analysis is descriptive and never an admission filter"
    )
    targeting = observed["targeting_contract"]
    assert targeting["maximum_attempts_per_world"] == 10_000
    assert targeting["generator_seed_namespace"] == corpus.SEED_NAMESPACE
    assert targeting["acceptance"].startswith("accept first generated=True")
    assert targeting["does_not_attest_policy_divergence_or_cap_activation"] is True
    assert not hasattr(corpus, "generate_holdout")
    assert not hasattr(corpus, "generate_confirmation")


def test_source_inventory_covers_evaluator_gate_evidence_transaction_and_sidecars() -> None:
    required = {
        "paired_sensor_faithful_harness",
        "comparison",
        "run_barn",
        "policy_specs",
        "policy_sidecar",
        "policy_sidecar_worker",
        "v8_policy_bundle",
        "v8_action_certifier",
        "v8_action_evidence",
        "v8_transaction",
        "v8_promotion_gate",
        "v8_experiment_runner",
        "v8_corpus_generator",
        "v8_protocol",
    }
    assert required <= set(corpus.SOURCE_FILES)
    source = Path(inspect.getsourcefile(corpus) or "").read_text(encoding="utf-8")
    assert "generate_predictive_shield_v7" not in source
    assert "predictive_shield_v7_retirement" not in source


def test_global_nearest_probe_requires_a_strictly_farther_closing_return() -> None:
    ray_count = 720
    angle_min = -math.pi
    increment = 2.0 * math.pi / (ray_count - 1)
    ranges = [math.inf] * ray_count
    ranges[0] = 0.50  # Globally nearest, directly behind, zero closing speed.
    forward_index = min(range(ray_count), key=lambda i: abs(angle_min + i * increment))
    ranges[forward_index] = 0.90

    analysis = corpus._classify_normalized_probe(
        ranges,
        angle_min_rad=angle_min,
        angle_increment_rad=increment,
        waypoint_index=4,
        position_xy=(1.0, 2.0),
        heading_rad=0.0,
    )

    witness = analysis["global_nearest_not_limiting"]
    assert witness is not None
    assert witness["nearest_ray_index"] == 0
    assert witness["nearest_range_m"] == 0.50
    assert witness["nearest_maximum_closing_speed_mps"] == 0.0
    assert witness["limiting_ray_index"] == forward_index
    assert witness["limiting_range_m"] == 0.90
    assert witness["strictly_farther_limiting_return"] is True


def test_rotation_probe_requires_yaw_sweep_to_strictly_tighten_the_limit() -> None:
    ray_count = 720
    angle_min = -math.pi
    increment = 2.0 * math.pi / (ray_count - 1)
    ranges = [math.inf] * ray_count
    target_bearing = 0.095
    target_index = min(
        range(ray_count),
        key=lambda index: abs(angle_min + index * increment - target_bearing),
    )
    ranges[target_index] = 0.95

    analysis = corpus._classify_normalized_probe(
        ranges,
        angle_min_rad=angle_min,
        angle_increment_rad=increment,
        waypoint_index=7,
        position_xy=(0.0, 0.0),
        heading_rad=0.0,
    )

    witness = analysis["yaw_sweep_rotation_limited"]
    assert witness is not None
    assert witness["limiting_ray_index"] == target_index
    assert witness["yaw_sweep_strictly_tightens_limit"] is True
    assert (
        witness["limiting_closing_speed_with_yaw_mps"]
        > (witness["limiting_closing_speed_without_yaw_mps"])
    )
    assert witness["minimum_projected_margin_m"] < (witness["zero_yaw_minimum_projected_margin_m"])


def test_targeted_generation_retries_connected_maps_until_assignment_passes(
    tmp_path: Path,
) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def main(self, **kwargs: object) -> bool:
            self.calls.append(kwargs)
            return True

    generator = FakeGenerator()
    attempts = iter((1, 2))

    def world_loader(_root: Path, world_id: int) -> SimpleNamespace:
        assert world_id == 4000
        return SimpleNamespace(attempt=next(attempts))

    def analyzer(world: SimpleNamespace) -> dict[str, object]:
        analysis = _empty_analysis()
        if world.attempt == 2:
            analysis["global_nearest_not_limiting"] = {"witness": True}
        return analysis

    seed, accepted_attempt, analysis = corpus._generate_one_targeted_world(
        generator=generator,
        assets_root=_empty_staging_tree(tmp_path / "staging"),
        world_id=4000,
        log=corpus.io.StringIO(),
        maximum_attempts=2,
        world_loader=world_loader,
        analyzer=analyzer,
    )

    assert accepted_attempt == 2
    assert seed == corpus._seed(4000, 2)
    assert analysis["policy_executed"] is False
    assert len(generator.calls) == 2
    assert [call["seed"] for call in generator.calls] == [
        corpus._seed(4000, 1),
        corpus._seed(4000, 2),
    ]


def test_targeted_generation_fails_if_analyzer_claims_policy_execution(tmp_path: Path) -> None:
    class FakeGenerator:
        @staticmethod
        def main(**_kwargs: object) -> bool:
            return True

    def analyzer(_world: object) -> dict[str, object]:
        analysis = _empty_analysis()
        analysis["policy_executed"] = True
        analysis["global_nearest_not_limiting"] = {"witness": True}
        return analysis

    with pytest.raises(ValueError, match="may not execute"):
        corpus._generate_one_targeted_world(
            generator=FakeGenerator(),
            assets_root=_empty_staging_tree(tmp_path / "staging"),
            world_id=4000,
            log=corpus.io.StringIO(),
            maximum_attempts=1,
            world_loader=lambda _root, _world_id: object(),
            analyzer=analyzer,
        )


def test_each_targeted_attempt_removes_only_exact_same_world_staging_files(
    tmp_path: Path,
) -> None:
    staging = _empty_staging_tree(tmp_path / "staging")
    exact = {
        staging / "world_files" / "world_4000.world",
        staging / "path_files" / "path_4000.npy",
        staging / "grid_files" / "grid_4000.npy",
        staging / "cspace_files" / "cspace_4000.npy",
        staging / "metrics_files" / "metrics_4000.npy",
    }
    retained = staging / "world_files" / "world_4001.world"
    for path in (*exact, retained):
        path.write_text("stale", encoding="utf-8")

    corpus._clear_staged_world_artifacts(staging, 4000)

    assert all(not path.exists() for path in exact)
    assert retained.read_text(encoding="utf-8") == "stale"

    target = tmp_path / "outside"
    target.write_text("outside", encoding="utf-8")
    unsafe = staging / "world_files" / "world_4000.world"
    unsafe.symlink_to(target)
    with pytest.raises(ValueError, match="symbolic link"):
        corpus._clear_staged_world_artifacts(staging, 4000)
    assert target.read_text(encoding="utf-8") == "outside"


def test_target_assignments_require_all_30_and_both_strata() -> None:
    analyses: dict[int, dict[str, object]] = {}
    for world_id in corpus.DEVELOPMENT_WORLD_IDS:
        analysis = _empty_analysis()
        analysis[corpus.TARGET_ASSIGNMENTS[world_id]] = {"witness": world_id}
        analyses[world_id] = analysis
    summary = corpus._validate_target_assignments(analyses)
    assert summary["assignment_satisfied_for_every_world"] is True
    assert summary["global_nearest_not_limiting_world_count"] == 15
    assert summary["yaw_sweep_rotation_limited_world_count"] == 15

    analyses[4000]["global_nearest_not_limiting"] = None
    with pytest.raises(ValueError, match="lacks its assigned"):
        corpus._validate_target_assignments(analyses)


def test_output_preflight_rejects_partial_complete_holdout_and_symlink_states(
    tmp_path: Path,
) -> None:
    assets = tmp_path / "assets"
    manifest = tmp_path / "split.json"
    holdout = tmp_path / "holdout"
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(corpus.PartialV8CorpusMaterializationError):
        corpus._assert_output_namespace_pristine(
            assets_root=assets,
            manifest_path=manifest,
            holdout_assets_root=holdout,
        )

    assets.mkdir()
    with pytest.raises(FileExistsError, match="already exist"):
        corpus._assert_output_namespace_pristine(
            assets_root=assets,
            manifest_path=manifest,
            holdout_assets_root=holdout,
        )

    other_root = tmp_path / "other"
    other_root.mkdir()
    holdout.mkdir()
    with pytest.raises(FileExistsError, match="holdout assets already exist"):
        corpus._assert_output_namespace_pristine(
            assets_root=other_root / "assets",
            manifest_path=other_root / "split.json",
            holdout_assets_root=holdout,
        )

    symlink_root = tmp_path / "symlink-root"
    symlink_root.symlink_to(other_root, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic-link component"):
        corpus._assert_output_namespace_pristine(
            assets_root=symlink_root / "assets",
            manifest_path=tmp_path / "fresh-split.json",
            holdout_assets_root=tmp_path / "fresh-holdout",
        )

    with pytest.raises(ValueError, match="manifest and holdout"):
        corpus._assert_output_namespace_pristine(
            assets_root=tmp_path / "isolated-assets",
            manifest_path=tmp_path / "nested-holdout" / "split.json",
            holdout_assets_root=tmp_path / "nested-holdout",
        )


def test_asset_publication_claims_without_clobber_and_makes_tree_read_only(
    tmp_path: Path,
) -> None:
    staged = tmp_path / "stage"
    (staged / "world_files").mkdir(parents=True)
    (staged / "world_files" / "world_4000.world").write_text("world", encoding="utf-8")
    destination = tmp_path / "published"

    corpus._commit_staged_assets(staged, destination)

    published = destination / "world_files" / "world_4000.world"
    assert published.read_text(encoding="utf-8") == "world"
    assert os.stat(published).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
    assert os.stat(destination).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0

    second_stage = tmp_path / "second-stage"
    second_stage.mkdir()
    (second_stage / "replacement").write_text("replacement", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to replace"):
        corpus._commit_staged_assets(second_stage, destination)
    assert published.read_text(encoding="utf-8") == "world"


def test_manifest_publication_is_exclusive_canonical_and_immutable(tmp_path: Path) -> None:
    manifest = tmp_path / "nested" / "split.json"
    corpus._write_exclusive_manifest(manifest, {"z": 1, "a": [2, 3]})

    assert json.loads(manifest.read_bytes()) == {"a": [2, 3], "z": 1}
    assert manifest.read_bytes().endswith(b"\n")
    assert os.stat(manifest).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
    original = manifest.read_bytes()
    with pytest.raises(FileExistsError, match="refusing to replace"):
        corpus._write_exclusive_manifest(manifest, {"different": True})
    assert manifest.read_bytes() == original


def test_manifest_publication_never_unlinks_a_foreign_temporary_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "nested" / "split.json"
    manifest.parent.mkdir(parents=True)
    fixed_hex = "f" * 32
    collision = manifest.parent / f".{manifest.name}.{os.getpid()}.{fixed_hex}.tmp"
    foreign_bytes = b"foreign manifest temporary file\n"
    collision.write_bytes(foreign_bytes)
    monkeypatch.setattr(corpus.uuid, "uuid4", lambda: SimpleNamespace(hex=fixed_hex))

    with pytest.raises(FileExistsError):
        corpus._write_exclusive_manifest(manifest, {"must_not_land": True})

    assert collision.read_bytes() == foreign_bytes
    assert manifest.exists() is False


def test_strict_generator_state_records_resolved_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator_root = tmp_path / "generator"
    generator_root.mkdir()
    monkeypatch.setattr(corpus, "_verify_generator", lambda _root: None)
    monkeypatch.setattr(corpus, "_generator_inputs", lambda _root: {})
    monkeypatch.setattr(
        corpus.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=""),
    )

    state = corpus._strict_generator_state(generator_root)

    assert state["root"] == str(generator_root.resolve())
    assert state["tracked_and_untracked_status_clean"] is True


def test_loaded_generator_modules_must_come_from_the_verified_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "generator"
    root.mkdir()
    modules: dict[str, types.ModuleType] = {}
    for name in ("gen_world_ca", "world_writer", "difficulty_quant"):
        path = root / f"{name}.py"
        path.write_text("# fixture\n", encoding="utf-8")
        module = types.ModuleType(name)
        module.__file__ = str(path)
        modules[name] = module
        if name != "gen_world_ca":
            monkeypatch.setitem(corpus.sys.modules, name, module)

    corpus._verify_loaded_generator_modules(modules["gen_world_ca"], root)

    modules["world_writer"].__file__ = str(tmp_path / "other" / "world_writer.py")
    with pytest.raises(ValueError, match="does not come from"):
        corpus._verify_loaded_generator_modules(modules["gen_world_ca"], root)


def test_current_evaluator_and_generator_source_closure_is_freezable() -> None:
    state = corpus._frozen_generation_state(corpus.DEFAULT_GENERATOR_ROOT)
    source_files = state["source_files"]

    assert set(source_files) == set(corpus.SOURCE_FILES)
    assert source_files["v8_promotion_gate"]["path"].endswith("barn_v8_promotion_gate.py")
    assert source_files["v8_experiment_runner"]["path"].endswith("run_all_ray_shield_v8.py")
    assert state["generator"]["root"] == str(corpus.DEFAULT_GENERATOR_ROOT.resolve())
    assert state["production_policy_source_tree"]["file_count"] > 0
    assert state["evaluator_profile"]["required_ray_count"] == 720


def test_generation_rechecks_policy_pair_before_any_asset_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets = tmp_path / "assets"
    manifest = tmp_path / "split.json"
    holdout = tmp_path / "holdout"
    generator_root = tmp_path / "generator"
    generator_root.mkdir()
    staged_parent = tmp_path / "staging"
    staged = staged_parent / "test_data"
    staged.mkdir(parents=True)
    calls: list[str] = []
    identities = iter(({"pair": "before"}, {"pair": "after"}))

    monkeypatch.setattr(corpus, "_frozen_generation_state", lambda _root: {"source": "same"})
    monkeypatch.setattr(corpus, "prepare_v8_candidate_bundle", lambda: object())
    monkeypatch.setattr(corpus, "_freeze_policy_pair", lambda _bundle: next(identities))
    monkeypatch.setattr(
        corpus,
        "_generate_staged_assets",
        lambda **_kwargs: (staged, [], "0" * 64, staged_parent),
    )
    monkeypatch.setattr(corpus, "validate_generated_development_corpus", lambda *_args: {})
    monkeypatch.setattr(corpus, "_commit_staged_assets", lambda *_args: calls.append("commit"))

    with pytest.raises(ValueError, match="policy pair changed"):
        corpus.generate_corpus(
            generator_root=generator_root,
            assets_root=assets,
            manifest_path=manifest,
            holdout_assets_root=holdout,
        )
    assert calls == []
    assert not assets.exists()
    assert not manifest.exists()
    assert not holdout.exists()


def test_generation_source_state_mismatch_fails_before_policy_recheck_or_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged_parent = tmp_path / "staging"
    staged = staged_parent / "test_data"
    staged.mkdir(parents=True)
    states = iter(({"source_sha256": "a" * 64}, {"source_sha256": "b" * 64}))
    calls: list[str] = []

    monkeypatch.setattr(corpus, "_frozen_generation_state", lambda _root: next(states))
    monkeypatch.setattr(corpus, "prepare_v8_candidate_bundle", lambda: object())
    monkeypatch.setattr(corpus, "_freeze_policy_pair", lambda _bundle: {"pair": "same"})
    monkeypatch.setattr(
        corpus,
        "_generate_staged_assets",
        lambda **_kwargs: (staged, [], "0" * 64, staged_parent),
    )
    monkeypatch.setattr(corpus, "validate_generated_development_corpus", lambda *_args: {})
    monkeypatch.setattr(corpus, "_commit_staged_assets", lambda *_args: calls.append("commit"))

    with pytest.raises(ValueError, match="changed during staging"):
        corpus.generate_corpus(
            generator_root=tmp_path / "generator",
            assets_root=tmp_path / "assets",
            manifest_path=tmp_path / "split.json",
            holdout_assets_root=tmp_path / "holdout",
        )
    assert calls == []


def test_generation_rechecks_holdout_absence_immediately_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets = tmp_path / "assets"
    manifest = tmp_path / "split.json"
    holdout = tmp_path / "holdout"
    staged_parent = tmp_path / "staging"
    staged = staged_parent / "test_data"
    staged.mkdir(parents=True)
    calls: list[str] = []

    def stage(**_kwargs: object) -> tuple[Path, list[object], str, Path]:
        holdout.mkdir()
        return staged, [], "0" * 64, staged_parent

    monkeypatch.setattr(corpus, "_frozen_generation_state", lambda _root: {"source": "same"})
    monkeypatch.setattr(corpus, "prepare_v8_candidate_bundle", lambda: object())
    monkeypatch.setattr(corpus, "_freeze_policy_pair", lambda _bundle: {"pair": "same"})
    monkeypatch.setattr(corpus, "_generate_staged_assets", stage)
    monkeypatch.setattr(corpus, "validate_generated_development_corpus", lambda *_args: {})
    monkeypatch.setattr(corpus, "_verify_policy_identity", lambda _identity: None)
    monkeypatch.setattr(corpus, "_commit_staged_assets", lambda *_args: calls.append("commit"))

    with pytest.raises(FileExistsError, match="holdout assets already exist"):
        corpus.generate_corpus(
            generator_root=tmp_path / "generator",
            assets_root=assets,
            manifest_path=manifest,
            holdout_assets_root=holdout,
        )
    assert calls == []
    assert not assets.exists()
    assert not manifest.exists()


def test_successful_development_freeze_path_never_materializes_holdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets = tmp_path / "assets"
    manifest_path = tmp_path / "split.json"
    holdout = tmp_path / "holdout"
    staged_parent = tmp_path / "staging"
    staged = staged_parent / "test_data"
    staged.mkdir(parents=True)
    publications: list[str] = []

    monkeypatch.setattr(corpus, "_frozen_generation_state", lambda _root: {"source": "same"})
    monkeypatch.setattr(corpus, "prepare_v8_candidate_bundle", lambda: object())
    monkeypatch.setattr(corpus, "_freeze_policy_pair", lambda _bundle: {"pair": "same"})
    monkeypatch.setattr(
        corpus,
        "_generate_staged_assets",
        lambda **_kwargs: (staged, [], "0" * 64, staged_parent),
    )
    monkeypatch.setattr(corpus, "validate_generated_development_corpus", lambda *_args: {})
    monkeypatch.setattr(corpus, "_verify_policy_identity", lambda _identity: None)
    monkeypatch.setattr(
        corpus,
        "_commit_staged_assets",
        lambda *_args: publications.append("assets"),
    )
    monkeypatch.setattr(
        corpus,
        "_write_exclusive_manifest",
        lambda *_args: publications.append("manifest"),
    )

    manifest = corpus.generate_corpus(
        generator_root=tmp_path / "generator",
        assets_root=assets,
        manifest_path=manifest_path,
        holdout_assets_root=holdout,
    )

    assert publications == ["assets", "manifest"]
    assert manifest["operational_holdout_recipe"]["generated"] is False
    assert manifest["operational_holdout_recipe"]["opened"] is False
    assert manifest["operational_holdout_recipe"]["evaluated"] is False
    assert not holdout.exists()


def test_generation_log_identity_rejects_tamper_and_symlink(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    log = assets / "generation.log"
    log.write_text("accepted\n", encoding="utf-8")
    expected = hashlib.sha256(log.read_bytes()).hexdigest()
    corpus._verify_generation_log(assets, expected)

    log.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="identity changed"):
        corpus._verify_generation_log(assets, expected)

    log.unlink()
    target = tmp_path / "outside.log"
    target.write_text("accepted\n", encoding="utf-8")
    log.symlink_to(target)
    with pytest.raises(ValueError, match="missing or unsafe"):
        corpus._verify_generation_log(assets, expected)


def test_profile_snapshot_uses_the_profile_identity_payload() -> None:
    payload = corpus.FROZEN_V8_BARN_EVALUATOR_PROFILE.identity_payload()
    assert payload["required_ray_count"] == 720
    assert payload["reaction_horizon_s"] == 0.12
    assert payload["control_period_s"] == 0.1


def test_frozen_manifest_verifier_roundtrip_and_contract_tamper_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    log = assets / "generation.log"
    log.write_text("accepted\n", encoding="utf-8")
    holdout = tmp_path / "holdout"
    generator_root = tmp_path / "generator"
    generator_root.mkdir()
    state = {"generator": {"root": str(generator_root)}, "source": "frozen"}
    episodes = [{"world_id": world_id} for world_id in corpus.DEVELOPMENT_WORLD_IDS]
    validation = {"world_count": 30, "test_fixture": True}
    manifest = {
        "schema_version": corpus.SCHEMA_VERSION,
        "manifest_id": corpus.MANIFEST_ID,
        "corpus_id": corpus.CORPUS_ID,
        "created_at": "2026-08-03T00:00:00Z",
        "purpose": corpus.MANIFEST_PURPOSE,
        "benchmark_scope": corpus._benchmark_scope_manifest(),
        "identity_partition": corpus._identity_partition_manifest(),
        "development_corpus": {
            "assets_root": str(assets),
            "corpus_sha256": corpus._corpus_sha256(episodes),
            "episodes": episodes,
            "generation_log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
            "independent_validation": validation,
            "world_count": 30,
        },
        "operational_holdout_recipe": corpus._holdout_manifest(holdout),
        "paired_protocol_frozen_before_execution": corpus._paired_protocol_manifest(),
        "policy_pair_identity": {},
        "frozen_generation_state": {
            "content": state,
            "post_generation_sha256": corpus._canonical_sha256(state),
            "pre_and_post_identical": True,
            "pre_generation_sha256": corpus._canonical_sha256(state),
        },
        "promotion_gate_frozen_before_development": corpus.PROMOTION_GATE,
        "status_at_freeze": corpus._status_at_freeze_manifest(),
    }
    manifest_path = tmp_path / "split.json"

    def write(document: dict[str, object]) -> None:
        if manifest_path.exists():
            manifest_path.chmod(0o644)
        manifest_path.write_text(json.dumps(document), encoding="utf-8")
        manifest_path.chmod(0o444)

    monkeypatch.setattr(
        corpus,
        "validate_generated_development_corpus",
        lambda _episodes, _assets: validation,
    )
    monkeypatch.setattr(corpus, "_frozen_generation_state", lambda _root: state)
    monkeypatch.setattr(corpus, "_verify_policy_identity", lambda _identity: None)
    write(manifest)

    report = corpus.verify_frozen_corpus(manifest_path)

    assert report["corpus_id"] == corpus.CORPUS_ID
    assert report["world_count"] == 30
    assert report["holdout_absent"] is True
    assert report["policy_pair_verified"] is True

    mutations = (
        ("benchmark_scope", {**corpus._benchmark_scope_manifest(), "official_gazebo_score": True}),
        ("promotion_gate_frozen_before_development", {}),
        ("status_at_freeze", {**corpus._status_at_freeze_manifest(), "holdout_opened": True}),
        ("paired_protocol_frozen_before_execution", {}),
        (
            "operational_holdout_recipe",
            {**corpus._holdout_manifest(holdout), "root_authorization_required": False},
        ),
    )
    for field, value in mutations:
        changed = copy.deepcopy(manifest)
        changed[field] = value
        write(changed)
        with pytest.raises(ValueError):
            corpus.verify_frozen_corpus(manifest_path)


def test_cli_requires_explicit_development_freeze_authorization() -> None:
    with pytest.raises(SystemExit) as exc_info:
        corpus.main([])
    assert exc_info.value.code == 2


def test_v8_runner_imports_frozen_constants_and_requires_single_use_authorization() -> None:
    from evals.external import run_all_ray_shield_v8 as runner

    assert runner.CORPUS_ID == corpus.CORPUS_ID
    assert runner.PAIR_EXECUTION_SCHEDULE_SHA256 == corpus.PAIR_EXECUTION_SCHEDULE_SHA256
    assert runner.PAIRED_ARM_ORDER_SCHEDULE_SHA256 == (corpus.PAIRED_ARM_ORDER_SCHEDULE_SHA256)
    with pytest.raises(PermissionError, match="single-use"):
        runner.run_development()
