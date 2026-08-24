"""H2 capability proof — the monologue tick's contract is fail-closed.

Two claims, and nothing else (reduced testing policy):

1. **A well-formed decision survives a JSON round trip unchanged**, and the
   digest renders inside its declared budget. That is the capability H3 and
   the H2 harness stand on.
2. **Every malformed reply raises.** No repair, no default ``ignore``: a
   parser that invents a decision from a broken reply is how a "0 % parse
   failure" number gets manufactured. The table below is the refutation
   surface — each row is a way a real constrained decode has been seen to
   fail.
"""

from __future__ import annotations

import json

import pytest

from parcel_robot.brain.monologue import (
    DECISION_KINDS,
    MAX_RENDERED_CHARS,
    MonologueDecisionV1,
    MonologueParseError,
    Noticing,
    WorldDigestV1,
    decision_json_schema,
    monologue_enabled,
    parse_decision,
)


def _digest() -> WorldDigestV1:
    return WorldDigestV1(
        at_s=1234.5,
        place="living room",
        posture="standing",
        nav_state="idle",
        battery_percent=71.0,
        owner_present=True,
        last_owner_turn_age_s=42.0,
        last_robot_utterance_age_s=310.0,
        noticings=(
            Noticing("a backpack on the floor", -35.0, 2.4, 0.81, 1.2),
            Noticing("the owner", 5.0, 1.9, 0.05, 0.3),
        ),
        drives=(("curiosity", 0.62), ("social", 0.40), ("vigilance", 0.15), ("rest", 0.22)),
        recent_actions=("looked left", "said hello"),
    )


def test_digest_renders_inside_its_budget_and_round_trips() -> None:
    digest = _digest()
    rendered = digest.render()
    assert len(rendered) <= MAX_RENDERED_CHARS
    assert digest.estimated_tokens() <= 600
    assert "backpack" in rendered and "curiosity 0.62" in rendered
    assert WorldDigestV1.from_mapping(digest.as_dict()) == digest


def test_every_decision_kind_round_trips_through_json() -> None:
    samples = {
        "ignore": MonologueDecisionV1("ignore", reason="nothing new", confidence=0.9),
        "look": MonologueDecisionV1("look", target="-35", reason="novelty 0.81", confidence=0.7),
        "remark": MonologueDecisionV1(
            "remark", text="There's a backpack here that wasn't before.",
            reason="owner present, novelty high", confidence=0.6,
        ),
        "ask": MonologueDecisionV1(
            "ask", text="Is that bag yours?", reason="owner present", confidence=0.5
        ),
        "go_check": MonologueDecisionV1(
            "go_check", target="hallway", reason="sound off map", confidence=0.4
        ),
    }
    assert set(samples) == set(DECISION_KINDS)
    for decision in samples.values():
        assert parse_decision(json.dumps(decision.as_dict(), separators=(",", ":"))) == decision
    assert samples["look"].bearing_deg == pytest.approx(-35.0)
    assert samples["remark"].speaks and not samples["ignore"].speaks


@pytest.mark.parametrize(
    ("label", "reply"),
    [
        ("empty", ""),
        ("prose only", "I think the dog should stay quiet."),
        ("json array", "[]"),
        ("json string", '"ignore"'),
        ("truncated json", '{"kind": "ignore", "reason": "nothin'),
        ("prose wrapping json", 'Sure! {"kind":"ignore","reason":"x","confidence":0.5}'),
        ("unknown kind", '{"kind":"bark","reason":"x","confidence":0.5}'),
        ("missing kind", '{"reason":"x","confidence":0.5}'),
        ("missing reason", '{"kind":"ignore","confidence":0.5}'),
        ("extra field", '{"kind":"ignore","reason":"x","confidence":0.5,"speak_now":true}'),
        ("confidence out of range", '{"kind":"ignore","reason":"x","confidence":1.4}'),
        ("confidence not a number", '{"kind":"ignore","reason":"x","confidence":"high"}'),
        ("ignore carrying text", '{"kind":"ignore","text":"hi","reason":"x","confidence":0.5}'),
        ("remark without text", '{"kind":"remark","reason":"x","confidence":0.5}'),
        (
            "look without bearing",
            '{"kind":"look","target":"over there","reason":"x","confidence":0.5}',
        ),
        (
            "look bearing out of range",
            '{"kind":"look","target":"420","reason":"x","confidence":0.5}',
        ),
        ("go_check without a place", '{"kind":"go_check","reason":"x","confidence":0.5}'),
        (
            "remark over the text budget",
            json.dumps(
                {"kind": "remark", "text": "x" * 141, "reason": "x", "confidence": 0.5}
            ),
        ),
    ],
)
def test_malformed_replies_are_refused(label: str, reply: str) -> None:
    with pytest.raises(MonologueParseError):
        parse_decision(reply)


def test_fenced_json_is_the_only_repair() -> None:
    fenced = (
        '```json\n{"kind":"ignore","target":"","text":"","reason":"calm",'
        '"confidence":0.8}\n```'
    )
    assert parse_decision(fenced).kind == "ignore"


def test_schema_and_flag_agree_with_the_contract() -> None:
    schema = decision_json_schema()
    assert schema["properties"]["kind"]["enum"] == list(DECISION_KINDS)
    assert schema["additionalProperties"] is False
    assert monologue_enabled({}) is False
    assert monologue_enabled({"PARCEL_MONOLOGUE_TICK": "1"}) is True
