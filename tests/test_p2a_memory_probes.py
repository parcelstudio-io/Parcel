"""Card P2-A — the pre-registered memory-probe family, through the real lane.

THE FAMILY WAS FIXED BEFORE ANY OF IT WAS MEASURED
--------------------------------------------------
``scrum/20260822/task_10/P2A_PREREGISTRATION.md``, written before the first
probe ran. Every row below carries its number. A row that did not pass is a
MISS in ``P2A_STATUS.md``, not a row that was re-specified afterwards.

WHAT "THROUGH THE REAL LANE" MEANS HERE
---------------------------------------
A real :class:`~parcel_robot.realtime.lane.RealtimeLane` driving the repo's
scripted ``FakeRealtimeServer`` over a real transport pair, a real
:class:`~parcel_robot.realtime.tool_broker.RealtimeToolBroker` with the real
privacy policy inside it, a real
:class:`~parcel_robot.memory.ConversationMemory` on a scratch file, and the
real :func:`~parcel_robot.realtime.prompting.render_developer_instruction`.
The only fakes are the socket, the clock and the speaker.

What that leaves unproven is stated once, here, rather than implied: **no
hosted model was involved.** The provider's function calls are scripted, so
these rows prove the machinery answers correctly when the model calls the tool
— never that the model chooses to. Pre-registered row 10 is that claim and it
is owner-gated on one live session.

pass^3
------
Rows marked pass^3 in the pre-registration are parametrized over three runs,
each on its own scratch store (``tmp_path`` is per-test-invocation, so the
three runs share nothing). One failure in three fails the row.

THE OWNER'S STORE
-----------------
Never opened. Every store here is under ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parcel_robot.memory import FACT_OWNER_STATED, ConversationMemory
from parcel_robot.models import ToolResult
from parcel_robot.owner_model import (
    CONSENT_GRANTED,
    CONSENT_PENDING,
    known_facts_answer,
    owner_notes_from_facts,
)
from parcel_robot.realtime.config import RealtimeConfig
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    function_call,
    handshake,
    response_done,
)
from parcel_robot.realtime.lane import MAX_TAIL_ITEMS, RealtimeLane
from parcel_robot.realtime.prompting import (
    MAX_OWNER_NOTES,
    DeveloperFlags,
    render_developer_instruction,
)
from parcel_robot.realtime.tool_broker import (
    STATUS_CONSENT_REQUIRED,
    STATUS_OK,
    TOOL_REMEMBER_FACT,
    RealtimeToolBroker,
    ToolDoors,
)
from parcel_robot.realtime.transport import transport_pair

#: The three runs every pass^3 row is measured over.
RUNS = (1, 2, 3)


class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _Sink:
    def begin_utterance(self) -> None:
        return None

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        del chunk, token

    def interrupt(self) -> None:
        return None


class _Session:
    """One lane + one broker + one store. The unit a "session" means here.

    Deliberately reconstructible against the SAME store path: a restart is a
    new ``_Session`` on the same file, which is exactly the thing probe row 1
    is about. Nothing is carried across in Python — if a fact survives, it
    survived on disk.
    """

    def __init__(self, store_path: Path, *, script: list[Step] | None = None) -> None:
        self.clock = _Clock()
        self.memory = ConversationMemory(store_path)
        self.script = script if script is not None else handshake()
        self.transports: list[object] = []
        self.servers: list[FakeRealtimeServer] = []
        self.broker = RealtimeToolBroker(
            ToolDoors(
                validate=lambda call: ToolResult(name=call.name, accepted=True, message="ok"),
                status=dict,
                recall=lambda query: "",
                gesture=lambda name, intensity: "",
                pose=lambda name: "",
                navigate=lambda place, relation: "",
                remember_fact=self._remember,
                forget_fact=self._forget,
                known_facts=self._known,
            )
        )
        self.lane = RealtimeLane(
            config=RealtimeConfig(enabled=True, source="test"),
            instructions="be a good dog",
            transport_factory=self._factory,
            sink=_Sink(),
            clock=self.clock,
            tool_handler=self.broker,
            memory_tail=lambda: self.memory.ledger_tail(limit=MAX_TAIL_ITEMS * 4),
            session_id_factory=lambda: "rt_probe",
            sleep=lambda _delay: None,
            jitter=lambda: 1.0,
        )

    # -- the runtime's doors, reproduced exactly (runtime.py is not importable
    # -- without a simulator backend, and the seam is three one-line methods)
    def _remember(self, key: str, fact: str, decision: object) -> dict[str, object]:
        consent = str(getattr(decision, "consent", CONSENT_PENDING))
        return {
            "id": self.memory.add_owner_fact(
                key=key,
                value=fact,
                provenance=FACT_OWNER_STATED,
                consent=consent,
                category=str(getattr(decision, "category", "")) or None,
                reason=str(getattr(decision, "reason", "")) or None,
            ),
            "consent": consent,
        }

    def _forget(self, key: str) -> dict[str, object]:
        return {"forgotten": self.memory.forget_owner_fact(key)}

    def _known(self) -> tuple[str, ...]:
        return known_facts_answer(self.memory.owner_facts(consent=CONSENT_GRANTED))

    # -- transport / pumping
    def _factory(self) -> object:
        lane_end, server_end = transport_pair(clock=self.clock)
        self.transports.append(lane_end)
        self.servers.append(
            FakeRealtimeServer(
                transport=server_end, script=list(self.script), clock=self.clock
            )
        )
        return lane_end

    def open(self) -> None:
        self.lane.open_session(handshake_token="tok", mic_gesture=True)
        self.settle()

    def settle(self, rounds: int = 4) -> None:
        for _ in range(rounds):
            self.servers[-1].pump()
            self.lane.pump()

    def outputs(self) -> list[dict]:
        """Every ``function_call_output`` the lane put on the wire."""

        sent = self.transports[-1].sent  # type: ignore[attr-defined]
        out: list[dict] = []
        for frame in sent:
            item = frame.get("item") if frame.get("type") == "conversation.item.create" else None
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                out.append(json.loads(item["output"]))
        return out

    def tail_items(self) -> list[tuple[str, str]]:
        """The (role, text) pairs replayed into the session at open."""

        sent = self.transports[-1].sent  # type: ignore[attr-defined]
        out: list[tuple[str, str]] = []
        for frame in sent:
            if frame.get("type") != "conversation.item.create":
                continue
            item = frame.get("item") or {}
            if item.get("type") != "message":
                continue
            content = item.get("content") or []
            text = "".join(str(part.get("text", "")) for part in content)
            out.append((str(item.get("role")), text))
        return out

    def developer_instruction(self) -> str:
        """The DI as the model would receive it at THIS session's open."""

        return render_developer_instruction(
            DeveloperFlags(
                owner_notes=owner_notes_from_facts(
                    self.memory.owner_facts(consent=CONSENT_GRANTED), limit=MAX_OWNER_NOTES
                )
            )
        ).text

    def close(self) -> None:
        self.lane.close()
        self.memory.connection.close()


