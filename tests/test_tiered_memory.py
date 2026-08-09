"""Property/unit gate for the low-latency tiered conversation memory.

Proves the *mechanism*, deterministically and model-free:
  * tier promotion / aging (recent verbatim -> summary -> durable profile);
  * the read path never invokes the summarizer or distiller (low latency);
  * determinism of the read path;
  * fail-closed config and inputs;
  * a fact stated 50 turns ago survives into Tier 2 and into the Tier-3 profile
    and is retrievable.

It does NOT prove a real LLM writes good summaries — the summarizer/distiller
here are deterministic fakes (recorded as the honesty boundary in the module and
the PERSONAL_CONVO result).
"""

from __future__ import annotations

import pytest

from parcel_robot.dynamic_prompting import (
    DynamicPromptComposer,
    MemorySource,
    build_prompting_stack,
)
from parcel_robot.tiered_memory import (
    ConcatSummarizer,
    FactProposal,
    TieredMemory,
    TieredMemoryConfig,
    keyword_overlap,
    null_distiller,
)


def _concat(previous_summary: str, turns) -> str:
    """A content-preserving fake summarizer (no compression, no model)."""

    parts = [previous_summary] if previous_summary else []
    parts.extend(turn.content for turn in turns)
    return " ".join(part for part in parts if part).strip()


class _Counter:
    """Wrap a callable to count how many times it is invoked."""

    def __init__(self, fn) -> None:
        self._fn = fn
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self._fn(*args, **kwargs)


def _topic_distiller(summary):
    # One durable row per conversation, keyed by session so distinct sessions do
    # not overwrite each other.
    return [FactProposal(key=f"session_{summary.session_id}", value=summary.text)]


# --- keyword overlap ------------------------------------------------------------


def test_keyword_overlap_is_deterministic_and_bounded() -> None:
    assert keyword_overlap("job interview Monday", "the job interview went well") == pytest.approx(
        2 / 3
    )
    assert keyword_overlap("", "anything") == 0.0
    assert keyword_overlap("the a of", "content here") == 0.0  # all stopwords -> 0
    assert 0.0 <= keyword_overlap("basil plants", "I watered the basil") <= 1.0


# --- aging / tier promotion -----------------------------------------------------


def test_tier1_holds_last_n_and_older_turns_roll_into_tier2() -> None:
    memory = TieredMemory(
        summarizer=_concat,
        distiller=null_distiller,
        config=TieredMemoryConfig(tier1_max_turns=3, tier2_max_summaries=100),
    )
    for i in range(1, 8):
        memory.append("user", f"message {i}")
    result = memory.retrieve("message")
    # Tier 1 is exactly the last three, verbatim and in order.
    assert [t.content for t in result.tier1_recent] == ["message 5", "message 6", "message 7"]
    # The aged-out earlier turns are in a Tier-2 rolling summary.
    assert len(result.tier2_summaries) == 1
    summary_text = result.tier2_summaries[0].text
    for early in ("message 1", "message 2", "message 3", "message 4"):
        assert early in summary_text
    # And they are no longer verbatim in Tier 1.
    assert "message 1" not in " ".join(t.content for t in result.tier1_recent)


def test_relevance_ranks_tier2_summaries_by_query() -> None:
    memory = TieredMemory(
        summarizer=_concat,
        distiller=null_distiller,
        config=TieredMemoryConfig(tier1_max_turns=1, retrieval_summaries=2),
    )
    memory.append("user", "the kitchen cabinets are reorganized", session_id="s_home")
    memory.append("user", "spacer one", session_id="s_home")
    memory.append("user", "my flight to Tokyo leaves on Tuesday", session_id="s_travel")
    memory.append("user", "spacer two", session_id="s_travel")
    memory.append("user", "latest", session_id="s_now")
    ranked = memory.retrieve("when is my flight to Tokyo")
    assert ranked.tier2_summaries  # something matched
    assert "Tokyo" in ranked.tier2_summaries[0].text  # best match first


# --- low-latency read path ------------------------------------------------------


