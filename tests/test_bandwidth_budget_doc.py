"""``BANDWIDTH_BUDGET.md`` is generated, and this is the sentinel that says so.

Card **PS-P**, tranche PS-3. The finding these tests exist for:

    BANDWIDTH_BUDGET.md was STALE BY 8.6% and it was the number of record on
    every sheet the operator holds. The doc said 84.60 MiB/s / 297.4 GiB/h /
    342.1 GiB / 114.1 GiB; budget.py computed 91.870 / 322.98 / 371.5 / 123.9.

The document was hand-maintained and went stale within one day of the PS-H
channel corrections. Hand-maintained arithmetic goes stale again, so the fix is
structural: the document is rendered from
:func:`scripts.parcel_capture.budget.render_document` and these tests fail if
the committed bytes diverge from what the code computes.

Three layers, deliberately, because each catches a different way of going wrong:

1. :func:`test_committed_document_is_byte_identical_to_the_generator` — the
   whole-file sentinel. Catches any hand edit and any model change.
2. :func:`test_headline_numbers_in_the_document_are_the_ones_the_code_computes`
   — parses the four headline figures back **out** of the committed markdown
   and compares them to :func:`build_budget`. This is the test that would have
   caught the original finding, and :func:`test_the_stale_document_fails_the_headline_check`
   proves it does by running it against a reconstruction of the stale text.
3. :func:`test_a_model_change_reddens_the_freshness_check` — seeds a change in
   the *load model* and asserts the sentinel notices. Without this, layer 1
   could be passing because nothing is actually being compared.

The precedent is ``scripts/ci_gate.py``'s frozen-digest sentinels, with one
difference: a frozen digest pins bytes to a constant, and this pins bytes to
*what the code computes*, which is the property that actually failed here.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from scripts.parcel_capture import budget as budget_mod
from scripts.parcel_capture.budget import (
    CANDIDATE_PROFILES,
    DROP_LADDER,
    RECOMMENDED_PROFILE,
    ROSBAG2_CEILING_MB_S,
    build_budget,
    document_path,
    recorder_verdict,
    render_document,
)

#: The four figures the finding named, as they appeared in the stale document.
#: Literals on purpose: deriving them from the code would make this test agree
#: with itself. They are what the operator was reading on 2026-08-13.
STALE_MIB_PER_S = 84.60
STALE_GIB_PER_HOUR = 297.4
STALE_ONE_HOUR_RESERVE_GIB = 342.1
STALE_TWENTY_MINUTE_RESERVE_GIB = 114.1


def _plan_budget():
    return build_budget(RECOMMENDED_PROFILE)


def _short_budget():
    return build_budget(RECOMMENDED_PROFILE, session_duration_s=1200.0)


# ---------------------------------------------------------------------------
# Layer 1: the whole-file sentinel
# ---------------------------------------------------------------------------


def test_committed_document_is_byte_identical_to_the_generator() -> None:
    """The committed document must equal what ``budget.py`` renders, exactly.

    If this fails the document has been hand-edited, or the model moved and
    nobody re-rendered. Both are the same defect from the operator's seat: the
    sheet in their hand disagrees with the code.
    """

    path = document_path()
    assert path.is_file(), f"{path} is missing; run --emit-doc"
    assert path.read_text(encoding="utf-8") == render_document(), (
        "BANDWIDTH_BUDGET.md has diverged from budget.py::render_document(). "
        "Regenerate it: .parcel/bin/python -m scripts.parcel_capture.budget --emit-doc"
    )


def test_render_is_byte_stable_across_calls() -> None:
    """A sentinel that compares against a moving target is not a sentinel.

    No timestamp, no hostname, no measurement taken at render time.
    """

    assert render_document() == render_document()


def test_the_document_announces_that_it_is_generated() -> None:
    """An operator who opens the file must be told not to hand-edit it."""

    text = document_path().read_text(encoding="utf-8")
    assert "GENERATED FILE — do not hand-edit" in text
    assert "--emit-doc" in text
    assert "--check-doc" in text


# ---------------------------------------------------------------------------
# Layer 2: the headline numbers, parsed back out of the markdown
# ---------------------------------------------------------------------------


def _headline_from_markdown(text: str) -> dict[str, float]:
    """Pull the four figures the operator actually reads out of the document.

    Deliberately parses the *rendered markdown* rather than calling the model:
    the whole finding was that the markdown and the model disagreed, so a check
    that reads the model twice would have passed while the sheet was wrong.
    """

    found: dict[str, float] = {}

    # The plan-of-record row of the decision table: the label, then the two
    # emphasised whole-rig figures. Tolerant of surrounding bold markers and of
    # extra columns, because the table's shape is allowed to change — and
    # tolerant of BOTH spellings of the profile label ("848x480@30 CDI" as the
    # code renders it, "848×480@30 C+D+IR" as the hand-maintained document wrote
    # it) so that running this against the pre-fix file fails on the NUMBER
    # rather than on a label mismatch. The point of the test is the arithmetic.
    label = (
        rf"{RECOMMENDED_PROFILE.width}\s*[x×]\s*{RECOMMENDED_PROFILE.height}"
        rf"@{RECOMMENDED_PROFILE.fps}\s*(?:CDI|C\+D\+IR)"
    )
    row = re.search(
        r"^\|\s*\*{0,2}"
        + label
        + r"\*{0,2}\s*\|\s*\*{0,2}([0-9.]+)\*{0,2}\s*\|\s*\*{0,2}([0-9.]+)\*{0,2}\s*\|",
        text,
        re.MULTILINE,
    )
    if row is None:
        raise AssertionError(
            f"no decision-table row for {RECOMMENDED_PROFILE.label} in the document"
        )
    found["mib_per_second"] = float(row.group(1))
    found["gib_per_hour"] = float(row.group(2))

    reserves = re.findall(
        r"^([0-9.]+)\s*#\s*(?:(\d+)-minute|one-hour) take", text, re.MULTILINE
    )
    if len(reserves) != 2:
        raise AssertionError(f"expected two --required-free-gib lines, found {reserves}")
    for value, minutes in reserves:
        key = "reserve_twenty_minute_gib" if minutes else "reserve_one_hour_gib"
        found[key] = float(value)
    return found


def test_headline_numbers_in_the_document_are_the_ones_the_code_computes() -> None:
    """The regression test for the finding, stated in the operator's numbers.

    Parses MiB/s, GiB/hour, the one-hour reserve and the twenty-minute reserve
    out of the committed markdown and compares each to ``build_budget``. Against
    the pre-fix document every one of the four fails.
    """

    headline = _headline_from_markdown(document_path().read_text(encoding="utf-8"))
    plan, short = _plan_budget(), _short_budget()

    assert headline["mib_per_second"] == pytest.approx(plan.mib_per_second, abs=0.005)
    assert headline["gib_per_hour"] == pytest.approx(plan.gib_per_hour, abs=0.05)
    assert headline["reserve_one_hour_gib"] == pytest.approx(plan.required_free_gib(), abs=0.05)
    assert headline["reserve_twenty_minute_gib"] == pytest.approx(
        short.required_free_gib(), abs=0.05
    )


def test_the_stale_document_fails_the_headline_check() -> None:
    """Proof that the check above would have caught the original defect.

    A minimal reconstruction of the stale document's two load-bearing shapes —
    the decision-table row and the ``--required-free-gib`` block — carrying the
    exact figures the pre-fix file published. Every one of the four assertions
    in the test above must fail on it, and the failure must name a number.
    """

    stale = (
        "| D455 profile | whole rig MiB/s | whole rig GiB/hour |\n"
        "|---|---:|---:|\n"
        f"| **{RECOMMENDED_PROFILE.label}** | **{STALE_MIB_PER_S:.2f}** "
        f"| **{STALE_GIB_PER_HOUR:.1f}** |\n"
        "\n```\n"
        f"{STALE_TWENTY_MINUTE_RESERVE_GIB}        # 20-minute take at 848x480@30 C+D+IR\n"
        f"{STALE_ONE_HOUR_RESERVE_GIB}        # one-hour take\n"
        "```\n"
    )
    headline = _headline_from_markdown(stale)
    plan, short = _plan_budget(), _short_budget()

    assert headline["mib_per_second"] != pytest.approx(plan.mib_per_second, abs=0.005)
    assert headline["gib_per_hour"] != pytest.approx(plan.gib_per_hour, abs=0.05)
    assert headline["reserve_one_hour_gib"] != pytest.approx(plan.required_free_gib(), abs=0.05)
    assert headline["reserve_twenty_minute_gib"] != pytest.approx(
        short.required_free_gib(), abs=0.05
    )
    # And the drift is material, not a rounding wobble: 8.6% on the headline.
    drift = abs(plan.mib_per_second - STALE_MIB_PER_S) / STALE_MIB_PER_S
    assert drift > 0.05, f"the stale figure drifted only {drift:.1%}; the finding said 8.6%"


def test_no_stale_headline_survives_anywhere_in_the_document() -> None:
    """The four stale figures must not appear as live numbers anywhere.

    The generated document *does* recite them once, in the "why this file is
    generated" note, so this test allows them only inside that block and refuses
    them anywhere below it.
    """

    text = document_path().read_text(encoding="utf-8")
    marker = "\n## 0."
    assert marker in text, "the document lost its section 0 anchor"
    body = text.split(marker, 1)[1]
    for stale in (
        f"{STALE_MIB_PER_S:.2f}",
        f"{STALE_GIB_PER_HOUR:.1f}",
        str(STALE_ONE_HOUR_RESERVE_GIB),
        str(STALE_TWENTY_MINUTE_RESERVE_GIB),
    ):
        assert stale not in body, (
            f"{stale!r} — a pre-PS-H figure — appears below section 0 of the budget document"
        )


# ---------------------------------------------------------------------------
# Layer 3: seeded model change must redden the sentinel
# ---------------------------------------------------------------------------


def test_a_model_change_reddens_the_freshness_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seed the exact class of change that made the document stale.

    PS-H's correction was the front camera's per-frame size. Move it again and
    the committed document must stop matching the render — otherwise the
    sentinel is comparing nothing.
    """

    committed = document_path().read_text(encoding="utf-8")
    assert committed == render_document(), "precondition: the document starts fresh"

    monkeypatch.setattr(budget_mod, "ASSUMED_FRONT_CAMERA_JPEG_BYTES", 16_666.0)
    mutated = render_document()

    assert mutated != committed, (
        "a 12x change to the front camera's payload size did not move the rendered "
        "document — the freshness check is not actually checking the model"
    )
    assert "91.870" not in mutated.split("\n## 0.", 1)[1]


