"""Session-script schema for PERSONAL_CONVO_V1 (PC-1).

A session script is a frozen, hand-authored JSON fixture that drives one
multi-turn scenario through the live text path. The schema is the design's
"SESSION SCRIPTS" section verbatim: a scenario has a persona, a profile-facts
fixture, an optional sqlite ``memory_fixture`` (an event-graph YAML plus a
recency limit), frozen ``tool_fixtures`` (weather, including an outage mode),
and one or more ``sessions`` each holding ordered turns. Every turn carries a
Tier-D contract the deterministic scorer bank checks.

This module is pure validation — no I/O beyond being handed already-parsed
objects. It never reaches a model. The runner calls :func:`validate_session_script`
on every probe before executing it, so a malformed probe reddens before any
provider call, mirroring conversation_quality_v1's fail-closed suite loader.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Personas the pack may drive. These mirror the frozen personality profiles the
# conversation_quality_v1 manifest already sha-pins; the text tier reuses them
# rather than introducing new persona artifacts.
KNOWN_PERSONAS = frozenset(
    {"calm_guardian", "gentle_companion", "playful_companion"}
)

# The eight probe families from the approved design. Every probe declares
# exactly one; the runner asserts the corpus covers all eight.
PROBE_FAMILIES = (
    "in_session_context",
    "cross_session_memory",
    "fact_tool_composition",
    "persona_consistency",
    "affect_handling",
    "interactivity_clarification",
    "adaptability_no_sycophancy",
    "asr_robustness",
)

# Weather tool fixture modes. "normal" returns the deterministic offline stub;
# "outage" makes the tool fail so the truthfulness contract can prove the model
# does not fabricate a forecast it could not fetch.
WEATHER_MODES = frozenset({"normal", "outage"})

# DialogueClaimV1 veracity ladder (contracts.v1.CLAIM_VERACITY). ``max_veracity``
# in a turn contract caps how strong a claim the turn may contain: "tentative"
# forbids any verified claim (used for outage / degraded-input turns).
VERACITY_RANK = {"tentative": 0, "verified": 1}


class SessionScriptError(ValueError):
    """A session script (probe fixture) is structurally invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SessionScriptError(message)


def _str_list(value: object, name: str) -> list[str]:
    _require(isinstance(value, list), f"{name} must be a list")
    assert isinstance(value, list)
    for item in value:
        _require(isinstance(item, str), f"{name} entries must be strings")
    return [str(item) for item in value]


def _group_list(value: object, name: str) -> list[list[str]]:
    """required_any_groups: a list of groups; each group a list of substrings."""

    _require(isinstance(value, list), f"{name} must be a list of groups")
    assert isinstance(value, list)
    groups: list[list[str]] = []
    for group in value:
        _require(isinstance(group, list) and bool(group), f"{name} groups must be non-empty lists")
        assert isinstance(group, list)
        for term in group:
            _require(isinstance(term, str) and bool(term), f"{name} terms must be non-empty strings")
        groups.append([str(term) for term in group])
    return groups


def _validate_contract(contract: Mapping[str, Any], where: str) -> None:
    _require(isinstance(contract, Mapping), f"{where} contract must be an object")

    # Fact recall / confabulation (reuses conversation_quality_v1 vocabulary).
    _group_list(contract.get("facts_must_appear", []), f"{where} facts_must_appear")
    _str_list(contract.get("facts_must_not_appear", []), f"{where} facts_must_not_appear")

    # Tool invocation correctness from the trace.
    _str_list(contract.get("tool_calls_expected", []), f"{where} tool_calls_expected")
    _str_list(contract.get("tool_calls_forbidden", []), f"{where} tool_calls_forbidden")

    # DialogueAct truthfulness contract.
    act = contract.get("dialogue_act", {})
    _require(isinstance(act, Mapping), f"{where} dialogue_act must be an object")
    assert isinstance(act, Mapping)
    if "asks_clarification_expected" in act:
        _require(
            isinstance(act["asks_clarification_expected"], bool),
            f"{where} asks_clarification_expected must be a boolean",
        )
    _str_list(act.get("forbidden_claim_patterns", []), f"{where} forbidden_claim_patterns")
    max_veracity = act.get("max_veracity", "verified")
    _require(
        max_veracity in VERACITY_RANK,
        f"{where} max_veracity must be one of {sorted(VERACITY_RANK)}",
    )

    # Emote policy tag budget.
    emote = contract.get("emote", {})
    _require(isinstance(emote, Mapping), f"{where} emote must be an object")
    assert isinstance(emote, Mapping)
    max_tags = emote.get("max_tags", 0)
    _require(
        isinstance(max_tags, int) and not isinstance(max_tags, bool) and max_tags >= 0,
        f"{where} emote.max_tags must be a non-negative integer",
    )

    # Reply length budget.
    budget = contract.get("reply_word_budget", 60)
    _require(
        isinstance(budget, int) and not isinstance(budget, bool) and budget > 0,
        f"{where} reply_word_budget must be a positive integer",
    )


