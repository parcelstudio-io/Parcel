"""Research H5 — the capability proof for governed continual memory.

``research/20260823/governed-continual-memory/DESIGN.md``. The measurement lives
in that folder's harness and RESULTS.md; this file is the one capability test the
reduced-testing policy asks for, and it pins the four properties the product
seams would be worthless without:

1. **Something calls the distiller, and only when it is switched on.** The
   scheduler's flag defaults OFF and an OFF scheduler writes nothing; ON, a
   session close produces owner-fact rows from turns nobody hand-labelled. That
   is the defect P2-A's own handoff named ("Nothing schedules distillation") and
   it is the whole hypothesis.
2. **The synthetic-range refusal survives being scheduled.** A store with
   un-quarantined executor rows is refused, no fact is written, and the refusal
   latches instead of firing on every idle tick.
3. **A revoked fact does not come back on the next pass.** Measured as a defect
   with ``respect_revocations=False`` (the pre-H5 behaviour, kept reachable so
   the seeded-RED half is a flag rather than a patch) and closed with it on.
4. **Tiers 2/3 survive the process, and the world answer never claims the
   present.** A snapshot round-trips byte-identically and answers identically;
   every world sentence is past tense with its provenance attached, and a query
   the map has no evidence for is refused in words.

The owner's store is never opened: every store here is under ``tmp_path``, and
the negative control at the bottom pins that a pytest process cannot reach the
owner's path at all.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from parcel_robot.memory.conversation import FACT_OWNER_STATED, ConversationMemory
from parcel_robot.memory.episodes import (
    EPISODE_CONVERSATION,
    Episode,
    EpisodeLog,
    EpisodeStoreRefused,
)
from parcel_robot.memory.path import MemoryPathRefused, owner_store_paths
from parcel_robot.memory.scheduler import (
    TRIGGER_DISABLED,
    TRIGGER_IDLE,
    TRIGGER_REFUSED,
    TRIGGER_SESSION_CLOSE,
    ContinualMemoryConfig,
    ContinualMemoryScheduler,
    revoked_fact_keys,
)
from parcel_robot.memory.tiered import (
    TIERED_SNAPSHOT_SCHEMA,
    ConcatSummarizer,
    TieredMemory,
    TieredMemoryConfig,
    null_distiller,
)
from parcel_robot.online_map.answers import PlaceSighting, describe_place, what_is_around, where_is
from parcel_robot.owner_model.distiller import DeterministicFactProposer
from parcel_robot.owner_model.guard import SYNTHETIC_ID_RANGE, SYNTHETIC_WINDOWS
from parcel_robot.owner_model.policy import CONSENT_GRANTED

#: One short session that states two keepable facts and one distractor.
_TURNS: tuple[tuple[str, str], ...] = (
    ("user", "My sister's name is Hana and she lives nearby."),
    ("assistant", "I will remember Hana."),
    ("user", "I like short answers before coffee."),
    ("assistant", "Short before coffee."),
    ("user", "The kettle takes forever to boil."),
    ("assistant", "Old kettles are like that."),
)


def _memory(tmp_path: Path, name: str = "h5.sqlite3") -> ConversationMemory:
    return ConversationMemory(tmp_path / name)


def _scheduler(
    memory: ConversationMemory,
    *,
    enabled: bool = True,
    respect_revocations: bool = True,
    episodes: EpisodeLog | None = None,
) -> ContinualMemoryScheduler:
    return ContinualMemoryScheduler(
        memory=memory,
        config=ContinualMemoryConfig(
            enabled=enabled,
            idle_seconds=1.0,
            min_new_turns=1,
            turn_window=60,
            respect_revocations=respect_revocations,
        ),
        proposer=DeterministicFactProposer(),
        episodes=episodes,
    )


def _write_turns(memory: ConversationMemory, scheduler: ContinualMemoryScheduler) -> None:
    for role, text in _TURNS:
        memory.add(role, text)
        scheduler.note_turn()


# ==========================================================================
# 1 — the scheduler is the thing that was missing, and it is off by default
# ==========================================================================
def test_the_flag_is_off_by_default_and_an_off_scheduler_writes_nothing(
    tmp_path: Path,
) -> None:
    """A disabled scheduler still answers and still reports. It just does not learn."""

    assert ContinualMemoryConfig().enabled is False
    assert ContinualMemoryConfig.from_settings(None).enabled is False
    assert ContinualMemoryConfig.from_settings({}).enabled is False
    assert (
        ContinualMemoryConfig.from_settings({"memory": {"continual": {"enabled": True}}}).enabled
        is True
    )
    with pytest.raises(ValueError, match="unknown memory.continual keys"):
        ContinualMemoryConfig.from_settings({"memory": {"continual": {"enabld": True}}})

    memory = _memory(tmp_path)
    scheduler = _scheduler(memory, enabled=False)
    _write_turns(memory, scheduler)

    closed = scheduler.on_session_close("s1")
    idle = scheduler.on_idle(now=1e9)
    assert (closed.ran, closed.trigger) == (False, TRIGGER_DISABLED)
    assert (idle.ran, idle.trigger) == (False, TRIGGER_DISABLED)
    assert memory.owner_facts() == []
    memory.connection.close()


def test_a_session_close_distils_the_turns_and_records_an_episode(tmp_path: Path) -> None:
    """The hypothesis in one test: turns in, durable consented facts out, and a
    dated episode that points at them."""

    memory = _memory(tmp_path)
    episodes = EpisodeLog(tmp_path / "episodes.sqlite3")
    scheduler = _scheduler(memory, episodes=episodes)
    _write_turns(memory, scheduler)

    run = scheduler.on_session_close("s1", outcome="closed")
    assert run.ran is True
    assert run.trigger == TRIGGER_SESSION_CLOSE
    assert run.written >= 2

    values = [str(row["value"]) for row in memory.owner_facts(consent=CONSENT_GRANTED)]
    assert any("Hana" in value for value in values)
    assert any("short answers before coffee" in value for value in values)
    # The distractor produced no belief.
    assert not any("kettle" in value.lower() for value in values)

    assert run.episode is not None
    assert run.episode.kind == EPISODE_CONVERSATION
    assert run.episode.session_id == "s1"
    assert run.episode.fact_keys, "the episode must point at the facts the pass wrote"
    assert episodes.count() == 1
    stored = episodes.recent()[0]
    assert stored.episode_id == run.episode.episode_id
    assert stored.ended_wall_s >= stored.started_wall_s

    episodes.close()
    memory.connection.close()


def test_the_idle_tick_waits_for_quiet_and_for_new_turns(tmp_path: Path) -> None:
    """Both conditions, so a silent house costs nothing and a busy one is not
    distilled every minute."""

    memory = _memory(tmp_path)
    scheduler = _scheduler(memory)
    assert scheduler.on_idle(now=1e9).trigger == "no_new_turns"

    _write_turns(memory, scheduler)
    assert scheduler.on_idle(now=scheduler.clock()).trigger == "too_soon"
    run = scheduler.on_idle(now=1e9)
    assert (run.ran, run.trigger) == (True, TRIGGER_IDLE)
    assert scheduler.turns_since_pass == 0
    memory.connection.close()


# ==========================================================================
# 2 — the guard is preserved, and a scheduled caller latches it
# ==========================================================================
def _seed_synthetic_rows(path: Path) -> None:
    """Two rows inside card R27's measured id range and time window."""

    memory = ConversationMemory(path)
    low, _high = SYNTHETIC_ID_RANGE
    start, _end = SYNTHETIC_WINDOWS[0]
    for offset, text in enumerate(("go to the lamppost", "find the fountain")):
        memory.connection.execute(
            "INSERT INTO messages (id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (low + offset, "user", text, f"{start[:-2]}30"),
        )
    memory.connection.commit()
    memory.connection.close()


