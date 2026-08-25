"""Executable quality coverage for the 25 captured realtime conversations."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from evals.companion.realtime_convo_v1.schema import ToolCall, load_fixtures, load_scenarios
from evals.companion.realtime_convo_v1.score_corpus import (
    QualityError,
    load_review,
    machine_findings,
    score_corpus,
    validate_review,
)

SCENARIOS = load_scenarios()
FIXTURES = load_fixtures()
REVIEW_PATH = (
    Path(__file__).resolve().parents[1]
    / "evals/companion/realtime_convo_v1/reviews/20260824-unblinded-ai-review.json"
)


def _complete_review() -> dict[str, object]:
    return {
        "schema_version": 1,
        "reviewer": {"id": "test-reviewer", "kind": "test", "blinded": False},
        "threads": [
            {
                "thread_id": scenario.thread_id,
                "verdict": "pass",
                "expectation_verdicts": ["pass"] * len(scenario.expect),
                "note": "",
            }
            for scenario in SCENARIOS
        ],
    }


def test_current_corpus_passes_hard_machine_contracts_and_is_fully_counted() -> None:
    report = score_corpus(SCENARIOS, FIXTURES)
    assert report["machine"]["status"] == "pass"
    assert report["machine"]["hard_failure_count"] == 0
    assert report["corpus"]["thread_count"] == 25
    assert report["corpus"]["turn_count"] == 174
    assert report["semantic_review"]["status"] == "incomplete"


def test_review_must_cover_every_authored_expectation_and_thread() -> None:
    review = _complete_review()
    rows = validate_review(review, SCENARIOS)
    assert len(rows) == 25
    assert sum(row["expectation_count"] for row in rows) == sum(
        len(scenario.expect) for scenario in SCENARIOS
    )
    review["threads"][0]["expectation_verdicts"].pop()  # type: ignore[index]
    with pytest.raises(QualityError, match="reviewed .* authored expectations"):
        validate_review(review, SCENARIOS)


def test_an_undeclared_tool_is_a_hard_failure() -> None:
    fixture = FIXTURES[0]
    turn = replace(
        fixture.turns[0],
        tool_calls=(ToolCall("call_bad", "raw_vendor_move", json.dumps({"vx": 1})),),
    )
    mutated = (replace(fixture, turns=(turn, *fixture.turns[1:])), *FIXTURES[1:])
    findings = machine_findings(SCENARIOS, mutated)
    assert any(
        finding.check_id == "undeclared_tool" and finding.severity == "hard"
        for finding in findings
    )


def test_unverified_arrival_language_is_visible_but_not_laundered_into_a_verdict() -> None:
    fixture = FIXTURES[0]
    turn = replace(fixture.turns[0], robot_text="We are here at the destination.")
    mutated = (replace(fixture, turns=(turn, *fixture.turns[1:])), *FIXTURES[1:])
    findings = machine_findings(SCENARIOS, mutated)
    arrival = [finding for finding in findings if finding.check_id == "arrival_claim_without_result"]
    assert arrival and all(finding.severity == "review" for finding in arrival)


def test_one_unblinded_review_stays_report_only() -> None:
    report = score_corpus(SCENARIOS, FIXTURES, review=_complete_review())
    assert report["semantic_review"]["status"] == "complete"
    assert report["semantic_review"]["report_only"] is True
    assert report["claims"]["single_unblinded_review_proves_owner_preference"] is False


def test_checked_in_review_covers_the_whole_corpus_without_claiming_human_calibration() -> None:
    report = score_corpus(SCENARIOS, FIXTURES, review=load_review(REVIEW_PATH))
    review = report["semantic_review"]
    assert review["status"] == "complete"
    assert review["thread_verdicts"] == {"pass": 6, "mixed": 8, "fail": 11}
    assert review["expectation_verdicts"] == {"pass": 43, "fail": 33}
    assert review["reviewer"]["kind"] == "ai_semantic_review"
    assert review["reviewer"]["human"] is False
    assert review["reviewer"]["calibrated"] is False
