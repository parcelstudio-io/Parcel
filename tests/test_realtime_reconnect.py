"""Card R4-lite, task_1 — Defect A: the lane must not go deaf after a reconnect.

WHAT THIS FILE PINS
-------------------
The live incident: after ``lane reconnected: stall`` (stalls: 1, reconnects: 1)
the owner's next typed turn was accepted — 202, ledgered, utterance sequence
advanced — and was never answered. No response, no tool call, broker counters
frozen. The session was "active" by every counter the panel could see and deaf
in fact.

Everything here is offline and deterministic: ``FakeRealtimeServer`` with a
fresh script per connection, a hand-advanced clock, and an injected ``sleep``
that records the backoff instead of waiting it. The rule the whole file exists
to state is one sentence:

    **The FIRST turn after a reconnect must be answered.**

and the rule that keeps the fix honest is the second sentence:

    **A fix that hides the stall is not a fix** — ``stalls`` and ``reconnects``
    keep counting, and the backoff stays bounded and jittered.

CARD R6, task_3 — THE ANSWERED TURN
-----------------------------------
R4-lite made the lane SURVIVE a provider stall. It did not make the owner's
SENTENCE survive one: a turn that was in flight when the session died was never
re-asked, so the panel showed a healthy session that had quietly eaten a
question (R4L live session 3, R5 live session 3 — no response, no refusal, no
billing). Two more sentences are pinned here, from the bottom of this file:

    **A reconnect repays what was owed** — once per reconnect, only what
    ``_responses_pending`` says was actually outstanding, and out loud in the
    ledger.

    **One tool turn, one spoken beat — but never silence about a failure.**
    The post-tool ``response.create`` is skipped only when the model already
    spoke in the response that carried the call, the call SUCCEEDED, and the
    result is a receipt the robot's own systems will report on later. Every
    refusal, deferral, drop and answer-shaped result still gets its sentence.
"""

from __future__ import annotations

import base64
import threading
from collections.abc import Callable

import pytest

from parcel_robot.memory import ConversationMemory
from parcel_robot.realtime.config import RealtimeConfig
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    function_call,
    handshake,
    happy_turn,
    pcm_tone,
    response_done,
    transcript_delta,
    transcript_done,
)
from parcel_robot.realtime.lane import (
    RESULT_BEAT_RULE,
    RealtimeLane,
    RealtimeLaneError,
)
from parcel_robot.realtime.transport import TransportClosed, transport_pair

#: The stall the watchdog is configured to notice, in seconds.
STALL_TIMEOUT_S = 4.0


def _b64(pcm: bytes) -> str:
    """Provider audio deltas arrive base64-encoded on the wire."""

    return base64.b64encode(pcm).decode("ascii")


class _Clock:
    """Monotonic time as a number the test advances by hand."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _FakeSink:
    """The two ``SpeakerSink`` behaviours the playback bridge depends on."""

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock
        self.chunks: list[bytes] = []
        self.begin_calls = 0
        self.interrupts = 0
        self.first_chunk_started_monotonic: float | None = None

    def begin_utterance(self) -> None:
        self.begin_calls += 1
        self.first_chunk_started_monotonic = None

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        del token
        self.chunks.append(chunk)
        if self.first_chunk_started_monotonic is None:
            self.first_chunk_started_monotonic = self._clock()

    def interrupt(self) -> None:
        self.interrupts += 1


class _Rig:
    """A lane plus a fresh scripted server per connection.

    The script is copied per connection, so a reconnect faces a server that has
    not consumed anything yet — exactly like a new provider session.
    """

    def __init__(
        self,
        script: list[Step],
        *,
        config: RealtimeConfig | None = None,
        reconnect_script: list[Step] | None = None,
        **lane_kwargs: object,
    ) -> None:
        self.clock = _Clock()
        self.script = script
        #: What every session AFTER the first one is scripted with. Card R6: a
        #: reconnect now sends a repay ``response.create`` of its own, so a test
        #: that wants to prove the OWNER's next turn was answered has to give
        #: the new session something to answer besides the repay. ``None`` keeps
        #: R4-lite's behaviour exactly — the same script for every connection.
        self.reconnect_script = reconnect_script
        self.servers: list[FakeRealtimeServer] = []
        self.transports: list[object] = []
        self.sink = _FakeSink(self.clock)
        self.sleeps: list[float] = []
        #: Called inside the backoff wait. The reconnect window, as a seam.
        self.on_backoff: Callable[[float], None] | None = None
        counter = {"n": 0}

        def _session_id() -> str:
            counter["n"] += 1
            return f"rt_session_{counter['n']}"

        self.lane = RealtimeLane(
            config=config
            or RealtimeConfig(enabled=True, stall_timeout_s=STALL_TIMEOUT_S, source="test"),
            instructions="be a good dog",
            transport_factory=self._factory,
            sink=self.sink,
            clock=self.clock,
            session_id_factory=_session_id,
            sleep=self._backoff,
            jitter=lambda: 1.0,
            **lane_kwargs,  # type: ignore[arg-type]
        )

    def _backoff(self, delay: float) -> None:
        """The injected sleep. Records the wait; never actually waits."""

        self.sleeps.append(delay)
        hook = self.on_backoff
        if hook is not None:
            hook(delay)

    def _factory(self):
        lane_end, server_end = transport_pair(clock=self.clock)
        self.transports.append(lane_end)
        script = self.script
        if self.servers and self.reconnect_script is not None:
            script = self.reconnect_script
        self.servers.append(
            FakeRealtimeServer(
                transport=server_end,
                script=list(script),
                clock=self.clock,
            )
        )
        return lane_end

    @property
    def orphans(self) -> list[int]:
        """Sockets left OPEN that the lane is no longer reading.

        The live incident's fingerprint. An orphan is worse than a closed
        socket: it is still billing, and it may be holding a turn whose answer
        will be delivered to nobody.
        """

        return [
            index
            for index, transport in enumerate(self.transports)
            if not transport.closed and transport is not self.lane.transport
        ]

    @property
    def server(self) -> FakeRealtimeServer:
        return self.servers[-1]

    # -- driving ---------------------------------------------------------
    def settle(self, rounds: int = 4) -> None:
        """Let both ends drain until nothing more moves."""

        for _ in range(rounds):
            self.server.pump()
            self.lane.pump()

    def open(self) -> None:
        self.lane.open_session(handshake_token="tok", mic_gesture=True)
        self.settle()

    def turn(self, text: str) -> None:
        self.lane.send_text(text)
        self.settle()


def _text_turn(*, reply: str, response_id: str, item_id: str) -> list[Step]:
    """One complete answered turn, triggered by the owner's typed line."""

    return happy_turn(
        response_id=response_id,
        item_id=item_id,
        reply=reply,
        trigger="response.create",
    )


def _deaf_after_stall_script(reply: str = "Still here.") -> list[Step]:
    """handshake → one answered turn → one turn the server never answers.

    A fresh copy of this script is what the reconnected session gets, so the
    third ``send_text`` faces a server whose FIRST scripted turn is waiting to
    be triggered. If the lane is healthy it is answered.
    """

    return (
        handshake()
        + _text_turn(reply=reply, response_id="resp_1", item_id="item_robot_1")
        + [Step("response.create", (), label="silent_stall_text")]
    )


def _answers_twice_script(
    first: str = "Answered on the new session.",
    second: str = "And again.",
) -> list[Step]:
    """A reconnected session that can answer TWO ``response.create`` frames.

    Card R6: the first one is the lane's repay of the turn the dead session
    swallowed; the second is the owner's next turn. A script with only one
    answerable step cannot tell those apart.
    """

    return (
        handshake("sess_fake_2")
        + _text_turn(reply=first, response_id="resp_repay", item_id="item_robot_repay")
        + _text_turn(reply=second, response_id="resp_next", item_id="item_robot_next")
        + [Step("response.create", (), label="silent_stall_text")]
    )


def _never_answers_script() -> list[Step]:
    """A reconnected session that accepts everything and answers nothing.

    The provider behaviour behind card R6: the socket is fine, the session
    exists, and no response ever comes back. Used to prove that a repay is
    watched like any other request and that repaying is bounded.
    """

    return handshake("sess_fake_2") + [
        Step("response.create", (), label="silent_forever_1"),
        Step("response.create", (), label="silent_forever_2"),
    ]


def _force_stall(rig: _Rig) -> str | None:
    """Advance past the watchdog's patience and take one tick."""

    rig.clock.advance(STALL_TIMEOUT_S + 1.0)
    return rig.lane.tick()


