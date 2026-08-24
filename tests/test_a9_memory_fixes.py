"""Card A9 — H5's four verified memory defects, each reproduced then fixed.

``scrum/20260824/task_2/IMPLEMENTATION_PLAN.md`` row A9; the defects and their
file:line are ``research/20260823/governed-continual-memory/VERDICT.md`` §4,
where Fable verified all four independently. Each section below carries the
MEASURED before-number as well as the after-number, because "it is fixed"
without the number it was fixed from is not a measurement.

The four:

1. ``distil_session(session_id=…)`` read ZERO turns on every store, forever —
   the filter tests ``turn["session_id"]`` and the reader never emitted the key
   (3 turns in, ``turns_read 0``; ``session_id=None`` read 3).
2. ``LanguageModelFactProposer`` never parsed: the only seam was the
   conversational ``decide``, whose grammar pins the answer to a 500-character
   ``reply`` string, so 13/13 measured calls degraded silently to the regex
   proposer.
3. ``add_owner_fact`` upserted past tombstones: add -> forget -> add left row
   id 2 alive beside the dead row 1 (1 live / 2 total), and a scheduled pass
   that was not the H5 scheduler resurrected a revoked fact.
4. The shipped ranking margin refuses every query the online map can ask:
   ``ranking_margin([5.2] + [0.0]*7) == 0.0`` against a threshold of 1.0
   (H5 M6: 0/20 admitted shipped, 20/20 at ``label_strength``).

NO OWNER STORE IS EVER OPENED HERE. Every store is a fresh file under pytest's
``tmp_path``; ``PARCEL_MEMORY_PURPOSE`` is never set; no hosted call is made
(the model rows use hand-written doubles and a monkeypatched transport).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.memory.conversation import (
    FACT_OWNER_STATED,
    OWNER_FACTS_TABLE,
    ConversationMemory,
)
from parcel_robot.memory.scheduler import (
    ContinualMemoryConfig,
    ContinualMemoryScheduler,
    revoked_fact_keys,
)
from parcel_robot.models import AgentDecision
from parcel_robot.online_map.entries import MapObservation, WriterProvenance
from parcel_robot.online_map.online_map import OnlineSemanticMap
from parcel_robot.owner_model.distiller import (
    FACT_RESPONSE_SCHEMA,
    DeterministicFactProposer,
    LanguageModelFactProposer,
    distil_session,
)
from parcel_robot.owner_model.policy import CONSENT_GRANTED
from parcel_robot.perception.abstention import (
    MIN_RANKING_MARGIN,
    RANKING_MARGIN_LABEL_STRENGTH,
    RANKING_MARGIN_ROBUST_Z,
    STRAY_LABEL_STRENGTH,
    AbstentionPolicy,
    label_strength_margin,
    ranking_margin,
    use_abstention_policy,
)
from parcel_robot.providers import LlamaCppProvider
from parcel_robot.runtime import RobotRuntime

# The sentences H5 measured on, kept verbatim so the numbers stay comparable.
OWNER_TURNS: tuple[tuple[str, str], ...] = (
    ("user", "My sister is called Hana and she lives two streets away."),
    ("assistant", "Noted."),
    ("user", "I usually walk before breakfast."),
)


def _hana_keys(memory: ConversationMemory) -> list[str]:
    """Every key the deterministic proposer derived from the sister sentence."""

    return [
        str(row["key"]) for row in memory.owner_facts() if "Hana" in str(row["value"])
    ]


def _rows_for(memory: ConversationMemory, key: str) -> int:
    """How many rows — live or tombstoned — that key owns. One, since A9."""

    return sum(
        1 for row in memory.owner_facts(include_deleted=True) if row["key"] == key
    )


def _store(tmp_path: Path, name: str = "a9.sqlite3") -> ConversationMemory:
    """A memory on a fresh file. Never the owner's, never read-write shared."""

    return ConversationMemory(tmp_path / name)


# ==========================================================================
# Defect 1 — the session-id filter that read zero turns
# ==========================================================================


class _PreA9Reader:
    """The reader as it was: no ``session_id`` key on any turn.

    This is the seed-RED arm and it is not a patch of the product — it is the
    exact shape ``conversation_turns`` returned before this card, wrapped around
    a real store so every other call (the guard, the writes) is the real one.
    """

    def __init__(self, memory: ConversationMemory) -> None:
        self._memory = memory

    def conversation_turns(self, *, limit: int = 40) -> list[dict[str, object]]:
        rows = self._memory.conversation_turns(limit=limit)
        return [{k: v for k, v in row.items() if k != "session_id"} for row in rows]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._memory, name)