def _tool_script(*calls: tuple[str, dict]) -> list[Step]:
    """A handshake, then one scripted ``remember_fact`` call per entry."""

    steps = handshake()
    for index, (call_id, arguments) in enumerate(calls):
        steps.append(
            Step(
                "input_audio_buffer.append",
                (
                    function_call(call_id, TOOL_REMEMBER_FACT, json.dumps(arguments)),
                    response_done(f"resp_{index}"),
                ),
                label=f"remember_fact:{call_id}",
            )
        )
    return steps


def _drive(session: _Session, count: int) -> None:
    """Fire ``count`` scripted provider turns."""

    for _ in range(count):
        session.lane.send_audio(b"\x00\x00" * 240)
        session.settle()


# ==========================================================================
# Row 1 — the sister's name survives a restart
# ==========================================================================
@pytest.mark.parametrize("run", RUNS)
def test_row1_a_fact_stored_in_one_session_is_there_in_the_next(
    tmp_path: Path, run: int
) -> None:
    """pass^3. Session A stores it through the lane; session B is a FRESH lane
    on the same file and finds it in the developer instruction and in the
    what-do-you-know answer.

    Nothing crosses in Python: session B constructs its own memory, broker and
    lane from the path alone.
    """

    store = tmp_path / f"probe_row1_{run}.sqlite3"

    first = _Session(
        store,
        script=_tool_script(
            ("call_a", {"fact": "their sister is called Hana", "key": "sister_name"})
        ),
    )
    first.open()
    _drive(first, 1)
    (stored,) = first.outputs()
    assert stored["status"] == STATUS_OK
    assert stored["stored"] is True
    first.close()

    second = _Session(store, script=_tool_script(("call_b", {"action": "list"})))
    second.open()
    assert "Hana" in second.developer_instruction()
    _drive(second, 1)
    (listed,) = second.outputs()
    assert listed["facts"] == ["their sister is called Hana"]
    second.close()


