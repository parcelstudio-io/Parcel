"""D-O4: DUPLEX_V1 eval hard gates + nav regression pin."""

from __future__ import annotations

import json
from pathlib import Path

from evals.companion.duplex_v1.run_duplex_v1 import (
    EMBODIED_POST_SPEED,
    FOLLOW_BENCH_POST_SPEED,
    build_report,
    main,
)


def test_duplex_v1_hard_gates_pass() -> None:
    report = build_report()
    assert report["hard_gates_pass"] is True
    gates = report["hard_gates"]
    assert gates["ttft_p50_under_1s"]
    assert gates["no_response_over_2s_without_filler"]
    assert gates["act_continuity_zero_missing"]
    assert gates["barge_in_atomicity"]
    assert gates["shadow_round_trip"]
    assert gates["nav_regression_unchanged"]
    assert gates["filler_no_consecutive_repeats"]
    assert report["metrics"]["response_ceiling_breaches"] == 0
    assert "does_not_prove" in report
    assert len(report["does_not_prove"]) >= 3


def test_nav_regression_pins_post_speed_raise_rows() -> None:
    report = build_report()
    nav = report["nav_regression"]
    latest = nav["follow_bench_latest_shipped"]
    assert latest["follow_success"] == FOLLOW_BENCH_POST_SPEED["follow_success"]
    assert latest["hard_collision_total"] == FOLLOW_BENCH_POST_SPEED["hard_collision_total"]
    assert latest["navigate_success"] == FOLLOW_BENCH_POST_SPEED["navigate_success"]
    assert nav["embodied_post_speed"]["simulator_step_count"] == (
        EMBODIED_POST_SPEED["simulator_step_count"]
    )


def test_duplex_v1_cli_writes_report_and_ledger(tmp_path: Path) -> None:
    code = main(["--out", str(tmp_path)])
    assert code == 0
    reports = list(tmp_path.glob("duplex-v1-*.json"))
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text(encoding="utf-8"))
    assert payload["hard_gates_pass"] is True
    ledger_lines = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(ledger_lines) == 1
    entry = json.loads(ledger_lines[0])
    assert entry["suite"] == "duplex-v1"
    assert entry["hard_gates_pass"] is True
