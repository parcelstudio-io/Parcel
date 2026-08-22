"""Self-test for the CI gate — proof each hard gate is not theatre.

Mirrors ``scripts/mutation_panel.py``'s discipline: a green gate proves nothing
unless it goes RED for the right reason. For every hard regression gate the
runner enforces, this file seeds the exact class of regression the verdict names
and asserts the gate reddens — then asserts it is green on a clean input:

* MODEL-OFF NON-INFERIORITY  <- a flag-off drift (SigLIP fallback perturbed)
* HARD-SAFETY                <- an injected collision, and a new false_arrival
* LATENCY-TAIL               <- a p95/p99 spike past the ratchet ceiling
* FROZEN-DIGEST INTEGRITY    <- a byte-changed frozen manifest
* RUFF RATCHET               <- a new (file, rule) fingerprint
* TIER COVERAGE (card R26)   <- a narrowed nightly selection that orphans a tier

Seeds are injected into *copies* / synthetic inputs or via runtime monkeypatch —
never a committed source or frozen artifact edit (the mutation-panel rule).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci_gate import (
    COMMIT_MARKERS,
    DIGEST_SENTINELS,
    MODEL_OFF_NODE_IDS,
    NIGHTLY_SLOW_MARKERS,
    RELEASE_PARITY_MANIFEST,
    evaluate_frozen_digest_sentinels,
    evaluate_hard_safety,
    evaluate_latency_ledger,
    evaluate_latency_ratchet,
    evaluate_release_parity,
    evaluate_ruff,
    evaluate_tier_coverage,
    run_commit_tier,
    run_nightly_tier,
    run_pytest,
)

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# helpers — build clean product-path artifacts in a tmp dir
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _clean_artifacts(tmp: Path) -> dict[str, Path]:
    nav = _write_jsonl(
        tmp / "nav_ledger.jsonl",
        [
            {"report_id": "old", "frozen_baseline": False, "collision_total": 0,
             "authority_histogram": {"false_arrival": 0}},
            {"report_id": "frozen", "frozen_baseline": True, "collision_total": 0,
             "authority_histogram": {"false_arrival": 0}},
        ],
    )
    panel = tmp / "mutation_panel.json"
    panel.write_text(
        json.dumps({"clean_run": {"collisions": 0}, "clean_checks": {"no_false_arrival": True}}),
        encoding="utf-8",
    )
    fb = _write_jsonl(
        tmp / "followbench.jsonl",
        [{"report_id": "fb-1", "hard_collision_total": 0}, {"report_id": "fb-2", "hard_collision_total": 0}],
    )
    wwm = _write_jsonl(
        tmp / "walk_with_me.jsonl",
        [
            # Legacy stub row without the field — must not redden hard-safety.
            {"report_id": "wwm-legacy", "smoke": True, "n": 2},
            {"report_id": "wwm-1", "hard_collision_total": 0, "smoke": True, "n": 2},
        ],
    )
    return {
        "nav_ledger": nav,
        "mutation_panel": panel,
        "followbench_ledger": fb,
        "walk_with_me_ledger": wwm,
    }


# ===========================================================================
# HARD-SAFETY
# ===========================================================================


def test_hard_safety_is_green_on_clean_artifacts(tmp_path: Path) -> None:
    a = _clean_artifacts(tmp_path)
    result = evaluate_hard_safety(**a)
    assert result.status == "pass", result.detail


def test_hard_safety_reddens_on_injected_collision(tmp_path: Path) -> None:
    a = _clean_artifacts(tmp_path)
    _write_jsonl(
        a["nav_ledger"],
        [{"report_id": "frozen", "frozen_baseline": True, "collision_total": 1,
          "authority_histogram": {"false_arrival": 0}}],
    )
    result = evaluate_hard_safety(**a)
    assert result.status == "fail", "an injected collision must redden hard-safety"
    assert "collision_total=1" in result.detail


def test_hard_safety_reddens_on_new_false_arrival(tmp_path: Path) -> None:
    a = _clean_artifacts(tmp_path)
    _write_jsonl(
        a["nav_ledger"],
        [{"report_id": "frozen", "frozen_baseline": True, "collision_total": 0,
          "authority_histogram": {"false_arrival": 1}}],
    )
    result = evaluate_hard_safety(**a)
    assert result.status == "fail", "a new false_arrival must redden hard-safety"
    assert "false_arrival=1" in result.detail


def test_hard_safety_reddens_on_followbench_collision(tmp_path: Path) -> None:
    a = _clean_artifacts(tmp_path)
    _write_jsonl(a["followbench_ledger"], [{"report_id": "fb-x", "hard_collision_total": 2}])
    result = evaluate_hard_safety(**a)
    assert result.status == "fail"
    assert "fb-x" in result.detail


def test_hard_safety_skips_legacy_walk_with_me_rows_without_field(tmp_path: Path) -> None:
    a = _clean_artifacts(tmp_path)
    _write_jsonl(
        a["walk_with_me_ledger"],
        [{"report_id": "wwm-legacy", "smoke": True, "n": 2}],
    )
    result = evaluate_hard_safety(**a)
    assert result.status == "pass", result.detail
    assert "none carry hard_collision_total" in result.detail


def test_hard_safety_reddens_on_walk_with_me_collision(tmp_path: Path) -> None:
    a = _clean_artifacts(tmp_path)
    _write_jsonl(
        a["walk_with_me_ledger"],
        [
            {"report_id": "wwm-legacy", "smoke": True},
            {"report_id": "wwm-x", "hard_collision_total": 1},
        ],
    )
    result = evaluate_hard_safety(**a)
    assert result.status == "fail"
    assert "wwm-x" in result.detail


# ---------------------------------------------------------------------------
# HARD-SAFETY / mutation-panel FRESHNESS (lane E7, 2026-08-10)
#
# The seeded regression here is *staleness*, not a bad number: a committed panel
# artifact whose safety fields no longer reproduce on the tree. That is the exact
# hole this lane found — the gate printed ``no_false_arrival=True`` from a
# payload written at 19c9226 while a live clean run on the same tree said
# ``false``. The reproducer is injected, so the seed is a stub and never a
# committed-artifact edit (the mutation-panel rule).
# ---------------------------------------------------------------------------


def _panel_fields(*, no_false_arrival: bool, false_arrivals: int = 0) -> dict:
    authority = {"agreement": 5 - false_arrivals}
    if false_arrivals:
        authority["false_arrival"] = false_arrivals
    return {
        "collisions": 0,
        "authority": authority,
        "clean_checks": {
            "zero_collisions": True,
            "no_authority_disagreement": True,
            "no_false_arrival": no_false_arrival,
            "path_length_plausible": True,
        },
    }


def _panel_artifact(tmp: Path, fields: dict) -> Path:
    path = tmp / "mutation_panel.json"
    path.write_text(
        json.dumps(
            {
                "clean_run": {"collisions": fields["collisions"], "authority": fields["authority"]},
                "clean_checks": fields["clean_checks"],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_hard_safety_is_green_when_the_panel_reproduces(tmp_path: Path) -> None:
    a = _clean_artifacts(tmp_path)
    fields = _panel_fields(no_false_arrival=True)
    a["mutation_panel"] = _panel_artifact(tmp_path, fields)
    result = evaluate_hard_safety(**a, reproduce_panel=lambda: fields)
    assert result.status == "pass", result.detail
    assert "freshness: committed fields reproduce live = True" in result.detail


def test_hard_safety_reddens_when_a_live_run_contradicts_the_committed_panel(
    tmp_path: Path,
) -> None:
    """The E7 defect: the artifact says no false arrival, the tree says otherwise."""

    a = _clean_artifacts(tmp_path)
    a["mutation_panel"] = _panel_artifact(tmp_path, _panel_fields(no_false_arrival=True))
    live = _panel_fields(no_false_arrival=False, false_arrivals=1)
    result = evaluate_hard_safety(**a, reproduce_panel=lambda: live)
    assert result.status == "fail", (
        "a committed panel a live run contradicts must redden hard-safety — "
        "otherwise the gate certifies a safety property from a stale file"
    )
    assert "STALE" in result.detail
    assert "clean_checks" in result.detail


def test_hard_safety_reddens_when_the_panel_merely_drops_the_check(tmp_path: Path) -> None:
    """Deleting ``no_false_arrival`` must not be cheaper than recording it false."""

    a = _clean_artifacts(tmp_path)
    committed = _panel_fields(no_false_arrival=True)
    del committed["clean_checks"]["no_false_arrival"]
    a["mutation_panel"] = _panel_artifact(tmp_path, committed)
    result = evaluate_hard_safety(
        **a, reproduce_panel=lambda: _panel_fields(no_false_arrival=True)
    )
    assert result.status == "fail", "a dropped safety check must read as False, not as absent"


def test_hard_safety_freshness_is_skipped_only_for_synthetic_artifacts(
    tmp_path: Path,
) -> None:
    """No reproducer + a synthetic path = recorded skip, never a silent pass."""

    a = _clean_artifacts(tmp_path)
    result = evaluate_hard_safety(**a)
    assert "freshness: skipped (synthetic artifact" in result.detail


def test_hard_safety_defaults_to_reproducing_the_real_committed_artifact() -> None:
    """The default path must WIRE the live reproducer, not default to skipping."""

    from scripts.ci_gate import MUTATION_PANEL_JSON, _panel_safety_fields_live

    calls: list[int] = []

    def spy() -> dict:
        calls.append(1)
        return {"collisions": 0, "authority": {}, "clean_checks": {}}

    assert callable(_panel_safety_fields_live)
    result = evaluate_hard_safety(mutation_panel=MUTATION_PANEL_JSON, reproduce_panel=spy)
    assert calls, "hard-safety did not reproduce the committed panel"
    checks = result.extra["checks"]
    assert any("freshness" in line for line in checks), checks
    assert not any("skipped" in line for line in checks if "freshness" in line), checks


# ===========================================================================
# FROZEN-DIGEST INTEGRITY
# ===========================================================================


def test_frozen_digest_is_green_when_bytes_match(tmp_path: Path) -> None:
    import hashlib

    art = tmp_path / "manifest.json"
    art.write_text('{"frozen": true}', encoding="utf-8")
    sha = hashlib.sha256(art.read_bytes()).hexdigest()
    result = evaluate_frozen_digest_sentinels({"manifest.json": sha}, root=tmp_path)
    assert result.status == "pass", result.detail


def test_frozen_digest_reddens_on_byte_change(tmp_path: Path) -> None:
    import hashlib

    art = tmp_path / "manifest.json"
    art.write_text('{"frozen": true}', encoding="utf-8")
    sha = hashlib.sha256(art.read_bytes()).hexdigest()
    # Seed: a single byte changes -> the pinned sha no longer matches.
    art.write_text('{"frozen": true} ', encoding="utf-8")
    result = evaluate_frozen_digest_sentinels({"manifest.json": sha}, root=tmp_path)
    assert result.status == "fail", "a byte-changed frozen digest must redden"
    assert "!=" in result.detail


def test_frozen_digest_reddens_on_missing_artifact(tmp_path: Path) -> None:
    result = evaluate_frozen_digest_sentinels({"gone.json": "0" * 64}, root=tmp_path)
    assert result.status == "fail"
    assert "MISSING" in result.detail


def test_real_frozen_sentinels_match_the_current_tree() -> None:
    """Positive control: the pinned sentinels are byte-identical on this tree."""

    result = evaluate_frozen_digest_sentinels(DIGEST_SENTINELS)
    assert result.status == "pass", result.detail
    # A LITERAL, deliberately — deriving it from ``len(DIGEST_SENTINELS)`` would
    # make the assertion vacuous and let a sentinel be dropped silently. 3 -> 4
    # on 2026-08-11 (lane E8): ``nav_instruct/episodes/v4/manifest.json`` was
    # ADDED when the owner authorized the v4 re-freeze. The other three, v3
    # included, are unchanged and still byte-identical to their pins.
    assert result.extra["checked"] == 4, "four immutable manifests are pinned"


@pytest.mark.parametrize("relpath", sorted(DIGEST_SENTINELS))
def test_each_real_sentinel_reddens_on_a_seeded_byte(relpath: str, tmp_path: Path) -> None:
    """Per-sentinel proof, not one synthetic stand-in.

    ``test_frozen_digest_reddens_on_byte_change`` only proves the *comparator*
    works on a made-up file. It could not tell you whether any particular
    committed manifest is actually wired to it — which is how
    ``personal_convo_v1``'s pack_digest moved under a green gate during task_15
    (Fable audit ``AUDIT_FABLE_INDEPENDENT.md``, BLOCKING 2): the manifest simply
    was not in ``DIGEST_SENTINELS``.

    So this seeds each *real* pinned manifest's bytes and asserts that manifest's
    own pin reddens. The seed goes into a tmp COPY — never the frozen artifact
    (the mutation-panel rule).
    """

    source = REPO / relpath
    assert source.is_file(), f"{relpath} is pinned but absent from the tree"

    copy = tmp_path / relpath
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_bytes(source.read_bytes())
    pinned = DIGEST_SENTINELS[relpath]

    clean = evaluate_frozen_digest_sentinels({relpath: pinned}, root=tmp_path)
    assert clean.status == "pass", f"{relpath} clean copy must match its pin: {clean.detail}"

    # Seed: one byte appended to the copy -> this manifest's own pin must redden.
    copy.write_bytes(copy.read_bytes() + b" ")
    seeded = evaluate_frozen_digest_sentinels({relpath: pinned}, root=tmp_path)
    assert seeded.status == "fail", f"a byte-changed {relpath} must redden its sentinel"
    assert relpath in seeded.detail and "!=" in seeded.detail


def test_one_seeded_sentinel_reddens_the_whole_gate(tmp_path: Path) -> None:
    """A single bad manifest fails the aggregate gate and is named in the detail."""

    for relpath in DIGEST_SENTINELS:
        copy = tmp_path / relpath
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes((REPO / relpath).read_bytes())

    target = "evals/companion/personal_convo_v1/manifest.json"
    seeded = tmp_path / target
    seeded.write_bytes(seeded.read_bytes() + b"\n")

    result = evaluate_frozen_digest_sentinels(DIGEST_SENTINELS, root=tmp_path)
    assert result.status == "fail"
    assert target in result.detail


def test_no_frozen_manifest_silently_escapes_the_sentinel_set() -> None:
    """The set of frozen-but-unpinned manifests is itself pinned.

    ``personal_convo_v1`` was frozen but unpinned, so its digest could move under
    a green gate. Freezing a new suite (or dropping an existing pin) changes this
    set and reddens here, forcing an explicit decision instead of silence.
    """

    frozen = set()
    for manifest in sorted((REPO / "evals").rglob("manifest.json")):
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("frozen") is True:
            frozen.add(manifest.relative_to(REPO).as_posix())

    # (Not every sentinel carries a ``frozen`` flag — ``nav_instruct/episodes/v3``
    # is an immutable episode set pinned by convention, so this is one-way: every
    # flagged-frozen manifest is accounted for, pins may cover more.)
    #
    # Frozen suites that are knowingly not byte-pinned yet. Each is covered by a
    # recompute-vs-manifest pytest id in ``FROZEN_DIGEST_NODE_IDS`` or its own
    # suite tests; byte-pinning them is tracked follow-up, not silence.
    known_unpinned = {
        "evals/companion/acoustic_loop_v1/manifest.json",
        "evals/companion/brain_v1/manifest.json",
        "evals/companion/conversation_quality_v1/manifest.json",
        "evals/companion/live_planner_v1/manifest.json",
        "evals/companion/planner_quality_sketch_v1/manifest.json",
        "evals/companion/planner_quality_v2/manifest.json",
    }
    assert frozen - set(DIGEST_SENTINELS) == known_unpinned, (
        "a frozen manifest appeared or lost its pin; add it to DIGEST_SENTINELS "
        "(preferred) or to known_unpinned with a reason"
    )


# ===========================================================================
# LATENCY-TAIL
# ===========================================================================


def test_latency_tail_is_green_within_ceiling() -> None:
    series = {"turn": {"p95_ms": 90.0, "p99_ms": 110.0}}
    baseline = {"turn": {"p95_ms": 100.0, "p99_ms": 120.0}}
    assert evaluate_latency_ratchet(series, baseline).status == "pass"


def test_latency_tail_reddens_on_p99_regression() -> None:
    series = {"turn": {"p95_ms": 90.0, "p99_ms": 200.0}}
    baseline = {"turn": {"p95_ms": 100.0, "p99_ms": 120.0}}
    result = evaluate_latency_ratchet(series, baseline)
    assert result.status == "fail", "a p99 spike past the ceiling must redden latency-tail"
    assert "p99_ms" in result.detail


def test_latency_ledger_skips_under_window(tmp_path: Path) -> None:
    ledger = _write_jsonl(
        tmp_path / "ledger.jsonl",
        [{"row_id": "one", "metrics": {"TurnTotal": {"p95_ms": 10.0, "p99_ms": 12.0}}}],
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({
            "window": 5,
            "metrics": {"TurnTotal": {"p95_ms": 100.0, "p99_ms": 120.0}},
        }),
        encoding="utf-8",
    )
    result = evaluate_latency_ledger(ledger=ledger, baseline_path=baseline)
    assert result.status == "skip", result.detail
    assert "rows=1 < window=5" in result.detail


def test_latency_ledger_reddens_on_seeded_spike(tmp_path: Path) -> None:
    """Source-switch self-test: enough rows + a p99 spike must redden."""

    row = {
        "row_id": "spike",
        "metrics": {"TurnTotal": {"p95_ms": 90.0, "p99_ms": 200.0}},
    }
    ledger = _write_jsonl(tmp_path / "ledger.jsonl", [row, row, row, row, row])
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({
            "window": 5,
            "metrics": {"TurnTotal": {"p95_ms": 100.0, "p99_ms": 120.0}},
        }),
        encoding="utf-8",
    )
    result = evaluate_latency_ledger(ledger=ledger, baseline_path=baseline)
    assert result.status == "fail", "a p99 spike past the ceiling must redden latency-ledger"
    assert "p99_ms" in result.detail


# ===========================================================================
# RUFF RATCHET
# ===========================================================================


def _fake_ruff(monkeypatch, fingerprints: list[str]) -> None:
    proc = SimpleNamespace(returncode=1, stdout="", stderr="")
    monkeypatch.setattr(
        "scripts.ci_gate._ruff_fingerprints", lambda root=REPO: (sorted(fingerprints), proc)
    )


def test_ruff_ratchet_is_green_when_no_new_fingerprint(tmp_path: Path, monkeypatch) -> None:
    fps = ["src/a.py::I001", "src/b.py::B009"]
    _fake_ruff(monkeypatch, fps)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"fingerprints": fps}), encoding="utf-8")
    assert evaluate_ruff(baseline_path=baseline).status == "pass"


def test_ruff_ratchet_reddens_on_new_fingerprint(tmp_path: Path, monkeypatch) -> None:
    # Baseline knows only a.py; a new violation appears in c.py.
    _fake_ruff(monkeypatch, ["src/a.py::I001", "src/c.py::F401"])
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"fingerprints": ["src/a.py::I001"]}), encoding="utf-8")
    result = evaluate_ruff(baseline_path=baseline)
    assert result.status == "fail", "a new ruff fingerprint must redden the ratchet"
    assert "src/c.py::F401" in result.detail


# ===========================================================================
# MODEL-OFF NON-INFERIORITY (subprocess; mirrors mutation-panel monkeypatch)
# ===========================================================================

_SIGLIP_BYTE_EQUAL = (
    "tests/test_siglip_real_embeddings.py::"
    "test_weights_absent_match_is_byte_identical_to_pre_neural_stub"
)


def test_model_off_gate_is_green_without_a_seed() -> None:
    proc = run_pytest([_SIGLIP_BYTE_EQUAL], timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:]


def test_model_off_gate_reddens_on_flag_off_drift() -> None:
    proc = run_pytest(
        [_SIGLIP_BYTE_EQUAL],
        plugins=["scripts.ci_selftest_seed"],
        env_extra={"CI_GATE_SEED": "flag_off_drift"},
        timeout=300,
    )
    assert proc.returncode != 0, "a flag-off drift must redden the model-off gate"
    assert "FAILED" in proc.stdout


def test_model_off_selection_is_wired_and_collectable() -> None:
    proc = run_pytest(["--collect-only", *MODEL_OFF_NODE_IDS], timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:]


# ---------------------------------------------------------------------------
# RELEASE PARITY (N27)
#
# At HEAD 8473a51 the packaged navigation config carried max_vx 0.45 against
# source 0.9, timeout_steps 400 against 200, align_enter_deg 28.0 against 55.0,
# and omitted the perception:/route_memory: blocks — while the asset test suite
# was green, because it only asserted the files EXIST. Every seed below is the
# class of regression that shipped, injected into a COPY of the tree.
# ---------------------------------------------------------------------------


def _parity_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Copy the packaged tree and the source files its manifest points at."""

    import shutil

    root = tmp_path / "repo"
    packaged = root / "src" / "parcel_robot" / "runtime_assets"
    packaged.parent.mkdir(parents=True)
    shutil.copytree(RELEASE_PARITY_MANIFEST.parent, packaged)
    manifest = json.loads((packaged / "MANIFEST.json").read_text(encoding="utf-8"))
    for entry in manifest["assets"]:
        if entry["source"] is None:
            continue
        target = root / entry["source"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(packaged / entry["packaged"], target)
    for entry in manifest["side_mirrors"]:
        for relpath in (entry["target"], entry["source"]):
            target = root / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / relpath, target)
    return root, packaged