def validate_session_script(script: Mapping[str, Any]) -> None:
    """Validate one probe fixture; raise :class:`SessionScriptError` on any defect."""

    _require(isinstance(script, Mapping), "session script must be an object")

    scenario_id = script.get("scenario_id")
    _require(
        isinstance(scenario_id, str) and bool(scenario_id),
        "scenario_id must be a non-empty string",
    )

    family = script.get("probe_family")
    _require(family in PROBE_FAMILIES, f"probe_family must be one of {list(PROBE_FAMILIES)}")

    persona = script.get("persona_id")
    _require(persona in KNOWN_PERSONAS, f"persona_id must be one of {sorted(KNOWN_PERSONAS)}")

    facts = script.get("profile_facts", {})
    _require(isinstance(facts, Mapping), "profile_facts must be an object")
    assert isinstance(facts, Mapping)
    for key, value in facts.items():
        _require(
            isinstance(key, str) and isinstance(value, str),
            "profile_facts must map strings to strings",
        )

    memory = script.get("memory_fixture")
    if memory is not None:
        _require(isinstance(memory, Mapping), "memory_fixture must be an object or null")
        assert isinstance(memory, Mapping)
        _require(
            isinstance(memory.get("graph"), str) and bool(memory.get("graph")),
            "memory_fixture.graph must name an event-graph file",
        )
        limit = memory.get("recency_limit", 8)
        _require(
            isinstance(limit, int) and not isinstance(limit, bool) and limit > 0,
            "memory_fixture.recency_limit must be a positive integer",
        )

    tools = script.get("tool_fixtures", {})
    _require(isinstance(tools, Mapping), "tool_fixtures must be an object")
    assert isinstance(tools, Mapping)
    weather = tools.get("weather")
    if weather is not None:
        _require(isinstance(weather, Mapping), "tool_fixtures.weather must be an object")
        assert isinstance(weather, Mapping)
        _require(
            weather.get("mode") in WEATHER_MODES,
            f"tool_fixtures.weather.mode must be one of {sorted(WEATHER_MODES)}",
        )

    sessions = script.get("sessions")
    _require(isinstance(sessions, list) and bool(sessions), "sessions must be a non-empty list")
    assert isinstance(sessions, list)
    seen_sessions: set[str] = set()
    seen_turns: set[str] = set()
    for session in sessions:
        _require(isinstance(session, Mapping), "each session must be an object")
        assert isinstance(session, Mapping)
        session_id = session.get("session_id")
        _require(
            isinstance(session_id, str) and bool(session_id),
            "session_id must be a non-empty string",
        )
        _require(session_id not in seen_sessions, f"duplicate session_id: {session_id}")
        seen_sessions.add(str(session_id))
        if "reset_live_history" in session:
            _require(
                isinstance(session["reset_live_history"], bool),
                "reset_live_history must be a boolean",
            )
        session_tools = session.get("tool_fixtures")
        if session_tools is not None:
            _require(isinstance(session_tools, Mapping), "session tool_fixtures must be an object")
            assert isinstance(session_tools, Mapping)
            session_weather = session_tools.get("weather")
            if session_weather is not None:
                _require(
                    isinstance(session_weather, Mapping),
                    "session tool_fixtures.weather must be an object",
                )
                assert isinstance(session_weather, Mapping)
                _require(
                    session_weather.get("mode") in WEATHER_MODES,
                    f"session weather.mode must be one of {sorted(WEATHER_MODES)}",
                )
        turns = session.get("turns")
        _require(isinstance(turns, list) and bool(turns), "session turns must be a non-empty list")
        assert isinstance(turns, list)
        for turn in turns:
            _require(isinstance(turn, Mapping), "each turn must be an object")
            assert isinstance(turn, Mapping)
            turn_id = turn.get("turn_id")
            _require(
                isinstance(turn_id, str) and bool(turn_id),
                "turn_id must be a non-empty string",
            )
            _require(turn_id not in seen_turns, f"duplicate turn_id: {turn_id}")
            seen_turns.add(str(turn_id))
            _require(
                isinstance(turn.get("user"), str) and bool(turn.get("user")),
                f"turn {turn_id} must carry a non-empty user utterance",
            )
            _validate_contract(turn.get("contract", {}), f"turn {turn_id}")


def veracity_at_most(claim_veracity: str, ceiling: str) -> bool:
    """True if ``claim_veracity`` does not exceed the contract ``ceiling``."""

    return VERACITY_RANK.get(claim_veracity, 99) <= VERACITY_RANK.get(ceiling, -1)


__all__ = [
    "KNOWN_PERSONAS",
    "PROBE_FAMILIES",
    "VERACITY_RANK",
    "WEATHER_MODES",
    "SessionScriptError",
    "validate_session_script",
    "veracity_at_most",
]