# --------------------------------------------------------------- the defect
def test_the_first_turn_after_a_stall_reconnect_is_answered() -> None:
    """Defect A, stated as one sentence.

    Turn 1 is answered. Turn 2 stalls and the watchdog reconnects. Turn 3 —
    the first turn of the NEW session — must be answered by the new session.
    On the shipped code it was not: the panel accepted it, the ledger recorded
    it, and nothing ever came back.

    Card R6 keeps this test honest rather than letting it drift: the reconnect
    now also REPAYS turn 2, and the repay would otherwise consume the new
    session's one answerable step and satisfy this assertion for a reason that
    has nothing to do with turn 3. ``reconnect_script`` gives the new session an
    answer for each — the repay's and the owner's — and the baseline is taken
    after the repay has landed.
    """

    rig = _Rig(_deaf_after_stall_script(), reconnect_script=_answers_twice_script())
    rig.open()

    rig.turn("hello")
    assert rig.lane.usage_rows, "turn 1 should have been answered before anything else"

    rig.turn("are you still there")
    assert _force_stall(rig) == "stall"
    assert rig.lane.stalls == 1
    assert rig.lane.reconnects == 1
    assert len(rig.servers) == 2, "the watchdog must have opened a second session"

    rig.settle()
    answered_before = len(rig.lane.usage_rows)
    rig.turn("hello again")

    assert len(rig.lane.usage_rows) > answered_before, (
        "the first turn after a reconnect was accepted and never answered: "
        f"servers={len(rig.servers)} "
        f"fired={rig.server.fired} "
        f"server_saw={rig.server.received_types()} "
        f"notes={rig.lane.events[-4:]}"
    )


def test_the_reconnected_session_actually_receives_the_turn() -> None:
    """The frames must reach the NEW socket, not the corpse of the old one."""

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.turn("hello")
    rig.turn("are you still there")
    assert _force_stall(rig) == "stall"
    rig.settle()

    rig.turn("hello again")

    saw = rig.server.received_types()
    assert "session.update" in saw, "the new session never got its instructions"
    assert "conversation.item.create" in saw, "the owner's line never reached the new session"
    assert "response.create" in saw, "nothing ever asked the new session to answer"


# ------------------------------------------------------- the fix must not lie
def test_the_fix_does_not_mask_the_stall() -> None:
    """Counters keep counting. A quiet lane is not the same as a healthy one."""

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.turn("hello")
    rig.turn("are you still there")
    assert _force_stall(rig) == "stall"
    rig.settle()
    rig.turn("hello again")

    snapshot = rig.lane.snapshot()
    assert snapshot["stalls"] == 1
    assert snapshot["reconnects"] == 1
    assert snapshot["active"] is True


def test_the_backoff_is_bounded_and_jittered_on_the_injected_clock() -> None:
    """A flapping provider must not become a hot loop, and must not be masked."""

    rig = _Rig(
        _deaf_after_stall_script(),
        config=RealtimeConfig(enabled=True, stall_timeout_s=STALL_TIMEOUT_S, source="test"),
    )
    rig.open()
    for _ in range(8):
        rig.lane.send_text("say something")
        assert _force_stall(rig) == "stall"
        rig.settle()

    assert rig.lane.stalls == 8
    assert rig.sleeps, "a failure reconnect must wait before retrying"
    assert rig.sleeps == rig.lane.backoff_waits
    assert all(wait <= 30.0 for wait in rig.sleeps), "backoff must stay capped"
    assert rig.sleeps == sorted(rig.sleeps), "the ladder must climb"


def test_a_healthy_reconnect_resets_the_ladder() -> None:
    """``session.created`` is the provider's own word that a session exists."""

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.turn("hello")
    rig.turn("are you still there")
    assert _force_stall(rig) == "stall"
    rig.settle()
    first_wait = rig.sleeps[-1]

    rig.turn("hello again")
    rig.lane.send_text("and again")
    assert _force_stall(rig) == "stall"
    rig.settle()

    assert rig.sleeps[-1] == pytest.approx(first_wait), (
        "a session that came back healthy must start the ladder from the bottom"
    )


# ------------------------------- card R4-lite: narrating what the robot did
def test_a_mission_fact_reaches_the_model_as_a_system_item() -> None:
    """Defect B.3. The model narrates a fact; it never decides one.

    A system conversation item plus a ``response.create`` — the same door a
    post-hoc action report takes — so the guardrails apply unchanged.
    """

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.settle()

    assert rig.lane.narrate_event("The robot arrived at the sidewalk.") is True

    sent = rig.transports[-1].sent
    items = [frame for frame in sent if frame.get("type") == "conversation.item.create"]
    assert items, "no conversation item went up"
    assert items[-1]["item"]["role"] == "system"
    assert "arrived at the sidewalk" in items[-1]["item"]["content"][0]["text"]
    assert sent[-1]["type"] == "response.create", "nothing asked the model to say it"
    assert rig.lane.snapshot()["narrations"] == 1


def test_narration_is_refused_while_the_model_has_the_mouth() -> None:
    """The floor gate. A fact is never worth talking over the robot's own voice.

    The script deliberately stops mid-response — audio started, no
    ``response.done`` — because that is the state the gate exists for.
    """

    mid_response = handshake() + [
        Step(
            "response.create",
            (
                {
                    "type": "response.output_audio.delta",
                    "response_id": "resp_mid",
                    "item_id": "item_mid",
                    "delta": _b64(pcm_tone(250)),
                },
            ),
            label="response_in_flight",
        )
    ]
    rig = _Rig(mid_response)
    rig.open()
    rig.turn("hello")

    assert rig.lane.playback_owned is True, "the model should still hold the mouth"
    assert rig.lane.narrate_event("The robot arrived.") is False
    assert rig.lane.snapshot()["narrations"] == 0
    assert rig.lane.snapshot()["narrations_skipped"] >= 1


def test_narration_is_refused_while_a_response_is_still_owed() -> None:
    """The owner asked something and has not been answered. Wait your turn."""

    silent = handshake() + [Step("response.create", (), label="no_answer_yet")]
    rig = _Rig(silent)
    rig.open()
    rig.turn("hello")

    assert rig.lane.playback_owned is False, "nothing is playing"
    assert rig.lane.narrate_event("The robot arrived.") is False, (
        "a response is still outstanding; narrating would talk over the answer"
    )


def test_narration_is_refused_without_a_session() -> None:
    rig = _Rig(_deaf_after_stall_script())
    assert rig.lane.narrate_event("The robot arrived.") is False

    rig.open()
    rig.settle()
    rig.lane.close()
    assert rig.lane.narrate_event("The robot arrived.") is False


def test_narration_refuses_empty_text_without_touching_the_session() -> None:
    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.settle()
    before = len(rig.transports[-1].sent)

    assert rig.lane.narrate_event("   ") is False
    assert len(rig.transports[-1].sent) == before


# ------------------------------------------------------- the root cause itself
def test_a_reconnect_never_orphans_a_socket() -> None:
    """The live incident's fingerprint, as a structural invariant.

    Whatever else happens, exactly one socket is open at a time and it is the
    one the lane is reading. A socket that is open, unread, and not
    ``lane.transport`` is a socket that may be holding the owner's turn.
    """

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    assert rig.orphans == []

    rig.turn("hello")
    rig.turn("are you still there")
    assert _force_stall(rig) == "stall"
    rig.settle()

    assert rig.orphans == [], "the reconnect left a socket open that nobody reads"
    assert rig.lane.transport is rig.transports[-1]


def test_opening_over_a_live_session_closes_the_socket_it_replaces() -> None:
    """``_connect`` owns exactly one socket, whatever it is replacing.

    The reconnect path closes the old transport itself, so it hides this hole.
    Opening straight over a HEALTHY session does not — and that is the path the
    panel took during the incident. A transport that is replaced and not closed
    is an orphan: still open, still billing, still holding whatever was sent
    into it, and read by nobody ever again.
    """

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    first = rig.lane.transport
    assert first.closed is False

    rig.lane.open_session(handshake_token="tok", mic_gesture=True)

    assert rig.lane.transport is not first, "a second session should have a second socket"
    assert first.closed is True, "the socket that was replaced was left open and unread"
    assert rig.orphans == []


