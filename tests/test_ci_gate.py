"""Self-test for the CI gate — proof each hard gate is not theatre.

Mirrors ``scripts/mutation_panel.py``'s discipline: a green gate proves nothing
unless it goes RED for the right reason. For every hard regression gate the
runner enforces, this file seeds the exact class of regression the verdict names
and asserts the gate reddens — then asserts it is green on a clean input:

* MODEL-OFF NON-INFERIORITY  <- a flag-off drift (SigLIP fallback perturbed)
* HARD-SAFETY                <- an injected collision, and a new false_arrival
* LATENCY-TAIL               <- a p95/p99 spike past the ratchet ceiling
* FROZEN-DIGEST INTEGRITY    <- a byte-changed frozen manifest
* RUFF RATCHET               <- a new (file, rule) fingerprint, and (card
                                GATE-0) a baseline recorded on a different ruff
* TIER COVERAGE (card R26)   <- a narrowed nightly selection that orphans a tier
* STAGE CONTAINMENT (GATE-0) <- an evaluator that raises must still leave a
                                complete summary and a complete --json

Seeds are injected into *copies* / synthetic inputs or via runtime monkeypatch —
never a committed source or frozen artifact edit (the mutation-panel rule).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci_gate import (
    CI_GATE_NESTED_ENV,
    COMMIT_MARKERS,
    COMMIT_TIER_STAGE_NAMES,
    DIGEST_SENTINELS,
    MODEL_OFF_NODE_IDS,
    NIGHTLY_SLOW_MARKERS,
    RELEASE_PARITY_MANIFEST,
    XDIST_MAX_WORKERS,
    XDIST_WORKERS_ENV,
    GateResult,
    evaluate_default_suite,
    evaluate_frozen_digest_sentinels,
    evaluate_hard_safety,
    evaluate_latency_ledger,
    evaluate_latency_ratchet,
    evaluate_release_parity,
    evaluate_ruff,
    evaluate_tier_coverage,
    main,
    resolve_xdist_workers,
    run_commit_tier,
    run_nightly_tier,
    run_pytest,
    run_stage,
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


#: Card GATE-0: the linter the synthetic baselines below claim to be recorded on.
_FAKE_RUFF_VERSION = "9.9.9"


def _fake_ruff(monkeypatch, fingerprints: list[str], version: str = _FAKE_RUFF_VERSION) -> None:
    proc = SimpleNamespace(returncode=1, stdout="", stderr="")
    monkeypatch.setattr(
        "scripts.ci_gate._ruff_fingerprints", lambda root=REPO: (sorted(fingerprints), proc)
    )
    monkeypatch.setattr("scripts.ci_gate.ruff_version", lambda root=REPO: version)


def _baseline(path: Path, fingerprints: list[str], version: str | None = _FAKE_RUFF_VERSION) -> Path:
    payload: dict = {"fingerprints": fingerprints}
    if version is not None:
        payload["ruff_version"] = version
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_ruff_ratchet_is_green_when_no_new_fingerprint(tmp_path: Path, monkeypatch) -> None:
    fps = ["src/a.py::I001", "src/b.py::B009"]
    _fake_ruff(monkeypatch, fps)
    baseline = _baseline(tmp_path / "baseline.json", fps)
    assert evaluate_ruff(baseline_path=baseline).status == "pass"


def test_ruff_ratchet_reddens_on_new_fingerprint(tmp_path: Path, monkeypatch) -> None:
    # Baseline knows only a.py; a new violation appears in c.py.
    _fake_ruff(monkeypatch, ["src/a.py::I001", "src/c.py::F401"])
    baseline = _baseline(tmp_path / "baseline.json", ["src/a.py::I001"])
    result = evaluate_ruff(baseline_path=baseline)
    assert result.status == "fail", "a new ruff fingerprint must redden the ratchet"
    assert "src/c.py::F401" in result.detail


# --- card GATE-0: the ratchet knows which linter it was recorded on --------
#
# The defect: ruff was range-pinned (`>=0.12,<1`) and the baseline recorded no
# version, so the commit verdict depended on whichever wheel pip resolved that
# day — this tree yields 7 fingerprints on 0.16.x and roughly 51 on 0.15.x. A
# ratchet compared across rule sets is not a gate, it is a coin flip that
# usually lands green.


def test_the_ratchet_refuses_a_baseline_recorded_on_another_ruff(
    tmp_path: Path, monkeypatch
) -> None:
    fps = ["src/a.py::I001"]
    _fake_ruff(monkeypatch, fps, version="0.15.0")
    baseline = _baseline(tmp_path / "baseline.json", fps, version="0.16.1")
    result = evaluate_ruff(baseline_path=baseline)
    assert result.status == "error", (
        "the same fingerprint set under a different linter is a different "
        "question; the ratchet must refuse rather than answer it"
    )
    assert "0.15.0" in result.detail and "0.16.1" in result.detail
    assert result.hard, "an unrenderable verdict still fails the build"


def test_the_ratchet_refuses_an_unstamped_baseline(tmp_path: Path, monkeypatch) -> None:
    fps = ["src/a.py::I001"]
    _fake_ruff(monkeypatch, fps)
    baseline = _baseline(tmp_path / "baseline.json", fps, version=None)
    result = evaluate_ruff(baseline_path=baseline)
    assert result.status == "error"
    assert "ruff_version" in result.detail


def test_the_ratchet_refuses_when_the_running_ruff_cannot_be_identified(
    tmp_path: Path, monkeypatch
) -> None:
    fps = ["src/a.py::I001"]
    _fake_ruff(monkeypatch, fps, version=None)  # ruff --version unreadable
    baseline = _baseline(tmp_path / "baseline.json", fps, version="0.16.1")
    result = evaluate_ruff(baseline_path=baseline)
    assert result.status == "error"
    assert "unknown linter" in result.detail


def test_the_committed_baseline_and_the_pyproject_pin_agree() -> None:
    """The two halves of the pin are in different files; they must not drift."""

    import re

    from scripts.ci_gate import RUFF_BASELINE

    stamped = json.loads(RUFF_BASELINE.read_text(encoding="utf-8"))["ruff_version"]
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'"ruff==([0-9][^"]*)"', pyproject)
    assert match, "the dev extra must PIN ruff (`ruff==X.Y.Z`), not range it"
    assert match.group(1) == stamped, (
        f"pyproject pins ruff=={match.group(1)} but "
        f"{RUFF_BASELINE.name} was recorded on {stamped}"
    )


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
    # LITERAL, per the sentinel convention: 105 packaged assets + 1 side mirror.
    # SI v4 and v5 each added three frozen persona snapshots on 2026-08-26.
    assert result.extra["checked"] == 106


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
        # Card GATE-0: the vendored-simulator closure. Both tiers, because the
        # nightly is a superset and a fresh clone has to reach it either way.
        "evaluate_unitree_assets",
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


# ===========================================================================
# STAGE CONTAINMENT — card GATE-0 (scrum/20260822/task_20)
#
# `run_commit_tier` used to be a straight-line list build. On a clean clone the
# Go2 MJCF was gitignored, `evaluate_hard_safety` raised about a second in, and
# the traceback took the whole runner with it: no summary, no `--json`, and
# eight later gates that nobody ever learned the verdict of. The gate's own
# failure mode was invisible to the gate. Every stage now runs under
# `run_stage`, and these are the seeds that prove it.
# ===========================================================================


def _stub_stage(name: str, tier: str = "commit") -> GateResult:
    return GateResult(name, tier, True, "pass", "stub")


@pytest.fixture
def fast_commit_tier(monkeypatch):
    """Every commit-tier evaluator replaced by a cheap green stub.

    The tier itself is REAL — this exercises the actual `run_commit_tier`
    ordering and the actual wrapper, not a re-implementation of them. Only the
    five-minute evaluators are stubbed out.
    """

    import scripts.ci_gate as gate

    monkeypatch.setattr(gate, "evaluate_ruff", lambda **kw: _stub_stage("ruff"))
    monkeypatch.setattr(
        gate, "evaluate_unitree_assets", lambda **kw: _stub_stage("unitree-assets")
    )
    monkeypatch.setattr(gate, "evaluate_hard_safety", lambda **kw: _stub_stage("hard-safety"))
    monkeypatch.setattr(
        gate, "evaluate_release_parity", lambda **kw: _stub_stage("release-parity")
    )
    monkeypatch.setattr(
        gate, "evaluate_assertion_evals", lambda **kw: _stub_stage("assertion-evals")
    )
    monkeypatch.setattr(
        gate, "evaluate_tier_coverage", lambda **kw: _stub_stage("tier-coverage")
    )
    monkeypatch.setattr(
        gate, "_pytest_gate", lambda name, tier, ids, **kw: _stub_stage(name, tier)
    )
    # ---- CARD XD-1 addendum A1 --------------------------------------------
    # `default-suite` used to be one more `_pytest_gate` call, so the stub above
    # covered it. When this card made it two phases it moved to its own
    # evaluator, and this fixture -- unchanged -- stopped covering the one stage
    # that runs NINE THOUSAND tests. Every test below then called the real
    # `evaluate_default_suite`, which launched the whole suite in a subprocess
    # FROM INSIDE A TEST; under xdist those nest, and on 2026-08-23 five chained
    # runs put 986 python processes and 237 GB on this host and the kernel
    # OOM-killed the machine. `test_without_the_stub_...` below is the seeded
    # proof that the hole was real; this line is its closure.
    monkeypatch.setattr(
        gate,
        "evaluate_default_suite",
        lambda **kw: _stub_stage("default-suite", kw.get("tier", "commit")),
    )
    # ---- END CARD XD-1 addendum A1 ----------------------------------------
    return gate


def test_the_clean_commit_tier_reports_exactly_the_declared_stages(fast_commit_tier) -> None:
    """The control for every seed below."""

    results = run_commit_tier()
    assert tuple(r.name for r in results) == COMMIT_TIER_STAGE_NAMES
    assert all(r.status == "pass" for r in results)


def test_the_asset_stage_runs_before_the_gate_that_used_to_die_on_it() -> None:
    names = list(COMMIT_TIER_STAGE_NAMES)
    assert names.index("unitree-assets") < names.index("hard-safety"), (
        "hard-safety is the gate that raised on the missing MJCF; the payload "
        "check has to speak first or the report still blames the wrong thing"
    )


#: The victim, and how many of the ten commit-tier rows it can cost. One per
#: stage that calls it: ``evaluate_ruff`` and ``evaluate_hard_safety`` back one
#: stage each, while ``_pytest_gate`` is the shared helper behind THREE
#: (model-off-non-inferiority, release-parity-integrity, owner-store-isolation).
#: It backed FOUR until card XD-1 moved ``default-suite`` onto its own
#: ``evaluate_default_suite``; that stage is listed separately now, so the total
#: is unchanged and the move is visible instead of silent. The number is written
#: down rather than counted from the result, so a fifth pytest stage reddens
#: this test on purpose.
EXPLODING_VICTIMS = [
    ("evaluate_ruff", 1),
    ("evaluate_hard_safety", 1),
    ("_pytest_gate", 3),
    ("evaluate_default_suite", 1),
]


@pytest.mark.parametrize(("victim", "expected_rows"), EXPLODING_VICTIMS)
def test_one_exploding_evaluator_costs_exactly_one_row(
    fast_commit_tier, victim: str, expected_rows: int
) -> None:
    """Seeded RED. Anywhere in the tier — first, middle, or the pytest gates —
    a raising evaluator becomes a NAMED error on exactly the stages it backs and
    the rest still run.

    Corrected by FINISH-1 (task_29 §C7): the test asserted only that SOME row
    errored, so "costs exactly one row" was in its name and nowhere in its
    body — a containment gate that let the blast radius grow silently. The
    count is now asserted, and it is per-victim because ``_pytest_gate`` really
    does back four stages: one evaluator, one row; one shared helper, its own
    four.
    """

    def boom(*args, **kwargs):
        raise ValueError("seeded: this evaluator explodes")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(fast_commit_tier, victim, boom)
    try:
        results = run_commit_tier()
    finally:
        monkey.undo()

    assert tuple(r.name for r in results) == COMMIT_TIER_STAGE_NAMES, (
        "a crash must not shorten the report"
    )
    errored = [r for r in results if r.status == "error"]
    assert errored, "the crash has to be visible as an ERROR row"
    assert len(errored) == expected_rows, (
        f"seeding {victim} cost {[r.name for r in errored]}; this evaluator backs "
        f"{expected_rows} stage(s) and containment means the blast radius is exactly that"
    )
    for row in errored:
        assert "ValueError" in row.detail
        assert "seeded: this evaluator explodes" in row.detail
        assert row.hard, "containment reports the failure, it does not forgive it"
        assert "traceback_tail" in row.extra
    assert any(r.status == "pass" for r in results), "later gates still ran"


def test_the_json_summary_still_emits_when_the_first_evaluator_raises(
    fast_commit_tier, capsys
) -> None:
    """The headline row: `--json` used to never print at all."""

    def boom(**kwargs):
        raise RuntimeError("seeded: no Go2 assets in this checkout")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(fast_commit_tier, "evaluate_ruff", boom)
    try:
        exit_code = main(["--tier", "commit", "--json"])
    finally:
        monkey.undo()

    out = capsys.readouterr().out
    assert exit_code == 1, "a contained ERROR is still a red build"

    summary, brace, raw_json = out.partition("\n{")
    assert brace, "the JSON block never printed — the exact defect this closes"
    assert "Traceback (most recent call last)" not in summary, (
        "the human summary must REPORT the crash, not bleed it"
    )
    assert "RESULT: FAIL" in summary
    assert "[ ERROR] HARD  ruff" in summary

    payload = json.loads("{" + raw_json)
    assert payload["tier"] == "commit"
    names = [gate["name"] for gate in payload["gates"]]
    assert names == list(COMMIT_TIER_STAGE_NAMES), (
        f"--json must name every stage even on a crash; got {names}"
    )
    assert payload["gates"][0]["status"] == "error"
    # The traceback survives INSIDE the machine-readable payload on purpose: a
    # contained crash still has to be diagnosable without re-running the gate.
    assert "RuntimeError" in payload["gates"][0]["extra"]["traceback_tail"]


def test_a_keyboard_interrupt_is_not_swallowed(fast_commit_tier) -> None:
    """`except Exception`, never `BaseException`: an operator's Ctrl-C is not a
    gate result, and a runner that turns it into one cannot be stopped."""

    def interrupted(**kwargs):
        raise KeyboardInterrupt

    monkey = pytest.MonkeyPatch()
    monkey.setattr(fast_commit_tier, "evaluate_hard_safety", interrupted)
    try:
        with pytest.raises(KeyboardInterrupt):
            run_commit_tier()
    finally:
        monkey.undo()


def test_a_system_exit_is_not_swallowed_either(fast_commit_tier) -> None:
    def leaving(**kwargs):
        raise SystemExit(3)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(fast_commit_tier, "evaluate_tier_coverage", leaving)
    try:
        with pytest.raises(SystemExit):
            run_commit_tier()
    finally:
        monkey.undo()


def test_the_wrapper_flattens_multi_result_stages() -> None:
    """Some evaluators return a list (the nightly's pose-drift arms). The
    wrapper must not wrap a list inside a list."""

    rows = [_stub_stage("a"), _stub_stage("b")]
    assert run_stage("multi", lambda: rows, tier="commit") == rows
    assert run_stage("single", lambda: rows[0], tier="commit") == [rows[0]]


def test_the_traceback_tail_is_bounded() -> None:
    from scripts.ci_gate import STAGE_TRACEBACK_TAIL_CHARS

    def deep(n: int = 60):
        if n:
            return deep(n - 1)
        raise ValueError("x" * 5000)

    row = run_stage("deep", deep, tier="commit")[0]
    assert row.status == "error"
    assert len(row.extra["traceback_tail"]) <= STAGE_TRACEBACK_TAIL_CHARS
    assert len(row.detail) < 400, "a gate report is read by humans"


# ---------------------------------------------------------------------------
# THE PARALLEL DEFAULT SUITE (card XD-1, scrum/20260822/task_14)
#
# The commit tier's `default-suite` runs `-n min(cpu_count, XDIST_MAX_WORKERS)`
# — 16 here, 8 on the Orin, NEVER `auto`, see addendum A3 below — and then the
# wall-clock assertions serially. The thing that can go silently wrong is not
# speed, it is COVERAGE: a phase-A marker expression that stops excluding
# `load_sensitive` puts wall-clock pins back under worker contention (they
# measure the machine and redden an unrelated card's gate), and a phase-B
# expression that is not the exact complement drops tests out of the tier while
# both phases stay green.
#
# So the partition is proved SEMANTICALLY — the two expressions are evaluated
# over every combination of the two markers — rather than by string-matching the
# source, which would pass for any pair of literals that happened to contain the
# right words.
# ---------------------------------------------------------------------------


def _selects(expr: str, *, slow: bool, load_sensitive: bool) -> bool:
    """Evaluate a pytest ``-m`` expression the way pytest does: as a boolean."""

    return bool(eval(expr, {"__builtins__": {}}, {"slow": slow, "load_sensitive": load_sensitive}))


def test_the_two_default_suite_phases_partition_the_commit_tier() -> None:
    from scripts.ci_gate import default_suite_phases

    parallel, serial = default_suite_phases()
    for slow in (False, True):
        for load_sensitive in (False, True):
            flags = {"slow": slow, "load_sensitive": load_sensitive}
            in_tier = _selects(COMMIT_MARKERS, **flags)
            in_a = _selects(parallel, **flags)
            in_b = _selects(serial, **flags)
            assert in_a or in_b or not in_tier, (
                f"{flags} is in the commit tier and in NEITHER phase — the two "
                f"phases are not a cover: {parallel!r} / {serial!r}"
            )
            assert not (in_a and in_b), (
                f"{flags} is in BOTH phases — it would be run twice and a "
                f"wall-clock pin would be measured under xdist: {parallel!r} / {serial!r}"
            )
            assert (in_a or in_b) == in_tier, (
                f"{flags} is selected by a phase but is not in the commit tier"
            )


def test_no_wall_clock_assertion_can_reach_the_parallel_phase() -> None:
    """The card's named seed: a ``load_sensitive`` test run under xdist."""

    from scripts.ci_gate import default_suite_phases

    parallel, _serial = default_suite_phases()
    assert not _selects(parallel, slow=False, load_sensitive=True)


def test_the_phases_are_derived_from_the_tier_and_not_written_out_twice() -> None:
    """Change the tier expression and BOTH phases must follow it."""

    from scripts.ci_gate import default_suite_phases

    parallel, serial = default_suite_phases("not slow and not e2e")
    assert "not slow and not e2e" in parallel and "not slow and not e2e" in serial
    # ... and the parenthesisation must survive, or `and`/`or` would rebind.
    assert parallel.startswith("(") and serial.startswith("(")


def _capture_phases(monkeypatch, returncodes=(0, 0), stdouts=("1 passed", "1 passed")):
    from scripts import ci_gate

    calls: list[dict] = []

    def fake_run_pytest(selection, **kwargs):
        index = len(calls)
        calls.append({"selection": selection, **kwargs})
        return SimpleNamespace(
            returncode=returncodes[index], stdout=stdouts[index], stderr=""
        )

    monkeypatch.setattr(ci_gate, "run_pytest", fake_run_pytest)
    # These tests are about the phases, not about the A2 recursion guard; when
    # this file is itself run BY the gate the mark is set in the environment and
    # `evaluate_default_suite` would (correctly) refuse before reaching them.
    monkeypatch.delenv(CI_GATE_NESTED_ENV, raising=False)
    result = ci_gate.evaluate_default_suite(tier="commit")
    return result, calls


def test_the_parallel_phase_is_parallel_and_the_serial_phase_is_serial(monkeypatch) -> None:
    result, calls = _capture_phases(monkeypatch)

    assert result.status == "pass", result.detail
    assert len(calls) == 2, "default-suite is exactly two phases"
    parallel, serial = calls
    assert "not load_sensitive" in parallel["markers"]
    assert "-n" in parallel["extra_args"], "phase A must actually run under xdist"
    assert "--dist" in parallel["extra_args"]
    assert "load_sensitive" in serial["markers"]
    assert "not load_sensitive" not in serial["markers"]
    assert "-n" not in (serial["extra_args"] or []), (
        "phase B exists BECAUSE it is serial; running it under xdist is the "
        "defect this split repairs"
    )
    assert result.extra["seconds"].keys() == {"parallel", "serial"}


def test_a_red_serial_phase_reddens_the_row_even_when_the_parallel_phase_is_green(
    monkeypatch,
) -> None:
    """A fast green phase A must not be able to hide phase B's verdict."""

    result, calls = _capture_phases(
        monkeypatch,
        returncodes=(0, 1),
        stdouts=("9000 passed", "FAILED tests/test_dynamic_costs.py::t\n1 failed"),
    )
    assert len(calls) == 2, "phase B runs even when phase A is green"
    assert result.status == "fail"
    assert "tests/test_dynamic_costs.py::t" in result.detail


def test_a_red_parallel_phase_still_runs_the_serial_phase(monkeypatch) -> None:
    """A gate that stops at the first red reports half a verdict."""

    result, calls = _capture_phases(
        monkeypatch,
        returncodes=(1, 0),
        stdouts=("FAILED tests/test_x.py::t\n1 failed", "10 passed"),
    )
    assert len(calls) == 2
    assert result.status == "fail"
    assert result.extra["returncodes"] == {"parallel": 1, "serial": 0}


def test_the_commit_tier_runs_the_two_phase_default_suite() -> None:
    import inspect

    source = inspect.getsource(run_commit_tier)
    assert "evaluate_default_suite" in source, (
        "the commit tier stopped calling the two-phase runner — that is a "
        "deliberate edit, and it belongs in this test too"
    )
    assert "default-suite" in source


def test_the_nightly_default_suite_is_still_serial_and_that_is_deliberate() -> None:
    """Card XD-1 changed the COMMIT tier only.

    The nightly runs with ``PARCEL_LOAD_GUARD=off`` precisely so the wall-clock
    assertions cannot skip; it is the tier where time is available and
    determinism is worth more than speed. Flipping it is allowed — but it is a
    decision, and this test is where it becomes visible.
    """

    import inspect

    source = inspect.getsource(run_nightly_tier)
    assert "evaluate_default_suite" not in source
    assert 'markers=COMMIT_MARKERS' in source


# ---------------------------------------------------------------------------
# THE GATE MUST NOT BE ABLE TO RUN ITSELF (card XD-1 addendum, rows A1-A3)
#
# Owner-mandated after 2026-08-23 05:38. The failure was not a bug in a test; it
# was a bug in a FIXTURE, and its blast radius was the whole machine:
#
#   1. `default-suite` moved from `_pytest_gate` to `evaluate_default_suite`.
#   2. `fast_commit_tier` stubbed the former and not the latter, so ~8 tests in
#      this file called the REAL evaluator and each spawned the entire 9,000-test
#      suite in a subprocess.
#   3. Under `-n auto` (192 workers here) those subprocesses each spawned 192
#      more. Five chained runs 29 s apart = 986 python processes, 237 GB; the
#      kernel OOM-killed Cursor and every agent session on the box.
#
# Three independent things had to be wrong at once, so three things are pinned
# here: the fixture covers every stage (A1), the gate refuses to run the default
# suite from inside a gate-spawned pytest (A2), and the worker count is derived
# and capped rather than `auto` (A3). Any ONE of them would have been enough.
# ---------------------------------------------------------------------------


class _SeededSuiteLaunch(RuntimeError):
    """Raised by the tripwire below INSTEAD of running a real pytest."""


def _run_pytest_tripwire(calls: list[dict]):
    """A `run_pytest` that RECORDS what would have run and then refuses to.

    This is what makes the A1 proof affordable: the hole is demonstrated by the
    arguments the gate was about to hand to a subprocess, not by paying for the
    subprocess. Nothing in this file ever starts a real suite.
    """

    def record_and_raise(selection, **kwargs):
        calls.append({"selection": tuple(selection), **kwargs})
        raise _SeededSuiteLaunch(
            "seeded tripwire: a stubbed commit tier tried to spawn pytest"
        )

    return record_and_raise


def test_the_stubbed_commit_tier_never_spawns_a_pytest_subprocess(
    fast_commit_tier, monkeypatch
) -> None:
    """Row A1, the closure. Not one stage of `run_commit_tier` reaches a
    subprocess once `fast_commit_tier` has stubbed it -- which is the whole
    premise of every containment seed in this file."""

    monkeypatch.delenv(CI_GATE_NESTED_ENV, raising=False)
    calls: list[dict] = []
    monkeypatch.setattr(fast_commit_tier, "run_pytest", _run_pytest_tripwire(calls))

    results = run_commit_tier()

    assert calls == [], (
        "a stubbed tier reached a real pytest: "
        + "; ".join(f"markers={c.get('markers')!r} args={c.get('extra_args')!r}" for c in calls)
    )
    assert tuple(r.name for r in results) == COMMIT_TIER_STAGE_NAMES
    assert all(r.status == "pass" for r in results), [
        (r.name, r.status) for r in results if r.status != "pass"
    ]


def test_without_the_stub_the_default_suite_stage_would_launch_the_whole_suite(
    fast_commit_tier, monkeypatch
) -> None:
    """Row A1, SEEDED RED: the hole, reproduced, without paying for it.

    Undo exactly the one line A1 added to `fast_commit_tier` -- the fixture as
    it stood between 16:19 on 08-22 and this addendum -- and the tripwire
    catches the default-suite stage about to run `pytest -m "(not slow) and not
    load_sensitive" -n <N>` from inside a test. That is the recursion. With the
    stub in place (the test above) the tripwire records nothing.
    """

    monkeypatch.delenv(CI_GATE_NESTED_ENV, raising=False)
    calls: list[dict] = []
    monkeypatch.setattr(fast_commit_tier, "run_pytest", _run_pytest_tripwire(calls))
    monkeypatch.setattr(fast_commit_tier, "evaluate_default_suite", evaluate_default_suite)

    results = run_commit_tier()

    assert len(calls) == 1, "exactly the default-suite stage had the hole"
    launched = calls[0]
    assert launched["selection"] == (), "no node-id list: this is the WHOLE suite"
    assert launched["markers"] == "(not slow) and not load_sensitive", launched["markers"]
    assert "-n" in launched["extra_args"], (
        "and it is the parallel phase, so the subprocess fans out again"
    )

    # The stage is contained (GATE-0's wrapper), which is exactly why nobody
    # noticed: the tier still reported ten rows and the runaway was invisible.
    errored = [r for r in results if r.status == "error"]
    assert [r.name for r in errored] == ["default-suite"]
    assert "_SeededSuiteLaunch" in errored[0].detail
    assert tuple(r.name for r in results) == COMMIT_TIER_STAGE_NAMES


def test_run_pytest_stamps_the_nesting_mark_into_every_child(monkeypatch) -> None:
    """Row A2. The mark is set by the DRIVER, so it covers every gate stage."""

    from scripts import ci_gate

    seen: dict[str, str] = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs["env"])
        return SimpleNamespace(returncode=0, stdout="1 passed", stderr="")

    monkeypatch.setattr(ci_gate.subprocess, "run", fake_run)
    run_pytest(("tests/test_ci_gate.py::test_the_traceback_tail_is_bounded",))

    assert seen[CI_GATE_NESTED_ENV] == "1"


