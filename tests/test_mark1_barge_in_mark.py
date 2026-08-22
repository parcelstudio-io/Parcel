"""Card MARK-1: an interruption tells the truth about what was heard.

WHAT THIS FILE MEASURES
-----------------------
The registered debt (``scrum/20260818/task_4/R7_STATUS.md`` does_not_prove 2,
``AUDIT_R7_FABLE.md`` carried-forward 2): the live truncation was
``[interrupted after 0 ms]`` — the provider was told the owner heard NONE of a
reply they heard thirteen chunks of, because the client only reports ``played``
when a new chunk arrives. Everything downstream of that number (the ledger line,
the model's belief about its own reply, whether it repeats itself) was wrong
after every barge-in.

THE RIG IS R7'S, EXTENDED
-------------------------
``FakeRealtimeServer`` → :class:`RealtimeLane` → :class:`BrowserSink` →
:class:`BrowserAudioGateway` → :class:`_HeadlessBrowser`. The last of those is
the piece R7 had in a scratchpad and never committed: a port of the playback
path in ``ui/index.html`` over a virtual ``AudioContext`` on the same fake clock
as everything else. ``index.html`` is never executed by any test on this host
(no browser, no DOM), so the port is pinned to the JS by source assertions in
``test_mark1_browser_ear.py`` — R7's own technique, stated out loud.

THE REFEREE IS NOT THE CODE UNDER TEST
--------------------------------------
"What the owner actually heard" is computed by :class:`_AudioContext` from the
list of scheduled buffers — the overlap of each scheduled source with
``(-inf, now]``. That is what came out of the speaker. The number the browser
*reports*, and the number the lane *truncates at*, are both measured against it
and neither is used to compute it.

THREE CLIENTS, ONE HARNESS
--------------------------
``ack_mode`` selects which client is speaking to the gateway:

* ``"none"`` — the R7 live client. Sends no ``played`` acks at all. This is the
  shape that produced ``[interrupted after 0 ms]`` live, kept here as a standing
  witness for the debt rather than a story about it.
* ``"arrival"`` — ``index.html`` as R7 shipped it: one ack per arriving chunk,
  position measured from ``playStart``. Correct while the stream keeps up,
  catastrophically wrong the moment the schedule runs dry (``playStart`` is
  re-stamped and the reported position collapses to ~0 mid-reply).
* ``"continuous"`` — MARK-1: a ~100 ms timer while audio is rendering, position
  from ``scheduled − not-yet-played``, one ``drained`` ack on the edge where the
  schedule runs dry, plus a final ack on interrupt.
* ``"continuous_no_drain"`` — MARK-1 as first written, before the correction
  pass: the same formula and the same timer, but the timer goes QUIET the moment
  the schedule drains, so the gateway extrapolates the position forward with the
  wall clock through a stall. The control for defect 3.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass

import pytest

from parcel_robot.realtime.audio_gateway import BrowserAudioGateway
from parcel_robot.realtime.browser_sink import BrowserSink
from parcel_robot.realtime.config import MODE_AUDIO, RealtimeConfig
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    audio_delta,
    audio_done,
    pcm_tone,
    response_done,
    session_created,
    speech_started,
    speech_stopped,
)
from parcel_robot.realtime.lane import RealtimeLane
from parcel_robot.realtime.protocol import PCM16_SAMPLE_RATE_HZ
from parcel_robot.realtime.transport import transport_pair

TOKEN = "panel-token-mark1"

#: The R7 live shape: a reply of thirteen coalesced chunks. The lane coalesces
#: provider deltas to 240 ms (``DEFAULT_COALESCE_MS``), so one delta of 240 ms
#: is exactly one chunk on the wire to the browser.
CHUNK_MS = 240
REPLY_CHUNKS = 13

#: How often the fixed browser reports its position while audio is rendering.
ACK_INTERVAL_S = 0.1


# ============================================================ tiny scaffolding
class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class _AudioContext:
    """The referee: the four things ``index.html`` uses from a Web Audio context.

    ``rendered_ms`` is ground truth for "what came out of the speaker" — the sum
    of every scheduled buffer's overlap with the past. It is deliberately a
    different representation from any position formula the browser reports, so a
    browser that computes its position wrongly cannot also move the target.
    """

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock
        self._t0 = clock()
        self.sources: list[list[float]] = []

    @property
    def current_time(self) -> float:
        return self._clock() - self._t0

    def schedule(self, start_s: float, duration_s: float) -> None:
        self.sources.append([start_s, duration_s])

    def stop_all(self) -> None:
        """``source.stop()`` on everything live, exactly like ``stopPlayback``."""

        now = self.current_time
        kept: list[list[float]] = []
        for start, duration in self.sources:
            if start >= now:
                continue  # scheduled but never started: nothing came out
            kept.append([start, min(duration, now - start)])
        self.sources = kept

    def reset(self) -> None:
        """A new utterance. The clock keeps running; the schedule does not."""

        self.sources = []

    def rendered_ms(self) -> float:
        now = self.current_time
        return 1000.0 * sum(max(0.0, min(d, now - s)) for s, d in self.sources)


class _HeadlessBrowser:
    """``ui/index.html``'s playback path, minus the DOM. See the module docstring."""

    def __init__(
        self,
        clock: _Clock,
        gateway: BrowserAudioGateway,
        conn: object,
        *,
        ack_mode: str = "continuous",
        socket_lag_s: float = 0.0,
    ) -> None:
        self._clock = clock
        self._gateway = gateway
        self._conn = conn
        self.ack_mode = ack_mode
        #: Card MARK-1, correction pass. How long a frame sits between leaving
        #: the gateway and reaching this tab's audio graph. Non-zero is the case
        #: the ``enqueued_ms`` clamp does NOT cover: the lane believes more
        #: audio is playing than the browser has even scheduled yet.
        self._socket_lag_s = socket_lag_s
        self._inflight: list[tuple[float, bytes | str]] = []
        self.was_rendering = False
        self.context = _AudioContext(clock)
        self.utterance = 0
        self.play_at = 0.0
        self.play_start = 0.0
        self.scheduled_ms = 0.0
        self.acks_sent = 0
        self.final_acks_sent = 0
        self.drained_acks_sent = 0
        self.hello: dict | None = None
        self.capture_pin: dict | None = None
        self.stops = 0
        self._last_tick = clock()

    # ------------------------------------------------------------- the socket
    def drain(self) -> None:
        now = self._clock()
        for frame in self._conn.drain():  # type: ignore[attr-defined]
            self._inflight.append((now + self._socket_lag_s, frame))
        while self._inflight and self._inflight[0][0] <= self._clock():
            _due, frame = self._inflight.pop(0)
            if isinstance(frame, bytes | bytearray):
                self._play_chunk(bytes(frame))
            else:
                self._control(json.loads(frame))

    def _control(self, body: dict) -> None:
        kind = body.get("type")
        if kind == "hello":
            self.hello = body
            self.capture_pin = body.get("capture")
            return
        if kind == "utterance":
            self.utterance = int(body.get("utterance") or 0)
            self.play_at = 0.0
            self.play_start = 0.0
            self.scheduled_ms = 0.0
            self.was_rendering = False
            self.context.reset()
            return
        if kind == "stop":
            self.stops += 1
            # MARK-1: one last ack with the final position, BEFORE the state that
            # computes it is thrown away.
            if self.continuous:
                self._ack(drained=self.ack_mode == "continuous")
                self.final_acks_sent += 1
            self.context.stop_all()
            self.play_at = 0.0
            self.play_start = 0.0
            self.scheduled_ms = 0.0
            self.was_rendering = False

    # ------------------------------------------------------------- playback
    def _play_chunk(self, buffer: bytes) -> None:
        if len(buffer) < 44:
            return
        rate = int.from_bytes(buffer[24:28], "little") or PCM16_SAMPLE_RATE_HZ
        samples = (len(buffer) - 44) // 2
        if samples <= 0:
            return
        duration = samples / rate
        now = self.context.current_time
        if self.play_at < now:
            self.play_at = now + 0.02
            self.play_start = self.play_at
        self.context.schedule(self.play_at, duration)
        self.play_at += duration
        self.scheduled_ms += duration * 1000.0
        self.was_rendering = True
        if self.ack_mode != "none":
            self._ack()

    @property
    def continuous(self) -> bool:
        return self.ack_mode.startswith("continuous")

    def position_ms(self) -> float:
        """What this client believes the owner has heard of this utterance."""

        if self.ack_mode == "arrival":
            # R7's formula: time since the last time the schedule was (re)stamped.
            return max(0.0, (self.context.current_time - self.play_start) * 1000.0)
        # MARK-1: scheduled minus not-yet-played. Immune to gaps, because a gap
        # moves neither number.
        remaining = max(0.0, (self.play_at - self.context.current_time) * 1000.0)
        return max(0.0, min(self.scheduled_ms, self.scheduled_ms - remaining))

    def _ack(self, *, drained: bool = False) -> None:
        if not self.utterance:
            return
        body = {"type": "played", "utterance": self.utterance, "ms": self.position_ms()}
        if self.ack_mode == "continuous":
            # Only MARK-1's corrected client knows the word. The clients it
            # replaces never sent it, which is part of what is being measured.
            body["drained"] = drained
        self._gateway.handle_control(self._conn, json.dumps(body))  # type: ignore[arg-type]
        self.acks_sent += 1
        if drained:
            self.drained_acks_sent += 1

    # ---------------------------------------------------------------- timer
    def next_tick_at(self) -> float:
        return self._last_tick + ACK_INTERVAL_S

    def tick(self) -> None:
        """The ~100 ms ``setInterval``. Only the fixed client has one."""

        self._last_tick = self._clock()
        if not self.continuous or not self.utterance:
            return
        rendering = self.play_at > self.context.current_time
        if rendering:
            self._ack()
        elif self.was_rendering and self.ack_mode == "continuous":
            # The drain edge, once. Without it the timer goes quiet at exactly
            # the moment the audio clock and the wall clock diverge.
            self._ack(drained=True)
        self.was_rendering = rendering