def test_the_session_filter_read_zero_turns_before_this_card(tmp_path: Path) -> None:
    """SEEDED RED: H5's measurement, reproduced through the product function."""

    memory = _store(tmp_path, "d1_red.sqlite3")
    for role, text in OWNER_TURNS:
        memory.add(role, text, session_id="s1")

    blind = _PreA9Reader(memory)
    assert distil_session(blind, session_id="s1").turns_read == 0  # the defect
    assert distil_session(blind, session_id=None).turns_read == 3  # H5's control
    memory.connection.close()


def test_the_session_filter_now_reads_exactly_that_session(tmp_path: Path) -> None:
    memory = _store(tmp_path, "d1_green.sqlite3")
    for role, text in OWNER_TURNS:
        memory.add(role, text, session_id="s1")
    memory.add("user", "I moved to Brooklyn last spring.", session_id="s2")

    assert distil_session(memory, session_id="s1").turns_read == 3
    assert distil_session(memory, session_id="s2").turns_read == 1
    assert distil_session(memory, session_id=None).turns_read == 4
    # A session id that matches nothing reads nothing — that is the filter
    # working, and it is why the scheduler bounds by turn window instead.
    assert distil_session(memory, session_id="never-happened").turns_read == 0
    memory.connection.close()


def test_the_reader_reports_the_column_and_legacy_rows_stay_honest(
    tmp_path: Path,
) -> None:
    """``add`` can stamp a session; a row written without one says ``None``."""

    memory = _store(tmp_path, "d1_column.sqlite3")
    memory.add("user", "stamped", session_id="s9")
    memory.add("user", "unstamped")
    rows = {str(row["content"]): row["session_id"] for row in memory.conversation_turns()}
    assert rows == {"stamped": "s9", "unstamped": None}
    memory.connection.close()


# ==========================================================================
# Defect 2 — the proposer that could never parse
# ==========================================================================

#: The reply Fable's single live call produced (VERDICT §4.2), verbatim.
MEASURED_PROSE_REPLY = (
    "I have noted that your sister's name is Hana, she lives two streets away, "
    "and that you usually walk before breakfast."
)


class _ConversationalModel:
    """A model reachable ONLY through ``decide`` — the pre-A9 seam."""

    def __init__(self, reply: str = MEASURED_PROSE_REPLY) -> None:
        self.reply = reply
        self.decide_calls = 0

    def decide(self, transcript: str, tools: list[Any], context: list[Any]) -> AgentDecision:
        self.decide_calls += 1
        return AgentDecision(reply=self.reply)


