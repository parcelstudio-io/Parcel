"""Card DUPLEX-1: the pre-registered rows, on the product lane.

WHAT THIS FILE MEASURES
-----------------------
``scrum/20260822/task_26/PREREGISTRATION.md`` (sha in ``DUPLEX1_STATUS.md``)
fixed seven rows and one decision rule before any of them was run. This file is
where D-1 … D-7 are measured.

THE RIG IS MARK-1'S, IMPORTED, NOT FORKED
-----------------------------------------
``FakeRealtimeServer`` → :class:`~parcel_robot.realtime.lane.RealtimeLane` →
:class:`~parcel_robot.realtime.browser_sink.BrowserSink` →
:class:`~parcel_robot.realtime.audio_gateway.BrowserAudioGateway` → a headless
port of ``ui/index.html``'s playback path. Everything in
``tests/test_mark1_barge_in_mark.py`` is used as it stands — the fixtures, the
clock, and in particular the referee ``_AudioContext.rendered_ms()``, which is
computed from the scheduled buffers and is never a number under test. What this
file adds is the panel's new playback ``GainNode`` (:class:`_DuckBrowser`) and
the two stopwatches DUPLEX-1 pre-registered.

NO MONKEYPATCH. ``played_ms``, ``turn_timings``, the gateway's clamps and the
lane's hold are all the shipped code; the only thing this file constructs is a
browser, which is the one piece of the loop that does not exist on this host.

WHAT IT CANNOT MEASURE, SAID ONCE HERE
--------------------------------------
There is no microphone, no loudspeaker and no acoustic path on this machine, so
nothing here is evidence about echo, AEC or a real "mm-hmm". The burst
durations are the pre-registration's stand-ins. Every acoustic claim is
owner-gated and listed in the status doc.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

# MARK-1's rig, imported rather than forked: same fixtures, same clock, same
# referee, same headless panel base. ``tests/`` is on the import path because
# ``conftest.py`` lives there.
from test_mark1_barge_in_mark import (
    FIXTURES,
    _grid,
    _HeadlessBrowser,
    _p,
    _Rig,
)
from test_mark1_barge_in_mark import TOKEN as MARK1_TOKEN

from parcel_robot.duplex.turn_controller import (
    MIN_DUCK_GAIN,
    STATE_LISTEN,
    STATE_OVERLAP,
    STATE_SPEAK,
)
from parcel_robot.realtime.audio_gateway import (
    CAPTURE_INDEX_NAME,
    SERVER_DUCK,
    BrowserAudioGateway,
    SessionAudioCapture,
)
from parcel_robot.realtime.browser_sink import BrowserSink
from parcel_robot.realtime.config import MODE_AUDIO, RealtimeConfig
from parcel_robot.realtime.lane import RealtimeLane

BURST = FIXTURES[0]

#: The pre-registered backchannel set: (token, burst_ms). Fixed in
#: PREREGISTRATION.md §2 before the floor ladder was run.
BACKCHANNELS: tuple[tuple[str, float], ...] = (
    ("mm", 120.0),
    ("mm-hmm", 150.0),
    ("yeah", 180.0),
    ("sure", 200.0),
    ("uh-huh", 220.0),
    ("right", 240.0),
    ("okay", 260.0),
    ("[laugh]", 300.0),
    ("yeah okay", 320.0),
    ("mm-hmm yeah", 380.0),
)

#: ...and the interruptions, which must never be swallowed at any floor.
INTERRUPTIONS: tuple[tuple[str, float], ...] = (
    ("wait, stop", 600.0),
    ("no, go to the kitchen", 900.0),
    ("actually can you come back here please", 1400.0),
)

#: PREREGISTRATION.md §3. Smallest first; the rule takes the first that clears.
FLOOR_LADDER: tuple[float, ...] = (0.0, 250.0, 350.0, 450.0, 700.0, 1000.0)

#: TURN-1's accepted minimum ``silence_duration_ms`` (200–800). The prerequisite
#: half of MARK-1's H-4: at the provider's default ~500 ms tail nothing under
#: 700 ms survives even a 150 ms "mm-hmm".
TUNED_TAIL_S = 0.200
PROVIDER_TAIL_S = 0.500


class _DuckBrowser(_HeadlessBrowser):
    """MARK-1's headless panel plus DUPLEX-1's playback ``GainNode``.

    Mirrors ``duckGainFor`` / ``applyDuck`` / ``resetDuck`` in ``index.html``.
    The JS is pinned to this port by ``tests/test_duplex1_panel_duck.py``, which
    lifts the real function out of the file and evaluates it in gjs — the
    technique MARK-1's correction pass established after "no JS engine on this
    host" turned out to be false.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.duck_gain = 1.0
        self.ducks_applied = 0
        self.ducks_dropped = 0
        #: The clock the FIRST attenuation of the current utterance landed at.
        self.ducked_at: float | None = None
        self.resumed_at: float | None = None
        self.duck_frames: list[dict] = []

    def _reset_duck(self) -> None:
        self.duck_gain = 1.0

    def _control(self, body: dict) -> None:
        kind = body.get("type")
        if kind == SERVER_DUCK:
            self.duck_frames.append(dict(body))
            # ``duckGainFor``: a duck for an utterance that is no longer playing
            # must never attenuate the reply that replaced it.
            utterance = body.get("utterance")
            gain = body.get("gain")
            # CORRECTION PASS, finding 1. This port drifted from the panel in
            # the one direction a port must never drift: it was STRICTER than
            # the shipped JS (it refused ``None``/``[]``/``""`` that
            # ``Number()`` happily read as ``+0``), so no row here could ever
            # have caught the silent-mute defect. It now mirrors the shipped
            # rule line for line — ``typeof body.gain !== "number"`` first, no
            # coercion, and a clamp that bottoms out at ``MIN_DUCK_GAIN``.
            # ``bool`` is excluded explicitly because Python's ``bool`` is an
            # ``int`` and JS's ``false`` is not a number.
            if (
                not self.gain_node_present
                or isinstance(utterance, bool)
                or not isinstance(utterance, int)
                or utterance <= 0
                or utterance != self.utterance
                or isinstance(gain, bool)
                or not isinstance(gain, (int, float))
                or not math.isfinite(float(gain))
            ):
                self.ducks_dropped += 1
                return
            level = max(MIN_DUCK_GAIN, min(1.0, float(gain)))
            self.duck_gain = level
            self.ducks_applied += 1
            if level < 1.0 and self.ducked_at is None:
                self.ducked_at = self._clock()
            elif level >= 1.0 and self.ducked_at is not None and self.resumed_at is None:
                self.resumed_at = self._clock()
            return
        if kind == "utterance":
            self._reset_duck()
        if kind == "stop":
            self._reset_duck()
        super()._control(body)

    #: The panel builds the node in ``armCapture``; a port with no node is the
    #: pre-DUPLEX-1 panel and is what the "an old tab is not attenuated" row
    #: drives.
    gain_node_present = True