# ================================================================== fixtures
@dataclass(frozen=True)
class _Fixture:
    """One arrival pattern and the moments the owner talks over it."""

    name: str
    arrivals: tuple[float, ...]
    barge_at: tuple[float, ...]


def _burst() -> tuple[float, ...]:
    """The provider dumps the whole reply far faster than it plays (R7 live)."""

    return tuple(0.05 * i for i in range(REPLY_CHUNKS))


def _realtime() -> tuple[float, ...]:
    """Chunks arrive just ahead of the playhead. No gap."""

    return tuple(0.228 * i for i in range(REPLY_CHUNKS))


def _underrun() -> tuple[float, ...]:
    """Five chunks, a stall long enough to run the schedule dry, then the rest."""

    return tuple([0.05 * i for i in range(5)] + [2.0 + 0.05 * (i - 5) for i in range(5, 13)])


def _jitter() -> tuple[float, ...]:
    """Seeded jitter around real time with one shorter stall."""

    return tuple([0.19 * i for i in range(6)] + [1.70 + 0.19 * (i - 6) for i in range(6, 13)])


FIXTURES: tuple[_Fixture, ...] = (
    _Fixture("burst", _burst(), (0.33, 0.71, 1.24, 1.83, 2.42, 2.97)),
    _Fixture("realtime", _realtime(), (0.33, 0.71, 1.24, 1.83, 2.42, 2.97)),
    # 1.53 falls inside the dry stretch; 2.06 is just after the schedule restarts.
    _Fixture("underrun", _underrun(), (0.33, 0.91, 1.53, 2.06, 2.61, 3.44)),
    # 1.55 falls inside the shorter dry stretch.
    _Fixture("jitter", _jitter(), (0.27, 0.83, 1.55, 2.11, 2.68, 3.21)),
)