def test_retrieve_never_invokes_summarizer_or_distiller() -> None:
    summarizer = _Counter(_concat)
    distiller = _Counter(_topic_distiller)
    memory = TieredMemory(
        summarizer=summarizer,
        distiller=distiller,
        config=TieredMemoryConfig(tier1_max_turns=2, tier2_max_summaries=1),
    )
    for i in range(1, 7):
        memory.append("user", f"turn {i} content", session_id=f"s{i // 3}")
    calls_after_writes = (summarizer.calls, distiller.calls)
    assert summarizer.calls > 0  # writes did summarize
    for query in (None, "turn", "content", "nothing matches here", ""):
        memory.retrieve(query)
    # The read path added zero model calls: retrieval is pure lookup.
    assert (summarizer.calls, distiller.calls) == calls_after_writes


# --- determinism ----------------------------------------------------------------


def test_read_path_is_deterministic() -> None:
    def build() -> TieredMemory:
        mem = TieredMemory(
            summarizer=_concat,
            distiller=_topic_distiller,
            config=TieredMemoryConfig(tier1_max_turns=3, tier2_max_summaries=1),
        )
        for i in range(1, 13):
            mem.append("user", f"fact number {i}", session_id="a" if i <= 6 else "b")
        return mem

    first = build().retrieve("fact number 2")
    second = build().retrieve("fact number 2")
    assert first == second


# --- fail-closed ----------------------------------------------------------------


def test_config_fails_closed_on_bad_values() -> None:
    with pytest.raises(ValueError):
        TieredMemoryConfig(tier1_max_turns=0)
    with pytest.raises(ValueError):
        TieredMemoryConfig(tier2_max_summaries=0)
    with pytest.raises(ValueError):
        TieredMemoryConfig(retrieval_summaries=0)
    with pytest.raises(ValueError):
        TieredMemoryConfig(retrieval_min_overlap=1.5)


def test_append_fails_closed_on_bad_inputs() -> None:
    memory = TieredMemory(summarizer=_concat, distiller=null_distiller)
    with pytest.raises(ValueError, match="unsupported memory role"):
        memory.append("system", "hi")
    with pytest.raises(ValueError, match="non-empty"):
        memory.append("user", "   ")
    with pytest.raises(ValueError, match="session_id"):
        memory.append("user", "hi", session_id="")
    with pytest.raises(TypeError):
        TieredMemory(summarizer=None, distiller=null_distiller)  # type: ignore[arg-type]


# --- 50-turns-ago survival ------------------------------------------------------


def test_fact_from_50_turns_ago_survives_into_tier2() -> None:
    memory = TieredMemory(
        summarizer=_concat,
        distiller=null_distiller,
        config=TieredMemoryConfig(tier1_max_turns=8, tier2_max_summaries=100),
    )
    memory.append("user", "my favorite fruit is PINEAPPLE and I adore it")
    for i in range(2, 51):
        memory.append("user", f"small talk number {i}")
    result = memory.retrieve("what is my favorite fruit")
    # Long gone from verbatim Tier 1...
    assert "PINEAPPLE" not in " ".join(t.content for t in result.tier1_recent)
    # ...but preserved and retrievable in a Tier-2 summary.
    assert result.tier2_summaries
    assert "PINEAPPLE" in result.tier2_summaries[0].text


def test_fact_from_50_turns_ago_survives_into_tier3_profile() -> None:
    memory = TieredMemory(
        summarizer=_concat,
        distiller=_topic_distiller,
        config=TieredMemoryConfig(tier1_max_turns=4, tier2_max_summaries=1),
    )
    # Session one carries the durable fact at turn 1.
    memory.append("user", "my dog's name is PICKLE", session_id="s1")
    for i in range(2, 26):
        memory.append("user", f"s1 chatter {i}", session_id="s1")
    # A much later conversation pushes session one's summary into Tier 3.
    for i in range(26, 51):
        memory.append("user", f"s2 chatter {i}", session_id="s2")

    result = memory.retrieve("what is my dog's name")
    profile_text = " ".join(f.value for f in result.tier3_profile)
    assert "PICKLE" in profile_text  # distilled into a durable profile row
    # The typed row carries provenance for the aged fact.
    dog_fact = next(f for f in result.tier3_profile if "PICKLE" in f.value)
    assert dog_fact.source_turn_ids and dog_fact.source_turn_ids[0] == 1
    assert dog_fact.last_updated_turn_id > 0
    # It has left the live Tier-2 view (it was distilled).
    assert all("PICKLE" not in s.text for s in result.tier2_summaries)


# --- owner-profile seeding ------------------------------------------------------


