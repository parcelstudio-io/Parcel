"""AutoRater framework — the judge must fail closed and must not be fooled by order.

An LLM judge is itself an unverified component. These tests pin the properties
that decide whether its numbers mean anything: position bias is measured rather
than averaged away, unparseable replies abstain instead of defaulting, and a
tie is distinguishable from an abstention.
"""

from __future__ import annotations

import json

import pytest

from evals.autorater import (
    ComparativeVerdict,
    LLMPuntRater,
    PairwiseQualityRater,
    RatingRequest,
    Response,
    RulePuntRater,
    ScriptedJudge,
    SideMetric,
    Turn,
    default_registry,
    parse_judge_json,
)
from evals.autorater.types import MetricDelta


def _request(base_text: str = "Okay.", test_text: str = "On my way.") -> RatingRequest:
    return RatingRequest(
        prompt="go to the sidewalk",
        base=Response("base", (Turn("robot", base_text),)),
        test=Response("test", (Turn("robot", test_text),)),
        context=(Turn("owner", "hey"),),
    )


def _verdict_json(winner: str, margin: float) -> str:
    return json.dumps({"winner": winner, "margin": margin, "criteria": {}, "rationale": "r"})


# --- types -----------------------------------------------------------------


def test_abstained_verdict_cannot_carry_a_score() -> None:
    with pytest.raises(ValueError, match="no score"):
        ComparativeVerdict(
            rater_id="x", rater_version="1", score=0.0, preference="tie",
            rationale="", abstained=True, abstain_reason="judge died",
        )


def test_abstention_must_say_why() -> None:
    with pytest.raises(ValueError, match="say why"):
        ComparativeVerdict(
            rater_id="x", rater_version="1", score=None, preference=None,
            rationale="", abstained=True,
        )


def test_score_is_bounded() -> None:
    with pytest.raises(ValueError, match="outside"):
        ComparativeVerdict(
            rater_id="x", rater_version="1", score=1.5, preference="test", rationale="",
        )


def test_response_requires_at_least_one_turn() -> None:
    with pytest.raises(ValueError, match="at least one turn"):
        Response("base", ())


def test_multi_turn_is_detected_from_robot_turns_only() -> None:
    single = Response("base", (Turn("owner", "hi"), Turn("robot", "hello")))
    multi = Response("base", (Turn("robot", "one"), Turn("owner", "ok"), Turn("robot", "two")))
    assert not single.is_multi_turn
    assert multi.is_multi_turn


# --- fail-closed parsing ---------------------------------------------------


def test_parse_accepts_a_fenced_json_block() -> None:
    assert parse_judge_json('```json\n{"winner": "A"}\n```')["winner"] == "A"


def test_parse_recovers_one_object_from_surrounding_prose() -> None:
    assert parse_judge_json('Sure!\n{"winner": "B"}\nHope that helps')["winner"] == "B"


