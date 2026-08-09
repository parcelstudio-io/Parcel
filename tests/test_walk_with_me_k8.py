"""K8 smoke: frozen walk-with-me pack load + stub episode execution."""

from __future__ import annotations

import json

from evals.walk_with_me.generator import (
    FREEZE_SEED,
    THEMES,
    default_freeze_path,
    generate_frozen_pack,
    load_frozen_manifest,
    matrix_digest,
    write_frozen_manifest,
)
from evals.walk_with_me.runner import WalkWithMeRunner, aggregate_results
from parcel_robot.instructnav.scoring import AttributionLayer, FailureClass


def test_frozen_pack_size_and_themes(tmp_path):
    scripts = generate_frozen_pack(seed=FREEZE_SEED)
    assert 8 <= len(scripts) <= 12
    assert {s.theme for s in scripts} == set(THEMES)
    path = write_frozen_manifest(tmp_path / "manifest.json", seed=FREEZE_SEED)
    manifest, loaded = load_frozen_manifest(path)
    assert manifest["freeze_seed"] == FREEZE_SEED
    assert manifest["digest"] == matrix_digest(scripts)
    assert len(manifest["does_not_prove"]) >= 3
    assert [s.script_id for s in loaded] == [s.script_id for s in scripts]
    assert set(manifest["script_seeds"]) == {s.script_id for s in scripts}


def test_same_seed_byte_identical():
    a = generate_frozen_pack(seed=FREEZE_SEED)
    b = generate_frozen_pack(seed=FREEZE_SEED)
    assert matrix_digest(a) == matrix_digest(b)
    assert [s.as_dict() for s in a] == [s.as_dict() for s in b]


def test_committed_freeze_matches_generator():
    freeze = default_freeze_path()
    assert freeze.is_file(), "K8 freeze manifest must be committed"
    manifest, scripts = load_frozen_manifest(freeze)
    expected = generate_frozen_pack(seed=int(manifest["freeze_seed"]))
    assert matrix_digest(scripts) == matrix_digest(expected)
    assert manifest["digest"] == matrix_digest(expected)
    assert set(manifest["themes"]) == set(THEMES)


def test_smoke_stub_pause_resume_and_barge_in():
    scripts = generate_frozen_pack(seed=FREEZE_SEED)
    wanted = ("wwm-pause-resume", "wwm-barge-in-tts")
    runner = WalkWithMeRunner(mode="stub")
    results = runner.run_pack(scripts, script_ids=wanted)
    assert len(results) == 2
    by_id = {item.script_id: item for item in results}
    assert by_id["wwm-pause-resume"].success
    assert by_id["wwm-pause-resume"].harness_used == "resume_store"
    assert by_id["wwm-barge-in-tts"].success
    assert by_id["wwm-barge-in-tts"].failure in {FailureClass.NONE, FailureClass.CONTROL_ERROR}
    aggregate = aggregate_results(results)
    assert aggregate["n"] == 2
    assert aggregate["sr"] == 1.0
    assert aggregate["does_not_prove"]
    assert "attribution_histogram" in aggregate
    # Attribution fields are instructnav-compatible enums.
    for item in results:
        assert isinstance(item.failure, FailureClass)
        assert isinstance(item.attribution_layer, AttributionLayer)


def test_absent_target_attribution_fields():
    scripts = {s.script_id: s for s in generate_frozen_pack(seed=FREEZE_SEED)}
    result = WalkWithMeRunner(mode="stub").run_script(scripts["wwm-absent-target"])
    assert result.success
    assert result.failure == FailureClass.REFUSAL
    assert result.attribution_layer in {
        AttributionLayer.L1_PARSE,
        AttributionLayer.L2A_VOCABULARY,
    }
    payload = result.as_dict()
    assert "failure" in payload and "attribution_layer" in payload


def test_cli_smoke(tmp_path):
    from evals.walk_with_me import run_walk_with_me_v1

    # Ensure freeze exists for CLI path.
    if not default_freeze_path().is_file():
        write_frozen_manifest(default_freeze_path(), seed=FREEZE_SEED)
    code = run_walk_with_me_v1.main(
        ["--smoke", "--mode", "stub", "--out", str(tmp_path)]
    )
    assert code == 0
    reports = list(tmp_path.glob("walk-with-me-v1-stub-*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["smoke"] is True
    assert report["aggregate"]["n"] == 2
    assert report["does_not_prove"]
