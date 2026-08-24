"""Card P2-A — the owner model: facts the dog keeps, with consent.

WHAT THIS FILE PROVES
---------------------
The mechanism, on scratch stores, unit by unit:

* the privacy policy is a deterministic function of the text (§1),
* the ``owner_facts`` table stores, upserts, soft-deletes and filters (§2),
* the renderer and the answer path drop everything unconsented (§3),
* the distiller REFUSES a store whose synthetic range is un-quarantined, and
  proceeds once it is (§4),
* the broker's ``remember_fact`` proposes, lets the policy decide, and confirms
  what it stored (§5).

WHAT IT DOES NOT PROVE
----------------------
Nothing here opens a hosted session, and nothing here proves a real model
*chooses* to call ``remember_fact`` at the right moment. That is
``P2A_PREREGISTRATION.md`` row 10 and it is owner-gated on one live
``gpt-realtime`` session. The end-to-end probe family through the real lane is
``test_p2a_memory_probes.py``.

THE OWNER'S STORE IS NEVER OPENED HERE
--------------------------------------
Every store in this file is a ``tmp_path`` file or ``:memory:``. Card R27's
guard makes that structural rather than conventional — a pytest process cannot
declare itself the owner's stack, so ``ConversationMemory`` would refuse the
owner's path even if a test asked for it — and
``test_the_owner_store_is_not_reachable_from_this_file`` pins it from the
inside rather than trusting the ambient guarantee.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from parcel_robot.memory.conversation import (
    FACT_MODEL_PROPOSED,
    FACT_OWNER_STATED,
    OWNER_FACTS_TABLE,
    ConversationMemory,
)
from parcel_robot.memory.path import MemoryPathRefused, owner_store_paths
from parcel_robot.memory.tiered import (
    ConcatSummarizer,
    SummaryRecord,
    TieredMemory,
    TieredMemoryConfig,
)
from parcel_robot.models import ToolCall, ToolResult
from parcel_robot.owner_model import policy as privacy
from parcel_robot.owner_model.distiller import (
    DeterministicFactProposer,
    OwnerFactDistiller,
    distil_session,
    distil_turns,
)
from parcel_robot.owner_model.guard import (
    QUARANTINE_TABLE,
    SYNTHETIC_ID_RANGE,
    SYNTHETIC_WINDOWS,
    SyntheticRowsUnquarantined,
    assert_store_is_distillable,
    survey,
)
from parcel_robot.owner_model.notes import known_facts_answer, owner_notes_from_facts
from parcel_robot.owner_model.policy import (
    CONSENT_DENIED,
    CONSENT_GRANTED,
    CONSENT_PENDING,
    DISPOSITION_ASK,
    DISPOSITION_KEEP,
    DISPOSITION_REFUSE,
    decide,
)
from parcel_robot.realtime.tool_broker import (
    ANSWER_TOOLS,
    BROKER_TOOLS,
    STATUS_CONSENT_REQUIRED,
    STATUS_OK,
    STATUS_REJECTED,
    TOOL_REMEMBER_FACT,
    RealtimeToolBroker,
    ToolDoors,
    build_tool_specs,
)

#: The three runs the pre-registration marks rows 7 and 8 pass^3 over. Each
#: parametrized invocation gets its own ``tmp_path``, so the three share nothing.
RUNS = (1, 2, 3)


def _store(tmp_path: Path, name: str = "p2a.sqlite3") -> ConversationMemory:
    """A scratch store at an ABSOLUTE path. Never the owner's."""

    return ConversationMemory(tmp_path / name)


# ==========================================================================
# §0 — the isolation this whole card is conditional on
# ==========================================================================
def test_the_owner_store_is_not_reachable_from_this_file(tmp_path: Path) -> None:
    """R27's property, re-asserted from inside the card that writes facts.

    P2-A adds a SECOND table to the same file and a write path that runs on a
    background pass. If the isolation guard ever regressed, this card would be
    the one that quietly filled the owner's real database with derived beliefs.
    So the refusal is pinned here rather than assumed from
    ``test_owner_store_isolation.py`` — the cost is one test and the thing it
    buys is that P2-A's own suite fails first.
    """

    del tmp_path
    owner = owner_store_paths()[0]
    with pytest.raises(MemoryPathRefused) as refusal:
        ConversationMemory(owner)
    assert "OWNER'S conversation memory" in str(refusal.value)


