"""``scrum/20260814/task_1/DISK_LEDGER.md`` is generated, and this is its pin.

Card **S-1** item 6 (``scrum/20260814/task_1/REVISED_BOARD.md``). The finding:
operator-facing disk arithmetic in the 20260813 status pack was derived from
the superseded **84.60 MiB/s** model (``PSK_STATUS.md`` M9 builds a whole
ledger on ``84.60 × 60 / 1024``, concluding "≈425 GiB free required" and
"256 GiB buys ≈45 min"). The current generated model is **91.87 MiB/s**, so
those figures are ~8.6% low: the free-space requirement is understated and a
take sized by them would truncate. Historical scrum is immutable, so the fix
is a superseding RUN-SPECIFIC ledger under 20260814/task_1, rendered from
``budget.py``'s own model and pinned here exactly the way
``tests/test_bandwidth_budget_doc.py`` pins ``BANDWIDTH_BUDGET.md``:

1. the committed file must be byte-identical to :func:`render_disk_ledger`;
2. the headline figures are parsed back OUT of the committed markdown and
   compared against :func:`build_budget` — the check that catches a hand edit;
3. a reconstruction of the 84.60-era arithmetic is shown to FAIL check 2, so
   the oracle provably rejects the stale numbers it exists to replace.

Regenerate with::

    .parcel/bin/python -m tests.test_disk_ledger_doc --emit
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from scripts.parcel_capture.budget import (
    GIB,
    RECOMMENDED_PROFILE,
    build_budget,
    recorder_verdict,
)

#: The stale headline the 20260813 operator pack derived from. Literals on
#: purpose — deriving them from the code would make the guard agree with
#: itself. ``PSK_STATUS.md`` M9: 84.60 MiB/s → 4.957 GiB/min → ≈425 GiB free
#: for the whole script → ≈45 min at 256 GiB.
STALE_MIB_PER_S = 84.60
STALE_GIB_PER_MIN = 4.957
STALE_WHOLE_SCRIPT_FREE_GIB = 425.0
STALE_MINUTES_AT_256_GIB = 45.0

#: Reservation rows the operator actually uses on the day.
RESERVE_MINUTES = (10, 20, 30, 60)

#: Free-space rows: the plausible states of the record target.
FREE_GIB_ROWS = (256, 512, 1024, 2048)


def ledger_path() -> Path:
    return REPO_ROOT / "scrum" / "20260814" / "task_1" / "DISK_LEDGER.md"


def render_disk_ledger() -> str:
    """The whole run-specific operator disk ledger, derived rather than typed.

    Byte-stable: no timestamps, no host lookups, no measurement at render
    time. Every figure comes from ``budget.build_budget(RECOMMENDED_PROFILE)``
    — the same model that renders ``BANDWIDTH_BUDGET.md`` — so the operator
    sheet and the budget document cannot disagree.
    """

    plan = build_budget(RECOMMENDED_PROFILE)
    verdict, margin_x = recorder_verdict(plan.bytes_per_second)
    gib_per_min = plan.bytes_per_second * 60.0 / GIB

    out: list[str] = []
    w = out.append
    w("# Disk ledger — run-specific operator figures (2026-08-14, card S-1)")
    w("")
    w("> ## ⚠ GENERATED FILE — do not hand-edit")
    w(">")
    w("> Every number below is rendered by")
    w("> `tests/test_disk_ledger_doc.py::render_disk_ledger()` from")
    w("> `scripts/parcel_capture/budget.py`'s current model. Hand-editing is a")
    w("> defect: `tests/test_disk_ledger_doc.py` reddens until it is reverted.")
    w(">")
    w("> ```")
    w("> .parcel/bin/python -m tests.test_disk_ledger_doc --emit    # regenerate")
    w("> ```")
    w("")
    w(f"**Plan of record:** `{plan.profile.label}` · "
      f"**{plan.mib_per_second:.2f} MiB/s** · {plan.gib_per_hour:.2f} GiB/hour · "
      f"{plan.bytes_per_second / 1e6:.1f} MB/s")
    w(f"**Recorder-ceiling verdict:** {verdict} (×{margin_x:.2f} against the low "
      f"field-report reading) — a model, not a measurement of this Orin.")
    w("")
    w("## 1. What one minute costs")
    w("")
    w("| | rate |")
    w("|---|---:|")
    w(f"| per second | {plan.mib_per_second:.2f} MiB |")
    w(f"| per minute | {gib_per_min:.3f} GiB |")
    w(f"| per hour | {plan.gib_per_hour:.2f} GiB |")
    w("")
    w(f"## 2. Reserve before a take (recorder margin ×{1.0 + plan.margin:.2f} included)")
    w("")
    w("| take length | free space required |")
    w("|---|---:|")
    for minutes in RESERVE_MINUTES:
        w(f"| {minutes} min | {plan.required_free_gib(minutes * 60.0):.1f} GiB |")
    w("")
    w("A take may start only when the record target's measured free space covers")
    w("the row for its planned length. The margin is the same 15% the recorder's")
    w("own `SpaceBudget` refuses under, so a take this table clears is a take the")
    w("recorder will agree to start.")
    w("")
    w("## 3. What the free space you actually have buys")
    w("")
    w("| free on record target | recording time |")
    w("|---|---:|")
    for gib in FREE_GIB_ROWS:
        minutes = plan.session_hours(gib * GIB) * 60.0
        w(f"| {gib} GiB | {minutes:.1f} min |")
    w("")
    w("## 4. Supersession notice — the 84.60-era arithmetic is history")
    w("")
    w("The 20260813 status pack derived operator figures from the superseded")
    w(f"**{STALE_MIB_PER_S:.2f} MiB/s** model (`PSK_STATUS.md` M9: "
      f"{STALE_GIB_PER_MIN:.3f} GiB/min, ≈{STALE_WHOLE_SCRIPT_FREE_GIB:.0f} GiB "
      f"free for the whole script, ≈{STALE_MINUTES_AT_256_GIB:.0f} min at 256 GiB; "
      f"`PSL_STATUS.md` repeats the same base rate).")
    w(f"Those figures are ~{(plan.mib_per_second / STALE_MIB_PER_S - 1.0) * 100:.1f}% "
      f"low: the free-space requirement is understated and a take sized by them")
    w("would truncate. **Nothing operator-facing may derive from them.** The")
    w("historical sheets stay as provenance (working agreement 3); THIS ledger is")
    w("the run-use replacement, and its pin fails if it drifts from the model.")
    w("")
    w("## 5. What this ledger does not know")
    w("")
    w("- The Orin's actual free space — unmeasured until H-1/H-2 (`df -h` on the")
    w("  record target is the day's first evidence).")
    w("- Whether the recorder sustains this rate on the Orin — the rate is a")
    w("  model; `TONIGHT_CHECKLIST.md` N3 (fio tail) and N4 (real `ros2 bag")
    w("  record` for ten minutes) are the measurements, and neither has run.")
    w("- Anything about a profile other than the plan of record; re-render after")
    w("  any budget-model change.")
    w("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Layer 1: the whole-file sentinel
# ---------------------------------------------------------------------------


def test_committed_ledger_is_byte_identical_to_the_generator() -> None:
    committed = ledger_path()
    assert committed.exists(), (
        f"{committed} is missing; emit it with "
        f".parcel/bin/python -m tests.test_disk_ledger_doc --emit"
    )
    assert committed.read_text(encoding="utf-8") == render_disk_ledger(), (
        "DISK_LEDGER.md diverges from render_disk_ledger(); the committed ledger "
        "was hand-edited or the budget model moved. Regenerate — never hand-edit."
    )


# ---------------------------------------------------------------------------
# Layer 2: the headline figures are re-derived from the committed markdown
# ---------------------------------------------------------------------------

_RATE_LINE = re.compile(r"\*\*(?P<mib>[0-9.]+) MiB/s\*\* · (?P<gibh>[0-9.]+) GiB/hour")
_PER_MIN_LINE = re.compile(r"\| per minute \| (?P<gib>[0-9.]+) GiB \|")
_RESERVE_LINE = re.compile(r"\| (?P<minutes>\d+) min \| (?P<gib>[0-9.]+) GiB \|")
_FREE_LINE = re.compile(r"\| (?P<free>\d+) GiB \| (?P<minutes>[0-9.]+) min \|")


def _headline_check(text: str) -> list[str]:
    """Compare a ledger text's figures against the live model; return errors."""

    plan = build_budget(RECOMMENDED_PROFILE)
    errors: list[str] = []
    rate = _RATE_LINE.search(text)
    if rate is None:
        return ["no headline rate line found"]
    if abs(float(rate.group("mib")) - plan.mib_per_second) > 0.005:
        errors.append(
            f"headline MiB/s is {rate.group('mib')}, model computes "
            f"{plan.mib_per_second:.2f}"
        )
    if abs(float(rate.group("gibh")) - plan.gib_per_hour) > 0.005:
        errors.append(
            f"headline GiB/hour is {rate.group('gibh')}, model computes "
            f"{plan.gib_per_hour:.2f}"
        )
    per_min = _PER_MIN_LINE.search(text)
    if per_min is None:
        errors.append("no per-minute row found")
    elif abs(float(per_min.group("gib")) - plan.bytes_per_second * 60.0 / GIB) > 0.0005:
        errors.append(f"per-minute GiB is {per_min.group('gib')}, model disagrees")
    reserves = {int(m.group("minutes")): float(m.group("gib")) for m in _RESERVE_LINE.finditer(text)}
    for minutes in RESERVE_MINUTES:
        expected = plan.required_free_gib(minutes * 60.0)
        if minutes not in reserves:
            errors.append(f"no reserve row for {minutes} min")
        elif abs(reserves[minutes] - expected) > 0.05:
            errors.append(
                f"reserve for {minutes} min is {reserves[minutes]}, model computes "
                f"{expected:.1f}"
            )
    frees = {int(m.group("free")): float(m.group("minutes")) for m in _FREE_LINE.finditer(text)}
    for gib in FREE_GIB_ROWS:
        expected = plan.session_hours(gib * GIB) * 60.0
        if gib not in frees:
            errors.append(f"no free-space row for {gib} GiB")
        elif abs(frees[gib] - expected) > 0.05:
            errors.append(
                f"runtime at {gib} GiB is {frees[gib]} min, model computes "
                f"{expected:.1f}"
            )
    return errors