# ====================================================================== rig
@dataclass
class _Row:
    """One measured barge-in."""

    fixture: str
    barge_at: float
    audio_end_ms: int
    heard_ms: float
    enqueued_ms: float
    acks_at_truncate: int = 0
    regressive_acks: int = 0

    @property
    def error_ms(self) -> float:
        return abs(self.audio_end_ms - self.heard_ms)


class _Rig:
    """Lane + gateway + headless browser on one fake clock."""

    def __init__(
        self,
        fixture: _Fixture,
        barge_at: float,
        *,
        ack_mode: str = "continuous",
        backchannel_floor_ms: float | None = None,
        speech_stopped_at: float | None = None,
        finish_at: float | None = None,
        provider_cancel_at: float | None = None,
        socket_lag_s: float = 0.0,
        lane_kwargs: dict | None = None,
    ) -> None:
        self.fixture = fixture
        self.barge_at = barge_at
        self.speech_stopped_at = speech_stopped_at
        self.finish_at = finish_at
        self.provider_cancel_at = provider_cancel_at
        self.clock = _Clock()
        self._t0 = self.clock.now
        self.heard_frames: list[bytes] = []
        self.gateway = BrowserAudioGateway(
            on_audio=self.heard_frames.append,
            on_mic=lambda _on: None,
            clock=self.clock,
        )
        self.gateway.bind_token(TOKEN)
        self.gateway.start()
        self.conn = self.gateway.attach(TOKEN)
        self.sink = BrowserSink(self.gateway)
        self.browser = _HeadlessBrowser(
            self.clock, self.gateway, self.conn, ack_mode=ack_mode, socket_lag_s=socket_lag_s
        )
        self.script = self._script()
        self.servers: list[FakeRealtimeServer] = []
        kwargs = dict(lane_kwargs or {})
        if backchannel_floor_ms is not None:
            kwargs["backchannel_floor_ms"] = backchannel_floor_ms
        self.lane = RealtimeLane(
            config=RealtimeConfig(enabled=True, source="mark1", mode=MODE_AUDIO),
            instructions="be a good dog",
            transport_factory=self._factory,
            sink=self.sink,
            clock=self.clock,
            **kwargs,
        )
        self.heard_at_truncate: float | None = None
        self.acks_at_truncate = 0

    # -------------------------------------------------------------- plumbing
    def _factory(self):
        lane_end, server_end = transport_pair(clock=self.clock)
        self.servers.append(
            FakeRealtimeServer(transport=server_end, script=list(self.script), clock=self.clock)
        )
        return lane_end

    @property
    def server(self) -> FakeRealtimeServer:
        return self.servers[-1]

    def _timeline(self) -> list[tuple[float, str]]:
        events: list[tuple[float, str]] = [(t, "chunk") for t in self.fixture.arrivals]
        events.append((self.barge_at, "speech_started"))
        if self.speech_stopped_at is not None:
            events.append((self.speech_stopped_at, "speech_stopped"))
        if self.finish_at is not None:
            events.append((self.finish_at, "finish"))
        if self.provider_cancel_at is not None:
            events.append((self.provider_cancel_at, "provider_cancel"))
        events.sort(key=lambda item: (item[0], item[1] == "chunk"))
        return events

    def _script(self) -> list[Step]:
        steps = [Step("session.update", (session_created("sess_mark1"),), label="handshake")]
        for at, kind in self._timeline():
            if kind == "chunk":
                frames = (audio_delta("resp_mark1", "item_mark1", pcm_tone(CHUNK_MS)),)
            elif kind == "speech_started":
                frames = (speech_started(int(self.barge_at * 1000)),)
            elif kind == "finish":
                frames = (
                    audio_done("resp_mark1", "item_mark1"),
                    response_done("resp_mark1"),
                )
            elif kind == "provider_cancel":
                # The hosted default is ``turn_detection.interrupt_response:
                # true``: the PROVIDER cancels its own reply when its VAD hears
                # the owner, and says so with this status. Correction pass,
                # defect 2.
                frames = (response_done("resp_mark1", status="cancelled"),)
            else:
                frames = (speech_stopped(int(at * 1000)),)
            steps.append(Step("input_audio_buffer.append", frames, label=kind))
        return steps

    def _advance_to(self, offset_s: float) -> None:
        target = self._t0 + offset_s
        while True:
            tick = self.browser.next_tick_at()
            if tick <= target:
                self.clock.now = tick
                self.browser.tick()
                continue
            self.clock.now = max(self.clock.now, target)
            return

    # ------------------------------------------------------------------ run
    def run(self, *, tail_s: float = 0.05, step_s: float = 0.05) -> _Row:
        """Drive, then insist a mark was sent. See :meth:`drive` when it may not be."""

        self.drive(tail_s=tail_s, step_s=step_s)
        return self.row()

    def drive(self, *, tail_s: float = 0.05, step_s: float = 0.05) -> None:
        """Drive the whole session, pumping at the driver's real 20 Hz.

        The pump rate matters now: MARK-1's backchannel floor is a deadline, and
        a deadline measured by a harness that only pumps when a frame arrives is
        a deadline that never expires. ``tail_s`` keeps the loop running past the
        last scripted frame so a held barge-in has somewhere to be settled.
        """

        self.lane.open_session(handshake_token="csrf-token", mic_gesture=True)
        self.server.pump()
        self.lane.pump()
        self.browser.drain()
        timeline = self._timeline()
        end = (timeline[-1][0] if timeline else 0.0) + tail_s
        moments = sorted({at for at, _kind in timeline} | _grid(end, step_s))
        pending = list(timeline)
        for moment in moments:
            self._advance_to(moment)
            while pending and pending[0][0] <= moment + 1e-9:
                pending.pop(0)
                self.lane.send_audio(pcm_tone(20, seed=3))
                self.server.pump()
            self.lane.pump()
            self._note_truncate()
            self.browser.drain()

    def _note_truncate(self) -> None:
        """Ground truth for "heard", read the instant the mark is sent."""

        if self.heard_at_truncate is None and self.truncates():
            self.heard_at_truncate = self.browser.context.rendered_ms()
            self.acks_at_truncate = self.browser.acks_sent

    def truncates(self) -> list[dict]:
        transport = self.lane.transport
        assert transport is not None
        return [
            frame
            for frame in transport.sent  # type: ignore[attr-defined]
            if frame.get("type") == "conversation.item.truncate"
        ]

    def sent_types(self) -> list[str]:
        transport = self.lane.transport
        assert transport is not None
        return [str(frame.get("type")) for frame in transport.sent]  # type: ignore[attr-defined]

    def survived(self) -> bool:
        """The hold settled as a backchannel: nothing was cancelled at all."""

        return not self.truncates() and self.lane.backchannels_survived > 0

    def row(self) -> _Row:
        truncates = self.truncates()
        assert truncates, f"{self.fixture.name}@{self.barge_at}: no truncate was ever sent"
        assert self.lane.truncations, "the lane recorded no truncation row"
        return _Row(
            fixture=self.fixture.name,
            barge_at=self.barge_at,
            audio_end_ms=int(truncates[-1]["audio_end_ms"]),
            heard_ms=float(self.heard_at_truncate or 0.0),
            enqueued_ms=float(self.lane.truncations[-1]["enqueued_ms"]),
            acks_at_truncate=self.acks_at_truncate,
            regressive_acks=int(self.gateway.snapshot()["regressive_acks"]),
        )