def test_a_turn_that_arrives_during_the_backoff_is_not_lost() -> None:
    """Defect A's root cause, pinned across the two threads that caused it.

    A real thread is unavoidable here. The bug is a cross-thread read of
    ``lane.active``: the driver thread closes the socket and blocks in the
    reconnect backoff, and for that whole window ``active`` is False. The
    panel's HTTP thread reads that flag, concludes there is no session, opens
    one of its OWN, and sends the turn into it. The driver then completes its
    reconnect, replaces the transport, and the socket holding the turn is
    orphaned — open, unread, answered to nobody.

    The clock stays injected; the only real time here is a bounded observation
    window used to assert that the panel thread is *blocked* rather than racing
    ahead. Nothing in the assertions depends on how long anything takes.
    """

    rig = _Rig(_deaf_after_stall_script(), reconnect_script=_answers_twice_script())
    panel_at_gate = threading.Event()
    panel_done = threading.Event()
    escaped: list[str] = []
    panel_error: list[BaseException] = []

    def _panel_submit() -> None:
        """Exactly what ``runtime.submit_realtime_text`` does, on its own thread."""

        panel_at_gate.set()
        try:
            rig.lane.ensure_session(handshake_token="tok", mic_gesture=True)
            rig.lane.send_text("walk over to the sidewalk")
        except BaseException as error:  # noqa: BLE001 - reported, not swallowed
            panel_error.append(error)
        finally:
            panel_done.set()

    panel = threading.Thread(target=_panel_submit, name="panel", daemon=True)

    def _on_backoff(delay: float) -> None:
        """The backoff window. The owner types into the panel right here."""

        del delay
        if panel.is_alive() or panel_done.is_set():
            return
        panel.start()
        panel_at_gate.wait(5.0)
        # If the lane is held, the panel CANNOT get through this window. Under
        # the defect it sailed through and opened a competing session.
        if panel_done.wait(0.25):
            escaped.append("the panel opened a session while a reconnect was in flight")

    rig.on_backoff = _on_backoff

    rig.open()
    rig.turn("hello")
    rig.turn("are you still there")
    assert _force_stall(rig) == "stall"

    panel.join(timeout=5.0)
    assert not panel.is_alive(), "the panel thread never finished"
    assert not panel_error, f"the panel turn failed: {panel_error}"
    assert not escaped, escaped

    rig.settle()
    assert rig.orphans == [], "a socket was orphaned with the owner's turn inside it"
    # THE count that catches the race at its source. Two sockets is the whole
    # story: the one the owner opened, and the one the watchdog replaced it
    # with. A third means the panel decided, from another thread, that a lane
    # in the middle of reconnecting had no session — which is the bug.
    assert len(rig.transports) == 2, (
        "a competing session was opened during the reconnect: "
        f"{len(rig.transports)} sockets were built, expected 2"
    )
    assert rig.lane.stalls == 1, "the stall must still be counted, not masked"
    assert rig.lane.reconnects == 1

    # The pin: the turn the owner typed during the reconnect was answered — and
    # named, so the lane's own repay (card R6, which lands on the same new
    # socket a beat earlier) cannot be mistaken for the panel's answer.
    answered = [row["response_id"] for row in rig.lane.usage_rows]
    assert "resp_next" in answered, (
        f"the turn submitted during the reconnect was never answered: {answered}"
    )
    assert rig.lane.text_turns == 3


def test_a_dropped_owner_turn_refuses_instead_of_acknowledging() -> None:
    """No phantom 202s. A turn whose frames were dropped is a failed turn.

    The socket that dies BETWEEN the liveness check and the send is the live
    case: ``WebSocketTransport`` learns it is down on its reader thread, so
    ``closed`` can still read False at the top of ``send_text`` and
    ``TransportClosed`` can still come out of the very next ``send``. The lane
    answered that with a note, then ran the ingress (ledger row written,
    utterance sequence advanced) and returned success. The panel said 202 for a
    turn that never left the process.
    """

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.settle()

    class _DiesOnSend:
        """Reports healthy, refuses every send. The race, made deterministic."""

        closed = False

        def __init__(self, real):
            self._real = real
            self.attempts = 0

        def send(self, event):
            self.attempts += 1
            raise TransportClosed("the peer hung up between the check and the send")

        def receive(self):
            return self._real.receive()

        def close(self):
            self._real.close()

    lying = _DiesOnSend(rig.lane.transport)
    rig.lane.transport = lying
    ingressed: list[str] = []
    rig.lane._ingress = lambda text, **kwargs: ingressed.append(text)

    with pytest.raises(RealtimeLaneError, match="NOT delivered"):
        rig.lane.send_text("walk over to the sidewalk")

    assert lying.attempts == 1, "the lane should stop at the first refused frame"
    assert ingressed == [], "a turn that was never delivered must not run the ingress"
    assert rig.lane.snapshot()["dropped_sends"] == 1, "the drop must be visible, not just noted"


def test_the_watchdog_watches_the_response_that_follows_a_tool_answer() -> None:
    """Every ``response.create`` arms the watchdog, not just ``send_text``'s.

    A provider that answers the tool call and then goes silent used to be
    invisible: the tool turn's ``response.done`` cleared ``_expecting_server``
    and the lane's own follow-up ``response.create`` never re-armed it, so the
    watchdog had nothing to notice and the lane waited forever.
    """

    calls: list[str] = []

    class _Broker:
        def session_events(self):
            return ()

        def handle(self, *, name, call_id, arguments):
            calls.append(name)
            return '{"status": "ok", "detail": "mission accepted: sidewalk"}'

    script = handshake() + [
        Step(
            "response.create",
            (
                {
                    "type": "response.function_call_arguments.done",
                    "call_id": "call_1",
                    "name": "navigate_to",
                    "arguments": '{"place": "the sidewalk"}',
                },
                {
                    "type": "response.done",
                    "response": {"id": "resp_tool", "status": "completed", "usage": {}},
                },
            ),
            label="tool_call_then_silence",
        )
    ]
    rig = _Rig(script, tool_handler=_Broker())
    rig.open()
    rig.turn("walk over to the sidewalk")

    assert calls == ["navigate_to"], "the broker should have answered the call"
    assert _force_stall(rig) == "stall", (
        "the lane asked for a response after the tool answer and never got one; "
        "the watchdog must notice that silence"
    )
    assert rig.lane.stalls == 1


def test_an_armed_lane_that_lost_its_transport_recovers_itself() -> None:
    """A deaf lane must not need a panel POST to come back.

    ``tick`` used to return None whenever ``active`` was False — which is
    exactly the state a lane is in when its socket has died and nothing is
    pumping it. The only thing in the product that reconnects refused to run
    precisely when it was needed.
    """

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.lane.transport.close()
    assert rig.lane.active is False

    assert rig.lane.tick() == "disconnect"
    assert rig.lane.reconnects == 1
    assert rig.lane.disconnects == 1
    assert rig.lane.active is True

    rig.settle()
    rig.turn("hello again")
    assert rig.lane.usage_rows, "the recovered session must answer"


def test_an_unarmed_lane_is_idle_and_is_left_alone() -> None:
    """The other half of the same rule: never reconnect what nobody armed."""

    rig = _Rig(_deaf_after_stall_script())
    assert rig.lane.tick() is None
    assert rig.lane.reconnects == 0
    assert len(rig.servers) == 0


def test_closing_during_a_reconnect_does_not_resurrect_the_socket() -> None:
    """A hosted socket opened after the owner hung up would keep billing."""

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.turn("hello")
    rig.turn("are you still there")

    rig.on_backoff = lambda delay: rig.lane.close()
    assert _force_stall(rig) == "stall"

    assert rig.lane.transport is None
    assert rig.orphans == []
    assert len(rig.servers) == 1, "no socket may be opened after close()"
    assert any("abandoned" in note for note in rig.lane.events)
    assert rig.lane.tick() is None, "a closed lane is not a lane to recover"


def test_the_snapshot_shows_recovery_and_drops_rather_than_hiding_them() -> None:
    """Whatever the lane survives, the panel can see that it happened."""

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    snapshot = rig.lane.snapshot()
    assert snapshot["recovering"] is False
    assert snapshot["dropped_sends"] == 0

    seen: list[bool] = []

    rig.on_backoff = lambda delay: seen.append(bool(rig.lane.snapshot()["recovering"]))
    rig.lane.send_text("are you still there")
    assert _force_stall(rig) == "stall"

    assert seen == [True], "a lane in the middle of a reconnect must say so"
    assert rig.lane.snapshot()["recovering"] is False


# ==================================================================== card R6
# Defect 1 — a reconnect must repay the turn it inherited.
def _system_rows(memory: ConversationMemory) -> list[str]:
    return [str(row["content"]) for row in memory.realtime_turns() if row["speaker"] == "system"]


def _response_creates(rig: _Rig, *, index: int = -1) -> list[dict]:
    """Every ``response.create`` that went up a given socket, in order."""

    return [
        dict(frame)
        for frame in rig.transports[index].sent
        if frame.get("type") == "response.create"
    ]


