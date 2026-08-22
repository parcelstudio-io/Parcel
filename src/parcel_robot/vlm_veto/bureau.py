"""The veto's bureau — a bounded worker, and verdicts that are published (NM-1).

What was wrong with the seam P1-D shipped
-----------------------------------------
P1-D wired the veto correctly and wired it **synchronously**:
``perception_abstention.resolve_veto`` handed the gate
``VetoRunner.veto_for``, so ``assess_place_query`` — which is on the mission
path, called from ``navigation.semantic_map.resolve`` and
``online_map.OnlineSemanticMap.resolve`` — ran a 41 ms GPU generation *inside
the grounding call*. The control-thread tripwire stops that happening on the
10 Hz loop, which is the worst case; it does not stop navigation blocking on a
model, and it cannot stop it, because a tripwire is a refusal and the caller
still wanted an answer.

DW-2's rule (``WAVE2_DESIGN_FABLE.md`` §1) is stronger and simpler:
**navigation never runs inference. It reads a verdict somebody else published,
or it asks.**

The shape
---------
* A :class:`VerdictBureau` owns one bounded worker thread and one bounded board.
* Navigation calls :meth:`VerdictBureau.read` — the callable
  ``resolve_veto`` installs. It **never blocks, never loads a model and never
  generates**. It looks the query up on the board and returns either the
  published answer or :data:`~parcel_robot.perception_abstention.VETO_UNAVAILABLE`,
  which the abstention gate already reads as ASK.
* A miss (or a stale or mismatched verdict) also *requests* a fresh judgement.
  The worker takes it, runs the seat off the caller's thread, and publishes.
* By the next time the owner asks, the verdict is usually there. The first
  question about a new place is answered with a question — which is exactly the
  posture the whole wave is built on.

What a published verdict must carry
-----------------------------------
A verdict that does not say *what it is about* is a verdict that will eventually
be applied to something else. :class:`PublishedVerdict` is frozen and carries,
immutably:

``query``           the noun that was asked about
``place_id``        which place
``place_revision``  a digest of the EVIDENCE the answer was computed against —
                    the label, the crop, the position, the counts. If the map
                    learns more about that place, the revision moves and the old
                    verdict stops matching. This is the field that makes
                    "verdict about a world that no longer exists" impossible
                    rather than unlikely.
``model``           which seat answered
``captured_at``     when the request was made
``resolved_at``     when the answer came back
``expires_at``      when it stops being usable at all

and navigation consumes it only when it is **ready** (an answer exists),
**matching** (query + place + revision) and **fresh** (not expired). Anything
else is an ASK.

Bounded, in three places
------------------------
The queue is bounded (:data:`DEFAULT_QUEUE_DEPTH`) and overflows by DROPPING and
counting, never by blocking a navigation call. The board is bounded
(:data:`DEFAULT_BOARD_DEPTH`) and evicts oldest-first. And each job is admitted
by the contention guard inside :meth:`VetoRunner.veto_for`, so a veto still
never starts while a safety lease is held for longer than its measured budget.
"""

from __future__ import annotations

import hashlib
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from parcel_robot.perception_abstention import (
    VETO_UNAVAILABLE,
    PlaceEvidence,
    in_control_thread,
)
from parcel_robot.vlm_veto.verifier import VetoAnswer

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_BOARD_DEPTH",
    "DEFAULT_QUEUE_DEPTH",
    "DEFAULT_RETRY_BACKOFF_S",
    "DEFAULT_VERDICT_TTL_S",
    "PublishedVerdict",
    "VerdictBureau",
    "bureau_for",
    "clear_bureaus",
    "place_revision",
]

#: How long a verdict about a place stays usable. A map entry's evidence moves on
#: the order of a visit, and a visit is minutes; two minutes is "the answer is
#: about the walk I am on". It is a ceiling, not the primary defence — the place
#: revision is, and it invalidates the instant the evidence actually changes.
DEFAULT_VERDICT_TTL_S = 120.0

#: How long an UNAVAILABLE answer (no seat, no crop, a declined GPU moment)
#: suppresses a re-request. Without it every resolve of a place the seat cannot
#: judge would enqueue another job and the worker would spin on it.
DEFAULT_RETRY_BACKOFF_S = 5.0

#: Jobs in flight. Small on purpose: a backlog of stale questions is worth less
#: than a short queue of current ones, and an overflow is DROPPED and counted
#: rather than allowed to block a navigation call.
DEFAULT_QUEUE_DEPTH = 32