def _grid(end_s: float, step_s: float) -> set[float]:
    """The driver's own 20 Hz tick, as offsets from the session opening."""

    steps = int(end_s / step_s) + 2
    return {round(index * step_s, 6) for index in range(steps)}


def _sweep(ack_mode: str, **kwargs) -> list[_Row]:
    rows: list[_Row] = []
    for fixture in FIXTURES:
        for barge_at in fixture.barge_at:
            rows.append(_Rig(fixture, barge_at, ack_mode=ack_mode, **kwargs).run())
    return rows


def _p(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(quantile * (len(ordered) - 1)))
    return ordered[index]


def _report(label: str, rows: list[_Row]) -> str:
    errors = [row.error_ms for row in rows]
    zeros = [row for row in rows if row.audio_end_ms == 0]
    lines = [
        (
            f"[{label}] n={len(rows)} zero_truncations={len(zeros)} "
            f"p50={_p(errors, 0.5):.1f}ms p95={_p(errors, 0.95):.1f}ms "
            f"max={max(errors):.1f}ms mean={statistics.fmean(errors):.1f}ms"
        )
    ]
    for row in rows:
        lines.append(
            f"    {row.fixture:>9}@{row.barge_at:>5.2f}s  truncate={row.audio_end_ms:>5} ms  "
            f"heard={row.heard_ms:>7.1f} ms  enqueued={row.enqueued_ms:>7.1f} ms  "
            f"|err|={row.error_ms:>7.1f} ms"
        )
    return "\n".join(lines)


# =============================================== R1/R2: the mark tells the truth
def test_mark1_r1_audio_end_ms_is_never_zero_after_a_chunk_has_played() -> None:
    """Pre-registered R1: 24/24 non-zero, and 24/24 never overstating."""

    rows = _sweep("continuous")
    print("\n" + _report("MARK-1 continuous acks", rows))
    assert len(rows) == 24
    zero = [row for row in rows if row.audio_end_ms == 0]
    assert not zero, f"truncated at 0 ms after audio played: {zero}"
    over = [row for row in rows if row.audio_end_ms > row.enqueued_ms + 1]
    assert not over, f"truncate overstates what was enqueued: {over}"


def test_mark1_r2_the_truncate_is_within_150ms_of_what_was_heard_at_p95() -> None:
    """Pre-registered R2: p95 |truncate − heard| ≤ 150 ms over the fixture set."""

    rows = _sweep("continuous")
    errors = [row.error_ms for row in rows]
    p95 = _p(errors, 0.95)
    print(
        f"\n[MARK-1 R2] p50={_p(errors, 0.5):.1f}ms p95={p95:.1f}ms max={max(errors):.1f}ms"
    )
    assert p95 <= 150.0, _report("MARK-1 continuous acks", rows)