def test_a_turn_the_dead_session_never_answered_is_repaid_on_the_new_one() -> None:
    """R6 Defect 1, stated as one sentence, with zero owner action.

    The live shape, twice observed: the owner asks something, the provider goes
    quiet, the watchdog reconnects — and the question is simply gone. The new
    session holds the sentence (the ledger wrote it, ``_inject_tail`` replays
    it) and nobody was asking it to answer.
    """

    memory = ConversationMemory(":memory:")
    rig = _Rig(
        _deaf_after_stall_script(),
        reconnect_script=_answers_twice_script(),
        ledger=memory,
    )
    rig.open()
    rig.turn("walk over to the sidewalk")  # answered by the first happy_turn
    rig.turn("are you still there")  # the provider says nothing at all

    assert _force_stall(rig) == "stall"
    rig.settle()

    # Nothing else happened: no second turn was typed, nothing was clicked.
    assert rig.lane.text_turns == 2
    assert rig.lane.turn_repays == 1, "the reconnect owed an answer and did not ask for one"
    creates = _response_creates(rig)
    assert len(creates) == 1, f"exactly one repay belongs on the new socket: {creates}"
    answered = [row["response_id"] for row in rig.lane.usage_rows]
    assert "resp_repay" in answered, (
        f"the inherited turn was never answered on the new session: {answered}"
    )


def test_the_repay_is_visible_in_the_snapshot_and_explained_in_the_ledger() -> None:
    """An answer that arrives after a reconnect must be explainable.

    Without the system row the transcript reads as a reply that came out of
    nowhere, minutes after the question, with a session boundary in between.
    """

    memory = ConversationMemory(":memory:")
    rig = _Rig(_deaf_after_stall_script(), ledger=memory, reconnect_script=_answers_twice_script())
    rig.open()
    rig.turn("hello")
    rig.turn("are you still there")
    assert _force_stall(rig) == "stall"
    rig.settle()

    snapshot = rig.lane.snapshot()
    assert snapshot["turn_repays"] == 1
    assert snapshot["turn_repays_abandoned"] == 0
    assert snapshot["stalls"] == 1, "the repay must not mask the stall that caused it"
    rows = _system_rows(memory)
    assert any("[turn repaid]" in row for row in rows), rows
    assert any("stall" in row for row in rows if "[turn repaid]" in row), rows


def test_one_repay_per_reconnect_even_when_two_responses_were_owed() -> None:
    """A tool turn has TWO responses outstanding. It is still ONE question.

    Repaying per owed response would buy the owner a duplicate answer and a
    duplicate bill for one sentence.
    """

    class _Broker:
        def session_events(self):
            return ()

        def handle(self, *, name, call_id, arguments):
            return '{"status": "ok", "tool": "navigate_to", "detail": "mission accepted"}'

    script = handshake() + [
        Step(
            "response.create",
            (function_call("call_1", "navigate_to", '{"place": "the sidewalk"}'),),
            label="tool_call_then_silence",
        )
    ]
    rig = _Rig(script, tool_handler=_Broker(), reconnect_script=_answers_twice_script())
    rig.open()
    rig.turn("go to the sidewalk")

    # The owner's response.create and the lane's post-tool one, both unanswered.
    assert rig.lane._responses_pending == 2
    assert _force_stall(rig) == "stall"
    rig.settle()

    assert rig.lane.turn_repays == 1
    assert len(_response_creates(rig)) == 1, "one repay, whatever was owed"


def test_a_response_that_actually_completed_is_never_repaid() -> None:
    """The no-double-answer rule, from the side that matters.

    Turn answered, THEN the socket dies. There is nothing outstanding, so a
    repay here would make the model answer a question it has already answered.
    """

    memory = ConversationMemory(":memory:")
    rig = _Rig(_deaf_after_stall_script(), ledger=memory)
    rig.open()
    rig.turn("hello")
    assert rig.lane.usage_rows, "turn 1 must be answered before this proves anything"

    rig.lane.transport.close()
    assert rig.lane.tick() == "disconnect"
    rig.settle()

    assert rig.lane.turn_repays == 0, "nothing was owed; the answer had already arrived"
    assert _response_creates(rig) == []
    assert not any("[turn repaid]" in row for row in _system_rows(memory))


def test_a_rollover_repays_the_turn_it_interrupted() -> None:
    """The 60-minute cap takes the same path, so it inherits the same duty."""

    rig = _Rig(
        _deaf_after_stall_script(),
        config=RealtimeConfig(
            enabled=True, stall_timeout_s=STALL_TIMEOUT_S, session_max_s=60.0, source="test"
        ),
        reconnect_script=_answers_twice_script(),
    )
    rig.open()
    rig.lane.send_text("are you still there")  # asked, never answered
    rig.clock.advance(61.0)

    assert rig.lane.tick() == "rollover"
    rig.settle()

    assert rig.lane.rollovers == 1
    assert rig.lane.turn_repays == 1, "a rollover mid-turn swallows the turn just as a stall does"
    assert "resp_repay" in [row["response_id"] for row in rig.lane.usage_rows]


def test_the_repaid_turn_is_watched_like_any_other() -> None:
    """A repay that is not watched is a second way to lose the same sentence."""

    rig = _Rig(_deaf_after_stall_script(), reconnect_script=_never_answers_script())
    rig.open()
    rig.lane.send_text("are you still there")
    assert _force_stall(rig) == "stall"
    rig.settle()

    assert rig.lane.turn_repays == 1
    assert rig.lane._expecting_server is True, "a repay nobody answers must still be watched"
    # The new session ignored the repay too. The watchdog must notice THAT.
    assert _force_stall(rig) == "stall"
    assert rig.lane.stalls == 2


def test_a_turn_that_kills_every_session_is_abandoned_out_loud_not_re_asked_forever() -> None:
    """The bound on "the next watchdog cycle's problem".

    A repay that stalls is legitimately re-tried — but a turn the provider dies
    on every single time must not be re-asked until the budget runs out. The
    give-up is a counter and a ledger row, never a silent stop.
    """

    memory = ConversationMemory(":memory:")
    rig = _Rig(
        _deaf_after_stall_script(),
        reconnect_script=_never_answers_script(),
        ledger=memory,
    )
    rig.open()
    rig.lane.send_text("the turn nobody ever answers")

    reasons = []
    for _ in range(8):
        reason = _force_stall(rig)
        rig.settle()
        if reason is None:
            break
        reasons.append(reason)

    assert reasons == ["stall"] * 4, f"the cycle must end, not run forever: {reasons}"
    assert rig.lane.stalls == 4, "the stalls keep counting whatever the repay does"
    assert rig.lane.turn_repays == 3, (
        f"repays must stop at the limit, not run per stall: {rig.lane.turn_repays}"
    )
    assert rig.lane.turn_repays_abandoned == 1
    rows = _system_rows(memory)
    assert any("[turn abandoned]" in row for row in rows), rows


def test_a_new_owner_turn_gets_its_own_repay_budget() -> None:
    """The repay limit bounds ONE turn, not the session.

    A lane that spent its budget on a turn the provider choked on must still
    repay the NEXT question — otherwise one bad sentence quietly disarms the
    whole mechanism for the rest of the conversation.
    """

    rig = _Rig(_deaf_after_stall_script(), reconnect_script=_never_answers_script())
    rig.open()
    rig.lane.send_text("the turn nobody ever answers")
    for _ in range(4):
        _force_stall(rig)
        rig.settle()
    assert rig.lane.turn_repays == 3
    assert rig.lane.turn_repays_abandoned == 1

    rig.lane.send_text("a completely different question")
    assert _force_stall(rig) == "stall"
    rig.settle()

    assert rig.lane.turn_repays == 4, "the new turn inherited the old turn's spent budget"


def test_a_repay_is_never_sent_after_the_owner_hung_up() -> None:
    """``close()`` during the backoff abandons the reconnect — repay included."""

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.lane.send_text("are you still there")
    rig.on_backoff = lambda delay: rig.lane.close()

    assert _force_stall(rig) == "stall"

    assert rig.lane.turn_repays == 0
    assert len(rig.servers) == 1, "no socket may be opened after close()"


# --------------------------------------------------------------------------
# Defect 2 — one beat per tool turn, without lying by silence.
ANNOUNCEMENT = "Okay, let's head over to the sidewalk."


class _ScriptedBroker:
    """A broker seam that answers with whatever JSON the test names."""

    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[str] = []

    def session_events(self):
        return ()

    def handle(self, *, name, call_id, arguments):
        self.calls.append(name)
        return self.output