def test_the_default_suite_refuses_to_run_inside_a_gate_spawned_pytest(
    monkeypatch,
) -> None:
    """Row A2. The refusal is a NAMED ERROR ROW, not a silent skip and not a
    pass: a gate that quietly did not run the suite would be worse than one that
    ran it twice."""

    from scripts import ci_gate

    calls: list[dict] = []
    monkeypatch.setenv(CI_GATE_NESTED_ENV, "1")
    monkeypatch.setattr(ci_gate, "run_pytest", _run_pytest_tripwire(calls))

    row = ci_gate.evaluate_default_suite(tier="commit")

    assert calls == [], "the refusal has to come BEFORE the subprocess"
    assert row.status == "error"
    assert row.hard, "a gate that could not run its suite is not a pass"
    assert row.extra["nested"] is True
    assert CI_GATE_NESTED_ENV in row.detail, "the row has to name the cause"


def test_a_targeted_gate_stage_is_still_allowed_inside_a_gate_spawned_pytest(
    monkeypatch,
) -> None:
    """Row A2's boundary. `_pytest_gate` runs a BOUNDED node-id list; nesting one
    costs a few tests, not a fan-out, and the gate's own self-tests depend on it.
    Refusing everything would have been the easy over-correction."""

    from scripts import ci_gate

    calls: list[tuple] = []

    def fake_run_pytest(selection, **kwargs):
        calls.append(tuple(selection))
        return SimpleNamespace(returncode=0, stdout="3 passed", stderr="")

    monkeypatch.setenv(CI_GATE_NESTED_ENV, "1")
    monkeypatch.setattr(ci_gate, "run_pytest", fake_run_pytest)

    row = ci_gate._pytest_gate("model-off-non-inferiority", "commit", ("tests/a.py::t",))

    assert row.status == "pass"
    assert calls == [("tests/a.py::t",)]


