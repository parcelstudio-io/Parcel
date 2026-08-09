"""U31 closure by derived re-scoring of persisted NAV_INSTRUCT traces (W0-A/B).

These tests run against the **actual persisted reports** — the frozen baseline
``nav-instruct-v1-baseline-20260805T070524Z`` and the candidate
``nav-instruct-v1-candidate-20260806T070335Z``, both at runner_version
``nav-instruct-v1.1-k0-arrival``. Nothing is re-run and nothing is re-frozen;
the traces are read and scored twice.

Three claims are pinned:

* the re-scoring is **paired** — replaying the frozen rule reproduces every
  recorded ``success``, so the derived numbers are comparable to the frozen row;
* the derived rule flips **exactly** the episodes U31 predicted, and the
  candidate lands on the corrected 4/25 upper bound, not the retracted 8/25;
* the four ``circle_owner`` step-limit rows are **not** hold-fixable — they are
  still moving when the budget ends, so no hold rule can rescue them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evals.nav_instruct.generator import generate_minival
from evals.nav_instruct.rescore import (
    DEFAULT_REPORTS,
    DERIVED_RULE_ID,
    LEDGER,
    RESULTS_DIR,
    derived_arrival,
    rescore_report,
    trailing_inside_stopped_s,
    truncated_by_step_limit,
)
from parcel_robot.instructnav.scoring import AuthorityCategory, FailureClass

BASELINE_REPORT = RESULTS_DIR / DEFAULT_REPORTS[0]
CANDIDATE_REPORT = RESULTS_DIR / DEFAULT_REPORTS[1]

#: sha256 of the seven measured-run ledger rows that existed before Wave 0
#: appended derived rows. Frozen rows are append-only; if this moves, a frozen
#: row was rewritten.
FROZEN_LEDGER_PREFIX_LINES = 7
FROZEN_LEDGER_PREFIX_SHA256 = (
    "e7cb5139b8194fe6882ea626fb9ba5458992d10a0c648686ea6762eaf86fe9e5"
)

#: U31's corrected bound (arbitration OB-6): 1/25 today, at most 4/25 with the
#: hold mismatch fixed, and four `circle_owner` rows that a hold rule cannot
#: touch.
CANDIDATE_HOLD_FLIPS = (
    "nav-region_goal-A-00-1c735162",
    "nav-region_goal-B-05-586317e4",
    "nav-object_goal-A-00-4caa923b",
)
BASELINE_HOLD_FLIPS = (
    "nav-region_goal-A-00-1c735162",
    "nav-object_goal-A-00-4caa923b",
)
NOT_HOLD_FIXABLE = (
    "nav-circle_owner-A-00-6ba3a31d",
    "nav-circle_owner-B-05-4d7b5b21",
    "nav-circle_owner-D-15-717b5947",
    "nav-circle_owner-E-20-12e7db57",
)
FALSE_ARRIVAL_EPISODE = "nav-object_goal-D-15-109547e2"


@pytest.fixture(scope="module")
def baseline() -> dict:
    return rescore_report(BASELINE_REPORT)


@pytest.fixture(scope="module")
def candidate() -> dict:
    return rescore_report(CANDIDATE_REPORT)


def _by_id(rescoring: dict) -> dict[str, dict]:
    return {row["episode_id"]: row for row in rescoring["episodes"]}


# ------------------------------------------------------------------- pairing
@pytest.mark.parametrize("report", [BASELINE_REPORT, CANDIDATE_REPORT])
def test_the_persisted_reports_exist_at_the_same_runner_version(report: Path) -> None:
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["runner_version"] == "nav-instruct-v1.1-k0-arrival"
    assert payload["episode_digest"] == (
        "cf4d5384d1787d110cbc5a74e8b46699e6aa26eaaa576b1c24beb0fbb04adfbf"
    )
    assert len(payload["episodes"]) == 25
    assert all(item.get("trace") for item in payload["episodes"])


def test_replaying_the_frozen_rule_reproduces_every_recorded_success(
    baseline: dict, candidate: dict
) -> None:
    """Without this the derived numbers are not comparable to the frozen row."""

    for rescoring in (baseline, candidate):
        for row in rescoring["episodes"]:
            assert row["frozen_success"] == row["recorded_success"], row["episode_id"]
        assert rescoring["sr_frozen_rule"] == pytest.approx(rescoring["sr_recorded"])


def test_rescoring_refuses_to_pair_against_a_drifted_episode_set(tmp_path: Path) -> None:
    payload = json.loads(BASELINE_REPORT.read_text(encoding="utf-8"))
    payload["episode_digest"] = "0" * 64
    drifted = tmp_path / "drifted.json"
    drifted.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="episode set drift"):
        rescore_report(drifted)


# ------------------------------------------------------------- the U31 bound
def test_the_candidate_derived_success_rate_is_the_corrected_four_of_25(
    candidate: dict,
) -> None:
    assert candidate["n"] == 25
    assert candidate["sr_frozen_rule"] == pytest.approx(0.04)
    assert candidate["sr_derived_rule"] == pytest.approx(4 / 25)
    assert sorted(candidate["hold_flip_episodes"]) == sorted(CANDIDATE_HOLD_FLIPS)
    # The retracted 8/25 claim would need eight; it is not reachable.
    assert candidate["sr_derived_rule"] < 8 / 25


def test_the_baseline_derived_success_rate_is_three_of_25(baseline: dict) -> None:
    assert baseline["n"] == 25
    assert baseline["sr_frozen_rule"] == pytest.approx(0.04)
    assert baseline["sr_derived_rule"] == pytest.approx(3 / 25)
    assert sorted(baseline["hold_flip_episodes"]) == sorted(BASELINE_HOLD_FLIPS)


def test_the_candidate_still_leads_the_baseline_under_the_derived_rule(
    baseline: dict, candidate: dict
) -> None:
    """The paired comparison is the point — both sides move, one moves more."""

    assert candidate["sr_derived_rule"] > baseline["sr_derived_rule"]
    assert candidate["episode_digest"] == baseline["episode_digest"]
    assert candidate["rescore_rule"] == baseline["rescore_rule"] == DERIVED_RULE_ID


@pytest.mark.parametrize("episode_id", NOT_HOLD_FIXABLE)
def test_the_circle_owner_step_limit_rows_are_not_hold_fixable(
    candidate: dict, episode_id: str
) -> None:
    """They are inside the goal disc and still moving when the budget ends."""

    row = _by_id(candidate)[episode_id]
    assert row["mission_status"] == "timed_out"
    assert row["reason"] == "spatial_step_limit"
    assert row["scorer_arrival"] is True  # geometrically inside
    assert row["trailing_hold_s"] == 0.0  # never stopped at the end
    assert row["derived_success"] is False
    assert row["hold_flip"] is False
    assert row["derived_failure"] == FailureClass.TERMINATION.value


def test_every_flipped_episode_flipped_for_the_documented_reason(
    baseline: dict, candidate: dict
) -> None:
    """A flip means: mission claimed arrival, and the trace ended stopped inside."""

    for rescoring in (baseline, candidate):
        for row in rescoring["episodes"]:
            if not row["hold_flip"]:
                continue
            assert row["derived_branch"] == "trace_end_hold"
            assert row["system_arrival"] is True
            assert row["scorer_arrival"] is True
            assert row["authority_category"] == AuthorityCategory.AGREEMENT.value
            assert row["derived_failure"] == FailureClass.NONE.value
            # The hold that was actually observed: one 0.1 s control tick,
            # against the 1.0 s the frozen rule demands. That gap IS U31.
            assert 0.0 < row["trailing_hold_s"] < 1.0


def test_a_step_limited_trace_is_never_credited_by_the_derived_rule() -> None:
    """The exclusion that keeps branch (b) honest."""

    goal = generate_minival(seed=20260804)[0].goal
    inside = goal.polygon[0] if goal.kind == "polygon" else (0.0, 0.0)
    trace = [
        {
            "t_s": 0.0,
            "x": 0.0,
            "y": 3.0,
            "stopped": True,
            "step_limit": True,
            "note": "navigation_step_limit",
        }
    ]
    assert truncated_by_step_limit(trace) is True
    success, branch = derived_arrival(
        trace, goal, frozen_success=False, anchor_xy=goal.center
    )
    assert success is False
    assert branch == "none"
    assert inside is not None  # goal geometry sanity


def test_the_derived_rule_never_demotes_a_frozen_success(
    baseline: dict, candidate: dict
) -> None:
    for rescoring in (baseline, candidate):
        for row in rescoring["episodes"]:
            if row["frozen_success"]:
                assert row["derived_success"] is True
                assert row["derived_branch"] == "frozen_hold"


def test_trailing_hold_is_zero_when_the_trace_does_not_end_inside_and_stopped() -> None:
    goal = generate_minival(seed=20260804)[0].goal
    trace = [{"t_s": 0.0, "x": 40.0, "y": 40.0, "stopped": True}]
    assert trailing_inside_stopped_s(trace, goal, anchor_xy=goal.center) == 0.0


# ------------------------------------------------------------------ U32 / W0-B
def test_the_claimed_arrival_3_2_m_from_the_goal_lands_in_false_arrival(
    candidate: dict,
) -> None:
    row = _by_id(candidate)[FALSE_ARRIVAL_EPISODE]
    assert row["mission_status"] == "arrived"
    assert row["reason"] == "arrived_verified"
    assert row["system_arrival"] is True
    assert row["scorer_arrival"] is False
    assert row["distance_to_goal_m"] == pytest.approx(3.1995, abs=1e-3)
    assert row["frozen_failure"] == FailureClass.FALSE_ARRIVAL.value
    assert row["derived_failure"] == FailureClass.FALSE_ARRIVAL.value
    assert row["authority_category"] == AuthorityCategory.FALSE_ARRIVAL.value
    assert candidate["false_arrival_episodes"] == [FALSE_ARRIVAL_EPISODE]


def test_the_same_false_arrival_is_present_in_the_frozen_baseline(baseline: dict) -> None:
    """It is not a candidate-only regression — the baseline claims it too."""

    row = _by_id(baseline)[FALSE_ARRIVAL_EPISODE]
    assert row["derived_failure"] == FailureClass.FALSE_ARRIVAL.value
    assert row["distance_to_goal_m"] == pytest.approx(3.206, abs=1e-3)


def test_no_episode_is_recorded_as_both_a_false_arrival_and_a_success(
    baseline: dict, candidate: dict
) -> None:
    for rescoring in (baseline, candidate):
        for row in rescoring["episodes"]:
            if row["derived_failure"] == FailureClass.FALSE_ARRIVAL.value:
                assert row["derived_success"] is False
                assert row["frozen_success"] is False


def test_reclassification_changed_only_failure_labels_not_the_success_set(
    baseline: dict, candidate: dict
) -> None:
    """W0-B's safety property, measured on the persisted traces.

    The scorer gained ``false_arrival`` and the differential verdict. The set of
    episodes scored ``success=True`` under the frozen rule must be byte-for-byte
    what the reports recorded — the classification change cannot have moved a
    single row across the success boundary.
    """

    for report_path, rescoring in (
        (BASELINE_REPORT, baseline),
        (CANDIDATE_REPORT, candidate),
    ):
        recorded = json.loads(report_path.read_text(encoding="utf-8"))
        before = {
            item["episode_id"]
            for item in recorded["episodes"]
            if item["score"]["success"]
        }
        after = {row["episode_id"] for row in rescoring["episodes"] if row["frozen_success"]}
        assert after == before
        # And the only failure class that moved is the one that was mislabelled.
        moved = {
            row["episode_id"]
            for row, item in zip(rescoring["episodes"], recorded["episodes"], strict=True)
            if row["frozen_failure"] != item["score"]["failure"]
        }
        assert moved == {FALSE_ARRIVAL_EPISODE}


# ------------------------------------------------------- instrument 5 logging
def test_every_episode_carries_both_arrival_verdicts(
    baseline: dict, candidate: dict
) -> None:
    for rescoring in (baseline, candidate):
        assert sum(rescoring["authority_histogram"].values()) == rescoring["n"]
        assert rescoring["authority_histogram"][AuthorityCategory.UNKNOWN.value] == 0
        for row in rescoring["episodes"]:
            assert isinstance(row["scorer_arrival"], bool)
            assert isinstance(row["system_arrival"], bool)
            assert row["authority_category"] in {
                item.value for item in AuthorityCategory
            }


def test_the_one_way_implication_violations_are_named_not_swallowed(
    candidate: dict,
) -> None:
    """scorer-arrival without system-arrival is logged, per episode, by name."""

    assert sorted(candidate["authority_disagreement_episodes"]) == sorted(NOT_HOLD_FIXABLE)
    for row in candidate["episodes"]:
        if row["scorer_arrival"] and not row["system_arrival"]:
            assert row["authority_category"] in {
                AuthorityCategory.AUTHORITY_DISAGREEMENT.value,
                AuthorityCategory.TOLERATED_BOUNDARY.value,
            }


# ------------------------------------------------------------------- ledger
def test_frozen_ledger_rows_are_byte_identical() -> None:
    """The derived rows were appended; nothing before them was rewritten."""

    lines = LEDGER.read_bytes().splitlines(keepends=True)
    prefix = b"".join(lines[:FROZEN_LEDGER_PREFIX_LINES])
    assert hashlib.sha256(prefix).hexdigest() == FROZEN_LEDGER_PREFIX_SHA256
    for raw in lines[:FROZEN_LEDGER_PREFIX_LINES]:
        assert json.loads(raw).get("kind") != "derived_rescoring"


def test_the_derived_rows_are_present_and_labelled() -> None:
    rows = [
        json.loads(line)
        for line in LEDGER.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    derived = [row for row in rows if row.get("kind") == "derived_rescoring"]
    assert len(derived) >= 2
    parents = {row["parent_run_id"] for row in derived}
    assert "nav-instruct-v1-baseline-20260805T070524Z" in parents
    assert "nav-instruct-v1-candidate-20260806T070335Z" in parents
    for row in derived:
        assert row["rescore_rule"] == DERIVED_RULE_ID
        assert row["frozen_baseline"] is False
        assert "episodes" not in row  # ledger rows stay small
        assert row["scorer_version"].startswith("instructnav-scoring-")
        assert row["runner_version"] == "nav-instruct-v1.1-k0-arrival"