def test_check_doc_cli_reports_stale_and_exits_nonzero(tmp_path: Path) -> None:
    """``--check-doc`` is the operator-facing form of the sentinel."""

    stale = tmp_path / "BANDWIDTH_BUDGET.md"
    stale.write_text(render_document().replace("91.87", "84.60"), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.parcel_capture.budget", "--check-doc", str(stale)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,  # the non-zero exit IS the assertion
    )
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "STALE" in proc.stderr
    assert "--emit-doc" in proc.stderr


def test_check_doc_fails_closed_on_a_missing_document(tmp_path: Path) -> None:
    """Unknown = absent. A document that cannot be read is stale, never fresh."""

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.parcel_capture.budget",
            "--check-doc",
            str(tmp_path / "does-not-exist.md"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,  # the non-zero exit IS the assertion
    )
    assert proc.returncode == 3
    assert "STALE" in proc.stderr


# ---------------------------------------------------------------------------
# The decision the document drives: does the plan of record actually fit?
# ---------------------------------------------------------------------------


def test_every_profile_row_carries_a_recorder_ceiling_verdict() -> None:
    """The sanity check the finding asked for, present for every profile."""

    text = document_path().read_text(encoding="utf-8")
    for profile in CANDIDATE_PROFILES:
        verdict, margin = recorder_verdict(build_budget(profile).bytes_per_second)
        assert f"{verdict} (x{margin:.2f})" in text, (
            f"{profile.label} has no rosbag2-ceiling verdict in the decision table"
        )


