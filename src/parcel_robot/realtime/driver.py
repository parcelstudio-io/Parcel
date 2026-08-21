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
broker. If the loop body raises **anything that is not a ``BaseException``**,
the driver records the failure with its exception type, counts it, and keeps
going: a driver that died on one bad frame would silently take the whole
conversation with it, which is precisely the failure the watchdog exists for.

THE SENTENCE ABOVE USED TO BE FALSE, AND THAT IS CARD R22
---------------------------------------------------------
Until R22 this module said "records the failure and keeps going" while catching
exactly four types — ``OSError``, ``RuntimeError``, ``TypeError``,
``ValueError`` — around each of ``pump()``, ``refresh()`` and ``tick()``.
Anything else propagated out of :meth:`RealtimeDriver.step`, out of
:meth:`RealtimeDriver._loop`, and out of the thread, permanently and in
silence. The full-audit finding (AUDIT_FULL_FABLE §Safety-1, CONFIRMED, refuter
verified) named the exception that makes this the most dangerous defect in the
product:

    ``sqlite3.Error`` subclasses ``Exception`` **and none of those four**.

The conversation-ledger write is raw sqlite on this very thread
(``lane._write_ledger`` → ``memory.write_realtime_turn`` → ``INSERT``). A
disk-full, a locked database or a corrupted page mid-turn therefore killed the
pump, and with it the SPOKEN E-STOP relay, the stall watchdog, the 60-minute
rollover and the idle hang-up — while the microphone stayed open and nothing
anywhere alarmed. Three mechanisms close it, and the first is not enough on its
own:

1. **The firewall.** Every loop body catches ``Exception``. Never
   ``BaseException``: ``KeyboardInterrupt`` and ``SystemExit`` still end the
   thread, because a pump that ignored Ctrl-C would be its own incident.
2. **The alarm.** A pump that stops is LOUD. :attr:`alive` goes False,
   :attr:`death_reason` says why, the heartbeat age in :meth:`snapshot` says
   how long ago, and ``on_alarm`` fires a safety-class event the runtime turns
   into a safety-log row the panel renders beside the emergency-stop history.
   Silence is the defect; a ``failures`` entry nobody reads is silence.
3. **Revival, bounded.** Repeated failures restart the loop on a backoff
   ladder — counted, ledgered and capped at :attr:`max_revivals` — because
   mid-session there is no owner gesture coming to restart it by hand. Bounded
   because an unbounded revival against a genuinely broken lane is a hot loop
   that bills the provider and hides the fault.

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
from collections.abc import Callable, Mapping
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

#: Card R22. How many CONSECUTIVE failed steps mean the pump is sick rather than
#: unlucky. One bad frame is noise — the protocol refusal path already absorbs
#: those without ever reaching this counter. Three in a row at 20 Hz is 150 ms of
#: a lane that cannot complete a single pass, which is a fault and not a blip.
DEFAULT_REVIVE_AFTER = 3

#: Card R22. How many times the driver may restart its own loop before it
#: declares itself dead and waits for a gesture. Bounded on purpose: a lane
#: whose transport is genuinely gone will fail every step, and an unbounded
#: revival would spin on it forever while the alarm it should have raised never
#: fires. Five attempts across the backoff ladder below is ~15 s of trying.
DEFAULT_MAX_REVIVALS = 5

#: Card R22. First and largest wait between a sick loop and its replacement.
#: Deliberately the same exponential-with-cap shape as the lane's reconnect
#: ladder, and for the same reason: the failure that killed the step is very
#: often the failure that will kill the next one, and hammering it is how a
#: degraded provider becomes a bill.
DEFAULT_REVIVAL_BACKOFF_S = 0.5
DEFAULT_REVIVAL_BACKOFF_MAX_S = 8.0

#: Card R22. Alarm classes handed to ``on_alarm``. Strings and not an enum for
#: exactly the reason :data:`DEFAULT_STOP_REASONS` is a string set: the runtime
#: and the driver are joined by a callable here, not by a shared type.
ALARM_DIED = "pump_died"
ALARM_REVIVED = "pump_revived"

