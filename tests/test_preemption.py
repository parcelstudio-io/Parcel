"""S1: PreemptionTable encodes today's stop-site semantics."""

from __future__ import annotations

from parcel_robot.core.commands import SOURCE_PRIORITIES
from parcel_robot.core.preemption import ChannelSpec, PreemptionAction, PreemptionTable


def test_default_channels_mirror_source_priorities() -> None:
    table = PreemptionTable.default()
    by_name = {channel.name: channel for channel in table.channels()}
    for source, priority in SOURCE_PRIORITIES.items():
        if source not in by_name:
            continue
        assert by_name[source].priority == priority
        assert by_name[source].source == source


def test_matrix_is_complete_for_registered_channels() -> None:
    # Full 90-pair golden matrix is deferred this pass; completeness is via
    # missing_pairs() so adding a channel without rules fails loudly.
    table = PreemptionTable.default()
    assert table.missing_pairs() == frozenset()


def test_unknown_pair_fails_closed() -> None:
    table = PreemptionTable.default()
    decision = table.decide("voice", "not_a_channel")
    assert decision.action is PreemptionAction.STOP
    assert decision.reason == "undeclared_pair"


def test_search_pauses_follow_the_one_resume_precedent() -> None:
    table = PreemptionTable.default()
    decision = table.decide("search", "follow")
    assert decision.action is PreemptionAction.PAUSE
    follow = next(c for c in table.channels() if c.name == "follow")
    assert follow.pausable is True


def test_mined_stop_expectations() -> None:
    table = PreemptionTable.default()
    expectations = {
        ("manual", "follow"): PreemptionAction.STOP,
        ("manual", "navigation"): PreemptionAction.STOP,
        ("manual", "spatial"): PreemptionAction.STOP,
        ("voice", "follow"): PreemptionAction.STOP,
        ("voice", "navigation"): PreemptionAction.STOP,
        ("voice", "spatial"): PreemptionAction.STOP,
        ("pose", "follow"): PreemptionAction.STOP,
        ("pose", "navigation"): PreemptionAction.STOP,
        ("pose", "spatial"): PreemptionAction.STOP,
        ("navigation", "follow"): PreemptionAction.STOP,
        ("navigation", "spatial"): PreemptionAction.STOP,
        ("follow", "navigation"): PreemptionAction.STOP,
        ("follow", "spatial"): PreemptionAction.STOP,
        ("spatial", "follow"): PreemptionAction.STOP,
        ("spatial", "navigation"): PreemptionAction.STOP,
        ("search", "follow"): PreemptionAction.PAUSE,
        ("search", "navigation"): PreemptionAction.STOP,
        ("search", "spatial"): PreemptionAction.STOP,
        ("safety", "follow"): PreemptionAction.STOP,
        ("safety", "search"): PreemptionAction.STOP,
        ("activities", "follow"): PreemptionAction.NONE,
        # Cheap activities↔nav/pose edges (full matrix deferred; see missing_pairs).
        ("activities", "navigation"): PreemptionAction.NONE,
        ("activities", "pose"): PreemptionAction.NONE,
        ("pose", "activities"): PreemptionAction.STOP,
        # navigation priority < activities → DEFER (mined default), not STOP.
        ("navigation", "activities"): PreemptionAction.DEFER,
    }
    for pair, action in expectations.items():
        assert table.decide(*pair).action is action, pair


def test_same_channel_is_none() -> None:
    table = PreemptionTable.default()
    assert table.decide("follow", "follow").action is PreemptionAction.NONE


def test_adding_channel_without_rules_fails_completeness() -> None:
    table = PreemptionTable.default()
    incomplete = PreemptionTable(
        list(table.channels()) + [ChannelSpec("novelty", "voice", 55)],
        table.rules(),
    )
    assert ("novelty", "follow") in incomplete.missing_pairs()