def test_the_plan_of_record_is_classified_thin_and_the_document_says_so() -> None:
    """848x480 all-streams fits — with 14% of headroom, and that must be said.

    The number is decimal MB/s because that is the unit the rosbag2 ceiling is
    quoted in; treating 91.87 MiB/s as 91.87 MB/s would flatter the margin by 5%.
    """

    plan = _plan_budget()
    megabytes = plan.bytes_per_second / 1e6
    low, _high = ROSBAG2_CEILING_MB_S
    verdict, margin = recorder_verdict(plan.bytes_per_second)

    assert megabytes < low, "the plan of record is over the low rosbag2 reading"
    assert verdict == "THIN", f"expected THIN, got {verdict} at x{margin:.2f}"
    assert 1.0 < margin < 1.25

    text = document_path().read_text(encoding="utf-8")
    assert "Until N4 comes back green, treat this profile as a hypothesis" in text
    assert "not recordable" in text


def test_the_over_ceiling_profiles_are_named_as_unrecordable() -> None:
    """A profile the recorder cannot sustain must be named, not just tabled."""

    text = document_path().read_text(encoding="utf-8")
    over = [
        profile.label
        for profile in CANDIDATE_PROFILES
        if recorder_verdict(build_budget(profile).bytes_per_second)[0].startswith("OVER")
    ]
    assert over, "no profile is over the ceiling — the classifier is not classifying"
    for label in over:
        assert f"`{label}`" in text, f"{label} is over the ceiling and is not named in prose"