# ============================================ the two clients this replaces
def test_the_r7_live_client_that_never_acked_is_why_the_provider_heard_zero() -> None:
    """The standing witness for the registered debt — and its seeded RED.

    R7's live client sent no ``played`` frames at all. With the pre-MARK-1
    played clock (``assume_playback_without_ack=False``) every barge-in
    truncates at 0 ms — ``[interrupted after 0 ms]`` — while the owner has heard
    seconds of the reply. That is the recorded live failure, reproduced here
    rather than described. The guard that fixes it is one line in ``played_ms``
    and this is what it looks like when it is not there.
    """

    rows = _sweep("none", lane_kwargs={"assume_playback_without_ack": False})
    zero = [row for row in rows if row.audio_end_ms == 0]
    heard = [row.heard_ms for row in zero]
    print(
        f"\n[R7 live client, pre-MARK-1 played clock] {len(zero)}/{len(rows)} truncated at "
        f"0 ms while the owner had heard up to {max(heard):.0f} ms"
    )
    assert len(zero) == len(rows), "the historical failure must still reproduce"
    assert max(heard) > 1_000.0


def test_a_client_that_never_acks_is_no_longer_told_the_owner_heard_nothing() -> None:
    """The fallback, measured: same silent client, shipped played clock.

    A browser that stops acking (a stale cached page, a JS error, R7's own
    headless client) is the case the sink can prove nothing about. The lane now
    anchors on the moment the first chunk was handed to the sink instead of
    claiming zero. It is a weaker claim than an ack and it is counted as one.
    """

    rows = _sweep("none")
    zero = [row for row in rows if row.audio_end_ms == 0]
    errors = [row.error_ms for row in rows]
    print(
        f"\n[silent client + first-enqueue fallback] zero_truncations={len(zero)} "
        f"p50={_p(errors, 0.5):.1f}ms p95={_p(errors, 0.95):.1f}ms max={max(errors):.1f}ms"
    )
    assert not zero, "no barge-in may claim the owner heard nothing of audio that was sent"
    over = [row for row in rows if row.audio_end_ms > row.enqueued_ms + 1]
    assert not over, f"the fallback must never overstate what was enqueued: {over}"


def test_the_shipped_arrival_only_ack_collapses_the_moment_the_stream_stalls() -> None:
    """``index.html`` as R7 shipped it: correct while the stream keeps up.

    One ack per arriving chunk is fine as long as chunks keep arriving. The
    moment the schedule runs dry, ``playStart`` is re-stamped to *now* and the
    reported position collapses to ~0 in the middle of a reply the owner is
    still listening to. This is the defect the timer replaces, measured.
    """

    rows = _sweep("arrival")
    errors = [row.error_ms for row in rows]
    print("\n" + _report("R7 shipped: ack per arriving chunk", rows))
    assert _p(errors, 0.95) > 150.0, "the shipped client must still miss the bound"
    assert max(errors) > 1_000.0


def test_the_continuous_client_beats_the_shipped_one_on_every_fixture() -> None:
    """Same rig, same fixtures, two clients. The comparison is the evidence."""

    fixed = {(r.fixture, r.barge_at): r.error_ms for r in _sweep("continuous")}
    shipped = {(r.fixture, r.barge_at): r.error_ms for r in _sweep("arrival")}
    worse = {key: (fixed[key], shipped[key]) for key in fixed if fixed[key] > shipped[key] + 1e-6}
    assert not worse, f"the fix must never be worse than what it replaces: {worse}"


# ============================ R4: the backchannel floor (first slice; DUPLEX-1 owns the rest)
BURST = FIXTURES[0]


def _barge_frames(rig: _Rig) -> list[str]:
    types = rig.sent_types()
    return [name for name in types if name in ("response.cancel", "conversation.item.truncate")]


def test_mark1_r4a_the_shipped_floor_of_zero_is_todays_barge_in_to_the_frame() -> None:
    """Pre-registered R4a. The knob ships OFF and OFF means R16, unchanged."""

    omitted = _Rig(BURST, 1.0)
    explicit = _Rig(BURST, 1.0, backchannel_floor_ms=0.0)
    omitted.run()
    explicit.run()

    assert omitted.sent_types() == explicit.sent_types()
    assert omitted.truncates() == explicit.truncates()
    assert _barge_frames(omitted) == ["response.cancel", "conversation.item.truncate"]
    # Nothing was ever held: the cancel left on the frame that caused it.
    assert omitted.lane.backchannel_holds == 0
    assert omitted.lane.barge_ins_committed == 1
    assert omitted.lane.backchannels_survived == 0
    assert omitted.sink.interrupts == 1


