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

Seeds are injected into *copies* / synthetic inputs or via runtime monkeypatch —
never a committed source or frozen artifact edit (the mutation-panel rule).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.ci_gate import (
    DIGEST_SENTINELS,
    MODEL_OFF_NODE_IDS,
    evaluate_frozen_digest_sentinels,
    evaluate_hard_safety,
    evaluate_latency_ledger,
    evaluate_latency_ratchet,
    evaluate_ruff,
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
