"""The load guard, proved in BOTH directions. Card R26, work item 3.

A guard is only a guard if it can be shown to do two things: refuse to measure a
contended machine, and *not* refuse anything else. A guard tested only in the
skipping direction is indistinguishable from ``pytest.skip()`` at the top of the
file — which is the failure mode this card's Definition of Done names explicitly
("a load-guard that skips unconditionally" must be a RED seed).

Every threshold assertion here is anchored to the four load readings recorded in
the repo's own status docs (``scrum/20260819/task_1/R8_STATUS.md`` and
``scrum/20260820/task_2/R13_STATUS.md``), so the pin cannot drift away from the
evidence that produced it without a test noticing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts import load_guard
from scripts.load_guard import (
    BUSY_FRACTION,
    MAX_DEADLINE_STRETCH,
    MIN_ABSOLUTE_LOAD,
    MODE_ENV,
    LoadGuardMisconfigured,
    ceiling,
    contention_reason,
    deadline,
    read_mode,
    snapshot,
)

REPO = Path(__file__).resolve().parents[1]

#: The recorded gate runs the pin is derived from: (1-min load, CPUs, was it red).
RECORDED_GATE_RUNS = (
    (66.6, 192, True, "R8 gate 03:55:56Z"),
    (66.6, 192, True, "R8 gate 04:02:32Z"),
    (65.0, 192, True, "R13 first gate"),
    (50.0, 192, False, "R8 green gate"),
    (20.0, 192, False, "R13 green gate"),
)

#: Every test carrying ``load_sensitive``. Enumerated rather than discovered so
#: that removing a marker is a visible edit to THIS list and not a silent loss.
GUARDED_TESTS = {
    "tests/test_cpu_budget_proxy.py": {
        "test_build_report_includes_budget_and_does_not_prove",
        "test_cli_writes_json",
    },
    "tests/test_dynamic_costs.py": {"test_cost_field_vectorization_performance"},
}


# --- the guard does not skip a quiet machine -------------------------------


def test_an_idle_machine_is_never_skipped() -> None:
    assert contention_reason(load1=0.0, cpus=192, mode="on") is None
    assert contention_reason(load1=0.5, cpus=4, mode="on") is None
    assert contention_reason(load1=1.4, cpus=1, mode="on") is None


def test_the_guard_is_not_welded_shut_on_this_machine() -> None:
    """The anti-''skips unconditionally'' seed, run against the live readings.

    Whatever the load is right now, feeding the guard an idle reading from the
    SAME code path must produce no skip. If someone replaces the body of
    ``contention_reason`` with ``return "busy"`` this fails, and it fails on a
    machine at any load — which a test that only checks today's real reading
    would not.
    """

    live = snapshot()
    assert live["mode"] in {"on", "off"}
    assert isinstance(live["cpus"], int) and live["cpus"] >= 1
    assert contention_reason(load1=0.0, cpus=live["cpus"], mode="on") is None


# --- ... and does skip a contended one -------------------------------------


def test_a_contended_machine_is_skipped_with_the_numbers_in_the_reason() -> None:
    reason = contention_reason(load1=120.0, cpus=192, mode="on")
    assert reason is not None
    assert "120.00" in reason, "the reason must carry the measurement, not just a verdict"
    assert "192" in reason
    assert f"{BUSY_FRACTION:.2f}" in reason, "the reason must carry the threshold it applied"
    assert "R26" in reason, "a skip with no owner is how these tests became unowned"
    assert "nightly" in reason, "the reason must say where the coverage is not lost"


@pytest.mark.parametrize(("load1", "cpus", "was_red", "label"), RECORDED_GATE_RUNS)
def test_the_pin_separates_every_recorded_red_from_every_recorded_green(
    load1: float, cpus: int, was_red: bool, label: str
) -> None:
    """The threshold is measurement-derived; this is the measurement."""

    skipped = contention_reason(load1=load1, cpus=cpus, mode="on") is not None
    assert skipped is was_red, (
        f"{label}: load {load1} over {cpus} CPUs was "
        f"{'RED' if was_red else 'green'} in the record, but the guard "
        f"{'skips' if skipped else 'measures'} it"
    )


def test_a_small_machine_is_not_permanently_contended() -> None:
    """``MIN_ABSOLUTE_LOAD`` is what stops a 2-core runner never running them."""

    assert ceiling(2) == pytest.approx(MIN_ABSOLUTE_LOAD)
    assert contention_reason(load1=1.0, cpus=2, mode="on") is None
    assert contention_reason(load1=9.0, cpus=2, mode="on") is not None


# --- the mode switch is fail-closed ----------------------------------------


def test_the_nightly_mode_never_skips() -> None:
    assert contention_reason(load1=10_000.0, cpus=1, mode="off") is None


def test_an_unrecognised_mode_raises_rather_than_guessing() -> None:
    assert read_mode({}) == "on"
    assert read_mode({MODE_ENV: "OFF"}) == "off"
    with pytest.raises(LoadGuardMisconfigured):
        read_mode({MODE_ENV: "0"})
    with pytest.raises(LoadGuardMisconfigured):
        read_mode({MODE_ENV: "false"})
    with pytest.raises(LoadGuardMisconfigured):
        read_mode({MODE_ENV: "disabled"})


# --- the scaled deadline ---------------------------------------------------


def test_a_quiet_machine_gets_exactly_the_deadline_the_author_wrote() -> None:
    assert deadline(2.0, load1=0.0, cpus=192, mode="on") == 2.0
    assert deadline(2.0, load1=57.0, cpus=192, mode="on") == 2.0


def test_the_deadline_grows_with_contention_and_stops_growing() -> None:
    stretched = deadline(2.0, load1=115.2, cpus=192, mode="on")
    assert stretched == pytest.approx(4.0), "0.60 busy fraction is 2x the 0.30 ceiling"
    capped = deadline(2.0, load1=192_000.0, cpus=192, mode="on")
    assert capped == pytest.approx(2.0 * MAX_DEADLINE_STRETCH)
    assert capped < 1e9, "an unbounded deadline is timeout=None wearing a disguise"


def test_the_deadline_never_shrinks() -> None:
    for load1 in (0.0, 10.0, 57.6, 100.0, 5_000.0):
        assert deadline(2.0, load1=load1, cpus=192, mode="on") >= 2.0


# --- the marker is really on the tests that need it ------------------------


def _marked_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            attribute = decorator.func if isinstance(decorator, ast.Call) else decorator
            if (
                isinstance(attribute, ast.Attribute)
                and attribute.attr == "load_sensitive"
                and isinstance(attribute.value, ast.Attribute)
                and attribute.value.attr == "mark"
            ):
                found.add(node.name)
    return found


@pytest.mark.parametrize("relpath", sorted(GUARDED_TESTS))
def test_every_wall_clock_assertion_still_carries_the_guard(relpath: str) -> None:
    """A marker silently dropped is a wall-clock assertion back in the hard gate."""

    assert _marked_functions(REPO / relpath) == GUARDED_TESTS[relpath], (
        f"{relpath}: the set of load_sensitive tests moved. That is a decision — "
        "update GUARDED_TESTS here and say why in the status doc."
    )


def test_the_guarded_set_is_not_empty_and_not_the_whole_suite() -> None:
    """A guard applied to nothing is decoration; applied to everything, a delete."""

    total = sum(len(names) for names in GUARDED_TESTS.values())
    assert 1 <= total <= 8, f"{total} guarded tests is not a handful of wall-clock pins"


def test_the_marker_is_registered_so_it_cannot_be_a_typo() -> None:
    conftest = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "load_sensitive:" in conftest
    assert "pytest_runtest_setup" in conftest, (
        "the marker is inert unless conftest actually consults the guard at setup"
    )


def test_the_nightly_tier_forces_the_guarded_tests_to_run() -> None:
    """Relocation, not deletion: the nightly must switch the guard off.

    Without this, every tier could skip them and the coverage would be gone
    while every gate stayed green — which is the exact shape of the defect this
    card exists to close.
    """

    from scripts.ci_gate import NIGHTLY_ENV

    assert NIGHTLY_ENV.get(MODE_ENV) == load_guard.MODE_OFF
    assert read_mode({MODE_ENV: NIGHTLY_ENV[MODE_ENV]}) == load_guard.MODE_OFF