def test_the_drop_ladder_states_a_cost_and_a_saving_for_every_rung() -> None:
    """*Which streams to drop first and what each drop costs* — both, per rung."""

    text = document_path().read_text(encoding="utf-8")
    plan = _plan_budget()
    assert len(DROP_LADDER) >= 3
    for step in DROP_LADDER:
        rung = budget_mod._ladder_budget(step, plan)
        assert rung.bytes_per_second < plan.bytes_per_second, (
            f"{step.what} does not reduce the offered load"
        )
        assert step.cost.strip() in text, f"{step.what} has no stated cost in the document"
        assert f"{rung.mib_per_second:.2f}" in text


def test_the_first_rung_is_the_one_that_loses_no_sensing_modality() -> None:
    """Ordering principle: cheapest real loss first, and it is argued in prose."""

    assert DROP_LADDER[0].dropped_channels == ("go2.front_camera",)
    assert "removes no unique sensing modality" in DROP_LADDER[0].cost


def test_recorder_verdict_fails_closed_on_a_nonsense_rate() -> None:
    """A rate that is not a positive finite number is a refusal, not a verdict."""

    for bad in (0, -1.0, float("nan"), float("inf"), "96", True, None):
        with pytest.raises(budget_mod.BudgetError):
            recorder_verdict(bad)  # type: ignore[arg-type]


def test_unknowns_table_is_rendered_from_the_module_not_transcribed() -> None:
    """§0 must be derived from ``budget.UNKNOWNS`` so the two cannot drift."""

    text = document_path().read_text(encoding="utf-8")
    for item in budget_mod.UNKNOWNS:
        key, _, rest = item.partition(": ")
        assert f"| **{key}** | {rest} |" in text, f"§0 lost the {key!r} row"
