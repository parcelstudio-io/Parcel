"""CPU-budget proxy smoke (K7 / HR-6 desktop stand-in)."""

from __future__ import annotations

import json
from pathlib import Path

from evals.cpu_budget_proxy import build_report, main


def test_build_report_includes_budget_and_does_not_prove(tmp_path: Path) -> None:
    report = build_report(
        ticks=8,
        hz=10.0,
        directive="go to the coffee shop at 42nd street",
        warmup=2,
        budget_median_ms=176.0,
    )
    assert report["schema"] == "parcel.cpu_budget_proxy.v1"
    assert report["hardware_readiness"] == "HR-6"
    assert report["budget"]["within_budget"] is True
    assert report["profile"]["latency_ms"]["median"] >= 0.0
    assert "Orin NX" in report["does_not_prove"][0]
    assert all("scan_missing_fallback" not in note for note in report["profile"]["last_notes"])


def test_cli_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "cpu.json"
    rc = main(["--ticks", "5", "--warmup", "1", "--output", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["card"] == "K7"
    assert payload["budget"]["within_budget"] is True