def test_mark1_r4b_a_burst_that_ends_inside_the_floor_never_cancels_anything() -> None:
    """Pre-registered R4b: 'mm-hmm' does not stop the dog mid-sentence."""

    rig = _Rig(BURST, 1.0, backchannel_floor_ms=700.0, speech_stopped_at=1.35)
    rig.lane.open_session(handshake_token="csrf-token", mic_gesture=True)
    rig.server.pump()
    rig.lane.pump()
    rig.browser.drain()
    timeline = rig._timeline()
    moments = sorted({at for at, _kind in timeline} | _grid(2.60, 0.05))
    pending = list(timeline)
    heard_at_barge = 0.0
    for moment in moments:
        rig._advance_to(moment)
        while pending and pending[0][0] <= moment + 1e-9:
            _at, kind = pending.pop(0)
            rig.lane.send_audio(pcm_tone(20, seed=3))
            rig.server.pump()
            rig.lane.pump()
            if kind == "speech_started":
                heard_at_barge = rig.browser.context.rendered_ms()
        rig.lane.pump()
        rig.browser.drain()

    assert _barge_frames(rig) == [], "a backchannel must not cancel or truncate anything"
    assert rig.sink.interrupts == 0, "the sink was never taken from the reply"
    assert rig.lane.backchannel_holds == 1
    assert rig.lane.backchannels_survived == 1
    assert rig.lane.barge_ins_committed == 0
    assert rig.survived()
    # ...and the owner went on hearing the reply they were agreeing with.
    assert rig.browser.context.rendered_ms() > heard_at_barge + 900.0


def test_mark1_r4c_a_burst_past_the_floor_commits_once_at_what_was_heard_then() -> None:
    """Pre-registered R4c: a real interruption still interrupts, one floor late."""

    floor_ms = 350.0
    rig = _Rig(BURST, 1.0, backchannel_floor_ms=floor_ms, speech_stopped_at=1.90)
    row = rig.run(tail_s=1.20)

    assert _barge_frames(rig) == ["response.cancel", "conversation.item.truncate"]
    assert rig.lane.backchannel_holds == 1
    assert rig.lane.barge_ins_committed == 1
    assert rig.lane.backchannels_survived == 0
    assert rig.sink.interrupts == 1
    # The mark is what was heard AT COMMIT, not at speech-start: the owner spent
    # the whole floor listening to the reply and the provider must be told so.
    heard_at_barge_ms = 1_000.0 - 20.0  # playback began 20 ms after the first chunk
    assert row.audio_end_ms > heard_at_barge_ms + floor_ms - 60.0
    assert row.error_ms <= 150.0, f"the held mark must be as honest as the immediate one: {row}"


def test_mark1_r4d_backchannel_survival_is_reported_over_the_fixture_set() -> None:
    """Pre-registered R4d: report the number; DUPLEX-1 sets the bar it must clear.

    The matrix is the point. Survival is not a property of the floor alone: the
    lane cannot know the owner stopped until the ENDPOINTER says so, and server
    VAD only says so after its silence tail. So a floor only ever buys
    survival while ``floor > burst + tail`` — which makes TURN-1's
    ``silence_duration_ms`` a prerequisite for this feature and not a
    neighbouring nicety.
    """

    floors = (0.0, 250.0, 350.0, 450.0, 700.0, 1000.0)
    bursts = (0.15, 0.30)  # "mm-hmm"; "yeah, okay"
    tails = (0.20, 0.50)  # TURN-1's tunable minimum; the provider's default
    lines = ["", "[MARK-1 R4d] backchannel survival — floor_ms × (burst, VAD tail)"]
    survived_total = 0
    trials = 0
    for burst in bursts:
        for tail in tails:
            row = []
            for floor in floors:
                rig = _Rig(
                    BURST,
                    1.0,
                    backchannel_floor_ms=floor,
                    speech_stopped_at=1.0 + burst + tail,
                )
                rig.drive(tail_s=max(1.4, floor / 1000.0 + 0.4))
                survived = rig.survived()
                trials += 1
                survived_total += int(survived)
                row.append("yes" if survived else " . ")
                # The classifier must agree with the arithmetic it implements.
                # <=, not <: a burst whose endpoint lands exactly ON the
                # deadline is seen by the resolver in the same pump pass that
                # would have committed it, and the earlier branch wins.
                assert survived == ((burst + tail) * 1000.0 <= floor), (
                    f"floor={floor} burst={burst} tail={tail} survived={survived}"
                )
            lines.append(
                f"    burst={burst * 1000:>4.0f} ms tail={tail * 1000:>4.0f} ms  "
                + "  ".join(f"{f:>6.0f}:{cell}" for f, cell in zip(floors, row, strict=True))
            )
    lines.append(
        f"    survival over the whole matrix: {survived_total}/{trials} "
        f"({survived_total / trials:.2f}) — DUPLEX-1 sets the >= 0.9 bar"
    )
    print("\n".join(lines))
    assert trials == len(floors) * len(bursts) * len(tails)


def test_a_real_interruption_is_never_mistaken_for_a_backchannel_at_any_floor() -> None:
    """The floor buys backchannel survival. It must not cost an interruption."""

    for floor in (250.0, 450.0, 700.0):
        rig = _Rig(BURST, 1.0, backchannel_floor_ms=floor, speech_stopped_at=2.60)
        row = rig.run(tail_s=1.8)
        assert _barge_frames(rig) == ["response.cancel", "conversation.item.truncate"]
        assert rig.lane.barge_ins_committed == 1, f"floor={floor} swallowed a real interruption"
        assert row.audio_end_ms > 0


def test_a_reply_that_ends_while_the_hold_is_open_is_not_retro_cancelled() -> None:
    """The other way out of a hold: nothing left to interrupt."""

    # Barge in while the tail of the reply is still playing, and let the
    # provider close the response before the floor expires.
    rig = _Rig(BURST, 3.10, backchannel_floor_ms=700.0, finish_at=3.30)
    rig.drive(tail_s=1.4)
    assert _barge_frames(rig) == []
    assert rig.lane.backchannel_holds == 1
    assert rig.lane.barge_ins_committed == 0
    assert rig.sink.interrupts == 0