# ==========================================================================
# Row 2 — a stated preference is recalled unprompted next session
# ==========================================================================
@pytest.mark.parametrize("run", RUNS)
def test_row2_a_stated_preference_comes_back_unprompted(tmp_path: Path, run: int) -> None:
    """pass^3. The DISTILLER derives it — nobody called ``remember_fact`` — and
    it is in the next session's developer instruction with nothing asked for."""

    from parcel_robot.memory import FACT_MODEL_PROPOSED
    from parcel_robot.owner_model import distil_session

    store = tmp_path / f"probe_row2_{run}.sqlite3"
    talking = ConversationMemory(store)
    talking.add("user", "I like short answers before coffee.")
    talking.add("assistant", "Noted.")
    report = distil_session(talking)
    assert report.written >= 1
    talking.connection.close()

    later = _Session(store)
    later.open()
    instruction = later.developer_instruction()
    assert "short answers before coffee" in instruction
    assert "What you know about them:" in instruction
    (row,) = [f for f in later.memory.owner_facts() if f["key"] == "preference"]
    assert row["provenance"] == FACT_MODEL_PROPOSED
    later.close()


# ==========================================================================
# Row 3 — "don't remember that" is honored
# ==========================================================================
@pytest.mark.parametrize("run", RUNS)
def test_row3_forgetting_stops_the_fact_reaching_the_next_session(
    tmp_path: Path, run: int
) -> None:
    """pass^3. Soft-deleted on disk; gone from the answer and from the DI."""

    store = tmp_path / f"probe_row3_{run}.sqlite3"
    session = _Session(
        store,
        script=_tool_script(
            ("call_a", {"fact": "their sister is called Hana", "key": "sister_name"}),
            ("call_b", {"action": "forget", "key": "sister_name"}),
            ("call_c", {"action": "list"}),
        ),
    )
    session.open()
    _drive(session, 3)
    stored, forgotten, listed = session.outputs()
    assert stored["stored"] is True
    assert forgotten["forgotten"] == 1
    assert listed["facts"] == []
    session.close()

    after = _Session(store)
    after.open()
    assert "Hana" not in after.developer_instruction()
    assert after.memory.owner_facts() == []
    assert len(after.memory.owner_facts(include_deleted=True)) == 1
    after.close()


# ==========================================================================
# Row 4 — what-do-you-know lists only consented facts
# ==========================================================================
@pytest.mark.parametrize("run", RUNS)
def test_row4_only_consented_facts_are_listed_or_rendered(tmp_path: Path, run: int) -> None:
    """pass^3. Granted, pending and denied go in; only the granted one comes out
    of BOTH exits — the answer and the developer instruction."""

    store = tmp_path / f"probe_row4_{run}.sqlite3"
    seed = ConversationMemory(store)
    for key, value, consent in (
        ("sister_name", "their sister is called Hana", CONSENT_GRANTED),
        ("medication", "their medication is amlodipine", CONSENT_PENDING),
        ("password", "their password is hunter2", "denied"),
    ):
        seed.add_owner_fact(
            key=key, value=value, provenance=FACT_OWNER_STATED, consent=consent
        )
    seed.connection.close()

    session = _Session(store, script=_tool_script(("call_a", {"action": "list"})))
    session.open()
    _drive(session, 1)
    (listed,) = session.outputs()
    assert listed["facts"] == ["their sister is called Hana"]

    instruction = session.developer_instruction()
    assert "Hana" in instruction
    assert "amlodipine" not in instruction
    assert "hunter2" not in instruction
    session.close()


# ==========================================================================
# Row 5 — the dog says what it will not store
# ==========================================================================
@pytest.mark.parametrize("run", RUNS)
def test_row5_a_health_fact_asks_first_and_never_renders(tmp_path: Path, run: int) -> None:
    """pass^3. ``consent_required`` comes back, the row is parked pending, and
    the detail names the category so the model can say it aloud."""

    store = tmp_path / f"probe_row5_{run}.sqlite3"
    session = _Session(
        store,
        script=_tool_script(("call_a", {"fact": "their medication is amlodipine"})),
    )
    session.open()
    _drive(session, 1)
    (asked,) = session.outputs()

    assert asked["status"] == STATUS_CONSENT_REQUIRED
    assert asked["stored"] is False
    assert asked["category"] == "health"
    assert "health" in asked["detail"]
    assert asked["answer"] is True, "the beat carrying an ask must speak"

    (row,) = session.memory.owner_facts()
    assert row["consent"] == CONSENT_PENDING
    assert "amlodipine" not in session.developer_instruction()
    session.close()