def test_release_parity_is_green_on_the_committed_tree() -> None:
    result = evaluate_release_parity()
    assert result.status == "pass", result.detail
    # LITERAL, per the sentinel convention: 90 packaged assets + 1 side mirror.
    assert result.extra["checked"] == 91


def test_release_parity_reddens_when_a_packaged_asset_drifts_from_source(tmp_path: Path) -> None:
    root, packaged = _parity_fixture(tmp_path)
    source = root / "configs" / "navigation" / "default.yaml"
    source.write_text(source.read_text(encoding="utf-8") + "\n# seeded source edit\n", encoding="utf-8")
    result = evaluate_release_parity(manifest=packaged / "MANIFEST.json", root=root)
    assert result.status == "fail"
    assert "configs/navigation/default.yaml" in result.detail


def test_release_parity_reddens_on_an_unlisted_packaged_file(tmp_path: Path) -> None:
    root, packaged = _parity_fixture(tmp_path)
    (packaged / "configs" / "navigation" / "models" / "rogue.yaml").write_text("id: rogue\n")
    result = evaluate_release_parity(manifest=packaged / "MANIFEST.json", root=root)
    assert result.status == "fail"
    assert "rogue.yaml" in result.detail and "not in the manifest" in result.detail


def test_release_parity_reddens_when_the_side_mirror_drifts(tmp_path: Path) -> None:
    root, packaged = _parity_fixture(tmp_path)
    mirror = root / "src" / "parcel_robot" / "config" / "robot.yaml"
    mirror.write_text(mirror.read_text(encoding="utf-8") + "\n# seeded\n", encoding="utf-8")
    result = evaluate_release_parity(manifest=packaged / "MANIFEST.json", root=root)
    assert result.status == "fail"
    assert "side mirror" in result.detail


