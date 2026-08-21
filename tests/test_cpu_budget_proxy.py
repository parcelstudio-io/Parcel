"""CPU-budget proxy smoke (K7 / HR-6 desktop stand-in).

Card R26 note. Both tests here assert ``within_budget is True``, and
``within_budget`` is a **wall-clock** comparison: the measured median tick of the
10 Hz hot path against a 176 ms ceiling. On an idle machine that measures the
code. On a machine running the owner's inference stack it measures the machine —
``test_build_report_includes_budget_and_does_not_prove`` reddened three recorded
commit-gate runs across cards R8 and R13 for exactly that reason, with no owning
card. Both now carry ``load_sensitive`` (``scripts/load_guard.py``), which skips
them with a reason carrying the measured load rather than failing an unrelated
card's gate — and the nightly tier runs them with the guard OFF, so the coverage
is not lost, only relocated to the tier where the load is controlled.

The audit named three such tests; this file holds two of them. ``test_cli_writes
_json`` was not on the audit's list and is the fourth instance of the same class,
found by reading the assertion rather than the failure history: it has not
reddened a recorded gate yet, which is precisely why it was invisible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.cpu_budget_proxy import build_report, main


@pytest.mark.load_sensitive
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


def test_build_report_shape_holds_under_any_load(tmp_path: Path) -> None:
    """The non-timing half of the smoke above, with no wall-clock assertion.

    Split out on purpose: the schema, the readiness tag, the ``does_not_prove``
    disclosure and the fallback-note check are all deterministic, and they were
    being skipped along with the timing assertion whenever the machine was busy.
    Coverage of everything that does not depend on the clock is therefore
    UNCONDITIONAL — the guard now costs exactly the one assertion it has to.
    """

    report = build_report(
        ticks=8,
        hz=10.0,
        directive="go to the coffee shop at 42nd street",
        warmup=2,
        budget_median_ms=176.0,
    )
    assert report["schema"] == "parcel.cpu_budget_proxy.v1"
    assert report["hardware_readiness"] == "HR-6"
    assert report["profile"]["latency_ms"]["median"] >= 0.0
    assert report["budget"]["median_ms"] == 176.0
    assert "within_budget" in report["budget"]
    assert "Orin NX" in report["does_not_prove"][0]
    assert all("scan_missing_fallback" not in note for note in report["profile"]["last_notes"])


@pytest.mark.load_sensitive
def test_cli_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "cpu.json"
    rc = main(["--ticks", "5", "--warmup", "1", "--output", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["card"] == "K7"
    assert payload["budget"]["within_budget"] is True


def test_cli_writes_json_shape_under_any_load(tmp_path: Path) -> None:
    """The CLI's contract minus the timing verdict — never skipped."""

    out = tmp_path / "cpu.json"
    rc = main(["--ticks", "5", "--warmup", "1", "--output", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["card"] == "K7"
    assert payload["schema"] == "parcel.cpu_budget_proxy.v1"
    assert "within_budget" in payload["budget"]