def _tool_turn(
    *,
    announcement: str | None = ANNOUNCEMENT,
    tool: str = "navigate_to",
    arguments: str = '{"place": "the sidewalk"}',
    response_id: str = "resp_tool",
) -> list[Step]:
    """One provider response that speaks (or does not) and calls a tool.

    This is the live shape R5 recorded: the announcement is *co-emitted* with
    the ``function_call`` inside a single response, which is exactly why no SI
    wording can remove it and why the lane has to decide about the second beat.
    """

    frames: list[dict] = []
    if announcement is not None:
        frames.append(transcript_delta(response_id, "item_say", announcement))
        frames.append(transcript_done(response_id, "item_say", announcement))
    frames.append(function_call("call_1", tool, arguments))
    frames.append(response_done(response_id))
    return handshake() + [Step("response.create", tuple(frames), label="announced_tool_call")]


def _beat_creates(rig: _Rig) -> list[dict]:
    """``response.create`` frames sent AFTER the owner's own (i.e. the beats)."""

    return _response_creates(rig)[1:]


def test_an_announced_navigation_turn_gets_exactly_one_spoken_beat() -> None:
    """R6 Defect 2, the owner's 20:45 complaint, as a frame count.

    Under the shipped code this turn produced two: the model's announcement,
    then a second response the lane asked for unconditionally. The announcement
    is not suppressible on ``gpt-realtime-2.1-mini`` (R5 proved it live under
    three wordings), so the second one is the beat that goes.
    """

    broker = _ScriptedBroker('{"status": "ok", "tool": "navigate_to", "detail": "mission accepted"}')
    rig = _Rig(_tool_turn(), tool_handler=broker)
    rig.open()
    rig.turn("go to the sidewalk")

    assert broker.calls == ["navigate_to"], "the call must still be answered"
    assert _beat_creates(rig) == [], (
        "the model had already announced this turn; the lane asked for a second beat anyway"
    )
    assert rig.lane.snapshot()["tool_beats_suppressed"] == 1
    assert rig.lane.snapshot()["tool_beats_requested"] == 0


def test_the_suppressed_beat_leaves_the_pending_ledger_exactly_as_sent() -> None:
    """The R4-lite watchdog reads ``_responses_pending``. It must stay true.

    A beat that was not sent must not be counted as outstanding — a lane that
    waits for a response it never asked for reconnects a perfectly healthy
    session every ``stall_timeout_s``, forever.
    """

    broker = _ScriptedBroker('{"status": "ok", "tool": "navigate_to", "detail": "mission accepted"}')
    rig = _Rig(_tool_turn(), tool_handler=broker)
    rig.open()
    rig.turn("go to the sidewalk")

    assert rig.lane._responses_pending == 0
    assert rig.lane._expecting_server is False
    rig.clock.advance(STALL_TIMEOUT_S + 1.0)
    assert rig.lane.tick() is None, "nothing was owed, so nothing may be reconnected"
    assert rig.lane.stalls == 0
    assert rig.lane.reconnects == 0


def test_a_tool_call_the_model_made_silently_still_gets_its_beat() -> None:
    """No announcement means no beat has happened yet. Silence would be a lie."""

    broker = _ScriptedBroker('{"status": "ok", "tool": "navigate_to", "detail": "mission accepted"}')
    rig = _Rig(_tool_turn(announcement=None), tool_handler=broker)
    rig.open()
    rig.turn("go to the sidewalk")

    assert len(_beat_creates(rig)) == 1, (
        "the model said nothing at all this turn; suppressing the beat is silence"
    )
    assert rig.lane.snapshot()["tool_beats_requested"] == 1
    assert rig.lane.snapshot()["tool_beats_suppressed"] == 0


@pytest.mark.parametrize(
    ("status", "detail"),
    [
        ("deferred", "Deferred paw_wave while navigation is active"),
        ("dropped", "the arm is cooling down"),
        ("rejected", "motion is disabled by emergency stop"),
    ],
)
def test_a_call_that_did_not_succeed_is_always_narrated(status: str, detail: str) -> None:
    """THE over-correction guard, and the reason this beat exists at all.

    The model has just told the owner it is doing something. If the robot then
    refused, deferred or dropped it, the turn's only spoken content is a
    promise that is now false. Going quiet here is the worst outcome available
    to this card — worse than the two beats it removes.
    """

    broker = _ScriptedBroker(f'{{"status": "{status}", "tool": "play_gesture", "detail": "{detail}"}}')
    rig = _Rig(_tool_turn(tool="play_gesture", arguments='{"name": "paw_wave"}'), tool_handler=broker)
    rig.open()
    rig.turn("wave at me please")

    assert len(_beat_creates(rig)) == 1, f"a {status} call went unnarrated"
    assert rig.lane.snapshot()["tool_beats_suppressed"] == 0
    assert any(f"status={status}" in note for note in rig.lane.events), rig.lane.events[-3:]


@pytest.mark.parametrize("tool", ["get_status", "recall_memory"])
def test_an_answer_shaped_tool_result_is_never_swallowed(tool: str) -> None:
    """``status: ok`` is not the same as "the owner has heard the answer".

    ``get_status`` and ``recall_memory`` return ok and carry the ANSWER; there
    is no mission log, no terminal and no ``narrate_event`` coming later to say
    it instead. Suppressing this beat leaves "what do you remember about the
    willow?" answered by "let me check" and nothing else.
    """

    broker = _ScriptedBroker(f'{{"status": "ok", "tool": "{tool}", "detail": "the willow, in June"}}')
    rig = _Rig(
        _tool_turn(tool=tool, arguments='{"query": "the willow"}'),
        tool_handler=broker,
    )
    rig.open()
    rig.turn("what do you remember about the willow")

    assert len(_beat_creates(rig)) == 1, f"{tool}'s answer was never spoken"
    assert rig.lane.snapshot()["tool_beats_suppressed"] == 0


def test_a_tool_answer_the_lane_cannot_read_gets_its_beat() -> None:
    """Fail toward speech. An unparseable result proves nothing about success."""

    broker = _ScriptedBroker("mission accepted, probably")
    rig = _Rig(_tool_turn(), tool_handler=broker)
    rig.open()
    rig.turn("go to the sidewalk")

    assert len(_beat_creates(rig)) == 1
    assert any("not JSON" in note for note in rig.lane.events), rig.lane.events[-3:]


def test_a_broker_that_raises_is_narrated_rather_than_hidden() -> None:
    """The lane's own rejected-output path is a failure like any other."""

    class _Exploding:
        def session_events(self):
            return ()

        def handle(self, *, name, call_id, arguments):
            raise RuntimeError("broker exploded")

    rig = _Rig(_tool_turn(), tool_handler=_Exploding())
    rig.open()
    rig.turn("go to the sidewalk")

    assert len(_beat_creates(rig)) == 1, "a broker failure must not be answered with silence"
    assert rig.lane.active, "one bad tool call must not take down the session"


def test_the_beat_carries_the_whole_prompt_not_just_the_result_rule() -> None:
    """``response.instructions`` REPLACES the session prompt for that response.

    Sending the result-only rule on its own would strip the persona and every
    guardrail from the single beat that reports what the robot actually did —
    the beat where "never claim to have arrived" matters most.
    """

    broker = _ScriptedBroker('{"status": "deferred", "tool": "play_gesture", "detail": "later"}')
    rig = _Rig(_tool_turn(tool="play_gesture"), tool_handler=broker)
    rig.open()
    rig.turn("wave at me please")

    beats = _beat_creates(rig)
    assert len(beats) == 1
    instructions = beats[0]["response"]["instructions"]
    assert instructions.startswith(rig.lane.instructions), (
        "the beat dropped the session instructions: persona and guardrails are gone"
    )
    assert RESULT_BEAT_RULE in instructions


def test_a_lane_told_not_to_use_per_response_instructions_still_asks_for_the_beat() -> None:
    """The wire-verification escape hatch, pinned.

    If a provider ever refuses ``response.instructions``, the fix is to stop
    sending them — never to stop asking for the beat.
    """

    broker = _ScriptedBroker('{"status": "rejected", "tool": "set_pose", "detail": "e-stop"}')
    rig = _Rig(_tool_turn(tool="set_pose"), tool_handler=broker, result_beat_instruction=None)
    rig.open()
    rig.turn("sit")

    beats = _beat_creates(rig)
    assert len(beats) == 1
    assert beats[0]["response"] == {}, "no instructions were asked for; none may be sent"