def test_release_parity_errors_when_the_manifest_is_absent(tmp_path: Path) -> None:
    result = evaluate_release_parity(manifest=tmp_path / "MANIFEST.json", root=tmp_path)
    assert result.status == "error"


# ---------------------------------------------------------------------------
# TIER COVERAGE (card R26) — the gate that can see a whole tier go dark
# ---------------------------------------------------------------------------


def _fake_collector(all_ids: set[str], commit_ids: set[str], nightly_ids: set[str]):
    def collect(markers):
        if markers is None:
            return set(all_ids), f"{len(all_ids)} tests collected"
        if markers == COMMIT_MARKERS:
            return set(commit_ids), ""
        if markers == NIGHTLY_SLOW_MARKERS:
            return set(nightly_ids), ""
        # Any OTHER expression is a narrowed selection: model it as a subset.
        return {tid for tid in nightly_ids if "e2e" not in tid}, ""

    return collect


def test_tier_coverage_is_green_on_a_clean_partition() -> None:
    result = evaluate_tier_coverage(
        collector=_fake_collector(
            {"a::t1", "b::t2", "tests/test_voice_nav_e2e.py::t3"},
            {"a::t1", "b::t2"},
            {"tests/test_voice_nav_e2e.py::t3"},
        )
    )
    assert result.status == "pass", result.detail
    assert result.extra["orphaned"] == [] and result.extra["doubled"] == []