class _OldBrowser(_DuckBrowser):
    """The panel as MARK-1 shipped it: no gain node, so a duck does nothing."""

    gain_node_present = False


class _DuplexRig(_Rig):
    """MARK-1's rig with the ducking panel and DUPLEX-1's two stopwatches."""

    def __init__(
        self,
        *args,
        browser_class: type[_DuckBrowser] = _DuckBrowser,
        capture: SessionAudioCapture | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        if capture is not None:
            # Correction pass, finding 4. The R17 tee is a CONSTRUCTOR argument
            # to the gateway, so binding one means rebuilding the chain from the
            # gateway down — the same three objects ``_Rig`` builds, with the
            # same arguments, plus the capture. Rebuilt rather than poked into
            # ``gateway._capture`` so nothing here reaches past a public door.
            self.gateway = BrowserAudioGateway(
                on_audio=self.heard_frames.append,
                on_mic=lambda _on: None,
                clock=self.clock,
                capture=capture,
            )
            self.gateway.bind_token(MARK1_TOKEN)
            self.gateway.start()
            self.conn = self.gateway.attach(MARK1_TOKEN)
            self.sink = BrowserSink(self.gateway)
            self.lane = RealtimeLane(
                config=RealtimeConfig(enabled=True, source="duplex1", mode=MODE_AUDIO),
                instructions="be a good dog",
                transport_factory=self._factory,
                sink=self.sink,
                clock=self.clock,
                **{k: v for k, v in kwargs.items() if k == "backchannel_floor_ms"},
            )
        self.capture = capture
        self.browser = browser_class(
            self.clock,
            self.gateway,
            self.conn,
            ack_mode=self.browser.ack_mode,
            socket_lag_s=self.browser._socket_lag_s,
        )
        #: When the lane itself asked for the duck (the pump pass that handled
        #: ``speech_started``), and when the truncate left the lane.
        self.duck_requested_at: float | None = None
        self.truncate_at: float | None = None

    @property
    def onset_at(self) -> float:
        """The instant the server made ``speech_started`` available."""

        return self._t0 + self.barge_at

    def _note_truncate(self) -> None:
        super()._note_truncate()
        if self.duck_requested_at is None and self.lane.ducks_requested > 0:
            self.duck_requested_at = self.clock.now
        if self.truncate_at is None and self.truncates():
            self.truncate_at = self.clock.now

    # ------------------------------------------------------------ stopwatches
    @property
    def duck_latency_ms(self) -> float | None:
        """D-1: the lane saw the onset → the panel's gain is below 1.0."""

        if self.browser.ducked_at is None or self.duck_requested_at is None:
            return None
        return 1000.0 * (self.browser.ducked_at - self.duck_requested_at)

    @property
    def time_to_quiet_ms(self) -> float | None:
        """D-2b: the owner started → the panel's gain is below 1.0."""

        if self.browser.ducked_at is None:
            return None
        return 1000.0 * (self.browser.ducked_at - self.onset_at)

    @property
    def cancel_latency_ms(self) -> float | None:
        """D-2: the owner started → ``conversation.item.truncate`` on the wire."""

        if self.truncate_at is None:
            return None
        return 1000.0 * (self.truncate_at - self.onset_at)


def _run(
    *,
    floor_ms: float,
    burst_ms: float,
    tail_s: float = TUNED_TAIL_S,
    barge_at: float = 1.0,
    fixture=BURST,
    browser_class: type[_DuckBrowser] = _DuckBrowser,
    socket_lag_s: float = 0.0,
    provider_cancel_at: float | None = None,
    capture: SessionAudioCapture | None = None,
) -> _DuplexRig:
    stopped_at = barge_at + burst_ms / 1000.0 + tail_s
    rig = _DuplexRig(
        fixture,
        barge_at,
        backchannel_floor_ms=floor_ms,
        speech_stopped_at=stopped_at,
        socket_lag_s=socket_lag_s,
        provider_cancel_at=provider_cancel_at,
        browser_class=browser_class,
        capture=capture,
    )
    rig.drive(tail_s=max(1.6, floor_ms / 1000.0 + 0.6))
    return rig


def _survival(floor_ms: float, tail_s: float = TUNED_TAIL_S) -> tuple[int, list[str]]:
    survived = 0
    detail: list[str] = []
    for token, burst_ms in BACKCHANNELS:
        rig = _run(floor_ms=floor_ms, burst_ms=burst_ms, tail_s=tail_s)
        ok = rig.survived()
        survived += int(ok)
        detail.append(f"{token}({burst_ms:.0f}ms)={'yes' if ok else 'NO'}")
    return survived, detail


# ============================================================ the floor ladder
@pytest.mark.load_sensitive
def test_duplex1_d3_the_shipped_floor_is_the_smallest_that_clears_survival() -> None:
    """PREREGISTRATION.md §3's decision rule, executed rather than described.

    The rule was fixed before any of this ran: take the SMALLEST floor on the
    ladder whose survival over the ten pre-registered acknowledgement tokens is
    >= 0.9, with both of TURN-1's prerequisites set. Whatever cancel latency
    that floor turns out to cost is then reported, not negotiated.
    """

    lines = ["", "[DUPLEX-1 D-3] the floor ladder (silence_duration_ms = 200)"]
    chosen: float | None = None
    for floor in FLOOR_LADDER:
        survived, detail = _survival(floor)
        rate = survived / len(BACKCHANNELS)
        lines.append(f"    floor={floor:>6.0f} ms  survival={survived:>2}/10 ({rate:.2f})")
        lines.append(f"        {'  '.join(detail)}")
        if chosen is None and rate >= 0.9:
            chosen = floor
    lines.append(f"    decision rule picks: {chosen} ms")
    print("\n".join(lines))

    assert chosen is not None, "no floor on the pre-registered ladder reaches 0.9 survival"
    assert chosen == SHIPPED_FLOOR_MS, (
        f"the ladder picked {chosen} ms; the config and this file say {SHIPPED_FLOOR_MS} ms"
    )
    survived, _detail = _survival(SHIPPED_FLOOR_MS)
    assert survived / len(BACKCHANNELS) >= 0.9


#: What §3's rule picked, written down so the config, the rig and the status
#: doc cannot drift apart. The test above re-derives it every run.
SHIPPED_FLOOR_MS = 700.0


@pytest.mark.load_sensitive
def test_duplex1_d6_without_the_prerequisites_the_floor_buys_nothing() -> None:
    """D-6: the arms with TURN-1's knobs left at the provider's defaults.

    Two separate failures, and they are different failures:

    * **the tail** — at the provider's ~500 ms silence tail the lane cannot
      learn the owner stopped until 500 ms after they did, so a floor only
      survives bursts shorter than ``floor - 500``;
    * **``interrupt_response: true``** — the provider cancels its own reply the
      moment its VAD hears the owner, so the reply is already dead before the
      floor can protect it. MARK-1's correction pass makes the lane handle that
      correctly (it commits rather than counting a survived backchannel), which
      is exactly why the floor then buys nothing at all.
    """

    tuned, _d = _survival(SHIPPED_FLOOR_MS, tail_s=TUNED_TAIL_S)
    untuned, _d2 = _survival(SHIPPED_FLOOR_MS, tail_s=PROVIDER_TAIL_S)

    # ...and the interrupt_response arm: the provider cancels inside the floor.
    cancelled_survivors = 0
    for _token, burst_ms in BACKCHANNELS:
        rig = _run(
            floor_ms=SHIPPED_FLOOR_MS,
            burst_ms=burst_ms,
            tail_s=TUNED_TAIL_S,
            provider_cancel_at=1.0 + 0.15,
        )
        cancelled_survivors += int(rig.survived())

    print(
        f"\n[DUPLEX-1 D-6] floor={SHIPPED_FLOOR_MS:.0f} ms  "
        f"tail=200 ms -> {tuned}/10   tail=500 ms -> {untuned}/10   "
        f"interrupt_response=true -> {cancelled_survivors}/10"
    )
    assert tuned > untuned, "tuning silence_duration_ms is supposed to be the prerequisite"
    assert cancelled_survivors == 0, (
        "with interrupt_response left true the provider kills the reply first: "
        "no backchannel can survive, whatever the floor says"
    )


# ==================================================================== D-1 / D-2b
@pytest.mark.load_sensitive
def test_duplex1_d1_the_reply_goes_quiet_within_100ms_of_the_onset() -> None:
    """D-1 (<= 100 ms) and D-2b (<= 100 ms), and what those numbers are worth.

    **Read the second table, not the first.** At the nominal socket this rig's
    transport has no delay and the browser drains inside the same simulated
    instant, so the answer is 0.0 ms *by construction*. That clears the
    pre-registered bar and proves almost nothing on its own, and saying so is
    the point of printing it.

    The informative measurement is the ladder: the same barge-in at socket lags
    of 0 / 20 / 50 / 100 / 350 ms, reporting ``quiet - lag`` — everything the
    LANE adds between server VAD and the panel's gain moving. That is the part
    this card is responsible for, and it is what must stay under a pump.
    """

    duck_ms: list[float] = []
    quiet_ms: list[float] = []
    for fixture in FIXTURES:
        for barge_at in fixture.barge_at:
            rig = _run(
                floor_ms=SHIPPED_FLOOR_MS,
                burst_ms=900.0,  # a real interruption: the hold runs its course
                barge_at=barge_at,
                fixture=fixture,
            )
            assert rig.duck_latency_ms is not None, f"{fixture.name}@{barge_at}: no duck"
            duck_ms.append(rig.duck_latency_ms)
            quiet_ms.append(rig.time_to_quiet_ms or 0.0)

    lines = [
        "",
        (
            f"[DUPLEX-1 D-1] nominal socket: n={len(duck_ms)} duck "
            f"p50={_p(duck_ms, 0.5):.1f} ms p95={_p(duck_ms, 0.95):.1f} ms "
            f"max={max(duck_ms):.1f} ms"
        ),
        (
            f"[DUPLEX-1 D-2b] nominal socket: quiet p50={_p(quiet_ms, 0.5):.1f} ms "
            f"p95={_p(quiet_ms, 0.95):.1f} ms max={max(quiet_ms):.1f} ms"
        ),
        "    (0.0 is an identity of a transport with no delay — see the ladder below)",
        "[DUPLEX-1 D-1 ladder] lag_ms -> quiet p95 / lane overhead p95",
    ]
    overheads: list[float] = []
    for lag_ms in (0.0, 20.0, 50.0, 100.0, 350.0):
        arm: list[float] = []
        for barge_at in BURST.barge_at:
            rig = _run(
                floor_ms=SHIPPED_FLOOR_MS,
                burst_ms=900.0,
                barge_at=barge_at,
                socket_lag_s=lag_ms / 1000.0,
            )
            if rig.time_to_quiet_ms is not None:
                arm.append(rig.time_to_quiet_ms)
        assert arm, f"lag={lag_ms}: no duck reached the panel at all"
        over = [value - lag_ms for value in arm]
        overheads.extend(over)
        lines.append(
            f"    {lag_ms:>6.0f} -> quiet p95 {_p(arm, 0.95):>7.1f} ms / "
            f"overhead p95 {_p(over, 0.95):>6.1f} ms"
        )
    print("\n".join(lines))

    assert _p(duck_ms, 0.95) <= 100.0
    assert _p(quiet_ms, 0.95) <= 100.0
    # The row that is not free: whatever the socket costs, the lane adds under
    # one 20 Hz pump on top of it.
    assert _p(overheads, 0.95) <= 100.0
    assert max(overheads) <= 100.0


@pytest.mark.load_sensitive
def test_duplex1_d1b_a_lagging_socket_is_the_transport_bound_arm() -> None:
    """D-1b: reported, no bar. The duck can only be as fast as the socket."""

    ms: list[float] = []
    for fixture in (FIXTURES[2], FIXTURES[3]):
        for barge_at in fixture.barge_at:
            rig = _run(
                floor_ms=SHIPPED_FLOOR_MS,
                burst_ms=900.0,
                barge_at=barge_at,
                fixture=fixture,
                socket_lag_s=0.350,
            )
            if rig.time_to_quiet_ms is not None:
                ms.append(rig.time_to_quiet_ms)
    assert ms, "the lagging arm produced no duck at all"
    print(
        f"\n[DUPLEX-1 D-1b] socket 350 ms behind the tab: n={len(ms)} "
        f"p50={_p(ms, 0.5):.1f} ms p95={_p(ms, 0.95):.1f} ms max={max(ms):.1f} ms"
    )
    assert _p(ms, 0.95) >= 350.0, (
        "a 350 ms socket lag must show up in this number; if it does not, the "
        "harness is not modelling the socket at all"
    )


# ======================================================================== D-2
@pytest.mark.load_sensitive
def test_duplex1_d2_cancel_latency_at_the_shipped_floor() -> None:
    """D-2 (<= 450 ms) at the floor §3's rule picked. Reported either way.

    This row is the price of D-3 and the pre-registration says so: a floor that
    protects a 380 ms "mm-hmm yeah" cannot also cancel in 450 ms, because the
    lane does not learn the owner is still talking until the floor expires. The
    bar is not moved. What is reported beside it is D-2b — the reply is quiet
    within 100 ms either way, so the floor is spent with the dog silent under
    the owner rather than talking over them.
    """

    ms: list[float] = []
    for fixture in FIXTURES:
        for barge_at in fixture.barge_at:
            rig = _run(
                floor_ms=SHIPPED_FLOOR_MS,
                burst_ms=900.0,
                barge_at=barge_at,
                fixture=fixture,
            )
            assert rig.cancel_latency_ms is not None, f"{fixture.name}@{barge_at}: no truncate"
            ms.append(rig.cancel_latency_ms)
    verdict = "MET" if _p(ms, 0.95) <= 450.0 else "MISSED"
    print(
        f"\n[DUPLEX-1 D-2] floor={SHIPPED_FLOOR_MS:.0f} ms  n={len(ms)} "
        f"p50={_p(ms, 0.5):.1f} ms p95={_p(ms, 0.95):.1f} ms max={max(ms):.1f} ms — {verdict}"
    )
    # The number is asserted against the FLOOR, which is the thing that
    # produces it. The pre-registered 450 ms bar is reported above and recorded
    # as a miss in DUPLEX1_STATUS.md; asserting it here would be moving it.
    assert _p(ms, 0.95) <= SHIPPED_FLOOR_MS + 120.0, (
        "a commit must land within one pump of the floor expiring"
    )

    # ...and the arm that DOES meet 450 ms, so the trade is visible in one run.
    fast: list[float] = []
    for barge_at in BURST.barge_at:
        rig = _run(floor_ms=350.0, burst_ms=900.0, barge_at=barge_at)
        if rig.cancel_latency_ms is not None:
            fast.append(rig.cancel_latency_ms)
    survived_at_350, _detail = _survival(350.0)
    print(
        f"[DUPLEX-1 D-2 alt] floor=350 ms  cancel p95={_p(fast, 0.95):.1f} ms  "
        f"survival={survived_at_350}/10 — meets D-2, misses D-3"
    )
    assert _p(fast, 0.95) <= 450.0
    assert survived_at_350 / len(BACKCHANNELS) < 0.9


# ======================================================================== D-4
def test_duplex1_d4_initiative_is_refused_whenever_anyone_holds_the_floor() -> None:
    """D-4: proactive collisions = 0.

    Sampled at every pump of a real barge-in run, not at a chosen instant: the
    controller must refuse initiative in SPEAK, in OVERLAP and in YIELD, and
    the only place it may say yes is idle LISTEN with nothing owed.
    """

    rig = _DuplexRig(BURST, 1.0, backchannel_floor_ms=SHIPPED_FLOOR_MS, speech_stopped_at=2.2)
    rig.lane.open_session(handshake_token="csrf-token", mic_gesture=True)
    rig.server.pump()
    rig.lane.pump()
    rig.browser.drain()
    timeline = rig._timeline()
    moments = sorted({at for at, _kind in timeline} | _grid(3.2, 0.05))
    pending = list(timeline)
    collisions = 0
    states: list[str] = []
    for moment in moments:
        rig._advance_to(moment)
        while pending and pending[0][0] <= moment + 1e-9:
            pending.pop(0)
            rig.lane.send_audio(b"\x00" * 640)
            rig.server.pump()
        rig.lane.pump()
        state = rig.lane.turn_controller.state
        states.append(state)
        # Correction pass: ``initiative_allowed`` is a PURE read now, so
        # sampling it 70 times no longer inflates the counters this row is
        # scored from. The counted door is ``consult_initiative``.
        if rig.lane.initiative_allowed and state != STATE_LISTEN:
            collisions += 1
        if state != STATE_LISTEN:
            # ...and one real consultation per non-idle sample, so the refusal
            # count below is evidence about the product door and not about how
            # often this loop happened to look.
            assert rig.lane.consult_initiative() is False
        rig._note_truncate()
        rig.browser.drain()

    assert collisions == 0
    assert STATE_SPEAK in states, "the robot never held the floor; the row proves nothing"
    assert STATE_OVERLAP in states, "nobody ever overlapped; the row proves nothing"
    snapshot = rig.lane.snapshot()["turn_controller"]
    assert isinstance(snapshot, dict)
    assert snapshot["initiative_refusals"] > 0

    # A gate that always says no is indistinguishable from a gate that is
    # broken, so the positive case is measured in the same run: a reply that
    # ENDS on its own gives the floor back, and with nothing owed the robot may
    # speak again.
    # Correction pass: nothing is nudged into place here. The reply finishes on
    # its own, ``_on_response_done`` gives the floor back and clears the owed
    # turn through the product path, and the gate is then asked once.
    quiet = _DuplexRig(BURST, 3.10, backchannel_floor_ms=SHIPPED_FLOOR_MS, finish_at=3.30)
    quiet.drive(tail_s=1.4)
    assert quiet.lane.turn_controller.state == STATE_LISTEN
    assert quiet.lane.turn_controller.owner_turn_owed is False
    before = quiet.lane.turn_controller.initiative_grants
    assert quiet.lane.consult_initiative() is True
    granted = quiet.lane.snapshot()["turn_controller"]
    assert isinstance(granted, dict)
    assert granted["initiative_grants"] == before + 1

    print(
        f"\n[DUPLEX-1 D-4] samples={len(states)} collisions={collisions} "
        f"grants={snapshot['initiative_grants']} refusals={snapshot['initiative_refusals']}"
        f"  ·  idle arm: state={quiet.lane.turn_controller.state} "
        f"allowed={granted['initiative_grants'] >= 1}"
    )


# ======================================================================== D-5
@pytest.mark.load_sensitive
def test_duplex1_d5_no_owed_turn_is_dropped_by_a_state_transition() -> None:
    """D-5: over a bounded soak, 0 holds left open and 0 owed turns abandoned.

    The card's README asks for a one-hour fake-server soak. This is a bounded
    stand-in and the status doc says so: 40 barge-ins across the four arrival
    fixtures and both outcomes (backchannel and interruption), which is the
    part of a soak that exercises the state machine — a longer wall clock adds
    time, not transitions.
    """

    holds_left_open = 0
    abandoned = 0
    owed_at_end = 0
    runs = 0
    for fixture in FIXTURES:
        for barge_at in fixture.barge_at[:5]:
            for burst_ms in (150.0, 900.0):
                rig = _run(
                    floor_ms=SHIPPED_FLOOR_MS,
                    burst_ms=burst_ms,
                    barge_at=barge_at,
                    fixture=fixture,
                )
                runs += 1
                holds_left_open += int(rig.lane._barge_in_hold is not None)
                controller = rig.lane.turn_controller
                abandoned += controller.owed_turns_abandoned
                owed_at_end += int(controller.owner_turn_owed)
    print(
        f"\n[DUPLEX-1 D-5] runs={runs} holds_left_open={holds_left_open} "
        f"owed_abandoned={abandoned} owed_at_end={owed_at_end}"
    )
    assert runs == 40
    assert holds_left_open == 0
    assert abandoned == 0


# ======================================================================== D-7
def test_duplex1_d7_with_the_floor_off_nothing_this_card_added_happens() -> None:
    """D-7: the shipped default is byte-identical to MARK-1's floor-0 arm.

    Not "similar". The same frames in the same order, the same truncate rows,
    zero duck frames, and a controller that made no decision anybody can hear.
    """

    omitted = _DuplexRig(BURST, 1.0)
    explicit = _DuplexRig(BURST, 1.0, backchannel_floor_ms=0.0)
    omitted.run()
    explicit.run()

    assert omitted.sent_types() == explicit.sent_types()
    assert omitted.truncates() == explicit.truncates()
    assert omitted.browser.duck_frames == []
    assert omitted.gateway.snapshot()["ducks"] == 0
    assert omitted.lane.ducks_requested == 0
    assert omitted.lane.backchannel_holds == 0
    assert omitted.lane.barge_ins_committed == 1
    assert omitted.browser.duck_gain == 1.0
    # The controller still SAW it — it simply had nothing to do about it.
    assert omitted.lane.turn_controller.commits == 1
    assert omitted.lane.turn_controller.ducks == 0


# ============================================ the mechanism, not just the rows
def test_a_surviving_backchannel_ducks_and_then_comes_back_up() -> None:
    """The reply must not spend the rest of its sentence at duck level.

    Seeded RED: delete the ``_apply_turn_action(... note_owner_stopped ...)``
    line in ``_resolve_barge_in_hold`` and the resume never happens — the owner
    keeps a reply they can no longer hear, which is a worse companion than the
    one that cancelled.
    """

    rig = _run(floor_ms=SHIPPED_FLOOR_MS, burst_ms=150.0)

    assert rig.survived(), "a 150 ms burst inside a 700 ms floor is a backchannel"
    assert rig.browser.ducks_applied == 2, "one duck down and one back up"
    assert rig.browser.duck_gain == pytest.approx(1.0)
    assert rig.browser.ducked_at is not None
    assert rig.browser.resumed_at is not None
    assert rig.browser.resumed_at > rig.browser.ducked_at
    gateway = rig.gateway.snapshot()
    assert gateway["ducks"] == 2
    assert gateway["duck_resumes"] == 1
    assert rig.lane.ducks_requested == 1
    assert rig.lane.duck_resumes_requested == 1
    # Nothing was told to the provider and nothing was taken from the sink.
    assert rig.sink.interrupts == 0
    assert rig.truncates() == []


def _robot_segments(capture: SessionAudioCapture) -> list[dict]:
    index = json.loads((capture.directory / CAPTURE_INDEX_NAME).read_text(encoding="utf-8"))
    return list(index["streams"]["robot"]["segments"])


def test_the_lane_itself_derives_the_onset_that_reaches_the_capture_index(
    tmp_path: Path,
) -> None:
    """**Correction pass, finding 4.** H-7 end to end, with nothing hand-fed.

    Every earlier assertion about ``interrupted_onset_at`` passed
    ``onset_ago_s`` in at the SINK, and the seeded RED (S4) renamed the key
    inside the gateway. Neither touched the one line that actually derives the
    number — ``lane._barge_in_onset``, set in ``_on_speech_started`` and turned
    into a duration in ``_commit_barge_in``. If it were never set, the stamp
    would silently vanish from every real capture and all 58 tests would have
    stayed green.

    So this arm runs a real barge-in through the real lane into a real
    ``SessionAudioCapture``, and the number it asserts is the FLOOR — which
    only the lane can know.

    Seed: `self._barge_in_onset = now` in ``_on_speech_started`` → the two keys
    disappear and this goes RED.
    """

    capture = SessionAudioCapture(root=tmp_path, session_id="sess_duplex1_onset")
    capture.start()
    rig = _run(
        floor_ms=SHIPPED_FLOOR_MS,
        burst_ms=900.0,  # a real interruption: the floor runs its whole course
        capture=capture,
    )
    assert rig.lane.barge_ins_committed == 1
    capture.close("test")

    cut = [segment for segment in _robot_segments(capture) if segment.get("interrupted")]
    assert cut, "the committed barge-in never reached the capture index"
    segment = cut[-1]
    assert "interrupted_onset_at" in segment, (
        "the lane derived no onset: `_barge_in_onset` never reached the sink"
    )
    assert segment["interrupted_onset_at"] < segment["interrupted_at"]
    # The hold IS the floor, derived by the lane and by nothing in this test.
    assert segment["interrupt_hold_ms"] == pytest.approx(SHIPPED_FLOOR_MS, abs=60.0), segment


def test_with_the_floor_off_the_cut_carries_no_onset_keys(tmp_path: Path) -> None:
    """Floor 0: the cut IS the onset, and MARK-1's index is unchanged.

    The keys must be ABSENT, not zero — an `interrupt_hold_ms` of 0.0 on every
    pre-DUPLEX-1 capture would make the two eras indistinguishable to AIR-1's
    join.
    """

    capture = SessionAudioCapture(root=tmp_path, session_id="sess_duplex1_floor0")
    capture.start()
    rig = _DuplexRig(BURST, 1.0, backchannel_floor_ms=0.0, capture=capture)
    rig.run()
    assert rig.lane.barge_ins_committed == 1
    capture.close("test")

    segment = [s for s in _robot_segments(capture) if s.get("interrupted")][-1]
    assert "interrupted_at" in segment
    assert "interrupted_onset_at" not in segment
    assert "interrupt_hold_ms" not in segment


def test_ducking_does_not_move_the_played_clock_or_the_mark() -> None:
    """The owner HEARD the ducked audio, quietly, and the mark must say so.

    A duck that reset the played anchor would make every held barge-in truncate
    early — the exact class of defect MARK-1 exists to remove, reintroduced by
    the feature meant to soften it.
    """

    ducked = _run(floor_ms=SHIPPED_FLOOR_MS, burst_ms=900.0)
    row = ducked.row()
    assert row.audio_end_ms > 0
    assert row.error_ms <= 150.0, f"a ducked reply's mark must be as honest: {row}"
    # ...and the browser really did keep playing through the hold.
    assert ducked.browser.context.rendered_ms() > 1_000.0


def test_a_stop_that_lands_past_the_deadline_never_splits_the_two_deciders() -> None:
    """**Correction pass, finding 2.** The pump gap that made them disagree.

    A pump pass can be late — a slow ledger write, a GC pause, a stalled disk in
    the tee — and if one spans BOTH the floor's deadline and the
    ``speech_stopped`` that follows it, the resolver used to see "a stop
    happened" and call it a backchannel while the controller, told the same
    stop, correctly read it as past the deadline and yielded.

    The symptom is the worst one available: the two disagree, nobody sends the
    RESUME, and a still-playing reply finishes its sentence permanently ducked —
    the owner hears the dog fade out and never come back.

    Seed: drop the ``<= hold.deadline`` comparison and this goes RED on all
    three assertions at once.
    """

    rig = _DuplexRig(BURST, 1.0, backchannel_floor_ms=SHIPPED_FLOOR_MS)
    rig.lane.open_session(handshake_token="csrf-token", mic_gesture=True)
    rig.server.pump()
    rig.lane.pump()
    rig.browser.drain()

    # Open a hold the ordinary way: a reply is playing, server VAD fires.
    rig.lane._begin_response("resp_gap", "item_gap")
    rig.lane._on_speech_started()
    rig.browser.drain()
    assert rig.lane.backchannel_holds == 1
    assert rig.gateway.snapshot()["ducks"] == 1

    hold = rig.lane._barge_in_hold
    assert hold is not None
    deadline = hold.deadline

    # THE GAP: the clock jumps past the deadline, and the endpointer's stop —
    # which landed inside that gap — is delivered on the same pass.
    rig.clock.now = deadline + 0.35
    rig.lane.note_owner_speech_stopped(at=deadline + 0.20)
    rig.lane.pump()
    rig.browser.drain()

    assert rig.lane.backchannels_survived == 0, "a stop past the floor is not a 'mm-hmm'"
    assert rig.lane.barge_ins_committed == 1
    assert rig.lane.turn_controller.commits == 1
    assert rig.lane.turn_decider_disagreements == 0
    # ...and the panel is audible again either way, because the commit stopped it.
    assert rig.browser.duck_gain == pytest.approx(1.0)


def test_a_stop_that_lands_on_the_deadline_is_still_a_backchannel() -> None:
    """MARK-1's R4d boundary, unchanged by the correction: ``<=``, not ``<``."""

    rig = _DuplexRig(BURST, 1.0, backchannel_floor_ms=SHIPPED_FLOOR_MS)
    rig.lane.open_session(handshake_token="csrf-token", mic_gesture=True)
    rig.server.pump()
    rig.lane.pump()
    rig.lane._begin_response("resp_edge", "item_edge")
    rig.lane._on_speech_started()
    rig.browser.drain()
    hold = rig.lane._barge_in_hold
    assert hold is not None

    rig.clock.now = hold.deadline + 0.05
    rig.lane.note_owner_speech_stopped(at=hold.deadline)  # exactly ON it
    rig.lane.pump()
    rig.browser.drain()

    assert rig.lane.backchannels_survived == 1
    assert rig.lane.barge_ins_committed == 0
    assert rig.lane.turn_decider_disagreements == 0
    assert rig.browser.duck_gain == pytest.approx(1.0), "the reply must come back up"


def test_the_controller_and_marks_hold_never_disagree_about_a_barge_in() -> None:
    """One decider. The controller is a cross-check and never an instruction.

    If these two counts ever diverge, two objects are deciding what an
    interruption is and the product has a race, not a state machine.
    """

    for burst_ms in (150.0, 320.0, 600.0, 900.0):
        rig = _run(floor_ms=SHIPPED_FLOOR_MS, burst_ms=burst_ms)
        controller = rig.lane.turn_controller
        assert controller.commits == rig.lane.barge_ins_committed, burst_ms
        assert controller.backchannels + controller.commits == rig.lane.backchannel_holds, burst_ms


def test_a_provider_cancel_during_a_hold_leaves_the_panel_audible() -> None:
    """MARK-1's correction-pass case, with a duck in the middle of it.

    The provider cancels under ``interrupt_response``; the lane commits. The
    panel must be told to STOP, and the gain it stops at must not be carried
    into the next reply — a tab left at 0.18 would make the following answer
    inaudible for no reason anyone could see.
    """

    rig = _run(
        floor_ms=SHIPPED_FLOOR_MS,
        burst_ms=900.0,
        provider_cancel_at=1.15,
    )
    assert rig.lane.barge_ins_committed == 1
    assert rig.lane.backchannels_survived == 0
    assert rig.sink.interrupts == 1
    assert rig.browser.stops == 1
    assert rig.browser.duck_gain == pytest.approx(1.0), "stop resets the panel's gain"


def test_a_duck_minted_for_another_utterance_is_dropped_by_the_panel() -> None:
    """The stale-frame guard, and an honest note about how reachable it is.

    An ordered socket delivers ``duck`` before the ``utterance`` frame that
    would invalidate it, so on this transport the guard cannot fire from the
    product's own traffic — it is defence against a reordering proxy, a
    reconnect that replays, or a future sender that mints a duck off-thread.
    It is driven directly here rather than pretended into a scenario, and the
    same rule is evaluated against the REAL ``index.html`` function in
    ``tests/test_duplex1_panel_duck.py`` under gjs.
    """

    rig = _DuplexRig(BURST, 1.0, backchannel_floor_ms=SHIPPED_FLOOR_MS)
    rig.lane.open_session(handshake_token="csrf-token", mic_gesture=True)
    rig.server.pump()
    rig.lane.pump()
    rig.gateway.begin_utterance()
    rig.browser.drain()
    live = rig.browser.utterance
    assert live > 0

    rig.browser._control({"type": "duck", "utterance": live + 1, "gain": 0.18})
    rig.browser._control({"type": "duck", "utterance": live, "gain": "loud"})
    rig.browser._control({"type": "duck", "utterance": 0, "gain": 0.18})
    assert rig.browser.ducks_dropped == 3
    assert rig.browser.ducks_applied == 0
    assert rig.browser.duck_gain == pytest.approx(1.0)

    rig.browser._control({"type": "duck", "utterance": live, "gain": 0.18})
    assert rig.browser.ducks_applied == 1
    assert rig.browser.duck_gain == pytest.approx(0.18)


def test_a_survived_backchannel_does_not_leave_a_turn_owed() -> None:
    """MARK-1's handoff H-4(c) / its does_not_prove 6, closed and seeded.

    ``speech_stopped`` arms the owed-turn accounting for EVERY burst, including
    the one that ends a "mm-hmm". Left armed, the watchdog nudges the provider
    for an answer to a noise and the next reconnect re-asks a question the
    owner never asked.

    Seeded RED: remove the retraction block in ``_resolve_barge_in_hold`` and
    ``_voice_turn_owed`` is True here.
    """

    rig = _run(floor_ms=SHIPPED_FLOOR_MS, burst_ms=150.0)
    assert rig.survived()
    assert rig.lane.backchannel_turns_retracted == 1
    assert rig.lane._voice_turn_owed is False
    assert rig.lane.turn_controller.owner_turn_owed is False
    # The cumulative counter is history and is NOT rewritten: the turn really
    # was armed, and the record says it was taken back.
    assert rig.lane.voice_turns_owed == 1

    # ...and a real interruption still owes an answer.
    real = _run(floor_ms=SHIPPED_FLOOR_MS, burst_ms=900.0)
    assert real.lane.barge_ins_committed == 1
    assert real.lane.backchannel_turns_retracted == 0
    assert real.lane._voice_turn_owed is True


def test_a_panel_without_a_gain_node_is_not_broken_by_a_duck_frame() -> None:
    """An old tab connected to a new gateway. Counted, never fatal."""

    rig = _run(floor_ms=SHIPPED_FLOOR_MS, burst_ms=150.0, browser_class=_OldBrowser)
    assert rig.survived(), "the backchannel must still survive on an old panel"
    assert rig.browser.ducks_applied == 0
    assert rig.browser.ducks_dropped >= 1
    assert rig.browser.duck_gain == pytest.approx(1.0)


def test_the_state_machine_does_not_survive_the_hang_up_that_ends_its_reply() -> None:
    """A controller left in SPEAK by a dead socket would never speak again.

    MARK-1's correction pass, defect 4, made the provisional HOLD belong to one
    socket. The state machine has to belong to it too: stuck in SPEAK or
    OVERLAP, ``initiative_allowed`` is False forever and the dog goes
    permanently quiet because a socket died once.

    Seeded RED: drop the ``turn_controller.reset`` line from ``close()`` and
    the state below is ``overlap``.
    """

    rig = _DuplexRig(BURST, 1.0, backchannel_floor_ms=SHIPPED_FLOOR_MS)
    rig.lane.open_session(handshake_token="csrf-token", mic_gesture=True)
    rig.server.pump()
    rig.lane.pump()
    rig.lane._arm_voice_turn("the owner asked something")
    rig.lane._begin_response("resp_x", "item_x")
    rig.lane._on_speech_started()
    assert rig.lane.turn_controller.state == STATE_OVERLAP
    assert rig.lane.turn_controller.owner_turn_owed is True

    rig.lane.close()

    assert rig.lane.turn_controller.state == STATE_LISTEN
    # The lane clears the owed turn on close; the controller must agree, and the
    # drop is COUNTED rather than silent.
    assert rig.lane.turn_controller.owner_turn_owed is False
    assert rig.lane.turn_controller.owed_turns_abandoned == 1
    assert rig.lane._barge_in_onset is None


def test_the_gateway_refuses_a_duck_with_no_reply_to_attenuate() -> None:
    """A duck before any utterance would attenuate whatever comes next."""

    rig = _DuplexRig(BURST, 1.0, backchannel_floor_ms=SHIPPED_FLOOR_MS)
    rig.gateway.duck(0.18)
    snapshot = rig.gateway.snapshot()
    assert snapshot["ducks"] == 0
    assert snapshot["duck_refusals"] == 1
    assert rig.browser.duck_frames == []


def test_the_duck_frame_on_the_wire_is_the_shape_the_panel_parses() -> None:
    """The gateway's own JSON, read back. Card DUPLEX-1's wire contract."""

    rig = _DuplexRig(BURST, 1.0, backchannel_floor_ms=SHIPPED_FLOOR_MS)
    rig.lane.open_session(handshake_token="csrf-token", mic_gesture=True)
    rig.server.pump()
    rig.lane.pump()
    rig.gateway.begin_utterance()
    rig.gateway.duck(1.7)  # clamped, not refused: prototype, not production
    frames = [
        json.loads(frame)
        for frame in rig.conn.drain()
        if isinstance(frame, str) and '"duck"' in frame
    ]
    assert len(frames) == 1
    assert frames[0] == {"type": "duck", "utterance": 1, "gain": 1.0}
    assert rig.gateway.snapshot()["last_duck_gain"] == 1.0
