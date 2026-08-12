"""Card J-C: the follow-bench comfort ratchet, its baseline, and the split metric.

The gate this file covers is a RATCHET, not a target: it holds the attributed
1.2187 pin (three deliberate committed changes, §3.1 of
``scrum/20260811/task_1/FOLLOWUP_DESIGNS.md``) at the same 1.20x margin the
latency tail already uses, and it is required to redden on a seeded spike and to
SKIP — never redden — when the ledger carries no measurement.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from ci_gate import (
    FOLLOWBENCH_JERK_BASELINE,
    FOLLOWBENCH_JERK_FIELD,
    FOLLOWBENCH_LEDGER,
    LATENCY_TAIL_MARGIN,
    evaluate_followbench_jerk_ledger,
    evaluate_followbench_jerk_ratchet,
)

from evals.companion_nav.metrics import (
    rms_commanded_jerk_mps3,
    rms_commanded_jerk_nominal_mps3,
)
from evals.companion_nav.run_follow_bench_v1 import build_report

BASELINE = 1.2187


def _rows() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in FOLLOWBENCH_LEDGER.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --- the gate on the real artifacts -------------------------------------------


def test_the_gate_passes_on_the_committed_ledger() -> None:
    result = evaluate_followbench_jerk_ledger()

    assert result.status == "pass", result.detail
    assert "1.2187" in result.detail
    assert "1.46244" in result.detail


def test_the_baseline_is_the_latest_shipped_row_and_carries_its_attribution() -> None:
    doc = json.loads(FOLLOWBENCH_JERK_BASELINE.read_text(encoding="utf-8"))
    shipped = [row for row in _rows() if row.get("features") == "shipped"]

    assert doc[FOLLOWBENCH_JERK_FIELD] == BASELINE
    assert shipped[-1][FOLLOWBENCH_JERK_FIELD] == BASELINE
    # A re-pin without attribution is not a baseline: three named components,
    # each with a commit range and a cause.
    components = doc["provenance"]["components"]
    assert len(components) == 3
    ranges = " ".join(str(item["range"]) for item in components)
    for commit in ("be20471", "60ecea2", "6bd945d", "dd2e857"):
        assert commit in ranges
    causes = " ".join(str(item["cause"]) for item in components)
    assert "TERMINAL_APPROACH_FLOOR_MPS" in causes
    assert "P0-A" in causes
    assert "REFUTED" in causes, "E6's band-edge guess must be corrected on the record"
    assert doc["does_not_prove"]


def test_the_duplex_mirror_agrees_with_the_baseline_and_the_ledger() -> None:
    """The pinned value lives in two places; they may never disagree silently."""

    from evals.companion.duplex_v1.run_duplex_v1 import FOLLOW_BENCH_POST_SPEED

    doc = json.loads(FOLLOWBENCH_JERK_BASELINE.read_text(encoding="utf-8"))
    shipped = [row for row in _rows() if row.get("features") == "shipped"]

    assert FOLLOW_BENCH_POST_SPEED[FOLLOWBENCH_JERK_FIELD] == doc[FOLLOWBENCH_JERK_FIELD]
    assert FOLLOW_BENCH_POST_SPEED[FOLLOWBENCH_JERK_FIELD] == shipped[-1][FOLLOWBENCH_JERK_FIELD]
    assert FOLLOW_BENCH_POST_SPEED["report"] == shipped[-1]["report"]


def test_the_ratchet_reuses_the_one_repo_wide_margin() -> None:
    """No second tolerance constant: 1.20 is imported, not restated."""

    import ci_gate

    assert LATENCY_TAIL_MARGIN == 1.20
    margins = [
        name
        for name in dir(ci_gate)
        if name.endswith("_MARGIN") and isinstance(getattr(ci_gate, name), float)
    ]
    assert margins == ["LATENCY_TAIL_MARGIN"], margins
    source = (REPO / "scripts" / "ci_gate.py").read_text(encoding="utf-8")
    assert "FOLLOWBENCH_JERK_MARGIN" not in source


# --- would it notice if it were wrong? ----------------------------------------


def test_a_seeded_spike_reddens_the_gate() -> None:
    rows = _rows()
    seeded = rows + [
        {
            "features": "shipped",
            "report": "seeded-spike.json",
            FOLLOWBENCH_JERK_FIELD: 1.47,
        }
    ]

    result = evaluate_followbench_jerk_ratchet(seeded, BASELINE)

    assert result.status == "fail", result.detail
    assert "1.4700" in result.detail
    assert "seeded-spike.json" in result.detail


def test_the_boundary_is_inclusive_and_a_hair_over_it_reddens() -> None:
    ceiling = BASELINE * LATENCY_TAIL_MARGIN

    at_ceiling = evaluate_followbench_jerk_ratchet(
        [{"features": "shipped", FOLLOWBENCH_JERK_FIELD: ceiling}], BASELINE
    )
    over = evaluate_followbench_jerk_ratchet(
        [{"features": "shipped", FOLLOWBENCH_JERK_FIELD: ceiling * 1.0000001}], BASELINE
    )

    assert at_ceiling.status == "pass"
    assert over.status == "fail"


def test_only_the_latest_shipped_row_is_judged() -> None:
    """An old spike is history; a NEW clean row must not be masked by it."""

    rows = [
        {"features": "shipped", FOLLOWBENCH_JERK_FIELD: 9.0, "report": "old.json"},
        {"features": "shipped", FOLLOWBENCH_JERK_FIELD: 1.2187, "report": "new.json"},
    ]
    assert evaluate_followbench_jerk_ratchet(rows, BASELINE).status == "pass"

    # ...and a baseline-feature spike is not a shipped regression.
    mixed = [
        {"features": "shipped", FOLLOWBENCH_JERK_FIELD: 1.2187, "report": "new.json"},
        {"features": "baseline", FOLLOWBENCH_JERK_FIELD: 9.0, "report": "base.json"},
    ]
    assert evaluate_followbench_jerk_ratchet(mixed, BASELINE).status == "pass"


def test_a_field_less_ledger_slice_skips_with_a_note_and_never_reddens() -> None:
    """A missing measurement is not evidence of a regression."""

    older = [row for row in _rows() if FOLLOWBENCH_JERK_FIELD not in row]
    assert older, "the early ledger rows predate the jerk field"

    result = evaluate_followbench_jerk_ratchet(older, BASELINE)

    assert result.status == "skip"
    assert FOLLOWBENCH_JERK_FIELD in result.detail
    assert result.hard is True, "a skip on a hard gate must stay a hard gate"

    empty = evaluate_followbench_jerk_ratchet([], BASELINE)
    assert empty.status == "skip"


def test_a_null_or_malformed_measurement_never_passes_silently() -> None:
    assert (
        evaluate_followbench_jerk_ratchet(
            [{"features": "shipped", FOLLOWBENCH_JERK_FIELD: None}], BASELINE
        ).status
        == "skip"
    )
    assert (
        evaluate_followbench_jerk_ratchet(
            [{"features": "shipped", FOLLOWBENCH_JERK_FIELD: "1.2"}], BASELINE
        ).status
        == "error"
    )
    assert (
        evaluate_followbench_jerk_ratchet(
            [{"features": "shipped", FOLLOWBENCH_JERK_FIELD: float("nan")}], BASELINE
        ).status
        == "error"
    )


def test_a_baseline_without_provenance_is_an_error_not_a_pass(tmp_path: Path) -> None:
    naked = tmp_path / "jerk_baseline.json"
    naked.write_text(json.dumps({FOLLOWBENCH_JERK_FIELD: 1.2187}), encoding="utf-8")

    result = evaluate_followbench_jerk_ledger(baseline_path=naked)

    assert result.status == "error"
    assert "provenance" in result.detail

    missing = evaluate_followbench_jerk_ledger(baseline_path=tmp_path / "nope.json")
    assert missing.status == "error"


# --- the additive nominal metric ----------------------------------------------


def test_the_nominal_variant_equals_the_inclusive_one_with_no_emergency_steps() -> None:
    vx = [0.0, 0.2, 0.5, 0.4, 0.1, 0.0]
    vy = [0.0, 0.0, 0.1, 0.1, 0.0, 0.0]
    flags = [False] * len(vx)

    assert rms_commanded_jerk_nominal_mps3(vx, vy, flags, 0.1) == pytest.approx(
        rms_commanded_jerk_mps3(vx, vy, 0.1), rel=0, abs=0
    )


def test_the_nominal_variant_drops_every_window_touching_an_emergency_step() -> None:
    """The discontinuity is visible from BOTH sides, so the window is dropped."""

    vx = [0.10, 0.10, 0.10, 0.00, 0.10, 0.10, 0.10]
    vy = [0.0] * 7
    flags = [False, False, False, True, False, False, False]

    inclusive = rms_commanded_jerk_mps3(vx, vy, 0.1)
    nominal = rms_commanded_jerk_nominal_mps3(vx, vy, flags, 0.1)

    assert inclusive > 0.0
    assert nominal == 0.0, "only the flat windows survive, and they are jerk-free"


def test_the_nominal_variant_is_none_rather_than_zero_when_nothing_qualifies() -> None:
    assert rms_commanded_jerk_nominal_mps3([0.1, 0.2, 0.3], [0.0] * 3, [True] * 3, 0.1) is None
    assert rms_commanded_jerk_nominal_mps3([0.1, 0.2], [0.0, 0.0], [False, False], 0.1) is None
    with pytest.raises(ValueError):
        rms_commanded_jerk_nominal_mps3([0.1], [0.0, 0.0], [False, False], 0.1)
    with pytest.raises(ValueError):
        rms_commanded_jerk_nominal_mps3([0.1, 0.2, 0.3], [0.0] * 3, [False] * 3, 0.0)


def test_the_report_aggregate_is_additive_over_the_committed_one() -> None:
    """Every pre-existing aggregate field survives, by name; two are added."""

    committed = json.loads(
        (
            REPO
            / "evals"
            / "companion_nav"
            / "results"
            / "follow-bench-v1-20260811023618Z-93eba090.json"
        ).read_text(encoding="utf-8")
    )
    fresh = build_report([], robot_config="x")["aggregate"]

    assert set(fresh) - set(committed["aggregate"]) == {
        "mean_rms_commanded_jerk_nominal_mps3",
        "nominal_jerk_episode_count",
    }
    assert not set(committed["aggregate"]) - set(fresh), "no pre-existing field was renamed"


# --- runtime/replica parity for the new flag ----------------------------------


@pytest.mark.parametrize("ramp", [False, True])
def test_the_recorded_emergency_flag_matches_the_shaper_bypass_every_tick(
    ramp: bool,
) -> None:
    """The one duplicated predicate in the batch, held in lockstep by measurement.

    ``_DispatchReplica.step`` records the per-step ``emergency`` flag while
    ``_shape`` decides the bypass; the two must agree on EVERY tick of a real
    episode, in both flag states, or the additive metric is fiction.
    """

    from dataclasses import replace as dataclass_replace

    from evals.companion_nav import runner as runner_module
    from evals.companion_nav.runner import BenchFeatures, FollowBenchRunner
    from evals.companion_nav.scenarios import scenario_by_id

    runner = FollowBenchRunner(features=BenchFeatures())
    runner.motion_shaping = dataclass_replace(runner.motion_shaping, nominal_stop_ramp=ramp)

    observed: list[tuple[bool, bool]] = []
    original_step = runner_module.SCurveVelocityShaper.step
    original_shape = runner_module._DispatchReplica._shape

    def shape(self, command, **kwargs):
        seen: list[bool] = []

        def step(shaper_self, target, *, dt_s, emergency=False, stop=None):
            # A ramp tick is by construction NOT an emergency bypass.
            seen.append(bool(emergency))
            return original_step(
                shaper_self, target, dt_s=dt_s, emergency=emergency, stop=stop
            )

        runner_module.SCurveVelocityShaper.step = step
        try:
            result = original_shape(self, command, **kwargs)
        finally:
            runner_module.SCurveVelocityShaper.step = original_step
        observed.append((self.last_emergency, any(seen)))
        return result

    runner_module._DispatchReplica._shape = shape
    try:
        runner.run(scenario_by_id("owner_stops"))
    finally:
        runner_module._DispatchReplica._shape = original_shape

    assert observed, "the episode must have dispatched"
    mismatched = [index for index, (a, b) in enumerate(observed) if a != b]
    assert not mismatched, f"emergency flag disagreed with the bypass on ticks {mismatched[:5]}"
    if ramp:
        # The card's whole claim: with the flag on those stop ticks became
        # RAMPS, so they are no longer emergency bypasses.
        assert not any(flag for flag, _ in observed)
    else:
        assert any(flag for flag, _ in observed), "owner_stops must contain real stop ticks"