def test_tier_coverage_reddens_when_the_nightly_selection_is_narrowed() -> None:
    """The card's named seed: a deselected test silently dropped from the nightly.

    ``nightly_markers`` is narrowed to something that no longer covers the e2e
    file — exactly the edit that would leave the audit's 42 tests unrun again.
    """

    result = evaluate_tier_coverage(
        nightly_markers="slow and not e2e",
        collector=_fake_collector(
            {"a::t1", "tests/test_voice_nav_e2e.py::t3"},
            {"a::t1"},
            {"tests/test_voice_nav_e2e.py::t3"},
        ),
    )
    assert result.status == "fail"
    assert "NEITHER tier" in result.detail
    assert "tests/test_voice_nav_e2e.py::t3" in result.detail


def test_tier_coverage_reddens_when_a_test_is_in_both_tiers() -> None:
    result = evaluate_tier_coverage(
        collector=_fake_collector({"a::t1"}, {"a::t1"}, {"a::t1"})
    )
    assert result.status == "fail"
    assert "BOTH tiers" in result.detail


def test_tier_coverage_errors_rather_than_passing_on_an_empty_collection() -> None:
    result = evaluate_tier_coverage(collector=_fake_collector(set(), set(), set()))
    assert result.status == "error"


def test_tier_coverage_is_green_against_the_real_tree() -> None:
    """Not a mock: the actual three collections over the actual test suite."""

    result = evaluate_tier_coverage()
    assert result.status == "pass", result.detail
    assert result.extra["nightly_selected"] > 0, (
        "the nightly tier selects nothing — the deselected tier is dark again"
    )
    assert (
        result.extra["commit_selected"] + result.extra["nightly_selected"]
        == result.extra["collected"]
    )