def test_an_unquarantined_synthetic_range_is_refused_and_the_refusal_latches(
    tmp_path: Path,
) -> None:
    """The scheduler cannot distil a store the guard refuses, and it says so once."""

    store = tmp_path / "synthetic.sqlite3"
    _seed_synthetic_rows(store)
    memory = ConversationMemory(store)
    scheduler = _scheduler(memory)
    _write_turns(memory, scheduler)

    first = scheduler.on_session_close("s1")
    assert (first.ran, first.trigger) == (False, TRIGGER_REFUSED)
    assert "quarantine" in first.detail.lower()
    assert memory.owner_facts() == []

    # Latched: the second call does not re-enter the guard, and still writes nothing.
    second = scheduler.on_idle(now=1e9)
    assert (second.ran, second.trigger) == (False, TRIGGER_REFUSED)
    assert scheduler.refusal
    assert memory.owner_facts() == []
    memory.connection.close()


# ==========================================================================
# 3 — a revoked fact does not come back on the next scheduled pass
# ==========================================================================
@pytest.mark.parametrize("respect_revocations", [True, False])
def test_a_scheduled_pass_reproposes_a_revoked_fact_only_with_the_flag_off(
    tmp_path: Path, respect_revocations: bool
) -> None:
    """SEEDED RED, as a flag rather than a patch.

    ``add_owner_fact`` upserts on ``key = ? AND deleted_at IS NULL``, so a
    soft-deleted row is invisible to the upsert and a later pass over the SAME
    turns INSERTS the fact again with ``consent='granted'``. With the tombstone
    check on, the candidate never reaches the policy.
    """

    memory = _memory(tmp_path, f"revocation_{respect_revocations}.sqlite3")
    scheduler = _scheduler(memory, respect_revocations=respect_revocations)
    _write_turns(memory, scheduler)
    scheduler.on_session_close("s1")

    (key,) = [
        str(row["key"]) for row in memory.owner_facts() if "Hana" in str(row["value"])
    ]
    assert memory.forget_owner_fact(key) == 1
    assert revoked_fact_keys(memory) == frozenset({key})
    assert not any("Hana" in str(row["value"]) for row in memory.owner_facts())

    # A later pass re-reads the same turns — the sentence is still in `messages`.
    scheduler.note_turn(5)
    scheduler.on_idle(now=1e9)

    came_back = any("Hana" in str(row["value"]) for row in memory.owner_facts())
    assert came_back is (not respect_revocations)
    memory.connection.close()