class _ConstrainedModel(_ConversationalModel):
    """The same model with A9's constrained JSON mode available."""

    def __init__(self) -> None:
        super().__init__()
        self.json_calls: list[dict[str, Any]] = []

    def complete_json(
        self,
        transcript: str,
        *,
        system_prompt: str,
        response_schema: dict[str, Any],
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> str:
        self.json_calls.append(
            {
                "transcript": transcript,
                "system_prompt": system_prompt,
                "response_schema": response_schema,
            }
        )
        return json.dumps(
            {
                "facts": [
                    {
                        "key": "sister_name",
                        "value": "their sister is called Hana",
                        "confidence": 0.9,
                    },
                    {
                        "key": "morning_routine",
                        "value": "they usually walk before breakfast",
                        "confidence": 0.8,
                    },
                ]
            }
        )


def _turns() -> list[dict[str, object]]:
    return [{"speaker": role, "content": text} for role, text in OWNER_TURNS]


def test_the_conversational_seam_parses_nothing_and_degrades_silently() -> None:
    """SEEDED RED: 0/13 parseable, and the proposer equalled the regex one."""

    model = _ConversationalModel()
    proposer = LanguageModelFactProposer(model=model)
    turns = _turns()

    got = tuple(proposer(turns))
    assert model.decide_calls == 1
    assert proposer.structured_calls == 0
    assert proposer.fallbacks == 1  # the degrade is COUNTED now, not silent
    assert got == tuple(DeterministicFactProposer()(turns))


def test_the_constrained_seam_returns_the_array_the_parser_wants() -> None:
    model = _ConstrainedModel()
    proposer = LanguageModelFactProposer(model=model)

    got = list(proposer(_turns()))
    assert [candidate.key for candidate in got] == ["sister_name", "morning_routine"]
    assert (proposer.calls, proposer.structured_calls, proposer.fallbacks) == (1, 1, 0)
    assert model.decide_calls == 0  # the dialogue seam is not used for this

    (call,) = model.json_calls
    assert call["response_schema"] is FACT_RESPONSE_SCHEMA
    assert "JSON array" in call["system_prompt"]
    assert "Hana" in call["transcript"]


def test_an_unparseable_constrained_reply_still_degrades_and_says_so() -> None:
    """The contract that must survive the fix: never break the caller."""

    class _Broken(_ConstrainedModel):
        def complete_json(self, transcript: str, **kwargs: Any) -> str:
            raise RuntimeError("server said no")

    proposer = LanguageModelFactProposer(model=_Broken())
    turns = _turns()
    assert tuple(proposer(turns)) == tuple(DeterministicFactProposer()(turns))
    assert proposer.fallbacks == 1


def test_the_provider_asks_for_the_fact_schema_and_never_the_decision_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No socket: the transport is captured. $0."""

    captured: dict[str, Any] = {}

    def _fake_post(url: str, payload: dict[str, Any], timeout: float, **kwargs: Any):
        captured["url"] = url
        captured["payload"] = payload
        return {"choices": [{"message": {"content": '{"facts": []}'}}]}

    monkeypatch.setattr("parcel_robot.providers._post_json", _fake_post)

    provider = LlamaCppProvider(base_url="http://127.0.0.1:9", model="test-model")
    out = provider.complete_json(
        "Turns:\nowner: hello",
        system_prompt="list durable facts",
        response_schema=FACT_RESPONSE_SCHEMA,
    )
    assert out == '{"facts": []}'
    payload = captured["payload"]
    assert payload["response_format"]["schema"] is FACT_RESPONSE_SCHEMA
    assert payload["stream"] is False
    assert payload["messages"][0] == {"role": "system", "content": "list durable facts"}
    # The decision schema frames the call as Parcel's own turn. This one must not.
    assert "TOOLS=" not in payload["messages"][0]["content"]


def test_the_background_call_cannot_cancel_a_live_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A distillation pass at session close must not kill a spoken turn."""

    monkeypatch.setattr(
        "parcel_robot.providers._post_json",
        lambda *a, **k: {"choices": [{"message": {"content": "[]"}}]},
    )

    def _forbidden(*args: Any, **kwargs: Any):  # pragma: no cover - must not run
        raise AssertionError("complete_json must not take the cancellable path")

    provider = LlamaCppProvider(base_url="http://127.0.0.1:9", model="test-model")
    monkeypatch.setattr(provider, "_request_structured", _forbidden)
    provider.complete_json("x", system_prompt="y", response_schema={"type": "object"})
    assert provider._active_cancel is None


# ==========================================================================
# Defect 3 — the upsert that could not see a tombstone
# ==========================================================================


def _pre_a9_upsert(memory: ConversationMemory, *, key: str, value: str) -> int:
    """The write as it was: a lookup that filtered the tombstone away."""

    existing = memory.connection.execute(
        f"SELECT id FROM {OWNER_FACTS_TABLE} "
        "WHERE key = ? AND deleted_at IS NULL ORDER BY id DESC LIMIT 1",
        (key,),
    ).fetchone()
    if existing is not None:  # pragma: no cover - the red arm never gets here
        return int(existing[0])
    cursor = memory.connection.execute(
        f"INSERT INTO {OWNER_FACTS_TABLE} (key, value, category, provenance, consent, "
        "confidence, reason, session_id, source_turn_ids, writer) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (key, value, None, FACT_OWNER_STATED, CONSENT_GRANTED, 1.0, None, None, "", "test"),
    )
    memory.connection.commit()
    return int(cursor.lastrowid or 0)


def test_the_old_upsert_left_two_rows_for_one_key(tmp_path: Path) -> None:
    """SEEDED RED: H5's ``defect3`` repro — 1 live / 2 including deleted."""

    memory = _store(tmp_path, "d3_red.sqlite3")
    first = memory.add_owner_fact(
        key="sister_name",
        value="their sister is called Hana",
        provenance=FACT_OWNER_STATED,
        consent=CONSENT_GRANTED,
    )
    assert memory.forget_owner_fact("sister_name") == 1
    second = _pre_a9_upsert(
        memory, key="sister_name", value="their sister is called Hana"
    )

    assert second != first
    assert len(memory.owner_facts(include_deleted=True)) == 2
    assert len(memory.owner_facts()) == 1
    memory.connection.close()


def test_the_upsert_now_revives_the_row_it_could_not_see(tmp_path: Path) -> None:
    memory = _store(tmp_path, "d3_green.sqlite3")
    first = memory.add_owner_fact(
        key="sister_name",
        value="their sister is called Hana",
        provenance=FACT_OWNER_STATED,
        consent=CONSENT_GRANTED,
    )
    assert memory.forget_owner_fact("sister_name") == 1
    again = memory.add_owner_fact(
        key="sister_name",
        value="their sister is called Hana",
        provenance=FACT_OWNER_STATED,
        consent=CONSENT_GRANTED,
    )

    assert again == first  # one key, one row, for the life of the store
    rows = memory.owner_facts(include_deleted=True)
    assert len(rows) == 1
    assert rows[0]["deleted_at"] is None
    assert memory.revoked_fact_keys() == frozenset()
    memory.connection.close()


def test_a_model_proposal_never_resurrects_what_the_owner_revoked(
    tmp_path: Path,
) -> None:
    """The half the H5 scheduler's proposer wrapper could not cover: the WRITE.

    ``distil_session`` is the product path and now refuses on ANY caller's
    behalf, not only the scheduler's.
    """

    memory = _store(tmp_path, "d3_revoke.sqlite3")
    for role, text in OWNER_TURNS:
        memory.add(role, text, session_id="s1")

    first = distil_session(memory)
    assert first.written >= 1
    keys = _hana_keys(memory)
    assert keys
    for key in keys:
        assert memory.forget_owner_fact(key) == 1
    assert revoked_fact_keys(memory) == frozenset(keys)

    second = distil_session(memory)
    assert sorted(row.candidate.key for row in second.revoked) == sorted(keys)
    assert not any("Hana" in str(row["value"]) for row in memory.owner_facts())

    # SEEDED RED, one flag: the pre-A9 behaviour is still reachable and still
    # resurrects, so the difference stays a measurement.
    third = distil_session(memory, respect_revocations=False)
    assert third.revoked == ()
    assert any("Hana" in str(row["value"]) for row in memory.owner_facts())
    memory.connection.close()


def test_the_scheduler_flag_now_reaches_the_write_as_well(tmp_path: Path) -> None:
    memory = _store(tmp_path, "d3_sched.sqlite3")
    for role, text in OWNER_TURNS:
        memory.add(role, text, session_id="s1")
    scheduler = ContinualMemoryScheduler(
        memory=memory,
        config=ContinualMemoryConfig(enabled=True, min_new_turns=1, idle_seconds=1.0),
        proposer=DeterministicFactProposer(),
    )
    scheduler.note_turn(1)
    run = scheduler.on_session_close("s1")
    assert run.ran and run.written >= 1

    for key in _hana_keys(memory):
        memory.forget_owner_fact(key)
    scheduler.note_turn(2)
    scheduler.on_idle(now=1e9)
    assert not any("Hana" in str(row["value"]) for row in memory.owner_facts())
    memory.connection.close()


def test_a_read_only_store_is_not_counted_as_a_write(tmp_path: Path) -> None:
    """``written`` counts rows that exist, not calls that were attempted."""

    memory = _store(tmp_path, "d3_ro.sqlite3")
    for role, text in OWNER_TURNS:
        memory.add(role, text)
    memory.connection.close()

    read_only = ConversationMemory(tmp_path / "d3_ro.sqlite3", read_only=True)
    report = distil_session(read_only)
    assert report.turns_read == 3
    assert report.written == 0
    read_only.connection.close()


# ==========================================================================
# The product path — the broker's own remember / forget / restart
# ==========================================================================


class _Agent:
    def __init__(self, memory: ConversationMemory) -> None:
        self.memory = memory


class _Lane:
    session_id = "s-product"


class _RuntimeStub:
    """Only the two attributes the two broker methods read.

    A7's idiom: the product's own unbound methods, invoked over a stub, so the
    row measures the SHIPPED code path without constructing a robot. The
    verifier lesson this answers is that a seeded store proves a guard and only
    the product caller proves the integration.
    """

    def __init__(self, memory: ConversationMemory) -> None:
        self.agent = _Agent(memory)
        self.realtime_lane = _Lane()


class _Decision:
    consent = CONSENT_GRANTED
    category = "name"
    reason = "the owner said so"


def test_consent_revoke_restate_and_restart_through_the_product_path(
    tmp_path: Path,
) -> None:
    """Gate 8's "run consent/revoke/restart through the product", end to end."""

    path = tmp_path / "product.sqlite3"
    memory = ConversationMemory(path)
    stub = _RuntimeStub(memory)

    written = RobotRuntime._realtime_remember_fact(
        stub, "sister_name", "their sister is called Hana", _Decision()
    )
    assert written["id"] > 0
    assert RobotRuntime._realtime_known_facts(stub)

    forgotten = RobotRuntime._realtime_forget_fact(stub, "sister_name")
    assert forgotten == {"forgotten": 1}
    assert RobotRuntime._realtime_known_facts(stub) == ()

    # A scheduled model pass over the same sentence must not undo the forget…
    memory.add("user", "My sister is called Hana.", session_id="s-product")
    report = distil_session(memory)
    assert any(row.candidate.key == "sister_name" for row in report.revoked)
    live_keys = {str(row["key"]) for row in memory.owner_facts()}
    assert "sister_name" not in live_keys

    # …but the OWNER saying it again must, and must not leave a second row.
    again = RobotRuntime._realtime_remember_fact(
        stub, "sister_name", "their sister is called Hana", _Decision()
    )
    assert again["id"] == written["id"]
    assert _rows_for(memory, "sister_name") == 1  # revived, never duplicated
    memory.connection.close()

    # Restart: the same file, a new connection, the same answer.
    reopened = ConversationMemory(path)
    assert RobotRuntime._realtime_known_facts(_RuntimeStub(reopened))
    assert _rows_for(reopened, "sister_name") == 1
    reopened.connection.close()


def test_revocation_is_per_key_and_this_card_does_not_change_that(
    tmp_path: Path,
) -> None:
    """A GAP, recorded rather than hidden. Found while wiring the row above.

    ``forget_owner_fact`` revokes a KEY, and the tombstone check — H5's and
    A9's alike — is a key comparison. The deterministic proposer derives more
    than one key from one sentence (``sister`` and ``sister_name`` from "my
    sister is called Hana"), so revoking one leaves the other free to be
    re-proposed with the same content under its own name. That is exactly what
    H5 measured (M4 is a per-key row) and A9 does not widen it: value- or
    embedding-level revocation matching is a decision with false-suppression
    risk and belongs to a card that can measure it. The row exists so the next
    reader finds it as a known bound rather than as a surprise.
    """

    memory = _store(tmp_path, "per_key.sqlite3")
    for role, text in OWNER_TURNS:
        memory.add(role, text, session_id="s1")
    distil_session(memory)
    keys = _hana_keys(memory)
    assert len(keys) > 1, "the proposer derives more than one key per sentence"

    memory.forget_owner_fact(keys[0])
    distil_session(memory)
    live = {str(row["key"]) for row in memory.owner_facts()}
    assert keys[0] not in live  # the revoked key stays revoked
    assert keys[1] in live  # its sibling is untouched — the bound, named
    memory.connection.close()


# ==========================================================================
# Defect 4 — the ranking margin that refused everything
# ==========================================================================

PROV = WriterProvenance(
    session_id="a9-test",
    seat="in_loop_query",
    detector_name="owlv2-b16-int8",
    scene_id="city_block",
)


def _observation(label: str, *, x: float, y: float, frame_id: str) -> MapObservation:
    return MapObservation(
        label=label,
        score=0.4,
        surface_x=x,
        surface_y=y,
        surface_z=1.2,
        range_m=4.0,
        bearing_rad=0.0,
        depth_m=4.0,
        extent_w_m=0.2,
        extent_h_m=3.0,
        inlier_pixels=800,
        frame_id=frame_id,
        visit_id="v0",
        observed_wall_s=100.0,
        robot_x=0.0,
        robot_y=0.0,
        provenance=PROV,
    )


def _seeded_map(policy: AbstentionPolicy | None) -> OnlineSemanticMap:
    m = OnlineSemanticMap(provenance=PROV, policy=policy)
    for i in range(8):
        m.note_frame(("lamppost", "tree"))
        m.note_pose(0.5 * i, 0.0)
        m.observe(_observation("lamppost", x=3.0, y=1.0, frame_id=f"a{i}"))
        m.observe(_observation("tree", x=-4.0, y=2.0, frame_id=f"b{i}"))
    return m


ENABLED_POLICY = AbstentionPolicy(
    enabled=True,
    signals=("label_support", "evidence_count", "ranking_margin"),
)


@pytest.fixture
def enabled_gate():
    """Install an ENABLED process policy, and put the default back afterwards."""

    use_abstention_policy(ENABLED_POLICY)
    try:
        yield ENABLED_POLICY
    finally:
        use_abstention_policy(None)


def test_the_estimator_itself_is_untouched_and_still_reads_zero() -> None:
    """A9 changes which estimator the map uses, never what either computes."""

    assert ranking_margin([5.2] + [0.0] * 7) == 0.0
    assert ranking_margin([2.909294, 0.0, 0.0, 0.0]) == 0.0
    assert label_strength_margin([5.2] + [0.0] * 7) == pytest.approx(
        5.2 / STRAY_LABEL_STRENGTH
    )
    assert label_strength_margin([5.2] + [0.0] * 7) == pytest.approx(43.333, abs=1e-3)


def test_an_enabled_gate_refused_every_single_match_query(enabled_gate) -> None:
    """SEEDED RED: the shipped estimator on the map's own background, 0/2."""

    m = _seeded_map(dataclasses.replace(ENABLED_POLICY, ranking_margin_mode=RANKING_MARGIN_ROBUST_Z))
    refusal = m.resolve("lamppost")
    assert not refusal.admitted
    assert refusal.verdict.reason == "indecisive_ranking"
    assert refusal.verdict.signals["ranking_margin"] == 0.0
    assert refusal.diagnostics["background_mad"] == 0.0
    assert [q for q in ("lamppost", "tree") if m.resolve(q).admitted] == []


def test_the_unconfigured_map_now_uses_the_estimator_its_background_fits(
    enabled_gate,
) -> None:
    """The fix, at the site the verdict names: the runtime passes no policy."""

    m = _seeded_map(None)
    grounded = m.resolve("lamppost")
    assert grounded.admitted
    assert grounded.verdict.reason == "grounded"
    assert grounded.verdict.signals["ranking_margin"] > MIN_RANKING_MARGIN
    assert [q for q in ("lamppost", "tree") if m.resolve(q).admitted] == ["lamppost", "tree"]


def test_nothing_the_robot_never_saw_is_admitted_either_way(enabled_gate) -> None:
    """C-3's ``admission_flip``: 0 is the only acceptable count, both arms."""

    absent = ("fire hydrant", "Narnia", "my office", "the moon", "a coffee shop")
    for policy in (None, dataclasses.replace(ENABLED_POLICY, ranking_margin_mode=RANKING_MARGIN_ROBUST_Z)):
        m = _seeded_map(policy)
        assert [q for q in absent if m.resolve(q).admitted] == []


def test_an_explicit_estimator_still_wins_including_the_cosine_one(
    enabled_gate,
) -> None:
    """The fix repairs the UNCONFIGURED path only. P0-D's arm stays available."""

    explicit = dataclasses.replace(
        ENABLED_POLICY, ranking_margin_mode=RANKING_MARGIN_ROBUST_Z
    )
    assert _seeded_map(explicit)._background_policy() is explicit
    label = dataclasses.replace(
        ENABLED_POLICY, ranking_margin_mode=RANKING_MARGIN_LABEL_STRENGTH
    )
    assert _seeded_map(label)._background_policy() is label
    chosen = _seeded_map(None)._background_policy()
    assert chosen is not None
    assert chosen.ranking_margin_mode == RANKING_MARGIN_LABEL_STRENGTH
    # Everything else about the process policy is carried, not replaced.
    assert dataclasses.replace(
        chosen, ranking_margin_mode=RANKING_MARGIN_ROBUST_Z
    ) == ENABLED_POLICY


def test_the_default_process_policy_is_still_the_shipped_one() -> None:
    """A9 introduces no new default. The gate is still off until configured."""

    assert AbstentionPolicy().enabled is False
    assert AbstentionPolicy().ranking_margin_mode == RANKING_MARGIN_ROBUST_Z


# ==========================================================================
# The absolute rule
# ==========================================================================


def test_no_test_in_this_file_can_reach_the_owners_store(tmp_path: Path) -> None:
    """The stores here are files this test made; the guard sees them as such."""

    memory = _store(tmp_path, "purpose.sqlite3")
    assert str(tmp_path) in str(memory.store.path)
    assert memory.writer == "test"
    memory.connection.close()