def test_both_tiers_carry_the_tier_coverage_gate_and_the_commit_tier_keeps_every_hard_entry() -> None:
    """Card R26 OWNS ``ci_gate.py`` "tier plumbing only — the commit tier's HARD
    gate list must not lose an entry". This is that constraint, executable.

    The names are listed literally rather than derived, so DELETING a gate is a
    visible edit to this list and not a silently smaller loop.
    """

    import inspect

    commit_source = inspect.getsource(run_commit_tier)
    nightly_source = inspect.getsource(run_nightly_tier)
    # Card P0-E (scrum/20260822/task_5): the commit tier is the safety core plus
    # the cheap truth checks; the evidence ratchets below moved to nightly. Both
    # lists are literal so a further re-cut is a visible edit here, not a
    # silently smaller loop.
    commit_required = (
        "evaluate_ruff",
        "evaluate_hard_safety",
        "evaluate_release_parity",
        "evaluate_assertion_evals",
        "evaluate_tier_coverage",
        "model-off-non-inferiority",
        "release-parity-integrity",
        # Card R27: the owner's store must stay unreachable from a test.
        "owner-store-isolation",
        "default-suite",
    )
    nightly_only = (
        "evaluate_frozen_digest_sentinels",
        "evaluate_latency_ledger",
        "evaluate_followbench_jerk_ledger",
        "frozen-digest-integrity",
        "mutation-panel-freshness",
        "latency-tail",
    )
    for entry in commit_required:
        assert entry in commit_source, f"the commit tier lost its {entry} gate"
        assert entry in nightly_source, f"the nightly tier lost its {entry} gate"
    for entry in nightly_only:
        assert entry in nightly_source, f"the nightly tier lost its {entry} gate"
        assert entry not in commit_source, (
            f"{entry} is a nightly evidence ratchet since card P0-E; putting it back "
            "in the commit tier is a deliberate edit of BOTH lists"
        )
    for entry in ("evaluate_mutation_panel", "evaluate_nav_instruct_candidate",
                  "evaluate_pose_drift_arms", "slow-suite", "metamorphic"):
        assert entry in nightly_source, f"the nightly tier lost its {entry} gate"