#: Card R22. How many failure lines are kept for the record. ``failure_count``
#: and ``failure_types`` stay exact; this only bounds the text. A pump failing
#: at 20 Hz would otherwise grow an unbounded list inside the process it is
#: meant to be protecting.
FAILURE_LOG_LIMIT = 200


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
        on_alarm: Callable[[str, str, Mapping[str, object]], None] | None = None,
        revive_after: int = DEFAULT_REVIVE_AFTER,
        max_revivals: int = DEFAULT_MAX_REVIVALS,
        revival_backoff_s: float = DEFAULT_REVIVAL_BACKOFF_S,
        revival_backoff_max_s: float = DEFAULT_REVIVAL_BACKOFF_MAX_S,
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
        #: Card R22. The death alarm's one wire out of this module. Called
        #: ``(alarm_class, message, detail)`` and never relied upon: a driver
        #: with no hook still records everything in :meth:`snapshot`, which is
        #: what makes the offline tests able to assert the alarm without a
        #: runtime. A hook that raises is swallowed — see :meth:`_alarm`.
        self._on_alarm = on_alarm
        self._revive_after = max(1, int(revive_after))
        self._max_revivals = max(0, int(max_revivals))
        self._revival_backoff_s = max(0.0, float(revival_backoff_s))
        self._revival_backoff_max_s = max(self._revival_backoff_s, float(revival_backoff_max_s))
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

        self.steps = 0
        self.frames = 0
        self.refreshes = 0
        self.reconnect_reasons: list[str] = []
        self.failures: list[str] = []
        #: Card R22. The exact totals, kept beside the bounded text log above.
        #: ``failure_types`` is the audit's own vocabulary — the finding was
        #: that ``sqlite3.OperationalError`` was invisible here, so the type
        #: name is recorded by name and counted, not flattened into prose.
        self.failure_count = 0
        self.failure_types: dict[str, int] = {}
        #: Failed steps since the last clean one. Reset by any clean step and by
        #: :meth:`start`; :data:`DEFAULT_REVIVE_AFTER` is what it is measured
        #: against.
        self.consecutive_failures = 0
        #: Card R22, work item 3. Loop restarts this driver performed for
        #: itself, what each of them waited, and why.
        self.revivals = 0
        self.revival_waits: list[float] = []
        self.revival_reasons: list[str] = []
        self.revivals_exhausted = False
        #: Card R22, work item 2. The pump stopped and NOBODY ASKED IT TO.
        #: ``deaths`` counts them across the process; ``death_reason`` and
        #: ``died_at`` describe the most recent one and stay set after a
        #: restart, because "it died at 14:02 and was restarted" is a fact an
        #: operator needs an hour later.
        self.deaths = 0
        self.death_reason: str | None = None
        self.died_at: float | None = None
        #: Card R22. The wires OUT of this class, when they break. Recorded
        #: because a driver whose note/alarm sinks both raise is a driver whose
        #: only remaining record is this object, and that fact should not
        #: itself be silent.
        self.note_failures = 0
        self.alarm_failures = 0
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

        **Card R22.** Each of the four calls below is firewalled against
        ``Exception`` rather than against a hand-written type list. The list is
        what let ``sqlite3.OperationalError`` out of ``pump()`` — the ledger
        write is downstream of ``_dispatch`` — and out of the thread. There is
        no type here whose escape is preferable to a counted failure: this
        method's entire job is to be called twenty times a second forever.

        ``BaseException`` is deliberately NOT caught. ``KeyboardInterrupt`` and
        ``SystemExit`` are instructions to stop, and a pump that swallowed them
        would be a worse bug than the one this card fixes.
        """

        self.steps += 1
        self.last_step_at = self._clock()
        handled = 0
        failed = False
        try:
            handled = int(self._lane.pump())
        except Exception as error:  # noqa: BLE001 - see the docstring above
            self._fail("pump", error)
            failed = True
        self.frames += handled
        source = self._instructions
        if source is not None:
            try:
                if source.refresh(self._lane):
                    self.refreshes += 1
            except Exception as error:  # noqa: BLE001
                # A prompt that will not render must not stop the conversation;
                # the lane keeps the last text it was given.
                self._fail("instruction refresh", error)
                failed = True
        try:
            reason = self._lane.tick()
        except Exception as error:  # noqa: BLE001
            self._fail("tick", error)
            failed = True
        else:
            if reason:
                try:
                    self._on_reason(str(reason))
                except Exception as error:  # noqa: BLE001
                    # The fourth call, and the one nobody thinks of: the reason
                    # handler notes, counts and can stop the loop, and it runs
                    # OUTSIDE the tick guard above by design (see the ordering
                    # note). Unguarded, an ``on_event`` sink that broke would
                    # kill the pump through the one path added to protect it.
                    self._fail("reason handling", error)
                    failed = True
        if failed:
            self.consecutive_failures += 1
        else:
            self.consecutive_failures = 0
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

    @property
    def alive(self) -> bool:
        """Is a pump thread ACTUALLY turning right now? Card R22, work item 2.

        Deliberately not the same question as :attr:`running`, and the gap
        between the two is the whole finding. ``running`` folds in intent — it
        answers "does the owner's next gesture need to start a pump", so it is
        False the moment ``stop()`` is called and stays False through the wind
        down. ``alive`` answers the operator's question instead: **is there a
        living thread on this lane**. A pump killed by an escaping exception is
        ``alive is False`` with ``stopped_reason is None`` and a
        :attr:`death_reason` that says what killed it, which is precisely the
        state that used to be indistinguishable from "healthy but quiet".

        Read with :meth:`heartbeat_age_s`: a thread can be alive and wedged
        inside a blocking call, and only the heartbeat says so.
        """

        thread = self._thread
        return thread is not None and thread.is_alive()

    def heartbeat_age_s(self) -> float | None:
        """Seconds since the pump last began a step, or ``None`` if it never has.

        The cadence is :data:`DEFAULT_INTERVAL_S`, so anything past a second is
        already several hundred missed passes. Never raises: an injected clock
        that misbehaves must not be able to break the health question.
        """

        last = self.last_step_at
        if last is None:
            return None
        try:
            now = float(self._clock())
        except Exception:  # noqa: BLE001 - a health probe never raises
            return None
        return max(0.0, now - float(last))

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
        # Card R22. An explicit start is a FRESH MANDATE: the revival budget and
        # the consecutive-failure streak both reset. Without this a driver that
        # exhausted its five revivals could never be revived again for the life
        # of the process, so the owner's gesture would buy one loop and no
        # resilience at all. ``deaths``/``death_reason`` deliberately do NOT
        # reset — they are the record, and the record outlives the restart.
        self.revivals = 0
        self.revivals_exhausted = False
        self.consecutive_failures = 0
        self.started_at = self._clock()
        thread = threading.Thread(target=self._loop, name="parcel-realtime-driver", daemon=True)
        self._thread = thread
        thread.start()
        # Card R22, incidental. This line was ``1.0 / self._interval_s`` with no
        # guard, so ``interval_s=0.0`` — a legal, documented value the
        # constructor clamps to and which means "never sleep" — raised
        # ZeroDivisionError out of ``start()`` AFTER the thread was already
        # running. The owner's gesture would have seen a traceback while a pump
        # it could not see was turning. Found by this card's own test and fixed
        # here because a start path that can raise is the same class of defect.
        cadence = "as fast as it can" if self._interval_s <= 0.0 else f"{1.0 / self._interval_s:.0f} Hz"
        self._note(f"realtime driver started at {cadence}")

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout_s)
        self._thread = None

    def _loop(self) -> None:
        """The pump thread. It leaves for exactly three reasons. Card R22.

        1. **It was told to** — ``stop()`` or an idle hang-up set ``_stop``.
           Quiet, expected, and the only silent exit there is.
        2. **It handed off to a replacement** — :meth:`_revive` started a fresh
           thread after :attr:`consecutive_failures` crossed the threshold. The
           alarm has already fired; this thread returns so there is never more
           than one pump on one lane.
        3. **Something got past the firewall** — which now means a
           ``BaseException`` or a broken ``_sleep``/``_revive``, because
           :meth:`step` cannot raise ``Exception`` any more. That is a DEATH and
           it alarms on the way out before the exception is re-raised.
        """

        try:
            while not self._stop.is_set():
                try:
                    self.step()
                except Exception as error:  # noqa: BLE001
                    # ``step()`` firewalls its own four calls, so reaching here
                    # means the scaffolding itself broke — the injected clock,
                    # the counters, ``int()`` on something exotic. This is the
                    # last thing standing between the pump and a silent death,
                    # so it catches broadly and counts the same way.
                    self._fail("step", error)
                    self.consecutive_failures += 1
                if self.consecutive_failures >= self._revive_after:
                    self._revive()
                    return
                if self._interval_s > 0.0:
                    self._sleep(self._interval_s)
        except BaseException as error:
            self._die(f"the pump thread raised {type(error).__name__}: {error}")
            raise

    # ------------------------------------------------------ revival and death
    def _revive(self) -> None:
        """Restart the loop after repeated failures. Card R22, work item 3.

        Called from inside the dying thread, which then returns: the new thread
        is started here and the old one ends one line later, so the invariant
        ``start()`` has always defended — one pump per lane — survives.

        Bounded. Past :attr:`max_revivals` this stops trying and calls
        :meth:`_die` instead, because a lane whose transport is genuinely gone
        fails every step and an unbounded ladder against it is a hot loop that
        bills the provider while the operator is told nothing new.
        """

        reason = (
            f"{self.consecutive_failures} consecutive failed steps "
            f"({self._failure_types_text() or 'no type recorded'})"
        )
        if self.revivals >= self._max_revivals:
            self.revivals_exhausted = True
            self._stop.set()
            self._die(
                f"revival exhausted after {self.revivals} attempt(s); the last "
                f"was {reason}"
            )
            return
        self.revivals += 1
        wait = min(
            self._revival_backoff_max_s,
            self._revival_backoff_s * (2.0 ** (self.revivals - 1)),
        )
        self.revival_waits.append(wait)
        self.revival_reasons.append(reason)
        self.consecutive_failures = 0
        self._alarm(
            ALARM_REVIVED,
            f"realtime pump revival {self.revivals}/{self._max_revivals} after "
            f"{reason}; restarting the loop in {wait:.2f}s",
            {
                "revivals": self.revivals,
                "max_revivals": self._max_revivals,
                "wait_s": round(wait, 3),
                "reason": reason,
                "failure_types": dict(self.failure_types),
            },
        )
        if wait > 0.0:
            self._sleep(wait)
        if self._stop.is_set():
            # Someone stopped us during the backoff. Starting a thread now would
            # be a pump nobody asked for on a session that may already be closed.
            return
        thread = threading.Thread(target=self._loop, name="parcel-realtime-driver", daemon=True)
        self._thread = thread
        thread.start()

    def _die(self, reason: str) -> None:
        """The pump has stopped and nobody asked it to. BE LOUD. Card R22.

        Three records, because one of them alone is what §Safety-1 called
        silence: the count and the reason on this object (so ``/api/state``
        shows it), the ordinary event note (so the panel's event ring shows
        it), and the ``on_alarm`` hook (so the runtime can write a SAFETY-class
        row that sits beside the emergency-stop history and is never evicted by
        chatter).

        ``_stop`` is set on the way out. A dead pump must not report
        ``running is True`` to the runtime, because ``running`` is exactly what
        the owner's next gesture consults before starting a replacement.
        """

        self.deaths += 1
        self.death_reason = reason
        try:
            self.died_at = float(self._clock())
        except Exception:  # noqa: BLE001 - a death record never raises
            self.died_at = None
        self._stop.set()
        self._alarm(
            ALARM_DIED,
            f"REALTIME PUMP DEAD: {reason}. The hosted lane is no longer being "
            "pumped: the spoken e-stop relay, the stall watchdog, the session "
            "rollover and the idle hang-up are all stopped until it restarts. "
            "The local emergency stop (panel, Space, typed) is unaffected.",
            {
                "reason": reason,
                "deaths": self.deaths,
                "steps": self.steps,
                "failure_count": self.failure_count,
                "failure_types": dict(self.failure_types),
                "revivals": self.revivals,
                "revivals_exhausted": self.revivals_exhausted,
            },
        )

    def ensure_alive(self) -> bool:
        """Supervisor entry point: is the pump still there, and alarm if not.

        Card R22. :meth:`_die` fires from inside the dying thread, which covers
        every death this module can see. This covers the ones it cannot — a
        thread killed by the interpreter, an ``on_alarm`` that itself brought
        the thread down, a ``_die`` that never ran. The runtime calls it from
        the service-health loop, so a pump that vanished without a word is still
        named within one health period.

        Returns True when a pump is turning (or when there is deliberately none:
        never started, stopped, or self-stopped on an idle hang-up). Returns
        False exactly once per undetected death, having alarmed.
        """

        if self._thread is None or self._stop.is_set():
            # Never started, stopped, self-stopped, or already dead and recorded
            # — all four are states somebody chose or has already been told about.
            return True
        if self.alive:
            return True
        self._die(
            "the pump thread is gone and left no reason; it was never told to "
            "stop and the lane was never closed"
        )
        return False

    # -------------------------------------------------------------- plumbing
    def _fail(self, where: str, error: BaseException) -> None:
        """Record one caught failure BY TYPE. Card R22, work item 1.

        The type name is the point. §Safety-1 is a story about a type that was
        not on a list, and a failure log that says only "pump failed: database
        is locked" leaves the next reader doing the MRO walk by hand.
        """

        name = type(error).__name__
        message = f"{where} failed: {name}: {error}"
        self.failure_count += 1
        self.failure_types[name] = self.failure_types.get(name, 0) + 1
        self.failures.append(message)
        if len(self.failures) > FAILURE_LOG_LIMIT:
            del self.failures[:-FAILURE_LOG_LIMIT]
        self._note(message)

    def _failure_types_text(self) -> str:
        return ", ".join(
            f"{name}x{count}" for name, count in sorted(self.failure_types.items())
        )

    def _note(self, message: str) -> None:
        hook = self._on_event
        if hook is None:
            return
        try:
            hook(message)
        except Exception:  # noqa: BLE001 - the note sink may never kill the pump
            # Counted rather than passed: a note sink that is broken makes every
            # OTHER record in this class the only one left, and an operator
            # reading a healthy-looking driver deserves to know the panel wire
            # is cut. Deliberately not re-noted — that is the same call again.
            self.note_failures += 1

    def _alarm(self, alarm: str, message: str, detail: Mapping[str, object]) -> None:
        """Note it, then raise it. Card R22, work item 2. Never raises."""

        self._note(message)
        hook = self._on_alarm
        if hook is None:
            return
        try:
            hook(alarm, message, dict(detail))
        except Exception:  # noqa: BLE001 - an alarm sink may never kill the pump
            # The alarm about the alarm. An ``on_alarm`` that raises inside a
            # dying pump thread would otherwise be a second, silent death.
            self.alarm_failures += 1

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
            # Card R22, work item 2. The death alarm, from outside. ``alive``
            # and ``running`` disagreeing is the shape of the incident: a
            # driver the runtime believes is pumping, with no thread under it.
            "alive": self.alive,
            "heartbeat_age_s": self.heartbeat_age_s(),
            "failure_count": self.failure_count,
            "failure_types": dict(self.failure_types),
            "consecutive_failures": self.consecutive_failures,
            "deaths": self.deaths,
            "death_reason": self.death_reason,
            "note_failures": self.note_failures,
            "alarm_failures": self.alarm_failures,
            # Card R22, work item 3.
            "revivals": self.revivals,
            "max_revivals": self._max_revivals,
            "revival_waits": list(self.revival_waits),
            "revivals_exhausted": self.revivals_exhausted,
        }


__all__ = [
    "ALARM_DIED",
    "ALARM_REVIVED",
    "DEFAULT_INTERVAL_S",
    "DEFAULT_MAX_REVIVALS",
    "DEFAULT_REVIVAL_BACKOFF_MAX_S",
    "DEFAULT_REVIVAL_BACKOFF_S",
    "DEFAULT_REVIVE_AFTER",
    "DEFAULT_STOP_REASONS",
    "FAILURE_LOG_LIMIT",
    "InstructionRefresher",
    "PumpableLane",
    "RealtimeDriver",
]