def test_speech_in_one_response_does_not_pay_for_a_call_in_the_next() -> None:
    """The beat is per RESPONSE, not per session.

    The model announces in response 1 and calls the tool silently in response
    2. Response 2 has had no spoken content at all, so it owes the owner one.
    """

    broker = _ScriptedBroker('{"status": "ok", "tool": "navigate_to", "detail": "mission accepted"}')
    script = (
        handshake()
        + [
            Step(
                "response.create",
                (
                    transcript_delta("resp_talk", "item_say", "Sure, one moment."),
                    transcript_done("resp_talk", "item_say", "Sure, one moment."),
                    response_done("resp_talk"),
                ),
                label="just_talking",
            ),
            Step(
                "response.create",
                (
                    function_call("call_1", "navigate_to", '{"place": "the sidewalk"}'),
                    response_done("resp_tool"),
                ),
                label="silent_tool_call",
            ),
        ]
    )
    rig = _Rig(script, tool_handler=broker)
    rig.open()
    rig.turn("hello")
    rig.turn("go to the sidewalk")

    creates = _response_creates(rig)
    # Two owner turns, and exactly one beat for the silent call.
    assert len(creates) == 3, [frame["response"] for frame in creates]
    assert rig.lane.snapshot()["tool_beats_requested"] == 1
    assert rig.lane.snapshot()["tool_beats_suppressed"] == 0


def test_a_beat_whose_frame_was_dropped_is_not_counted_as_a_beat() -> None:
    """Counters follow what was SENT. The watchdog reads the same number.

    ``_responses_pending`` has always moved only after the transport accepted
    the frame; ``tool_beats_requested`` and ``turn_repays`` have to keep that
    property or the snapshot and the watchdog stop agreeing.
    """

    broker = _ScriptedBroker('{"status": "rejected", "tool": "navigate_to", "detail": "no"}')
    rig = _Rig(_tool_turn(), tool_handler=broker)
    rig.open()

    class _DiesOnSend:
        closed = False

        def __init__(self, real):
            self._real = real

        def send(self, event):
            raise TransportClosed("the peer hung up between the check and the send")

        def receive(self):
            return self._real.receive()

        def close(self):
            self._real.close()

    rig.lane.send_text("go to the sidewalk")
    rig.server.pump()
    rig.lane.transport = _DiesOnSend(rig.lane.transport)
    # The whole tool turn arrives at once: the announcement, the call, and the
    # response.done that closes the owner's response. Every answering frame the
    # lane tries to send is refused by the socket.
    rig.lane.pump()

    assert rig.lane.snapshot()["tool_beats_requested"] == 0, "a dropped beat is not a beat"
    assert rig.lane.snapshot()["dropped_sends"] >= 1, "the drop must be counted, not swallowed"
    assert rig.lane._responses_pending == 0, (
        "a frame that never left the process must not be waited for"
    )
    assert rig.lane._expecting_server is False, (
        "the watchdog would reconnect a healthy session over a beat that was never asked for"
    )


# --------------------------------------------------------------------------
# The phantom stall — found live, card R6 session 1.
def test_a_turn_typed_after_a_quiet_gap_is_not_instantly_a_stall() -> None:
    """The watchdog measures silence since we ASKED, not since it last spoke.

    Live evidence (R6 session 1, ``gpt-realtime-2.1-mini``): the previous
    response finished at t=8.4 s, the owner typed at t=18.4 s, and the lane
    declared a stall and hung up a perfectly healthy socket about two seconds
    later — because ``_last_event_at`` was still 8.4 s and ``stall_timeout_s``
    is 8. Every conversation with a pause in it hit this, which makes it the
    most likely cause of the stall counts R4L and R5 reported, and of the turns
    that vanished with them.
    """

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.turn("hello")
    assert rig.lane.usage_rows, "turn 1 must be answered before this proves anything"

    rig.clock.advance(600.0)  # the owner goes away and comes back
    rig.lane.send_text("are you still there")

    assert rig.lane.tick() is None, (
        "the provider has had no time at all to answer; this is not a stall"
    )
    assert rig.lane.stalls == 0
    assert rig.lane.reconnects == 0

    # And the stall this watchdog exists for is still caught.
    rig.clock.advance(STALL_TIMEOUT_S + 1.0)
    assert rig.lane.tick() == "stall"
    assert rig.lane.stalls == 1


def test_owner_audio_also_starts_the_patience_clock() -> None:
    """The same rule for the voice path: the wait begins when we ask.

    The idle window is named explicitly (card R16) so this test keeps measuring
    the ONE clock it is about. A ten-minute gap with a live microphone and no
    speech now has a second meaning — the lane hangs up, see
    ``test_realtime_idle_hangup.py`` — and leaving that to the default would make
    this test's failure ambiguous between two unrelated timers.
    """

    rig = _Rig(
        _deaf_after_stall_script(),
        config=RealtimeConfig(
            enabled=True,
            stall_timeout_s=STALL_TIMEOUT_S,
            idle_close_after_s=3_600.0,
            source="test",
        ),
    )
    rig.open()
    rig.clock.advance(600.0)
    rig.lane.send_audio(b"\x00\x01" * 240)

    assert rig.lane.tick() is None, "the owner has only just spoken"
    rig.clock.advance(STALL_TIMEOUT_S + 1.0)
    assert rig.lane.tick() == "stall"


# --------------------------------------------------------------------------
# Card R8, work item 2 — a refused item must be VISIBLE.
#
# For seven cards the lane appended every provider refusal to a list nothing
# rendered and wrote a note nothing read. ``narrate_event`` returned True and
# counted a narration the provider had thrown away; the memory tail counted
# items that never reached the conversation. From ``/api/state`` a session whose
# every assistant item was being refused looked exactly like a healthy one.
#
# Attribution needed no protocol surgery: the item goes up carrying an
# ``event_id`` and the provider echoes it inside the error (verified live —
# six refusals, six correct echoes). So a refusal names the thing it cost.
# --------------------------------------------------------------------------
REFUSED_TEXT_TYPE = "Invalid value: 'text'. Value must be 'input_text'."


def _refusal_for(event_id: str, message: str = REFUSED_TEXT_TYPE) -> dict:
    """An ``error`` frame shaped exactly as the provider sends one.

    Built here rather than extended onto ``fake_server.error_frame`` because
    ``fake_server`` is frozen for this card except for additive script steps.
    The two ``event_id`` fields are the point: the top-level one identifies the
    ERROR, the nested one identifies OUR frame, and only the nested one is an
    attribution.
    """

    return {
        "type": "error",
        "event_id": "event_the_error_itself",
        "error": {
            "type": "invalid_request_error",
            "code": "invalid_value",
            "message": message,
            "param": "item.content[0].type",
            "event_id": event_id,
        },
    }


def _last_item_event_id(rig: _Rig, *, index: int = -1) -> str:
    items = [
        frame
        for frame in rig.transports[index].sent
        if frame.get("type") == "conversation.item.create" and "event_id" in frame
    ]
    assert items, "no tagged conversation item went up"
    return str(items[-1]["event_id"])


def test_a_refused_narration_is_counted_and_named_rather_than_silently_dropped() -> None:
    """R6's live finding, as a pin that cannot come back quietly.

    ``narrations`` says a fact left this process. It has never said the provider
    kept it, and for the whole of R1-R7 the provider kept none of them. The two
    numbers side by side are what "the narration was heard" looks like from
    ``/api/state``.
    """

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.settle()
    assert rig.lane.narrate_event("The robot arrived at the sidewalk.") is True
    assert rig.lane.narrations == 1

    # The provider refuses the item the narration rode in on.
    rig.server.transport.send(_refusal_for(_last_item_event_id(rig)))
    rig.lane.pump()

    snapshot = rig.lane.snapshot()
    assert snapshot["narrations"] == 1, "the send still happened; that count is honest"
    assert snapshot["narrations_refused"] == 1, (
        "a narration the provider threw away must be a NUMBER, not a wire trace"
    )
    assert snapshot["items_refused"] == 1
    recent = snapshot["recent_server_errors"]
    assert recent and recent[-1]["item"]["purpose"] == "narration"
    assert "arrived at the sidewalk" in recent[-1]["item"]["text"], (
        "the refusal must name the fact that was lost, not just that one was"
    )


def test_the_snapshot_carries_the_server_error_count_and_the_most_recent_few() -> None:
    """Shaped like ``dropped_sends``: a count you can watch, plus enough detail.

    The window is bounded on purpose — ``/api/state`` is polled, and a session
    that refuses everything must not turn it into a log file.
    """

    rig = _Rig(_deaf_after_stall_script(), server_error_window=2)
    rig.open()
    rig.settle()
    for index in range(4):
        rig.server.transport.send(_refusal_for(f"never_sent_{index}", message=f"boom {index}"))
    rig.lane.pump()

    snapshot = rig.lane.snapshot()
    assert snapshot["server_errors"] == 4, "the COUNT is every refusal, not the window"
    recent = snapshot["recent_server_errors"]
    assert len(recent) == 2, "the window is bounded"
    assert [row["message"] for row in recent] == ["boom 2", "boom 3"], "newest last"