# ==========================================================================
# Row 6 — the dog confirms aloud what it stored
# ==========================================================================
@pytest.mark.parametrize("run", RUNS)
def test_row6_the_result_carries_the_stored_text_and_must_be_spoken(
    tmp_path: Path, run: int
) -> None:
    """pass^3. ``answer: true`` (so the lane cannot suppress the beat) and the
    exact stored sentence in ``detail`` (so the confirmation is true rather than
    plausible)."""

    store = tmp_path / f"probe_row6_{run}.sqlite3"
    session = _Session(
        store,
        script=_tool_script(("call_a", {"fact": "their sister is called Hana"})),
    )
    session.open()
    _drive(session, 1)
    (stored,) = session.outputs()
    assert stored["answer"] is True
    assert "their sister is called Hana" in stored["detail"]
    assert session.memory.owner_facts()[0]["value"] == "their sister is called Hana"
    session.close()


# ==========================================================================
# Row 9 — full-ledger replay at session open
# ==========================================================================
@pytest.mark.parametrize("run", RUNS)
def test_row9_session_open_replays_both_lanes_deduped_and_capped(
    tmp_path: Path, run: int
) -> None:
    """pass^3. Legacy rows AND hosted rows, one duplicate pair, all in order.

    The pre-card behaviour was ``realtime_turns(limit=20)`` — hosted only — so
    the legacy line below is the thing that had never once reached a session.
    """

    store = tmp_path / f"probe_row9_{run}.sqlite3"
    seed = ConversationMemory(store)
    seed.add("user", "I typed this into the panel last year")
    seed.add("assistant", "and I answered it locally")
    seed.write_realtime_turn(
        session_id="s1", speaker="owner", text="and I said this out loud", origin="realtime"
    )
    seed.write_realtime_turn(
        session_id="s1", speaker="robot", text="and I answered that too", origin="realtime"
    )
    # The overlap the two write paths produce in the wild: the same sentence
    # logged by both. Replaying it twice teaches the model they said it twice.
    seed.add("user", "and I said this out loud")
    seed.connection.close()

    session = _Session(store)
    session.open()

    replayed = session.tail_items()
    assert replayed == [
        ("user", "I typed this into the panel last year"),
        ("assistant", "and I answered it locally"),
        ("user", "and I said this out loud"),
        ("assistant", "and I answered that too"),
    ]
    assert session.lane.tail_items_injected == 4
    assert session.lane.tail_items_deduped == 1
    assert session.lane.tail_items_dropped == 0
    session.close()


@pytest.mark.parametrize("run", RUNS)
def test_row9_the_replay_is_capped_at_the_stated_ceiling(tmp_path: Path, run: int) -> None:
    """pass^3. A store bigger than the cap opens a session with the cap, and the
    items kept are the NEWEST ones."""

    store = tmp_path / f"probe_row9_cap_{run}.sqlite3"
    seed = ConversationMemory(store)
    for index in range(MAX_TAIL_ITEMS + 40):
        seed.add("user", f"turn number {index}")
    seed.connection.close()

    session = _Session(store)
    session.open()
    replayed = session.tail_items()
    assert len(replayed) == MAX_TAIL_ITEMS
    assert session.lane.tail_items_dropped == 40
    assert replayed[-1] == ("user", f"turn number {MAX_TAIL_ITEMS + 39}")
    session.close()


# ==========================================================================
# Row 12 — the negative control
# ==========================================================================
def test_row12_nothing_in_this_file_can_reach_the_owners_store() -> None:
    """The card's absolute, pinned rather than promised.

    Card R27 forces a pytest process to ``purpose=test`` whatever it declares,
    so the owner's path is a refusal from inside this suite. The sha256 check in
    ``P2A_STATUS.md`` is the outside half of the same claim.
    """

    from parcel_robot.memory_path import MemoryPathRefused, owner_store_paths

    with pytest.raises(MemoryPathRefused):
        ConversationMemory(owner_store_paths()[0])