#: Published verdicts kept. Oldest-first eviction; a robot that has seen 256
#: distinct (query, place) pairs since the last expiry is not being starved of
#: anything a bigger dict would fix.
DEFAULT_BOARD_DEPTH = 256


def place_revision(place: PlaceEvidence) -> str:
    """A digest of the evidence a verdict about ``place`` would be computed on.

    Deliberately derived rather than stored: ``PlaceEvidence`` is P1-D's frozen
    contract and belongs to the abstention gate, and a revision COUNTER would
    have to be maintained by every producer that builds one — the map, the
    oracle, ``place_evidence_from_mapping`` — which is the "a seam every caller
    must remember" defect ``resolve_veto`` was written to repair.

    What goes in is what the answer depends on: the label the place carries, the
    pixels the model would look at, where the place is, and how much evidence it
    has. What stays out is ``similarity`` — a ranking score with no absolute
    scale that moves with the *query*, not with the place.
    """

    crop = bytes(place.crop_png) if place.crop_png else b""
    parts = (
        str(place.label),
        f"{float(place.x):.3f}",
        f"{float(place.y):.3f}",
        f"{float(place.z):.3f}",
        str(int(place.label_support)),
        str(int(place.detection_count)),
        str(int(place.evidence_frames)),
        f"{float(place.ground_evidence_fraction):.4f}",
        hashlib.sha256(crop).hexdigest() if crop else "no-crop",
    )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class PublishedVerdict:
    """One answer, immutable, and unmistakable about what it is an answer to.

    Frozen because a verdict that can be edited after publication is a verdict
    whose identity fields are decoration. ``slots`` because there are a lot of
    them and they are cheap.
    """

    query: str
    place_id: str
    place_revision: str
    verdict: str
    model: str
    captured_at: float
    resolved_at: float
    expires_at: float
    p_yes: float | None = None
    latency_ms: float = 0.0
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.query:
            raise ValueError("a published verdict must name the query it answers")
        if not self.place_id:
            raise ValueError("a published verdict must name the place it is about")
        if not self.place_revision:
            raise ValueError("a published verdict must name the revision it saw")
        if self.expires_at < self.resolved_at:
            raise ValueError("a verdict cannot expire before it was resolved")

    def matches(self, query: str, place_id: str, revision: str) -> bool:
        """Is this verdict an answer to THIS question about THIS world?"""

        return (
            self.query == query
            and self.place_id == place_id
            and self.place_revision == revision
        )

    def fresh(self, now: float) -> bool:
        return now < self.expires_at

    @property
    def usable(self) -> bool:
        """An UNAVAILABLE verdict is a backoff marker, never an answer to use."""

        return self.verdict != VETO_UNAVAILABLE

    def as_answer(self) -> VetoAnswer:
        return VetoAnswer(
            self.verdict,
            p_yes=self.p_yes,
            latency_ms=self.latency_ms,
            model=self.model,
            detail=self.detail,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "place_id": self.place_id,
            "place_revision": self.place_revision,
            "verdict": self.verdict,
            "model": self.model,
            "captured_at": round(self.captured_at, 4),
            "resolved_at": round(self.resolved_at, 4),
            "expires_at": round(self.expires_at, 4),
            "p_yes": self.p_yes,
            "latency_ms": round(float(self.latency_ms), 3),
            "detail": self.detail,
        }