# ==========================================================================
# §1 — the policy decides, and it is a function of the text
# ==========================================================================
@pytest.mark.parametrize(
    ("fact", "category", "disposition"),
    [
        ("their sister is called Hana", privacy.CATEGORY_NAME, DISPOSITION_KEEP),
        ("they like short answers before coffee", privacy.CATEGORY_PREFERENCE, DISPOSITION_KEEP),
        ("they usually walk the dog after dinner", privacy.CATEGORY_ROUTINE, DISPOSITION_KEEP),
        ("they live in Brooklyn", privacy.CATEGORY_PLACE, DISPOSITION_KEEP),
        ("their medication is amlodipine", privacy.CATEGORY_HEALTH, DISPOSITION_ASK),
        ("their salary is ninety thousand", privacy.CATEGORY_FINANCE, DISPOSITION_ASK),
        (
            "their brother is getting a divorce and nobody knows",
            privacy.CATEGORY_THIRD_PARTY,
            DISPOSITION_ASK,
        ),
        ("their wifi password is hunter2", privacy.CATEGORY_SECRET, DISPOSITION_REFUSE),
    ],
)
def test_the_policy_puts_the_cards_own_categories_where_the_card_says(
    fact: str, category: str, disposition: str
) -> None:
    """The card's list, item by item: names/preferences/routines/places yes;
    health/finance/third-party ask; and the one credential refusal this card
    declares as an addition."""

    verdict = decide(fact)
    assert verdict.category == category
    assert verdict.disposition == disposition


def test_the_sensitive_lists_are_checked_before_the_permissive_ones() -> None:
    """A sentence that is BOTH lands on the cautious side.

    "my sister's blood pressure medication" contains a relative (which would
    make it a ``name``) and a health term. Ordering is the policy; if a refactor
    ever turns the classifier into a registry loop, this is what catches it.
    """

    verdict = decide("their sister's blood pressure medication is amlodipine")
    assert verdict.category == privacy.CATEGORY_HEALTH
    assert verdict.disposition == DISPOSITION_ASK


def test_an_unclassified_fact_asks_rather_than_being_kept_silently() -> None:
    """The declared addition: ``other`` asks. Never a silent keep."""

    verdict = decide("the quarterly forecast has been rebased")
    assert verdict.category == privacy.CATEGORY_OTHER
    assert verdict.disposition == DISPOSITION_ASK
    assert verdict.consent == CONSENT_PENDING


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_an_empty_fact_is_not_a_fact(text: str) -> None:
    assert decide(text).disposition == DISPOSITION_REFUSE


def test_a_transcript_sized_fact_is_refused() -> None:
    """A "fact" longer than the cap is a transcript, and ``messages`` has those."""

    assert decide("x" * (privacy.MAX_FACT_CHARS + 1)).disposition == DISPOSITION_REFUSE


def test_the_verdict_is_deterministic() -> None:
    """Same text, same verdict — the property that makes the policy auditable."""

    first = decide("their sister is called Hana")
    for _ in range(5):
        again = decide("their sister is called Hana")
        assert again == first


def test_consent_is_derived_from_the_disposition_and_never_invented() -> None:
    """One mapping, one place. There is no fourth combination to reach."""

    assert decide("their sister is called Hana").consent == CONSENT_GRANTED
    assert decide("their medication is amlodipine").consent == CONSENT_PENDING
    assert decide("their password is hunter2").consent == CONSENT_DENIED


def test_only_a_keep_is_renderable_and_an_ask_is_still_storable() -> None:
    """The two properties every caller reads instead of re-deriving them."""

    keep = decide("their sister is called Hana")
    ask = decide("their medication is amlodipine")
    refuse = decide("their password is hunter2")
    assert (keep.renderable, keep.storable) == (True, True)
    assert (ask.renderable, ask.storable) == (False, True)
    assert (refuse.renderable, refuse.storable) == (False, False)