def test_seed_profile_facts_become_retrievable_tier3_rows() -> None:
    memory = TieredMemory(summarizer=_concat, distiller=null_distiller)
    memory.seed_profile_facts({"home": "Manhattan", "occupation": "software engineer"})
    result = memory.retrieve("where is home")
    keys = {f.key for f in result.tier3_profile}
    assert {"home", "occupation"} <= keys
    home = next(f for f in result.tier3_profile if f.key == "home")
    assert home.value == "Manhattan"
    assert home.source_turn_ids == ()  # a seed, not a distilled observation


# --- prompt composition (three memory sections with budgets) --------------------


def test_three_memory_sources_render_as_bounded_sections() -> None:
    memory = TieredMemory(
        summarizer=_concat,
        distiller=null_distiller,
        config=TieredMemoryConfig(tier1_max_turns=2, tier2_max_summaries=100),
    )
    memory.seed_profile_facts({"home": "Manhattan"})
    for i in range(1, 6):
        memory.append("user", f"conversation line {i}")

    composer = DynamicPromptComposer()
    composer.register(
        MemorySource(memory, 1, source_id="memory_tier1_recent", placement="turn", priority=12)
    )
    composer.register(
        MemorySource(memory, 2, source_id="memory_tier2_summary", placement="turn", priority=14)
    )
    composer.register(
        MemorySource(memory, 3, source_id="memory_tier3_profile", placement="stable", priority=22)
    )
    composed = composer.compose("conversation")
    rendered = {s.source_id: s for s in composed.sections}
    assert {"memory_tier1_recent", "memory_tier2_summary", "memory_tier3_profile"} <= set(rendered)
    for section in rendered.values():
        assert section.chars <= section_budget(composer, section.source_id)
    assert "conversation line 5" in rendered["memory_tier1_recent"].text  # recent verbatim
    assert "Manhattan" in rendered["memory_tier3_profile"].text  # durable profile


def section_budget(composer: DynamicPromptComposer, source_id: str) -> int:
    source = composer.get_source(source_id)
    assert source is not None
    return source.budget_chars


def test_memory_source_rejects_bad_tier() -> None:
    memory = TieredMemory(summarizer=_concat, distiller=null_distiller)
    with pytest.raises(ValueError, match="tier must be"):
        MemorySource(memory, 4, source_id="x", placement="turn", priority=10)


# --- build_prompting_stack wiring ----------------------------------------------


def test_prompting_stack_wires_tiered_memory_when_enabled() -> None:
    stack = build_prompting_stack(
        {
            "user_profile": {"home": "Manhattan", "occupation": "software engineer"},
            "memory": {"enabled": True, "tier1_max_turns": 4},
        }
    )
    assert stack.memory is not None
    assert isinstance(stack.memory.config, TieredMemoryConfig)
    assert stack.memory.config.tier1_max_turns == 4
    # Owner facts became Tier-3 seed rows (not a hardcoded string).
    seeded = {f.key for f in stack.memory.retrieve("home").tier3_profile}
    assert {"home", "occupation"} <= seeded
    # Three memory sections are registered on the composer.
    assert stack.composer is not None
    ids = set(stack.composer.sources())
    assert {"memory_tier1_recent", "memory_tier2_summary", "memory_tier3_profile"} <= ids
    # A live turn fed on the write path shows up in the composed Tier-1 section.
    stack.memory.append("user", "remember the blue umbrella")
    composed = stack.composer.compose("umbrella")
    tier3 = next(s for s in composed.sections if s.source_id == "memory_tier3_profile")
    assert "Manhattan" in tier3.text


def test_prompting_memory_is_off_by_default_and_fails_closed_on_unknown_keys() -> None:
    off = build_prompting_stack({"user_profile": {"home": "Manhattan"}})
    assert off.memory is None
    assert off.composer is not None
    assert not any(sid.startswith("memory_tier") for sid in off.composer.sources())
    with pytest.raises(ValueError, match="unsupported prompting.memory keys"):
        build_prompting_stack({"memory": {"enabled": True, "bogus": 1}})


def test_concat_summarizer_default_is_bounded() -> None:
    summarizer = ConcatSummarizer(max_chars=40)
    from parcel_robot.tiered_memory import Turn

    text = summarizer("", [Turn(1, "s", "user", "x" * 200)])
    assert len(text) <= 40