def test_the_mark_run_pytest_writes_is_the_mark_the_default_suite_refuses_on(
    monkeypatch,
) -> None:
    """Row A2, end to end. Two halves that agree only because they share a
    constant would still pass if the constant were never actually written into
    the child; this feeds the ACTUAL child environment back in."""

    from scripts import ci_gate

    child_env: dict[str, str] = {}

    def fake_run(cmd, **kwargs):
        child_env.update(kwargs["env"])
        return SimpleNamespace(returncode=0, stdout="1 passed", stderr="")

    monkeypatch.setattr(ci_gate.subprocess, "run", fake_run)
    run_pytest(("tests/a.py::t",))
    assert child_env, "the driver built no environment at all"

    # Become that child.
    monkeypatch.setattr(ci_gate.os, "environ", child_env)
    calls: list[dict] = []
    monkeypatch.setattr(ci_gate, "run_pytest", _run_pytest_tripwire(calls))
    row = ci_gate.evaluate_default_suite(tier="commit")

    assert row.status == "error" and calls == []


@pytest.mark.parametrize(
    "raw", ["auto", "logical", "AUTO", " auto ", "", "   ", "eight", "0", "-4", "3.5"]
)
def test_the_worker_count_is_never_auto_and_never_nonsense(raw: str) -> None:
    """Row A3. `auto` is 192 workers on this host; that is the number that
    OOM-killed it. No input reaches xdist as anything but a positive integer."""

    workers, why = resolve_xdist_workers(None, {XDIST_WORKERS_ENV: raw})

    assert workers.isdigit(), workers
    assert 1 <= int(workers) <= XDIST_MAX_WORKERS
    assert why, "a substituted worker count must carry its reason"