def test_a_refusal_the_lane_cannot_attribute_still_reaches_the_snapshot() -> None:
    """Not every refusal is about an item: a rate limit is about the session.

    Failing to match must degrade to the aggregate, never to a dropped record —
    the visibility this card adds has to be strictly more than what was there.
    """

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.settle()
    rig.server.transport.send(
        {"type": "error", "error": {"code": "rate_limit_exceeded", "message": "slow down"}}
    )
    rig.lane.pump()

    snapshot = rig.lane.snapshot()
    assert snapshot["server_errors"] == 1
    assert snapshot["items_refused"] == 0, "nothing may be attributed to an item we did not send"
    assert snapshot["recent_server_errors"][-1]["code"] == "rate_limit_exceeded"
    assert "item" not in snapshot["recent_server_errors"][-1]


def test_a_refused_memory_tail_item_names_the_half_of_the_conversation_it_cost() -> None:
    """The silent half of R6's finding: the tail, refused item by item.

    Every session open and every reconnect replayed the owner's sentences with
    the robot's answers missing from between them, and ``tail_items_injected``
    happily counted them all. The counter records what was SENT; this records
    what was kept.
    """

    tail = [
        {"role": "user", "content": "I liked the bench by the water"},
        {"role": "assistant", "content": "The one under the willow."},
    ]
    rig = _Rig(_deaf_after_stall_script(), memory_tail=lambda: tail)
    rig.open()
    rig.settle()
    assert rig.lane.tail_items_injected == 2

    items = [
        frame
        for frame in rig.transports[-1].sent
        if frame.get("type") == "conversation.item.create"
    ]
    assistant = [frame for frame in items if frame["item"]["role"] == "assistant"]
    assert len(assistant) == 1
    rig.server.transport.send(
        _refusal_for(
            str(assistant[0]["event_id"]),
            message="Invalid value: 'text'. Value must be 'output_text'.",
        )
    )
    rig.lane.pump()

    snapshot = rig.lane.snapshot()
    assert snapshot["items_refused"] == 1
    refused = snapshot["recent_server_errors"][-1]["item"]
    assert refused["role"] == "assistant"
    assert refused["purpose"] == "memory tail"
    assert refused["text"] == "The one under the willow."
    assert snapshot["narrations_refused"] == 0, "a tail item is not a narration"


def test_the_item_trace_is_bounded_and_forgets_the_oldest_first() -> None:
    """An ACCEPTED item never produces an error, so its descriptor is never
    claimed. Without a bound the map grows one entry per item for the life of
    the session. Oldest-first because a refusal arrives within a frame or two of
    the item that caused it.
    """

    rig = _Rig(_deaf_after_stall_script(), item_trace_limit=2)
    rig.open()
    rig.settle()
    for index in range(3):
        rig.lane._send_item(role="system", text=f"fact {index}", purpose="narration")
    sent = [
        frame
        for frame in rig.transports[-1].sent
        if frame.get("type") == "conversation.item.create"
    ]
    first, _, third = (str(frame["event_id"]) for frame in sent[-3:])

    rig.server.transport.send(_refusal_for(first))
    rig.server.transport.send(_refusal_for(third))
    rig.lane.pump()

    snapshot = rig.lane.snapshot()
    assert snapshot["server_errors"] == 2, "both refusals are recorded whatever the trace says"
    assert snapshot["items_refused"] == 1, "only the item still in the trace can be named"
    assert snapshot["recent_server_errors"][-1]["item"]["text"] == "fact 2"


def test_a_frame_the_socket_dropped_leaves_nothing_for_a_refusal_to_claim() -> None:
    """A frame that never left cannot be what a later error is about.

    Keeping its descriptor would let an unrelated refusal claim it and report a
    narration as "refused by the provider" when the provider never saw it.
    """

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.settle()
    rig.transports[-1].close()

    assert rig.lane._send_item(role="system", text="never left", purpose="narration") is False
    assert rig.lane._item_trace == {}, "a dropped frame must leave no descriptor behind"
    assert rig.lane.dropped_sends == 1, "the drop is still counted where drops are counted"


def test_a_reconnect_forgets_the_dead_sessions_item_descriptors() -> None:
    """Event ids are per-socket. A new session can never echo an old one's."""

    rig = _Rig(_deaf_after_stall_script())
    rig.open()
    rig.settle()
    rig.lane.narrate_event("The robot arrived.")
    stale = _last_item_event_id(rig)
    assert rig.lane._item_trace

    assert _force_stall(rig) == "stall"
    rig.settle()
    assert rig.lane._item_trace.get(stale) is None

    rig.server.transport.send(_refusal_for(stale))
    rig.lane.pump()
    assert rig.lane.snapshot()["narrations_refused"] == 0, (
        "a refusal on the NEW socket must never be attributed to the dead one's item"
    )


# --------------------------------------------------------------------------
# Card R8, work item 3 — the voice-turn owed signal.
#
# R6's repay keys on ``_responses_pending``, which counts only the
# ``response.create`` frames this lane sent. A server-VAD turn is answered by a
# response the PROVIDER creates, so nothing was ever owed by the lane's
# bookkeeping and a spoken sentence that died with its socket was lost in
# silence — R6 does_not_prove ("No voice turn was repaid"), R6 open risk 3.
# --------------------------------------------------------------------------
def _spoken_turn_nobody_answers() -> list[Step]:
    """Server VAD hears the owner out, and the provider then says nothing.

    The exact shape of the incident: the turn is real, it is in the
    conversation, the provider owes an answer, and no ``response.create`` was
    ever sent by this lane because none was needed.
    """

    return handshake() + [
        Step(
            "input_audio_buffer.append",
            (
                {"type": "input_audio_buffer.speech_started", "audio_start_ms": 0},
                {"type": "input_audio_buffer.speech_stopped", "audio_end_ms": 900},
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "item_id": "item_owner_spoken",
                    "transcript": "are you still there",
                },
            ),
            label="spoken_turn_then_silence",
        )
    ]


def _answers_the_spoken_repay() -> list[Step]:
    return handshake("sess_fake_2") + _text_turn(
        reply="Yes — still here.", response_id="resp_repay", item_id="item_robot_repay"
    )


def test_a_spoken_turn_the_dead_session_never_answered_is_repaid() -> None:
    """The sentence this work item exists for.

    Nothing in the lane sent a ``response.create``, so ``_responses_pending`` is
    zero for the whole turn — and before R8 that meant a reconnect inherited a
    question with nobody asking it to be answered, exactly as R6's typed turn
    did before R6 fixed it.
    """

    rig = _Rig(_spoken_turn_nobody_answers(), reconnect_script=_answers_the_spoken_repay())
    rig.open()
    rig.lane.send_audio(b"\x00\x01" * 240)
    rig.settle()

    assert rig.lane._responses_pending == 0, "the premise: this lane asked for nothing"
    assert rig.lane.snapshot()["voice_turn_owed"] is True
    assert rig.lane.snapshot()["voice_turns_owed"] == 1

    assert _force_stall(rig) == "stall"
    rig.settle()

    assert rig.lane.turn_repays == 1, "a spoken turn that died with its socket was not repaid"
    assert rig.lane.voice_turn_repays == 1
    assert "resp_repay" in [row["response_id"] for row in rig.lane.usage_rows], (
        "the inherited spoken turn was never answered on the new session"
    )


def test_a_spoken_turn_that_was_answered_is_never_repaid() -> None:
    """The double-count guard. An answered question must not be re-asked.

    ``happy_turn`` is a complete spoken turn: VAD open, VAD close, transcript,
    the reply, and ``response.done``. After it the provider owes nothing, and a
    reconnect that re-asked would buy the owner a duplicate answer, a duplicate
    bill, and a transcript that says the same thing twice.
    """

    rig = _Rig(handshake() + happy_turn())
    rig.open()
    rig.lane.send_audio(b"\x00\x01" * 240)
    rig.settle()

    assert rig.lane.usage_rows, "the turn must actually be answered for this to prove anything"
    assert rig.lane.snapshot()["voice_turn_owed"] is False, (
        "a response came back; nothing is owed"
    )

    assert _force_stall(rig) is None, "nothing is outstanding, so nothing is stalled"
    rig.lane._reconnect("disconnect")
    rig.settle()

    assert rig.lane.turn_repays == 0, "an answered spoken turn was re-asked anyway"
    assert rig.lane.voice_turn_repays == 0


