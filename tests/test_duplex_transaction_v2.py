"""Capability proof for the DMC-2 trace/oracle separation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACK = REPO_ROOT / "research" / "20260829" / "duplex-transaction-2"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dmc2_runner_is_deterministic_and_does_not_self_adjudicate() -> None:
    runner = _load("parcel_dmc2_runner", PACK / "run.py")
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))

    first = runner.run_suite(manifest, trials=1)
    second = runner.run_suite(manifest, trials=1)

    assert len(first["traces"]) == 33
    assert first["normalized_trace_sha256"] == second["normalized_trace_sha256"]
    assert first["trace_chain_root_sha256"] == second["trace_chain_root_sha256"]
    assert first["architecture_gate"]["status"] == "NOT_EVALUABLE_RED"
    assert all(
        "expected" not in row and "oracle_pass" not in row
        for row in first["traces"]
    )
    assert all(item["passed"] is None for item in first["hypotheses"].values())


def test_dmc2_independent_oracle_accepts_partial_rows_but_not_partial_population() -> None:
    runner = _load("parcel_dmc2_runner_for_oracle", PACK / "run.py")
    verifier = _load("parcel_dmc2_verifier", PACK / "verify_results.py")
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    partial = runner.run_suite(manifest, trials=1)
    # Result payload metadata normally added by main().
    partial["started_utc"] = "2026-08-29T00:00:00Z"
    partial["duration_s"] = 0.0
    partial["result_sha256"] = verifier.digest(
        {key: value for key, value in partial.items() if key != "result_sha256"}
    )

    checked = verifier.verify_one(partial, manifest)

    assert checked["H1_passed"] is True
    assert checked["H2_passed"] is True
    assert checked["H3_passed"] is True
    assert checked["passed"] is False
    assert checked["errors"] == [
        "case inventory mismatch",
        "result is not the complete frozen population",
        "trial count mismatch",
    ]