# ---------------------------------------------------------------------------
# CREDENTIAL HERMETICITY (card R26) — the offline tiers do not read the
# operator's shell. Found by the first recorded nightly; see R26_STATUS.md §3.5.
# ---------------------------------------------------------------------------


def test_the_offline_tiers_scrub_credentials(monkeypatch) -> None:
    from scripts.ci_gate import CREDENTIAL_ENV_VARS, LIVE_OPT_IN_ENV, _base_env

    for name in CREDENTIAL_ENV_VARS:
        monkeypatch.setenv(name, "sk-seeded-not-a-real-key")
    monkeypatch.delenv(LIVE_OPT_IN_ENV, raising=False)
    env = _base_env()
    for name in CREDENTIAL_ENV_VARS:
        assert name not in env, f"{name} leaked into an offline-tier subprocess"


def test_the_key_env_indirection_is_scrubbed_too(monkeypatch) -> None:
    """``PARCEL_REALTIME_KEY_ENV`` names ANOTHER variable; follow it."""

    from scripts.ci_gate import LIVE_OPT_IN_ENV, _base_env

    monkeypatch.setenv("PARCEL_REALTIME_KEY_ENV", "MY_HOUSE_KEY")
    monkeypatch.setenv("MY_HOUSE_KEY", "sk-seeded-not-a-real-key")
    monkeypatch.delenv(LIVE_OPT_IN_ENV, raising=False)
    env = _base_env()
    assert "MY_HOUSE_KEY" not in env
    assert "PARCEL_REALTIME_KEY_ENV" not in env


def test_the_explicit_live_opt_in_keeps_its_credential(monkeypatch) -> None:
    """Starving a deliberate live run of its key would be a silent skip."""

    from scripts.ci_gate import LIVE_OPT_IN_ENV, _base_env

    monkeypatch.setenv("OPENAI_API_KEY", "sk-seeded-not-a-real-key")
    monkeypatch.setenv(LIVE_OPT_IN_ENV, "1")
    assert _base_env()["OPENAI_API_KEY"] == "sk-seeded-not-a-real-key"


def test_the_lane_arming_test_states_its_own_premise() -> None:
    """The specific test the nightly caught must not read ambient credentials.

    Source-level because the failure it guards against is environmental: on a
    machine WITHOUT a credential the broken and the fixed versions are
    indistinguishable, so an outcome assertion here would pass either way.
    """

    source = (REPO / "tests" / "test_realtime_lane.py").read_text(encoding="utf-8")
    start = source.index("def test_flag_on_constructs_the_lane_and_wires_it_to_the_restricted_ingress")
    body = source[start : source.index("\ndef ", start + 10)]
    assert 'monkeypatch.setenv("OPENAI_API_KEY", "")' in body
    assert 'monkeypatch.delenv("PARCEL_REALTIME_KEY_ENV"' in body