def test_a_provider_side_cancel_during_the_hold_is_committed_not_counted_survived() -> None:
    """Correction pass, defect 2 — and its seeded RED.

    ``turn_detection.interrupt_response`` defaults to TRUE on the hosted lane,
    so a genuine interruption during the floor is cancelled by the PROVIDER
    before the floor expires: ``response.done`` arrives with
    ``status: "cancelled"``. Read as "the reply finished", that is a survived
    backchannel — nothing interrupts the sink, so the owner is talked over by
    the seconds already scheduled in the browser, and nothing truncates the
    item, so the provider still believes it said the whole thing. Exactly the
    defect this card removes, reintroduced by the feature meant to soften it.

    Seed: drop the ``_response_was_cancelled`` branch and this goes RED.
    """

    rig = _Rig(
        BURST,
        1.0,
        backchannel_floor_ms=700.0,
        provider_cancel_at=1.15,  # inside the floor, as interrupt_response does
    )
    row = rig.run(tail_s=1.2)

    assert rig.lane.backchannel_holds == 1
    assert rig.lane.backchannels_survived == 0, "a provider cancel is not a backchannel"
    assert rig.lane.barge_ins_committed == 1
    assert rig.sink.interrupts == 1, "the browser's own buffer must still be stopped"
    # The mark is sent; the cancel is not, because the provider already sent it.
    assert _barge_frames(rig) == ["conversation.item.truncate"]
    assert row.audio_end_ms > 0
    assert row.error_ms <= 150.0, f"a provider-cancelled mark must be as honest: {row}"


def test_a_reply_that_completes_normally_inside_the_hold_is_still_a_backchannel() -> None:
    """The other half of the same branch: ``completed`` is not ``cancelled``."""

    rig = _Rig(BURST, 3.10, backchannel_floor_ms=700.0, finish_at=3.30)
    rig.drive(tail_s=1.4)
    assert _barge_frames(rig) == []
    assert rig.lane.backchannels_survived == 1
    assert rig.lane.barge_ins_committed == 0
    assert rig.sink.interrupts == 0


# ================== correction pass, defect 3: the socket may run ahead of the tab
#: The two fixtures whose schedule actually runs dry, plus a socket that sits
#: 350 ms behind the gateway. This is the case ``enqueued_ms`` does NOT bound:
#: the lane believes 350 ms more audio is playing than the browser has even
#: scheduled, so a stall extrapolated on the wall clock has nothing to stop it.
LAG_FIXTURES = (FIXTURES[2], FIXTURES[3])
SOCKET_LAG_S = 0.35


def _lag_sweep(ack_mode: str) -> list[_Row]:
    rows: list[_Row] = []
    for fixture in LAG_FIXTURES:
        for barge_at in fixture.barge_at:
            rows.append(
                _Rig(fixture, barge_at, ack_mode=ack_mode, socket_lag_s=SOCKET_LAG_S).run()
            )
    return rows


def test_the_drained_ack_stops_the_played_clock_running_through_a_stall() -> None:
    """Correction pass, defect 3 — and its seeded RED.

    The timer only reports WHILE audio is rendering, so it goes quiet at exactly
    the moment the audio clock and the wall clock diverge. With the socket ahead
    of the tab the ``enqueued_ms`` clamp no longer covers for that, and the mark
    walks forward through silence. One ack on the drain edge, and a gateway that
    stops extrapolating when it sees one, is the whole fix.

    Reported, not folded into R1/R2: the pre-registered sweep is the 24 rows it
    was pre-registered on and its numbers are unchanged.
    """

    fixed = _lag_sweep("continuous")
    control = _lag_sweep("continuous_no_drain")
    fixed_errors = [row.error_ms for row in fixed]
    control_errors = [row.error_ms for row in control]
    print(
        f"\n[correction pass, defect 3] socket {SOCKET_LAG_S * 1000:.0f} ms behind the gateway, "
        f"n={len(fixed)}"
        f"\n    no drain ack (MARK-1 as first written): p50={_p(control_errors, 0.5):.1f}ms "
        f"p95={_p(control_errors, 0.95):.1f}ms max={max(control_errors):.1f}ms"
        f"\n    with the drain ack:                     p50={_p(fixed_errors, 0.5):.1f}ms "
        f"p95={_p(fixed_errors, 0.95):.1f}ms max={max(fixed_errors):.1f}ms"
    )
    assert max(control_errors) > 150.0, "the control must still show the defect"
    assert max(fixed_errors) < max(control_errors), "the drain ack must move the needle"

    # The residual is NOT the stall any more; it is the lag itself. Split the
    # rows on whether the browser had managed to say anything at all yet.
    acked = [row.error_ms for row in fixed if row.acks_at_truncate > 0]
    unacked = [row for row in fixed if row.acks_at_truncate == 0]
    print(
        f"    once ANY ack has landed (n={len(acked)}):        "
        f"p50={_p(acked, 0.5):.1f}ms p95={_p(acked, 0.95):.1f}ms max={max(acked):.1f}ms"
        f"\n    before the first ack arrives (n={len(unacked)}): the lane's first-enqueue "
        f"fallback overstates by up to the lag itself "
        f"({max((r.error_ms for r in unacked), default=0.0):.0f} ms measured, "
        f"bound {SOCKET_LAG_S * 1000:.0f} ms)"
    )
    assert _p(acked, 0.95) <= 150.0, "with an ack in hand the mark must be honest"
    assert all(row.error_ms <= SOCKET_LAG_S * 1000.0 + 5.0 for row in unacked), (
        "the first-enqueue fallback must never overstate by more than the lag"
    )
    worse = [
        (f.fixture, f.barge_at, f.error_ms, c.error_ms)
        for f, c in zip(fixed, control, strict=True)
        if f.error_ms > c.error_ms + 1e-6
    ]
    assert not worse, f"the drain ack must never be worse than not sending it: {worse}"