def test_a_refused_worker_setting_says_so_instead_of_silently_substituting() -> None:
    """Row A3. The provenance string is not decoration -- it is what makes a
    timing row honest about what actually ran."""

    _workers, why = resolve_xdist_workers(None, {XDIST_WORKERS_ENV: "auto"})
    assert "REFUSED" in why and "auto" in why

    _workers, why = resolve_xdist_workers(None, {XDIST_WORKERS_ENV: "eight"})
    assert "not a positive worker count" in why


def test_an_explicit_worker_pin_is_honoured_even_above_the_cap() -> None:
    """Row A3. The cap stops an ACCIDENT (`auto` on a 192-thread box). A person
    who types a number is not an accident, and a gate that overrules them would
    make `PARCEL_XDIST_WORKERS` a lie."""

    workers, why = resolve_xdist_workers(None, {XDIST_WORKERS_ENV: "48"})
    assert workers == "48"
    assert "honoured" in why and XDIST_WORKERS_ENV in why

    workers, why = resolve_xdist_workers("2", {XDIST_WORKERS_ENV: "48"})
    assert workers == "2", "the caller's argument outranks the environment"
    assert "argument" in why


@pytest.mark.parametrize(
    ("cpus", "expected"),
    [(8, "8"), (16, "16"), (192, "16"), (1, "1")],
    ids=["orin-nx-8-core", "at-the-cap", "dev-box-192-thread", "single-core"],
)
def test_the_default_worker_count_is_cpu_count_capped(
    monkeypatch, cpus: int, expected: str
) -> None:
    """Row A3 + the hardware row. On the Go2 EDU+'s onboard Orin NX (8 cores)
    the default resolves to 8 -- exactly what `auto` would have chosen, so the
    cap costs the target hardware nothing. It only bites this dev box."""

    monkeypatch.setattr("os.cpu_count", lambda: cpus)
    workers, why = resolve_xdist_workers(None, {})

    assert workers == expected
    assert f"cpu_count={cpus}" in why and f"cap={XDIST_MAX_WORKERS}" in why


def test_the_resolved_worker_count_reaches_the_command_line_and_the_row(
    monkeypatch,
) -> None:
    """Row A3. A recorded number that is not the number that ran is worse than
    no number, so the same value is asserted in both places."""

    monkeypatch.setenv(XDIST_WORKERS_ENV, "3")
    result, calls = _capture_phases(monkeypatch)

    parallel = calls[0]
    assert parallel["extra_args"][:2] == ["-n", "3"]
    assert result.extra["workers"] == "3"
    assert "honoured" in result.extra["workers_provenance"]
    assert "-n 3" in result.detail