def test_headline_figures_in_the_ledger_are_the_ones_the_code_computes() -> None:
    errors = _headline_check(ledger_path().read_text(encoding="utf-8"))
    assert not errors, "; ".join(errors)


# ---------------------------------------------------------------------------
# Layer 3: the stale 84.60-era arithmetic provably fails the check above
# ---------------------------------------------------------------------------


def test_the_stale_84_60_era_ledger_fails_the_headline_check() -> None:
    """Reconstruct PSK M9's arithmetic in this ledger's shape and watch the
    oracle reject every row of it. Without this cell, layer 2 could be green
    because it compares nothing."""

    plan = build_budget(RECOMMENDED_PROFILE)
    stale_bytes_per_second = STALE_MIB_PER_S * 1024 * 1024
    lines = [
        (
            f"**Plan of record:** `stale` · **{STALE_MIB_PER_S:.2f} MiB/s** · "
            f"{stale_bytes_per_second * 3600 / GIB:.2f} GiB/hour · x MB/s"
        ),
        f"| per minute | {STALE_GIB_PER_MIN:.3f} GiB |",
    ]
    for minutes in RESERVE_MINUTES:
        gib = math.ceil(stale_bytes_per_second * minutes * 60 * 1.15 / GIB * 10) / 10
        lines.append(f"| {minutes} min | {gib:.1f} GiB |")
    for gib in FREE_GIB_ROWS:
        minutes = gib * GIB / (stale_bytes_per_second * 1.15) / 60.0
        lines.append(f"| {gib} GiB | {minutes:.1f} min |")
    errors = _headline_check("\n".join(lines))
    assert errors, "the stale reconstruction passed the oracle; the oracle is dead"
    # Every figure class must be caught, not just one.
    joined = "; ".join(errors)
    assert "headline MiB/s" in joined
    assert "per-minute" in joined
    for minutes in RESERVE_MINUTES:
        assert f"reserve for {minutes} min" in joined
    # And the specific operator-facing conclusions the pack drew are wrong now:
    assert plan.session_hours(256 * GIB) * 60.0 < STALE_MINUTES_AT_256_GIB, (
        "256 GiB buys LESS than the stale 45 min claim; if this ever flips, the "
        "supersession notice must be re-argued, not deleted"
    )


def test_the_committed_ledger_never_quotes_a_stale_operator_figure() -> None:
    """The stale rate may appear only in the supersession notice, never as a
    figure of record in the tables."""

    text = ledger_path().read_text(encoding="utf-8")
    tables = [
        line for line in text.splitlines() if line.startswith("|") and "---" not in line
    ]
    joined = "\n".join(tables)
    for stale in (f"{STALE_MIB_PER_S:.2f}", f"{STALE_GIB_PER_MIN:.3f}", "425", "148.7"):
        assert stale not in joined, (
            f"stale 84.60-era figure {stale!r} appears in a ledger table; nothing "
            f"operator-facing may derive from the superseded model"
        )
    assert "Supersession notice" in text


if __name__ == "__main__":
    if "--emit" in sys.argv:
        target = ledger_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_disk_ledger(), encoding="utf-8")
        print(f"wrote {target}")
    else:
        print(__doc__)