def test_a_drained_ack_freezes_the_anchor_and_an_ordinary_one_lifts_it() -> None:
    """The gateway half on its own, with no browser in the way."""

    class _C:
        def __init__(self) -> None:
            self.now = 1_000.0

        def __call__(self) -> float:
            return self.now

    clock = _C()
    gateway = BrowserAudioGateway(on_audio=lambda _p: None, clock=clock)
    gateway.bind_token("t")
    gateway.start()
    gateway.attach("t")
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 48_000)  # 1 000 ms transmitted
    clock.now += 0.4
    assert gateway.ack_played(1, 400.0, True) is True
    anchor = gateway.played_started_monotonic
    assert anchor is not None
    assert clock.now - anchor == pytest.approx(0.400, abs=1e-6)

    # Two seconds of silence later, the owner has still heard 400 ms.
    clock.now += 2.0
    frozen = gateway.played_started_monotonic
    assert frozen is not None
    assert clock.now - frozen == pytest.approx(0.400, abs=1e-6)
    assert gateway.snapshot()["drained_acks"] == 1
    assert gateway.snapshot()["playback_drained_ms"] == pytest.approx(400.0)

    # Audio resumes; the very frame that proves it lifts the freeze.
    assert gateway.ack_played(1, 450.0, False) is True
    clock.now += 0.1
    live = gateway.played_started_monotonic
    assert live is not None
    assert clock.now - live == pytest.approx(0.550, abs=1e-6)
    assert gateway.snapshot()["playback_drained_ms"] is None


# ============ correction pass, defect 4: a hold belongs to one socket and one reply
def _rig_with_an_open_hold() -> _Rig:
    """Drive until a provisional barge-in is open and not yet settled."""

    rig = _Rig(BURST, 1.0, backchannel_floor_ms=5_000.0)
    rig.drive(tail_s=0.10)
    assert rig.lane.backchannel_holds == 1
    assert rig.lane._barge_in_hold is not None, "the fixture must leave a hold open"
    return rig


def test_a_hold_does_not_survive_the_hang_up_that_ends_its_reply() -> None:
    """Correction pass, defect 4 (``close``), and its seeded RED."""

    rig = _rig_with_an_open_hold()
    rig.lane.close()
    assert rig.lane._barge_in_hold is None
    rig.lane.pump()
    assert rig.lane.backchannels_survived == 0, "a hung-up session is not a 'mm-hmm'"
    assert rig.lane.barge_ins_committed == 0


def test_a_hold_does_not_survive_the_reconnect_that_replaces_its_socket() -> None:
    """Correction pass, defect 4 (``_connect``), and its seeded RED.

    ``_connect`` is the product's own reconnect path — it is what
    ``_on_disconnect`` calls — and it builds a fresh ``_ResponseState``. A hold
    carried past it names a response id from a conversation that no longer
    exists, so the next pump settles it against whatever is playing now.
    """

    rig = _rig_with_an_open_hold()
    rig.lane._connect()
    assert rig.lane._barge_in_hold is None
    rig.lane.pump()
    assert rig.lane.backchannels_survived == 0
    assert rig.lane.barge_ins_committed == 0
    assert _barge_frames(rig) == [], "nothing may be cancelled on the new socket"


# ============ correction pass, defect 6a: which client the monotonic guard is for
def test_the_monotonic_guard_is_for_the_client_this_card_replaces() -> None:
    """The measured fact behind D-8, so the deviation is not an assertion.

    MARK-1's pre-registration named a seed for the monotonic ack guard —
    "remove it and the underrun fixture truncates at ~0 ms". It could not have
    fired: MARK-1's own client reports a position that never walks backwards, so
    the guard is almost never reached on the continuous sweep. The client it is
    actually for is the one that SHIPPED, whose playback origin is re-stamped on
    every underrun; there the guard is worth ~130 ms of mean error.

    None of that makes the guard optional — a stale cached tab is exactly the
    old client — but it does make the pre-registered seed wrong about where the
    guard lives, and this is the measurement that says so.
    """

    continuous = _sweep("continuous")
    shipped = _sweep("arrival")
    continuous_regressive = sum(row.regressive_acks for row in continuous)
    shipped_regressive = sum(row.regressive_acks for row in shipped)
    print(
        f"\n[correction pass, D-8] regressive acks refused over the 24-fixture sweep: "
        f"MARK-1 client={continuous_regressive}, shipped client={shipped_regressive}"
    )
    assert shipped_regressive > continuous_regressive, (
        "the guard exists for the client this card replaces"
    )
    # The point of D-8: MARK-1's own client does not NEED the guard to be
    # accurate. Its regressions are the ~20 ms scheduling lead-in after an
    # underrun resumes, and its mark is 1 ms honest with or without them.
    errors = [row.error_ms for row in continuous]
    assert _p(errors, 0.95) <= 150.0
    assert max(errors) <= 5.0, "the corrected client's accuracy does not rest on the guard"