# ==========================================================================
# 4a — tiers 2/3 survive the process
# ==========================================================================
def test_a_tiered_snapshot_round_trips_byte_identically_and_answers_the_same(
    tmp_path: Path,
) -> None:
    """Persist -> reload -> identical answers, and a second save is the same bytes.

    The snapshot carries no clock for exactly this reason: two saves of one state
    must be comparable, so a diff between two snapshots shows what the robot
    LEARNED rather than when it was written down.
    """

    config = TieredMemoryConfig(tier1_max_turns=3, tier2_max_summaries=2)
    store = TieredMemory(
        summarizer=ConcatSummarizer(), distiller=null_distiller, config=config
    )
    store.seed_profile_facts({"home": "Brooklyn"})
    for index in range(12):
        store.append("user" if index % 2 == 0 else "assistant", f"turn {index}", session_id="s1")

    first = store.save(tmp_path / "tiered.json")
    reloaded = TieredMemory(
        summarizer=ConcatSummarizer(), distiller=null_distiller, config=config
    )
    restored = reloaded.load(first)
    second = reloaded.save(tmp_path / "tiered_again.json")

    assert restored > 0
    assert first.read_bytes() == second.read_bytes()
    assert store.stats() == reloaded.stats()
    before = store.retrieve("turn")
    after = reloaded.retrieve("turn")
    assert before.tier1_recent == after.tier1_recent
    assert before.tier2_summaries == after.tier2_summaries
    assert before.tier3_profile == after.tier3_profile

    # A snapshot from another schema is refused rather than half-loaded.
    with pytest.raises(ValueError, match="unknown tiered-memory snapshot schema"):
        reloaded.restore({"schema": "parcel.tiered_memory.v0"})
    assert TIERED_SNAPSHOT_SCHEMA in first.read_text(encoding="utf-8")