class VerdictBureau:
    """One bounded worker, one bounded board, and a reader that never blocks."""

    def __init__(
        self,
        runner: Any,
        *,
        ttl_s: float = DEFAULT_VERDICT_TTL_S,
        backoff_s: float = DEFAULT_RETRY_BACKOFF_S,
        queue_depth: int = DEFAULT_QUEUE_DEPTH,
        board_depth: int = DEFAULT_BOARD_DEPTH,
        clock: Callable[[], float] | None = None,
        autostart: bool = True,
    ) -> None:
        self._runner = runner
        self._ttl_s = float(ttl_s)
        self._backoff_s = float(backoff_s)
        self._board_depth = max(1, int(board_depth))
        self._clock = clock if clock is not None else time.monotonic
        self._autostart = bool(autostart)
        self._queue: queue.Queue[tuple[str, PlaceEvidence, str, float] | None] = (
            queue.Queue(maxsize=max(1, int(queue_depth)))
        )
        self._board: dict[tuple[str, str], PublishedVerdict] = {}
        self._inflight: set[tuple[str, str, str]] = set()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._stopping = False
        self._counts = {
            "read": 0,
            "hit": 0,
            "miss": 0,
            "stale": 0,
            "mismatched": 0,
            "unusable": 0,
            "requested": 0,
            "dropped": 0,
            "published": 0,
            "declined": 0,
            "worker_errors": 0,
        }

    # -- the seat's identity ------------------------------------------------

    @property
    def model(self) -> str:
        return str(getattr(getattr(self._runner, "verifier", None), "name", "") or "")

    @property
    def runner(self) -> Any:
        return self._runner

    def counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def _bump(self, key: str, delta: int = 1) -> None:
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + delta

    # -- the reader navigation actually calls -------------------------------

    def read(self, query: str, place: PlaceEvidence) -> VetoAnswer:
        """THE navigation-side entry point. Never blocks, never infers.

        Returns the published answer when one is ready, matching and fresh;
        otherwise :data:`VETO_UNAVAILABLE` — which ``assess_place_query`` reads
        as ASK — and requests one for next time.
        """

        self._bump("read")
        noun = " ".join(str(query).split())
        if not noun:
            return self._unavailable("a veto needs a noun")
        revision = place_revision(place)
        key = (noun, place.place_id)
        now = self._clock()
        with self._lock:
            published = self._board.get(key)
        if published is not None:
            if not published.fresh(now):
                self._bump("stale")
                self._request(noun, place, revision, now)
                return self._unavailable("verdict expired; a fresh one was requested")
            if not published.matches(noun, place.place_id, revision):
                self._bump("mismatched")
                self._request(noun, place, revision, now)
                return self._unavailable(
                    "the place changed since that verdict; a fresh one was requested"
                )
            if not published.usable:
                # A published UNAVAILABLE is a backoff marker: the seat has
                # already been asked and could not answer. Asking again inside
                # the backoff window would spin the worker on a question it has
                # just failed.
                self._bump("unusable")
                return self._unavailable(published.detail or "the seat could not answer")
            self._bump("hit")
            with self._lock:
                # Correction pass: eviction was oldest-INSERTED, so the place
                # the robot asks about every minute could be evicted by 256
                # one-off queries while a verdict nobody has read since the walk
                # began survived. Touching on read makes the board least-recently
                # USED, which is what "keep what is in play" means.
                if key in self._board:
                    self._board[key] = self._board.pop(key)
            return published.as_answer()
        self._bump("miss")
        self._request(noun, place, revision, now)
        return self._unavailable("no verdict published yet; one was requested")

    def veto_callable(self) -> Callable[[str, PlaceEvidence], VetoAnswer]:
        """Bind :meth:`read` for ``assess_place_query(veto=...)``."""

        return self.read

    @staticmethod
    def _unavailable(detail: str) -> VetoAnswer:
        return VetoAnswer(VETO_UNAVAILABLE, detail=detail)

    # -- the worker ---------------------------------------------------------

    def _request(
        self, query: str, place: PlaceEvidence, revision: str, now: float
    ) -> None:
        job_key = (query, place.place_id, revision)
        with self._lock:
            if job_key in self._inflight:
                return
            self._inflight.add(job_key)
        if self._autostart:
            self.start()
        try:
            self._queue.put_nowait((query, place, revision, now))
        except queue.Full:
            with self._lock:
                self._inflight.discard(job_key)
            self._bump("dropped")
            logger.debug("vlm_veto bureau: queue full; dropped %s/%s", query, place.place_id)
            return
        self._bump("requested")

    def start(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            if self._stopping:
                return
            worker = threading.Thread(
                target=self._run, name="vlm-veto-bureau", daemon=True
            )
            self._worker = worker
        worker.start()

    def close(self, timeout: float = 2.0) -> None:
        """Stop the worker. Tests and shutdown only."""

        with self._lock:
            self._stopping = True
            worker = self._worker
            self._worker = None
        if worker is None:
            return
        try:
            self._queue.put_nowait(None)
        except queue.Full:  # pragma: no cover - a full queue still drains
            pass
        worker.join(timeout=timeout)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            with self._lock:
                stopping = self._stopping
            if stopping:
                return
            query, place, revision, captured_at = item
            job_key = (query, place.place_id, revision)
            try:
                self._work(query, place, revision, captured_at)
            except Exception as exc:  # noqa: BLE001 - a worker that dies stops asking
                self._bump("worker_errors")
                logger.warning("vlm_veto bureau: job failed (%s)", exc)
            finally:
                with self._lock:
                    self._inflight.discard(job_key)

    def _work(
        self, query: str, place: PlaceEvidence, revision: str, captured_at: float
    ) -> None:
        answer = self._runner.veto_for(query, place)
        resolved_at = self._clock()
        unavailable = getattr(answer, "verdict", VETO_UNAVAILABLE) == VETO_UNAVAILABLE
        if unavailable:
            self._bump("declined")
        ttl = self._backoff_s if unavailable else self._ttl_s
        self.publish(
            PublishedVerdict(
                query=query,
                place_id=place.place_id,
                place_revision=revision,
                verdict=str(getattr(answer, "verdict", VETO_UNAVAILABLE)),
                model=str(getattr(answer, "model", "") or self.model),
                captured_at=captured_at,
                resolved_at=resolved_at,
                expires_at=resolved_at + ttl,
                p_yes=getattr(answer, "p_yes", None),
                latency_ms=float(getattr(answer, "latency_ms", 0.0)),
                detail=str(getattr(answer, "detail", "")),
            )
        )

    def publish(self, verdict: PublishedVerdict) -> None:
        """Put a verdict on the board. The worker's only write, and tests'."""

        key = (verdict.query, verdict.place_id)
        with self._lock:
            self._board.pop(key, None)
            self._board[key] = verdict
            while len(self._board) > self._board_depth:
                # Least recently USED, not first inserted — ``read`` re-inserts
                # a verdict it served, so this drops the pair nobody has asked
                # about for longest.
                self._board.pop(next(iter(self._board)))
            self._counts["published"] = self._counts.get("published", 0) + 1

    def lookup(self, query: str, place: PlaceEvidence) -> PublishedVerdict | None:
        """What the board holds for this pair, matched or not. Read-only."""

        with self._lock:
            return self._board.get((" ".join(str(query).split()), place.place_id))

    def drain(self, timeout: float = 10.0) -> bool:
        """Block until the worker has caught up. **Tests and benches only.**

        Never call this from navigation — the entire point of the bureau is that
        the mission path does not wait on a model. It is here because a
        measurement harness has to be able to say "now that the answers exist,
        ask again", and a harness that sleeps for a guessed interval is a
        harness that is flaky on a busy GPU.
        """

        if in_control_thread():
            raise RuntimeError("drain() is a test seam; the control loop may not wait")
        deadline = time.monotonic() + float(timeout)
        while time.monotonic() < deadline:
            with self._lock:
                idle = not self._inflight
            if idle and self._queue.empty():
                return True
            time.sleep(0.01)
        return False


# --------------------------------------------------------- the config seam ---
#
# ``perception_abstention.resolve_veto`` reaches exactly one function here, the
# way it reached exactly one function in ``runner`` before this card. One place
# where a model id becomes a running seat; one place where that seat becomes the
# thing navigation is allowed to call.

_BUREAUS_LOCK = threading.Lock()
_BUREAUS: dict[str, VerdictBureau] = {}


def bureau_for(model_id: str) -> VerdictBureau:
    """The bureau for the seat a config named, built once and cached.

    The seat itself is still built by :func:`~parcel_robot.vlm_veto.runner_for`
    — warmed at install, off any mission lease. This only wraps it in the worker
    and the board.
    """

    from parcel_robot.vlm_veto.runner import runner_for

    key = str(model_id or "").strip()
    with _BUREAUS_LOCK:
        existing = _BUREAUS.get(key)
        if existing is not None:
            return existing
    bureau = VerdictBureau(runner_for(key))
    with _BUREAUS_LOCK:
        return _BUREAUS.setdefault(key, bureau)


def clear_bureaus() -> None:
    """Drop every built bureau, stopping its worker. Tests only.

    Correction pass: this used to leave ``perception_abstention``'s own
    ``_VETO_RUNNERS`` cache holding a bound ``read`` of a bureau whose worker had
    just been stopped — so the next ``resolve_veto`` returned a reader for a dead
    worker, and the gate would have asked about every place forever while looking
    perfectly wired. That is one layer down from the exact defect P1-D's verifier
    caught (a callable that answers nothing), so it is cleared here rather than
    left for each caller to remember.
    """

    from parcel_robot.perception_abstention import clear_veto_cache

    with _BUREAUS_LOCK:
        bureaus = list(_BUREAUS.values())
        _BUREAUS.clear()
    for bureau in bureaus:
        bureau.close()
    clear_veto_cache()
