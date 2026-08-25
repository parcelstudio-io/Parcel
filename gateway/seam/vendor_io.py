"""Bounded vendor I/O — a vendor call that never returns is a fault, not a wedge.

``gateway/writer.py`` already isolates ``Move`` on its own thread, because a
``Move`` that applies and never replies (GWF-009) was a known seed.  The other
two vendor calls were not isolated: ``gateway/core.py``'s ``_safe_stop_move``
and ``_safe_sample`` called ``stop_move()`` / ``state()`` **synchronously,
under the core ``RLock``**, including inside ``_stop_and_witness_locked``'s
retry/settle loop.  Against a vendor that *raises* or *returns False* that is
fine — the M1-0 corpus proved it.  Against a vendor that simply never returns
it is not: the calling thread never comes back, so the core lock is never
released, the watchdog's next ``tick()`` blocks on that lock forever, and an
independent explicit stop blocks with it.  That is the hole this module closes
(``ROBOT_READY_PLAN.md`` §3 A1, §4 work item 4).

**The pattern is ``writer.py``'s, generalised.**  One dedicated daemon thread
per call kind, one call in flight at a time, and a caller that waits with a
deadline instead of waiting forever.  When the deadline passes the caller gets
a *typed timeout* and walks away; the vendor call stays blocked on its own
thread, which is exactly what a hung vendor is, and the thread is a daemon so
it cannot hold the process open either.

**Two lanes, not one.**  ``state`` and ``stop_move`` get separate threads on
purpose: a hung ``state()`` must not stand between the gateway and its ability
to *issue* a ``StopMove``.  Sharing one lane would make the most dangerous
fault (feedback hangs) also disable the remedy (stop).

**One call in flight, never a queue.**  If a lane is already blocked, a second
caller does not enqueue a second vendor call — the vendor keeps exactly one
caller at a time, the same discipline ``writer.py`` gives ``Move``.  The second
caller waits for what is left of the in-flight call's *own* budget and then
reports a timeout; a call already past its budget is reported immediately, so a
polling loop against a wedged vendor stays a polling loop instead of costing a
full budget per poll.

Be precise about what that does and does not promise.  A vendor call that
returns **inside** its budget is never lost — whichever caller is waiting when
it lands gets its answer.  A call that **overruns** its budget is classified as
a failure by the caller that asked for it, and a later caller starts a fresh
call rather than adopting the stale one.  That is deliberate: for ``state()``
an old answer is not fresh evidence, and for ``stop_move()`` a retry is exactly
what the stop path wants.  A vendor whose stop RPC habitually takes longer than
``stop_retry_s`` therefore reads as a *failed* stop — unconfirmed, retried and
latched — which is the safe direction to be wrong in.

**Lock ordering.**  This module's condition variable is a **leaf**.  The lane
thread takes it and nothing else; the lane's callable runs with **no lock held
at all**; the lane never calls back into ``gateway.core`` (no observers, no
audit, no notifications).  Callers hold the core ``RLock`` when they invoke a
lane, so the order is always ``core.RLock`` → ``lane condition``, never the
reverse, and there is no cycle to deadlock on.  Nothing else in the gateway
takes two locks.

**Real time, deliberately.**  The lane budgets and its in-flight age come from
``time.monotonic`` directly, not from the core's injectable ``clock``.  A
virtual clock can model a deadline; it cannot bound a real blocked thread, and
this module's whole job is bounding real blocked threads.

**What it does not do.**  It does not cancel the vendor call — nothing in
CPython can — and it does not make the gateway's stop path instantaneous.  The
guarantee is a *bound*: with a permanently hung ``state()`` and a permanently
hung ``stop_move()``, one stop still completes inside ``stop_timeout_s``,
reports ``stationary_confirmed=False``, and latches, and the core lock is free
again afterwards.  Before this module that same fault held the lock forever.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..ports import SportPort, read_sport_sample


@dataclass(frozen=True)
class BoundedCallOutcomeV1:
    """One attempt to reach a call that may never return.

    Exactly one of ``completed`` / ``timed_out`` is true.  ``error`` is the
    exception the call raised, if it raised; a completed call with no error
    carries the vendor's answer in ``value``.
    """

    completed: bool
    timed_out: bool
    value: object
    error: BaseException | None
    waited_s: float
    in_flight_s: float

    @property
    def ok(self) -> bool:
        return self.completed and self.error is None


class BoundedCallLaneV1:
    """One call kind, one thread, one call in flight, a bounded caller wait."""

    def __init__(
        self,
        name: str,
        call: Callable[[object], object],
        *,
        idle_poll_s: float = 0.05,
    ) -> None:
        self._name = name
        self._call = call
        self._idle_poll_s = idle_poll_s
        self._cond = threading.Condition(threading.Lock())
        self._requested = 0
        self._completed = 0
        self._pending: tuple[int, object] | None = None
        self._result: tuple[object, BaseException | None] = (None, None)
        self._in_flight_since: float | None = None
        self._closed = False
        self._calls = 0
        self._timeouts = 0
        self._failures = 0
        self._thread = threading.Thread(
            target=self._run,
            name=f"parcel-gateway-lane-{name}",
            daemon=True,
        )
        self._thread.start()

    @property
    def name(self) -> str:
        return self._name

    @property
    def calls(self) -> int:
        with self._cond:
            return self._calls

    @property
    def timeouts(self) -> int:
        with self._cond:
            return self._timeouts

    @property
    def failures(self) -> int:
        with self._cond:
            return self._failures

    @property
    def call_in_flight(self) -> bool:
        """True while the vendor is holding this lane's thread."""

        with self._cond:
            return self._in_flight_since is not None

    def in_flight_age_s(self) -> float:
        with self._cond:
            return self._in_flight_age_locked()

    def invoke(self, payload: object, timeout_s: float) -> BoundedCallOutcomeV1:
        """Reach the vendor, or give up on time. Never blocks past the budget."""

        started_at = time.monotonic()
        budget = max(0.0, float(timeout_s))
        with self._cond:
            if self._closed:
                return BoundedCallOutcomeV1(
                    completed=False,
                    timed_out=True,
                    value=None,
                    error=None,
                    waited_s=0.0,
                    in_flight_s=self._in_flight_age_locked(),
                )
            if self._in_flight_since is None and self._pending is None:
                self._requested += 1
                self._pending = (self._requested, payload)
                wait_until = started_at + budget
                self._cond.notify_all()
            else:
                # Already out there.  Wait only for the remainder of the
                # in-flight call's own budget — an overdue call returns a
                # timeout immediately rather than costing another full budget.
                since = self._in_flight_since
                wait_until = (started_at if since is None else since) + budget
            target = self._requested
            while self._completed < target:
                remaining = wait_until - time.monotonic()
                if remaining <= 0.0:
                    self._timeouts += 1
                    return BoundedCallOutcomeV1(
                        completed=False,
                        timed_out=True,
                        value=None,
                        error=None,
                        waited_s=time.monotonic() - started_at,
                        in_flight_s=self._in_flight_age_locked(),
                    )
                self._cond.wait(remaining)
            value, error = self._result
            return BoundedCallOutcomeV1(
                completed=True,
                timed_out=False,
                value=value,
                error=error,
                waited_s=time.monotonic() - started_at,
                in_flight_s=self._in_flight_age_locked(),
            )

    def close(self, *, join_timeout_s: float = 0.5) -> None:
        """Ask the lane to stop. The join is bounded; a hung call keeps its thread.

        The thread is a daemon for exactly that reason: a vendor call that
        never returns must not be able to hold the process open at shutdown,
        and the stop path never ran on it.
        """

        with self._cond:
            self._closed = True
            self._pending = None
            self._cond.notify_all()
        self._thread.join(timeout=join_timeout_s)

    def _in_flight_age_locked(self) -> float:
        since = self._in_flight_since
        if since is None:
            return 0.0
        return max(0.0, time.monotonic() - since)

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._pending is None and not self._closed:
                    self._cond.wait(self._idle_poll_s)
                if self._pending is None:
                    if self._closed:
                        return
                    continue
                generation, payload = self._pending
                self._pending = None
                self._in_flight_since = time.monotonic()
                self._calls += 1
            value: object = None
            error: BaseException | None = None
            try:
                value = self._call(payload)
            except BaseException as caught:
                # The vendor is a fault boundary — same idiom as
                # ``gateway/writer.py`` and ``gateway/core.py``.  An ``Exception``
                # is evidence and is handed back to the caller.  Interpreter
                # shutdown is not a vendor fault: it is published for the caller
                # to re-raise on its own thread, the lane is closed so nobody
                # waits on a thread that is about to die, and it leaves here.
                if not isinstance(caught, Exception):
                    self._publish(generation, None, caught, close=True)
                    raise
                error = caught
            self._publish(generation, value, error, close=False)

    def _publish(
        self,
        generation: int,
        value: object,
        error: BaseException | None,
        *,
        close: bool,
    ) -> None:
        with self._cond:
            self._result = (value, error)
            self._completed = generation
            self._in_flight_since = None
            if error is not None:
                self._failures += 1
            if close:
                self._closed = True
            self._cond.notify_all()


class VendorIoSeamV1:
    """The gateway's synchronous vendor surface — ``state`` and ``stop_move``.

    ``Move`` is deliberately absent: it already has its own isolated writer
    thread (:mod:`gateway.writer`) with the stop-epoch and deadline gates on
    it, and moving it here would take those gates away.
    """

    def __init__(self, sport: SportPort) -> None:
        self._sport = sport
        self.state_lane = BoundedCallLaneV1(
            "vendor-state",
            lambda _payload: read_sport_sample(sport),
        )
        self.stop_lane = BoundedCallLaneV1(
            "vendor-stop",
            lambda reason: bool(sport.stop_move(reason=str(reason))),
        )

    def sample(self, timeout_s: float) -> BoundedCallOutcomeV1:
        return self.state_lane.invoke(None, timeout_s)

    def stop_move(self, reason: str, timeout_s: float) -> BoundedCallOutcomeV1:
        return self.stop_lane.invoke(reason, timeout_s)

    def close(self, *, join_timeout_s: float = 0.5) -> None:
        self.state_lane.close(join_timeout_s=join_timeout_s)
        self.stop_lane.close(join_timeout_s=join_timeout_s)