# ==========================================================================
# 4b — the world answer never claims the present
# ==========================================================================
def test_the_world_answer_is_past_tense_label_primary_and_refuses_what_it_never_saw() -> None:
    seen = PlaceSighting(
        entry_id="place-1",
        label="bench",
        distance_m=4.2,
        bearing_rad=1.3,
        last_seen_wall_s=1_000.0,
        visits=2,
        names=("reading corner",),
    )
    answer = where_is("bench", [seen], now_wall_s=1_300.0)
    assert answer.answered is True
    assert answer.text.startswith("I last saw a bench")
    assert "reading corner" in answer.text
    assert "a few minutes ago" in answer.text
    assert "on two separate visits" in answer.text
    # The rule the module exists for: no present-tense presence claim.
    for forbidden in ("there is", "there's", "is at", "you'll find"):
        assert forbidden not in answer.text.lower()

    refusal = where_is(
        "fountain", [], now_wall_s=1_300.0, answered=False, alternatives=("a bench",)
    )
    assert refusal.answered is False
    assert "have not seen" in refusal.text
    assert "a bench" in refusal.text

    # An admitted verdict with no evidence is still a refusal: the renderer will
    # not write a sentence about a place it was handed nothing for.
    assert where_is("bench", [], now_wall_s=1_300.0, answered=True).answered is False

    around = what_is_around([seen], now_wall_s=1_300.0)
    assert around.text.startswith("Last time I looked")
    assert "bench" in around.text

    # A proposed name identical to the label is not repeated back as a nickname.
    plain = PlaceSighting(
        entry_id="place-2",
        label="lamppost",
        distance_m=12.0,
        bearing_rad=0.0,
        last_seen_wall_s=0.0,
        names=("lamppost",),
    )
    assert "calling the" not in describe_place(plain, now_wall_s=100_000.0)


# ==========================================================================
# the episodic layer refuses the owner's store by identity
# ==========================================================================
def test_the_episode_log_refuses_the_owners_conversation_store(tmp_path: Path) -> None:
    with pytest.raises(EpisodeStoreRefused, match="owner's conversation store"):
        EpisodeLog(owner_store_paths()[0])

    log = EpisodeLog(tmp_path / "episodes.sqlite3")
    episode = Episode(
        episode_id="e1",
        kind=EPISODE_CONVERSATION,
        started_wall_s=10.0,
        ended_wall_s=20.0,
        summary="a short conversation about the garden",
        outcome="closed",
        turn_ids=(1, 2),
        fact_keys=("preference",),
    )
    log.append(episode)
    assert log.recent()[0] == episode
    assert log.since(5.0)[0].episode_id == "e1"
    with pytest.raises(sqlite3.IntegrityError):
        log.append(episode)  # an episode id is written once
    with pytest.raises(ValueError, match="unsupported episode kind"):
        Episode(
            episode_id="e2",
            kind="daydream",
            started_wall_s=1.0,
            ended_wall_s=2.0,
            summary="x",
            outcome="y",
        )
    log.close()


# ==========================================================================
# the negative control
# ==========================================================================
def test_nothing_in_this_file_can_reach_the_owners_store() -> None:
    """Card R27 forces a pytest process to ``purpose=test``, so the owner's path
    is a refusal from inside this suite."""

    with pytest.raises(MemoryPathRefused):
        ConversationMemory(owner_store_paths()[0])
    assert FACT_OWNER_STATED == "owner_stated"