@pytest.mark.parametrize("reply", ["no json here", "", "[1, 2, 3]", "{broken"])
def test_parse_refuses_anything_it_cannot_read(reply: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        parse_judge_json(reply)


def test_unparseable_judge_abstains_rather_than_scoring_zero() -> None:
    rater = PairwiseQualityRater(ScriptedJudge(["not json at all"]))
    verdict = rater.rate(_request())
    assert verdict.abstained
    assert verdict.score is None, "an abstention must not look like a tie"
    assert "ValueError" in verdict.abstain_reason


def test_unreachable_judge_abstains() -> None:
    verdict = PairwiseQualityRater(ScriptedJudge([])).rate(_request())
    assert verdict.abstained and "exhausted" in verdict.abstain_reason


def test_unknown_winner_token_abstains() -> None:
    rater = PairwiseQualityRater(ScriptedJudge([json.dumps({"winner": "maybe", "margin": 1})]))
    assert rater.rate(_request()).abstained


# --- position bias ---------------------------------------------------------


def test_both_presentation_orders_are_run() -> None:
    judge = ScriptedJudge([_verdict_json("A", 0.8), _verdict_json("B", 0.8)])
    PairwiseQualityRater(judge).rate(_request())
    assert len(judge.calls) == 2, "a comparative rater must swap the sides"


def test_a_consistent_judge_yields_no_position_bias() -> None:
    """Order 1 says A (=base) wins; order 2 says B (=base again) wins."""

    judge = ScriptedJudge([_verdict_json("A", 0.8), _verdict_json("B", 0.8)])
    verdict = PairwiseQualityRater(judge).rate(_request())
    assert verdict.score == pytest.approx(-0.8), "both orders agree base is better"
    assert verdict.preference == "base"
    assert verdict.position_bias == pytest.approx(0.0)
    assert verdict.is_decisive


def test_a_judge_that_always_picks_the_first_side_is_caught() -> None:
    """The classic failure: 'A' both times means it is reading position, not quality."""

    judge = ScriptedJudge([_verdict_json("A", 0.9), _verdict_json("A", 0.9)])
    verdict = PairwiseQualityRater(judge).rate(_request())
    assert verdict.score == pytest.approx(0.0), "the two orders cancel"
    assert verdict.preference == "tie"
    assert verdict.position_bias == pytest.approx(1.8)
    assert not verdict.is_decisive, "a position-biased verdict must not read as decisive"


def test_order_scores_are_reported_for_audit() -> None:
    judge = ScriptedJudge([_verdict_json("A", 0.9), _verdict_json("A", 0.9)])
    verdict = PairwiseQualityRater(judge).rate(_request())
    assert verdict.order_scores == (pytest.approx(-0.9), pytest.approx(0.9))


def test_small_margins_fall_into_the_tie_band() -> None:
    judge = ScriptedJudge([_verdict_json("B", 0.05), _verdict_json("A", 0.05)])
    verdict = PairwiseQualityRater(judge).rate(_request())
    assert verdict.preference == "tie", "a coin-flip margin is not a preference"
    assert not verdict.abstained, "a tie is a real verdict, unlike an abstention"


# --- punts -----------------------------------------------------------------


def test_rule_rater_counts_the_shipped_unrecognised_command_reply() -> None:
    response = Response("base", (Turn("robot", "I did not understand that command."),))
    metric = RulePuntRater().measure(response)
    assert metric.value == 1.0
    assert metric.per_turn[0]["index"] == 0


def test_a_grounded_refusal_with_an_offer_is_not_a_punt() -> None:
    response = Response(
        "test",
        (Turn("robot", "I can't get onto the sidewalk, there's a fence. Want me to go around?"),),
    )
    assert RulePuntRater().measure(response).value == 0.0


def test_declining_then_offering_an_alternative_is_not_a_punt() -> None:
    response = Response("test", (Turn("robot", "I don't know how to do that, but I can check the map."),))
    assert RulePuntRater().measure(response).value == 0.0


def test_punts_are_counted_per_turn_across_a_multi_turn_response() -> None:
    response = Response(
        "base",
        (
            Turn("robot", "I did not understand that command."),
            Turn("owner", "go to the sidewalk"),
            Turn("robot", "Sorry, I can't."),
            Turn("robot", "Heading over now."),
        ),
    )
    metric = RulePuntRater().measure(response)
    assert metric.value == 2.0
    assert [hit["index"] for hit in metric.per_turn] == [0, 1]
    assert metric.metadata["robot_turns"] == 3


def test_owner_turns_never_count_as_punts() -> None:
    response = Response(
        "base", (Turn("owner", "I don't know how to do that"), Turn("robot", "No problem."))
    )
    assert RulePuntRater().measure(response).value == 0.0


def test_llm_punt_rater_abstains_on_a_malformed_count() -> None:
    rater = LLMPuntRater(ScriptedJudge([json.dumps({"punts": "lots"})]))
    metric = rater.measure(Response("test", (Turn("robot", "hm"),)), _request())
    assert metric.abstained and metric.value == 0.0


def test_llm_punt_rater_reads_a_well_formed_count() -> None:
    reply = json.dumps({"punts": 2, "turns": [{"index": 0, "quote": "q", "why": "w"}]})
    metric = LLMPuntRater(ScriptedJudge([reply])).measure(
        Response("test", (Turn("robot", "hm"),)), _request()
    )
    assert metric.value == 2.0 and not metric.abstained


def test_metric_delta_is_none_when_either_side_abstained() -> None:
    good = SideMetric("r", "1", "base", "punts", 1.0, "count")
    bad = SideMetric("r", "1", "test", "punts", 0.0, "count", abstained=True, abstain_reason="x")
    assert MetricDelta("punts", good, bad).delta is None
    other = SideMetric("r", "1", "test", "punts", 3.0, "count")
    assert MetricDelta("punts", good, other).delta == 2.0


# --- registry --------------------------------------------------------------


def test_rule_raters_are_available_without_any_judge_model() -> None:
    assert default_registry().ids() == ("punts_rule",)


def test_every_judged_rater_registers_when_a_backend_exists() -> None:
    registry = default_registry(ScriptedJudge([]))
    assert set(registry.ids()) == {
        "punts_rule", "punts_llm", "pairwise_quality",
        "honesty_groundedness", "persona_consistency", "multi_turn_coherence",
    }


def test_rater_ids_are_unique() -> None:
    registry = default_registry(ScriptedJudge([]))
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(RulePuntRater())


def test_fingerprint_pins_prompt_version_so_scores_are_not_mixed() -> None:
    assert PairwiseQualityRater(ScriptedJudge([])).fingerprint == "pairwise_quality@1"


def test_a_missing_trailing_comma_is_reported_clearly() -> None:
    """`(Turn(...))` is a Turn, not a tuple — a very easy call-site mistake."""

    with pytest.raises(TypeError, match="trailing comma"):
        Response("base", Turn("robot", "hi"))
