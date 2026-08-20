"""The thing that actually turns the crank on a lane (card R1.6+R3, task_6).

WHY THIS EXISTS
---------------
``RealtimeLane`` is deliberately passive. It has ``pump()`` (drain and dispatch
every pending server frame) and ``tick()`` (watchdog + 60-minute rollover), and
through R2 nothing in the product ever called either of them: the tests drove
the lane by hand and the runtime constructed it and walked away. A hosted
session with nobody pumping is a session that never speaks, never notices a
stall, and never rolls over.

This is that caller, and it is deliberately the smallest possible one:

* one daemon thread, one loop, ``pump()`` then ``tick()``;
* the sleep and the clock are injected, so the offline test advances time by
  hand and asserts the cadence instead of waiting for it;
* ``instructions.refresh(lane)`` runs immediately BEFORE ``tick()``, which is
  the whole DI-at-boundaries mechanism (R2-C's handoff, one line): ``tick()`` is
  the only place a rollover can start, and ``_connect()`` reads
  ``lane.instructions`` when it does. Refreshing anywhere else would either miss
  the boundary or rewrite the prompt mid-session and bust the provider's cache.

WHAT IT REFUSES TO DO
---------------------
It never opens or closes a session — arming is the owner's act and belongs to
whoever holds the handshake token. It never touches the sink, the ledger or the
broker. If the loop body raises, the driver records the failure, counts it, and
keeps going: a driver that died on one bad frame would silently take the whole
conversation with it, which is precisely the failure the watchdog exists for.

IT DOES, HOWEVER, STOP TURNING A CRANK THAT IS ATTACHED TO NOTHING (card R16)
----------------------------------------------------------------------------
``tick()`` gained a fourth answer: the lane HUNG UP because nobody was talking
to it. That is not a reconnect — there is no new session — and a loop that kept
waking twenty times a second to pump a transport that is ``None`` would be pure
noise for however long the owner is away. So a reason in :attr:`stop_reasons`
ends the loop, and the driver goes back to exactly the state it was in before
``start()``: stopped, restartable, and restarted by the same one line in the
runtime that starts it on the owner's first gesture. Which reason means that is
a STRING and not a subclass check, because the lane and the driver are joined
by a Protocol here on purpose.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol

#: How often the loop wakes. 20 Hz is far below the audio frame rate and far
#: above human turn-taking; the lane coalesces audio itself, so this is a
#: liveness cadence rather than a latency budget.
DEFAULT_INTERVAL_S = 0.05

#: Card R16. Lane ``tick()`` answers that end the loop rather than being noted.
#: One entry, and it is ``lane.REASON_IDLE_HANG_UP`` — asserted equal by test, so
#: the two modules cannot drift apart without a red gate. Stated as a string set
#: (and injectable) so this module keeps its promise of touching exactly three
#: lane members and knowing nothing else about the class.
DEFAULT_STOP_REASONS = frozenset({"idle"})


class PumpableLane(Protocol):
    """The three lane members a driver is allowed to use."""

    @property
    def active(self) -> bool: ...

    def pump(self) -> int: ...

    def tick(self) -> str | None: ...


class InstructionRefresher(Protocol):
    """``InstructionSource``, as the driver sees it."""

    def refresh(self, lane: object) -> bool: ...


class RealtimeDriver:
    """Pump one lane on a cadence. Injectable clock and sleep; no globals."""

    def __init__(
        self,
        lane: PumpableLane,
        *,
        instructions: InstructionRefresher | None = None,
        interval_s: float = DEFAULT_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        on_event: Callable[[str], None] | None = None,
        stop_reasons: frozenset[str] | None = None,
    ) -> None:
        self._lane = lane
        self._instructions = instructions
        self._interval_s = max(0.0, float(interval_s))
        self._clock = clock
        self._sleep = sleep
        self._on_event = on_event
        self._stop_reasons = frozenset(
            DEFAULT_STOP_REASONS if stop_reasons is None else (str(r) for r in stop_reasons)
        )
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self.steps = 0
        self.frames = 0
        self.refreshes = 0
        self.reconnect_reasons: list[str] = []
        self.failures: list[str] = []
        self.started_at: float | None = None
        self.last_step_at: float | None = None
        #: Card R16. Why the loop stopped itself, and how many times it has. Kept
        #: OUT of ``reconnect_reasons``: an idle hang-up is the opposite of a
        #: reconnect, and folding it into that list would make the panel's
        #: "reconnects" count the sessions that were never re-opened.
        self.stopped_reason: str | None = None
        self.self_stops = 0

    # ------------------------------------------------------------- one step
    def step(self) -> int:
        """Drain, refresh the prompt plane, then tick. Returns frames handled.

        Order is load-bearing and is asserted by test: frames first (a
        ``session.created`` arriving in this batch resets the reconnect
        backoff before ``tick`` can consider another one), then the refresh,
        then ``tick`` — the only caller that can open a new session.
        """

        self.steps += 1
        self.last_step_at = self._clock()
        handled = 0
        try:
            handled = int(self._lane.pump())
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._fail(f"pump failed: {error}")
        self.frames += handled
        source = self._instructions
        if source is not None:
            try:
                if source.refresh(self._lane):
                    self.refreshes += 1
            except (RuntimeError, TypeError, ValueError) as error:
                # A prompt that will not render must not stop the conversation;
                # the lane keeps the last text it was given.
                self._fail(f"instruction refresh failed: {error}")
        try:
            reason = self._lane.tick()
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._fail(f"tick failed: {error}")
        else:
            if reason:
                self._on_reason(str(reason))
        return handled

    def _on_reason(self, reason: str) -> None:
        """One ``tick()`` answer. Either a reconnect to note, or the end of us."""

        if reason in self._stop_reasons:
            # Card R16. Set the flag rather than calling ``stop()``: ``stop()``
            # clears ``_thread``, and a loop that erased its own handle while
            # still inside its final sleep would look "not running" to a gesture
            # that then started a SECOND pump beside it. The loop re-reads this
            # flag at the top and exits; ``start()`` joins whatever is left.
            self.stopped_reason = reason
            self.self_stops += 1
            self._stop.set()
            self._note(
                f"realtime driver stopping: the lane closed itself ({reason}); "
                "the next owner gesture re-opens the session and starts a new pump"
            )
            return
        self.reconnect_reasons.append(reason)
        self._note(f"lane reconnected: {reason}")

    # ---------------------------------------------------------------- thread
    @property
    def running(self) -> bool:
        """Is there a pump, and is it still meant to be pumping?

        Card R16 adds the second half. A thread that has been told to stop but
        has not finished its last sleep is NOT running for the purpose the only
        caller has — ``runtime`` asks this to decide whether the owner's gesture
        needs to start a pump — and answering True for those few milliseconds
        would leave the freshly re-opened session with nobody turning its crank.
        """

        thread = self._thread
        return thread is not None and thread.is_alive() and not self._stop.is_set()

    def start(self) -> None:
        if self.running:
            return
        # Card R16. A previous loop may still be winding down (it stopped itself
        # on an idle hang-up and is inside its last sleep). Let it finish before
        # clearing the flag it is reading, or clearing it would revive that
        # thread and leave two pumps on one lane.
        previous = self._thread
        if previous is not None and previous is not threading.current_thread():
            previous.join(timeout=max(1.0, self._interval_s * 4.0))
        self._stop.clear()
        self.stopped_reason = None
        self.started_at = self._clock()
        thread = threading.Thread(target=self._loop, name="parcel-realtime-driver", daemon=True)
        self._thread = thread
        thread.start()
        self._note(f"realtime driver started at {1.0 / self._interval_s:.0f} Hz")

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout_s)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.step()
            if self._interval_s > 0.0:
                self._sleep(self._interval_s)

    # -------------------------------------------------------------- plumbing
    def _fail(self, message: str) -> None:
        self.failures.append(message)
        self._note(message)

    def _note(self, message: str) -> None:
        hook = self._on_event
        if hook is None:
            return
        try:
            hook(message)
        except (RuntimeError, TypeError, ValueError):  # pragma: no cover - defensive
            pass

    def snapshot(self) -> dict[str, object]:
        return {
            "running": self.running,
            "interval_s": self._interval_s,
            "steps": self.steps,
            "frames": self.frames,
            "instruction_refreshes": self.refreshes,
            "reconnects": list(self.reconnect_reasons),
            # Card R16. Why the pump is not running, when it is not.
            "stopped_reason": self.stopped_reason,
            "self_stops": self.self_stops,
            "failures": list(self.failures[-3:]),
        }


__all__ = [
    "DEFAULT_INTERVAL_S",
    "DEFAULT_STOP_REASONS",
    "InstructionRefresher",
    "PumpableLane",
    "RealtimeDriver",
]