# ==========================================================================
# The product path — the runtime's own wiring, not a reconstruction of it
# ==========================================================================
#
# Everything above builds the lane and the broker by hand, which proves the
# MECHANISM and proves nothing about whether ``runtime.py`` actually connects
# it. These two tests close that gap: they build a real ``RobotRuntime`` with
# the hosted lane enabled and assert that the four seams P2-A added to it are
# live — the three owner-fact doors, the ``owner_notes`` provider, and the
# full-ledger row source. Without them, this card could ship a complete owner
# model that nothing calls.
REPO = Path(__file__).resolve().parents[1]


def _runtime_config(tmp_path: Path, store: Path) -> Path:
    path = tmp_path / "p2a-runtime.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: true
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: {store}
duplex:
  enabled: true
  logging: false
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def wired_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A real runtime, hosted lane on, text mode, on a scratch store."""

    from parcel_robot.audio_io import AudioDeviceStatus
    from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
    from parcel_robot.models import AgentDecision, VelocityCommand
    from parcel_robot.realtime.config import REALTIME_CONFIG_ENV
    from parcel_robot.runtime import RobotRuntime

    class _Backend:
        name = "p2a-runtime"

        def reset(self) -> None:
            return None

        def observe(self) -> SimObservation:
            return SimObservation(
                time_s=0.0,
                pose=RobotPose(),
                owner=OwnerTrack(),
                nearest_obstacle_m=10.0,
                backend="p2a-runtime",
            )

        def move(self, command: VelocityCommand) -> None:
            del command

        def stop(self) -> None:
            return None

        def emergency_stop(self) -> None:
            return None

        def pose(self, pose: object) -> None:
            del pose

        def trajectory(self, skill: object) -> None:
            del skill

        def move_owner(self, dx: float, dy: float) -> None:
            del dx, dy

    class _SilentModel:
        def decide(self, transcript, tools, context) -> AgentDecision:
            del transcript, tools, context
            return AgentDecision("Understood.")

    realtime = tmp_path / "realtime.yaml"
    realtime.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(realtime))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PARCEL_REALTIME_KEY_ENV", raising=False)

    runtime = RobotRuntime(
        _runtime_config(tmp_path, tmp_path / "runtime_store.sqlite3"),
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="p2a fixture",
        ),
    )
    try:
        yield runtime
    finally:
        runtime.close()


def test_the_runtime_wires_the_owner_fact_doors_and_the_notes_provider(
    wired_runtime,
) -> None:
    """The product path, end to end: tool call in, store row out, DI line back.

    Driven through ``broker.handle`` — the exact entry point the lane calls —
    so the supervisor, the privacy policy, the runtime doors and the store are
    all the real ones.
    """

    runtime = wired_runtime
    broker = runtime.realtime_broker
    assert broker is not None, "the hosted lane is on; the broker must exist"

    # The DI carries no owner-notes block before anything is stored.
    assert runtime._realtime_owner_notes() == ()
    assert "What you know about them:" not in runtime.realtime_instructions.current().text

    stored = json.loads(
        broker.handle(
            name=TOOL_REMEMBER_FACT,
            call_id="call_a",
            arguments=json.dumps(
                {"fact": "their sister is called Hana", "key": "sister_name"}
            ),
        )
    )
    assert stored["status"] == STATUS_OK
    assert stored["stored"] is True

    (row,) = runtime.agent.memory.owner_facts()
    assert row["value"] == "their sister is called Hana"
    assert row["provenance"] == FACT_OWNER_STATED
    assert row["consent"] == CONSENT_GRANTED

    # The DI provider is wired, and the block now renders.
    assert runtime._realtime_owner_notes() == ("their sister is called Hana",)
    refreshed = runtime.realtime_instructions.current().text
    assert "What you know about them:" in refreshed
    assert "their sister is called Hana" in refreshed

    listed = json.loads(
        broker.handle(
            name=TOOL_REMEMBER_FACT, call_id="call_b", arguments=json.dumps({"action": "list"})
        )
    )
    assert listed["facts"] == ["their sister is called Hana"]

    asked = json.loads(
        broker.handle(
            name=TOOL_REMEMBER_FACT,
            call_id="call_c",
            arguments=json.dumps({"fact": "their medication is amlodipine"}),
        )
    )
    assert asked["status"] == STATUS_CONSENT_REQUIRED
    assert "amlodipine" not in runtime.realtime_instructions.current().text

    forgot = json.loads(
        broker.handle(
            name=TOOL_REMEMBER_FACT,
            call_id="call_d",
            arguments=json.dumps({"action": "forget", "key": "sister_name"}),
        )
    )
    assert forgot["forgotten"] == 1
    assert runtime._realtime_owner_notes() == ()


def test_the_runtime_hands_the_lane_the_whole_ledger_not_the_hosted_tail(
    wired_runtime,
) -> None:
    """Work item 4, at the seam the runtime actually passes.

    The legacy row below is written through ``add()`` — the panel/voice path
    that produced all 2,618 of the owner's older rows — and ``realtime_turns``
    (the pre-card source) cannot see it. The provider the runtime hands the lane
    must.
    """

    runtime = wired_runtime
    memory = runtime.agent.memory
    memory.add("user", "I typed this into the panel")
    memory.write_realtime_turn(
        session_id="s1", speaker="owner", text="and I said this out loud", origin="realtime"
    )

    assert [row["content"] for row in memory.realtime_turns(limit=20)] == [
        "and I said this out loud"
    ]
    replayed = [row["content"] for row in memory.ledger_tail(limit=MAX_TAIL_ITEMS * 4)]
    assert replayed == ["I typed this into the panel", "and I said this out loud"]
    assert runtime.realtime_lane is not None
    assert runtime.realtime_lane._memory_tail is not None
    assert [
        row["content"] for row in runtime.realtime_lane._memory_tail()
    ] == replayed


# ==========================================================================
# Post-verification — the credential the replay tail used to carry
# ==========================================================================
#
# The verifier's finding, and it is a real one: ``remember_fact`` refuses to put
# "my password is hunter2" into ``owner_facts``, but the hosted lane still
# writes the raw TURN to ``messages`` (R22's surface, correctly untouched), and
# P2-A's own full-ledger replay then reads up to 120 recent turns back to the
# model at every session open. The refusal cites plaintext-read-to-the-hosted-
# model as the harm and then P2-A opened a second door to it.
#
# Closed at replay, with the SAME policy — one definition of "credential", not
# two.
@pytest.mark.parametrize("run", RUNS)
def test_a_credential_turn_is_never_replayed_into_a_session(
    tmp_path: Path, run: int
) -> None:
    """SEEDED RED. The credential turn must not reach the wire, and the ordinary
    turns around it must be unaffected."""

    store = tmp_path / f"probe_secret_{run}.sqlite3"
    seed = ConversationMemory(store)
    seed.add("user", "how was your day")
    seed.add("assistant", "warm and quiet")
    seed.add("user", "my wifi password is hunter2")
    seed.add("user", "anyway, remind me to buy milk")
    seed.connection.close()

    session = _Session(store)
    session.open()

    replayed = session.tail_items()
    assert replayed == [
        ("user", "how was your day"),
        ("assistant", "warm and quiet"),
        ("user", "anyway, remind me to buy milk"),
    ]
    assert "hunter2" not in json.dumps(replayed)
    assert session.lane.tail_items_redacted == 1
    assert session.lane.tail_items_injected == 3
    assert session.lane.snapshot()["tail_items_redacted"] == 1
    session.close()


def test_the_redaction_is_counted_and_noted_without_the_secret(tmp_path: Path) -> None:
    """A redaction that writes the secret into the event ring has MOVED it, not
    removed it."""

    store = tmp_path / "probe_secret_note.sqlite3"
    seed = ConversationMemory(store)
    seed.add("user", "my wifi password is hunter2")
    seed.connection.close()

    session = _Session(store)
    session.open()
    notes = [event for event in session.lane.events if "memory tail" in event]
    assert len(notes) == 1
    assert "credential" in notes[0]
    assert "hunter2" not in notes[0]
    assert "hunter2" not in json.dumps(session.lane.snapshot())
    session.close()


@pytest.mark.parametrize("run", RUNS)
def test_the_refusal_the_model_reads_never_contains_the_credential(
    tmp_path: Path, run: int
) -> None:
    """SEEDED RED. ``_fact_key`` derived ``wifi_password_hunter2`` and the broker
    echoed it back inside the refusal — the model reading the credential aloud
    in the course of being told it may not be stored."""

    store = tmp_path / f"probe_key_{run}.sqlite3"
    session = _Session(
        store,
        script=_tool_script(("call_a", {"fact": "their wifi password is hunter2"})),
    )
    session.open()
    _drive(session, 1)
    (refused,) = session.outputs()

    assert refused["status"] == "rejected"
    assert refused["stored"] is False
    assert refused["key"] == "password"
    assert "hunter2" not in json.dumps(refused), refused
    assert session.memory.owner_facts() == []
    session.close()