# ==========================================================================
# §2 — the table
# ==========================================================================
def test_the_table_is_created_beside_messages_and_nothing_else_moves(
    tmp_path: Path,
) -> None:
    """Additive: ``messages`` keeps its shape and its rows."""

    memory = _store(tmp_path)
    memory.add("user", "hello")
    before = memory.connection.execute("PRAGMA table_info(messages)").fetchall()

    reopened = ConversationMemory(tmp_path / "p2a.sqlite3")
    after = reopened.connection.execute("PRAGMA table_info(messages)").fetchall()
    assert after == before
    assert reopened.connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    tables = {
        row[0]
        for row in reopened.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert OWNER_FACTS_TABLE in tables


def test_a_fact_round_trips_with_its_provenance_and_consent(tmp_path: Path) -> None:
    memory = _store(tmp_path)
    memory.add_owner_fact(
        key="sister_name",
        value="their sister is called Hana",
        provenance=FACT_OWNER_STATED,
        consent=CONSENT_GRANTED,
        category=privacy.CATEGORY_NAME,
    )
    (row,) = memory.owner_facts()
    assert row["key"] == "sister_name"
    assert row["value"] == "their sister is called Hana"
    assert row["provenance"] == FACT_OWNER_STATED
    assert row["consent"] == CONSENT_GRANTED
    assert row["deleted_at"] is None


def test_a_second_fact_with_the_same_key_replaces_the_first(tmp_path: Path) -> None:
    """A profile is not an event log. The owner moved house; they do not live
    in two places."""

    memory = _store(tmp_path)
    memory.add_owner_fact(
        key="home",
        value="they live in Manhattan",
        provenance=FACT_OWNER_STATED,
        consent=CONSENT_GRANTED,
    )
    memory.add_owner_fact(
        key="home",
        value="they live in Brooklyn",
        provenance=FACT_OWNER_STATED,
        consent=CONSENT_GRANTED,
    )
    rows = memory.owner_facts()
    assert len(rows) == 1
    assert rows[0]["value"] == "they live in Brooklyn"


def test_the_writer_column_is_stamped_on_every_fact(tmp_path: Path) -> None:
    """Card R27's provenance discipline, applied to the new table.

    A pytest process is ``test``. If a fact ever appears in the owner's store
    carrying that stamp, the next audit does not have to guess where it came
    from — which is the entire argument for the column.
    """

    memory = _store(tmp_path)
    memory.add_owner_fact(
        key="sister_name",
        value="their sister is called Hana",
        provenance=FACT_OWNER_STATED,
        consent=CONSENT_GRANTED,
    )
    assert memory.owner_facts()[0]["writer"] == memory.writer == "test"


def test_forgetting_a_fact_soft_deletes_it_and_hides_it_from_every_reader(
    tmp_path: Path,
) -> None:
    """"Don't remember that." The row survives for the audit; the belief does not."""

    memory = _store(tmp_path)
    memory.add_owner_fact(
        key="sister_name",
        value="their sister is called Hana",
        provenance=FACT_OWNER_STATED,
        consent=CONSENT_GRANTED,
    )
    assert memory.forget_owner_fact("sister_name") == 1

    assert memory.owner_facts() == []
    assert memory.owner_facts(consent=CONSENT_GRANTED) == []
    assert owner_notes_from_facts(memory.owner_facts(consent=CONSENT_GRANTED)) == ()

    kept = memory.owner_facts(include_deleted=True)
    assert len(kept) == 1
    assert kept[0]["deleted_at"] is not None


def test_forgetting_a_key_that_was_never_there_is_zero_not_an_error(
    tmp_path: Path,
) -> None:
    assert _store(tmp_path).forget_owner_fact("nothing_like_this") == 0


def test_consent_can_be_granted_after_the_fact(tmp_path: Path) -> None:
    """The point of writing ``pending`` rows: "yes, remember that" has a row to
    point at."""

    memory = _store(tmp_path)
    memory.add_owner_fact(
        key="medication",
        value="their medication is amlodipine",
        provenance=FACT_OWNER_STATED,
        consent=CONSENT_PENDING,
    )
    assert owner_notes_from_facts(memory.owner_facts(consent=CONSENT_GRANTED)) == ()
    assert memory.set_owner_fact_consent("medication", CONSENT_GRANTED) == 1
    assert owner_notes_from_facts(memory.owner_facts(consent=CONSENT_GRANTED)) == (
        "their medication is amlodipine",
    )


@pytest.mark.parametrize("provenance", ["guessed", "", "OWNER_STATED", None])
def test_an_unknown_provenance_is_refused(tmp_path: Path, provenance: object) -> None:
    """Fail-closed on the column whose job is to say how much to trust the row."""

    memory = _store(tmp_path)
    with pytest.raises(ValueError, match="provenance"):
        memory.add_owner_fact(
            key="k",
            value="v",
            provenance=provenance,  # type: ignore[arg-type]
            consent=CONSENT_GRANTED,
        )


def test_a_read_only_store_reports_zero_rather_than_raising(tmp_path: Path) -> None:
    """A background distillation pass must not take a turn down with it."""

    path = tmp_path / "ro.sqlite3"
    ConversationMemory(path).add("user", "hello")
    read_only = ConversationMemory(path, read_only=True)
    assert (
        read_only.add_owner_fact(
            key="k",
            value="v",
            provenance=FACT_OWNER_STATED,
            consent=CONSENT_GRANTED,
        )
        == 0
    )
    assert read_only.forget_owner_fact("k") == 0


# ==========================================================================
# §3 — the consent boundary, on both paths out of the store
# ==========================================================================
def _seed_three(memory: ConversationMemory) -> None:
    for key, value, consent in (
        ("sister_name", "their sister is called Hana", CONSENT_GRANTED),
        ("medication", "their medication is amlodipine", CONSENT_PENDING),
        ("password", "their password is hunter2", CONSENT_DENIED),
    ):
        memory.add_owner_fact(
            key=key, value=value, provenance=FACT_OWNER_STATED, consent=consent
        )


def test_only_consented_facts_render_into_the_developer_instruction(
    tmp_path: Path,
) -> None:
    """Pre-registered probe row 4, on the DI half."""

    memory = _store(tmp_path)
    _seed_three(memory)
    notes = owner_notes_from_facts(memory.owner_facts())
    assert notes == ("their sister is called Hana",)


def test_only_consented_facts_appear_in_the_what_do_you_know_answer(
    tmp_path: Path,
) -> None:
    """Pre-registered probe row 4, on the answer half. Same filter, by design."""

    memory = _store(tmp_path)
    _seed_three(memory)
    assert known_facts_answer(memory.owner_facts()) == ("their sister is called Hana",)


def test_the_renderer_filters_even_when_the_query_did_not() -> None:
    """The consent boundary is INSIDE the renderer, not only in the caller.

    Seeded RED for the consent bypass: a caller that forgets ``consent=`` — or
    a future one that queries everything on purpose — still cannot leak a
    pending row into the prompt.
    """

    rows = [
        {"value": "their sister is called Hana", "consent": CONSENT_GRANTED},
        {"value": "their medication is amlodipine", "consent": CONSENT_PENDING},
        {"value": "their password is hunter2", "consent": CONSENT_DENIED},
        {"value": "a forgotten thing", "consent": CONSENT_GRANTED, "deleted_at": "now"},
    ]
    assert owner_notes_from_facts(rows) == ("their sister is called Hana",)


def test_the_note_block_is_bounded_and_deduped() -> None:
    rows = [{"value": f"fact {n}", "consent": CONSENT_GRANTED} for n in range(20)]
    rows.append({"value": "fact 0", "consent": CONSENT_GRANTED})
    notes = owner_notes_from_facts(rows, limit=6)
    assert len(notes) == 6
    assert len(set(notes)) == 6


def test_an_empty_store_renders_no_block_at_all(tmp_path: Path) -> None:
    """What keeps the pinned DI digest and the 25 sealed fixtures valid."""

    assert owner_notes_from_facts(_store(tmp_path).owner_facts()) == ()


# ==========================================================================
# §4 — the distiller, and the refusal that gates it
# ==========================================================================
def _seed_synthetic(path: Path, *, rows: int = 8) -> None:
    """Rows shaped exactly like the 256 card R27 measured: inside the id range,
    inside a measured window, no annotation columns, no owner-stack writer."""

    ConversationMemory(path).connection.close()
    connection = sqlite3.connect(path)
    low, _high = SYNTHETIC_ID_RANGE
    start, _end = SYNTHETIC_WINDOWS[0]
    when = datetime.strptime(start, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    with connection:
        for index in range(rows):
            stamp = (when + timedelta(seconds=30 * (index + 1))).strftime("%Y-%m-%d %H:%M:%S")
            connection.execute(
                "INSERT INTO messages(id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (low + index, "user", "go to the lamppost", stamp),
            )
    connection.close()


@pytest.mark.parametrize("run", RUNS)
def test_the_distiller_refuses_an_unquarantined_synthetic_range(
    tmp_path: Path, run: int
) -> None:
    """SEEDED RED, pass^3 (pre-registered row 7). Without the guard, this store
    teaches the robot about lampposts.

    The rows are the shape R27 measured. The refusal names the count, the id
    range and the command — an owner reading it must not have to go looking.
    """

    path = tmp_path / f"polluted_{run}.sqlite3"
    _seed_synthetic(path)
    memory = ConversationMemory(path)

    with pytest.raises(SyntheticRowsUnquarantined) as refusal:
        distil_session(memory)

    message = str(refusal.value)
    assert "8 row(s)" in message
    assert "2883" in message
    assert "quarantine_synthetic_memory.py --apply" in message
    assert memory.owner_facts() == [], "the refusal must write nothing"


def test_the_refusal_is_not_swallowed_by_a_value_error_guard(tmp_path: Path) -> None:
    """It is a ``RuntimeError`` on purpose — several call sites catch
    ``ValueError`` broadly to keep a turn alive, and this one must stop."""

    path = tmp_path / "polluted.sqlite3"
    _seed_synthetic(path)
    assert issubclass(SyntheticRowsUnquarantined, RuntimeError)
    assert not issubclass(SyntheticRowsUnquarantined, ValueError)
    with pytest.raises(RuntimeError):
        assert_store_is_distillable(ConversationMemory(path).connection)


@pytest.mark.parametrize("run", RUNS)
def test_quarantining_the_rows_clears_the_refusal(tmp_path: Path, run: int) -> None:
    """Pre-registered probe row 8, pass^3. The owner acts; the distiller proceeds."""

    path = tmp_path / f"polluted_{run}.sqlite3"
    _seed_synthetic(path)
    memory = ConversationMemory(path)
    low, high = SYNTHETIC_ID_RANGE
    with memory.connection:
        memory.connection.execute(
            f"CREATE TABLE {QUARANTINE_TABLE} (id TEXT, quarantined_at TEXT, "
            "quarantine_reason TEXT)"
        )
        memory.connection.execute(
            f"INSERT INTO {QUARANTINE_TABLE} SELECT id, 'now', 'test' FROM messages "
            "WHERE id BETWEEN ? AND ?",
            (low, high),
        )
        memory.connection.execute("DELETE FROM messages WHERE id BETWEEN ? AND ?", (low, high))

    memory.add("user", "My sister's name is Hana.")
    report = distil_session(memory)
    assert report.written >= 1
    assert [row["key"] for row in memory.owner_facts()] == ["sister_name"]
    assert report.guard["clean"] is True


def test_a_fresh_scratch_store_never_trips_the_guard(tmp_path: Path) -> None:
    """All three halves of the predicate must hold. A scratch store that happens
    to reach id 2883 carries TODAY's timestamps, not August 20th's."""

    memory = _store(tmp_path)
    with memory.connection:
        memory.connection.execute(
            "INSERT INTO messages(id, role, content) VALUES (?, ?, ?)",
            (SYNTHETIC_ID_RANGE[0], "user", "go to the lamppost"),
        )
    found = survey(memory.connection)
    assert found.clean is True
    assert found.suspect_rows == 0


def test_the_distiller_reads_only_what_the_owner_said(tmp_path: Path) -> None:
    """A robot that distils facts from its own replies builds a profile of
    itself and calls it the owner."""

    memory = _store(tmp_path)
    memory.add("assistant", "My name is Parcel and I love lampposts.")
    memory.add("assistant", "I always chase pigeons.")
    report = distil_session(memory)
    assert report.proposed == 0
    assert memory.owner_facts() == []


def test_the_distiller_stamps_its_proposals_as_proposals(tmp_path: Path) -> None:
    """The table must always be able to answer "did I say this, or did you work
    it out?"."""

    memory = _store(tmp_path)
    memory.add("user", "My sister's name is Hana.")
    distil_session(memory)
    assert memory.owner_facts()[0]["provenance"] == FACT_MODEL_PROPOSED


def test_a_sensitive_proposal_is_parked_pending_not_kept(tmp_path: Path) -> None:
    """Pre-registered probe row 5, on the distiller path."""

    memory = _store(tmp_path)
    memory.add("user", "My blood pressure medication is amlodipine.")
    report = distil_session(memory)
    assert [row.candidate.key for row in report.asked] == ["blood_pressure_medication"]
    assert report.kept == ()
    (row,) = memory.owner_facts()
    assert row["consent"] == CONSENT_PENDING
    assert owner_notes_from_facts(memory.owner_facts()) == ()


def test_the_proposer_never_decides_consent() -> None:
    """HLD §8.4's rule, as a shape rather than as a convention: the candidate
    type has nowhere to put a verdict."""

    (candidate,) = DeterministicFactProposer()(
        ({"speaker": "owner", "content": "My sister's name is Hana."},)
    )
    assert not hasattr(candidate, "consent")
    assert not hasattr(candidate, "disposition")


def test_a_low_confidence_proposal_is_dropped_before_the_policy_sees_it() -> None:
    """Confidence only ever narrows — it is the proposer's claim, not evidence."""

    class _Unsure:
        def __call__(self, turns: object) -> tuple:
            from parcel_robot.owner_model.distiller import FactCandidate

            del turns
            return (FactCandidate(key="k", value="they like tea", confidence=0.01),)

    report = distil_turns((), proposer=_Unsure())
    assert report.kept == ()
    assert len(report.refused) == 1


def test_the_tiered_memory_distiller_emits_only_keeps() -> None:
    """Tier 3 is rendered into prompts unconditionally by ``dynamic_prompting``,
    so a ``pending`` row reaching it would be a consent bypass by the side door."""

    distiller = OwnerFactDistiller()
    keep = distiller(
        SummaryRecord(
            summary_id=1,
            session_id="s",
            text="My sister's name is Hana.",
            source_turn_ids=(1,),
            updated_at_turn_id=1,
        )
    )
    assert [fact.key for fact in keep] == ["sister_name"]

    ask = distiller(
        SummaryRecord(
            summary_id=2,
            session_id="s",
            text="My blood pressure medication is amlodipine.",
            source_turn_ids=(2,),
            updated_at_turn_id=2,
        )
    )
    assert ask == ()


def test_the_distiller_drops_into_tiered_memory_where_null_distiller_was() -> None:
    """The protocol is satisfied: Tier 3 stops being seed-only."""

    memory = TieredMemory(
        summarizer=ConcatSummarizer(),
        distiller=OwnerFactDistiller(),
        config=TieredMemoryConfig(tier1_max_turns=1, tier2_max_summaries=1),
    )
    memory.append("user", "My sister's name is Hana.", session_id="a")
    memory.append("user", "something else entirely", session_id="b")
    memory.append("user", "and another", session_id="c")
    assert "sister_name" in {fact.key for fact in memory.profile()}


# ==========================================================================
# §5 — the broker's remember_fact region
# ==========================================================================
class _FactDoors:
    """A store seam that records what the broker asked for."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, str]] = {}
        self.decisions: list[object] = []

    def remember(self, key: str, fact: str, decision: object) -> dict[str, object]:
        self.decisions.append(decision)
        self.rows[key] = (fact, str(getattr(decision, "consent", "")))
        return {"id": len(self.rows)}

    def forget(self, key: str) -> dict[str, object]:
        return {"forgotten": 1 if self.rows.pop(key, None) else 0}

    def known(self) -> tuple[str, ...]:
        return tuple(
            fact for fact, consent in self.rows.values() if consent == CONSENT_GRANTED
        )


def _broker(doors: _FactDoors) -> RealtimeToolBroker:
    return RealtimeToolBroker(
        ToolDoors(
            validate=lambda call: ToolResult(name=call.name, accepted=True, message="ok"),
            status=dict,
            recall=lambda query: "",
            gesture=lambda name, intensity: "",
            pose=lambda name: "",
            navigate=lambda place, relation: "",
            remember_fact=doors.remember,
            forget_fact=doors.forget,
            known_facts=doors.known,
        )
    )


def _call(broker: RealtimeToolBroker, **arguments: object) -> dict:
    return json.loads(
        broker.handle(
            name=TOOL_REMEMBER_FACT, call_id="call_1", arguments=json.dumps(arguments)
        )
    )


def test_the_tool_is_on_the_surface_and_the_specs_match_it() -> None:
    assert TOOL_REMEMBER_FACT in BROKER_TOOLS
    assert [spec["name"] for spec in build_tool_specs()] == list(BROKER_TOOLS)


def test_the_tool_is_an_answer_tool_so_the_beat_cannot_go_quiet() -> None:
    """A robot that stores a fact about a person in silence is the outcome the
    consent design exists to prevent."""

    from parcel_robot.realtime.lane import DEFAULT_ANSWER_TOOLS

    assert TOOL_REMEMBER_FACT in ANSWER_TOOLS
    assert ANSWER_TOOLS == DEFAULT_ANSWER_TOOLS
    doors = _FactDoors()
    assert _call(_broker(doors), fact="their sister is called Hana")["answer"] is True


def test_an_admitted_fact_is_stored_and_the_result_says_what_was_stored() -> None:
    """Pre-registered probe row 6. R15's lesson applied to a write: the model
    narrates what it is handed."""

    doors = _FactDoors()
    broker = _broker(doors)
    result = _call(broker, fact="their sister is called Hana", key="sister_name")
    assert result["status"] == STATUS_OK
    assert result["stored"] is True
    assert "their sister is called Hana" in result["detail"]
    assert doors.rows["sister_name"] == ("their sister is called Hana", CONSENT_GRANTED)
    assert broker.snapshot()["facts_remembered"] == 1


def test_a_sensitive_fact_asks_and_is_not_kept() -> None:
    """Pre-registered probe row 5, on the tool path. The row exists as pending
    so "yes" has something to point at; ``stored`` is False because nothing
    about the owner has been kept."""

    doors = _FactDoors()
    broker = _broker(doors)
    result = _call(broker, fact="their medication is amlodipine")
    assert result["status"] == STATUS_CONSENT_REQUIRED
    assert result["stored"] is False
    assert result["category"] == privacy.CATEGORY_HEALTH
    assert doors.rows[result["key"]][1] == CONSENT_PENDING
    assert doors.known() == ()
    assert broker.snapshot()["facts_consent_asks"] == 1


def test_a_credential_never_reaches_the_store_at_all() -> None:
    """SEEDED RED for the consent bypass on the refusal arm: a ``refuse``
    verdict must not touch the door, not even to park a pending row."""

    doors = _FactDoors()
    broker = _broker(doors)
    result = _call(broker, fact="their wifi password is hunter2")
    assert result["status"] == STATUS_REJECTED
    assert result["stored"] is False
    assert doors.rows == {}
    assert doors.decisions == []
    assert broker.snapshot()["facts_refused"] == 1


def test_the_reason_the_policy_gave_travels_in_the_result() -> None:
    """The model must not have to invent an explanation for a decision it did
    not make."""

    result = _call(_broker(_FactDoors()), fact="their salary is ninety thousand")
    assert result["reason"] == decide("their salary is ninety thousand").reason


def test_forget_is_always_honoured_and_never_asks_the_policy() -> None:
    """Pre-registered probe row 3, on the tool path."""

    doors = _FactDoors()
    broker = _broker(doors)
    _call(broker, fact="their sister is called Hana", key="sister_name")
    result = _call(broker, action="forget", key="sister_name")
    assert result["status"] == STATUS_OK
    assert result["forgotten"] == 1
    assert doors.rows == {}
    assert broker.snapshot()["facts_forgotten"] == 1


def test_forgetting_something_never_stored_is_ok_not_a_refusal() -> None:
    """Making the owner argue with a robot about whether it ever had the fact
    is not a product."""

    result = _call(_broker(_FactDoors()), action="forget", key="never_stored")
    assert result["status"] == STATUS_OK
    assert result["forgotten"] == 0


def test_forget_accepts_the_fact_text_when_the_model_sends_no_key() -> None:
    """Both paths derive the key the same way, so a round trip lines up."""

    doors = _FactDoors()
    broker = _broker(doors)
    _call(broker, fact="their sister is called Hana")
    result = _call(broker, action="forget", fact="their sister is called Hana")
    assert result["forgotten"] == 1


def test_what_do_you_know_answers_from_the_table(tmp_path: Path) -> None:
    """Pre-registered probe row 4, through the tool."""

    del tmp_path
    doors = _FactDoors()
    broker = _broker(doors)
    _call(broker, fact="their sister is called Hana")
    _call(broker, fact="their medication is amlodipine")
    result = _call(broker, action="list")
    assert result["facts"] == ["their sister is called Hana"]
    assert result["count"] == 1
    assert "amlodipine" not in json.dumps(result)


def test_an_empty_table_says_so_plainly() -> None:
    result = _call(_broker(_FactDoors()), action="list")
    assert result["status"] == STATUS_OK
    assert result["count"] == 0
    assert "nothing kept" in result["detail"]


def test_a_remember_call_with_no_fact_is_refused_not_guessed() -> None:
    result = _call(_broker(_FactDoors()), action="remember")
    assert result["status"] == STATUS_REJECTED


def test_an_unwired_store_refuses_rather_than_pretending() -> None:
    """The ``_unwired`` contract: a host that has not connected the doors gets
    an honest refusal, never a broker that says it remembered something."""

    broker = RealtimeToolBroker(
        ToolDoors(
            validate=lambda call: ToolResult(name=call.name, accepted=True, message="ok"),
            status=dict,
            recall=lambda query: "",
            gesture=lambda name, intensity: "",
            pose=lambda name: "",
            navigate=lambda place, relation: "",
        )
    )
    result = _call(broker, fact="their sister is called Hana")
    assert result["status"] == STATUS_REJECTED
    assert "fact store is unavailable" in result["detail"]


def test_the_supervisor_still_sees_every_call() -> None:
    """It is a tool like any other; the privacy policy is additional, not
    instead."""

    seen: list[ToolCall] = []

    def _validate(call: ToolCall) -> ToolResult:
        seen.append(call)
        return ToolResult(name=call.name, accepted=False, message="not allowed here")

    broker = RealtimeToolBroker(
        ToolDoors(
            validate=_validate,
            status=dict,
            recall=lambda query: "",
            gesture=lambda name, intensity: "",
            pose=lambda name: "",
            navigate=lambda place, relation: "",
            remember_fact=lambda key, fact, decision: {"id": 1},
        )
    )
    result = _call(broker, fact="their sister is called Hana")
    assert result["status"] == STATUS_REJECTED
    assert [call.name for call in seen] == [TOOL_REMEMBER_FACT]


def test_remembering_is_never_counted_as_motion() -> None:
    """Nothing here reaches a door that can move the body, so the R11
    system-initiated gate has nothing to refuse."""

    doors = _FactDoors()
    broker = _broker(doors)
    broker.note_response_provenance("system")
    result = _call(broker, fact="their sister is called Hana")
    assert result["status"] == STATUS_OK
    assert broker.system_initiated_motion_refusals == 0