def test_speech_stopped_and_the_transcription_that_follows_are_one_owed_turn() -> None:
    """Two frames, one utterance, one owed answer — and one repay.

    Counting both would make ``voice_turns_owed`` claim the owner said twice as
    much as they did, and would make a single unanswered sentence look like two.
    """

    rig = _Rig(_spoken_turn_nobody_answers(), reconnect_script=_answers_the_spoken_repay())
    rig.open()
    rig.lane.send_audio(b"\x00\x01" * 240)
    rig.settle()

    assert rig.lane.voice_turns_owed == 1, "speech_stopped + transcription is ONE spoken turn"

    assert _force_stall(rig) == "stall"
    rig.settle()
    assert len(_response_creates(rig)) == 1, "one question, one repay"


def test_a_typed_and_a_spoken_turn_outstanding_together_are_still_one_repay() -> None:
    """Both signals set is still one conversation with one question at the end.

    ``_responses_pending`` and the voice signal are deliberately separate
    counters; a repay that fired once per signal would be the same duplicate-bill
    defect R6 bounded for owed responses, reintroduced through the side door.
    """

    script = handshake() + [
        Step(
            "response.create",
            (
                {"type": "input_audio_buffer.speech_stopped", "audio_end_ms": 400},
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "item_id": "item_owner_spoken",
                    "transcript": "and also this",
                },
            ),
            label="typed_then_spoken_then_silence",
        )
    ]
    rig = _Rig(script, reconnect_script=_answers_the_spoken_repay())
    rig.open()
    rig.lane.send_text("a typed question")
    rig.settle()

    assert rig.lane._responses_pending == 1, "the typed turn is owed"
    assert rig.lane.snapshot()["voice_turn_owed"] is True, "and so is the spoken one"

    assert _force_stall(rig) == "stall"
    rig.settle()

    assert rig.lane.turn_repays == 1
    assert len(_response_creates(rig)) == 1, "two signals must not buy two repays"


def test_a_spoken_turn_starts_the_watchdogs_patience_clock() -> None:
    """The provider becomes late when the owner STOPS talking, not before.

    Same rule R6's ``_arm_watchdog`` states for every other request: the clock
    measures our wait, never the provider's last frame.

    The script is the shape that makes this OBSERVABLE, and it took a green seed
    to find it. ``send_audio`` also arms the watchdog, so in an ordinary spoken
    turn ``_expecting_server`` is already True and arming again changes nothing
    a test can see. The case that matters is the one below: the provider
    finishes the PREVIOUS answer and server VAD closes the NEXT utterance in the
    same batch of frames. ``_on_response_done`` disarms — correctly, nothing it
    knows about is outstanding — and if the spoken turn does not arm the clock
    itself, the lane is left waiting on an answer it is not watching for, which
    is a second way to lose the same sentence.
    """

    script = handshake() + [
        Step(
            "input_audio_buffer.append",
            (
                # the answer to the turn before this one lands first…
                response_done("resp_previous"),
                # …and server VAD closes the owner's NEXT sentence right behind it
                {"type": "input_audio_buffer.speech_stopped", "audio_end_ms": 900},
            ),
            label="answer_lands_then_the_owner_speaks_again",
        )
    ]
    rig = _Rig(script)
    rig.open()
    rig.lane.send_audio(b"\x00\x01" * 240)
    rig.settle()

    assert rig.lane._responses_pending == 0, "the lane itself asked for nothing"
    assert rig.lane._expecting_server is True, (
        "a spoken turn is a turn we are waiting on, even when the frame before it "
        "was an answer to something else"
    )
    assert rig.lane.tick() is None, "the owner has only just stopped speaking"
    rig.clock.advance(STALL_TIMEOUT_S + 1.0)
    assert rig.lane.tick() == "stall", "a spoken turn nobody answers must be noticed"


def test_a_spoken_repay_says_in_the_ledger_that_the_turn_was_spoken() -> None:
    """"The previous session owed 0 answer(s)" is a lie about a real question.

    The row has to explain a reply that arrives after a session boundary, and
    for a spoken turn the honest explanation is that the lane never sent a
    request for it because it never had to.
    """

    memory = ConversationMemory(":memory:")
    rig = _Rig(
        _spoken_turn_nobody_answers(),
        reconnect_script=_answers_the_spoken_repay(),
        ledger=memory,
    )
    rig.open()
    rig.lane.send_audio(b"\x00\x01" * 240)
    rig.settle()
    assert _force_stall(rig) == "stall"
    rig.settle()

    rows = [row for row in _system_rows(memory) if "[turn repaid]" in row]
    assert rows, _system_rows(memory)
    assert "SPOKEN" in rows[-1], rows[-1]
    assert "owed 0 answer(s)" not in rows[-1], rows[-1]


def test_a_narration_never_talks_over_a_spoken_turn_awaiting_its_answer() -> None:
    """The floor gate, applied to the half ``_responses_pending`` cannot see.

    "The robot does not talk over its own pending answer" was only ever enforced
    for turns this lane asked for. A spoken question was invisible to it, so a
    mission terminal could interrupt the owner's own question in ``mode: audio``.
    """

    rig = _Rig(_spoken_turn_nobody_answers())
    rig.open()
    rig.lane.send_audio(b"\x00\x01" * 240)
    rig.settle()

    assert rig.lane.playback_owned is False, "nothing is playing; only the gate can refuse"
    assert rig.lane._responses_pending == 0, "and no response was asked for by this lane"
    assert rig.lane.narrate_event("The robot arrived.") is False, (
        "the owner asked something out loud and is still waiting for the answer"
    )
    assert rig.lane.snapshot()["narrations_skipped"] >= 1


def test_a_spoken_turn_is_bounded_by_the_same_repay_budget() -> None:
    """A voice turn the provider dies on every time is abandoned, not re-asked.

    R6 bounded this for typed turns because an unbounded repay keeps billing on
    a socket that will never answer. The voice signal must inherit the bound
    rather than route around it.
    """

    memory = ConversationMemory(":memory:")
    rig = _Rig(
        _spoken_turn_nobody_answers(),
        reconnect_script=_never_answers_script(),
        ledger=memory,
    )
    rig.open()
    rig.lane.send_audio(b"\x00\x01" * 240)
    rig.settle()
    assert rig.lane.snapshot()["voice_turn_owed"] is True

    for _ in range(8):
        if _force_stall(rig) is None:
            break
        rig.settle()

    assert rig.lane.turn_repays == 3, (
        f"the voice signal must not route around the bound: {rig.lane.turn_repays}"
    )
    assert rig.lane.turn_repays_abandoned == 1
    assert any("[turn abandoned]" in row for row in _system_rows(memory))


def test_a_new_spoken_turn_gets_its_own_repay_budget() -> None:
    """Symmetric with ``send_text``: one poisoned sentence does not disarm the
    mechanism for everything the owner says next.
    """

    rig = _Rig(_spoken_turn_nobody_answers(), reconnect_script=_never_answers_script())
    rig.open()
    rig.lane.send_audio(b"\x00\x01" * 240)
    rig.settle()
    for _ in range(4):
        _force_stall(rig)
        rig.settle()
    assert rig.lane.turn_repays == 3
    assert rig.lane.turn_repays_abandoned == 1

    # The owner speaks again on the session that never answers anything.
    rig.server.transport.send({"type": "input_audio_buffer.speech_stopped", "audio_end_ms": 700})
    rig.lane.pump()

    assert _force_stall(rig) == "stall"
    rig.settle()
    assert rig.lane.turn_repays == 4, "the new spoken turn inherited the old turn's spent budget"


def test_the_voice_signal_leaves_the_pending_ledger_exactly_as_sent() -> None:
    """``_responses_pending`` still counts frames this lane sent, and only those.

    R6's whole accounting — the watchdog, the repay, the beat counters and four
    of its sixteen seeds — reads that number through one invariant. Folding a
    provider-created response into it would make it a count of two different
    things and would break every one of them silently.
    """

    rig = _Rig(_spoken_turn_nobody_answers())
    rig.open()
    rig.lane.send_audio(b"\x00\x01" * 240)
    rig.settle()

    creates = [
        frame
        for frame in rig.transports[-1].sent
        if frame.get("type") == "response.create"
    ]
    assert creates == [], "a server-VAD turn needs no response.create from us"
    assert rig.lane._responses_pending == 0, (
        "the voice signal must live beside the pending count, never inside it"
    )
    assert rig.lane._voice_turn_owed is True
